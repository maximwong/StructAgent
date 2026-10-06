"""Real installed column plugin, unchanged Controller and offline CLI."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.controller import AgentController
from agent.state import AgentState
from agent.workflow import ResultBinding, Workflow, WorkflowStep
from core import ToolRegistry
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from examples.column_workflow import LocalColumnParser, run_request
from tests.test_column_calculation import actual_bars, column_model
from tests.test_column_tools import envelope
from tools.column.plugin import register_column_workflow

ROOT = Path(__file__).resolve().parents[1]


class ColumnWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "柱结果"

    def result_at(self, snapshot, step):
        call = next(call for call in snapshot["tool_calls"] if call["step"] == step)
        return json.loads(Path(call["result_path"]).read_text(encoding="utf-8"))

    def test_installed_plugins_construct_only_without_creating_output_or_calculating(self):
        column_plugins = Path(self.temp.name) / "column_plugins"
        shutil.copytree(ROOT / "plugins/rc_column", column_plugins / "rc_column", ignore=shutil.ignore_patterns("__pycache__"))
        with patch("tools.column.design_adapter.design_column", side_effect=AssertionError("no calculation")), \
             patch("tools.column.design_adapter.check_column", side_effect=AssertionError("no check")), \
             patch("tools.floor.design_adapter.FloorDesignAdapter.design", side_effect=AssertionError("no floor")), \
             patch("llm.gateway.DeepSeekGateway.__init__", side_effect=AssertionError("no cloud")), \
             patch("tools.floor.cad_adapter.AutoCADBackend.execute", side_effect=AssertionError("no CAD")):
            column_catalog = load_plugins(column_plugins, PluginContext(self.output))
            self.assertFalse(self.output.exists())
            self.assertEqual(len(column_catalog.plugins), 1)
            self.assertEqual(column_catalog.profiles, ())
            self.assertEqual(column_catalog.web_bindings, ())
            catalog = load_plugins(ROOT / "plugins", PluginContext(self.output))
        self.assertEqual({plugin["id"] for plugin in catalog.plugins}, {"rc_floor", "rc_column"})
        self.assertEqual({item["name"] for item in catalog.registry.list_tools()},
                         {"design_column", "check_column_design", "design_floor_system", "check_floor_design",
                          "generate_floor_cad", "generate_floor_report"})
        self.assertEqual(len(catalog.web_bindings), 1)
        self.assertTrue(all(profile.tool != "design_column" for profile in catalog.profiles))
        workflow = next(item for item in catalog.workflows if item.name == "rc_column_design")
        self.assertFalse(any(step.external_effects for step in workflow.steps))
        self.assertEqual(workflow.steps[1].bindings["design_result_ref"].path, ("result", "design_result_ref"))

    def test_short_and_slender_run_with_existing_controller_without_cloud_cad_or_floor(self):
        before = (ROOT / "agent/controller.py").read_bytes()
        for case, diameter in (("column-short.json", 16), ("column-slender.json", 20)):
            request = json.loads((ROOT / "demos" / case).read_text(encoding="utf-8"))
            with self.subTest(case=case), \
                 patch("llm.gateway.DeepSeekGateway.__init__", side_effect=AssertionError("no API object")), \
                 patch("llm.gateway.DeepSeekGateway.complete", side_effect=AssertionError("no API call")), \
                 patch("tools.floor.cad_adapter.AutoCADBackend.execute", side_effect=AssertionError("no CAD")), \
                 patch("tools.floor.design_adapter.FloorDesignAdapter.design", side_effect=AssertionError("no floor")):
                snapshot = run_request(request, self.output)
            self.assertTrue(snapshot["success"], snapshot["errors"])
            self.assertEqual(snapshot["steps"], {"parse": "completed", "design": "completed", "check": "completed"})
            self.assertEqual(snapshot["project_id"], request["project_id"])
            design, checked = self.result_at(snapshot, "design"), self.result_at(snapshot, "check")
            self.assertEqual(design["result"]["selected"]["actual"]["bar_diameter_mm"], diameter)
            self.assertEqual(checked["result"]["actual"], design["result"]["selected"]["actual"])
            self.assertEqual(checked["result"]["design_result_ref"], design["result"]["design_result_ref"])
        self.assertEqual((ROOT / "agent/controller.py").read_bytes(), before)

    def test_design_fail_skips_check_and_publication_failure_also_stops(self):
        registry = ToolRegistry()
        workflow = register_column_workflow(registry, self.output)
        request = envelope()
        request["parameters"]["model"]["actions"]["N_kN"] = 10000
        controller = AgentController(registry, LocalColumnParser(request, registry),
                                     AgentState(self.output / "agent"), [workflow])
        with patch.object(registry.get("check_column_design"), "execute", side_effect=AssertionError("must skip")):
            snapshot = controller.run("local", project_id=request["project_id"])
        self.assertFalse(snapshot["success"])
        self.assertEqual(snapshot["steps"]["check"], "skipped")
        self.assertEqual(self.result_at(snapshot, "design")["result"]["status"], "FAIL")
        request = envelope()
        controller = AgentController(registry, LocalColumnParser(request, registry),
                                     AgentState(self.output / "io-agent"), [workflow])
        with patch.object(registry.get("design_column").store, "save", side_effect=OSError("secret")), \
             patch.object(registry.get("check_column_design"), "execute", side_effect=AssertionError("must skip")):
            snapshot = controller.run("local", project_id=request["project_id"])
        self.assertFalse(snapshot["success"])
        self.assertEqual(snapshot["steps"]["check"], "skipped")
        self.assertEqual(snapshot["errors"][0]["code"], "column_snapshot_failed")

    def test_actual_failure_stops_later_declared_workflow_step(self):
        registry = ToolRegistry()
        register_column_workflow(registry, self.output)
        workflow = Workflow("test_actual_gate", (
            WorkflowStep("check", "check_column_design"),
            WorkflowStep("later", "design_column", bindings={
                "model": ResultBinding("check", ("result", "effective_input")),
            }),
        ))
        request = envelope("check_column_design", {"model": column_model(), "actual": actual_bars(14)})
        controller = AgentController(registry, LocalColumnParser(request, registry),
                                     AgentState(self.output / "agent"), [workflow])
        with patch.object(registry.get("design_column"), "execute", side_effect=AssertionError("no later step")):
            snapshot = controller.run("local", project_id=request["project_id"])
        self.assertFalse(snapshot["success"])
        self.assertEqual(snapshot["steps"]["later"], "skipped")
        self.assertEqual(self.result_at(snapshot, "check")["result"]["actual"], actual_bars(14))

    def test_parser_keeps_envelope_identity_and_does_not_fill_fields(self):
        registry = ToolRegistry()
        register_column_workflow(registry, self.output)
        request = envelope()
        parser = LocalColumnParser(request, registry)
        self.assertEqual(parser.parse("local", project_id="OTHER").status, "invalid_input")
        del request["parameters"]["model"]["actions"]["combination_source"]
        parsed = LocalColumnParser(request, registry).parse("local", project_id=request["project_id"])
        self.assertEqual(parsed.status, "invalid_input")
        self.assertIsNone(parsed.envelope)
        request = envelope()
        parsed = LocalColumnParser(request, registry).parse("local", project_id=request["project_id"])
        self.assertEqual(parsed.envelope, request)
        parsed.envelope["parameters"].clear()
        self.assertTrue(request["parameters"])

    def cli(self, request_file, *, tool_only=False):
        args = [sys.executable, "-m", "examples.column_workflow", "--request-file", str(request_file),
                "--output-root", str(self.output)]
        if tool_only:
            args.append("--tool-only")
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(proc.stderr, b"", proc.stderr)
        return proc.returncode, json.loads(proc.stdout.decode("utf-8"))

    def test_cli_anonymous_examples_success_fail_and_repeated_run(self):
        seen_refs = []
        for case in ("column-short.json", "column-slender.json", "column-short.json"):
            with self.subTest(case=case):
                code, snapshot = self.cli(ROOT / "demos" / case)
                self.assertEqual(code, 0)
                self.assertTrue(snapshot["success"])
                seen_refs.append(self.result_at(snapshot, "design")["result"]["design_result_ref"])
        self.assertEqual(len(set(seen_refs)), 3)
        code, snapshot = self.cli(ROOT / "demos/column-check-fail.json", tool_only=True)
        self.assertEqual(code, 1)
        self.assertFalse(snapshot["success"])
        checked = self.result_at(snapshot, "check")
        self.assertEqual(checked["result"]["status"], "FAIL")
        self.assertEqual(checked["result"]["actual"]["bar_diameter_mm"], 14)

    def test_cli_reference_check_uses_original_project_and_mode(self):
        code, snapshot = self.cli(ROOT / "demos/column-short.json")
        self.assertEqual(code, 0)
        reference = self.result_at(snapshot, "design")["result"]["design_result_ref"]
        request = envelope("check_column_design", {"design_result_ref": reference}, "TEACHING-COLUMN-SHORT")
        path = Path(self.temp.name) / "check.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        code, checked = self.cli(path, tool_only=True)
        self.assertEqual(code, 0)
        self.assertTrue(checked["success"])
        code, failed = self.cli(path)
        self.assertEqual(code, 1)
        self.assertFalse(failed["success"])
        request["project_id"] = "OTHER"
        path.write_text(json.dumps(request), encoding="utf-8")
        code, failed = self.cli(path, tool_only=True)
        self.assertEqual(code, 1)
        self.assertEqual(failed["errors"][0]["code"], "invalid_column_reference")

    def test_cli_duplicate_keys_nonfinite_unknown_and_missing_inputs_exit_one(self):
        path = Path(self.temp.name) / "bad.json"
        request = envelope()
        for text in ('{"tool":"design_column","tool":"check_column_design"}',
                     '{"N":NaN}', '{"N":Infinity}', '{"N":1e999}', "[]", "not json",
                     json.dumps({**request, "tool": "generate_floor_cad"}),
                     json.dumps({**request, "parameters": {}})):
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text):
                code, snapshot = self.cli(path)
                self.assertEqual(code, 1)
                self.assertFalse(snapshot["success"])
        path.unlink()
        code, snapshot = self.cli(path)
        self.assertEqual(code, 1)
        self.assertFalse(snapshot["success"])


if __name__ == "__main__":
    unittest.main()
