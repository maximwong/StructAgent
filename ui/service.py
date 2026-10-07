"""Single-operation UI service backed by authoritative AgentState records."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from uuid import uuid4

from agent.state import AgentState
from core.persistence import write_json
from core.validation import ensure_json
from core.exceptions import ToolValidationError
from core import ToolResult
from core.json_data import loads_json
from .check_presentation import present_check


class UIError(ValueError):
    def __init__(self, message, status=400, code=None):
        self.status = status
        self.code = code
        super().__init__(message)


class RunService:
    def __init__(self, root, controller_factory, *, settings_check, recover, opener=None,
                 explicit_controller_factory=None, input_form=None,
                 report_factory=None, report_source=None, report_validator=None,
                 template_profile="office_floor_demo_v1", explicit_profile="floor_explicit_v1",
                 structured_bindings=(), structured_controller_factory=None, legacy_profession=None):
        self.root = Path(root).resolve()
        self.jobs = self.root / "ui" / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.state = AgentState(self.root / "agent")
        self.controller_factory = controller_factory
        self.structured_bindings = {binding.id: binding for binding in structured_bindings}
        self.structured_controller_factory = structured_controller_factory
        self.legacy_profession = deepcopy(legacy_profession or {'id': 'rc_floor', 'name': '钢筋混凝土楼盖'})
        self.explicit_controller_factory, self.input_form = explicit_controller_factory, input_form
        self.template_profile, self.explicit_profile = template_profile, explicit_profile
        self.settings_check, self.recover = settings_check, recover
        self.opener = opener or os.startfile
        self.lock = threading.RLock()
        self.active = None
        self.thread = None
        self.recovery = None
        self.stopping = False
        self.failures = {}
        self.reports = None
        if any(item is not None for item in (report_factory, report_source, report_validator)):
            if any(item is None for item in (report_factory, report_source, report_validator)):
                raise ValueError('Report composition requires factory, source and validator.')
            from .report_service import ReportService
            self.reports = ReportService(self,report_factory,report_source,report_validator)

    def configuration(self, profession=None):
        if profession in self.structured_bindings:
            return {'ready': True, 'message': '本地结构化计算已就绪，无需API或CAD。'}
        try:
            self.settings_check()
            return {"ready": True, "message": "DeepSeek已配置"}
        except ValueError:
            return {"ready": False, "message": "请先在本机 .env 配置有效的DeepSeek API，保存后重新开始。"}

    def _path(self, job_id):
        if not isinstance(job_id, str) or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            raise UIError("找不到这次运行。", 404)
        return self.jobs / (job_id + ".json")

    def _record(self, job_id):
        path = self._path(job_id)
        try:
            record = loads_json(path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or record.get('id') != job_id
                    or any(not isinstance(record.get(key), str) or not record[key].strip()
                           for key in ('project_name', 'project_id'))
                    or type(record.get('created')) not in (int, float)
                    or 'run_id' in record and (not isinstance(record['run_id'], str)
                        or re.fullmatch(r'[0-9a-f]{32}', record['run_id']) is None)):
                raise ValueError('Invalid job identity or shape.')
            if record.get('input_mode') == 'structured':
                profession, envelope = record.get('profession'), record.get('envelope')
                if (not isinstance(profession, str) or profession not in self.structured_bindings
                        or not isinstance(record.get('operation'), str)
                        or record['operation'] not in {o.id for o in self.structured_bindings[profession].operations}
                        or not isinstance(envelope, dict) or envelope.get('project_id') != record['project_id']
                        or not isinstance(envelope.get('context'), dict)
                        or not isinstance(envelope.get('parameters'), dict)):
                    raise ValueError('Invalid structured job shape.')
            else:
                # Existing floor jobs omit input_mode. A damaged structured job
                # must not fall back to the floor presenter and its CAD wording.
                if ('input_mode' in record
                        or any(key in record for key in ('profession', 'operation', 'envelope'))
                        or not isinstance(record.get('text'), str) or not record['text'].strip()
                        or record.get('profile') not in (self.template_profile, self.explicit_profile)
                        or record['profile'] == self.explicit_profile and not isinstance(record.get('model'), dict)):
                    raise ValueError('Invalid legacy job shape.')
            return record
        except (OSError, ValueError, TypeError, KeyError):
            raise UIError("本机运行记录不可读取或结构不完整，请保留记录供检查。", 409, 'ui_record_invalid') from None

    @staticmethod
    def _unconfirmed_snapshot():
        message = '本次绑定的运行记录缺失或无法确认，不能显示通过；请保留本机记录供检查。'
        return {'status': 'invalid_output', 'success': False, 'steps': {}, 'tool_calls': [],
                'artifacts': [], 'warnings': [], 'errors': [{'code': 'ui_record_invalid', 'message': message, 'path': []}],
                'record_issue': message}

    def _ensure_idle(self):
        if self.stopping:
            raise UIError("程序正在退出，请重新打开。", 409)
        if self.active is not None:
            raise UIError("已有任务正在执行，请等待完成，不要重复提交。", 409)
        # A previous server may have been force-closed; never run over a live owner.
        self.state.store.reconcile()
        if self.state.store.list_runs(state="RUNNING"):
            raise UIError("同一输出目录还有正在执行的任务，请等待原任务结束。", 409)

    def start(self, payload):
        if isinstance(payload, dict) and payload.get('input_mode') == 'structured':
            return self._start_structured(payload)
        explicit = isinstance(payload, dict) and payload.get("input_mode") == "explicit"
        expected = {"project_name", "text", "input_mode", "model"} if explicit else {"project_name", "text", "template_confirmed"}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise UIError("请提供项目名称、设计要求和完整工程参数。" if explicit else "请填写项目名称、设计要求并确认演示模板。")
        if explicit and self.explicit_controller_factory is None:
            raise UIError("本机尚未启用完整参数模式。")
        name, text = payload["project_name"], payload["text"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise UIError("项目名称请填写1至80个字符。")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise UIError("设计要求请填写1至4000个字符。")
        if not explicit and payload["template_confirmed"] is not True:
            raise UIError("请先确认使用办公楼演示模板。")
        try:
            ensure_json(payload)
        except ToolValidationError:
            raise UIError("完整参数必须为有限数值和标准JSON数据。") from None
        try:
            settings = self.settings_check()
        except ValueError:
            raise UIError(self.configuration()["message"]) from None
        if settings.api_key in json.dumps(payload, ensure_ascii=False):
            raise UIError("设计要求和项目名称中不能包含API密钥，请删除后提交。")
        with self.lock:
            self._ensure_idle()
            job_id = uuid4().hex
            record = {"id": job_id, "project_name": name.strip(), "text": text.strip(),
                      "project_id": name.strip() + "-" + job_id[:8], "created": time.time(),
                      "profile": self.explicit_profile if explicit else self.template_profile}
            if explicit:
                record["model"] = deepcopy(payload["model"])
            write_json(self._path(job_id), record, exclusive=True)
            self.active = job_id
            self.thread = threading.Thread(target=self._run, args=(record,), name="structagent-workflow", daemon=False)
            try:
                self.thread.start()
            except Exception:
                self.active = None
                raise UIError("无法启动任务，请重新打开程序。", 500) from None
        return {"id": job_id}

    def professions(self):
        return {'professions': [{**self.legacy_profession, 'kind': 'cloud'}] + [
            {'id': b.id, 'name': b.name, 'kind': 'structured', 'form': b.form(),
             'operations': [{'id': o.id, 'name': o.name} for o in b.operations]}
            for b in self.structured_bindings.values()]}

    def validate_structured(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'profession', 'operation', 'envelope'}
                or not isinstance(payload.get('profession'), str) or not isinstance(payload.get('operation'), str)
                or payload.get('profession') not in self.structured_bindings):
            raise UIError('请选择已加载的专业并提供完整请求。')
        binding = self.structured_bindings[payload['profession']]
        envelope = payload['envelope']
        try:
            ensure_json(envelope)
            # This format guard does not read the user's local configuration or credentials.
            if re.search(r'sk-[A-Za-z0-9_-]{16,}', json.dumps(envelope, ensure_ascii=False)):
                raise UIError('工程输入不能包含API密钥，请删除后提交。')
            return binding.request(payload['operation'], envelope)
        except ToolValidationError as exc:
            parts = []
            descriptors = {field['path']: field for mode in binding.form()['modes'] for field in mode['fields']}
            for error in exc.errors:
                path = '.'.join(map(str, error.get('path', [])))
                field = descriptors.get(path)
                title = (field['group'] + ' · ' + field['label'] + '（' + path + '）') if field else path
                parts.append((title + '：' if title else '') + '缺项、类型、取值或适用范围不符合要求。')
            raise UIError('请检查工程参数：' + '；'.join(parts)) from None

    def import_structured(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'profession', 'json'}
                or not isinstance(payload['json'], str) or not isinstance(payload['profession'], str)):
            raise UIError('请导入完整JSON请求。')
        try:
            envelope = loads_json(payload['json'].lstrip('\ufeff'))
        except (ValueError, TypeError):
            raise UIError('JSON格式无效：请检查重复字段、非有限数值和语法。') from None
        binding = self.structured_bindings.get(payload['profession'])
        if binding is None:
            raise UIError('请选择已加载的专业。')
        operation = next((o.id for o in binding.operations if isinstance(envelope, dict) and o.tool == envelope.get('tool')), None)
        envelope = self.validate_structured({'profession': binding.id, 'operation': operation, 'envelope': envelope})
        return {'operation': operation, 'envelope': envelope}

    def _start_structured(self, payload):
        if set(payload) != {'input_mode', 'profession', 'operation', 'project_name', 'envelope'}:
            raise UIError('请提供专业、操作、项目名称和完整工程请求。')
        name = payload['project_name']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise UIError('项目名称请填写1至80个字符。')
        if re.search(r'sk-[A-Za-z0-9_-]{16,}', name):
            raise UIError('项目名称不能包含API密钥，请删除后提交。')
        envelope = self.validate_structured({k: payload[k] for k in ('profession', 'operation', 'envelope')})
        if self.structured_controller_factory is None:
            raise UIError('本机尚未启用结构化流程。')
        with self.lock:
            self._ensure_idle()
            job_id = uuid4().hex
            record = {'id': job_id, 'project_name': name.strip(), 'project_id': envelope['project_id'],
                      'created': time.time(), 'profession': payload['profession'], 'operation': payload['operation'],
                      'input_mode': 'structured', 'envelope': envelope}
            write_json(self._path(job_id), record, exclusive=True)
            self.active = job_id
            self.thread = threading.Thread(target=self._run, args=(record,), name='structagent-local', daemon=False)
            try:
                self.thread.start()
            except Exception:
                self.active = None
                raise UIError('无法启动任务，请重新打开程序。', 500) from None
        return {'id': job_id}

    def _run(self, record):
        try:
            if record.get('input_mode') == 'structured':
                operation = next(o for o in self.structured_bindings[record['profession']].operations if o.id == record['operation'])
                def pin(run_id):
                    with self.lock:
                        record['run_id'] = run_id
                        write_json(self._path(record['id']), record)
                controller = self.structured_controller_factory(self.root, deepcopy(record['envelope']), operation, pin)
                result = controller.run('完整本地结构化请求', project_id=record['project_id'])
            else:
                controller = (self.explicit_controller_factory(self.root, deepcopy(record["model"]))
                          if record["profile"] == self.explicit_profile else self.controller_factory(self.root))
                result = controller.run(record["text"], project_id=record["project_id"], profile_name=record["profile"])
            if result.get('run_id'):
                with self.lock:
                    record['run_id'] = result['run_id']
                    write_json(self._path(record['id']), record)
        except Exception:
            result = {"success": False, "status": "error", "errors": [
                {"code": "ui_start_failed", "message": "无法启动设计流程，请检查本机配置与输出目录。"}], 'state_saved': False}
        finally:
            # The SQL record remains authoritative. This fallback records setup/persistence failure only.
            try:
                if not result.get("success"):
                    failure = {
                        "success": False, "status": result.get("status", "error"), "errors": result.get("errors", []),
                        "state_saved": result.get("state_saved", True)}
                    with self.lock:
                        self.failures[record["id"]] = failure
                    write_json(self.jobs / (record["id"] + ".failure.json"), failure)
            except OSError:
                pass  # Preserve in-memory failure; SQL still governs external recovery.
            finally:
                with self.lock:
                    self.active = None

    def _snapshot(self, record):
        failure = self.jobs / (record['id'] + '.failure.json')
        if record.get('input_mode') == 'structured' and (record['id'] in self.failures or failure.is_file()):
            fallback = deepcopy(self.failures[record['id']]) if record['id'] in self.failures else loads_json(failure.read_text(encoding='utf-8'))
            if not record.get('run_id') or fallback.get('state_saved') is False:
                return fallback
        if record.get('run_id'):
            try:
                snapshot = self.state.get(record['run_id'])
                if snapshot['project_id'] != record['project_id']:
                    raise ValueError('Run project differs.')
                return snapshot
            except (KeyError, ValueError, TypeError, AttributeError, OSError, sqlite3.Error):
                return self._unconfirmed_snapshot()
        if record.get('input_mode') == 'structured':
            return {'status': 'queued' if self.active == record['id'] else 'interrupted', 'success': False,
                    'steps': {}, 'tool_calls': [], 'artifacts': [], 'errors': [], 'warnings': []}
        runs = self.state.store.list_runs(record["project_id"])
        if runs:
            snapshot = self.state.get(runs[-1]["run_id"])
            if snapshot.get("status") != "running":
                return snapshot
            if self.active == record["id"]:
                return snapshot
        failure = self.jobs / (record["id"] + ".failure.json")
        if record["id"] in self.failures:
            return deepcopy(self.failures[record["id"]])
        if failure.is_file():
            return json.loads(failure.read_text(encoding="utf-8"))
        if runs:
            return snapshot
        return {"status": "queued" if self.active == record["id"] else "interrupted", "success": False,
                "steps": {}, "tool_calls": [], "artifacts": [], "errors": [], "warnings": []}

    def view(self, job_id):
        with self.lock:
            record = self._record(job_id)
            snapshot = self._snapshot(record)
            if snapshot.get('record_issue'):
                return {**record, 'snapshot': snapshot, 'summary': None, 'check': None,
                        'display_summary': None, 'display_sources': [], 'display_errors': [],
                        'check_issue': snapshot['record_issue'], 'report': None, 'can_open': False}
            if record.get('input_mode') == 'structured':
                issue, presented = None, {'summary': None, 'check': None}
                try:
                    binding = self.structured_bindings[record['profession']]
                    presented = binding.presentation(record, snapshot, self._read_tool_result)
                except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, ArithmeticError):
                    issue = '柱结果不可用或归属、输入、逐项判定与来源不一致，无法确认通过；请保留记录供检查。'
                if issue:
                    snapshot = {**snapshot, 'success': False, 'status': 'invalid_output'}
                return {**record, 'snapshot': snapshot, **presented, 'check_issue': issue,
                        'report': None, 'can_open': False}
            summary = self._summary(snapshot)
            checked, check_issue = self._check_summary(snapshot)
            report = self.reports.view(record,snapshot) if self.reports else None
            return {**record, "snapshot": snapshot, "summary": summary, "check": checked, "check_issue": check_issue,
                    "report": report,
                    "can_open": snapshot.get("success") is True and not check_issue and self.active is None and self._drawing(snapshot) is not None}

    def status(self, profession=None, project_id=None):
        with self.lock:
            records = []
            for path in sorted(self.jobs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name.endswith(".failure.json"):
                    continue
                try:
                    data = self._record(path.stem)
                    if profession and data.get('profession', self.legacy_profession['id']) != profession:
                        continue
                    if project_id and data.get('project_id') != project_id:
                        continue
                    records.append({k: data[k] for k in ("id", "project_name", "created")} | {
                        'profession': data.get('profession', self.legacy_profession['id']), 'project_id': data['project_id']})
                except (ValueError, KeyError, OSError):
                    continue
                if len(records) == 30:
                    break
            return {"active": self.active, "jobs": records, "configuration": self.configuration(profession),
                    "recovery": deepcopy(self.recovery)}

    def _drawing(self, snapshot):
        for artifact in snapshot.get("artifacts", []):
            if artifact.get("type") == "dwg":
                path = Path(artifact["path"]).resolve()
                if path.is_relative_to(self.root) and path.suffix.lower() == ".dwg" and path.is_file() and path.stat().st_size:
                    return path
        return None

    def open_drawing(self, job_id):
        with self.lock:
            self._ensure_idle()
            record = self._record(job_id)
            if record.get('input_mode') == 'structured':
                raise UIError('此专业未提供CAD图纸操作。', 409)
            snapshot = self._snapshot(record)
            if self._check_summary(snapshot)[1]:
                raise UIError("校核记录无法确认，请保留记录并检查后再打开图纸。", 409)
            path = self._drawing(snapshot) if snapshot.get("success") is True else None
            if path is None:
                raise UIError("本次没有可打开的已验证图纸，或图纸已被移动。", 409)
            try:
                self.opener(str(path))
            except OSError:
                raise UIError("无法打开图纸，请检查本机DWG文件关联或用AutoCAD手动打开。", 500) from None
            return {"success": True}

    def start_recovery(self):
        with self.lock:
            self._ensure_idle()
            self.active = "recovery"
            self.recovery = {"status": "running", "message": "正在检查并恢复本工具的未完成绘图……"}
            self.thread = threading.Thread(target=self._recover, name="structagent-recovery", daemon=False)
            try:
                self.thread.start()
            except Exception:
                self.active = None
                self.recovery = {"status": "failed", "message": "无法启动恢复检查，请重新打开程序。"}
                raise UIError(self.recovery["message"], 500) from None
            return {"success": True}

    def _recover(self):
        try:
            self.recover(self.root)
            outcome = {"status": "completed", "message": "恢复检查完成，可以重新开始设计；历史失败记录仍保留。"}
        except Exception:
            outcome = {"status": "failed", "message": "尚未确认恢复完成。请保留现场，检查AutoCAD是否有未结束的命令或弹窗。"}
        with self.lock:
            self.recovery, self.active = outcome, None

    def _summary(self, snapshot):
        # Presentation reads published ToolResult, never legacy stdout or private scripts.
        for call in snapshot.get("tool_calls", []):
            if call.get("step") != "design" or call.get("status") != "completed":
                continue
            try:
                result = self._read_tool_result(call, snapshot).result
                return {"sections": {key: len(result[key]["sections"]) for key in ("slab", "secondary_beam", "main_beam")},
                        "reinforcement_items": len(result["reinforcement"]["bars"])}
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                return None
        return None

    def prepare_shutdown(self):
        with self.lock:
            self._ensure_idle()
            self.stopping = True

    def _check_summary(self, snapshot):
        calls = [call for call in snapshot.get('tool_calls', []) if call.get('tool') == 'check_floor_design']
        state = snapshot.get('steps', {}).get('check')
        if not calls and state not in ('completed', 'failed'):
            return None, None  # Historical runs did not include this tool.
        if len(calls) == 1 and calls[0].get('status') in ('running', 'interrupted') and not snapshot.get('success'):
            return None, None
        try:
            if len(calls) != 1:
                raise ValueError('Missing or duplicated check call.')
            call = calls[0]
            payload = self._read_tool_result(call, snapshot)
            checked = present_check(payload, snapshot)
            if snapshot.get('success') and checked['status'] != 'PASS':
                raise ValueError('Completed workflow has no passing check.')
            return checked, None
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, ArithmeticError):
            return None, "校核结果不可用或记录不一致，无法确认通过；请保留运行记录供检查，不会自动重新计算或出图。"

    def _read_tool_result(self, call, snapshot):
        # Resolve inside the try boundary in callers; malformed/null paths are also invalid records.
        run_id, step = snapshot['run_id'], call['step']
        if (not isinstance(run_id, str) or re.fullmatch(r'[0-9a-f]{32}', run_id) is None
                or not isinstance(step, str) or re.fullmatch(r'[a-z][a-z0-9_]*', step) is None):
            raise ValueError('Invalid result identity.')
        path = Path(call['result_path']).resolve()
        expected = self.root / 'agent' / run_id / (step + '.json')
        if path != expected or not path.is_file():
            raise ValueError('Result must belong to this run and step.')
        payload = ToolResult(**loads_json(path.read_text(encoding='utf-8')))
        if (payload.tool != call['tool'] or payload.version != call['version']
                or call.get('status') != ('completed' if payload.success else 'failed')):
            raise ValueError('Result identity or execution status differs.')
        return payload
