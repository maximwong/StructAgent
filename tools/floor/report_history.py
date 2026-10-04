"""Read a completed revision by opaque identity, without replaying any tool."""

from copy import deepcopy
import json
from pathlib import Path

from agent.revision import digest, leaves
from core import ToolResult
from core.validation import make_validator, validate_json
from .check_adapter import validate_report
from .check_tool import OUTPUT as CHECK_OUTPUT


REVISION_ID = {'type': 'string', 'pattern': r'^revision-[0-9a-f]{32}$'}


def load_history(root, revision_id, *, project_id, reference, design, registry):
    validate_json(revision_id, make_validator(REVISION_ID))
    root = Path(root).resolve()
    folder = root / revision_id
    if folder.resolve().parent != root:
        raise ValueError('Revision directory is outside the configured store.')

    hashes = {}

    def read(name):
        path = folder / name
        if path.resolve() != path.absolute():
            raise ValueError('Revision evidence must not redirect to another directory.')
        raw = path.read_bytes()
        import hashlib
        hashes[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw.decode('utf-8-sig'))

    request, state = read('input.json'), read('state.json')
    outcome = ToolResult(**read('result.json'))
    revision_tool = registry.get('design_floor_with_revisions')
    revision_tool.validate(request)
    validate_json(outcome.result, make_validator(revision_tool.output_schema))
    result = outcome.result
    attempts = result['attempts']
    if (not outcome.success or outcome.tool != revision_tool.name or outcome.version != revision_tool.version
            or outcome.metadata.get('project_id') != project_id or request['project_id'] != project_id
            or result['revision_id'] != revision_id or state['revision_id'] != revision_id
            or state['project_id'] != project_id or result['status'] != 'PASS' or state['status'] != 'PASS'
            or state['current_step'] is not None
            or state['initial_sha256'] != digest(request['parameters']['initial_parameters'])
            or result['final_reference'] != reference or state['attempts'] != attempts
            or result['attempt_count'] != len(attempts) or not 1 <= len(attempts) <= request['parameters']['max_attempts']
            or result['final_parameters']['model'] != design.result['effective_input']):
        raise ValueError('Revision identity, terminal state or final design is inconsistent.')

    expected = deepcopy(request['parameters']['initial_parameters'])
    records = []
    for index, attempt in enumerate(attempts, 1):
        prefix = f'attempt-{index:02d}/'
        parameters = read(prefix + 'input.json')
        if attempt['index'] != index or parameters != expected or digest(parameters) != attempt['parameters_sha256']:
            raise ValueError('Revision input or digest is inconsistent.')
        saved = {}
        for stage in ('design', 'check', 'diagnosis'):
            if stage not in attempt:
                continue
            child = ToolResult(**read(prefix + stage + '.json'))
            summary = attempt[stage]
            expected_tool = {'design':'design_floor_system','check':'check_floor_design','diagnosis':'propose_floor_revision'}[stage]
            if (child.tool != expected_tool or child.tool != summary['tool'] or child.version != registry.get(child.tool).version
                    or child.success != summary['success'] or [e['code'] for e in child.errors] != summary['errors']
                    or Path(summary['path']).resolve() != (folder / (prefix + stage + '.json')).resolve()):
                raise ValueError('Revision child evidence is inconsistent.')
            if child.success: validate_json(child.result,make_validator(registry.get(child.tool).output_schema))
            saved[stage] = child
        designed = saved['design']
        if designed.tool != 'design_floor_system':
            raise ValueError('Unexpected design child.')
        if designed.success and (designed.result['effective_input'] != parameters['model']
                                 or designed.metadata.get('project_id') != project_id):
            raise ValueError('Design child does not use the recorded input.')
        if 'check' in saved:
            checked = saved['check']
            validate_json(checked.result,make_validator(CHECK_OUTPUT))
            validate_report({key:checked.result[key] for key in ('status','checks','summary')})
            if (not designed.success or checked.result['design_result_ref'] != designed.metadata['design_result_ref']
                    or checked.metadata.get('project_id') != project_id
                    or checked.metadata.get('design_sha256') != designed.metadata['legacy_result_sha256']):
                raise ValueError('Historical check does not match its design.')
        if index == len(attempts):
            checked = saved['check']
            if (not designed.success or not checked.success or checked.tool != 'check_floor_design'
                    or checked.result['status'] != 'PASS' or checked.result['design_result_ref'] != reference
                    or designed.metadata['design_result_ref'] != reference
                    or designed.result != design.result or parameters != result['final_parameters'] or 'change' in attempt):
                raise ValueError('Final revision evidence does not match the saved design.')
        else:
            if designed.success and ('check' not in saved or saved['check'].success):
                raise ValueError('A revision must follow a recorded failure.')
            proposal = saved['diagnosis']
            if proposal.tool != 'propose_floor_revision' or not proposal.success or proposal.result['action'] != 'revise':
                raise ValueError('Missing successful revision proposal.')
            candidate = proposal.result['parameters']
            before, after = dict(leaves(parameters)), dict(leaves(candidate))
            fields = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
            change = attempt['change']
            if fields != [change['field']] or proposal.result['changes'] != [change]:
                raise ValueError('Revision change evidence is inconsistent.')
            field = fields[0]
            choices = request['parameters']['allowed_changes'][field]
            if (change['before'] != before[field] or change['after'] != after[field]
                    or after[field] != min(v for v in choices if v > before[field])):
                raise ValueError('Revision is outside authorised candidates.')
            expected = deepcopy(candidate)
        records.append(dict(index=index, design_status='PASS' if designed.success else 'FAIL',
            errors=[dict(code=e['code'], message=e['message']) for child in saved.values() for e in child.errors],
            change=deepcopy(attempt.get('change')), reason=saved['diagnosis'].result['reason'] if 'diagnosis' in saved else '最终设计与校核通过'))
    return dict(revision_id=revision_id, records=records, evidence_sha256=hashes)
