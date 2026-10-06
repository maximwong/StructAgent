"""Exclusive snapshots with project/reference/hash and recalculated semantics."""

from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

from core import ToolResult
from core.persistence import write_json
from core.validation import make_validator, validate_json
from .calculation import check_column, validate_model
from .json_data import canonical_hash, loads_json
from .materials import CANDIDATE_DIAMETERS_MM
from .schemas import DESIGN_OUTPUT_SCHEMA, DESIGN_REPORT_SCHEMA, REFERENCE_SCHEMA

_OUTPUT = make_validator(DESIGN_OUTPUT_SCHEMA)
_REPORT = make_validator(DESIGN_REPORT_SCHEMA)


class ColumnReferenceError(ValueError):
    """Intentionally safe public error; never echo storage paths or contents."""


def validate_design_semantics(report):
    """Verify actual schemes and minimal candidate prefix without selecting bars."""
    validate_json(report, _REPORT)
    model = report["effective_input"]
    validate_model(model)
    attempts = report["attempts"]
    first_pass = None
    for index, attempt in enumerate(attempts):
        expected_actual = {"bar_count": 4, "bar_diameter_mm": CANDIDATE_DIAMETERS_MM[index],
                           "layout": "four_corner_bars"}
        if attempt != check_column(model, expected_actual):
            raise ColumnReferenceError("Column result differs from actual-scheme recalculation.")
        if attempt["status"] == "PASS":
            if index != len(attempts) - 1:
                raise ColumnReferenceError("Column attempts continued after the first passing candidate.")
            first_pass = attempt
    if (report["selected"] != first_pass
            or report["status"] != ("PASS" if first_pass else "FAIL")
            or first_pass is None and len(attempts) != len(CANDIDATE_DIAMETERS_MM)
            or report["selection_policy"] != "first all-PASS diameter in [12,14,16,18,20,22,25,28]; all other user inputs fixed"):
        raise ColumnReferenceError("Column selection/status/candidate history is inconsistent.")


class ColumnDesignStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @staticmethod
    def _check(data, *, reference, project_id):
        result = ToolResult(**data)
        if (not result.success or result.tool != "design_column" or result.version != "1.0.0"
                or result.metadata.get("project_id") != project_id
                or result.result.get("design_result_ref") != reference
                or result.metadata.get("design_result_ref") != reference):
            raise ColumnReferenceError("A successful column design matching this project and reference is required.")
        validate_json(result.result, _OUTPUT)
        report = {key: deepcopy(value) for key, value in result.result.items() if key != "design_result_ref"}
        if (report["status"] != "PASS"
                or canonical_hash(report) != result.metadata.get("column_report_sha256")):
            raise ColumnReferenceError("Column report status or checksum is inconsistent.")
        validate_design_semantics(report)
        return result

    def save(self, result):
        """Publish only validated PASS; return the final result including its ref."""
        data = result.to_dict()
        project = data["metadata"].get("project_id")
        if not isinstance(project, str) or not project.strip():
            raise ColumnReferenceError("Column result requires project identity.")
        # The caller cannot inject or reuse a reference.
        validate_design_semantics(data["result"])
        ref = "column-" + uuid4().hex
        report_hash = canonical_hash(data["result"])
        data["result"]["design_result_ref"] = ref
        data["metadata"].update(design_result_ref=ref, column_report_sha256=report_hash)
        validated = self._check(data, reference=ref, project_id=project)
        payload = {"reference": ref, "design": data}
        payload["checksum"] = canonical_hash(payload)
        path = self.root / (ref + ".json")
        if path.resolve().parent != self.root or path.is_symlink():
            raise ColumnReferenceError("Column snapshot destination is redirected.")
        write_json(path, payload, exclusive=True)
        return validated

    def load(self, reference, *, project_id):
        if not isinstance(reference, str) or re.fullmatch(REFERENCE_SCHEMA["pattern"], reference) is None:
            raise ColumnReferenceError("Invalid column design reference.")
        path = self.root / (reference + ".json")
        try:
            if path.resolve().parent != self.root or path.is_symlink():
                raise ColumnReferenceError("Column snapshot destination is redirected.")
            payload = loads_json(path.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict) or set(payload) != {"reference", "checksum", "design"}
                    or payload["reference"] != reference
                    or canonical_hash({key: value for key, value in payload.items() if key != "checksum"}) != payload["checksum"]):
                raise ColumnReferenceError("Column snapshot identity or checksum mismatch.")
            return self._check(payload["design"], reference=reference, project_id=project_id)
        except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError):
            raise ColumnReferenceError("Cannot read a valid column design for this project and reference.") from None
