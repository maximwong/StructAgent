"""Registry-facing drawing tool; backend commands are private to the adapter."""

from copy import deepcopy

from core import EngineeringTool, ToolResult
from core.validation import make_validator, validate_json
from .cad_adapter import FloorCADError
from .design_store import DesignReferenceError, REFERENCE
from .schemas import CONTEXT_SCHEMA, object_schema


class FloorCADTool(EngineeringTool):
    def __init__(self, store, adapter):
        super().__init__(name="generate_floor_cad", version="1.0.0",
                         description="读取本项目已成功设计的结果引用，生成独立楼盖图纸并保存、重开校验。",
                         parameters_schema=object_schema({"design_result_ref": REFERENCE}),
                         output_schema=object_schema({
                             "drawing_status": {"const": "completed"},
                             "run_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                             "entities": {"type": "integer", "minimum": 1}, "reopened": {"const": True}}))
        self.store, self.adapter = store, adapter
        self._cad_validator = make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema = super().input_schema
        schema["properties"]["context"] = deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self, data):
        validate_json(data, self._cad_validator)

    def _execute(self, data):
        reference = data["parameters"]["design_result_ref"]
        try:
            design = self.store.load(reference, project_id=data["project_id"])
        except DesignReferenceError as exc:
            return ToolResult.failure(self.name, self.version, "invalid_design_reference", str(exc),
                                      ("parameters", "design_result_ref"))
        try:
            return ToolResult(True, self.name, self.version, **self.adapter.generate(design, reference=reference))
        except FloorCADError as exc:
            return ToolResult(False, self.name, self.version,
                              errors=[{"code": exc.code, "message": str(exc), "path": []}],
                              metadata={"run_directory": exc.run_dir})
