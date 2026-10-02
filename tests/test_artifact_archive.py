import json
import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.state import AgentState
from core.artifact_archive import ArtifactArchive
from core.persistence import write_json
from core.project_state import ProjectStateStore


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="archive_中文_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        if os.name == "nt":
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetShortPathNameW(str(self.root), buffer, len(buffer)):
                self.root = Path(buffer.value)  # Exercise actual Windows aliases for both directories and receipts.
        self.state = AgentState(self.root / "agent")
        self.snapshot = self.state.begin("p")
        self.run_id = self.snapshot["run_id"]
        self.result_path = self.state.publish_result(self.run_id, "design", {"result": {"value": 7}})
        self.snapshot.update(steps={"design": "completed"}, status="completed", success=True,
            tool_calls=[{"step": "design", "tool": "some_plugin", "status": "completed", "result_path": self.result_path}])
        self.state.save(self.snapshot, "COMPLETED")
        self.archive = ArtifactArchive(self.root)
        self.reference = self.root / "design/immutable.json"
        write_json(self.reference, {"design": "keep"})

    def test_default_inventory_and_archive_preserve_sources(self):
        row = self.archive.inventory()[0]
        self.assertTrue(row["eligible"])
        self.assertGreater(row["bytes"], 0)
        result = self.archive.archive(self.run_id)
        self.assertFalse(result["compacted"])
        self.assertTrue(Path(self.result_path).exists())
        self.assertEqual(self.archive.verify(self.run_id)["files"][0]["path"], f"agent/{self.run_id}/design.json")
        with self.assertRaises(FileExistsError):
            self.archive.archive(self.run_id)

    def test_compact_restore_preserve_state_and_design_references(self):
        self.archive.archive(self.run_id, compact=True)
        self.assertFalse(Path(self.result_path).exists())
        snapshot = self.state.get(self.run_id)
        self.assertEqual(snapshot["persistence_state"], "COMPLETED")
        self.assertTrue(snapshot["artifact_archive"]["requires_restore"])
        self.assertTrue(self.reference.exists())
        self.archive.restore(self.run_id)
        self.assertEqual(json.loads(Path(self.result_path).read_text())["result"], {"value": 7})
        self.assertFalse(self.state.get(self.run_id)["artifact_archive"]["requires_restore"])
        self.assertTrue(self.archive.restore(self.run_id)["restored"])

    def test_restore_refuses_overwriting_and_corruption(self):
        self.archive.archive(self.run_id, compact=True)
        Path(self.result_path).write_text("new user data")
        with self.assertRaises(FileExistsError):
            self.archive.restore(self.run_id)
        self.assertEqual(Path(self.result_path).read_text(), "new user data")
        archive = self.root / "archives" / (self.run_id + ".zip")
        archive.write_bytes(archive.read_bytes() + b"corrupt")
        with self.assertRaises(ValueError):
            self.archive.verify(self.run_id)

    def test_running_and_recovery_required_are_never_archived(self):
        for state in ("RUNNING", "RECOVERY_REQUIRED"):
            snapshot = self.state.begin("p")
            if state != "RUNNING":
                self.state.save(snapshot, state)
            with self.assertRaises(ValueError):
                self.archive.archive(snapshot["run_id"], compact=True)
        self.assertFalse((self.root / "archives").exists())

    def test_path_escape_links_and_unowned_result_paths_are_rejected(self):
        for path in ("../user.txt", "/user.txt", "agent/../state.sqlite3", "agent\\file", "C:/user.txt"):
            with self.assertRaises(ValueError):
                self.archive._path(path)
        with patch.object(self.archive.state, "get", return_value={
                **self.state.store.get(self.run_id), "metadata": {**self.snapshot, "tool_calls": [
                    {"step": "design", "result_path": str(self.reference)}]}}):
            with self.assertRaises(ValueError):
                self.archive.archive(self.run_id)

    def test_source_change_after_archive_verification_prevents_compaction(self):
        original_verify = self.archive.verify
        def change(run_id):
            result = original_verify(run_id)
            Path(self.result_path).write_text("changed")
            return result
        with patch.object(self.archive, "verify", side_effect=change), self.assertRaises(ValueError):
            self.archive.archive(self.run_id, compact=True)
        self.assertEqual(Path(self.result_path).read_text(), "changed")

    def test_external_tool_requires_terminal_owner_and_closed_receipt(self):
        tool_id = "a" * 32
        directory = self.root / "plugin" / tool_id
        directory.mkdir(parents=True)
        metadata = {"run_id": tool_id, "run_directory": str(directory), "external_started": True}
        tool_store = ProjectStateStore(directory.parent / "state.sqlite3")
        tool_store.begin(tool_id, "p", "some_plugin", metadata)
        tool_store.update(tool_id, "COMPLETED", metadata)
        receipt = directory / "receipt.json"
        write_json(receipt, {"run_id": tool_id, "owned_document_closed": False})
        write_json(Path(self.result_path), {"metadata": metadata, "artifacts": [{"type": "verification", "path": str(receipt)}]})
        with self.assertRaises(ValueError):
            self.archive.archive(self.run_id)
        write_json(receipt, {"run_id": tool_id, "owned_document_closed": True})
        (directory / "floor.dwg").write_bytes(b"test fixture only")
        self.assertEqual(self.archive.archive(self.run_id, compact=True)["files"], 3)
        self.archive.restore(self.run_id)
        self.assertEqual((directory / "floor.dwg").read_bytes(), b"test fixture only")


if __name__ == "__main__":
    unittest.main()
