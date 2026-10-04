"""Registry-facing calculation book tool; preserves the supplied design."""

from copy import deepcopy

from core import EngineeringTool, ToolResult
from core.validation import make_validator, validate_json
from .check_adapter import COVERAGE, validate_report
from .check_tool import OUTPUT as CHECK_OUTPUT
from .design_store import DesignReferenceError, REFERENCE
from .report_adapter import FloorReportError
from .report_history import REVISION_ID, load_history
from .schemas import CONTEXT_SCHEMA, object_schema

OUTPUT = object_schema(dict(report_id={'type':'string', 'pattern':r'^report-[0-9a-f]{32}$'},
    status={'const':'completed'}, format={'const':'docx'}, docx_sha256={'type':'string','pattern':r'^[0-9a-f]{64}$'},
    evidence_sha256={'type':'string','pattern':r'^[0-9a-f]{64}$'},
    **{key:{'type':'integer','minimum':1} for key in ('paragraphs','tables','images')},
    design_result_ref=REFERENCE, design_sha256={'type':'string','pattern':r'^[0-9a-f]{64}$'},
    check_summary=CHECK_OUTPUT['properties']['summary'], revision_id={'anyOf':[REVISION_ID,{'type':'null'}]}))


class FloorReportTool(EngineeringTool):
    def __init__(self, store, registry, adapter, revision_root):
        parameters = object_schema({'design_result_ref': REFERENCE, 'revision_id': REVISION_ID})
        parameters['required'] = ['design_result_ref']
        super().__init__(name='generate_floor_report', version='1.0.0',
            description='读取已保存楼盖设计，只读复核后生成Word计算书；可附完整授权调整记录，不重新设计或调用CAD。',
            parameters_schema=parameters, output_schema=deepcopy(OUTPUT))
        self.store, self.registry, self.adapter, self.revision_root = store, registry, adapter, revision_root
        self._input_schema['properties']['context'] = deepcopy(CONTEXT_SCHEMA)
        self._input_validator = make_validator(self._input_schema)

    def _execute(self, data):
        reference = data['parameters']['design_result_ref']
        try:
            design = self.store.load(reference, project_id=data['project_id'])
        except (DesignReferenceError, ValueError, OSError):
            return ToolResult.failure(self.name,self.version,'invalid_design_reference','需要本项目完整且校验和有效的设计结果。')
        try:
            checked = self.registry.get('check_floor_design').execute({**data, 'tool':'check_floor_design',
                                                                      'parameters':{'design_result_ref':reference}})
            if not isinstance(checked,ToolResult): raise ValueError('Invalid check result.')
            checked.to_dict()
            if checked.tool!='check_floor_design' or checked.version!='1.0.0': raise ValueError('Wrong check identity.')
            if checked.metadata.get('recovery_required',False) is not False: raise ValueError('Unexpected external state.')
        except Exception:
            return ToolResult.failure(self.name,self.version,'report_check_failed','报告前校核调用或结果验证失败，已停止。')
        if not checked.success:
            return ToolResult(False,self.name,self.version,errors=checked.errors,warnings=checked.warnings,
                              metadata=dict(project_id=data['project_id'],recovery_required=False))
        try:
            validate_json(checked.result, make_validator(CHECK_OUTPUT))
            validate_report({key:checked.result[key] for key in ('status','checks','summary')})
            if (checked.tool != 'check_floor_design' or checked.version != '1.0.0' or checked.result['status'] != 'PASS'
                    or checked.result['design_result_ref'] != reference or checked.metadata.get('project_id') != data['project_id']
                    or checked.metadata.get('design_result_ref') != reference or checked.metadata.get('scope_version') != 'section-check-v1'
                    or checked.metadata.get('design_sha256') != design.metadata['legacy_result_sha256']
                    or checked.result['coverage'] != COVERAGE): raise ValueError('Inconsistent check provenance.')
            history = None
            if 'revision_id' in data['parameters']:
                history = load_history(self.revision_root, data['parameters']['revision_id'],
                    project_id=data['project_id'], reference=reference, design=design, registry=self.registry)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            return ToolResult.failure(self.name,self.version,'report_evidence_invalid','校核或调整记录不完整、归属不一致；禁止生成报告。')
        evidence = dict(project_id=data['project_id'],design_result_ref=reference,
            design_sha256=design.metadata['legacy_result_sha256'],check=checked.to_dict(),history=history)
        try:
            output = self.adapter.generate(design,evidence)
            return ToolResult(True,self.name,self.version,**output,warnings=checked.warnings)
        except FloorReportError as exc:
            return ToolResult.failure(self.name,self.version,exc.code,str(exc))
        except (OSError, ValueError, KeyError, TypeError):
            return ToolResult.failure(self.name,self.version,'report_publish_failed','无法完整发布计算书及回执，已停止后续执行。')
