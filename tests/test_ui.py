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
from core import ToolRegistry
from llm import GatewayError
from ui.server import LocalServer
from ui.service import RunService, UIError
from tools.floor.plugin import register_floor_workflow
from tools.floor.cad_adapter import FloorCADError
from tools.floor.language_profile import FloorDemoProfile
from tests.semantic_fixtures import floor_proposal
from tests.test_agent_controller import SimulatedCAD


TEXT = "设计6m×6m柱网办公楼楼盖，C30，HRB400，活荷载2.0kN/m²。"
PAYLOAD = {"project_name": "中文 项目", "text": TEXT, "template_confirmed": True}


class UIFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="structagent_ui_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 目录"
        self.settings = Mock(return_value=SimpleNamespace(api_key="FAKE_TEST_KEY"))
        self.opener = Mock()
        self.recover = Mock()
        self.entered, self.release = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)
        self.service = RunService(self.root, self.factory, settings_check=self.settings, recover=self.recover, opener=self.opener)
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        if self.service.thread:
            self.service.thread.join(20)

    def factory(self, root):
        def run(text, *, project_id, profile_name):
            state = AgentState(root / "agent")
            snapshot = state.begin(project_id)
            self.entered.set()
            self.release.wait(10)
            drawing = root / "cad" / snapshot["run_id"] / "floor.dwg"
            drawing.parent.mkdir(parents=True)
            drawing.write_bytes(b"SIMULATED DRAWING - NO AUTOCAD")
            snapshot.update(success=True, status="completed", artifacts=[{"type": "dwg", "path": str(drawing)}],
                            steps={"parse": "completed", "design": "completed", "cad": "completed"})
            state.save(snapshot, "COMPLETED")
            return snapshot
        return SimpleNamespace(run=run)

    def completed_job(self):
        job = self.service.start(PAYLOAD)["id"]
        self.finish()
        self.assertFalse(self.service.thread.is_alive())
        return job


class UITests(UIFixture):
    def test_cad_failures_preserve_design_and_never_enable_open(self):
        for code in ("cad_unavailable", "cad_busy", "cad_timeout", "cad_recovery_required"):
            backend = Mock()
            backend.execute.side_effect = FloorCADError(code, "Simulated CAD fault; no desktop touched.")
            def factory(root):
                registry = ToolRegistry()
                workflow = register_floor_workflow(registry, root, cad_backend=backend)
                gateway = Mock()
                gateway.complete.return_value = (floor_proposal(), {})
                return AgentController(registry, ParameterParser(registry, gateway, [FloorDemoProfile()]),
                                       AgentState(root / "agent"), [workflow])
            self.service.controller_factory = factory
            job = self.completed_job()
            view = self.service.view(job)
            self.assertEqual(view["snapshot"]["errors"][0]["code"], code)
            self.assertEqual(view["snapshot"]["steps"]["design"], "completed")
            self.assertFalse(view["can_open"])
            self.assertIsNotNone(view["summary"])

    def test_missing_input_and_api_failures_stop_before_engineering_tools(self):
        for mode in ("missing", "api_timeout", "api_invalid_json"):
            backend = Mock()
            def factory(root):
                registry = ToolRegistry()
                workflow = register_floor_workflow(registry, root, cad_backend=backend)
                gateway = Mock()
                if mode == "missing":
                    proposal = floor_proposal()
                    proposal["parameters"]["live_load"] = None
                    proposal["evidence"]["live_load"] = None
                    gateway.complete.return_value = (proposal, {})
                else:
                    gateway.complete.side_effect = GatewayError(mode, "Safe simulated error")
                return AgentController(registry, ParameterParser(registry, gateway, [FloorDemoProfile()]),
                                       AgentState(root / "agent"), [workflow])
            self.service.controller_factory = factory
            job = self.completed_job()
            result = self.service.view(job)
            self.assertEqual(result["snapshot"]["status"], "needs_input" if mode == "missing" else "error")
            self.assertFalse(result["can_open"])
            self.assertEqual(result["snapshot"]["tool_calls"], [])
            backend.execute.assert_not_called()

    def test_background_progress_duplicate_submit_and_shutdown_guard(self):
        job = self.service.start(PAYLOAD)["id"]
        self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.service.view(job)["snapshot"]["status"], "running")
        for action in (lambda: self.service.start(PAYLOAD), self.service.prepare_shutdown, self.service.start_recovery):
            with self.assertRaises(UIError) as context:
                action()
            self.assertEqual(context.exception.status, 409)
        self.finish()
        self.assertTrue(self.service.view(job)["snapshot"]["success"])

    def test_inputs_and_template_confirmation_are_required(self):
        cases = [{**PAYLOAD, "template_confirmed": False}, {**PAYLOAD, "template_confirmed": 1},
                 {**PAYLOAD, "text": " "}, {**PAYLOAD, "text": "a" * 4001}, {**PAYLOAD, "project_name": ""},
                 {**PAYLOAD, "extra": "RFALL"}, []]
        for payload in cases:
            with self.assertRaises(UIError):
                self.service.start(payload)
        self.assertEqual(list(self.service.jobs.iterdir()), [])

    def test_config_and_credential_errors_do_not_start_or_persist(self):
        with self.assertRaises(UIError):
            self.service.start({**PAYLOAD, "text": "FAKE_TEST_KEY"})
        self.settings.side_effect = ValueError("sensitive details")
        self.assertFalse(self.service.configuration()["ready"])
        with self.assertRaises(UIError) as context:
            self.service.start(PAYLOAD)
        self.assertNotIn("sensitive", str(context.exception))
        self.assertEqual(list(self.service.jobs.iterdir()), [])

    def test_refresh_restart_and_repeated_runs_preserve_old_results(self):
        first = self.completed_job()
        previous = self.service.view(first)
        content = Path(previous["snapshot"]["artifacts"][0]["path"]).read_bytes()
        second = self.completed_job()
        restored = RunService(self.root, self.factory, settings_check=self.settings, recover=self.recover, opener=self.opener)
        self.assertNotEqual(first, second)
        self.assertEqual(len(restored.status()["jobs"]), 2)
        self.assertEqual(restored.view(first)["snapshot"], previous["snapshot"])
        self.assertEqual(Path(previous["snapshot"]["artifacts"][0]["path"]).read_bytes(), content)

    def test_open_only_completed_existing_owned_dwg(self):
        job = self.completed_job()
        path = Path(self.service.view(job)["snapshot"]["artifacts"][0]["path"])
        self.service.open_drawing(job)
        self.opener.assert_called_once_with(str(path.resolve()))
        path.unlink()
        self.assertFalse(self.service.view(job)["can_open"])
        with self.assertRaises(UIError):
            self.service.open_drawing(job)
        self.assertIsNone(self.service._drawing({"artifacts": [{"type": "dwg", "path": str(Path(__file__))}]}))

    def test_setup_failure_is_sanitized_and_survives_restart(self):
        self.service.controller_factory = Mock(side_effect=RuntimeError("FAKE_TEST_KEY"))
        job = self.completed_job()
        self.assertEqual(self.service.view(job)["snapshot"]["status"], "error")
        restored = RunService(self.root, self.factory, settings_check=self.settings, recover=self.recover, opener=self.opener)
        data = restored.view(job)
        self.assertNotIn("FAKE_TEST_KEY", json.dumps(data))
        self.assertFalse(data["can_open"])

    def test_recovery_reuses_owned_recovery_action_and_preserves_history(self):
        job = self.completed_job()
        before = self.service.view(job)
        self.service.start_recovery()
        self.finish()
        self.recover.assert_called_once_with(self.root.resolve())
        self.assertEqual(self.service.status()["recovery"]["status"], "completed")
        self.assertEqual(self.service.view(job), before)
        with patch("ui.service.threading.Thread") as worker:
            worker.return_value.start.side_effect = RuntimeError("thread unavailable")
            with self.assertRaises(UIError):
                self.service.start_recovery()
        self.assertIsNone(self.service.active)
        self.assertEqual(self.service.status()["recovery"]["status"], "failed")
        self.recover.side_effect = RuntimeError("secret")
        self.service.start_recovery()
        self.finish()
        self.assertEqual(self.service.status()["recovery"]["status"], "failed")
        self.assertNotIn("secret", json.dumps(self.service.status()))

    def test_generic_controller_real_design_and_simulated_cad_in_background(self):
        def factory(root):
            registry = ToolRegistry()
            workflow = register_floor_workflow(registry, root, cad_backend=SimulatedCAD())
            gateway = Mock()
            gateway.complete.return_value = (floor_proposal(), {})
            parser = ParameterParser(registry, gateway, [FloorDemoProfile()])
            return AgentController(registry, parser, AgentState(root / "agent"), [workflow])
        self.service.controller_factory = factory
        job = self.completed_job()
        result = self.service.view(job)
        self.assertTrue(result["snapshot"]["success"], result)
        self.assertEqual(result["snapshot"]["parse_result"]["envelope"]["parameters"]["live_load"], 2.0)
        self.assertTrue(result["summary"]["reinforcement_items"] > 0)
        self.assertEqual(len(result["snapshot"]["tool_calls"]), 2)


class HTTPTests(UIFixture):
    def setUp(self):
        super().setUp()
        self.server = LocalServer(self.service, 0)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(5)

    def request(self, path, method="GET", payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        standard = {"X-StructAgent-Token": self.server.token, "Origin": self.server.url, "Content-Type": "application/json"}
        standard.update(headers or {})
        body = None if payload is None else json.dumps(payload).encode()
        connection.request(method, path, body=body, headers=standard)
        response = connection.getresponse()
        data = response.read()
        code = response.status
        connection.close()
        return code, data

    def test_page_and_assets_do_not_expose_local_configuration(self):
        code, html = self.request("/")
        self.assertEqual(code, 200)
        self.assertIn("描述你的设计要求".encode(), html)
        self.assertNotIn(b"FAKE_TEST_KEY", html)
        self.assertEqual(self.request("/app.js")[0], 200)
        self.assertEqual(self.request("/.env")[0], 404)
        self.assertEqual(self.request("/../config.py")[0], 404)

    def test_mutations_require_token_origin_and_local_host(self):
        for headers in ({"X-StructAgent-Token": "bad"}, {"Origin": "http://evil.example"},
                        {"Host": "evil.example"}):
            self.assertEqual(self.request("/api/jobs", "POST", PAYLOAD, headers)[0], 403)
        self.assertEqual(list(self.service.jobs.iterdir()), [])

    def test_json_submission_polling_and_duplicate_click(self):
        code, response = self.request("/api/jobs", "POST", PAYLOAD)
        self.assertEqual(code, 202)
        job = json.loads(response)["id"]
        self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.request("/api/jobs", "POST", PAYLOAD)[0], 409)
        self.assertEqual(self.request("/api/jobs/" + job)[0], 200)
        self.finish()
        result = json.loads(self.request("/api/jobs/" + job)[1])
        self.assertTrue(result["snapshot"]["success"])

    def test_oversize_body_and_path_traversal_rejected(self):
        self.assertEqual(self.request("/api/jobs", "POST", {"text": "a" * 21000})[0], 413)
        self.assertEqual(self.request("/api/jobs/../../.env")[0], 404)


if __name__ == "__main__":
    unittest.main()
