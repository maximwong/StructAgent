"""Local, immutable design snapshots addressed by opaque references."""

import json
from pathlib import Path
import re
from uuid import uuid4

from core import ToolResult
from core.validation import make_validator, validate_json
from .design_adapter import canonical_hash
from .schemas import OUTPUT_SCHEMA

_OUTPUT = make_validator(OUTPUT_SCHEMA)
REFERENCE = {"type": "string", "pattern": r"^floor-[0-9a-f]{32}$"}


class DesignReferenceError(ValueError):
    pass


class FloorDesignStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @staticmethod
    def _check(data, project_id):
        result = ToolResult(**data)
        if (not result.success or result.tool != "design_floor_system" or result.version != "1.0.0"
                or result.metadata.get("project_id") != project_id):
            raise DesignReferenceError("A successful floor design for this project is required.")
        validate_json(result.result, _OUTPUT)
        if canonical_hash(result.result["legacy_result"]) != result.metadata.get("legacy_result_sha256"):
            raise DesignReferenceError("Design snapshot checksum differs from the calculation result.")
        if result.result["legacy_result"]["input"] != result.result["effective_input"]:
            raise DesignReferenceError("Design snapshot input is inconsistent.")
        return result

    def save(self, result: ToolResult) -> str:
        data = result.to_dict()
        project = result.metadata.get("project_id")
        if not isinstance(project, str) or not project.strip():
            raise DesignReferenceError("Design snapshot has no project identity.")
        self._check(data, project)
        ref = "floor-" + uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: references are never reused or overwritten.
        with (self.root / (ref + ".json")).open("x", encoding="utf-8") as stream:
            json.dump({"checksum": canonical_hash(data), "design": data}, stream,
                      ensure_ascii=False, allow_nan=False)
        return ref

    def load(self, reference: str, *, project_id: str) -> ToolResult:
        if not isinstance(reference, str) or re.fullmatch(REFERENCE["pattern"], reference) is None:
            raise DesignReferenceError("Invalid design result reference.")
        path = self.root / (reference + ".json")
        if path.resolve().parent != self.root:
            raise DesignReferenceError("Design reference resolves outside its store.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if canonical_hash(payload["design"]) != payload["checksum"]:
                raise DesignReferenceError("Stored design checksum mismatch.")
            return self._check(payload["design"], project_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DesignReferenceError(f"Cannot read a valid design reference: {exc}") from exc
