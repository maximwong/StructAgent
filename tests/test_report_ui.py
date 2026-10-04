"""Real design/check/DOCX with simulated CAD; UI corruption and HTTP contracts."""

from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.state import AgentState
from app import report_controller_factory
from core import ToolRegistry
from tools.floor.cad_adapter import FloorCADError
from tests.semantic_fixtures import floor_proposal
from tests.test_agent_controller import SimulatedCAD
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.plugin import register_floor_workflow
from tools.floor.report_presentation import floor_report_source, validate_floor_report
from ui.service import RunService, UIError
from ui.server import LocalServer, Handler

PAYLOAD = dict(project_name='计算书界面测试',text='设计6m×6m办公楼，C30，HRB400，活荷载2.0kN/m²。',template_confirmed=True)


class ReportUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'中文 输出'
        self.settings = Mock(return_value=SimpleNamespace(api_key='FAKE_TEST_KEY'))
        self.opener = Mock()
        self.service = self.make_service()
        self.job = self.service.start(PAYLOAD)['id']
        self.service.thread.join(20)
        self.assertFalse(self.service.thread.is_alive())
        self.assertTrue(self.service.view(self.job)['snapshot']['success'])
        self.addCleanup(self.finish)

    def finish(self):
        if self.service.thread:self.service.thread.join(90)

    def make_service(self):
        def factory(root):
            registry = ToolRegistry()
            workflow = register_floor_workflow(registry,root,cad_backend=SimulatedCAD())
            gateway = Mock();gateway.complete.return_value=(floor_proposal(),{})
            return AgentController(registry,ParameterParser(registry,gateway,[FloorDemoProfile()]),AgentState(root/'agent'),[workflow])
        return RunService(self.root,factory,settings_check=self.settings,recover=Mock(),opener=self.opener,
            report_factory=report_controller_factory,report_source=floor_report_source,report_validator=validate_floor_report)

    def generate(self):
        self.service.reports.start(self.job)
        self.service.thread.join(90)
        self.assertFalse(self.service.thread.is_alive())
        view = self.service.view(self.job)
        self.assertEqual(view['report']['status'],'completed',view['report'])
        return self.service.reports.artifact(self.job)

    def test_report_is_separate_repeatable_and_restored_without_cloud_or_redesign(self):
        before = self.service.view(self.job)['snapshot']
        original = {p:p.read_bytes() for p in (self.root/'agent'/before['run_id']).glob('*.json')}
        self.settings.side_effect=ValueError('API unavailable; report needs no API')
        with patch('tools.floor.design_tool.FloorDesignTool.execute',side_effect=AssertionError('No design')):
            first = self.generate()
            checksum = hashlib.sha256(first['content']).hexdigest()
            self.service.reports.open(self.job)
            self.opener.assert_called_once_with(str(first['path']))
            second = self.generate()
        self.assertNotEqual(first['path'],second['path'])
        self.assertEqual(hashlib.sha256(first['path'].read_bytes()).hexdigest(),checksum)
        self.assertEqual(self.service.view(self.job)['snapshot'],before)
        for path,content in original.items():self.assertEqual(path.read_bytes(),content)
        restored = self.make_service()
        self.assertEqual(restored.view(self.job)['snapshot'],before)
        self.assertEqual(restored.reports.artifact(self.job)['content'],second['content'])
        self.assertEqual(len(restored.status()['jobs']),1)

    def test_corrupt_artifacts_receipt_request_and_source_disable_all_file_actions(self):
        artifact = self.generate()
        request_path = next((self.root/'ui'/'report-jobs'/self.job).glob('*.json'))
        request = json.loads(request_path.read_text(encoding='utf-8'))
        report_path = self.root/'agent'/request['run_id']/'report.json'
        design_path = self.root/'agent'/request['source_run_id']/'design.json'
        for path in (artifact['path'],artifact['path'].with_name('input.json'),artifact['path'].with_name('report_manifest.json'),
                     report_path,request_path,design_path):
            original = path.read_bytes()
            path.write_bytes(b'corrupted')
            view=self.service.view(self.job)
            self.assertFalse(view['report']['can_download'],str(path))
            self.assertFalse(view['report']['can_open'])
            with self.assertRaises(UIError):self.service.reports.artifact(self.job)
            with self.assertRaises(UIError):self.service.reports.open(self.job)
            path.write_bytes(original)
        for field,value in [('source_run_id','a'*32),('source',{'request':{'project_id':'other'}})]:
            altered=deepcopy(request);altered[field]=value
            request_path.write_text(json.dumps(altered),encoding='utf-8')
            self.assertFalse(self.service.view(self.job)['report']['can_download'])
            with self.assertRaises(UIError):self.service.reports.artifact(self.job)
        request_path.write_text(json.dumps(request),encoding='utf-8')
        receipt=json.loads(report_path.read_text(encoding='utf-8'))
        changed=deepcopy(receipt);changed['artifacts'][0]['path']=str(Path(__file__))
        report_path.write_text(json.dumps(changed),encoding='utf-8')
        with self.assertRaises(UIError):self.service.reports.artifact(self.job)
        report_path.write_text(json.dumps(receipt),encoding='utf-8')
        self.opener.assert_not_called()
        self.assertTrue(self.service.reports.artifact(self.job)['content'])

    def test_missing_or_failed_check_blocks_generation_and_primary_status_is_preserved(self):
        original=self.service.view(self.job)['snapshot']
        call=next(c for c in original['tool_calls'] if c['step']=='check')
        path=Path(call['result_path']);data=path.read_bytes()
        path.write_text('{}',encoding='utf-8')
        self.assertFalse(self.service.view(self.job)['report']['can_generate'])
        with self.assertRaises(UIError):self.service.reports.start(self.job)
        self.assertFalse((self.root/'ui'/'report-jobs').exists())
        path.write_bytes(data)
        # CAD unavailable is terminal and read-only reporting can still use its valid design.
        snapshot=self.service.state.begin('cad-failed-qa')
        self.assertFalse(self.service.reports.view({'id':'a'*32},snapshot)['can_generate'])
        snapshot.update(status='failed');self.service.state.save(snapshot,'FAILED')
        self.assertEqual(self.service.view(self.job)['snapshot'],original)

    def test_cad_unavailable_does_not_prevent_report_of_valid_design(self):
        def factory(root):
            registry=ToolRegistry();backend=Mock()
            backend.execute.side_effect=FloorCADError('cad_unavailable','Simulated unavailable CAD; no desktop touched.')
            workflow=register_floor_workflow(registry,root,cad_backend=backend)
            gateway=Mock();gateway.complete.return_value=(floor_proposal(),{})
            return AgentController(registry,ParameterParser(registry,gateway,[FloorDemoProfile()]),AgentState(root/'agent'),[workflow])
        self.service.controller_factory=factory
        self.job=self.service.start(PAYLOAD)['id'];self.service.thread.join(20)
        snapshot=self.service.view(self.job)['snapshot']
        self.assertFalse(snapshot['success']);self.assertEqual(snapshot['errors'][0]['code'],'cad_unavailable')
        self.assertTrue(self.service.view(self.job)['report']['can_generate'])
        self.generate()
        self.assertEqual(self.service.view(self.job)['snapshot'],snapshot)
        self.assertFalse(self.service.view(self.job)['can_open'])

    def test_report_link_write_failure_cannot_expose_completed_artifact(self):
        import ui.report_service as module
        real_write=module.write_json
        def fail_completion(path,data,**kwargs):
            if data.get('status') in ('completed','failed'):
                raise OSError('Simulated linkage publication failure')
            return real_write(path,data,**kwargs)
        with patch.object(module,'write_json',side_effect=fail_completion):
            self.service.reports.start(self.job);self.finish()
        view=self.service.view(self.job)
        self.assertEqual(view['report']['status'],'failed')
        self.assertFalse(view['report']['can_download'])
        with self.assertRaises(UIError):self.service.reports.artifact(self.job)
        restored=self.make_service()
        self.assertEqual(restored.view(self.job)['report']['status'],'interrupted')
        with self.assertRaises(UIError):restored.reports.artifact(self.job)
        self.assertTrue(list((self.root/'reports').glob('*/floor_report.docx')))

    def test_failures_are_sanitized_thread_failure_and_unconfirmed_completion_cannot_download(self):
        self.service.reports.factory=Mock(side_effect=RuntimeError('FAKE_TEST_KEY'))
        self.service.reports.start(self.job);self.finish()
        view=self.service.view(self.job)
        self.assertEqual(view['report']['status'],'failed')
        self.assertNotIn('FAKE_TEST_KEY',json.dumps(view))
        self.assertFalse(view['report']['can_download'])
        with patch('ui.report_service.threading.Thread') as worker:
            worker.return_value.start.side_effect=RuntimeError('FAKE_TEST_KEY')
            with self.assertRaises(UIError):self.service.reports.start(self.job)
        self.assertIsNone(self.service.active)
        self.assertEqual(self.service.view(self.job)['report']['status'],'failed')
        # Interrupted persisted intent is never resumed or treated as a completed report.
        records=list((self.root/'ui'/'report-jobs'/self.job).glob('*.json'))
        for path in records:
            data=json.loads(path.read_text(encoding='utf-8'));data['status']='running';path.write_text(json.dumps(data),encoding='utf-8')
        restored=self.make_service()
        self.assertEqual(restored.view(self.job)['report']['status'],'interrupted')
        with self.assertRaises(UIError):restored.reports.artifact(self.job)

    def test_active_report_blocks_mutations_and_primary_run_remains_visible(self):
        entered,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def factory(root,envelope):
            def run(*args,**kwargs):
                snapshot=AgentState(root/'agent').begin(envelope['project_id'])
                entered.set();release.wait(10)
                snapshot.update(status='failed');self.service.state.save(snapshot,'FAILED')
                return snapshot
            return SimpleNamespace(run=run)
        self.service.reports.factory=factory
        primary=self.service.view(self.job)['snapshot']
        self.service.reports.start(self.job);self.assertTrue(entered.wait(5))
        self.assertEqual(self.service.view(self.job)['snapshot'],primary)
        self.assertEqual(self.service.view(self.job)['report']['status'],'running')
        for action in (lambda:self.service.start(PAYLOAD),lambda:self.service.reports.start(self.job),
                       lambda:self.service.reports.open(self.job),self.service.prepare_shutdown,self.service.start_recovery):
            with self.assertRaises(UIError):action()
        restored=self.make_service()
        with self.assertRaises(UIError):restored.reports.start(self.job)
        release.set();self.finish()
        self.assertEqual(self.service.view(self.job)['report']['status'],'failed')

    def test_http_requires_session_and_origin_and_returns_validated_docx_attachment(self):
        self.generate()
        server=LocalServer(self.service,0)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            def request(path,method='GET',payload=None,headers=None):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                standard={'X-StructAgent-Token':server.token,'Origin':server.url,'Content-Type':'application/json'}
                standard.update(headers or {})
                connection.request(method,path,body=None if payload is None else json.dumps(payload),headers=standard)
                response=connection.getresponse();content=response.read();result=(response.status,dict(response.getheaders()),content)
                connection.close();return result
            base='/api/jobs/'+self.job
            for headers in ({'X-StructAgent-Token':'bad'},{'Host':'evil.example'}):
                self.assertEqual(request(base+'/report-download',headers=headers)[0],403)
            self.assertEqual(request(base+'/open-report','POST',{}, {'Origin':'http://evil.example'})[0],403)
            self.assertEqual(request(base+'/generate-report','POST',{'path':str(Path(__file__))})[0],400)
            self.assertEqual(request('/api/jobs/../../.env/report-download')[0],409)
            code,headers,body=request(base+'/report-download')
            self.assertEqual(code,200);self.assertEqual(body,self.service.reports.artifact(self.job)['content'])
            self.assertIn('attachment',headers['Content-Disposition'])
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertEqual(request(base+'/open-report','POST',{})[0],200)
            self.opener.assert_called_once()
            self.assertEqual(request(base+'/generate-report','POST',{})[0],202)
            self.finish()
        finally:
            server.shutdown();server.server_close();worker.join(5)


class DownloadDisconnectTests(unittest.TestCase):
    def test_disconnected_headers_or_body_end_connection_without_retry(self):
        for phase in ('headers','body'):
            handler=Handler.__new__(Handler)
            handler.request_version='HTTP/1.1'
            handler.requestline='GET /api/jobs/test/report-download HTTP/1.1'
            handler.close_connection=False
            handler.wfile=Mock()
            handler.wfile.write.side_effect=([ConnectionAbortedError('simulated closed connection')]
                if phase=='headers' else [None,ConnectionResetError('simulated download cancellation')])
            handler.reply(200,b'validated DOCX bytes',headers={'Content-Disposition':'attachment; filename="report.docx"'})
            self.assertTrue(handler.close_connection)
            self.assertEqual(handler.wfile.write.call_count,1 if phase=='headers' else 2)


if __name__=='__main__':unittest.main()
