"""Recover interrupted owned CAD sessions and reconcile project execution history."""

import argparse
import json
from pathlib import Path

from core.persistence import write_json
from tools.floor.cad_adapter import AutoCADBackend, FloorCADAdapter, FloorCADError


def main():
    parser = argparse.ArgumentParser(description="Recover owned CAD documents; never cancel a user's command.")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    args = parser.parse_args()
    backend = AutoCADBackend()
    adapter = FloorCADAdapter(args.output_root / "cad", backend=backend)
    try:
        backend.recover_pending()
        for run in adapter.state_store.list_runs():
            if run["state"] not in ("RECOVERY_REQUIRED", "INTERRUPTED"):
                continue
            session = backend.session_root / (run["run_id"] + ".json")
            closed = not run["metadata"].get("external_started")
            if session.is_file():
                closed = json.loads(session.read_text(encoding="utf-8-sig")).get("state") == "CLOSED"
            if closed:
                metadata = {**run["metadata"], "state": "FAILED", "recovery": "Interrupted execution recovered; rerun design/CAD explicitly."}
                adapter.state_store.update(run["run_id"], "FAILED", metadata)
                directory = Path(metadata["run_directory"])
                if directory.parent == adapter.output_root and directory.name == run["run_id"]:
                    write_json(directory / "run.json", metadata)
        print(json.dumps({"success": True, "runs": adapter.state_store.list_runs()}, ensure_ascii=True, indent=2))
        return 0
    except FloorCADError as exc:
        print(json.dumps({"success": False, "code": exc.code, "message": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
