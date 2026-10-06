"""Separate report executions, using injected professional contracts and Controller."""

from copy import deepcopy
import json
import re
import threading
import time
from uuid import uuid4

from core.persistence import write_json
from .service import UIError


class ReportService:
    def __init__(self, service, factory, source, validator):
        self.service, self.factory, self.source, self.validator = service, factory, source, validator
        self.root = service.root/'ui'/'report-jobs'
        self.failures = {}

    def _source(self, record, snapshot):
        if record.get('input_mode') == 'structured':
            raise UIError('此专业未提供计算书操作。', 409)
        return self.source(self.service.root, snapshot, self.service._read_tool_result)

    def _records(self, job_id):
        self.service._path(job_id)  # Same opaque job identity contract.
        records = []
        for path in (self.root/job_id).glob('*.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(data.get('id'),str) or re.fullmatch(r'[0-9a-f]{32}',data['id']) is None
                    or path.name != data['id']+'.json' or data.get('job_id') != job_id):
                raise ValueError('Invalid report request identity.')
            records.append(data)
        return sorted(records, key=lambda item:item['created'])

    def start(self, job_id):
        s = self.service
        with s.lock:
            s._ensure_idle()
            record = s._record(job_id)
            snapshot = s._snapshot(record)
            try:
                source = self._source(record,snapshot)
            except Exception:
                raise UIError('本次设计及独立校核尚未通过，或记录不完整，无法生成计算书。',409) from None
            # Pin the original design run before starting another run for the same project.
            # The original SQL snapshot and its result files remain unchanged.
            record['run_id'] = snapshot['run_id']
            write_json(s._path(job_id),record)
            request = dict(id=uuid4().hex,job_id=job_id,source_run_id=snapshot['run_id'],
                           created=time.time(),status='running',source=source)
            path = self.root/job_id/(request['id']+'.json')
            write_json(path,request,exclusive=True)
            s.active = job_id
            s.thread = threading.Thread(target=self._run,args=(request,path),name='structagent-report',daemon=False)
            try:
                s.thread.start()
            except Exception:
                s.active = None
                request.update(status='failed',message='无法启动计算书任务，请重新打开程序。')
                self.failures[request['id']] = deepcopy(request)
                write_json(path,request)
                raise UIError(request['message'],500) from None
            return {'id':request['id']}

    def _run(self, request, path):
        s = self.service
        try:
            envelope = request['source']['request']
            result = self.factory(s.root,deepcopy(envelope)).run('生成已存方案计算书',project_id=envelope['project_id'])
            request['run_id'] = result.get('run_id')
            if not result.get('success'):
                request.update(status='failed',message='计算书生成未完成，后续操作已停止；可保留记录后重新生成。')
            else:
                self._artifact(request)
                request.update(status='completed')
            write_json(path,request)
        except Exception:
            request.update(status='failed',message='无法确认计算书及记录完整，请保留本次记录供检查。')
            with s.lock:
                self.failures[request['id']] = deepcopy(request)
            try:
                write_json(path,request)
            except OSError:
                pass  # No download from an unconfirmed or unlinked execution.
        finally:
            with s.lock:
                s.active = None

    def _artifact(self, request):
        s = self.service
        record = s._record(request['job_id'])
        original = s._snapshot(record)
        if original['run_id'] != request['source_run_id'] or self._source(record,original) != request['source']:
            raise ValueError('Source run or evidence changed.')
        run_id = request['run_id']
        if not isinstance(run_id,str) or re.fullmatch(r'[0-9a-f]{32}',run_id) is None:
            raise ValueError('Invalid report run identity.')
        snapshot = s.state.get(run_id)
        calls = snapshot.get('tool_calls',[])
        if (snapshot.get('success') is not True or snapshot.get('status') != 'completed'
                or snapshot.get('persistence_state') != 'COMPLETED'
                or snapshot.get('external_started') or snapshot.get('workflow') != 'artifact_report'
                or snapshot.get('project_id') != record['project_id'] or len(calls) != 1
                or calls[0].get('tool') != request['source']['request']['tool']
                or calls[0].get('step') != 'report'
                or snapshot.get('parse_result',{}).get('envelope') != request['source']['request']):
            raise ValueError('Report execution provenance differs.')
        payload = s._read_tool_result(calls[0],snapshot)
        return self.validator(s.root,payload,request['source'])

    def view(self, record, snapshot):
        can_generate = False
        try:
            self._source(record,snapshot)
            can_generate = self.service.active is None and not self.service.stopping
        except Exception:
            pass
        result = dict(status='not_started',can_generate=can_generate,can_open=False,can_download=False,
                      message='设计及独立校核通过后可生成Word计算书。')
        try:
            records = self._records(record['id'])
            if not records:
                return result
            request = self.failures.get(records[-1]['id'],records[-1])
            result.update(id=request['id'],status=request['status'],run_id=request.get('run_id'))
            if request['status'] == 'running':
                active = self.service.active == record['id']
                result.update(status='running' if active else 'interrupted',
                    message='正在只读校核并生成计算书……' if active else '计算书运行已中断，不会自动重新生成；请检查记录后新建任务。')
            elif request['status'] == 'completed':
                artifact = self._artifact(request)
                result.update(summary=artifact['summary'],tool=request['source']['request']['tool'],can_open=can_generate,can_download=True,
                    message='Word计算书已生成并通过文件校验。目录和页码可在Word中选择全文后按F9更新。')
            else:
                result['message'] = request.get('message','计算书生成未完成，请保留记录。')
        except Exception:
            result.update(status='invalid',can_open=False,can_download=False,
                          message='计算书或记录不可用、归属或校验和不一致，禁止打开和下载；不会自动重算。')
        return result

    def artifact(self, job_id):
        s = self.service
        with s.lock:
            try:
                s._record(job_id)
                records = self._records(job_id)
                if not records or records[-1]['status'] != 'completed' or records[-1]['id'] in self.failures:
                    raise ValueError('No completed report.')
                return self._artifact(records[-1])
            except Exception:
                raise UIError('本次没有可用的已验证计算书，或文件与记录不一致。',409) from None

    def open(self, job_id):
        with self.service.lock:
            self.service._ensure_idle()
            artifact = self.artifact(job_id)
            try:
                self.service.opener(str(artifact['path']))
            except OSError:
                raise UIError('无法打开计算书，请安装Word或下载后用兼容软件打开。',500) from None
            return {'success':True}
