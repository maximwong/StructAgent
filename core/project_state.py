"""Durable tool execution history, independent of any engineering implementation."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

from .process_identity import process_identity
from .validation import ensure_json

STATES = {"RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", "RECOVERY_REQUIRED"}


class ProjectStateStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS executions (
                run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, tool TEXT NOT NULL,
                state TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_identity TEXT NOT NULL,
                updated REAL NOT NULL, metadata TEXT NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS executions_state ON executions(state)")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def begin(self, run_id, project_id, tool, metadata):
        if any(not isinstance(v, str) or not v.strip() for v in (run_id, project_id, tool)):
            raise ValueError("Execution identity is required.")
        ensure_json(metadata)
        with closing(self._connect()) as connection, connection:
            connection.execute("INSERT INTO executions VALUES (?,?,?,?,?,?,?,?)",
                (run_id, project_id, tool, "RUNNING", os.getpid(), process_identity(os.getpid()),
                 time.time(), json.dumps(metadata, ensure_ascii=False, allow_nan=False)))

    def update(self, run_id, state, metadata, *, expected=("RUNNING", "RECOVERY_REQUIRED", "INTERRUPTED")):
        if state not in STATES:
            raise ValueError("Unknown execution state.")
        ensure_json(metadata)
        with closing(self._connect()) as connection, connection:
            slots = ",".join("?" for _ in expected)
            changed = connection.execute(f"UPDATE executions SET state=?,metadata=?,updated=? WHERE run_id=? AND state IN ({slots})",
                (state, json.dumps(metadata, ensure_ascii=False, allow_nan=False), time.time(), run_id, *expected)).rowcount
            if changed != 1:
                raise ValueError("Execution state changed or is already final.")

    def get(self, run_id):
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM executions WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown execution run.")
        return {**dict(row), "metadata": json.loads(row["metadata"])}

    def list_runs(self, project_id=None, *, state=None):
        conditions, values = [], []
        if project_id is not None:
            conditions.append("project_id=?")
            values.append(project_id)
        if state is not None:
            if state not in STATES:
                raise ValueError("Unknown execution state.")
            conditions.append("state=?")
            values.append(state)
        with closing(self._connect()) as connection:
            query = "SELECT * FROM executions" + (" WHERE " + " AND ".join(conditions) if conditions else "")
            rows = connection.execute(query + " ORDER BY updated", values).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]

    def reconcile(self):
        """Mark dead/replaced owners; never turn a crashed call into successful CAD."""
        recovered = []
        for run in self.list_runs(state="RUNNING"):
            current = process_identity(run["owner_pid"])
            if current == "unknown" or current == run["owner_identity"]:
                continue
            metadata = {**run["metadata"], "interruption": "The original execution owner exited."}
            state = "RECOVERY_REQUIRED" if metadata.get("external_started") else "INTERRUPTED"
            try:
                self.update(run["run_id"], state, metadata, expected=("RUNNING",))
                recovered.append(run["run_id"])
            except ValueError:
                pass  # A live writer finalized this run during reconciliation.
        return recovered
