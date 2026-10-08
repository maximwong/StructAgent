"""Strict layout inputs; provenance and engineering bounds reuse phase17 rules."""
from copy import deepcopy

from core.validation import make_validator, reject, validate_json
from .combination_input import validate_combinations
from .layout_schema import ACTUAL_SCHEMA, AXES, COUNTS, LAYOUTS, PARAMETERS_SCHEMA


def validate_parameters(parameters):
    validate_json(parameters, make_validator(PARAMETERS_SCHEMA), prefix=("parameters",))
    # Explicit validation view only; no implicit engineering defaults enter computation.
    legacy = {key: deepcopy(parameters[key]) for key in ("model", "combinations")}
    ties = legacy["model"]["ties"]
    legacy["model"]["ties"] = {"configuration": "single_closed_rectangular",
        **{key: ties[key] for key in ("diameter_mm", "spacing_mm")}}
    validate_combinations(legacy)


def validate_actual(actual):
    validate_json(actual, make_validator(ACTUAL_SCHEMA), prefix=("actual",))
    if actual["bar_count"] != COUNTS[actual["layout"]]:
        reject("bar_count must match the declared layout.", ("actual", "bar_count"), "column_layout_count_mismatch")
