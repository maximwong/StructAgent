"""Versioned layout snapshots, separate from legacy single-layout refs."""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

from core import ToolResult
from core.persistence import write_json
from core.validation import make_validator, validate_json
from .layout_calculation import DESIGN_OUTPUT, REFERENCE_SCHEMA, validate_design_semantics
from .json_data import canonical_hash, loads_json


class ColumnLayoutReferenceError(ValueError):
    pass


class ColumnLayoutStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _check(self, data, *, reference, project_id):
        result = ToolResult(**data)
        if (not result.success or result.tool != "design_column_layouts" or result.version != "1.0.0"
                or result.metadata.get("project_id") != project_id
                or result.result.get("design_result_ref") != reference
                or result.metadata.get("design_result_ref") != reference):
            raise ColumnLayoutReferenceError("Successful layout design identity required")
        validate_json(result.result, make_validator(DESIGN_OUTPUT))
        report = {key: deepcopy(value) for key, value in result.result.items() if key != "design_result_ref"}
        if report["status"] != "PASS" or canonical_hash(report) != result.metadata.get("column_layout_sha256"):
            raise ColumnLayoutReferenceError("Layout status or report hash mismatch")
        validate_design_semantics(report)
        return result

    def save(self, result):
        data = result.to_dict()
        project = data["metadata"].get("project_id")
        if not isinstance(project, str) or not project.strip():
            raise ColumnLayoutReferenceError("Project identity required")
        validate_design_semantics(data["result"])
        reference = "column-layout-" + uuid4().hex
        checksum = canonical_hash(data["result"])
        data["result"]["design_result_ref"] = reference
        data["metadata"].update(design_result_ref=reference, column_layout_sha256=checksum)
        validated = self._check(data, reference=reference, project_id=project)
        payload = {"reference": reference, "design": data}
        payload["checksum"] = canonical_hash(payload)
        path = self.root / (reference + ".json")
        if path.resolve().parent != self.root or path.is_symlink():
            raise ColumnLayoutReferenceError("Redirected layout snapshot")
        write_json(path, payload, exclusive=True)
        return validated

    def load(self, reference, *, project_id):
        if not isinstance(reference, str) or re.fullmatch(REFERENCE_SCHEMA["pattern"], reference) is None:
            raise ColumnLayoutReferenceError("Invalid layout reference")
        path = self.root / (reference + ".json")
        try:
            if path.resolve().parent != self.root or path.is_symlink():
                raise ColumnLayoutReferenceError("Redirected layout snapshot")
            payload = loads_json(path.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict) or set(payload) != {"reference", "design", "checksum"}
                    or payload["reference"] != reference
                    or canonical_hash({k: v for k, v in payload.items() if k != "checksum"}) != payload["checksum"]):
                raise ColumnLayoutReferenceError("Layout snapshot checksum or identity mismatch")
            return self._check(payload["design"], reference=reference, project_id=project_id)
        except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError):
            raise ColumnLayoutReferenceError("Cannot read valid layout design for project and reference") from None
