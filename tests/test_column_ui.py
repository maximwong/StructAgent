"""Real local Controller/column tools; no cloud or CAD backend is called."""
from copy import deepcopy
from dataclasses import replace
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app
from core.json_data import loads_json
from core.persistence import write_json
from core.plugin_base import PluginContext, StructuredWebOperation, StructuredWebBinding
from core.plugin_loader import load_plugins, PluginLoadError
from ui.server import LocalServer
from ui.service import UIError

ROOT = Path(__file__).resolve().parents[1]


class ColumnUIFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='structagent_column_ui_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Mock(side_effect=AssertionError('Local mode must not read API configuration.'))
        self.gateway = Mock(side_effect=AssertionError('Local mode must not create a gateway.'))
        self.settings_patch = patch.object(app, 'load_settings', self.settings)
        self.gateway_patch = patch.object(app, 'DeepSeekGateway', self.gateway)
        self.settings_patch.start(); self.gateway_patch.start()
        self.addCleanup(self.settings_patch.stop); self.addCleanup(self.gateway_patch.stop)
        self.service = app.create_service(self.root)
        self.service.opener = Mock(side_effect=AssertionError('No drawing opens.'))
        self.service.recover = Mock(side_effect=AssertionError('No CAD recovery.'))
        self.addCleanup(self.finish)

    def finish(self):
        if self.service.thread:
            self.service.thread.join(20)

    def envelope(self, case='short'):
        return loads_json((ROOT / 'demos' / ('column-' + case + '.json')).read_text(encoding='utf-8'))

    def payload(self, envelope):
        return {'input_mode': 'structured', 'profession': 'rc_column',
                'operation': 'design' if envelope['tool'] == 'design_column' else 'check',
                'project_name': '匿名教学柱', 'envelope': deepcopy(envelope)}

    def run_local(self, envelope):
        job = self.service.start(self.payload(envelope))['id']
        self.finish()
        self.assertFalse(self.service.thread.is_alive())
        view = self.service.view(job)
        self.assertIsNone(view['check_issue'])
        return job, view


class ColumnUITests(ColumnUIFixture):
    def test_short_slender_and_actual_failure_real_controller(self):
        for case, diameter, phi, capacity, status in [('short', 16, 1, 1418.796, 'PASS'),
                                                     ('slender', 20, .75, 1173.933, 'PASS'),
                                                     ('check-fail', 14, 1, 1357.560, 'FAIL')]:
            with self.subTest(case=case):
                _, view = self.run_local(self.envelope(case))
                self.assertEqual(view['summary']['actual']['bar_diameter_mm'], diameter)
                self.assertEqual(view['summary']['phi'], phi)
                self.assertAlmostEqual(view['summary']['Nu_kN'], capacity, places=3)
                self.assertEqual(view['check']['status'], status)
                self.assertEqual(len(view['check']['checks']), 11)
                self.assertTrue(all(row['display_label'] for row in view['check']['checks']))
                self.assertTrue(view['check']['display_coverage']['not_checked'])
                self.assertFalse(view['can_open'])
                self.assertIsNone(view['report'])
                if status == 'FAIL':
                    self.assertEqual([c['tool'] for c in view['snapshot']['tool_calls']], ['check_column_design'])
                    self.assertFalse(view['snapshot']['success'])
        self.settings.assert_not_called(); self.gateway.assert_not_called()

    def test_same_project_is_pinned_refresh_restart_and_reference(self):
        request = self.envelope()
        first, first_view = self.run_local(request)
        second, second_view = self.run_local(request)
        self.assertNotEqual(first_view['run_id'], second_view['run_id'])
        self.assertNotEqual(first_view['summary']['design_result_ref'], second_view['summary']['design_result_ref'])
        check = {'project_id': request['project_id'], 'tool': 'check_column_design', 'context': request['context'],
                 'parameters': {'design_result_ref': first_view['summary']['design_result_ref']}}
        _, checked = self.run_local(check)
        self.assertEqual(checked['summary']['actual'], first_view['summary']['actual'])
        self.assertEqual(self.service.view(first)['snapshot']['run_id'], first_view['run_id'])
        restarted = app.create_service(self.root)
        self.assertEqual(restarted.view(first)['snapshot']['run_id'], first_view['run_id'])
        self.assertEqual(restarted.view(second)['snapshot']['run_id'], second_view['run_id'])
        check['project_id'] = 'OTHER-PROJECT'
        _, wrong = self.run_local(check)
        self.assertFalse(wrong['snapshot']['success'])
        self.assertIsNone(wrong['summary'])
        self.assertEqual(wrong['snapshot']['errors'][0]['code'], 'invalid_column_reference')

    def test_reference_presents_verified_original_input_and_sources(self):
        request = self.envelope()
        _, designed = self.run_local(request)
        reference = {'project_id': request['project_id'], 'tool': 'check_column_design', 'context': request['context'],
                     'parameters': {'design_result_ref': designed['summary']['design_result_ref']}}
        job, checked = self.run_local(reference)
        source = {row['label']: row['value'] for row in checked['display_sources']}
        self.assertIn('已核验的原设计输入', source['输入来源'])
        self.assertIn('不是当前引用请求', source['输入来源'])
        self.assertEqual(source['轴压力 N（kN）'], '1400')
        self.assertEqual(source['双主轴控制有效长度 l0（mm）'], '900')
        self.assertEqual(source['荷载组合来源'], request['parameters']['model']['actions']['combination_source'])
        self.assertEqual(source['有效长度来源'], request['parameters']['model']['effective_length']['source'])
        with patch('core.tool_base.EngineeringTool.execute', side_effect=AssertionError('Read only view')):
            self.assertEqual(self.service.view(job)['display_sources'], checked['display_sources'])

    def test_failure_display_is_chinese_and_keeps_raw_tool_result(self):
        _, failed = self.run_local(self.envelope('check-fail'))
        self.assertTrue(any('轴压承载力未通过' in error and '1400' in error and '1357.56' in error
                            for error in failed['display_errors']))
        self.assertTrue(all('result.checks' not in error and 'ideal axial' not in error
                            for error in failed['display_errors']))
        self.assertEqual(failed['snapshot']['errors'][0]['code'], 'column_check_failed')
        self.assertEqual(failed['snapshot']['errors'][0]['path'], ['result', 'checks', 0])
        raw = loads_json(Path(failed['snapshot']['tool_calls'][0]['result_path']).read_text(encoding='utf-8'))
        self.assertEqual(raw['result']['checks'][0]['label'], 'ideal axial compression capacity')

    def test_no_old_success_on_setup_or_persistence_failure(self):
        request = self.envelope()
        first, view = self.run_local(request)
        self.service.structured_controller_factory = Mock(side_effect=OSError('PRIVATE PATH sk-secret'))
        failed = self.service.start(self.payload(request))['id']; self.finish()
        bad = self.service.view(failed)
        self.assertEqual(bad['snapshot']['status'], 'error')
        self.assertIsNone(bad['summary'])
        self.assertNotIn('PRIVATE', json.dumps(bad))
        self.assertEqual(self.service.view(first)['snapshot']['run_id'], view['run_id'])

    def test_corruption_blocks_pass_without_reselecting(self):
        job, view = self.run_local(self.envelope())
        path = Path(view['snapshot']['tool_calls'][-1]['result_path'])
        original = loads_json(path.read_text(encoding='utf-8'))
        mutations = [lambda d: d['result']['checks'][0].update(passed=False),
                     lambda d: d['result']['coverage'].update(not_checked=['invented coverage']),
                     lambda d: d['result']['actual'].update(bar_diameter_mm=14),
                     lambda d: d['metadata'].update(project_id='other'),
                     lambda d: d.update(version='9.0.0'),
                     lambda d: d['result']['intermediates'].update(Nu_kN=99999),
                     lambda d: d['result']['checks'].pop()]
        with patch('tools.column.design_adapter.ColumnDesignAdapter.design', side_effect=AssertionError('No redesign')):
            for mutation in mutations:
                bad = deepcopy(original); mutation(bad); write_json(path, bad)
                broken = self.service.view(job)
                self.assertIsNotNone(broken['check_issue'])
                self.assertIsNone(broken['check'])
                self.assertFalse(broken['snapshot']['success'])
        write_json(path, original)
        self.assertIsNone(self.service.view(job)['check_issue'])

    def test_invalid_inputs_never_call_local_controller(self):
        factory = self.service.structured_controller_factory
        self.service.structured_controller_factory = Mock(wraps=factory)
        original = self.envelope()
        mutations = [lambda d: d['parameters']['model']['section'].pop('b_mm'),
                     lambda d: d['parameters']['model']['section'].update(b_mm=True),
                     lambda d: d['parameters']['model']['actions'].update(N_kN='1400'),
                     lambda d: d['parameters']['model']['actions'].update(Mx_kN_m=1),
                     lambda d: d['parameters']['model']['actions'].update(Vy_kN=1),
                     lambda d: d['parameters']['model']['actions'].update(N_kN=float('inf')),
                     lambda d: d['parameters']['model']['scope'].update(seismic='false'),
                     lambda d: d['parameters']['model']['materials'].update(fc_MPa=999),
                     lambda d: d['parameters']['model']['materials'].update(tie_fy_MPa=True),
                     lambda d: d['parameters']['model'].update(unknown=1),
                     lambda d: d['context'].update(unknown=1),
                     lambda d: d['context'].update(unit_system='m'),
                     lambda d: d.update(project_id=''),
                     lambda d: d.update(tool='draw_floor_cad')]
        for mutation in mutations:
            d = deepcopy(original); mutation(d)
            with self.assertRaises(UIError): self.service.start(self.payload(d))
        for field, value in [('profession', 'missing'), ('operation', 'missing')]:
            payload = self.payload(original); payload[field] = value
            with self.assertRaises(UIError): self.service.start(payload)
        self.service.structured_controller_factory.assert_not_called()
        self.assertEqual(list(self.service.jobs.glob('*.json')), [])

    def test_check_missing_field_error_keeps_chinese_and_precise_path(self):
        request = self.envelope('check-fail')
        request['parameters']['model']['effective_length'].pop('source')
        with self.assertRaises(UIError) as missing:
            self.service.start(self.payload(request))
        self.assertIn('parameters.model.effective_length.source', str(missing.exception))
        self.assertIn('有效长度来源', str(missing.exception))
        request = self.envelope('check-fail'); request['parameters']['model']['actions']['unknown'] = 1
        with self.assertRaises(UIError) as unknown:
            self.service.start(self.payload(request))
        self.assertIn('parameters.model.actions.unknown', str(unknown.exception))

    def test_import_preserves_context_project_and_optional_strengths(self):
        d = self.envelope(); d['parameters']['model']['materials'].update(fc_MPa=14.3, fy_compression_MPa=360, tie_fy_MPa=270)
        imported = self.service.import_structured({'profession': 'rc_column', 'json': json.dumps(d)})
        self.assertEqual(imported['envelope'], d)
        _, view = self.run_local(d)
        self.assertTrue(view['snapshot']['success'])
        for case in ('short', 'slender', 'check-fail'):
            d = self.envelope(case)
            self.assertEqual(self.service.import_structured({'profession': 'rc_column', 'json': json.dumps(d)})['envelope'], d)
        for raw in ['{"tool":"design_column","tool":"check_column_design"}', '{"a":NaN}', '{"a":1e999}']:
            with self.assertRaises(UIError): self.service.import_structured({'profession': 'rc_column', 'json': raw})

    def test_local_ready_and_server_rejects_column_cad_report(self):
        self.assertTrue(self.service.configuration('rc_column')['ready'])
        job, view = self.run_local(self.envelope())
        with self.assertRaises(UIError): self.service.open_drawing(job)
        with self.assertRaises(UIError): self.service.reports.start(job)
        self.service.opener.assert_not_called()
        self.service.recover.assert_not_called()
        self.settings.assert_not_called(); self.gateway.assert_not_called()

    def test_serial_guard_survives_mode_switch(self):
        entered, release = threading.Event(), threading.Event()
        factory = self.service.structured_controller_factory
        def blocked(*args):
            entered.set(); release.wait(10); return factory(*args)
        self.service.structured_controller_factory = blocked
        self.addCleanup(release.set)
        self.service.start(self.payload(self.envelope()))
        self.assertTrue(entered.wait(3))
        with self.assertRaises(UIError) as error: self.service.start(self.payload(self.envelope('check-fail')))
        self.assertEqual(error.exception.status, 409)
        release.set(); self.finish()

    def test_history_filters_before_limit_and_project_scope(self):
        job, view = self.run_local(self.envelope())
        for index in range(35):
            write_json(self.service.jobs / (f'{index:032x}.json'),
                       {'id': f'{index:032x}', 'project_name': 'floor', 'project_id': 'other', 'created': 1})
        local = self.service.status('rc_column', view['project_id'])
        self.assertEqual([j['id'] for j in local['jobs']], [job])
        self.assertEqual(self.service.status('rc_column', 'wrong')['jobs'], [])
        with patch.object(self.service, 'settings_check', side_effect=ValueError('Missing key.')):
            self.assertEqual(len(self.service.status('rc_floor')['jobs']), 30)

    def test_pin_publication_failure_closes_created_sql_run(self):
        original = self.envelope()
        first, view = self.run_local(original)
        import ui.service as module
        save = module.write_json
        def fault(path, data, **kwargs):
            if Path(path).parent == self.service.jobs and data.get('run_id') and data.get('id') != first:
                raise OSError('Simulated UI pin write failure.')
            return save(path, data, **kwargs)
        with patch.object(module, 'write_json', fault), patch('tools.column.design_adapter.ColumnDesignAdapter.design', side_effect=AssertionError('No tool execution')):
            failed = self.service.start(self.payload(original))['id']; self.finish()
        bad = self.service.view(failed)
        self.assertFalse(bad['snapshot']['success']); self.assertIsNone(bad['summary'])
        self.assertEqual(self.service.state.store.list_runs(state='RUNNING'), [])
        self.assertEqual(self.service.view(first)['run_id'], view['run_id'])
        _, next_view = self.run_local(original)
        self.assertTrue(next_view['snapshot']['success'])

    def test_final_job_publication_failure_does_not_show_success(self):
        original = self.envelope()
        first, view = self.run_local(original)
        import ui.service as module
        save = module.write_json
        publications = {}
        def fault(path, data, **kwargs):
            if Path(path).parent == self.service.jobs and data.get('run_id') and data.get('id') != first:
                key = data['id']; publications[key] = publications.get(key, 0) + 1
                if publications[key] == 2:
                    raise OSError('Simulated final publication failure.')
            return save(path, data, **kwargs)
        with patch.object(module, 'write_json', fault):
            failed = self.service.start(self.payload(original))['id']; self.finish()
        bad = self.service.view(failed)
        self.assertFalse(bad['snapshot']['success']); self.assertIsNone(bad['summary'])
        restarted = app.create_service(self.root)
        self.assertFalse(restarted.view(failed)['snapshot']['success'])
        self.assertEqual(restarted.view(first)['run_id'], view['run_id'])

    def test_design_candidate_failure_retains_all_actual_attempts(self):
        request = self.envelope(); request['parameters']['model']['actions']['N_kN'] = 10000
        _, view = self.run_local(request)
        self.assertFalse(view['snapshot']['success'])
        self.assertEqual(view['snapshot']['steps']['check'], 'skipped')
        self.assertEqual(view['check']['status'], 'FAIL')
        self.assertEqual(len(view['check']['attempts']), 8)
        self.assertEqual(len(view['check']['display_rows']), 8*11)

    def test_key_format_is_rejected_before_writing(self):
        payload = self.payload(self.envelope()); payload['project_name'] = 'sk-' + 'A'*24
        with self.assertRaises(UIError): self.service.start(payload)
        payload = self.payload(self.envelope()); payload['envelope']['parameters']['model']['effective_length']['source'] = 'sk-' + 'A'*24
        with self.assertRaises(UIError): self.service.start(payload)
        self.assertFalse(list(self.service.jobs.glob('*.json')))

    def test_catalog_structured_declarations_and_optional_fields(self):
        catalog = load_plugins(ROOT/'plugins', PluginContext(self.root))
        binding = catalog.structured_web[0]
        paths = {f['path'] for f in binding.form()['modes'][0]['fields']}
        self.assertTrue({'parameters.model.materials.fc_MPa', 'parameters.model.materials.fy_compression_MPa',
                         'parameters.model.materials.tie_fy_MPa'} <= paths)
        self.assertEqual(catalog.web_owners[0]['id'], 'rc_floor')
        import core.plugin_loader as loader
        factory = loader._factory
        for variant in ('foreign_workflow', 'duplicate_operation', 'foreign_id'):
            def substituted(directory, manifest):
                actual = factory(directory, manifest)
                def build(context):
                    contribution = actual(context)
                    if manifest['id'] != 'rc_column': return contribution
                    original = contribution.structured_web[0]
                    if variant == 'foreign_workflow':
                        changed = replace(original, operations=(StructuredWebOperation('design', 'x', 'floor_design', 'design_floor'),))
                    elif variant == 'duplicate_operation': changed = replace(original, operations=original.operations*2)
                    else: changed = replace(original, id='other')
                    return replace(contribution, structured_web=(changed,))
                return build
            with patch.object(loader, '_factory', substituted), self.assertRaises(PluginLoadError):
                load_plugins(ROOT/'plugins', PluginContext(self.root))

    def test_legacy_and_structured_profession_identity_cannot_overlap(self):
        import core.plugin_loader as loader
        factory = loader._factory
        def substituted(directory, manifest):
            actual = factory(directory, manifest)
            def build(context):
                contribution = actual(context)
                if manifest['id'] != 'rc_floor': return contribution
                # This operation and tool belong to the floor contribution and
                # satisfy the structured workflow contract; only UI identity conflicts.
                binding = StructuredWebBinding('rc_floor', '重复楼盖专业',
                    (StructuredWebOperation('report', '计算书', 'artifact_report', 'generate_floor_report'),),
                    lambda: {}, lambda operation, envelope: envelope, lambda *args: {})
                return replace(contribution, structured_web=(binding,))
            return build
        with patch.object(loader, '_factory', substituted), self.assertRaises(PluginLoadError) as error:
            load_plugins(ROOT/'plugins', PluginContext(self.root))
        self.assertEqual(error.exception.code, 'duplicate_web_profession')


class ColumnHTTPTests(ColumnUIFixture):
    def test_missing_sql_and_bad_job_records_are_local_record_errors(self):
        job, view = self.run_local(self.envelope())
        second, latest = self.run_local(self.envelope())
        path = self.service._path(job)
        saved = loads_json(path.read_text(encoding='utf-8'))
        original_state = self.service.state.get(view['snapshot']['run_id'])
        server = LocalServer(self.service, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def get(path):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('GET', path, headers={'X-StructAgent-Token': server.token})
            response = connection.getresponse(); data = json.loads(response.read()); connection.close()
            return response.status, data
        with patch('core.tool_base.EngineeringTool.execute', side_effect=AssertionError('No tools on reading')):
            changed = deepcopy(saved); changed['run_id'] = 'f'*32
            write_json(path, changed)
            status, bad = get('/api/jobs/'+job)
            self.assertEqual(status, 200)
            self.assertEqual(bad['snapshot']['status'], 'invalid_output')
            self.assertFalse(bad['snapshot']['success'])
            self.assertIsNone(bad['summary']); self.assertIsNone(bad['check'])
            self.assertTrue(bad['check_issue']); self.assertFalse(bad['can_open'])
            self.assertNotEqual(bad['snapshot'].get('run_id'), latest['snapshot']['run_id'])
            self.assertEqual(self.service.state.get(view['snapshot']['run_id']), original_state)
            self.assertEqual(loads_json(path.read_text(encoding='utf-8')), changed)
            for damaged in [[], None, {'id': job}, {**saved, 'created': True},
                            {**saved, 'envelope': None}, {**saved, 'profession': []}]:
                write_json(path, damaged)
                code, error = get('/api/jobs/'+job)
                self.assertEqual(code, 409)
                self.assertEqual(error['code'], 'ui_record_invalid')
                self.assertIn('本机运行记录', error['error'])
                self.assertEqual(get('/health')[0], 200)
                self.assertEqual(get('/api/status?profession=rc_column')[0], 200)
            path.write_bytes(b'\xff')
            self.assertEqual(get('/api/jobs/'+job)[1]['code'], 'ui_record_invalid')
            path.unlink()
            self.assertEqual(get('/api/jobs/'+job)[1]['code'], 'ui_record_invalid')
            self.assertEqual(get('/api/jobs/'+second)[1]['snapshot']['run_id'], latest['snapshot']['run_id'])
        write_json(path, saved)

    def test_http_strict_import_and_direct_payload(self):
        server = LocalServer(self.service, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def post(path, value, raw=False):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            connection.request('POST', path, value if raw else json.dumps(value), headers={
                'X-StructAgent-Token': server.token, 'Origin': server.url, 'Content-Type': 'application/json'})
            response = connection.getresponse(); data = json.loads(response.read()); connection.close()
            return response.status, data
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}']:
            self.assertEqual(post('/api/jobs', raw, True)[0], 400)
        envelope = self.envelope()
        code, data = post('/api/structured-import', {'profession': 'rc_column', 'json': json.dumps(envelope)})
        self.assertEqual(code, 200); self.assertEqual(data['envelope'], envelope)
        envelope['parameters']['model']['section']['b_mm'] = True
        self.assertEqual(post('/api/structured-import', {'profession': 'rc_column', 'json': json.dumps(envelope)})[0], 400)
        code, job = post('/api/jobs', self.payload(self.envelope()))
        self.assertEqual(code, 202); self.finish()
        self.assertEqual(post('/api/jobs/'+job['id']+'/open-cad', {})[0], 409)
        self.assertEqual(post('/api/jobs/'+job['id']+'/generate-report', {})[0], 409)


if __name__ == '__main__':
    unittest.main()
