"""Map floor inputs and invoke the unchanged continuous legacy calculation."""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from core.validation import ensure_json, make_validator, validate_json
from legacy.rc_floor.input_validation import CONCRETE_MATERIALS, validate_engineering_inputs

from .schemas import NONEMPTY, PARAMETERS_SCHEMA

_ROOT = Path(__file__).resolve().parents[2]
_WORKER = Path(__file__).with_name("_legacy_worker.py")
_TEMPLATE = Path(__file__).with_name("templates") / "office_floor_demo_v1.json"
_PARAMETERS_VALIDATOR = make_validator(PARAMETERS_SCHEMA)
_PROJECT_VALIDATOR = make_validator(NONEMPTY)


class FloorAdapterError(Exception):
    def __init__(self, code: str, message: str, path=()):
        super().__init__(message)
        self.code, self.path = code, list(path)


def canonical_hash(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FloorDesignAdapter:
    def __init__(self, *, timeout_seconds=30.0):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be a positive finite number.")
        self.timeout_seconds = timeout_seconds

    def prepare(self, parameters: dict, *, project_id: str) -> dict:
        validate_json(parameters, _PARAMETERS_VALIDATOR, prefix=("parameters",))
        validate_json(project_id, _PROJECT_VALIDATOR, prefix=("project_id",))
        if parameters["input_mode"] == "explicit":
            model = deepcopy(parameters["model"])
        else:
            try:
                model = json.loads(_TEMPLATE.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise FloorAdapterError("template_unavailable", "The packaged floor template cannot be read.") from exc
            model["project"] = project_id + " 办公楼"
            def millimetres(value):
                return int(value) if value == int(value) else value

            model["geometry"]["main_axis_spans_mm"] = [millimetres(parameters["span_x"])] * 3
            model["geometry"]["secondary_axis_spans_mm"] = [millimetres(parameters["span_y"])] * 5
            model["geometry"]["secondary_spacing_mm"] = millimetres(parameters["span_x"] / 3)
            # LLM JSON may spell an identical load as 2 or 2.0. Match the approved
            # template representation so legacy expression strings and hashes remain stable.
            model["loads"]["live_kN_m2"] = float(parameters["live_load"])
            grade = parameters["concrete"]
            fc, ft = CONCRETE_MATERIALS[grade]
            model["materials"].update(concrete=grade, fc_MPa=fc, ft_MPa=ft,
                                      beam_steel=parameters["steel"])
        try:
            validate_engineering_inputs(model)
        except ValueError as exc:
            path = ("parameters", "model") if parameters["input_mode"] == "explicit" else ("parameters",)
            raise FloorAdapterError("validation_error", str(exc), path) from exc
        return model

    def _calculate(self, model: dict) -> dict:
        try:
            process = subprocess.run(
                [sys.executable, "-I", str(_WORKER)],
                input=json.dumps(model, ensure_ascii=False, allow_nan=False),
                capture_output=True, text=True, encoding="utf-8", cwd=str(_ROOT),
                timeout=self.timeout_seconds,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise FloorAdapterError("design_timeout", "Floor calculation exceeded its time limit.") from exc
        except OSError as exc:
            raise FloorAdapterError("legacy_start_failed", "The floor calculation process could not start.") from exc
        except UnicodeError as exc:
            raise FloorAdapterError("legacy_protocol_error", "The floor calculation response is not UTF-8.") from exc
        if process.returncode != 0:
            raise FloorAdapterError("legacy_process_failed", f"Floor calculation exited with code {process.returncode}.")
        try:
            payload = json.loads(process.stdout)
            ensure_json(payload)
            if (type(payload) is not dict or type(payload.get("protocol")) is not int
                    or payload["protocol"] != 1 or type(payload.get("success")) is not bool):
                raise ValueError("Invalid worker envelope")
            if not payload["success"]:
                error = payload["error"]
                if (error["code"] not in ("design_rejected", "legacy_execution_error")
                        or not isinstance(error["message"], str) or not error["message"].strip()):
                    raise ValueError("Invalid worker error")
                raise FloorAdapterError(error["code"], error["message"], ("parameters",))
            result = payload["result"]
            if not isinstance(result, dict):
                raise ValueError("Invalid worker result")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise FloorAdapterError("legacy_protocol_error", "The floor calculation returned an invalid JSON response.") from exc

    def design(self, parameters: dict, *, project_id: str) -> dict:
        model = self.prepare(parameters, project_id=project_id)
        raw = self._calculate(model)
        try:
            result = {
                "slab": {"sections": raw["slab"], "distribution": raw["distribution"]},
                "secondary_beam": {"sections": raw["secondary"], "shear_checks": raw["secondary_shear"]},
                "main_beam": {"sections": raw["main"], "shear_checks": raw["main_shear"],
                              "hanger": raw["hanger"], "suspension": raw["suspension"]},
                "reinforcement": {"bars": raw["bars"]},
                "checks": {"joints": raw["joint_checks"], "material": raw["material_checks"]},
                "effective_input": raw["input"], "legacy_result": raw,
            }
            warnings = raw["warnings"]
        except (KeyError, TypeError) as exc:
            raise FloorAdapterError("legacy_protocol_error", "The floor calculation result is incomplete.") from exc
        return {
            "result": result, "warnings": warnings,
            "metadata": {
                "project_id": project_id, "input_mode": parameters["input_mode"],
                "template_id": parameters.get("template_id"),
                "legacy_result_sha256": canonical_hash(raw),
                "units": {"length": "mm", "force": "kN", "stress": "MPa", "area_load": "kN/m2"},
            },
        }
