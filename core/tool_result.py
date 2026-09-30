"""The result envelope shared by every engineering tool."""

from copy import deepcopy
from dataclasses import dataclass, field, fields

from .validation import make_validator, validate_json


_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_RESULT_SCHEMA = {
    "type": "object",
    "required": ["success", "tool", "version", "result", "warnings", "errors", "artifacts", "metadata"],
    "additionalProperties": False,
    "properties": {
        "success": {"type": "boolean"},
        "tool": _TEXT,
        "version": _TEXT,
        "result": {"type": "object"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "errors": {
            "type": "array", "items": {
                "type": "object", "required": ["code", "message", "path"],
                "additionalProperties": False,
                "properties": {
                    "code": _TEXT, "message": _TEXT,
                    "path": {"type": "array", "items": {"type": ["string", "integer"]}},
                },
            },
        },
        "artifacts": {
            "type": "array", "items": {
                "type": "object", "required": ["type", "path"],
                "properties": {"type": _TEXT, "path": _TEXT},
            },
        },
        "metadata": {"type": "object"},
    },
    "allOf": [{
        "if": {"properties": {"success": {"const": True}}},
        "then": {"properties": {"errors": {"maxItems": 0}}},
        "else": {"properties": {"errors": {"minItems": 1}}},
    }],
}
_VALIDATOR = make_validator(_RESULT_SCHEMA)


@dataclass(frozen=True)
class ToolResult:
    success: bool
    tool: str
    version: str
    result: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.to_dict()

    def to_dict(self) -> dict:
        data = {item.name: getattr(self, item.name) for item in fields(self)}
        validate_json(data, _VALIDATOR)
        return deepcopy(data)

    @classmethod
    def failure(cls, tool: str, version: str, code: str, message: str, path=()):
        return cls(False, tool, version, errors=[
            {"code": code, "message": message, "path": list(path)},
        ])
