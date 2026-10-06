"""Registry-facing fixed-input column design and mandatory snapshot publication."""

from copy import deepcopy

from core import EngineeringTool, ToolResult, ToolValidationError
from core.validation import make_validator, validate_json
from .calculation import validate_model
from .design_adapter import ColumnDesignAdapter
from .design_store import validate_design_semantics
from .schemas import CONTEXT_SCHEMA, DESIGN_OUTPUT_SCHEMA, DESIGN_PARAMETERS

WARNING = "教学非抗震静力理想轴压；PASS仅覆盖声明项目，未代替工程全项审查。phi包含轴压稳定影响。"


class ColumnDesignTool(EngineeringTool):
    def __init__(self, store, adapter=None):
        super().__init__(name="design_column", version="1.0.0",
                         description="按用户固定矩形截面设计教学非抗震静力理想轴压柱；四角筋，显式mm/kN/kN.m/MPa及规范声明。",
                         parameters_schema=DESIGN_PARAMETERS, output_schema=DESIGN_OUTPUT_SCHEMA)
        self.store = store
        self.adapter = adapter if adapter is not None else ColumnDesignAdapter()
        self._column_validator = make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema = super().input_schema
        schema["properties"]["context"] = deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self, data):
        validate_json(data, self._column_validator)
        try:
            validate_model(data["parameters"]["model"])
        except ToolValidationError as exc:
            raise ToolValidationError([{**row, "path": ["parameters", *row["path"]]} for row in exc.errors]) from None

    def _execute(self, data):
        try:
            expected_model = deepcopy(data["parameters"]["model"])
            report = self.adapter.design(deepcopy(expected_model))
            validate_design_semantics(report)
            if report["effective_input"] != expected_model:
                raise ValueError("Adapter changed the input.")
            if report["status"] == "FAIL":
                return ToolResult(False, self.name, self.version, result=report, warnings=[WARNING],
                    errors=[{"code": "column_design_failed", "message": "所有固定四角筋候选均未通过；详见每次尝试的逐项判定。",
                             "path": ["result", "attempts"]}], metadata={"project_id": data["project_id"]})
            result = ToolResult(True, self.name, self.version, result=report, warnings=[WARNING],
                                metadata={"project_id": data["project_id"]})
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_calculation_failed", "柱计算结果不能确认，已停止后续步骤。")
        try:
            return self.store.save(result)
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_snapshot_failed", "柱设计结果未能完整发布，已停止后续步骤。")
