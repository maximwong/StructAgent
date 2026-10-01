from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.persistence import write_json
from core.process_identity import process_identity
from core.project_state import ProjectStateStore


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_atomic_replacement_failure_keeps_previous_complete_snapshot(self):
        path = self.root / "state.json"
        write_json(path, {"state": "old"})
        with patch("core.persistence.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                write_json(path, {"state": "new"})
        self.assertEqual(json.loads(path.read_text()), {"state": "old"})
        self.assertEqual(list(self.root.glob(".pending-*")), [])

    def test_immutable_publication_never_overwrites_existing_reference(self):
        path = self.root / "snapshot.json"
        write_json(path, {"version": 1}, exclusive=True)
        with self.assertRaises(FileExistsError):
            write_json(path, {"version": 2}, exclusive=True)
        self.assertEqual(json.loads(path.read_text()), {"version": 1})

    def test_invalid_json_is_rejected_before_existing_file_changes(self):
        path = self.root / "snapshot.json"
        write_json(path, {"number": 1})
        with self.assertRaises(ValueError):
            write_json(path, {"number": float("nan")})
        self.assertEqual(json.loads(path.read_text()), {"number": 1})

    def test_project_history_is_durable_and_final_states_cannot_be_overwritten(self):
        path = self.root / "state.sqlite3"
        store = ProjectStateStore(path)
        store.begin("one", "project-a", "some_plugin", {"step": "design"})
        store.update("one", "COMPLETED", {"artifact": "ok"})
        loaded = ProjectStateStore(path).list_runs("project-a")
        self.assertEqual(loaded[0]["state"], "COMPLETED")
        self.assertEqual(loaded[0]["metadata"], {"artifact": "ok"})
        self.assertEqual(store.list_runs("another"), [])
        with self.assertRaises(ValueError):
            store.update("one", "FAILED", {})
        with self.assertRaises(sqlite3.IntegrityError):
            store.begin("one", "project-a", "some_plugin", {})

    def test_parallel_plugin_records_keep_their_own_results(self):
        store = ProjectStateStore(self.root / "state.sqlite3")
        def run(index):
            store.begin(str(index), "project", "plugin_" + str(index), {})
            store.update(str(index), "COMPLETED", {"index": index})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, range(12)))
        self.assertEqual({r["metadata"]["index"] for r in store.list_runs()}, set(range(12)))

    def test_live_and_unknown_owners_are_not_reconciled_as_dead(self):
        store = ProjectStateStore(self.root / "state.sqlite3")
        store.begin("live", "project", "plugin", {})
        self.assertEqual(store.reconcile(), [])
        with patch("core.project_state.process_identity", return_value="unknown"):
            self.assertEqual(store.reconcile(), [])

    def test_reused_pid_is_treated_as_an_interrupted_original_owner(self):
        store = ProjectStateStore(self.root / "state.sqlite3")
        store.begin("reused", "project", "plugin", {"external_started": True})
        with patch("core.project_state.process_identity", return_value="different-process-creation-time"):
            self.assertEqual(store.reconcile(), ["reused"])
        self.assertEqual(store.list_runs()[0]["state"], "RECOVERY_REQUIRED")

    def test_real_process_crash_is_reconciled_without_claiming_success(self):
        database = self.root / "crash.sqlite3"
        code = "from core.project_state import ProjectStateStore; import sys,os; s=ProjectStateStore(sys.argv[1]); s.begin('crash','project','plugin',{'external_started':True}); os._exit(9)"
        process = subprocess.run([sys.executable, "-c", code, str(database)], cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(process.returncode, 9)
        store = ProjectStateStore(database)
        self.assertEqual(store.reconcile(), ["crash"])
        self.assertEqual(store.list_runs()[0]["state"], "RECOVERY_REQUIRED")

    def test_process_identity_is_an_incarnation_token(self):
        identity = process_identity(os.getpid())
        self.assertNotIn(identity, ("unknown", "missing"))
        self.assertEqual(identity, process_identity(os.getpid()))
        self.assertEqual(process_identity(-1), "missing")


if __name__ == "__main__":
    unittest.main()
