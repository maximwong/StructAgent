"""The registry-facing floor design tool; no CAD or report side effects."""

from copy import deepcopy

from core import EngineeringTool, ToolResult, ToolValidationError
from core.validation import make_validator, validate_json

from .design_adapter import FloorAdapterError, FloorDesignAdapter
from .schemas import CONTEXT_SCHEMA, OUTPUT_SCHEMA, PARAMETERS_SCHEMA


class FloorDesignTool(EngineeringTool):
    def __init__(self, adapter=None):
        super().__init__(
            name="design_floor_system", version="1.0.0",
            description="沿用现有教学模型完成板、次梁、主梁及配筋校核；显式模板或完整参数输入，单位mm/kN/MPa。",
            parameters_schema=PARAMETERS_SCHEMA, output_schema=OUTPUT_SCHEMA,
        )
        self._adapter = adapter if adapter is not None else FloorDesignAdapter()
        self._floor_validator = make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema = super().input_schema
        schema["properties"]["context"] = deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self, data):
        validate_json(data, self._floor_validator)

    def _execute(self, data):
        try:
            output = self._adapter.design(data["parameters"], project_id=data["project_id"])
        except ToolValidationError as exc:
            return ToolResult(False, self.name, self.version, errors=exc.errors)
        except FloorAdapterError as exc:
            return ToolResult.failure(self.name, self.version, exc.code, str(exc), exc.path)
        return ToolResult(True, self.name, self.version, **output)
