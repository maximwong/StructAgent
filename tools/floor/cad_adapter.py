"""CAD boundary: isolated runs, existing scene conversion, verified DWG only."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from core.persistence import write_json
from core.process_identity import process_identity
from core.project_state import ProjectStateStore

from .design_adapter import canonical_hash

_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent


class FloorCADError(Exception):
    def __init__(self, code, message, run_dir=None):
        super().__init__(message)
        self.code, self.run_dir = code, run_dir


class AutoCADBackend:
    """Connect to an idle desktop instance; never reuse a user's drawing."""

    def __init__(self, session_root=None):
        self.session_root = Path(session_root).resolve() if session_root is not None else _ROOT / "data/runtime/cad"

    def _command(self, run_dir, run_id, timeout, mode="Draw"):
        if os.name != "nt":
            raise FloorCADError("cad_unavailable", "Desktop CAD requires Windows and AutoCAD 2022.")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        return [str(powershell), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                   str(_HERE / "cad_bridge.ps1"), "-RunDirectory", str(run_dir),
                   "-RunId", run_id, "-SessionRoot", str(self.session_root),
                   "-Mode", mode, "-TimeoutSeconds", str(int(timeout))]

    def recover(self, run_dir, run_id):
        """Bounded ownership-checked recovery. A failed attempt keeps the quarantine."""
        try:
            write_json(Path(run_dir) / "cancel.request", {"run_id": run_id})
            with (Path(run_dir) / "recovery.log").open("ab") as log:
                process = subprocess.run(self._command(run_dir, run_id, 10, "Recover"),
                    stdout=log, stderr=subprocess.STDOUT, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
            journal = json.loads((self.session_root / (run_id + ".json")).read_text(encoding="utf-8-sig"))
            return process.returncode == 0 and journal.get("state") == "CLOSED"
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False

    def _quarantine(self, run_id):
        path = self.session_root / (run_id + ".json")
        journal = json.loads(path.read_text(encoding="utf-8-sig"))
        if journal["state"] != "CLOSED":
            journal["state"] = "RECOVERY_REQUIRED"
            write_json(path, journal)

    def recover_pending(self):
        recovery_deadline = time.monotonic() + 15
        self.session_root.mkdir(parents=True, exist_ok=True)
        for path in self.session_root.glob("*.json"):
            try:
                journal = json.loads(path.read_text(encoding="utf-8-sig"))
                if (journal.get("schema") != 1 or path.stem != journal.get("run_id")
                        or len(path.stem) != 32 or any(c not in "0123456789abcdef" for c in path.stem)):
                    raise ValueError("Invalid session identity")
                if journal["state"] == "CLOSED":
                    continue
                owner = process_identity(journal["owner_pid"])
                if journal["state"] != "RECOVERY_REQUIRED" and (owner == "unknown" or owner == journal["owner_identity"]):
                    raise FloorCADError("cad_busy", "Another CAD call owns an unfinished session.")
                run_dir = Path(journal["run_directory"])
                if time.monotonic() + 12 > recovery_deadline:
                    raise FloorCADError("cad_recovery_required", "Recovery batch time budget exhausted; resolve remaining sessions before drawing.")
                if not run_dir.is_absolute() or not run_dir.is_dir() or not self.recover(run_dir, path.stem):
                    raise FloorCADError("cad_recovery_required", "Previous owned CAD session could not be recovered. Inspect CAD before retrying.", str(run_dir))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise FloorCADError("cad_recovery_required", "CAD session journal is unreadable; recovery must be resolved first.") from exc

    def execute(self, run_dir: Path, run_id: str, timeout: float):
        command = self._command(run_dir, run_id, timeout)
        self.recover_pending()
        session_path = self.session_root / (run_id + ".json")
        write_json(session_path, {"schema": 1, "run_id": run_id, "run_directory": str(run_dir.resolve()),
                   "state": "RESERVED", "owner_pid": os.getpid(), "owner_identity": process_identity(os.getpid())}, exclusive=True)
        try:
            with (run_dir / "cad.log").open("xb") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                         timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            self._quarantine(run_id)
            recovered = self.recover(run_dir, run_id)
            raise FloorCADError("cad_timeout" if recovered else "cad_recovery_required",
                                "CAD timed out; its owned document was recovered." if recovered else
                                "CAD timed out; ownership-checked recovery is pending. Retry is blocked until resolved.") from exc
        except OSError as exc:
            journal = json.loads(session_path.read_text(encoding="utf-8-sig"))
            journal["state"] = "CLOSED"
            write_json(session_path, journal)
            raise FloorCADError("cad_start_failed", "The CAD bridge could not start.") from exc
        except KeyboardInterrupt:
            self._quarantine(run_id)
            self.recover(run_dir, run_id)
            raise
        try:
            receipt = json.loads((run_dir / "cad_receipt.json").read_text(encoding="utf-8-sig"))
            if receipt.get("run_id") != run_id:
                raise ValueError("Receipt belongs to another run")
            if receipt.get("state") != "SUCCESS":
                if receipt.get("owned_document_closed") is False:
                    self._quarantine(run_id)
                    if not self.recover(run_dir, run_id):
                        raise FloorCADError("cad_recovery_required", "CAD failed and its owned document still needs recovery.")
                raise FloorCADError(str(receipt.get("code", "cad_failed")),
                                    str(receipt.get("message", "CAD drawing failed.")))
            if process.returncode != 0:
                raise ValueError("CAD bridge did not exit successfully")
            return receipt
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self._quarantine(run_id)
            if not self.recover(run_dir, run_id):
                raise FloorCADError("cad_recovery_required", "CAD bridge exited without a valid receipt; ownership recovery is pending.") from exc
            raise FloorCADError("cad_receipt_invalid", "CAD did not return a valid completion receipt.") from exc


class FloorCADAdapter:
    def __init__(self, output_root, *, backend=None, timeout_seconds=240, state_store=None):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 10 <= timeout_seconds <= 900):
            raise ValueError("timeout_seconds must be between 10 and 900 seconds.")
        self.output_root = Path(output_root).resolve()
        self.backend = backend if backend is not None else AutoCADBackend()
        self.timeout_seconds = timeout_seconds
        self.state_store = state_store if state_store is not None else ProjectStateStore(self.output_root / "state.sqlite3")
        for run_id in self.state_store.reconcile():
            run = next(r for r in self.state_store.list_runs() if r["run_id"] == run_id)
            directory = Path(run["metadata"].get("run_directory", ""))
            if directory.parent == self.output_root and directory.name == run_id:
                write_json(directory / "run.json", {**run["metadata"], "state": run["state"]})

    def prepare(self, raw, run_dir):
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(_HERE / "_cad_scene_worker.py"), str(run_dir)],
                input=json.dumps(raw, ensure_ascii=False, allow_nan=False), capture_output=True,
                text=True, encoding="utf-8", timeout=60, cwd=str(_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            response = json.loads(proc.stdout)
            if proc.returncode or response.get("success") is not True:
                raise ValueError(response.get("error", "Scene worker failed"))
            scene = json.loads((run_dir / "drawing_scene.json").read_text(encoding="utf-8"))
            if scene["version"] != "RCFLOOR-SCENE-2":
                raise ValueError("Unsupported scene version")
            count = sum(len(rows) for rows in scene["groups"].values())
            if count <= 0 or response.get("entities") != count:
                raise ValueError("Scene entity count mismatch")
            return scene, count
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise FloorCADError("cad_conversion_failed", f"Cannot convert design to CAD data: {exc}") from exc

    def generate(self, design, *, reference):
        run_id = uuid4().hex
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest = {"run_id": run_id, "project_id": design.metadata["project_id"],
                    "design_result_ref": reference,
                    "design_sha256": design.metadata["legacy_result_sha256"], "state": "RUNNING",
                    "run_directory": str(run_dir)}
        self.state_store.begin(run_id, manifest["project_id"], "generate_floor_cad", manifest)
        def record():
            write_json(run_dir / "run.json", manifest)
        record()
        try:
            scene, count = self.prepare(design.result["legacy_result"], run_dir)
            manifest["scene_sha256"] = canonical_hash(scene)
            manifest["external_started"] = True
            record()
            self.state_store.update(run_id, "RUNNING", manifest)
            receipt = self.backend.execute(run_dir, run_id, self.timeout_seconds)
            dwg = run_dir / "floor.dwg"
            if (not isinstance(receipt, dict) or receipt.get("state") != "SUCCESS" or receipt.get("run_id") != run_id
                    or receipt.get("reopened") is not True
                    or type(receipt.get("entities")) is not int or receipt["entities"] != count
                    or receipt.get("scene_verified") is not True
                    or not dwg.is_file() or dwg.stat().st_size <= 0):
                raise FloorCADError("cad_receipt_invalid", "Drawing or verified completion receipt is missing/inconsistent.")
            manifest["state"] = "COMPLETED"
            record()
            self.state_store.update(run_id, "COMPLETED", manifest)
            warnings = list(design.warnings)
            if receipt.get("owned_document_closed") is False:
                warnings.append("DWG verification passed, but its CAD document remains open; close it manually when finished.")
            return {"result": {"drawing_status": "completed", "run_id": run_id,
                               "entities": count, "reopened": True},
                    "warnings": warnings,
                    "artifacts": [{"type": "dwg", "path": str(dwg)},
                                  {"type": "verification", "path": str(run_dir / "cad_receipt.json")}],
                    "metadata": {**manifest, "run_directory": str(run_dir)}}
        except FloorCADError as exc:
            manifest.update(state="RECOVERY_REQUIRED" if exc.code == "cad_recovery_required" else "FAILED",
                            error={"code": exc.code, "message": str(exc)})
            record()
            self.state_store.update(run_id, manifest["state"], manifest)
            exc.run_dir = str(run_dir)
            raise
        except Exception as exc:
            manifest.update(state="FAILED", error={"code": "cad_failed", "message": f"{type(exc).__name__}: {exc}"})
            record()
            self.state_store.update(run_id, "FAILED", manifest)
            raise FloorCADError("cad_failed", manifest["error"]["message"], str(run_dir)) from exc
        except KeyboardInterrupt:
            manifest.update(state="INTERRUPTED", error={"code": "interrupted", "message": "Cancelled by the caller."})
            record()
            self.state_store.update(run_id, "INTERRUPTED", manifest)
            raise
