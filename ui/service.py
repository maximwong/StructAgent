"""Single-operation UI service backed by authoritative AgentState records."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from agent.state import AgentState
from core.persistence import write_json
from core.validation import ensure_json
from core.exceptions import ToolValidationError
from core import ToolResult
from .check_presentation import present_check


class UIError(ValueError):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


class RunService:
    def __init__(self, root, controller_factory, *, settings_check, recover, opener=None,
                 explicit_controller_factory=None, input_form=None,
                 report_factory=None, report_source=None, report_validator=None,
                 template_profile="office_floor_demo_v1", explicit_profile="floor_explicit_v1"):
        self.root = Path(root).resolve()
        self.jobs = self.root / "ui" / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.state = AgentState(self.root / "agent")
        self.controller_factory = controller_factory
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

    def configuration(self):
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
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise UIError("运行记录不可读取，请保留本机记录供检查。", 404) from None

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

    def _run(self, record):
        try:
            controller = (self.explicit_controller_factory(self.root, deepcopy(record["model"]))
                          if record["profile"] == self.explicit_profile else self.controller_factory(self.root))
            result = controller.run(record["text"], project_id=record["project_id"], profile_name=record["profile"])
        except Exception:
            result = {"success": False, "status": "error", "errors": [
                {"code": "ui_start_failed", "message": "无法启动设计流程，请检查本机配置与输出目录。"}]}
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
        if record.get('run_id'):
            snapshot = self.state.get(record['run_id'])
            if snapshot['project_id'] != record['project_id']:
                raise UIError('运行归属不一致，请保留记录供检查。',409)
            return snapshot
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
            summary = self._summary(snapshot)
            checked, check_issue = self._check_summary(snapshot)
            report = self.reports.view(record,snapshot) if self.reports else None
            return {**record, "snapshot": snapshot, "summary": summary, "check": checked, "check_issue": check_issue,
                    "report": report,
                    "can_open": snapshot.get("success") is True and not check_issue and self.active is None and self._drawing(snapshot) is not None}

    def status(self):
        with self.lock:
            records = []
            for path in sorted(self.jobs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name.endswith(".failure.json"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    records.append({k: data[k] for k in ("id", "project_name", "created")})
                except (ValueError, KeyError, OSError):
                    continue
                if len(records) == 30:
                    break
            return {"active": self.active, "jobs": records, "configuration": self.configuration(),
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
            snapshot = self._snapshot(self._record(job_id))
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
        payload = ToolResult(**json.loads(path.read_text(encoding='utf-8')))
        if (payload.tool != call['tool'] or payload.version != call['version']
                or call.get('status') != ('completed' if payload.success else 'failed')):
            raise ValueError('Result identity or execution status differs.')
        return payload
