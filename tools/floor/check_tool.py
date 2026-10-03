"""A PASS/FAIL engineering gate, registered like every other tool."""

from copy import deepcopy
from core import EngineeringTool, ToolResult, ToolValidationError
from core.validation import make_validator, validate_json
from .check_adapter import COVERAGE, REPORT, FloorCheckAdapter, FloorCheckError, validate_report
from .design_store import REFERENCE, DesignReferenceError
from .schemas import CONTEXT_SCHEMA, object_schema

OUTPUT = object_schema({**REPORT['properties'],'design_result_ref':REFERENCE,
                       'coverage':object_schema({
                           'recomputed':{'type':'array','items':{'type':'string'}},
                           'demand_source':{'type':'string'},
                           'not_checked':{'type':'array','items':{'type':'string'}}})})


class FloorCheckTool(EngineeringTool):
    def __init__(self,store,adapter=None):
        super().__init__(name='check_floor_design',version='1.0.0',
            description='按既有公式独立复核已保存实配截面的受弯、配筋、排布及抗剪约束；FAIL阻止后续出图，非规范全项校核。',
            parameters_schema=object_schema({'design_result_ref':REFERENCE}),output_schema=OUTPUT)
        self.store,self.adapter=store,adapter if adapter is not None else FloorCheckAdapter()
        self._input_validator=make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema=super().input_schema;schema['properties']['context']=deepcopy(CONTEXT_SCHEMA)
        return schema

    def _execute(self,data):
        ref=data['parameters']['design_result_ref']
        try:
            design=self.store.load(ref,project_id=data['project_id'])
        except (DesignReferenceError,ToolValidationError):
            return ToolResult.failure(self.name,self.version,'invalid_design_reference','需要本项目完整且校验和有效的设计结果。')
        try:
            report=self.adapter.check(design)
            validate_report(report)
            result={**report,'design_result_ref':ref,'coverage':deepcopy(COVERAGE)}
            # Failed engineering checks are also schema-validated, unlike generic failed executions.
            validate_json(result,make_validator(OUTPUT))
        except FloorCheckError as exc:
            return ToolResult.failure(self.name,self.version,exc.code,str(exc))
        except (ToolValidationError,KeyError,TypeError,ValueError):
            return ToolResult.failure(self.name,self.version,'check_input_invalid','设计数据不完整，无法确认校核通过。')
        member_names={'slab':'板','secondary':'次梁','main':'主梁'}
        errors=[{'code':'design_check_failed','path':['result','checks',i],
                 'message':member_names[item['member']]+'截面'+str(item['section']+1)+'：'+item['label']+'未通过，请检查实配方案。'}
                for i,item in enumerate(report['checks']) if not item['passed']]
        return ToolResult(report['status']=='PASS',self.name,self.version,result=result,errors=errors,
            warnings=[*design.warnings,'独立校核仅覆盖声明的截面及抗剪约束，PASS不表示工程全项审查通过。'],
            metadata={'project_id':data['project_id'],'design_result_ref':ref,
                      'design_sha256':design.metadata['legacy_result_sha256'],'scope_version':'section-check-v1'})
