"""Windows process cleanup with a fake Harness; never calls the model service."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from devtools.dsh.bridge import git, read, save

FAKE_WORKER = r'''
import sys, types, threading, subprocess
from pathlib import Path
import config
config.load_settings=lambda path: types.SimpleNamespace(api_key="fixture-credential",base_url="https://api.deepseek.com")
class FakeHarness:
    def __init__(self, **kwargs): self.stop=threading.Event()
    def run(self, *args, **kwargs):
        child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
        Path(sys.argv[1],"descendant.pid").write_text(str(child.pid))
        self.stop.wait(60)
        return types.SimpleNamespace(finish_reason="completed",final_response="fake stopped",events=[])
    def close(self): self.stop.set()
sys.modules["deepseek_harness"]=types.SimpleNamespace(DeepSeekHarness=FakeHarness)
from devtools.dsh.worker import execute
_job=execute(Path(sys.argv[1]))
'''


@unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("win32job"), "Windows/pywin32 process test")
class DshLifecycleTests(unittest.TestCase):
    def exercise(self, cancel):
        import win32api
        import win32con
        import win32event
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "source"
            repo.mkdir()
            git(repo, "init", "--quiet")
            git(repo, "config", "user.name", "Fixture")
            git(repo, "config", "user.email", "fixture@example.invalid")
            (repo / "fixture.txt").write_text("unchanged\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "fixture")
            private = repo / ".dsh-tasks"
            private.mkdir()
            save(private / "config.json", {"dsh_bin": sys.executable})
            task_id = "a" * 32
            directory = private / task_id
            directory.mkdir()
            save(directory / "request.json", {"task_id": task_id, "task": "fixture", "allowed_paths": ["fixture.txt"],
                 "repo": str(repo), "base_commit": git(repo, "rev-parse", "HEAD").strip(), "max_tokens": 256,
                 "timeout_seconds": 30, "created_at": time.time() - (0 if cancel else 27)})
            proc = subprocess.Popen([sys.executable, "-c", FAKE_WORKER, str(directory)],
                                    cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 15
                while not (directory / "descendant.pid").exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((directory / "descendant.pid").exists(), "fake runtime did not start")
                pid = int((directory / "descendant.pid").read_text())
                handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
                if cancel:
                    (directory / "cancel").touch()
                stdout, stderr = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 0, stderr.decode(errors="replace"))
                self.assertEqual(read(directory / "state.json")["status"], "cancelled" if cancel else "timed_out")
                self.assertEqual(win32event.WaitForSingleObject(handle, 5000), win32event.WAIT_OBJECT_0,
                                 "owned child process survived worker exit")
                win32api.CloseHandle(handle)
                self.assertEqual((repo / "fixture.txt").read_text(), "unchanged\n")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=10)

    def test_cancel_reclaims_owned_descendant(self):
        self.exercise(True)

    def test_total_timeout_reclaims_owned_descendant(self):
        self.exercise(False)


if __name__ == "__main__":
    unittest.main()
