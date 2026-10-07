"""Evaluate every declared axial combination against one fixed actual scheme."""
from copy import deepcopy
from decimal import Decimal

from core.validation import ensure_json, make_validator, validate_json
from .calculation import check_column, validate_actual
from .combination_input import COMBINATION_PARAMETERS_SCHEMA, compose_model, validate_combinations
from .materials import CANDIDATE_DIAMETERS_MM
from .schemas import ACTUAL_SCHEMA, NONEMPTY, POSITIVE, REPORT_SCHEMA, object_schema

SELECTION_POLICY = "first all-combinations all-PASS diameter in [12,14,16,18,20,22,25,28]; all user inputs fixed"
CONTROL_POLICY = "maximum exact input N with common section/materials/effective length and capacity; retain all ties in input order; construction failures are separate"
COVERAGE = {
    "checked": ["every declared v1 ideal axial check for each complete combination",
                "declared force-vector identities, units, effective-length analysis and common member/section",
                "minimum fixed four-corner scheme passing every combination in design mode"],
    "not_checked": ["truth or completeness of external analysis and supplied combinations",
                    "source force and effective-length analysis", "floor reactions and wall transfer",
                    "eccentric compression and additional eccentricity", "frame second-order analysis",
                    "seismic design", "anchorage, joints, full detailing and environment/fire cover"],
    "pass_meaning": "PASS means declared checks for supplied combinations only; provenance consistency is not source-analysis approval.",
}
CHECK_SET_SCHEMA = object_schema({
    "status": {"enum": ["PASS", "FAIL"]}, "effective_input": COMBINATION_PARAMETERS_SCHEMA,
    "actual": ACTUAL_SCHEMA,
    "combination_results": {"type": "array", "minItems": 1, "maxItems": 32,
        "items": object_schema({"combination_id": NONEMPTY,
            "source": COMBINATION_PARAMETERS_SCHEMA["properties"]["combinations"]["items"]["properties"]["source"],
            "report": REPORT_SCHEMA})},
    "controlling_combination_ids": {"type": "array", "minItems": 1, "maxItems": 32, "items": NONEMPTY, "uniqueItems": True},
    "maximum_utilization": POSITIVE, "capacity_control_policy": {"const": CONTROL_POLICY},
    "coverage": object_schema({"checked": {"type": "array", "items": NONEMPTY, "minItems": 1},
        "not_checked": {"type": "array", "items": NONEMPTY, "minItems": 1}, "pass_meaning": NONEMPTY}),
})
DESIGN_SET_SCHEMA = object_schema({
    "status": {"enum": ["PASS", "FAIL"]}, "effective_input": COMBINATION_PARAMETERS_SCHEMA,
    "selected": {"anyOf": [CHECK_SET_SCHEMA, {"type": "null"}]},
    "attempts": {"type": "array", "items": CHECK_SET_SCHEMA, "minItems": 1, "maxItems": len(CANDIDATE_DIAMETERS_MM)},
    "selection_policy": {"const": SELECTION_POLICY},
})
SET_REFERENCE_SCHEMA = {"type": "string", "pattern": r"^column-set-[0-9a-f]{32}$"}
DESIGN_SET_OUTPUT = object_schema({**DESIGN_SET_SCHEMA["properties"], "design_result_ref": SET_REFERENCE_SCHEMA})
CHECK_SET_OUTPUT = deepcopy(CHECK_SET_SCHEMA)
CHECK_SET_OUTPUT["properties"]["design_result_ref"] = SET_REFERENCE_SCHEMA


def check_column_combinations(parameters, actual):
    """No design call; preserve each group's full vector and source, including FAIL."""
    validate_combinations(parameters)
    validate_actual(actual)
    reports = [{"combination_id": group["combination_id"], "source": deepcopy(group["source"]),
                "report": check_column(compose_model(parameters, group), deepcopy(actual))}
               for group in parameters["combinations"]]
    maximum_n = max(Decimal(str(group["actions"]["N_kN"])) for group in parameters["combinations"])
    controlling = [index for index, group in enumerate(parameters["combinations"])
                   if Decimal(str(group["actions"]["N_kN"])) == maximum_n]
    coverage = deepcopy(COVERAGE)
    # Design's minimum candidate selection is not performed by actual-scheme checking.
    coverage["checked"] = coverage["checked"][:2]
    result = {"status": "PASS" if all(row["report"]["status"] == "PASS" for row in reports) else "FAIL",
              "effective_input": deepcopy(parameters), "actual": deepcopy(actual), "combination_results": reports,
              "controlling_combination_ids": [reports[index]["combination_id"] for index in controlling],
              "maximum_utilization": reports[controlling[0]]["report"]["intermediates"]["utilization"],
              "capacity_control_policy": CONTROL_POLICY, "coverage": coverage}
    ensure_json(result)
    return result


def design_column_combinations(parameters):
    validate_combinations(parameters)
    attempts = []
    selected = None
    for diameter in CANDIDATE_DIAMETERS_MM:
        report = check_column_combinations(parameters, {"bar_count": 4, "bar_diameter_mm": diameter, "layout": "four_corner_bars"})
        attempts.append(report)
        if report["status"] == "PASS":
            selected = deepcopy(report)
            break
    return {"status": "PASS" if selected else "FAIL", "effective_input": deepcopy(parameters),
            "selected": selected, "attempts": attempts, "selection_policy": SELECTION_POLICY}


def validate_set_check_semantics(report, expected_parameters, expected_actual):
    """Recheck the supplied actual scheme and all groups, without design selection.

    A structurally valid report still must match the original request/reference;
    it cannot replace bars, omit a group, or alter its declared source or controls.
    """
    validate_json(report, make_validator(CHECK_SET_OUTPUT))
    payload = {key: deepcopy(value) for key, value in report.items() if key != "design_result_ref"}
    if payload != check_column_combinations(deepcopy(expected_parameters), deepcopy(expected_actual)):
        raise ValueError("Combination check differs from supplied input and actual-scheme recalculation")


def validate_set_design_semantics(report):
    """Verify each actual candidate independently; never run design selection."""
    validate_json(report, make_validator(DESIGN_SET_SCHEMA))
    validate_combinations(report["effective_input"])
    first_pass = None
    for index, attempt in enumerate(report["attempts"]):
        actual = {"bar_count": 4, "bar_diameter_mm": CANDIDATE_DIAMETERS_MM[index], "layout": "four_corner_bars"}
        if attempt != check_column_combinations(report["effective_input"], actual):
            raise ValueError("Combination report differs from independent actual-scheme recalculation")
        if attempt["status"] == "PASS":
            if index != len(report["attempts"]) - 1:
                raise ValueError("Candidate sequence continued after PASS")
            first_pass = attempt
    if (report["selected"] != first_pass or report["status"] != ("PASS" if first_pass else "FAIL")
            or first_pass is None and len(report["attempts"]) != len(CANDIDATE_DIAMETERS_MM)):
        raise ValueError("Combination status, selected scheme or candidate prefix is inconsistent")
