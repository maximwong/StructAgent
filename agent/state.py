"""Workflow snapshots backed by the existing transaction and process-identity store."""

from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

from core.persistence import write_json
from core.project_state import ProjectStateStore


class AgentState:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = ProjectStateStore(self.root / "state.sqlite3")
        self.store.reconcile()

    def begin(self, project_id):
        run_id = uuid4().hex
        snapshot = {"run_id": run_id, "project_id": project_id, "success": False,
                    "status": "running", "workflow": None, "current_task": "parse",
                    "steps": {"parse": "running"}, "tool_calls": [], "errors": [],
                    "warnings": [], "artifacts": [], "events": [], "external_started": False}
        self.store.begin(run_id, project_id, "engineering_agent", snapshot)
        return snapshot

    def save(self, snapshot, state="RUNNING"):
        self.store.update(snapshot["run_id"], state, snapshot, expected=("RUNNING",))

    def publish_result(self, run_id, step, result):
        if (not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
                or not isinstance(step, str) or re.fullmatch(r"[a-z][a-z0-9_]*", step) is None):
            raise ValueError("Invalid workflow result identity.")
        path = self.root / run_id / (step + ".json")
        write_json(path, result, exclusive=True)
        return str(path)

    def get(self, run_id):
        self.store.reconcile()
        record = self.store.get(run_id)
        snapshot = deepcopy(record["metadata"])
        snapshot["persistence_state"] = record["state"]
        archive = self.root.parent / "archives" / (run_id + ".zip")
        if archive.is_file() and archive.with_suffix(".json").is_file():
            snapshot["artifact_archive"] = {"path": str(archive), "requires_restore": any(
                not Path(c["result_path"]).is_file() for c in snapshot["tool_calls"] if c.get("result_path"))}
        if record["state"] in ("INTERRUPTED", "RECOVERY_REQUIRED"):
            snapshot.update(success=False, status=record["state"].lower())
            snapshot["steps"] = {k: "interrupted" if v == "running" else "skipped" if v == "pending" else v
                                 for k, v in snapshot["steps"].items()}
            for call in snapshot["tool_calls"]:
                if call["status"] == "running":
                    call["status"] = "interrupted"
            if record["metadata"].get("interruption"):
                snapshot["errors"].append({"code": "owner_exited", "path": [],
                                           "message": "The original workflow process exited; no steps were replayed."})
        return snapshot
