"""Column-owned local forms, request validation and read-only presentation."""
from copy import deepcopy
from pathlib import Path
import re

from core import ToolValidationError
from core.json_data import loads_json
from core.plugin_base import StructuredWebBinding, StructuredWebOperation
from core.validation import make_validator, validate_json
from .calculation import check_column
from .design_store import ColumnDesignStore, validate_design_semantics
from .schemas import (MODEL_SCHEMA, ACTUAL_SCHEMA, CONTEXT_SCHEMA, REPORT_SCHEMA,
                      CHECK_OUTPUT_SCHEMA, DESIGN_OUTPUT_SCHEMA, CHECK_PARAMETERS, CHECK_MODEL_PARAMETERS)

LABELS = {
    'project_id': '项目标识（同项目可复用）', 'tool': '请求工具',
    'unit_system': '单位声明', 'design_code': '规范声明',
    'b_mm': '截面宽 b（mm）', 'h_mm': '截面高 h（mm）',
    'cover_to_outer_tie_mm': '至箍筋外缘保护层（mm）',
    'l0_mm': '双主轴控制有效长度 l0（mm）', 'source': '有效长度来源',
    'covers_both_principal_axes': '有效长度覆盖两个主轴',
    'N_kN': '最终轴压力 N（kN）', 'Mx_kN_m': '弯矩 Mx（kN·m）',
    'My_kN_m': '弯矩 My（kN·m）', 'Vx_kN': '剪力 Vx（kN）', 'Vy_kN': '剪力 Vy（kN）',
    'N_includes_gamma0': 'N 已含结构重要性系数 gamma0', 'combination_source': '同一荷载组合来源',
    'concrete': '混凝土等级', 'longitudinal_steel': '纵筋等级', 'tie_steel': '箍筋等级',
    'fc_MPa': '混凝土轴心抗压强度（MPa，可选）',
    'fy_compression_MPa': '纵筋抗压强度（MPa，可选）', 'tie_fy_MPa': '箍筋强度（MPa，可选）',
    'configuration': '箍筋形式', 'diameter_mm': '箍筋直径（mm）', 'spacing_mm': '箍筋间距（mm）',
    'purpose': '用途', 'loading': '荷载性质', 'seismic': '抗震设计',
    'ideal_axial_compression': '理想纯轴压假设', 'gamma_Rd': '承载力调整系数 gamma_Rd',
    'bar_count': '实际纵筋根数', 'bar_diameter_mm': '实际纵筋直径（mm）',
    'layout': '实际纵筋布局', 'design_result_ref': '本项目柱设计引用',
}
GROUPS = {'section': '截面', 'effective_length': '有效长度', 'actions': '作用与来源',
          'materials': '材料', 'ties': '箍筋', 'scope': '适用范围', 'actual': '实际纵筋',
          'context': '单位与规范'}
CHOICES = {'teaching': '教学', 'static': '静力', 'four_corner_bars': '四角纵筋',
           'single_closed_rectangular': '单个闭合矩形箍筋'}
CHECK_LABELS = {'axial_capacity': '理想轴心受压承载力（含稳定系数phi）',
                'total_ratio_min': '总纵筋最小配筋率', 'side_ratio_min': '每侧对称纵筋最小配筋率',
                'total_ratio_max': '本插件总纵筋最大配筋率', 'clear_spacing_b': 'b方向纵筋净距',
                'clear_spacing_h': 'h方向纵筋净距', 'center_spacing_b': 'b方向纵筋中心距',
                'center_spacing_h': 'h方向纵筋中心距', 'tie_diameter': '箍筋最小直径',
                'tie_spacing': '箍筋最大间距', 'longitudinal_cover': '纵筋外缘保护层与直径'}
DISPLAY_COVERAGE = {'checked': ['含稳定系数phi的理想轴压承载力', '总配筋率及单侧配筋率',
                    '双主轴四角纵筋净距及中心距', '箍筋直径及间距', '纵筋保护层与直径'],
                    'not_checked': ['环境、耐久性及防火保护层', '锚固与搭接', '节点及构件端部',
                    '箍筋弯钩与全项构造', '偏心受压及附加偏心距', '偏心二阶效应与框架二阶分析',
                    '抗震设计', '疲劳', '内力及有效长度来源分析'],
                    'pass_meaning': 'PASS仅表示本版全部已声明检查项通过，不代表完整工程验收。'}


def fields(schema, prefix='', group='请求归属'):
    rows = []
    for key, child in schema['properties'].items():
        path = prefix + '.' + key if prefix else key
        if child.get('type') == 'object':
            rows.extend(fields(child, path, GROUPS.get(key, group)))
        else:
            rows.append({'path': path, 'label': LABELS.get(key, key), 'group': group,
                         'schema': deepcopy(child), 'required': key in schema.get('required', []),
                         'choices_labels': CHOICES})
    return rows


def column_web_binding(registry, root):
    operations = (StructuredWebOperation('design', '设计并独立校核', 'rc_column_design', 'design_column'),
                  StructuredWebOperation('check', '单步校核实际方案或已有引用', 'rc_column_actual_check', 'check_column_design'))
    store = ColumnDesignStore(Path(root) / 'column-designs')

    def form():
        common = {'type': 'object', 'properties': {
            'project_id': {'type': 'string'}, 'context': CONTEXT_SCHEMA},
            'required': ['project_id', 'context']}
        base = fields(common)
        model = fields({'properties': {'model': MODEL_SCHEMA}}, 'parameters')
        actual = fields({'properties': {'actual': ACTUAL_SCHEMA}}, 'parameters')
        ref = fields({'properties': {'design_result_ref': {'type': 'string'}},
                      'required': ['design_result_ref']}, 'parameters')
        demos = []
        for filename, label in [('column-short.json', '匿名短柱 · 设计'),
                                ('column-slender.json', '匿名细长柱 · 设计'),
                                ('column-check-fail.json', '匿名实际4Φ14 · 校核FAIL')]:
            demos.append({'name': label, 'envelope': loads_json((Path(__file__).resolve().parents[2] / 'demos' / filename).read_text(encoding='utf-8'))})
        return {'title': '完整柱工程输入', 'design_label': '柱设计', 'result_title': '设计与校核结果',
                'help': '填写完整参数，或显式载入匿名教学案例。无需自然语言口令。',
                'notice': '教学非抗震静力理想纯轴压，固定矩形截面与四角纵筋；所有必填项由用户明确输入。',
                'modes': [{'id': 'design', 'operation': 'design', 'tool': 'design_column',
                           'name': '设计→独立校核', 'fields': base + model},
                          {'id': 'actual', 'operation': 'check', 'tool': 'check_column_design',
                           'name': '单步校核实际配筋', 'fields': base + model + actual},
                          {'id': 'reference', 'operation': 'check', 'tool': 'check_column_design',
                           'name': '单步校核本项目引用', 'fields': base + ref}], 'examples': demos}

    def request(operation, envelope):
        selected = next((o for o in operations if o.id == operation), None)
        if selected is None or not isinstance(envelope, dict) or envelope.get('tool') != selected.tool:
            raise ToolValidationError([{'code': 'invalid_operation', 'message': '请选择与完整请求工具一致的操作。', 'path': ['tool']}])
        try:
            if selected.tool == 'check_column_design' and isinstance(envelope.get('parameters'), dict):
                parameters = envelope['parameters']
                schema = CHECK_MODEL_PARAMETERS if {'model', 'actual'} & parameters.keys() else CHECK_PARAMETERS['oneOf'][1]
                validate_json(parameters, make_validator(schema), prefix=('parameters',))
            registry.get(selected.tool).validate(envelope)
        except ToolValidationError as exc:
            errors = []
            for error in exc.errors:
                path = list(error.get('path', []))
                missing = re.fullmatch(r"'([^']+)' is a required property", error['message'])
                if missing:
                    path.append(missing[1])
                unexpected = re.search(r"\('([^']+)' was unexpected\)", error['message'])
                if unexpected:
                    path.append(unexpected[1])
                errors.append({**error, 'path': path})
            raise ToolValidationError(errors) from None
        if not 1 <= len(envelope['project_id'].strip()) <= 80 or envelope['project_id'] != envelope['project_id'].strip():
            raise ToolValidationError([{'code': 'invalid_project', 'message': '项目标识须为1至80个字符，且首尾不含空格。', 'path': ['project_id']}])
        return deepcopy(envelope)

    def presentation(record, snapshot, read):
        envelope = record['envelope']
        operation = next(o for o in operations if o.id == record['operation'])
        parsed = snapshot.get('parse_result', {})
        calls = snapshot.get('tool_calls', [])
        safe_error_messages = {
            'invalid_column_reference': '需要本项目完整且校验有效的柱设计引用。',
            'column_snapshot_failed': '柱设计结果未能完整保存，本次已停止校核。',
            'column_calculation_failed': '柱计算结果无法确认，本次已停止。',
            'column_check_invalid': '柱实配校核结果无法确认，本次已停止。',
            'ui_start_failed': '无法启动本地流程，请检查运行目录与本机配置。',
            'workflow_error': '执行流程遇到异常，后续步骤已停止；请保留本次记录供检查。',
            'state_save_failed': '本次运行状态无法完整保存，请保留已有记录供检查。',
            'owner_exited': '原运行进程已退出，本次不会自动重做。',
        }
        display_errors = [safe_error_messages.get(error.get('code'), '本次流程未完成，请检查输入及运行记录。')
                          for error in snapshot.get('errors', [])
                          if error.get('code') not in {'column_check_failed', 'column_design_failed'}]
        if snapshot.get('project_id', record['project_id']) != envelope['project_id']:
            raise ValueError('Project differs.')
        if parsed and parsed.get('envelope') != envelope:
            raise ValueError('Input differs.')
        if snapshot.get('workflow') not in (None, operation.workflow):
            raise ValueError('Workflow differs.')
        if calls and (parsed.get('status') != 'ready' or parsed.get('envelope') != envelope
                      or snapshot.get('workflow') != operation.workflow):
            raise ValueError('Ready input provenance is missing.')
        expected_calls = [('design', 'design_column'), ('check', 'check_column_design')] if operation.id == 'design' else [('check', 'check_column_design')]
        if len(calls) > len(expected_calls) or any((c.get('step'), c.get('tool')) != expected_calls[i] for i, c in enumerate(calls)):
            raise ValueError('Steps differ.')
        reports, reference, model, actual, check_seen = [], None, None, None, False
        for call in calls:
            if snapshot.get('steps', {}).get(call['step']) != call.get('status'):
                raise ValueError('Step and tool execution status differ.')
            if call.get('status') in ('running', 'interrupted') or not call.get('result_path'):
                continue
            payload = read(call, snapshot)
            if payload.version != '1.0.0':
                raise ValueError('Version differs.')
            if not payload.result:
                if payload.success:
                    raise ValueError('Missing result.')
                continue
            if payload.metadata.get('project_id') != envelope['project_id']:
                raise ValueError('Result project differs.')
            result = payload.result
            if call['tool'] == 'design_column':
                report = {k: v for k, v in result.items() if k != 'design_result_ref'}
                validate_design_semantics(report)
                if result['effective_input'] != envelope['parameters']['model'] or payload.success != (result['status'] == 'PASS'):
                    raise ValueError('Design input or status differs.')
                if payload.success:
                    validate_json(result, make_validator(DESIGN_OUTPUT_SCHEMA))
                    reference = result['design_result_ref']
                    if store.load(reference, project_id=envelope['project_id']).to_dict() != payload.to_dict():
                        raise ValueError('Published design differs.')
                    model, actual = result['effective_input'], result['selected']['actual']
                    reports = [result['selected']]
                else:
                    reports = result['attempts']
            else:
                check_seen = True
                validate_json(result, make_validator(CHECK_OUTPUT_SCHEMA))
                if operation.id == 'check':
                    reference = envelope['parameters'].get('design_result_ref')
                    if reference:
                        saved = store.load(reference, project_id=envelope['project_id']).result
                        model, actual = saved['effective_input'], saved['selected']['actual']
                    else:
                        model, actual = envelope['parameters']['model'], envelope['parameters']['actual']
                expected = check_column(deepcopy(model), deepcopy(actual))
                if reference:
                    expected['design_result_ref'] = reference
                if (result != expected or payload.success != (result['status'] == 'PASS')
                        or payload.metadata.get('check_source') != ('stored_design' if reference else 'explicit_actual')):
                    raise ValueError('Actual report or provenance differs.')
                reports = [result]
        if snapshot.get('success') is True and (snapshot.get('status') != 'completed'
                or snapshot.get('persistence_state') != 'COMPLETED' or len(calls) != len(expected_calls)
                or snapshot.get('steps') != {'parse': 'completed', **{s: 'completed' for s, t in expected_calls}}
                or not reports or reports[-1]['status'] != 'PASS' or not check_seen or calls[-1].get('status') != 'completed'):
            raise ValueError('Completion differs.')
        if snapshot.get('success') is not True and snapshot.get('status') == 'completed':
            raise ValueError('Completion and success differ.')
        if not reports:
            return {'summary': None, 'check': None, 'display_summary': None,
                    'display_sources': [], 'display_errors': display_errors}
        report = reports[-1]
        summary = {'actual': report['actual'], **report['intermediates'],
                   'design_result_ref': reference, 'materials': report['materials'], 'basis': report['basis']}
        checked = {**deepcopy(report), 'summary': {'passed': sum(row['passed'] for row in report['checks']),
                                                  'total': len(report['checks'])},
                   'attempts': deepcopy(reports) if len(reports) > 1 else []}
        checked['display_coverage'] = deepcopy(DISPLAY_COVERAGE)
        checked['display_basis'] = ['承载力公式：' + summary['basis']['capacity_formula'],
                                    '混凝土面积策略：' + summary['basis']['area_policy'],
                                    '稳定系数策略：' + summary['basis']['phi_policy']]
        for item in checked['checks']:
            item['display_label'] = CHECK_LABELS[item['id']]
        for attempt in checked['attempts']:
            for item in attempt['checks']:
                item['display_label'] = CHECK_LABELS[item['id']]
        display_summary = (f"实际纵筋 {report['actual']['bar_count']}Φ{report['actual']['bar_diameter_mm']}；"
            f"As={summary['total_area_mm2']:.9g} mm²；phi={summary['phi']:.9g}；"
            f"Nu={summary['Nu_kN']:.9g} kN；N/Nu={summary['utilization']:.9g}。"
            f"材料来源：{summary['materials']['table_version']}；混凝土轴压强度fc={summary['materials']['fc_MPa']} MPa，"
            f"纵筋抗压强度fy′={summary['materials']['fy_compression_MPa']} MPa，箍筋强度fy={summary['materials']['tie_fy_MPa']} MPa。"
            f"依据版本：{summary['basis']['scope_version']}；{summary['basis']['design_code']}。"
            + (f"柱设计引用：{reference}。" if reference else ''))
        checked['display_rows'] = []
        for shown in checked['attempts'] or [checked]:
            for row in shown['checks']:
                checked['display_rows'].append({'label': (f"{shown['actual']['bar_count']}Φ{shown['actual']['bar_diameter_mm']} · " if checked['attempts'] else '') + row['display_label'],
                    'basis': row['basis'], 'comparison': f"{row['value']:.9g} {row['relation']} {row['limit']:.9g}",
                    'passed': row['passed']})
                if not row['passed']:
                    candidate = f"{shown['actual']['bar_count']}Φ{shown['actual']['bar_diameter_mm']} · " if checked['attempts'] else ''
                    if row['id'] == 'axial_capacity':
                        message = f"轴压承载力未通过：N={row['value']:.9g} kN 大于 Nu={row['limit']:.9g} kN。"
                    else:
                        message = f"{row['display_label']}未通过：实值 {row['value']:.9g}，要求 {row['relation']} {row['limit']:.9g}。"
                    display_errors.append(candidate + message)
        source_model = report['effective_input']
        from_reference = bool(reference)
        display_sources = [{'label': '输入来源', 'value': '已核验的原设计输入（来自本项目柱引用），不是当前引用请求中的新工程输入。'
                            if from_reference else '用户明确填写的本次工程输入，经校核结果一致性验证。'},
                           {'label': '轴压力 N（kN）', 'value': str(source_model['actions']['N_kN'])},
                           {'label': '荷载组合来源', 'value': source_model['actions']['combination_source']},
                           {'label': '双主轴控制有效长度 l0（mm）', 'value': str(source_model['effective_length']['l0_mm'])},
                           {'label': '有效长度来源', 'value': source_model['effective_length']['source']}]
        displayed = {'actions.N_kN', 'actions.combination_source', 'effective_length.l0_mm', 'effective_length.source'}
        for field in fields(MODEL_SCHEMA):
            if field['path'] in displayed:
                continue
            value = source_model
            for key in field['path'].split('.'):
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None:
                rendered = '是' if value is True else '否' if value is False else CHOICES.get(str(value), str(value))
                display_sources.append({'label': field['group'] + ' · ' + field['label'], 'value': rendered})
        return {'summary': summary, 'check': checked if check_seen or report['status'] == 'FAIL' else None,
                'display_summary': display_summary, 'display_sources': display_sources, 'display_errors': display_errors}

    return StructuredWebBinding('rc_column', '钢筋混凝土柱（本地教学轴压）', operations, form, request, presentation)
