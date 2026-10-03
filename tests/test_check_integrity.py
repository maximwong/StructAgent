"""Saved result corruption must not break polling or present a false PASS."""

from copy import deepcopy
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from core import ToolResult
from tools.floor.check_adapter import COVERAGE, validate_report
from ui.server import LocalServer
from ui.service import RunService, UIError


class CheckIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.opener = Mock()
        self.service = RunService(self.root, Mock(), settings_check=lambda: SimpleNamespace(api_key='TEST'),
                                  recover=Mock(), opener=self.opener)
        self.job = uuid4().hex
        self.service._path(self.job).write_text(json.dumps(dict(id=self.job, project_id='qa',
            project_name='QA', text='test', profile='office_floor_demo_v1', created=0)), encoding='utf-8')
        self.snapshot = self.service.state.begin('qa')
        ref = 'floor-' + 'a'*32
        self.report = dict(status='PASS', checks=[dict(id='slab.0.flexure', member='slab', section=0,
            label='test comparison', actual=10, relation='>=', limit=5, unit='kN·m', passed=True,
            source='test fixture')], summary=dict(total=1, passed=1, failed=0))
        self.data = ToolResult(True, 'check_floor_design', '1.0.0',
            result={**deepcopy(self.report), 'coverage':deepcopy(COVERAGE), 'design_result_ref':ref},
            metadata=dict(project_id='qa', design_result_ref=ref, scope_version='section-check-v1')).to_dict()
        self.path = Path(self.service.state.publish_result(self.snapshot['run_id'], 'check', self.data))
        self.drawing = self.root/'test.dwg'
        self.drawing.write_bytes(b'SIMULATED DWG - never opened')
        self.snapshot.update(success=True, status='completed', steps={'check':'completed','cad':'completed'},
            tool_calls=[dict(step='check', tool='check_floor_design', version='1.0.0', status='completed', result_path=str(self.path))],
            artifacts=[dict(type='dwg',path=str(self.drawing))])
        self.service.state.save(self.snapshot, 'COMPLETED')

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def assert_unavailable(self):
        before = self.path.read_bytes()
        view = self.service.view(self.job)
        self.assertIsNone(view['check'])
        self.assertTrue(view['check_issue'])
        self.assertFalse(view['can_open'])
        with self.assertRaises(UIError): self.service.open_drawing(self.job)
        self.opener.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.state.get(self.snapshot['run_id'])['status'], 'completed')
        self.assertEqual(self.drawing.read_bytes(), b'SIMULATED DWG - never opened')

    def test_valid_pass_and_domain_fail_are_presented_without_recalculation(self):
        view = self.service.view(self.job)
        self.assertEqual(view['check']['status'], 'PASS')
        self.assertIsNone(view['check_issue'])
        self.assertTrue(view['can_open'])
        data = deepcopy(self.data)
        data.update(success=False, errors=[dict(code='design_check_failed',message='test failure',path=[])])
        data['result'].update(status='FAIL', summary=dict(total=1,passed=0,failed=1))
        data['result']['checks'][0].update(actual=1,passed=False)
        self.write(data)
        snapshot = deepcopy(self.snapshot)
        snapshot.update(success=False,status='failed',steps={'check':'failed','cad':'skipped'})
        snapshot['tool_calls'][0]['status']='failed'
        with patch.object(self.service,'_snapshot',return_value=snapshot):
            view = self.service.view(self.job)
            self.assertEqual(view['check']['status'],'FAIL')
            self.assertIsNone(view['check_issue'])
            self.assertFalse(view['can_open'])

    def test_null_lists_invalid_json_and_missing_files_cannot_crash_reader(self):
        for result in (None, [], {}, 'PASS'):
            with self.subTest(result=result):
                self.write({**self.data,'result':result})
                self.assert_unavailable()
        self.path.write_text('{',encoding='utf-8')
        self.assert_unavailable()
        self.path.unlink()
        self.assertTrue(self.service.view(self.job)['check_issue'])

    def test_bad_counts_verdicts_numbers_and_coverage_are_not_displayed(self):
        mutations = [lambda d:d['result']['summary'].update(passed=0),
            lambda d:d['result']['checks'][0].update(actual=1),
            lambda d:d['result']['checks'][0].update(actual=True),
            lambda d:d['result']['checks'][0].update(actual=float('nan')),
            lambda d:d['result']['checks'][0].update(actual=10**400),
            lambda d:d['result']['checks'][0].update(actual='10'),
            lambda d:d['result']['coverage'].update(not_checked=[]),
            lambda d:d['metadata'].update(project_id='other'),
            lambda d:d.update(tool='another_tool'),
            lambda d:d['metadata'].update(design_result_ref='floor-'+'b'*32)]
        for mutation in mutations:
            data=deepcopy(self.data);mutation(data);self.write(data)
            with self.subTest(data=data): self.assert_unavailable()

    def test_paths_are_bound_to_run_and_step_and_invalid_paths_are_handled(self):
        other=self.root/'other.json';other.write_bytes(self.path.read_bytes())
        for path in (None,123,str(other),'bad\0path'):
            snapshot=deepcopy(self.snapshot);snapshot['tool_calls'][0]['result_path']=path
            with self.subTest(path=path),patch.object(self.service,'_snapshot',return_value=snapshot):
                self.assert_unavailable()

    def test_missing_duplicate_and_running_calls_cannot_enable_completed_drawing(self):
        for calls in ([],self.snapshot['tool_calls']*2,[{**self.snapshot['tool_calls'][0],'status':'running'}]):
            snapshot=deepcopy(self.snapshot);snapshot['tool_calls']=calls
            with self.subTest(calls=calls),patch.object(self.service,'_snapshot',return_value=snapshot):
                self.assert_unavailable()

    def test_legacy_history_has_no_invented_check_and_keeps_open_behavior(self):
        snapshot=deepcopy(self.snapshot);snapshot['steps'].pop('check');snapshot['tool_calls']=[]
        with patch.object(self.service,'_snapshot',return_value=snapshot):
            view=self.service.view(self.job)
            self.assertIsNone(view['check']);self.assertIsNone(view['check_issue'])
            self.assertTrue(view['can_open'])

    def test_bad_record_returns_http_200_with_issue_and_open_returns_409(self):
        self.write({**self.data,'result':None})
        server=LocalServer(self.service,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for method,suffix,expected in [('GET','',200),('POST','/open-cad',409)]:
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                connection.request(method,'/api/jobs/'+self.job+suffix,body='{}' if method=='POST' else None,
                    headers={'X-StructAgent-Token':server.token,'Origin':server.url,'Content-Type':'application/json'})
                response=connection.getresponse();data=json.loads(response.read());connection.close()
                self.assertEqual(response.status,expected)
                if method=='GET':self.assertTrue(data['check_issue']);self.assertIsNone(data['check'])
        finally:
            server.shutdown();server.server_close();thread.join(5)

    def test_protocol_verdict_validation_rejects_false_pass_and_duplicate_ids(self):
        bad=deepcopy(self.report);bad['checks'][0]['actual']=0
        with self.assertRaises(ValueError):validate_report(bad)
        bad=deepcopy(self.report);bad['checks']*=2;bad['summary']=dict(total=2,passed=2,failed=0)
        with self.assertRaises(ValueError):validate_report(bad)

    def test_server_port_is_exclusive_and_reusable_after_close(self):
        first=LocalServer(self.service,0)
        port=first.server_port
        try:
            with self.assertRaises(OSError): LocalServer(self.service,port)
        finally:first.server_close()
        restarted=LocalServer(self.service,port)
        restarted.server_close()


if __name__=='__main__': unittest.main()
