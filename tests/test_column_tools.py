"""Column Tool boundaries and adversarial snapshot integrity."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from core import ToolResult, ToolValidationError
from core.validation import make_validator, validate_json
from tests.test_column_calculation import actual_bars, column_model
from tools.column.calculation import check_column, design_column
from tools.column.check_tool import ColumnCheckTool
from tools.column.design_store import ColumnDesignStore, ColumnReferenceError
from tools.column.design_tool import ColumnDesignTool
from tools.column.json_data import canonical_hash
from tools.column.schemas import DESIGN_CODE


def envelope(tool="design_column", parameters=None, project="COLUMN-TEST"):
    return {"project_id": project, "tool": tool,
            "context": {"unit_system": "mm,kN,kN.m,MPa", "design_code": DESIGN_CODE},
            "parameters": parameters if parameters is not None else {"model": column_model()}}


class ColumnToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ColumnDesignStore(Path(self.temp.name) / "柱设计")
        self.design = ColumnDesignTool(self.store)
        self.check = ColumnCheckTool(self.store)

    def saved(self):
        result = self.design.execute(envelope())
        self.assertTrue(result.success, result.errors)
        reference = result.result["design_result_ref"]
        return result, reference, self.store.root / (reference + ".json")

    def rewrite(self, path, payload, *, report_hash=True, full_hash=True):
        if report_hash:
            report = {key: value for key, value in payload["design"]["result"].items() if key != "design_result_ref"}
            payload["design"]["metadata"]["column_report_sha256"] = canonical_hash(report)
        if full_hash:
            payload["checksum"] = canonical_hash({key: value for key, value in payload.items() if key != "checksum"})
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_design_then_reference_check_returns_full_input_and_same_actual(self):
        result, ref, _ = self.saved()
        validate_json(result.result, make_validator(self.design.output_schema))
        self.assertEqual(result.result["selected"]["actual"], actual_bars())
        with patch("tools.column.calculation.design_column", side_effect=AssertionError("no redesign")), \
             patch("tools.column.design_adapter.design_column", side_effect=AssertionError("no adapter design")):
            loaded = self.store.load(ref, project_id="COLUMN-TEST")
            checked = self.check.execute(envelope("check_column_design", {"design_result_ref": ref}))
        self.assertTrue(checked.success, checked.errors)
        self.assertEqual(loaded.result, result.result)
        self.assertEqual(checked.result["actual"], result.result["selected"]["actual"])
        self.assertEqual(checked.result["effective_input"], result.result["effective_input"])
        self.assertEqual(checked.result["design_result_ref"], ref)

    def test_weak_actual_returns_fail_and_structured_check_errors(self):
        parameters = {"model": column_model(), "actual": actual_bars(14)}
        result = self.check.execute(envelope("check_column_design", parameters))
        self.assertFalse(result.success)
        self.assertEqual(result.result["status"], "FAIL")
        self.assertEqual(result.result["actual"], actual_bars(14))
        self.assertEqual(result.result["intermediates"]["Nu_kN"], 1357.56)
        self.assertEqual(result.errors[0]["code"], "column_check_failed")
        self.assertTrue(result.result["checks"])
        self.assertTrue(all(row["path"][:2] == ["result", "checks"] for row in result.errors))
        validate_json(result.result, make_validator(self.check.output_schema))
        self.assertFalse(self.store.root.exists())

    def test_design_failure_retains_attempts_never_saves_or_returns_ref(self):
        request = envelope()
        request["parameters"]["model"]["actions"]["N_kN"] = 10000
        with patch.object(self.store, "save", side_effect=AssertionError("no save")):
            result = self.design.execute(request)
        self.assertFalse(result.success)
        self.assertEqual(result.result["status"], "FAIL")
        self.assertEqual(len(result.result["attempts"]), 8)
        self.assertNotIn("design_result_ref", result.result)

    def test_snapshot_publication_error_cannot_return_success_or_ref(self):
        with patch("tools.column.design_store.write_json", side_effect=OSError("secret local path")):
            result = self.design.execute(envelope())
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "column_snapshot_failed")
        self.assertNotIn("secret", str(result.to_dict()))
        self.assertNotIn("design_result_ref", result.result)

    def test_calculation_adapter_exception_and_inconsistent_pass_are_safe(self):
        adapter = Mock()
        adapter.design.side_effect = RuntimeError("API_KEY=secret")
        result = ColumnDesignTool(self.store, adapter).execute(envelope())
        self.assertFalse(result.success)
        self.assertNotIn("secret", str(result.to_dict()))
        report = design_column(column_model())
        report["selected"]["intermediates"]["Nu_kN"] += 100
        adapter.design.side_effect = None
        adapter.design.return_value = report
        self.assertFalse(ColumnDesignTool(self.store, adapter).execute(envelope()).success)
        check_adapter = Mock()
        report = check_column(column_model(), actual_bars(14))
        report["status"] = "PASS"
        check_adapter.check.return_value = report
        self.assertFalse(ColumnCheckTool(self.store, check_adapter).execute(envelope(
            "check_column_design", {"model": column_model(), "actual": actual_bars(14)})).success)

    def test_tool_validation_checks_context_model_scope_and_strength_before_adapter(self):
        adapter = Mock()
        tool = ColumnDesignTool(self.store, adapter)
        edits = [("context", "unit_system", "SI"), ("context", "design_code", "GB"),
                 ("section", "b_mm", True), ("effective_length", "l0_mm", 15000.00001),
                 ("materials", "fc_MPa", 20), ("scope", "gamma_Rd", True)]
        for group, key, value in edits:
            request = envelope()
            (request["context"] if group == "context" else request["parameters"]["model"][group])[key] = value
            with self.subTest(group=group, key=key):
                with self.assertRaises(ToolValidationError):
                    tool.validate(request)
                self.assertFalse(tool.execute(request).success)
        adapter.design.assert_not_called()
        request = envelope()
        request["parameters"]["model"]["materials"]["fc_MPa"] = 20
        result = tool.execute(request)
        self.assertEqual(result.errors[0]["path"], ["parameters", "model", "materials", "fc_MPa"])

    def test_mutating_adapters_cannot_reduce_user_force_or_replace_actual_bars(self):
        def lowered_force_design(model):
            model["actions"]["N_kN"] = 1
            return design_column(model)

        adapter = Mock()
        adapter.design.side_effect = lowered_force_design
        request = envelope()
        original = deepcopy(request)
        result = ColumnDesignTool(self.store, adapter).execute(request)
        self.assertFalse(result.success)
        self.assertNotIn("design_result_ref", result.result)
        self.assertFalse(self.store.root.exists())
        self.assertEqual(request, original)
        for mutation in ("force", "actual"):
            def changed_actual_check(model, actual):
                if mutation == "force":
                    model["actions"]["N_kN"] = 1
                else:
                    actual["bar_diameter_mm"] = 16
                return check_column(model, actual)
            check_adapter = Mock()
            check_adapter.check.side_effect = changed_actual_check
            request = envelope("check_column_design", {"model": column_model(), "actual": actual_bars(14)})
            original = deepcopy(request)
            with self.subTest(mutation=mutation):
                result = ColumnCheckTool(self.store, check_adapter).execute(request)
                self.assertFalse(result.success)
                self.assertEqual(result.errors[0]["code"], "column_check_invalid")
                self.assertEqual(request, original)

    def test_reference_and_actual_inputs_are_mutually_exclusive(self):
        _, ref, _ = self.saved()
        bad = {"design_result_ref": ref, "model": column_model(), "actual": actual_bars(14)}
        self.assertFalse(self.check.execute(envelope("check_column_design", bad)).success)
        for parameters in ({"model": column_model()}, {"actual": actual_bars()}, {}):
            self.assertFalse(self.check.execute(envelope("check_column_design", parameters)).success)

    def test_invalid_missing_traversal_and_cross_project_reference_are_safe(self):
        _, ref, _ = self.saved()
        for reference, project in ((ref, "OTHER"), ("../secret", "COLUMN-TEST"),
                                   ("column-" + "a" * 32, "COLUMN-TEST"), (True, "COLUMN-TEST")):
            with self.subTest(reference=reference, project=project):
                result = self.check.execute(envelope("check_column_design", {"design_result_ref": reference}, project))
                self.assertFalse(result.success)
                self.assertNotIn(str(self.store.root), str(result.to_dict()))

    def test_bad_checksum_and_malformed_duplicate_json_are_rejected(self):
        _, ref, path = self.saved()
        original = path.read_text(encoding="utf-8")
        payload = json.loads(original)
        payload["design"]["result"]["selected"]["intermediates"]["Nu_kN"] += 1
        self.rewrite(path, payload, report_hash=False, full_hash=False)
        with self.assertRaises(ColumnReferenceError):
            self.store.load(ref, project_id="COLUMN-TEST")
        for raw in ("{}", '{"reference":1,"reference":2}', '{"value":NaN}', "not json"):
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(ColumnReferenceError):
                self.store.load(ref, project_id="COLUMN-TEST")

    def test_rehashed_report_tampering_still_rejected_by_recalculation(self):
        _, ref, path = self.saved()
        original = json.loads(path.read_text(encoding="utf-8"))
        mutations = [
            lambda data: data["result"]["selected"]["actual"].update(bar_diameter_mm=14),
            lambda data: data["result"]["selected"]["intermediates"].update(Nu_kN=9999),
            lambda data: data["result"]["attempts"][0]["checks"][0].update(passed=True),
            lambda data: data["result"]["attempts"].pop(0),
            lambda data: data["result"]["effective_input"]["actions"].update(N_kN=10000),
            lambda data: data["result"]["selected"]["materials"].update(fc_MPa=19.1),
            lambda data: data["result"]["selected"]["coverage"].update(not_checked=["nothing"]),
            lambda data: data["result"]["selected"]["basis"].update(area_policy="subtract steel"),
            lambda data: data["result"].update(selection_policy="pick biggest"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                payload = deepcopy(original)
                mutate(payload["design"])
                self.rewrite(path, payload)
                with self.assertRaises(ColumnReferenceError):
                    self.store.load(ref, project_id="COLUMN-TEST")

    def test_complete_larger_passing_candidate_is_not_minimal(self):
        _, ref, path = self.saved()
        payload = json.loads(path.read_text(encoding="utf-8"))
        next_report = check_column(column_model(), actual_bars(18))
        payload["design"]["result"]["attempts"].append(next_report)
        payload["design"]["result"]["selected"] = deepcopy(next_report)
        self.rewrite(path, payload)
        with self.assertRaises(ColumnReferenceError):
            self.store.load(ref, project_id="COLUMN-TEST")

    def test_reference_filename_payload_and_result_bindings_reject_swaps(self):
        _, first_ref, first_path = self.saved()
        _, second_ref, second_path = self.saved()
        self.assertNotEqual(first_ref, second_ref)
        original = json.loads(first_path.read_text(encoding="utf-8"))
        second_path.write_text(first_path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(ColumnReferenceError):
            self.store.load(second_ref, project_id="COLUMN-TEST")
        for target in ("payload", "result", "metadata"):
            payload = deepcopy(original)
            if target == "payload":
                payload["reference"] = second_ref
            else:
                payload["design"][target]["design_result_ref"] = second_ref
            self.rewrite(first_path, payload)
            with self.subTest(target=target), self.assertRaises(ColumnReferenceError):
                self.store.load(first_ref, project_id="COLUMN-TEST")

    def test_duplicate_uuid_cannot_overwrite_or_return_a_reference(self):
        with patch("tools.column.design_store.uuid4", return_value=UUID(int=1)):
            _, ref, path = self.saved()
            original = path.read_bytes()
            result = self.design.execute(envelope())
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "column_snapshot_failed")
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn("design_result_ref", result.result)
        self.assertTrue(self.store.load(ref, project_id="COLUMN-TEST").success)

    def test_store_refuses_failed_or_wrong_tool_results(self):
        raw = design_column(column_model())
        bad = ToolResult(True, "other", "1.0.0", result=raw, metadata={"project_id": "COLUMN-TEST"})
        with self.assertRaises(ColumnReferenceError):
            self.store.save(bad)
        raw["status"] = "FAIL"
        with self.assertRaises(ValueError):
            self.store.save(ToolResult(False, "design_column", "1.0.0", result=raw,
                                      errors=[{"code": "fail", "message": "fail", "path": []}],
                                      metadata={"project_id": "COLUMN-TEST"}))


if __name__ == "__main__":
    unittest.main()
