"""Floor-specific presentation validation; never calculate or execute a tool."""

from core.validation import make_validator, validate_json
from tools.floor.check_adapter import COVERAGE, validate_report
from tools.floor.check_tool import OUTPUT

_OUTPUT = make_validator(OUTPUT)


def present_check(payload, snapshot):
    result = payload.result
    validate_json(result, _OUTPUT)
    validate_report({key: result[key] for key in ('status', 'checks', 'summary')})
    if (payload.version != '1.0.0'
            or payload.success != (result['status'] == 'PASS')
            or payload.metadata.get('project_id') != snapshot['project_id']
            or payload.metadata.get('design_result_ref') != result['design_result_ref']
            or payload.metadata.get('scope_version') != 'section-check-v1'
            or result['coverage'] != COVERAGE):
        raise ValueError('Check identity, verdict or coverage is inconsistent.')
    return {key: result[key] for key in ('status', 'summary', 'coverage', 'checks')}
