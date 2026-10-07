"""Offline tests for optional developer tooling; no Harness, key or model call."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from devtools.dsh.bridge import Jobs, allowed, collect, git, read, save, validate
from devtools.dsh.server import TOOLS, handle
from devtools.dsh.worker import redact


class DshBridgeTests(unittest.TestCase):
    def test_task_contract_rejects_private_and_escaping_paths(self):
        for path in ("../outside", "C:/secret", "/root", ".env", ".env.production", ".git/config",
                     "sources/a.py", "tests/../a.py", "tests//a.py", "tests\\a.py", ".venv-demo/x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate("test", [path], 300, 4096)

    def test_limits_reject_boolean_numbers(self):
        for timeout, tokens in ((True, 4096), (300, False), (29, 4096), (901, 4096), (300, 8193)):
            with self.subTest(timeout=timeout, tokens=tokens), self.assertRaises(ValueError):
                validate("test", ["tests/test_a.py"], timeout, tokens)

    def test_valid_contract(self):
        validate("Implement focused tests", ["tests/test_a.py", "docs/"], 300, 4096)

    def test_redaction(self):
        key = "test-credential-0123456789"
        value = redact(key + " sk-" + "a" * 30, key)
        self.assertNotIn(key, value)
        self.assertEqual(value.count("[REDACTED]"), 2)

    def test_invalid_task_ids_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(root=tmp)
            for value in ("../x", "", "A" * 32, "a" * 31):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    jobs.get(value)

    def test_cancel_is_a_request_and_preserves_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(root=tmp)
            task_id = "a" * 32
            directory = Path(tmp) / task_id
            directory.mkdir()
            save(directory / "request.json", {"created_at": time.time(), "timeout_seconds": 300, "base_commit": "abc"})
            save(directory / "state.json", {"task_id": task_id, "status": "running"})
            self.assertTrue(jobs.cancel(task_id)["cancellation_requested"])
            self.assertEqual(read(directory / "state.json")["status"], "running")
            self.assertTrue((directory / "cancel").exists())
            save(directory / "state.json", {"task_id": task_id, "status": "completed"})
            self.assertEqual(jobs.cancel(task_id)["status"], "completed")

    def test_expired_unfinished_record_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(root=tmp)
            task_id = "a" * 32
            directory = Path(tmp) / task_id
            directory.mkdir()
            save(directory / "request.json", {"created_at": 0, "timeout_seconds": 30, "base_commit": "abc"})
            save(directory / "state.json", {"task_id": task_id, "status": "running"})
            self.assertEqual(jobs.get(task_id)["status"], "interrupted")

    def test_mcp_inventory_and_invalid_tool_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(root=tmp)
            inventory = handle({"method": "tools/list"}, jobs)
            self.assertEqual(len(inventory["tools"]), 3)
            self.assertEqual({t["name"] for t in TOOLS}, {"start_deepseek_task", "get_deepseek_task", "cancel_deepseek_task"})
            result = handle({"method": "tools/call", "params": {"name": "start_deepseek_task", "arguments": {"task": "x", "allowed_paths": ["../x"]}}}, jobs)
            self.assertTrue(result["isError"])

    def test_mcp_stdio_roundtrip(self):
        server = Path(__file__).resolve().parents[1] / "devtools/dsh/server.py"
        messages = ["{invalid json}", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})]
        import sys
        result = subprocess.run([sys.executable, str(server)], input="\n".join(messages) + "\n", capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertIn("error", responses[0])
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(len(responses[2]["result"]["tools"]), 3)

    def test_diff_includes_new_files_and_detects_out_of_scope_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "--quiet")
            git(repo, "config", "user.name", "Fixture")
            git(repo, "config", "user.email", "fixture@example.invalid")
            (repo / "existing.txt").write_text("before\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "baseline")
            base = git(repo, "rev-parse", "HEAD").strip()
            (repo / "existing.txt").write_text("after\n", encoding="utf-8")
            (repo / "new.txt").write_text("new\n", encoding="utf-8")
            result = collect(repo, base, ["new.txt"])
            self.assertEqual(result["scope_violations"], ["existing.txt"])
            self.assertEqual(set(result["changed_files"]), {"existing.txt", "new.txt"})
            self.assertIn("+after", result["diff"])
            self.assertIn("+new", result["diff"])


if __name__ == "__main__":
    unittest.main()
