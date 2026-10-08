"""Two registry tools; analysis completion never claims engineering PASS."""
from copy import deepcopy
from core import EngineeringTool,ToolResult,ToolValidationError
from core.validation import make_validator
from .schemas import object_schema,CONTEXT_SCHEMA,NONEMPTY
from .reaction_input import EXTRACT_PARAMETERS,WALL_PARAMETERS,validate_parameters
from .reaction_adapter import FloorReactionAdapter
from .reaction_store import FloorReactionStore

QUANTITY=object_schema({'value':{'type':'number'},'exact':NONEMPTY})
VECTOR={'type':'array','items':QUANTITY,'minItems':4,'maxItems':4}
PATTERNS={'type':'array','items':{'type':'string','pattern':'^[01]{3}$'},'minItems':1,'maxItems':8,'uniqueItems':True}
CASE=object_schema({'pattern':{'type':'string','pattern':'^[01]{3}$'},
    'baseline_reactions_kN':VECTOR,'wall_increment_reactions_kN':VECTOR,'total_reactions_kN':VECTOR,
    'end_moments_kN_m':{'type':'array','items':{'type':'array','items':QUANTITY,'minItems':2,'maxItems':2},'minItems':3,'maxItems':3},
    'force_residual_kN':QUANTITY,'moment_residual_kN_m':QUANTITY})
CONTROL=object_schema({'support_id':NONEMPTY,'minimum_kN':QUANTITY,'maximum_kN':QUANTITY,
                       'minimum_patterns':PATTERNS,'maximum_patterns':PATTERNS})
OUTPUT=object_schema({'status':{'const':'MODEL_ANALYZED'},
    'input':{'oneOf':[EXTRACT_PARAMETERS,WALL_PARAMETERS]},'source_design_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},
    'spans_m':{'type':'array','items':QUANTITY,'minItems':3,'maxItems':3},'support_coordinates_mm':VECTOR,
    'legacy_factored_G_kN':QUANTITY,'legacy_factored_Q_kN':QUANTITY,
    'walls':{'type':'array','items':object_schema({'wall_id':NONEMPTY,'source':WALL_PARAMETERS['properties']['walls']['items']['properties']['source'],
        **{k:QUANTITY for k in ('net_area_m2','characteristic_weight_kN','characteristic_q_kN_m','design_weight_kN','design_q_kN_m')}}),'maxItems':8},
    'cases':{'type':'array','items':CASE,'minItems':8,'maxItems':8},'controls':{'type':'array','items':CONTROL,'minItems':4,'maxItems':4},
    'column_input_ready':{'type':'boolean','const':False},'floor_design_recheck_required':{'type':'boolean'},
    'support_contact_review_required':{'type':'boolean'},
    'coverage':object_schema({'model':{'const':'constant_EI_bilateral_no_settlement'},
        'combination_policy':{'const':'inherited_legacy_eight_patterns_not_full_code_combinations'},
        'wall_distribution':{'const':'total_weight_uniform_over_declared_interval'},
        'not_checked':{'type':'array','items':NONEMPTY,'minItems':6}})})


class FloorReactionTool(EngineeringTool):
    def __init__(self,design_store,root,*,walls=False):
        self.walls=walls
        super().__init__(name='analyze_floor_wall_reactions' if walls else 'extract_floor_reactions',version='1.0.0',
            description='教学连续主梁反力与直接落梁非承重墙自重分析；保留逐工况，不能直接用于柱设计。' if walls else '核实旧楼盖来源并标准化教学主梁8工况支座反力；非整层柱内力。',
            parameters_schema=WALL_PARAMETERS if walls else EXTRACT_PARAMETERS,output_schema=OUTPUT)
        self.adapter=FloorReactionAdapter(design_store)
        self.store=FloorReactionStore(root,self.adapter,OUTPUT)
        self._input_validator=make_validator(self.input_schema)

    @property
    def input_schema(self):
        schema=super().input_schema;schema['properties']['context']=deepcopy(CONTEXT_SCHEMA)
        return schema

    def validate(self,data):
        super().validate(data);validate_parameters(data['parameters'],walls=self.walls)

    def _execute(self,data):
        try:
            result=self.adapter.analyze(data['parameters'],project_id=data['project_id'],walls=self.walls)
            warnings=['反力仅对应旧教学主梁模型，未完成整层传力、完整规范组合或柱设计内力认证。']
            if self.walls: warnings.append('墙总重沿声明墙段均布；洞口局部传力未验证，旧楼盖须按新增荷载重新校核。')
            if result['support_contact_review_required']: warnings.append('合计反力出现负值；双向约束模型不验证支座抗拔或脱空。')
            outcome=ToolResult(True,self.name,self.version,result=result,warnings=warnings,metadata={'project_id':data['project_id']})
            ref=self.store.save(outcome)
            return ToolResult(True,self.name,self.version,result=result,warnings=warnings,
                              metadata={'project_id':data['project_id'],'reaction_result_ref':ref})
        except ToolValidationError as exc:
            return ToolResult(False,self.name,self.version,errors=exc.errors)
        except (ValueError,KeyError,TypeError,OSError,ArithmeticError):
            return ToolResult.failure(self.name,self.version,'reaction_source_or_analysis_invalid',
                '需要本项目完整且与输入对应的楼盖设计；请检查引用、来源、墙坐标和分析范围。')
