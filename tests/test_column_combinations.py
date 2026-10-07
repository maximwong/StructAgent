"""Independent frozen references, group completeness and result integrity."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from agent.controller import AgentController
from agent.state import AgentState
from agent.workflow import Workflow, WorkflowStep
from core import ToolRegistry
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from examples.column_workflow import LocalColumnParser
from examples.column_combinations import run_request
from tests.test_column_calculation import actual_bars, column_model
from tests.test_column_tools import envelope
from tools.column.calculation import check_column
from tools.column.combination_calculation import check_column_combinations, design_column_combinations
from tools.column.combination_store import ColumnCombinationStore, ColumnCombinationReferenceError
from tools.column.combination_tools import ColumnCombinationCheckTool, ColumnCombinationDesignTool
from tools.column.design_store import ColumnDesignStore
from tools.column.json_data import canonical_hash
from tools.column.plugin import register_column_combinations

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = json.loads((ROOT / 'tests/fixtures/column_combination_references.json').read_text(encoding='utf-8'))


def combination_parameters(case='short', forces=None):
    model = column_model('slender' if case == 'slender' else 'short')
    actions = model.pop('actions')
    model['effective_length']['analysis_id'] = 'TEACHING-ANALYSIS-1'
    groups = []
    for index, force in enumerate(forces if forces is not None else REFERENCES[case]['N_kN'], 1):
        combination_id = f'ULS-{index}'
        groups.append({'combination_id': combination_id, 'actions': {**deepcopy(actions), 'N_kN': force},
                       'source': {'analysis_id': 'TEACHING-ANALYSIS-1', 'member_id': 'C1', 'section_id': 'BOTTOM',
                                  'combination_id': combination_id, 'force_record_id': f'ROW-{index}',
                                  'description': 'Anonymous complete teaching force vector',
                                  'unit_system': 'mm,kN,kN.m,MPa', 'same_force_vector': True}})
    return {'model': model, 'combinations': groups}


def request(parameters=None, *, tool='design_column_combinations', project='COLUMN-SET-TEST'):
    return envelope(tool, parameters if parameters is not None else combination_parameters(), project)


class CombinationCalculationTests(unittest.TestCase):
    def test_frozen_independent_short_slender_and_exact_ties(self):
        for case in ('short', 'slender', 'tied'):
            with self.subTest(case=case):
                parameters = combination_parameters(case)
                before = deepcopy(parameters)
                report = design_column_combinations(parameters)
                expected = REFERENCES[case]
                self.assertEqual(report['status'], 'PASS')
                selected = report['selected']
                self.assertEqual(selected['actual'], actual_bars(expected['diameter_mm']))
                self.assertEqual(selected['controlling_combination_ids'], expected['controlling_combination_ids'])
                for attempt in report['attempts']:
                    self.assertEqual(len(attempt['combination_results']), len(parameters['combinations']))
                    for row, source in zip(attempt['combination_results'], parameters['combinations']):
                        self.assertEqual(row['source'], source['source'])
                        self.assertEqual(row['report']['effective_input']['actions'], source['actions'])
                for row in selected['combination_results']:
                    self.assertAlmostEqual(row['report']['intermediates']['Nu_kN'], expected['Nu_kN'], delta=1e-6)
                self.assertEqual(parameters, before)

    def test_actual_scheme_no_redesign_and_all_groups_after_failure(self):
        parameters = combination_parameters('weak_short')
        with patch('tools.column.combination_calculation.design_column_combinations', side_effect=AssertionError('no design')), \
             patch('tools.column.calculation.design_column', side_effect=AssertionError('no legacy design')):
            report = check_column_combinations(parameters, actual_bars(14))
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual([row['report']['status'] for row in report['combination_results']], REFERENCES['weak_short']['statuses'])
        for row in report['combination_results']:
            self.assertAlmostEqual(row['report']['intermediates']['Nu_kN'], 1357.56, delta=1e-6)
        parameters['model']['ties']['spacing_mm'] = 300
        with patch('tools.column.combination_calculation.check_column', wraps=check_column) as checked:
            report = check_column_combinations(parameters, actual_bars())
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['controlling_combination_ids'], ['ULS-2'])
        self.assertTrue(all(row['report']['status'] == 'FAIL' for row in report['combination_results']))

    def test_candidates_exhausted_keep_every_group_and_fixed_inputs(self):
        parameters = combination_parameters('capacity_failure')
        report = design_column_combinations(parameters)
        self.assertEqual(report['status'], 'FAIL')
        self.assertIsNone(report['selected'])
        self.assertEqual([row['actual']['bar_diameter_mm'] for row in report['attempts']], [12,14,16,18,20,22,25,28])
        self.assertTrue(all(len(row['combination_results']) == 2 for row in report['attempts']))
        self.assertEqual(report['effective_input'], parameters)

    def test_exact_controls_do_not_use_rounded_float_utilization(self):
        for forces in ([1400, 1400.0000000000002], [2**53, 2**53 + 1]):
            with self.subTest(forces=forces):
                report = check_column_combinations(combination_parameters(forces=forces), actual_bars())
                self.assertEqual(report['controlling_combination_ids'], ['ULS-2'])
        report = check_column_combinations(combination_parameters(forces=[1400, 1400.0]), actual_bars())
        self.assertEqual(report['controlling_combination_ids'], ['ULS-1', 'ULS-2'])


class CombinationToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '柱组合结果'
        self.store = ColumnCombinationStore(self.root)
        self.design = ColumnCombinationDesignTool(self.store)
        self.check = ColumnCombinationCheckTool(self.store)

    def saved(self):
        result = self.design.execute(request())
        self.assertTrue(result.success, result.errors)
        ref = result.result['design_result_ref']
        return result, ref, self.root / (ref + '.json')

    def rewrite(self, path, payload):
        data = payload['design']
        report = {key: value for key, value in data['result'].items() if key != 'design_result_ref'}
        data['metadata']['column_set_sha256'] = canonical_hash(report)
        payload['checksum'] = canonical_hash({key: value for key, value in payload.items() if key != 'checksum'})
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def test_roundtrip_reference_preserves_actual_input_and_sources(self):
        designed, ref, _ = self.saved()
        with patch('tools.column.combination_calculation.design_column_combinations', side_effect=AssertionError('no design')):
            checked = self.check.execute(request({'design_result_ref': ref}, tool=self.check.name))
        self.assertTrue(checked.success, checked.errors)
        self.assertEqual(checked.result['actual'], designed.result['selected']['actual'])
        self.assertEqual(checked.result['effective_input'], designed.result['effective_input'])
        self.assertEqual(checked.result['combination_results'], designed.result['selected']['combination_results'])
        self.assertEqual(checked.result['design_result_ref'], ref)

    def test_actual_fail_success_false_retains_per_group_checks(self):
        parameters = {**combination_parameters(), 'actual': actual_bars(14)}
        result = self.check.execute(request(parameters, tool=self.check.name))
        self.assertFalse(result.success)
        self.assertEqual(result.result['status'], 'FAIL')
        self.assertEqual(len(result.result['combination_results']), 2)
        self.assertTrue(result.errors)
        self.assertEqual(result.result['actual'], actual_bars(14))

    def test_projects_versions_ref_formats_exclusive_inputs_and_unicode_paths(self):
        _, ref, path = self.saved()
        self.assertTrue(path.exists())
        self.assertFalse(self.check.execute(request({'design_result_ref': ref}, tool=self.check.name, project='OTHER')).success)
        for params in ({'design_result_ref': 'column-' + 'a'*32}, {'design_result_ref': '../x'},
                       {'design_result_ref': ref, **combination_parameters(), 'actual': actual_bars()}):
            self.assertFalse(self.check.execute(request(params, tool=self.check.name)).success)
        with self.assertRaises(ValueError):
            ColumnDesignStore(self.root).load(ref, project_id='COLUMN-SET-TEST')
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['design']['version'] = '9.9.9'
        self.rewrite(path, payload)
        with self.assertRaises(ColumnCombinationReferenceError):
            self.store.load(ref, project_id='COLUMN-SET-TEST')

    def test_rehashed_semantic_tampering_is_rejected(self):
        _, ref, path = self.saved()
        original = json.loads(path.read_text(encoding='utf-8'))
        def source(data): data['selected']['combination_results'][0]['source']['force_record_id'] = 'OTHER'
        def drop(data): data['selected']['combination_results'].pop()
        def control(data): data['selected']['controlling_combination_ids'] = ['ULS-1']
        def prefix(data): data['attempts'].pop(0)
        def actual(data): data['selected']['actual']['bar_diameter_mm'] = 14
        def input_m(data): data['effective_input']['combinations'][0]['actions']['Mx_kN_m'] = 1
        def status(data):
            row = data['attempts'][0]['combination_results'][0]['report']['checks'][0]
            row['passed'] = not row['passed']
        for mutate in (source, drop, control, prefix, actual, input_m, status):
            with self.subTest(mutation=mutate.__name__):
                payload = deepcopy(original)
                mutate(payload['design']['result'])
                self.rewrite(path, payload)
                with self.assertRaises(ValueError): self.store.load(ref, project_id='COLUMN-SET-TEST')
                self.assertFalse(self.check.execute(request({'design_result_ref': ref}, tool=self.check.name)).success)

    def test_immutable_collision_and_calculation_publication_failures(self):
        fixed = UUID('0123456789abcdef0123456789abcdef')
        with patch('tools.column.combination_store.uuid4', return_value=fixed):
            first = self.design.execute(request())
            self.assertTrue(first.success, first.errors)
            path = self.root / (first.result['design_result_ref'] + '.json')
            before = path.read_bytes()
            second = self.design.execute(request())
            self.assertFalse(second.success)
            self.assertEqual(path.read_bytes(), before)
        with patch('tools.column.combination_tools.design_column_combinations', side_effect=RuntimeError('private secret')):
            result = self.design.execute(request())
        self.assertFalse(result.success)
        self.assertNotIn('private secret', json.dumps(result.to_dict()))


class CombinationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runs'

    def result_at(self, snapshot, step):
        call = next(row for row in snapshot['tool_calls'] if row['step'] == step)
        return json.loads(Path(call['result_path']).read_text(encoding='utf-8'))

    def test_registry_workflow_uses_original_controller_without_cloud_cad(self):
        before = (ROOT / 'agent/controller.py').read_bytes()
        with patch('llm.gateway.DeepSeekGateway.__init__', side_effect=AssertionError('no cloud')), \
             patch('tools.floor.cad_adapter.AutoCADBackend.execute', side_effect=AssertionError('no CAD')):
            snapshot = run_request(request(), self.root)
        self.assertTrue(snapshot['success'], snapshot['errors'])
        design, check = self.result_at(snapshot, 'design'), self.result_at(snapshot, 'check')
        self.assertEqual(design['result']['design_result_ref'], check['result']['design_result_ref'])
        self.assertEqual((ROOT / 'agent/controller.py').read_bytes(), before)

    def test_plugin_loading_constructs_only_and_preserves_single_web_binding(self):
        plugins = Path(self.temp.name) / 'plugins'
        shutil.copytree(ROOT / 'plugins/rc_column', plugins / 'rc_column', ignore=shutil.ignore_patterns('__pycache__'))
        with patch('tools.column.combination_tools.design_column_combinations', side_effect=AssertionError('no calculation')), \
             patch('tools.column.combination_tools.check_column_combinations', side_effect=AssertionError('no check')):
            load_plugins(plugins, PluginContext(self.root))
            self.assertFalse(self.root.exists())
            catalog = load_plugins(ROOT / 'plugins', PluginContext(self.root))
        self.assertEqual({row['id'] for row in catalog.plugins}, {'rc_floor', 'rc_column'})
        self.assertEqual(len(catalog.structured_web), 1)

    def test_design_fail_or_publication_fail_stops_check(self):
        registry = ToolRegistry()
        workflow = register_column_combinations(registry, self.root)
        for parameters, publication_fail in ((combination_parameters('capacity_failure'), False), (combination_parameters(), True)):
            controller = AgentController(registry, LocalColumnParser(request(parameters), registry), AgentState(self.root / 'agent'), [workflow])
            with patch.object(registry.get('check_column_combinations'), 'execute', side_effect=AssertionError('skip')):
                if publication_fail:
                    with patch.object(registry.get('design_column_combinations').store, 'save', side_effect=OSError('private')):
                        snapshot = controller.run('local', project_id='COLUMN-SET-TEST')
                else: snapshot = controller.run('local', project_id='COLUMN-SET-TEST')
            self.assertFalse(snapshot['success'])
            self.assertEqual(snapshot['steps']['check'], 'skipped')

    def test_actual_check_failure_stops_later_step(self):
        registry = ToolRegistry()
        register_column_combinations(registry, self.root)
        workflow = Workflow('fail_gate', (WorkflowStep('check', 'check_column_combinations'), WorkflowStep('later', 'design_column_combinations')))
        params = {**combination_parameters(), 'actual': actual_bars(14)}
        controller = AgentController(registry, LocalColumnParser(request(params, tool='check_column_combinations'), registry), AgentState(self.root / 'agent'), [workflow])
        with patch.object(registry.get('design_column_combinations'), 'execute', side_effect=AssertionError('no later design')):
            snapshot = controller.run('local', project_id='COLUMN-SET-TEST')
        self.assertFalse(snapshot['success'])
        self.assertEqual(snapshot['steps']['later'], 'skipped')

    def test_cli_full_json_success_repeated_refs_fail_and_strict_json(self):
        def cli(text, tool_only=False):
            path = Path(self.temp.name) / 'request.json'
            path.write_text(text, encoding='utf-8')
            args = [sys.executable, '-m', 'examples.column_combinations', '--request-file', str(path), '--output-root', str(self.root)]
            if tool_only: args.append('--tool-only')
            result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=30)
            self.assertEqual(result.stderr, b'')
            return result.returncode, json.loads(result.stdout.decode('utf-8'))
        refs = []
        for case in ('short', 'slender', 'short'):
            code, snapshot = cli(json.dumps(request(combination_parameters(case))))
            self.assertEqual(code, 0)
            refs.append(self.result_at(snapshot, 'design')['result']['design_result_ref'])
        self.assertEqual(len(set(refs)), 3)
        code, snapshot = cli(json.dumps(request({'design_result_ref': refs[0]}, tool='check_column_combinations')), True)
        self.assertEqual(code, 0)
        self.assertTrue(snapshot['success'])
        code, snapshot = cli(json.dumps(request({**combination_parameters(), 'actual': actual_bars(14)}, tool='check_column_combinations')), True)
        self.assertEqual(code, 1)
        self.assertEqual(self.result_at(snapshot, 'check')['result']['status'], 'FAIL')
        for text in ('{"tool":"x","tool":"y"}', '{"N":NaN}', '{"N":1e999}', '[]', json.dumps(request({}))):
            code, snapshot = cli(text)
            self.assertEqual(code, 1)
            self.assertFalse(snapshot['success'])


if __name__ == '__main__':
    unittest.main()
