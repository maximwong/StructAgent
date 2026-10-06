"""Read-only check of stored design or explicit actual scheme; no redesign."""

from copy import deepcopy

from core import EngineeringTool, ToolResult, ToolValidationError
from core.validation import make_validator, validate_json
from .calculation import check_column, validate_actual, validate_model
from .design_adapter import ColumnCheckAdapter
from .design_tool import WARNING
from .schemas import CHECK_OUTPUT_SCHEMA, CHECK_PARAMETERS, CONTEXT_SCHEMA, REPORT_SCHEMA


class ColumnCheckTool(EngineeringTool):
    def __init__(self, store, adapter=None):
        super().__init__(name="check_column_design", version="1.0.0",
                         description="只读复核柱引用或完整输入及实配四角筋；实际FAIL保留逐项依据并停止流程，不重新选筋。",
                         parameters_schema=CHECK_PARAMETERS, output_schema=CHECK_OUTPUT_SCHEMA)
        self.store = store
        self.adapter = adapter if adapter is not None else ColumnCheckAdapter()
        self._column_validator = make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema = super().input_schema
        schema["properties"]["context"] = deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self, data):
        validate_json(data, self._column_validator)
        if "model" in data["parameters"]:
            try:
                validate_model(data["parameters"]["model"])
                validate_actual(data["parameters"]["actual"])
            except ToolValidationError as exc:
                raise ToolValidationError([{**row, "path": ["parameters", *row["path"]]} for row in exc.errors]) from None

    def _execute(self, data):
        parameters = data["parameters"]
        reference = parameters.get("design_result_ref")
        if reference is not None:
            try:
                stored = self.store.load(reference, project_id=data["project_id"])
                model, actual = stored.result["effective_input"], stored.result["selected"]["actual"]
            except Exception:
                return ToolResult.failure(self.name, self.version, "invalid_column_reference",
                                          "需要本项目完整且校验有效的柱设计引用。", ["parameters", "design_result_ref"])
        else:
            model, actual = parameters["model"], parameters["actual"]
        try:
            expected_model, expected_actual = deepcopy(model), deepcopy(actual)
            report = self.adapter.check(deepcopy(expected_model), deepcopy(expected_actual))
            validate_json(report, make_validator(REPORT_SCHEMA))
            if report != check_column(expected_model, expected_actual):
                raise ValueError("Actual-scheme report is inconsistent.")
            if reference is not None:
                report = {**report, "design_result_ref": reference}
            validate_json(report, make_validator(CHECK_OUTPUT_SCHEMA))
            errors = [{"code": "column_check_failed", "message": row["label"] + "未通过，详见实配方案与依据。",
                       "path": ["result", "checks", index]} for index, row in enumerate(report["checks"]) if not row["passed"]]
            return ToolResult(report["status"] == "PASS", self.name, self.version, result=report,
                              errors=errors, warnings=[WARNING], metadata={"project_id": data["project_id"],
                                  "check_source": "stored_design" if reference is not None else "explicit_actual"})
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_check_invalid", "柱实配结果不能确认，已停止后续步骤。")
