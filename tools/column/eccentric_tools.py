"""Registry-only multi-combination tools; legacy column tools remain unchanged."""
from copy import deepcopy

from core import EngineeringTool, ToolResult
from core.validation import make_validator, validate_json
from .eccentric_input import validate_actual
from .eccentric_input import PARAMETERS_SCHEMA, validate_parameters, ACTUAL_SCHEMA
from .eccentric_calculation import (CHECK_OUTPUT, DESIGN_OUTPUT, REFERENCE_SCHEMA,
    check_column_eccentric, design_column_eccentric, validate_design_semantics,
    validate_check_semantics)
from .schemas import CONTEXT_SCHEMA, object_schema

WARNING = "教学非抗震静力四角筋单向偏压截面；二阶外部处理声明未获认证，PASS仅覆盖声明检查项。"
CHECK_PARAMETERS = {"type": "object", "oneOf": [object_schema({
    **PARAMETERS_SCHEMA["properties"], "actual": ACTUAL_SCHEMA}),
    object_schema({"design_result_ref": REFERENCE_SCHEMA})]}


class _EccentricTool(EngineeringTool):
    @property
    def input_schema(self):
        schema = super().input_schema
        schema["properties"]["context"] = deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self, data):
        validate_json(data, self._eccentric_validator)
        parameters = data["parameters"]
        if "model" in parameters:
            validate_parameters({key: deepcopy(parameters[key]) for key in ("model", "combinations")})
            if "actual" in parameters:
                validate_actual(parameters["actual"])


class ColumnEccentricDesignTool(_EccentricTool):
    def __init__(self, store):
        super().__init__(name="design_column_eccentric", version="1.0.0",
            description="完整来源绑定的教学柱多组合四角筋单向偏压设计；逐组复算，不拼接极值。",
            parameters_schema=PARAMETERS_SCHEMA, output_schema=DESIGN_OUTPUT)
        self.store = store
        self._eccentric_validator = make_validator(self.input_schema)

    def _execute(self, data):
        try:
            report = design_column_eccentric(deepcopy(data["parameters"]))
            validate_design_semantics(report)
            if report["effective_input"] != data["parameters"]:
                raise ValueError("Combination design changed input")
            if report["status"] == "FAIL":
                return ToolResult(False, self.name, self.version, result=report, warnings=[WARNING],
                    errors=[{"code": "column_eccentric_design_failed", "message": "全部固定纵筋候选在声明范围内未确认所有组合通过。",
                             "path": ["result", "attempts"]}], metadata={"project_id": data["project_id"]})
            result = ToolResult(True, self.name, self.version, result=report,
                warnings=[WARNING], metadata={"project_id": data["project_id"]})
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_eccentric_calculation_failed", "单向偏压柱计算结果不能确认。")
        try:
            return self.store.save(result)
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_eccentric_snapshot_failed", "单向偏压柱设计未能完整发布。")


class ColumnEccentricCheckTool(_EccentricTool):
    def __init__(self, store):
        super().__init__(name="check_column_eccentric", version="1.0.0",
            description="只读复核多组合引用或完整模型、来源与实际四角筋；逐组检查，不重选钢筋。",
            parameters_schema=CHECK_PARAMETERS, output_schema=CHECK_OUTPUT)
        self.store = store
        self._eccentric_validator = make_validator(self.input_schema)

    def _execute(self, data):
        reference = data["parameters"].get("design_result_ref")
        if reference is not None:
            try:
                stored = self.store.load(reference, project_id=data["project_id"]).result
                parameters, actual = stored["effective_input"], stored["selected"]["actual"]
            except Exception:
                return ToolResult.failure(self.name, self.version, "invalid_column_eccentric_reference",
                    "需要本项目完整且有效的单向偏压柱设计引用。", ["parameters", "design_result_ref"])
        else:
            parameters = {key: data["parameters"][key] for key in ("model", "combinations")}
            actual = data["parameters"]["actual"]
        try:
            report = check_column_eccentric(deepcopy(parameters), deepcopy(actual))
            validate_check_semantics(report, parameters, actual)
            if reference is not None:
                report["design_result_ref"] = reference
            errors = [{"code": "column_eccentric_check_failed",
                "message": group["combination_id"] + "：" + row["id"] + "未通过。",
                "path": ["result", "combination_results", index, "checks", check_index]}
                for index, group in enumerate(report["combination_results"])
                for check_index, row in enumerate(group["checks"]) if not row["passed"]]
            return ToolResult(report["status"] == "PASS", self.name, self.version, result=report,
                errors=errors, warnings=[WARNING], metadata={"project_id": data["project_id"],
                    "check_source": "stored_design" if reference else "explicit_actual"})
        except Exception:
            return ToolResult.failure(self.name, self.version, "column_eccentric_check_invalid", "单向偏压柱实配校核结果不能确认。")
