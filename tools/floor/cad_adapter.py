"""CAD boundary: isolated runs, existing scene conversion, verified DWG only."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from .design_adapter import canonical_hash

_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent


class FloorCADError(Exception):
    def __init__(self, code, message, run_dir=None):
        super().__init__(message)
        self.code, self.run_dir = code, run_dir


class AutoCADBackend:
    """Connect to an idle desktop instance; never reuse a user's drawing."""

    def execute(self, run_dir: Path, run_id: str, timeout: float):
        if os.name != "nt":
            raise FloorCADError("cad_unavailable", "Desktop CAD requires Windows and AutoCAD 2022.")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(powershell), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                   str(_HERE / "cad_bridge.ps1"), "-RunDirectory", str(run_dir),
                   "-RunId", run_id, "-TimeoutSeconds", str(int(timeout))]
        try:
            with (run_dir / "cad.log").open("xb") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                         timeout=timeout + 45, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            # Kill only our bridge (subprocess.run does this), never AutoCAD/user processes.
            raise FloorCADError("cad_timeout", "CAD bridge timed out. Inspect the retained CAD document before retrying.") from exc
        except OSError as exc:
            raise FloorCADError("cad_start_failed", "The CAD bridge could not start.") from exc
        try:
            receipt = json.loads((run_dir / "cad_receipt.json").read_text(encoding="utf-8-sig"))
            if receipt.get("run_id") != run_id:
                raise ValueError("Receipt belongs to another run")
            if receipt.get("state") != "SUCCESS":
                raise FloorCADError(str(receipt.get("code", "cad_failed")),
                                    str(receipt.get("message", "CAD drawing failed.")))
            if process.returncode != 0:
                raise ValueError("CAD bridge did not exit successfully")
            return receipt
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise FloorCADError("cad_receipt_invalid", "CAD did not return a valid completion receipt.") from exc


class FloorCADAdapter:
    def __init__(self, output_root, *, backend=None, timeout_seconds=240):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 10 <= timeout_seconds <= 900):
            raise ValueError("timeout_seconds must be between 10 and 900 seconds.")
        self.output_root = Path(output_root).resolve()
        self.backend = backend if backend is not None else AutoCADBackend()
        self.timeout_seconds = timeout_seconds

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
                    "design_sha256": design.metadata["legacy_result_sha256"], "state": "RUNNING"}
        def record():
            (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        record()
        try:
            scene, count = self.prepare(design.result["legacy_result"], run_dir)
            manifest["scene_sha256"] = canonical_hash(scene)
            record()
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
            manifest.update(state="FAILED", error={"code": exc.code, "message": str(exc)})
            record()
            exc.run_dir = str(run_dir)
            raise
        except Exception as exc:
            manifest.update(state="FAILED", error={"code": "cad_failed", "message": f"{type(exc).__name__}: {exc}"})
            record()
            raise FloorCADError("cad_failed", manifest["error"]["message"], str(run_dir)) from exc
