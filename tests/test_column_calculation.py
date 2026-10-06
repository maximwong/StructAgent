"""Frozen independent references, strict boundaries, and actual-bar checks."""

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from core import ToolValidationError
from core.validation import make_validator, validate_json
from tools.column.calculation import check_column, design_column, validate_model
from tools.column.materials import CONCRETE_FC_MPA, FOUR_BAR_AREA_MM2, PHI_TABLE
from tools.column.schemas import DESIGN_REPORT_SCHEMA, REPORT_SCHEMA

REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "column_references.json").read_text(encoding="utf-8"))


def column_model(case="short"):
    expected = REFERENCE["cases"][case]
    return {
        "section": {"b_mm": 300, "h_mm": 300, "cover_to_outer_tie_mm": 30},
        "effective_length": {"l0_mm": expected["l0_mm"], "source": "independent teaching model controlling both axes",
                             "covers_both_principal_axes": True},
        "actions": {"N_kN": expected["N_kN"], "Mx_kN_m": 0, "My_kN_m": 0, "Vx_kN": 0, "Vy_kN": 0,
                    "N_includes_gamma0": True, "combination_source": "teaching ULS combination including gamma0"},
        "materials": {"concrete": "C30", "longitudinal_steel": "HRB400", "tie_steel": "HPB300"},
        "ties": {"configuration": "single_closed_rectangular", "diameter_mm": 8, "spacing_mm": 200},
        "scope": {"purpose": "teaching", "loading": "static", "seismic": False,
                  "ideal_axial_compression": True, "gamma_Rd": 1},
    }


def actual_bars(diameter=16):
    return {"bar_count": 4, "bar_diameter_mm": diameter, "layout": "four_corner_bars"}


class ColumnCalculationTests(unittest.TestCase):
    def test_independent_short_and_slender_references(self):
        for case, expected in REFERENCE["cases"].items():
            with self.subTest(case=case):
                model = column_model(case)
                original = deepcopy(model)
                design = design_column(model)
                validate_json(design, make_validator(DESIGN_REPORT_SCHEMA))
                self.assertEqual(model, original)
                self.assertEqual(design["status"], "PASS")
                selected = design["selected"]
                self.assertEqual(selected["actual"]["bar_diameter_mm"], expected["selected_diameter_mm"])
                self.assertTrue(all(row["passed"] for row in selected["checks"]))
                inter = selected["intermediates"]
                keys = ("slenderness_ratio", "phi_node_ratio", "phi", "total_area_mm2", "side_area_mm2",
                        "capacity_required_area_mm2", "minimum_tie_diameter_mm", "maximum_tie_spacing_mm")
                for key in keys:
                    self.assertAlmostEqual(inter[key], expected[key], delta=1e-9)
                self.assertAlmostEqual(inter["rho_total"], expected["rho"], delta=1e-12)
                self.assertAlmostEqual(inter["Nu_kN"], expected["Nu_kN"], delta=1e-6)
                self.assertAlmostEqual(inter["utilization"], expected["utilization"], delta=1e-12)
                for axis in ("b", "h"):
                    self.assertEqual(inter[f"center_spacing_{axis}_mm"], expected["center_spacing_mm"])
                    self.assertEqual(inter[f"clear_spacing_{axis}_mm"], expected["clear_spacing_mm"])
                for key in ("gross_area_mm2", "minimum_total_area_mm2", "minimum_side_area_mm2", "longitudinal_outer_cover_mm"):
                    self.assertEqual(inter[key], REFERENCE["common"][key])
                self.assertEqual(selected["materials"]["fc_MPa"], 14.3)
                self.assertEqual(selected["materials"]["fy_compression_MPa"], 360)
                self.assertEqual(selected["materials"]["tie_fy_MPa"], 270)
                previous = design["attempts"][-2]
                self.assertEqual(previous["status"], expected["previous_status"])
                self.assertEqual(previous["actual"]["bar_diameter_mm"], expected["previous_diameter_mm"])
                self.assertEqual(previous["intermediates"]["total_area_mm2"], expected["previous_area_mm2"])
                self.assertAlmostEqual(previous["intermediates"]["Nu_kN"], expected["previous_Nu_kN"], delta=1e-6)
                self.assertFalse(next(row for row in previous["checks"] if row["id"] == "axial_capacity")["passed"])
                self.assertEqual(selected, check_column(model, selected["actual"]))

    def test_reference_tables_are_literal_and_material_strengths_independent(self):
        self.assertEqual({str(k): v for k, v in FOUR_BAR_AREA_MM2.items()}, REFERENCE["four_bar_area_mm2"])
        self.assertEqual([[r, float(p)] for r, p in PHI_TABLE], REFERENCE["phi_table"])
        for concrete, expected_fc in {"C25": 11.9, "C30": 14.3, "C35": 16.7, "C40": 19.1}.items():
            model = column_model()
            model["materials"]["concrete"] = concrete
            self.assertEqual(check_column(model, actual_bars())["materials"]["fc_MPa"], expected_fc)
        self.assertEqual(list(CONCRETE_FC_MPA), ["C25", "C30", "C35", "C40"])

    def test_actual_failure_does_not_design_or_replace_bars(self):
        model, actual = column_model(), actual_bars(14)
        before = deepcopy(actual)
        with patch("tools.column.calculation.design_column", side_effect=AssertionError("must never design")):
            report = check_column(model, actual)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["actual"], before)
        self.assertEqual(actual, before)
        validate_json(report, make_validator(REPORT_SCHEMA))
        self.assertTrue(report["coverage"]["not_checked"])

    def test_capacity_boundary_has_no_acceptance_tolerance(self):
        model = column_model()
        model["actions"]["N_kN"] = 1418.796
        self.assertEqual(check_column(model, actual_bars())["status"], "PASS")
        model["actions"]["N_kN"] = math.nextafter(1418.796, math.inf)
        self.assertEqual(check_column(model, actual_bars())["status"], "FAIL")

    def test_stability_every_node_and_next_higher_policy(self):
        model = column_model()
        for ratio, phi in REFERENCE["phi_table"]:
            model["effective_length"]["l0_mm"] = ratio * 300
            inter = check_column(model, actual_bars())["intermediates"]
            self.assertEqual(inter["phi"], phi)
            self.assertEqual(inter["phi_node_ratio"], ratio)
        model["effective_length"]["l0_mm"] = 2400.0000001
        self.assertEqual(check_column(model, actual_bars())["intermediates"]["phi"], .98)
        model["effective_length"]["l0_mm"] = 15000.0000001
        with self.assertRaises(ToolValidationError):
            check_column(model, actual_bars())

    def test_rectangle_uses_min_dimension_and_both_spacing_directions(self):
        model = column_model("slender")
        model["section"]["h_mm"] = 400
        report = check_column(model, actual_bars(20))
        self.assertEqual(report["intermediates"]["slenderness_ratio"], 20)
        self.assertEqual(report["intermediates"]["center_spacing_b_mm"], 204)
        self.assertEqual(report["intermediates"]["center_spacing_h_mm"], 304)
        self.assertFalse(next(row for row in report["checks"] if row["id"] == "center_spacing_h")["passed"])

    def test_spacing_can_force_larger_bars_with_all_inputs_fixed(self):
        model = column_model()
        model["section"]["h_mm"] = 400
        before = deepcopy(model)
        design = design_column(model)
        self.assertEqual(design["selected"]["actual"]["bar_diameter_mm"], 25)
        self.assertEqual(model, before)
        self.assertTrue(all(attempt["effective_input"] == before for attempt in design["attempts"]))

    def test_failed_search_retains_all_attempts_and_reasons(self):
        model = column_model()
        model["actions"]["N_kN"] = 10000
        design = design_column(model)
        self.assertEqual(design["status"], "FAIL")
        self.assertIsNone(design["selected"])
        self.assertEqual([row["actual"]["bar_diameter_mm"] for row in design["attempts"]], [12,14,16,18,20,22,25,28])
        self.assertTrue(all(row["status"] == "FAIL" for row in design["attempts"]))
        validate_json(design, make_validator(DESIGN_REPORT_SCHEMA))

    def test_constructive_checks_and_exact_tie_spacing_boundary(self):
        model = column_model()
        model["actions"]["N_kN"] = 1
        report = check_column(model, actual_bars(12))
        self.assertFalse(next(row for row in report["checks"] if row["id"] == "total_ratio_min")["passed"])
        model["ties"]["spacing_mm"] = 240
        self.assertEqual(check_column(model, actual_bars())["status"], "PASS")
        model["ties"]["spacing_mm"] = 240.00000000001
        self.assertEqual(check_column(model, actual_bars())["status"], "FAIL")
        model["ties"].update({"diameter_mm": 6, "spacing_mm": 100})
        self.assertFalse(next(row for row in check_column(model, actual_bars(28))["checks"] if row["id"] == "tie_diameter")["passed"])
        model["section"]["cover_to_outer_tie_mm"] = 1
        self.assertFalse(next(row for row in check_column(model, actual_bars())["checks"] if row["id"] == "longitudinal_cover")["passed"])

    def test_cover_50_is_in_scope_and_above_is_rejected(self):
        model = column_model()
        model["section"]["cover_to_outer_tie_mm"] = 42
        validate_model(model)
        model["section"]["cover_to_outer_tie_mm"] = 42.00000000001
        with self.assertRaises(ToolValidationError) as caught:
            validate_model(model)
        self.assertEqual(caught.exception.errors[0]["code"], "column_scope_error")

    def test_missing_conflicting_and_unsupported_inputs_are_structured_errors(self):
        bad_edits = [
            ("section", "b_mm", 299.999), ("section", "h_mm", True), ("section", "b_mm", float("nan")),
            ("effective_length", "l0_mm", float("inf")), ("effective_length", "covers_both_principal_axes", False),
            ("effective_length", "source", " "), ("actions", "N_kN", False), ("actions", "N_kN", -1),
            ("actions", "Mx_kN_m", .000000001), ("actions", "My_kN_m", -1), ("actions", "Vx_kN", 1),
            ("actions", "Vy_kN", 1), ("actions", "N_includes_gamma0", False), ("actions", "combination_source", ""),
            ("materials", "concrete", "C50"), ("materials", "fc_MPa", 20), ("materials", "longitudinal_steel", "HPB300"),
            ("materials", "tie_steel", "HRB400"), ("ties", "configuration", "spiral"), ("ties", "diameter_mm", True),
            ("scope", "seismic", True), ("scope", "gamma_Rd", True), ("scope", "gamma_Rd", 1.1),
            ("scope", "loading", "dynamic"), ("scope", "ideal_axial_compression", False),
        ]
        for group, key, value in bad_edits:
            with self.subTest(group=group, key=key, value=value):
                model = column_model()
                model[group][key] = value
                with self.assertRaises(ValueError) as caught:
                    design_column(model)
                self.assertIsInstance(caught.exception, ToolValidationError)
                self.assertTrue(caught.exception.errors[0]["path"])
        for group, fields in column_model().items():
            for key in fields:
                with self.subTest(missing=(group, key)):
                    model = column_model()
                    del model[group][key]
                    with self.assertRaises(ToolValidationError):
                        check_column(model, actual_bars())

    def test_actual_configuration_rejected_before_calculation(self):
        for key, value in (("bar_count", True), ("bar_count", 6), ("bar_diameter_mm", True),
                           ("bar_diameter_mm", 24), ("layout", "two_rows")):
            actual = actual_bars()
            actual[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ToolValidationError):
                check_column(column_model(), actual)

    def test_optional_explicit_strengths_match_table_without_overriding_it(self):
        model = column_model()
        model["materials"].update({"fc_MPa": 14.3, "fy_compression_MPa": 360, "tie_fy_MPa": 270})
        report = check_column(model, actual_bars())
        self.assertEqual(report["status"], "PASS")
        validate_json(report, make_validator(REPORT_SCHEMA))
        for key in ("fc_MPa", "fy_compression_MPa", "tie_fy_MPa"):
            with self.subTest(key=key):
                bad = deepcopy(model)
                bad["materials"][key] += .001
                with self.assertRaises(ToolValidationError) as caught:
                    check_column(bad, actual_bars())
                self.assertEqual(caught.exception.errors[0]["path"], ["model", "materials", key])
                self.assertEqual(caught.exception.errors[0]["code"], "column_material_conflict")
                for invalid in (True, float("inf"), float("nan")):
                    bad["materials"][key] = invalid
                    with self.assertRaises(ToolValidationError):
                        validate_model(bad)

    def test_output_and_tables_do_not_share_input_or_previous_result(self):
        model = column_model()
        first = check_column(model, actual_bars())
        first["effective_input"]["materials"]["concrete"] = "C25"
        first["basis"]["units"]["length"] = "m"
        first["coverage"]["not_checked"].clear()
        second = check_column(model, actual_bars())
        self.assertEqual(model["materials"]["concrete"], "C30")
        self.assertEqual(second["basis"]["units"]["length"], "mm")
        self.assertTrue(second["coverage"]["not_checked"])


if __name__ == "__main__":
    unittest.main()
