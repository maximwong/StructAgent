"""Conservative floor feedback rules; proposals use only explicit size candidates."""

from copy import deepcopy
import re

from core import EngineeringTool, ToolResult
from core.validation import make_validator
from .check_adapter import validate_report
from .schemas import CONTEXT_SCHEMA, EXPLICIT_PARAMETERS, object_schema

FIELDS = ('model.slab.h_mm','model.secondary.b_mm','model.secondary.h_mm',
          'model.main.b_mm','model.main.h_mm')
CHANGES_SCHEMA = dict(type='object',minProperties=1,additionalProperties=False,
    properties={field:dict(type='array',minItems=1,maxItems=8,uniqueItems=True,
        items=dict(type='number',exclusiveMinimum=0,maximum=800 if field.endswith('h_mm') and 'slab' not in field else 2000))
        for field in FIELDS})


class FloorRevisionProposalTool(EngineeringTool):
    def __init__(self):
        super().__init__(name='propose_floor_revision',version='1.0.0',
            description='依据受限工程失败提出单个已授权截面候选值；未知失败停止，不改变荷载、材料、支承或构造规则。',
            parameters_schema=object_schema(dict(design_parameters=EXPLICIT_PARAMETERS,
                allowed_changes=CHANGES_SCHEMA,feedback={'type':'object'})),
            output_schema=object_schema(dict(action={'enum':['revise','stop']},parameters=EXPLICIT_PARAMETERS,
                reason={'type':'string'},changes={'type':'array','items':object_schema(dict(
                    field={'enum':list(FIELDS)},before={'type':'number'},after={'type':'number'}))})))
        self._input_schema['properties']['context']=deepcopy(CONTEXT_SCHEMA)
        self._input_validator=make_validator(self._input_schema)

    def validate(self, data):
        super().validate(data)
        current=data['parameters']['design_parameters']
        for field, values in data['parameters']['allowed_changes'].items():
            target=current
            for part in field.split('.'):target=target[part]
            if target not in values or any(right<=left for left,right in zip(values,values[1:])):
                raise ValueError('Candidates must contain the current value and strictly increase: '+field)

    def _execute(self, data):
        values=data['parameters']
        current=values['design_parameters']
        feedback=ToolResult(**values['feedback'])
        paths=[]
        reason='该失败没有已验证的受限修改规则，需要人工检查。'
        if feedback.success or not feedback.errors:
            return ToolResult.failure(self.name,self.version,'invalid_feedback','需要明确失败的设计或校核结果。')
        codes={error['code'] for error in feedback.errors}
        if feedback.tool=='design_floor_system' and codes=={'design_rejected'} and len(feedback.errors)==1:
            message=feedback.errors[0]['message']
            beam=re.fullmatch(r'(secondary|main)/[^：]+：两排以内没有满足面积、净距及xi限制的配筋，请增大截面',message)
            if beam:
                member=beam[1]
                paths=[f'model.{member}.b_mm',f'model.{member}.h_mm']
                # Positive secondary bars must also fit inside the main-beam support width.
                if member=='secondary': paths.append('model.main.b_mm')
                reason='原设计未找到满足截面、排布与受压区限制的配筋；次梁还受主梁支座直段容纳约束。'
            elif message=='主梁中跨100%搭接的双倍钢筋无法在两排内排下，需增大梁宽或另定错开接头方案。':
                paths=['model.main.b_mm'];reason='原设计主梁搭接区排布不足，尝试已授权梁宽候选。'
            elif message=='本阶段主梁高度必须大于次梁高度。':
                paths=['model.main.h_mm'];reason='原设计主次梁高度关系不满足，尝试已授权主梁高度。'
            elif re.fullmatch(r'[^\n]+ 板候选配筋不足',message):
                paths=['model.slab.h_mm'];reason='原设计板配筋候选不足，尝试已授权板厚候选。'
            elif message=='默认Φ8@200板构造筋不足受力筋面积的1/3，本阶段需调整板截面或另定构造筋方案。':
                paths=['model.slab.h_mm'];reason='板构造筋与受力筋面积关系不足，尝试已授权板厚；仍需重新设计与校核。'
        elif feedback.tool=='check_floor_design' and codes=={'design_check_failed'}:
            report={key:feedback.result[key] for key in ('status','checks','summary')}
            validate_report(report)
            failed=[item for item in report['checks'] if not item['passed']]
            permitted={'flexure','xi','minimum','layout','spacing_min','spacing_max',
                       'shear_domain','stirrup_strength','stirrup_ratio','stirrup_code','stirrup_input','shear_geometry'}
            if all(item['id'].rsplit('.',1)[-1] in permitted for item in failed):
                for item in failed:
                    member=item['member']
                    paths.extend(['model.slab.h_mm'] if member=='slab' else
                                 [f'model.{member}.b_mm',f'model.{member}.h_mm'])
                reason='独立截面校核未通过，尝试已授权尺寸候选并重新完整设计；不修改已保存实配方案。'
            else:
                reason='失败包含数据一致性或未支持的构造检查，不能通过自动改参消除。'
        for field in dict.fromkeys(paths):
            if field not in values['allowed_changes']:continue
            target=current
            parts=field.split('.')
            for part in parts[:-1]: target=target[part]
            before=target[parts[-1]]
            options=[value for value in values['allowed_changes'][field] if value>before]
            if not options:continue
            candidate=deepcopy(current)
            target=candidate
            for part in parts[:-1]:target=target[part]
            target[parts[-1]]=min(options)
            return ToolResult(True,self.name,self.version,result=dict(action='revise',parameters=candidate,
                reason=reason,changes=[dict(field=field,before=before,after=min(options))]))
        return ToolResult(True,self.name,self.version,result=dict(action='stop',parameters=deepcopy(current),
            reason=reason+' 没有可用的已授权下一候选值。',changes=[]))
