"""Validated execution boundary for all engineering tool implementations."""

from abc import ABC, abstractmethod
from copy import deepcopy
import re

from jsonschema.exceptions import SchemaError

from .exceptions import ToolDefinitionError, ToolValidationError
from .tool_result import ToolResult
from .validation import make_validator, reject, validate_json


class EngineeringTool(ABC):
    """Implement _execute; keep the public execute method as the shared boundary."""

    def __init__(self, *, name: str, version: str, description: str,
                 parameters_schema: dict, output_schema: dict):
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
            raise ToolDefinitionError("Tool name must match [a-z][a-z0-9_]*.")
        if any(not isinstance(text, str) or not text.strip() for text in (version, description)):
            raise ToolDefinitionError("Tool version and description must be non-empty strings.")
        self._name, self._version, self._description = name, version, description
        text_schema = {"type": "string", "minLength": 1, "pattern": r"\S"}
        try:
            for schema in (parameters_schema, output_schema):
                if not isinstance(schema, dict) or schema.get("type") != "object":
                    raise ToolDefinitionError("Parameters and output schemas must declare type: object.")
                make_validator(schema)
            parameters = deepcopy(parameters_schema)
            # Give the embedded schema its own resource so its local $defs/$ref
            # keep the same meaning after wrapping it in the input envelope.
            parameters.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
            parameters.setdefault("$id", f"urn:structagent:{name}:parameters")
            self._input_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object", "additionalProperties": False,
                "required": ["project_id", "tool", "context", "parameters"],
                "properties": {
                    "project_id": text_schema,
                    "tool": {"type": "string", "const": name},
                    "context": {
                        "type": "object", "required": ["unit_system", "design_code"],
                        "properties": {"unit_system": text_schema, "design_code": text_schema},
                    },
                    "parameters": parameters,
                },
            }
            self._output_schema = deepcopy(output_schema)
            self._input_validator = make_validator(self._input_schema)
            self._output_validator = make_validator(self._output_schema)
        except (SchemaError, ToolValidationError) as exc:
            raise ToolDefinitionError(f"Invalid tool schema: {exc}") from exc

    @property
    def name(self):
        return self._name

    @property
    def version(self):
        return self._version

    @property
    def description(self):
        return self._description

    @property
    def input_schema(self):
        return deepcopy(self._input_schema)

    @property
    def output_schema(self):
        return deepcopy(self._output_schema)

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "description": self.description,
                "input_schema": self.input_schema, "output_schema": self.output_schema}

    def validate(self, data: dict) -> None:
        """Raise ToolValidationError (a ValueError) before any tool work starts."""
        validate_json(data, self._input_validator)

    def execute(self, data: dict) -> ToolResult:
        try:
            self.validate(data)
        except ToolValidationError as exc:
            return ToolResult(False, self.name, self.version, errors=exc.errors)
        except Exception as exc:
            return ToolResult.failure(self.name, self.version, "validation_error", f"{type(exc).__name__}: {exc}")

        try:
            result = self._execute(deepcopy(data))
        except Exception as exc:
            return ToolResult.failure(self.name, self.version, "execution_error", f"{type(exc).__name__}: {exc}")

        try:
            if not isinstance(result, ToolResult):
                reject("Tool implementation must return ToolResult.")
            payload = result.to_dict()
            if result.tool != self.name or result.version != self.version:
                reject("Result tool/version does not match the executing tool.")
            if result.success:
                validate_json(payload["result"], self._output_validator, prefix=("result",))
            return ToolResult(**payload)
        except Exception as exc:
            errors = exc.errors if isinstance(exc, ToolValidationError) else [
                {"message": f"{type(exc).__name__}: {exc}", "path": []},
            ]
            return ToolResult(False, self.name, self.version, errors=[
                {**error, "code": "output_validation_error"} for error in errors
            ])

    @abstractmethod
    def _execute(self, data: dict) -> ToolResult:
        """Run validated input through an implementation or Adapter."""
