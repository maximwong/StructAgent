from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import ToolRegistry, ToolValidationError
from tools.floor import FloorDesignTool
from tools.floor.design_adapter import FloorDesignAdapter

ROOT = Path(__file__).resolve().parents[1]
BASELINES = json.loads((ROOT / "tests/fixtures/floor_baselines.json").read_text(encoding="utf-8"))["cases"]


def model(name="demo_a"):
    return json.loads((ROOT / "legacy/rc_floor" / (name + ".json")).read_text(encoding="utf-8-sig"))


def request(parameters=None):
    return {
        "project_id": "CSU-DEMO-001", "tool": "design_floor_system",
        "context": {"unit_system": "SI", "design_code": "GB"},
        "parameters": parameters if parameters is not None else {
            "input_mode": "template", "template_id": "office_floor_demo_v1",
            "span_x": 6000, "span_y": 6000, "concrete": "C30", "steel": "HRB400", "live_load": 2.0,
        },
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


class FloorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ToolRegistry()
        cls.registry.register(FloorDesignTool())
        cls.tool = cls.registry.get("design_floor_system")
        cls.requests = {name: request({"input_mode": "explicit", "model": model(name)}) for name in BASELINES}
        cls.original_requests = copy.deepcopy(cls.requests)
        with ThreadPoolExecutor(max_workers=3) as pool:
            cls.results = dict(zip(cls.requests, pool.map(cls.tool.execute, cls.requests.values())))

    def test_three_parallel_calculations_match_frozen_baselines(self):
        for name, result in self.results.items():
            with self.subTest(case=name):
                self.assertTrue(result.success, result.errors)
                raw = result.result["legacy_result"]
                self.assertEqual(digest(raw), BASELINES[name]["result_sha256"])
                self.assertEqual(result.metadata["legacy_result_sha256"], digest(raw))
                self.assertEqual(digest(raw["bars"]), BASELINES[name]["bars_sha256"])
                self.assertEqual(len(raw["bars"]), BASELINES[name]["bar_count"])
        self.assertEqual(self.requests, self.original_requests)

    def test_standard_output_keeps_all_designs_checks_and_warnings(self):
        result = self.results["demo_a"]
        self.assertTrue(result.success, result.errors)
        raw = result.result["legacy_result"]
        for standard, legacy in (("slab", "slab"), ("secondary_beam", "secondary"), ("main_beam", "main")):
            self.assertEqual(result.result[standard]["sections"], raw[legacy])
        self.assertEqual(result.result["reinforcement"]["bars"], raw["bars"])
        self.assertEqual(result.result["checks"]["joints"], raw["joint_checks"])
        self.assertEqual(result.result["checks"]["material"], raw["material_checks"])
        self.assertEqual(result.warnings, raw["warnings"])
        self.assertEqual(result.result["effective_input"], raw["input"])
        self.assertEqual(result.artifacts, [])
        json.dumps(result.to_dict(), allow_nan=False)

    def test_confirmed_template_reproduces_demo_a(self):
        result = self.tool.execute(request())
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.metadata["legacy_result_sha256"], BASELINES["demo_a"]["result_sha256"])
        self.assertEqual(result.metadata["template_id"], "office_floor_demo_v1")
        self.assertEqual(result.result["effective_input"], model())

    def test_integer_and_float_template_loads_preserve_complete_baseline(self):
        data = request()
        data["parameters"]["live_load"] = 2
        result = self.tool.execute(data)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.metadata["legacy_result_sha256"], BASELINES["demo_a"]["result_sha256"])
        self.assertEqual(result.result["legacy_result"], self.results["demo_a"].result["legacy_result"])
        self.assertIsInstance(result.result["effective_input"]["loads"]["live_kN_m2"], float)

    def test_engine_import_names_do_not_leak_or_collide(self):
        original_path = sys.path[:]
        fake = ModuleType("engine")
        fake.calculate = Mock(side_effect=AssertionError("parent engine must not be used"))
        with patch.dict(sys.modules, {"engine": fake}):
            result = self.tool.execute(request())
            self.assertTrue(result.success, result.errors)
            self.assertIs(sys.modules["engine"], fake)
        self.assertEqual(sys.path, original_path)
        fake.calculate.assert_not_called()

    def test_chinese_working_directory_needs_no_files(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="楼盖测试_") as directory:
            try:
                os.chdir(directory)
                result = self.tool.execute(request())
                self.assertTrue(result.success, result.errors)
                self.assertEqual(result.metadata["legacy_result_sha256"], BASELINES["demo_a"]["result_sha256"])
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                os.chdir(previous)

    def test_design_rejection_and_retry(self):
        data = request()
        data["parameters"]["live_load"] = 100
        rejected = self.tool.execute(data)
        self.assertFalse(rejected.success)
        self.assertEqual(rejected.errors[0]["code"], "design_rejected")
        self.assertEqual(rejected.artifacts, [])
        valid = self.tool.execute(request())
        self.assertTrue(valid.success, valid.errors)
        self.assertEqual(valid.metadata["legacy_result_sha256"], BASELINES["demo_a"]["result_sha256"])

    def test_existing_topology_check_is_preserved(self):
        data = model()
        data["geometry"]["secondary_spacing_mm"] = 1900
        result = self.tool.execute(request({"input_mode": "explicit", "model": data}))
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "design_rejected")
        self.assertIn("3倍", result.errors[0]["message"])

    def test_legal_boolean_switch_and_effective_input(self):
        data = request({"input_mode": "explicit", "model": model()})
        data["parameters"]["model"]["report"]["allow_arch"] = False
        original = copy.deepcopy(data)
        result = self.tool.execute(data)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(data, original)
        self.assertEqual(result.result["effective_input"]["slab"]["arch_factor"], 1.0)


class FloorBoundaryTests(unittest.TestCase):
    def test_template_mapping_is_explicit_and_uses_shared_strengths(self):
        adapter = FloorDesignAdapter()
        for grade, strengths in {"C25": (11.9, 1.27), "C30": (14.3, 1.43), "C35": (16.7, 1.57), "C40": (19.1, 1.71)}.items():
            data = request()["parameters"]
            data.update(concrete=grade, span_x=5400, span_y=6300, live_load=3.0)
            prepared = adapter.prepare(data, project_id="OTHER-PROJECT")
            self.assertEqual(prepared["project"], "OTHER-PROJECT 办公楼")
            self.assertEqual(prepared["geometry"]["main_axis_spans_mm"], [5400] * 3)
            self.assertEqual(prepared["geometry"]["secondary_axis_spans_mm"], [6300] * 5)
            self.assertEqual(prepared["geometry"]["secondary_spacing_mm"], 1800)
            self.assertEqual((prepared["materials"]["fc_MPa"], prepared["materials"]["ft_MPa"]), strengths)
            self.assertEqual(prepared["materials"]["slab_steel"], "HPB300")
            self.assertEqual(prepared["materials"]["stirrup_steel"], "HPB300")
            self.assertEqual(prepared["loads"]["live_kN_m2"], 3.0)

    def test_missing_or_ambiguous_parameters_never_invoke_adapter(self):
        adapter = Mock(spec=FloorDesignAdapter)
        tool = FloorDesignTool(adapter)
        variants = []
        for field in request()["parameters"]:
            data = request()
            del data["parameters"][field]
            variants.append(data)
        data = request({"input_mode": "explicit", "model": model()})
        del data["parameters"]["model"]["main"]["b_mm"]
        variants.append(data)
        data = request()
        data["parameters"]["model"] = model()
        variants.append(data)
        for data in variants:
            self.assertFalse(tool.execute(data).success)
        adapter.design.assert_not_called()

    def test_wrong_context_or_template_is_rejected_before_adapter(self):
        adapter = Mock(spec=FloorDesignAdapter)
        tool = FloorDesignTool(adapter)
        variants = []
        for key, value in (("unit_system", "imperial"), ("design_code", "ACI")):
            data = request()
            data["context"][key] = value
            variants.append(data)
        data = request()
        data["parameters"]["template_id"] = "../../user_file.json"
        variants.append(data)
        for data in variants:
            self.assertFalse(tool.execute(data).success)
        adapter.design.assert_not_called()
        self.assertEqual(tool.input_schema["properties"]["context"]["properties"]["unit_system"], {"const": "SI"})

    def test_bool_number_and_unsupported_materials_never_launch_worker(self):
        tool = FloorDesignTool()
        variants = []
        for key, value in (("live_load", True), ("span_x", False), ("span_y", "6000"),
                           ("concrete", "C60"), ("steel", "HRB500")):
            data = request()
            data["parameters"][key] = value
            variants.append(data)
        for group, field in (("loads", "live_kN_m2"), ("materials", "fc_MPa"), ("main", "stirrup_legs")):
            data = request({"input_mode": "explicit", "model": model()})
            data["parameters"]["model"][group][field] = True
            variants.append(data)
        with patch("tools.floor.design_adapter.subprocess.run") as run:
            for data in variants:
                self.assertFalse(tool.execute(data).success)
            run.assert_not_called()

    def test_grade_strength_conflict_rejected_by_shared_legacy_validator(self):
        data = request({"input_mode": "explicit", "model": model()})
        data["parameters"]["model"]["materials"]["fc_MPa"] = 11.9
        with patch("tools.floor.design_adapter.subprocess.run") as run:
            result = FloorDesignTool().execute(data)
            self.assertFalse(result.success)
            self.assertEqual(result.errors[0]["code"], "validation_error")
            self.assertIn("materials.fc_MPa", result.errors[0]["message"])
            run.assert_not_called()

    def test_direct_adapter_rejects_bool_before_mapping(self):
        data = request()["parameters"]
        data["span_x"] = True
        with self.assertRaises(ToolValidationError):
            FloorDesignAdapter().prepare(data, project_id="TEST")

    def test_process_failures_are_structured(self):
        faults = [
            (subprocess.TimeoutExpired("worker", 1), "design_timeout"),
            (OSError("missing interpreter"), "legacy_start_failed"),
            (SimpleNamespace(returncode=1, stdout=""), "legacy_process_failed"),
            (SimpleNamespace(returncode=0, stdout="unexpected log\n{}"), "legacy_protocol_error"),
            (SimpleNamespace(returncode=0, stdout='{"protocol":true,"success":true,"result":{}}'), "legacy_protocol_error"),
            (SimpleNamespace(returncode=0, stdout='{"protocol":1,"success":true,"result":{}}'), "legacy_protocol_error"),
            (SimpleNamespace(returncode=0, stdout='{"protocol":1,"success":true,"result":{"bad":NaN}}'), "legacy_protocol_error"),
        ]
        for fault, code in faults:
            with self.subTest(code=code):
                kwargs = {"side_effect": fault} if isinstance(fault, Exception) else {"return_value": fault}
                with patch("tools.floor.design_adapter.subprocess.run", **kwargs):
                    result = FloorDesignTool().execute(request())
                    self.assertFalse(result.success)
                    self.assertEqual(result.errors[0]["code"], code)

    def test_worker_command_has_fixed_paths_and_no_shell(self):
        response = {"protocol": 1, "success": False, "error": {"code": "design_rejected", "message": "test"}}
        with patch("tools.floor.design_adapter.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response))) as run:
            FloorDesignTool(FloorDesignAdapter(timeout_seconds=9)).execute(request())
            args, kwargs = run.call_args
            self.assertEqual(args[0][:2], [sys.executable, "-I"])
            self.assertTrue(Path(args[0][2]).is_absolute())
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 9)
            self.assertEqual(kwargs["encoding"], "utf-8")

    def test_unexpected_adapter_exception_uses_core_error_contract(self):
        adapter = Mock(spec=FloorDesignAdapter)
        adapter.design.side_effect = RuntimeError("adapter bug")
        result = FloorDesignTool(adapter).execute(request())
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "execution_error")

    def test_timeout_setting_is_validated(self):
        for value in (0, -1, True, float("inf"), "30"):
            with self.assertRaises(ValueError):
                FloorDesignAdapter(timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
