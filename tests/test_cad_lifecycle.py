import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.persistence import write_json
from core.process_identity import process_identity
from tools.floor.cad_adapter import AutoCADBackend, FloorCADError


@unittest.skipUnless(os.name == "nt", "Windows CAD lifecycle boundary")
class CADLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run";self.run.mkdir()
        self.backend = AutoCADBackend(self.root / "sessions")
        self.rid = "a" * 32

    def reserve(self, *, state="ACTIVE", identity=None):
        write_json(self.backend.session_root / (self.rid + ".json"), {
            "schema": 1, "run_id": self.rid, "run_directory": str(self.run), "state": state,
            "owner_pid": os.getpid(), "owner_identity": identity or process_identity(os.getpid())})

    def test_live_owner_blocks_a_second_cad_call_without_launching_bridge(self):
        self.reserve()
        with patch("tools.floor.cad_adapter.subprocess.run") as launch:
            with self.assertRaises(FloorCADError) as error:
                self.backend.recover_pending()
        self.assertEqual(error.exception.code, "cad_busy")
        launch.assert_not_called()

    def test_interrupted_owner_is_recovered_before_new_work(self):
        self.reserve(identity="old-process")
        with patch.object(self.backend, "recover", return_value=True) as recover:
            self.backend.recover_pending()
        recover.assert_called_once_with(self.run, self.rid)

    def test_failed_recovery_remains_quarantined_and_blocks_retry(self):
        self.reserve(state="RECOVERY_REQUIRED")
        with patch.object(self.backend, "recover", return_value=False):
            with self.assertRaises(FloorCADError) as error:
                self.backend.recover_pending()
        self.assertEqual(error.exception.code, "cad_recovery_required")
        self.assertNotEqual(json.loads((self.backend.session_root / (self.rid + ".json")).read_text())["state"], "CLOSED")

    def test_closed_sessions_are_not_recovered_again(self):
        self.reserve(state="CLOSED")
        with patch.object(self.backend, "recover") as recover:
            self.backend.recover_pending()
        recover.assert_not_called()

    def test_multiple_pending_sessions_cannot_extend_recovery_without_limit(self):
        self.reserve(identity="old-process")
        self.rid = "b" * 32
        self.reserve(identity="old-process")
        with patch("tools.floor.cad_adapter.time.monotonic", side_effect=[0, 1, 5]), \
             patch.object(self.backend, "recover", return_value=True) as recover:
            with self.assertRaises(FloorCADError) as error:
                self.backend.recover_pending()
        self.assertEqual(error.exception.code, "cad_recovery_required")
        self.assertEqual(recover.call_count, 1)

    def test_corrupt_or_mismatched_journal_is_never_used_as_a_recovery_target(self):
        self.backend.session_root.mkdir()
        path = self.backend.session_root / (self.rid + ".json")
        for data in ("not JSON", '{"schema":1,"run_id":"another"}'):
            path.write_text(data)
            with patch.object(self.backend, "recover") as recover:
                with self.assertRaises(FloorCADError):
                    self.backend.recover_pending()
                recover.assert_not_called()

    def test_timeout_requests_recovery_and_never_returns_a_success_receipt(self):
        with patch("tools.floor.cad_adapter.subprocess.run", side_effect=subprocess.TimeoutExpired("bridge", 10)), \
             patch.object(self.backend, "recover", return_value=True) as recover:
            with self.assertRaises(FloorCADError) as error:
                self.backend.execute(self.run, self.rid, 10)
        self.assertEqual(error.exception.code, "cad_timeout")
        recover.assert_called_once_with(self.run, self.rid)

    def test_timeout_with_unresponsive_cad_reports_pending_recovery(self):
        with patch("tools.floor.cad_adapter.subprocess.run", side_effect=subprocess.TimeoutExpired("bridge", 10)), \
             patch.object(self.backend, "recover", return_value=False):
            with self.assertRaises(FloorCADError) as error:
                self.backend.execute(self.run, self.rid, 10)
        self.assertEqual(error.exception.code, "cad_recovery_required")
        self.assertEqual(json.loads((self.backend.session_root / (self.rid + ".json")).read_text())["state"], "RECOVERY_REQUIRED")

    def test_recovery_requires_closed_journal_and_a_successful_process_exit(self):
        self.reserve(state="RECOVERY_REQUIRED")
        def bridge(*args, **kwargs):
            journal = json.loads((self.backend.session_root / (self.rid + ".json")).read_text())
            journal["state"] = "CLOSED"
            write_json(self.backend.session_root / (self.rid + ".json"), journal)
            return SimpleNamespace(returncode=0)
        with patch("tools.floor.cad_adapter.subprocess.run", side_effect=bridge):
            self.assertTrue(self.backend.recover(self.run, self.rid))
        self.assertTrue((self.run / "cancel.request").is_file())

    def test_powershell_atomic_writer_replaces_an_existing_unicode_snapshot(self):
        bridge = Path(__file__).resolve().parents[1] / "tools/floor/cad_bridge.ps1"
        script = self.root / "check.ps1"
        script.write_text("""param($source,$target)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Write-AtomicJson'},$true)
Invoke-Expression $function.Extent.Text
Write-AtomicJson $target @{state='old'}
Write-AtomicJson $target @{state='新状态'}
Get-Content -LiteralPath $target -Raw -Encoding UTF8
""", encoding="utf-8-sig")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        response = subprocess.run([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                   str(bridge), str(self.root / "状态.json")], capture_output=True, timeout=15)
        self.assertEqual(response.returncode, 0, response.stderr.decode(errors="replace"))
        self.assertEqual(json.loads((self.root / "状态.json").read_text(encoding="utf-8")), {"state": "新状态"})

    def test_recovery_does_not_stop_an_unrelated_powershell_process(self):
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        helper = subprocess.Popen([str(powershell), "-NoProfile", "-Command", "Start-Sleep -Seconds 30"],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.reserve(state="RECOVERY_REQUIRED")
            path = self.backend.session_root / (self.rid + ".json")
            journal = json.loads(path.read_text())
            journal.update(bridge_pid=helper.pid, bridge_start=int(process_identity(helper.pid)) + 504911232000000000)
            write_json(path, journal)
            self.assertFalse(self.backend.recover(self.run, self.rid))
            self.assertIsNone(helper.poll())
            self.assertEqual(json.loads(path.read_text())["state"], "RECOVERY_REQUIRED")
            receipt = json.loads((self.run / "recovery_receipt.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(receipt["code"], "cad_recovery_required")
            self.assertIn("ownership", receipt["message"])
        finally:
            helper.kill()
            helper.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
