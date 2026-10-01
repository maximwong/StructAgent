"""Portable contract tests; fake CAD receipts are never desktop acceptance."""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import ToolRegistry, ToolResult
from tools.floor import FloorDesignTool
from tools.floor.cad_adapter import AutoCADBackend, FloorCADAdapter, FloorCADError
from tools.floor.cad_tool import FloorCADTool
from tools.floor.design_adapter import canonical_hash
from tools.floor.design_store import FloorDesignStore, DesignReferenceError

ROOT = Path(__file__).resolve().parents[1]
BASELINES = json.loads((ROOT / "tests/fixtures/cad_baselines.json").read_text())["cases"]


class FakeCAD:
    def execute(self, run_dir, run_id, timeout):
        scene = json.loads((run_dir / "drawing_scene.json").read_text(encoding="utf-8"))
        receipt = {"state": "SUCCESS", "run_id": run_id, "reopened": True, "scene_verified": True,
                   "entities": sum(len(rows) for rows in scene["groups"].values())}
        (run_dir / "floor.dwg").write_bytes(b"SIMULATED DRAWING - NOT AUTOCAD")
        (run_dir / "cad_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return receipt


class FloorCADTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.designs = {}
        for case in BASELINES:
            model = json.loads((ROOT / "legacy/rc_floor" / (case + ".json")).read_text(encoding="utf-8-sig"))
            cls.designs[case] = FloorDesignTool().execute({"project_id": "demo", "tool": "design_floor_system",
                "context": {"unit_system": "SI", "design_code": "GB"},
                "parameters": {"input_mode": "explicit", "model": model}})
            assert cls.designs[case].success, cls.designs[case].errors

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="StructAgent_CAD_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 工程"
        self.store = FloorDesignStore(self.root / "designs")
        self.adapter = FloorCADAdapter(self.root / "cad", backend=FakeCAD())
        self.registry = ToolRegistry()
        self.registry.register(FloorCADTool(self.store, self.adapter))
        self.tool = self.registry.get("generate_floor_cad")

    def request(self, case="demo_a"):
        return {"project_id": "demo", "tool": "generate_floor_cad",
                "context": {"unit_system": "SI", "design_code": "GB"},
                "parameters": {"design_result_ref": self.store.save(self.designs[case])}}

    def test_three_real_conversions_match_frozen_cad_baselines(self):
        for case, baseline in BASELINES.items():
            with self.subTest(case=case):
                before = copy.deepcopy(self.designs[case].to_dict())
                result = self.tool.execute(self.request(case))
                self.assertTrue(result.success, result.errors)
                run = Path(result.metadata["run_directory"])
                self.assertEqual(result.metadata["scene_sha256"], baseline["scene_sha256"])
                self.assertEqual(hashlib.sha256((run / "floor_data.dat").read_bytes()).hexdigest(), baseline["data_sha256"])
                self.assertEqual(self.designs[case].to_dict(), before)
                self.assertEqual(result.warnings, self.designs[case].warnings)

    def test_parallel_repeats_have_distinct_immutable_designs_and_run_outputs(self):
        requests = [self.request() for _ in range(2)]
        self.assertNotEqual(requests[0]["parameters"], requests[1]["parameters"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.tool.execute, requests))
        self.assertTrue(all(r.success for r in results), results)
        self.assertNotEqual(results[0].artifacts[0]["path"], results[1].artifacts[0]["path"])
        for result in results:
            self.assertTrue(Path(result.artifacts[0]["path"]).is_file())
            self.assertEqual(json.loads((Path(result.metadata["run_directory"]) / "run.json").read_text(encoding="utf-8"))["state"], "COMPLETED")

    def test_reference_never_accepts_paths_or_unknown_ids(self):
        for ref in ("../private.json", "C:/private.json", "floor-" + "a"*32, True):
            with self.subTest(ref=ref):
                data = self.request();data["parameters"]["design_result_ref"] = ref
                with patch.object(self.adapter, "generate") as call:
                    self.assertFalse(self.tool.execute(data).success)
                    call.assert_not_called()

    def test_project_mismatch_and_failed_design_rejected(self):
        data = self.request();data["project_id"] = "another"
        with patch.object(self.adapter, "generate") as call:
            self.assertEqual(self.tool.execute(data).errors[0]["code"], "invalid_design_reference")
            call.assert_not_called()
        with self.assertRaises(DesignReferenceError):
            self.store.save(ToolResult.failure("design_floor_system", "1.0.0", "rejected", "Failed"))

    def test_corrupted_or_tampered_snapshot_is_rejected(self):
        for contents in ("not JSON", '{"design":{}}'):
            data = self.request();ref = data["parameters"]["design_result_ref"]
            (self.store.root / (ref + ".json")).write_text(contents)
            self.assertFalse(self.tool.execute(data).success)
        data = self.request();path = self.store.root / (data["parameters"]["design_result_ref"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"));saved["design"]["result"]["legacy_result"]["bars"] = []
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.assertFalse(self.tool.execute(data).success)

    def test_snapshot_revalidation_rejects_even_rehashed_wrong_design(self):
        data = self.request();path = self.store.root / (data["parameters"]["design_result_ref"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"));saved["design"]["result"]["legacy_result"]["bars"] = []
        saved["checksum"] = canonical_hash(saved["design"])
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.assertFalse(self.tool.execute(data).success)

    def test_missing_parameter_wrong_context_and_extra_command_rejected(self):
        for mutation in (lambda d: d.update(parameters={}),
                         lambda d: d["context"].update(unit_system="imperial"),
                         lambda d: d["parameters"].update(command="anything")):
            data = self.request();mutation(data)
            with patch.object(self.adapter, "generate") as call:
                self.assertFalse(self.tool.execute(data).success)
                call.assert_not_called()

    def test_backend_failure_leaves_diagnostic_manifest_and_no_success_artifacts(self):
        self.adapter.backend = Mock()
        self.adapter.backend.execute.side_effect = FloorCADError("cad_busy", "Busy")
        result = self.tool.execute(self.request())
        self.assertFalse(result.success);self.assertEqual(result.artifacts, [])
        self.assertEqual(result.errors[0]["code"], "cad_busy")
        manifest = json.loads((Path(result.metadata["run_directory"]) / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "FAILED")

    def test_invalid_success_receipts_or_missing_drawings_never_pass(self):
        fake = FakeCAD()
        for field, value in (("run_id", "old"), ("reopened", False), ("entities", True),
                             ("entities", 1), ("scene_verified", False), ("state", "RUNNING"), ("remove_dwg", True)):
            def response(run, rid, timeout):
                receipt = fake.execute(run, rid, timeout)
                if field == "remove_dwg":
                    (run / "floor.dwg").unlink()
                else:
                    receipt[field] = value
                return receipt
            self.adapter.backend = Mock(execute=response)
            with self.subTest(field=field):
                result = self.tool.execute(self.request())
                self.assertFalse(result.success)
                self.assertEqual(result.errors[0]["code"], "cad_receipt_invalid")

    def test_conversion_failure_never_calls_cad(self):
        backend = Mock();self.adapter.backend = backend
        with patch.object(self.adapter, "prepare", side_effect=FloorCADError("cad_conversion_failed", "Rejected")):
            result = self.tool.execute(self.request())
        self.assertFalse(result.success);backend.execute.assert_not_called()

    def test_scene_worker_failures_are_structured(self):
        for response in (subprocess.TimeoutExpired("worker", 60), OSError("missing"),
                         SimpleNamespace(returncode=1, stdout='{"success":false,"error":"invalid"}'),
                         SimpleNamespace(returncode=0, stdout="not JSON")):
            with self.subTest(response=response):
                kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with patch("tools.floor.cad_adapter.subprocess.run", **kwargs):
                    with self.assertRaises(FloorCADError) as caught:
                        self.adapter.prepare({}, self.root)
                self.assertEqual(caught.exception.code, "cad_conversion_failed")

    def test_timeout_configuration_rejects_invalid_values(self):
        for value in (True, False, 0, 9, 901, float("nan"), "240"):
            with self.assertRaises(ValueError):
                FloorCADAdapter(self.root, timeout_seconds=value)

    def test_unexpected_backend_failure_records_failed_state(self):
        self.adapter.backend = Mock()
        self.adapter.backend.execute.side_effect = RuntimeError("Unexpected failure")
        result = self.tool.execute(self.request())
        self.assertFalse(result.success)
        manifest = json.loads((Path(result.metadata["run_directory"]) / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "FAILED")

    def test_cad_cleanup_warning_is_preserved_with_verified_success(self):
        fake = FakeCAD()
        def response(run, rid, timeout):
            receipt = fake.execute(run, rid, timeout)
            receipt["owned_document_closed"] = False
            return receipt
        self.adapter.backend = Mock(execute=response)
        result = self.tool.execute(self.request())
        self.assertTrue(result.success, result.errors)
        self.assertIn("remains open", result.warnings[-1])

    @unittest.skipUnless(__import__("os").name == "nt", "Windows bridge contract")
    def test_bridge_timeout_and_missing_receipt_do_not_report_success(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for index, outcome in enumerate((subprocess.TimeoutExpired("bridge", 100), OSError("missing"),
                                         SimpleNamespace(returncode=1))):
            run = self.root / str(index);run.mkdir()
            kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with patch("tools.floor.cad_adapter.subprocess.run", **kwargs):
                with self.assertRaises(FloorCADError):
                    AutoCADBackend(run / "sessions").execute(run, "a"*32, 60)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows bridge contract")
    def test_bridge_run_token_and_exit_code_are_both_required(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for index, (code, token, state) in enumerate(((0, "old", "SUCCESS"), (1, "a"*32, "SUCCESS"), (0, "a"*32, "FAILED"))):
            run = self.root / str(index);run.mkdir()
            (run / "cad_receipt.json").write_text(json.dumps({"run_id": token, "state": state}), encoding="utf-8")
            with patch("tools.floor.cad_adapter.subprocess.run", return_value=SimpleNamespace(returncode=code)):
                with self.assertRaises(FloorCADError):
                    AutoCADBackend(run / "sessions").execute(run, "a"*32, 60)


if __name__ == "__main__":
    unittest.main()
