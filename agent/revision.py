"""Bounded, journalled Registry composition; no engineering script dependencies."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from core import EngineeringTool, ToolResult
from core.persistence import write_json
from core.validation import make_validator, validate_json


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def leaves(value, prefix=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaves(item, prefix + ('.' if prefix else '') + key)
    else:
        yield prefix, value


def at(value, path):
    for segment in path:
        value = value[segment]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class RevisionSpec:
    design_tool: str
    check_tool: str
    proposal_tool: str
    reference_path: tuple
    check_reference_parameter: str
    checked_reference_path: tuple
    retry_codes: tuple = ()


_OUTPUT = object_schema({
    'revision_id': {'type':'string'}, 'status': {'enum':['PASS','STOPPED','LIMIT','TIMEOUT']},
    'attempt_count': {'type':'integer','minimum':0}, 'final_reference': {'type':['string','null']},
    'final_parameters': {'type':'object'}, 'attempts': {'type':'array','items':{'type':'object'}},
    'reason': {'type':'string'},
})


class BoundedRevisionTool(EngineeringTool):
    """A plugin declares child tools and schemas; limits come from explicit user input."""

    def __init__(self, *, name, description, registry, root, spec, initial_schema, changes_schema,
                 context_schema, clock=time.monotonic):
        super().__init__(name=name, version='1.0.0', description=description,
            parameters_schema=object_schema({
                'initial_parameters':initial_schema, 'allowed_changes':changes_schema,
                'max_attempts':{'type':'integer','minimum':1,'maximum':4},
                'time_budget_seconds':{'type':'number','exclusiveMinimum':0,'maximum':240},
            }), output_schema=_OUTPUT)
        self.registry, self.root, self.spec, self.clock = registry, Path(root).resolve(), spec, clock
        self.context_schema = deepcopy(context_schema)
        self._input_validator = make_validator(self.input_schema)
        for child in (spec.design_tool, spec.check_tool, spec.proposal_tool): registry.get(child)

    @property
    def input_schema(self):
        schema=super().input_schema
        schema['properties']['context']=deepcopy(self.context_schema)
        return schema

    def validate(self, data):
        super().validate(data)
        parameters=data['parameters']
        initial=parameters['initial_parameters']
        self.registry.get(self.spec.design_tool).validate({**data,'tool':self.spec.design_tool,'parameters':initial})
        fields=dict(leaves(initial))
        for path, values in parameters['allowed_changes'].items():
            if (path not in fields or values[0] != fields[path]
                    or any(right <= left for left,right in zip(values,values[1:]))):
                raise ValueError('Candidates must start at the explicit initial value and strictly increase: '+path)

    def _execute(self, data):
        try:
            return self._run(data)
        except (OSError, ValueError, KeyError, TypeError):
            return ToolResult.failure(self.name,self.version,'revision_execution_failed',
                '受限重设计未能完整记录或校验，已停止；不会自动重试或出图。')

    def _run(self, data):
        request=data['parameters']
        parameters=deepcopy(request['initial_parameters'])
        revision_id='revision-'+uuid4().hex
        folder=self.root/revision_id
        started=self.clock()
        manifest=dict(revision_id=revision_id, project_id=data['project_id'], status='RUNNING',
                      initial_sha256=digest(parameters), attempts=[], current_step=None)
        write_json(folder/'input.json',data,exclusive=True)
        warnings=[]

        def checkpoint(stage):
            manifest['current_step']=stage
            write_json(folder/'state.json',manifest)

        def expired(): return self.clock()-started >= request['time_budget_seconds']

        def finish(status, reason, reference=None):
            result=dict(revision_id=revision_id,status=status,attempt_count=len(manifest['attempts']),
                        final_reference=reference,final_parameters=deepcopy(parameters),
                        attempts=deepcopy(manifest['attempts']),reason=reason)
            outcome=ToolResult(status=='PASS',self.name,self.version,result=result,warnings=warnings,
                errors=[] if status=='PASS' else [dict(code='revision_'+status.lower(),message=reason,path=[])],
                artifacts=[dict(type='revision_log',path=str(folder/'state.json'))],
                metadata=dict(project_id=data['project_id'],recovery_required=False))
            write_json(folder/'result.json',outcome.to_dict(),exclusive=True)
            # Publish the complete result before declaring a terminal journal state.
            # A failed publication must never leave a PASS state or enable CAD.
            manifest.update(status=status,current_step=None,reason=reason)
            checkpoint(None)
            return outcome

        def call(name, inputs, attempt, stage):
            checkpoint(stage)
            tool=self.registry.get(name)
            envelope=dict(project_id=data['project_id'],tool=name,context=deepcopy(data['context']),parameters=inputs)
            try:
                payload=tool.execute(envelope)
                if not isinstance(payload,ToolResult) or payload.tool!=name or payload.version!=tool.version:
                    raise ValueError('Wrong child identity.')
                if ('recovery_required' in payload.metadata and type(payload.metadata['recovery_required']) is not bool
                        or payload.metadata.get('recovery_required') is True):
                    raise ValueError('Revision child tools cannot require external recovery.')
                if payload.success: validate_json(payload.result,make_validator(tool.output_schema))
            except Exception:
                payload=ToolResult.failure(name,tool.version,'revision_call_failed','子工具执行或结果校验失败。')
            path=folder/f"attempt-{attempt['index']:02d}"/(stage+'.json')
            write_json(path,payload.to_dict(),exclusive=True)
            attempt[stage]=dict(tool=name,success=payload.success,path=str(path),
                                errors=[e['code'] for e in payload.errors])
            warnings.extend(w for w in payload.warnings if w not in warnings)
            checkpoint(stage)
            return payload

        seen={digest(parameters)}
        try:
            for index in range(1,int(request['max_attempts'])+1):
                if expired(): return finish('TIMEOUT','已达到总时间预算，停止后续计算和出图。')
                attempt=dict(index=index,parameters_sha256=digest(parameters))
                manifest['attempts'].append(attempt)
                write_json(folder/f'attempt-{index:02d}'/'input.json',parameters,exclusive=True)
                designed=call(self.spec.design_tool,parameters,attempt,'design')
                if expired(): return finish('TIMEOUT','设计调用后已达到总时间预算。')
                feedback=designed
                if designed.success:
                    reference=at(designed.to_dict(),self.spec.reference_path)
                    if not isinstance(reference,str) or not reference.strip():
                        return finish('STOPPED','设计引用不完整，受限流程已停止。')
                    checked=call(self.spec.check_tool,{self.spec.check_reference_parameter:reference},attempt,'check')
                    if expired(): return finish('TIMEOUT','校核调用后已达到总时间预算。')
                    if (checked.success or any(e['code'] in self.spec.retry_codes for e in checked.errors)):
                        if at(checked.to_dict(),self.spec.checked_reference_path)!=reference:
                            return finish('STOPPED','校核与本轮设计引用不一致，受限流程已停止。')
                    if checked.success:
                        if checked.result.get('status')!='PASS':
                            return finish('STOPPED','校核通过标志不一致。')
                        return finish('PASS','最终方案通过已声明范围的设计与独立校核。',reference)
                    feedback=checked
                if (feedback.metadata.get('recovery_required') not in (None,False)
                        or not feedback.errors or any(e['code'] not in self.spec.retry_codes for e in feedback.errors)):
                    return finish('STOPPED','当前失败不属于允许重设计的工程反馈，停止循环。')
                if index==request['max_attempts']:
                    return finish('LIMIT','已达到最大设计轮数，仍未通过；请人工调整方案。')
                proposed=call(self.spec.proposal_tool,dict(design_parameters=parameters,
                    allowed_changes=request['allowed_changes'],feedback=feedback.to_dict()),attempt,'diagnosis')
                if expired(): return finish('TIMEOUT','诊断调用后已达到总时间预算。')
                if not proposed.success or proposed.result['action']!='revise':
                    return finish('STOPPED',proposed.result.get('reason','没有可执行的受限修改。'))
                candidate=proposed.result['parameters']
                old,new=dict(leaves(parameters)),dict(leaves(candidate))
                changed=[path for path in set(old)|set(new) if old.get(path)!=new.get(path)]
                if len(changed)!=1:
                    return finish('STOPPED','建议必须恰好修改一个已授权字段。')
                field=changed[0]
                if (field not in request['allowed_changes'] or new[field] not in request['allowed_changes'][field]
                        or new[field]<=old[field] or digest(candidate) in seen):
                    return finish('STOPPED','修改超出已授权候选范围或重复已有方案。')
                next_value=min(value for value in request['allowed_changes'][field] if value>old[field])
                if new[field]!=next_value:
                    return finish('STOPPED','建议跳过了已授权的下一候选值。')
                # Independently validate proposals; never trust a plugin's success flag alone.
                self.registry.get(self.spec.design_tool).validate({**data,'tool':self.spec.design_tool,'parameters':candidate})
                change=dict(field=field,before=old[field],after=new[field])
                if proposed.result['changes'] != [change]:
                    return finish('STOPPED','修改记录与实际参数差异不一致。')
                attempt['change']=change
                checkpoint('diagnosis')
                parameters=deepcopy(candidate);seen.add(digest(parameters))
        except KeyboardInterrupt:
            manifest.update(status='INTERRUPTED',reason='用户中断；不会自动续跑或出图。')
            checkpoint(None)
            raise
        except (ValueError,KeyError,TypeError):
            return finish('STOPPED','子工具结果或参数不完整，受限流程已停止。')
