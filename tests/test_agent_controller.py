"""Workflow contracts, real local design integration, and explicitly simulated CAD."""

import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser, ParseResult
from agent.state import AgentState
from agent.workflow import ResultBinding, Workflow, WorkflowStep
from core import EngineeringTool, ToolRegistry, ToolResult
from tools.floor import FloorDesignTool
from tools.floor.cad_adapter import FloorCADError
from tools.floor.design_store import DesignReferenceError, FloorDesignStore
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.plugin import register_floor_workflow


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = {"unit_system": "SI", "design_code": "GB"}
TEXT = "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
PARAMETERS = {"span_x": 6000, "span_y": 6000, "concrete": "C30", "steel": "HRB400", "live_load": 2.0}


class TestTool(EngineeringTool):
    def __init__(self, name, field, handler):
        super().__init__(name=name, version="1.0", description="Generic test tool",
            parameters_schema={"type": "object", "required": [field], "additionalProperties": False,
                               "properties": {field: {"type": "number"}}},
            output_schema={"type": "object", "required": ["value"], "properties": {"value": {"type": "number"}}})
        self.handler = Mock(side_effect=handler)

    def _execute(self, data):
        return self.handler(data)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 工程"
        self.state = AgentState(self.root)
        self.registry = ToolRegistry()
        self.first = TestTool("design_test", "load", lambda d: ToolResult(True, "design_test", "1.0", result={"value": d["parameters"]["load"] * 2}))
        self.second = TestTool("draw_test", "value", lambda d: ToolResult(True, "draw_test", "1.0", result={"value": d["parameters"]["value"]}))
        for tool in (self.first, self.second):
            self.registry.register(tool)
        self.parser = Mock()
        self.parser.parse.return_value = ParseResult("ready", envelope={"project_id": "p", "tool": self.first.name,
                                                    "context": CONTEXT, "parameters": {"load": 3}})
        self.workflow = Workflow("test_flow", (WorkflowStep("design", self.first.name),
            WorkflowStep("drawing", self.second.name, external_effects=True,
                         bindings={"value": ResultBinding("design", ("result", "value"))})))
        self.controller = AgentController(self.registry, self.parser, self.state, [self.workflow])

    def run_workflow(self):
        return self.controller.run("source", project_id="p", profile_name="test_profile")

    def test_success_routes_results_and_persists_steps_in_order(self):
        result = self.run_workflow()
        self.assertTrue(result["success"], result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps"], {"parse": "completed", "design": "completed", "drawing": "completed"})
        self.assertEqual(self.second.handler.call_args.args[0], {
            "project_id": "p", "tool": self.second.name, "context": CONTEXT, "parameters": {"value": 6}})
        self.assertEqual([(e["step"], e["status"]) for e in result["events"]], [
            ("parse", "running"), ("parse", "completed"), ("design", "running"), ("design", "completed"),
            ("drawing", "running"), ("drawing", "completed")])
        for call in result["tool_calls"]:
            self.assertEqual(json.loads(Path(call["result_path"]).read_text())["tool"], call["tool"])
        restored = AgentState(self.root).get(result["run_id"])
        self.assertEqual(restored["persistence_state"], "COMPLETED")
        self.assertEqual(restored["steps"], result["steps"])

    def test_external_intent_is_durable_before_tool_call(self):
        def draw(data):
            record = self.state.store.list_runs()[0]
            self.assertTrue(record["metadata"]["external_started"])
            self.assertEqual(record["metadata"]["steps"]["drawing"], "running")
            return ToolResult(True, self.second.name, "1.0", result={"value": 6})
        self.second.handler.side_effect = draw
        self.assertTrue(self.run_workflow()["success"])

    def test_warning_summary_deduplicates_but_raw_results_preserve_warnings(self):
        self.first.handler.side_effect = lambda d: ToolResult(True, self.first.name, "1.0", result={"value": 6}, warnings=["review"])
        self.second.handler.side_effect = lambda d: ToolResult(True, self.second.name, "1.0", result={"value": 6}, warnings=["review"])
        result = self.run_workflow()
        self.assertEqual(result["warnings"], ["review"])
        for call in result["tool_calls"]:
            self.assertEqual(json.loads(Path(call["result_path"]).read_text())["warnings"], ["review"])

    def test_dead_owner_updates_tool_call_and_known_recovery_does_not_invent_crash(self):
        snapshot = self.state.begin("p")
        snapshot["tool_calls"] = [{"status": "running"}]
        self.state.save(snapshot)
        with patch("core.project_state.process_identity", return_value="missing"):
            queried = self.state.get(snapshot["run_id"])
        self.assertEqual(queried["tool_calls"][0]["status"], "interrupted")
        self.assertEqual(queried["errors"][-1]["code"], "owner_exited")
        known = self.state.begin("p")
        known["errors"] = [{"code": "cad_recovery_required"}]
        self.state.save(known, "RECOVERY_REQUIRED")
        self.assertEqual(self.state.get(known["run_id"])["errors"], known["errors"])

    def test_parse_failure_or_missing_parameters_never_calls_tools(self):
        for status in ("needs_input", "invalid_input", "invalid_output", "error"):
            self.parser.parse.return_value = ParseResult(status, errors=[{"code": "missing", "message": "Missing input", "path": []}], missing_fields=["load"])
            result = self.run_workflow()
            self.assertFalse(result["success"])
            self.assertEqual(result["status"], status)
            self.assertEqual(result["parse_result"]["missing_fields"], ["load"])
        self.first.handler.assert_not_called()
        self.second.handler.assert_not_called()

    def test_unregistered_workflow_and_project_mismatch_never_execute(self):
        for change in ({"tool": self.second.name}, {"project_id": "other-project"}):
            original = copy.deepcopy(self.parser.parse.return_value)
            self.parser.parse.return_value.envelope.update(change)
            self.assertFalse(self.run_workflow()["success"])
            self.parser.parse.return_value = original
        self.first.handler.assert_not_called()

    def test_revalidate_parser_envelope_before_execution(self):
        self.parser.parse.return_value.envelope["parameters"]["load"] = True
        result = self.run_workflow()
        self.assertFalse(result["success"])
        self.first.handler.assert_not_called()

    def test_failed_design_stops_following_steps_and_preserves_errors(self):
        self.first.handler.side_effect = lambda _: ToolResult.failure(self.first.name, "1.0", "design_rejected", "Input outside supported range")
        result = self.run_workflow()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"]["drawing"], "skipped")
        self.assertEqual(result["errors"][0]["code"], "design_rejected")
        self.second.handler.assert_not_called()

    def test_missing_result_binding_does_not_call_downstream_tool(self):
        workflow = Workflow("missing", (self.workflow.steps[0], WorkflowStep("drawing", self.second.name,
            bindings={"value": ResultBinding("design", ("metadata", "absent"))})))
        result = AgentController(self.registry, self.parser, self.state, [workflow]).run("source", project_id="p")
        self.assertEqual(result["errors"][0]["code"], "result_binding_failed")
        self.second.handler.assert_not_called()

    def test_bound_value_is_validated_before_external_intent_or_call(self):
        workflow = Workflow("bad_type", (self.workflow.steps[0], WorkflowStep("drawing", self.second.name,
            bindings={"value": ResultBinding("design", ("tool",))}, external_effects=True)))
        result = AgentController(self.registry, self.parser, self.state, [workflow]).run("source", project_id="p")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["external_started"])
        self.second.handler.assert_not_called()

    def test_known_clean_external_failure_is_failed_not_recovery_required(self):
        self.second.handler.side_effect = lambda _: ToolResult(False, self.second.name, "1.0",
            errors=[{"code": "unavailable", "message": "Not running", "path": []}], metadata={"recovery_required": False})
        result = self.run_workflow()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state.get(result["run_id"])["persistence_state"], "FAILED")

    def test_external_failure_without_cleanup_confirmation_requires_recovery(self):
        self.second.handler.side_effect = RuntimeError("Failed after starting external side effect")
        result = self.run_workflow()
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(self.state.get(result["run_id"])["persistence_state"], "RECOVERY_REQUIRED")

    def test_tool_success_cannot_override_pending_recovery(self):
        self.second.handler.side_effect = lambda _: ToolResult(True, self.second.name, "1.0", result={"value": 6}, metadata={"recovery_required": True})
        self.assertEqual(self.run_workflow()["status"], "recovery_required")

    def test_unexpected_parser_exception_is_sanitized(self):
        self.parser.parse.side_effect = RuntimeError("secret-example-value")
        result = self.run_workflow()
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("secret-example-value", json.dumps(result))
        self.first.handler.assert_not_called()

    def test_invalid_parser_status_cannot_claim_workflow_success(self):
        for status in ("completed", "running", "anything"):
            self.parser.parse.return_value = ParseResult(status)
            result = self.run_workflow()
            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "failed")
        self.parser.parse.return_value = ParseResult("ready", errors=[{"code": "conflict", "message": "Conflict", "path": []}])
        self.assertFalse(self.run_workflow()["success"])
        self.first.handler.assert_not_called()

    def test_keyboard_interrupt_stops_and_marks_external_uncertainty(self):
        self.second.handler.side_effect = KeyboardInterrupt()
        result = self.run_workflow()
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(result["steps"]["drawing"], "interrupted")

    def test_parse_interrupt_is_interrupted_without_external_recovery(self):
        self.parser.parse.side_effect = KeyboardInterrupt()
        result = self.run_workflow()
        self.assertEqual(result["status"], "interrupted")
        self.first.handler.assert_not_called()

    def test_broken_tool_implementation_cannot_report_success(self):
        with patch.object(self.second, "execute", return_value="not a ToolResult"):
            result = self.run_workflow()
        self.assertEqual(result["status"], "recovery_required")

    def test_state_failure_prevents_any_tool_execution(self):
        with patch.object(self.state, "save", side_effect=OSError("disk full")):
            result = self.run_workflow()
        self.assertFalse(result["state_saved"])
        self.assertIn("state_save_failed", [e["code"] for e in result["errors"]])
        self.first.handler.assert_not_called()

    def test_result_persistence_failure_stops_downstream_tool(self):
        with patch.object(self.state, "publish_result", side_effect=OSError("disk full")):
            result = self.run_workflow()
        self.assertFalse(result["success"])
        self.second.handler.assert_not_called()

    def test_repeated_run_does_not_overwrite_first_run(self):
        first = self.run_workflow()
        paths = [Path(c["result_path"]) for c in first["tool_calls"]]
        contents = [p.read_bytes() for p in paths]
        second = self.run_workflow()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(contents, [p.read_bytes() for p in paths])
        with self.assertRaises(FileExistsError):
            self.state.publish_result(first["run_id"], "design", {})

    def test_second_professional_workflow_only_needs_registration(self):
        additional = TestTool("foundation_demo", "load", lambda _: ToolResult(True, "foundation_demo", "1.0", result={"value": 9}))
        self.registry.register(additional)
        extra_workflow = Workflow("another_plugin", (WorkflowStep("calculate", additional.name),))
        controller = AgentController(self.registry, self.parser, self.state, [self.workflow, extra_workflow])
        self.parser.parse.return_value.envelope["tool"] = additional.name
        result = controller.run("source", project_id="p")
        self.assertTrue(result["success"])
        self.assertEqual(result["workflow"], "another_plugin")
        self.assertEqual(len(controller.capabilities()), 3)
        self.first.handler.assert_not_called()

    def test_workflow_configuration_rejects_duplicate_unknown_forward_or_unsafe_steps(self):
        bad = [Workflow("empty", ()), Workflow("duplicate", (self.workflow.steps[0], self.workflow.steps[0])),
               Workflow("bad", (WorkflowStep("../outside", self.first.name),)),
               Workflow("bad", (WorkflowStep("parse", self.first.name),)),
               Workflow("bad", (WorkflowStep("design", "unregistered"),)),
               Workflow("bad", (WorkflowStep("design", self.first.name, parameters={"load": 3}),)),
               Workflow("bad", (self.workflow.steps[0], WorkflowStep("draw", self.second.name, bindings={
                   "value": ResultBinding("future", ("result", "value"))}))),
               Workflow("bad", (self.workflow.steps[0], WorkflowStep("draw", self.second.name, bindings={
                   "value": ResultBinding("design", "result.value")}))),
               Workflow("bad", (self.workflow.steps[0], WorkflowStep("draw", self.second.name, bindings={
                   "value": ResultBinding("design", ("result", -1))})))]
        for workflow in bad:
            with self.subTest(workflow=workflow), self.assertRaises((ValueError, KeyError)):
                AgentController(self.registry, self.parser, self.state, [workflow])
        with self.assertRaises(ValueError):
            AgentController(self.registry, self.parser, self.state, [self.workflow, self.workflow])

    def test_core_controller_has_no_professional_imports_or_commands(self):
        path = ROOT / "agent/controller.py"
        tree = ast.parse(path.read_text())
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(m.startswith(("tools", "legacy")) for m in modules if m))
        for literal in ("design_floor_system", "generate_floor_cad", "RFALL", "FloorLegacyProgram"):
            self.assertNotIn(literal, path.read_text())

    def test_real_process_exit_is_observed_without_replaying_external_step(self):
        code = """from agent.state import AgentState
import os,sys
s=AgentState(sys.argv[1]);r=s.begin('crash')
r.update(external_started=True,current_task='drawing',steps={'parse':'completed','drawing':'running','report':'pending'})
s.save(r);print(r['run_id'],flush=True);os._exit(9)
"""
        process = subprocess.run([sys.executable, "-c", code, str(self.root)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(process.returncode, 9)
        restored = AgentState(self.root).get(process.stdout.strip())
        self.assertEqual(restored["status"], "recovery_required")
        self.assertEqual(restored["steps"], {"parse": "completed", "drawing": "interrupted", "report": "skipped"})
        self.assertFalse(restored["success"])


class SimulatedCAD:
    def execute(self, directory, run_id, timeout):
        scene = json.loads((directory / "drawing_scene.json").read_text(encoding="utf-8"))
        (directory / "floor.dwg").write_bytes(b"SIMULATED - NOT AN AUTOCAD ACCEPTANCE")
        receipt = {"state": "SUCCESS", "run_id": run_id, "reopened": True, "scene_verified": True,
                   "entities": sum(len(rows) for rows in scene["groups"].values())}
        (directory / "cad_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return receipt


class FloorWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 目录"
        self.registry = ToolRegistry()
        self.backend = SimulatedCAD()
        self.workflow = register_floor_workflow(self.registry, self.root, cad_backend=self.backend)
        self.gateway = Mock()
        self.gateway.complete.return_value = ({"tool": "design_floor_system", "parameters": PARAMETERS}, {})
        self.parser = ParameterParser(self.registry, self.gateway, [FloorDemoProfile()])
        self.state = AgentState(self.root / "agent")
        self.controller = AgentController(self.registry, self.parser, self.state, [self.workflow])

    def test_real_calculation_persistence_conversion_and_simulated_cad_through_controller(self):
        result = self.controller.run(TEXT, project_id="CSU-DEMO-001", profile_name="office_floor_demo_v1")
        self.assertTrue(result["success"], result)
        saved = json.loads(Path(result["tool_calls"][0]["result_path"]).read_text(encoding="utf-8"))
        ref = saved["metadata"]["design_result_ref"]
        loaded = FloorDesignStore(self.root / "designs").load(ref, project_id="CSU-DEMO-001")
        baseline = json.loads((ROOT / "tests/fixtures/floor_baselines.json").read_text())["cases"]["demo_a"]
        self.assertEqual(loaded.metadata["legacy_result_sha256"], baseline["result_sha256"])
        self.assertEqual(result["steps"], {"parse": "completed", "design": "completed", "cad": "completed"})
        self.assertTrue(any(a["type"] == "dwg" for a in result["artifacts"]))

    def test_snapshot_failure_stops_cad(self):
        store = self.registry.get("design_floor_system")._store
        with patch.object(store, "save", side_effect=OSError("disk full")), patch.object(self.backend, "execute") as call:
            result = self.controller.run(TEXT, project_id="CSU-DEMO-001", profile_name="office_floor_demo_v1")
        self.assertFalse(result["success"])
        self.assertEqual(result["errors"][0]["code"], "design_snapshot_failed")
        self.assertEqual(result["steps"]["cad"], "skipped")
        call.assert_not_called()

    def test_cad_adapter_recovery_required_reaches_generic_workflow_status(self):
        with patch.object(self.backend, "execute", side_effect=FloorCADError("cad_recovery_required", "Pending ownership cleanup")):
            result = self.controller.run(TEXT, project_id="CSU-DEMO-001", profile_name="office_floor_demo_v1")
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(result["steps"]["design"], "completed")
        self.assertEqual(result["steps"]["cad"], "failed")

    def test_invalid_design_reference_requires_no_external_cleanup(self):
        store = self.registry.get("generate_floor_cad").store
        with patch.object(store, "load", side_effect=DesignReferenceError("Corrupted snapshot")), patch.object(self.backend, "execute") as call:
            result = self.controller.run(TEXT, project_id="CSU-DEMO-001", profile_name="office_floor_demo_v1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "invalid_design_reference")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
