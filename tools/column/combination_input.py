"""Strict shared-model input contract for column combinations.

The module owns only the input contract and the pure copy that turns one
validated combination into the existing v1 column model. Engineering checks
remain in :mod:`tools.column.calculation`.
"""

from copy import deepcopy

from core import ToolValidationError
from core.validation import make_validator, reject, validate_json

from .calculation import validate_model
from .schemas import MODEL_SCHEMA, NONEMPTY, object_schema

UNIT_SYSTEM = "mm,kN,kN.m,MPa"

# IDs are explicit source identifiers: 1-128 characters and no whitespace.
ID_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": r"^\S+$",
    "not": {"pattern": r"\s"},
}

# The common model is the v1 MODEL_SCHEMA with actions removed. The traceability
# analysis_id is appended to the otherwise shared effective_length object.
_COMMON_MODEL_SCHEMA = deepcopy(MODEL_SCHEMA)
_COMMON_MODEL_SCHEMA["properties"].pop("actions")
_COMMON_MODEL_SCHEMA["required"].remove("actions")
_EFFECTIVE_LENGTH_SCHEMA = _COMMON_MODEL_SCHEMA["properties"]["effective_length"]
_EFFECTIVE_LENGTH_SCHEMA["properties"]["analysis_id"] = deepcopy(ID_SCHEMA)
_EFFECTIVE_LENGTH_SCHEMA["required"].append("analysis_id")

COMMON_MODEL_SCHEMA = _COMMON_MODEL_SCHEMA

_ACTIONS_SCHEMA = deepcopy(MODEL_SCHEMA["properties"]["actions"])

_SOURCE_SCHEMA = object_schema({
    "analysis_id": deepcopy(ID_SCHEMA),
    "member_id": deepcopy(ID_SCHEMA),
    "section_id": deepcopy(ID_SCHEMA),
    "combination_id": deepcopy(ID_SCHEMA),
    "force_record_id": deepcopy(ID_SCHEMA),
    "description": deepcopy(NONEMPTY),
    "unit_system": {"const": UNIT_SYSTEM},
    "same_force_vector": {"type": "boolean", "const": True},
})

COMBINATION_SCHEMA = object_schema({
    "combination_id": deepcopy(ID_SCHEMA),
    "actions": deepcopy(_ACTIONS_SCHEMA),
    "source": deepcopy(_SOURCE_SCHEMA),
})

COMBINATION_PARAMETERS_SCHEMA = object_schema({
    "model": deepcopy(COMMON_MODEL_SCHEMA),
    "combinations": {
        "type": "array",
        "items": deepcopy(COMBINATION_SCHEMA),
        "minItems": 1,
        "maxItems": 32,
    },
})

_PARAMETERS_VALIDATOR = make_validator(COMBINATION_PARAMETERS_SCHEMA)

__all__ = [
    "COMMON_MODEL_SCHEMA",
    "COMBINATION_SCHEMA",
    "COMBINATION_PARAMETERS_SCHEMA",
    "validate_combinations",
    "compose_model",
]


def compose_model(parameters, combination):
    """Return a fresh complete v1 model for one already-validated combination.

    This helper deliberately performs no validation and never calls
    ``validate_combinations``; callers must establish the full contract first.
    """
    model = deepcopy(parameters["model"])
    model["effective_length"].pop("analysis_id", None)
    model["actions"] = deepcopy(combination["actions"])
    return model


def _map_validation_error(error, index):
    """Move a v1 validate_model error path onto the combination parameters."""
    path = list(error.get("path", ()))
    if path and path[0] == "model":
        path = path[1:]
    if path and path[0] == "actions":
        mapped_path = ["parameters", "combinations", index, "actions", *path[1:]]
    else:
        mapped_path = ["parameters", "model", *path]
    return {**error, "path": mapped_path}


def _validate_consistency(parameters):
    combinations = parameters["combinations"]
    analysis_id = parameters["model"]["effective_length"]["analysis_id"]
    combination_ids = set()
    force_record_ids = set()
    member_id = combinations[0]["source"]["member_id"]
    section_id = combinations[0]["source"]["section_id"]

    for index, combination in enumerate(combinations):
        combination_id = combination["combination_id"]
        if combination_id in combination_ids:
            reject(
                f"combination_id {combination_id!r} is duplicated; each combination_id must be unique.",
                ("parameters", "combinations", index, "combination_id"),
                "column_combination_duplicate",
            )
        combination_ids.add(combination_id)

        source = combination["source"]
        force_record_id = source["force_record_id"]
        if force_record_id in force_record_ids:
            reject(
                f"source.force_record_id {force_record_id!r} is duplicated; each force_record_id must be unique.",
                ("parameters", "combinations", index, "source", "force_record_id"),
                "column_combination_duplicate",
            )
        force_record_ids.add(force_record_id)

        if source["combination_id"] != combination_id:
            reject(
                "source.combination_id must match the containing combination_id.",
                ("parameters", "combinations", index, "source", "combination_id"),
                "column_combination_source_mismatch",
            )
        if source["analysis_id"] != analysis_id:
            reject(
                "source.analysis_id must match model.effective_length.analysis_id.",
                ("parameters", "combinations", index, "source", "analysis_id"),
                "column_combination_analysis_mismatch",
            )
        if source["member_id"] != member_id:
            reject(
                "All combinations must bind to the same source.member_id.",
                ("parameters", "combinations", index, "source", "member_id"),
                "column_combination_member_mismatch",
            )
        if source["section_id"] != section_id:
            reject(
                "All combinations must bind to the same source.section_id.",
                ("parameters", "combinations", index, "source", "section_id"),
                "column_combination_section_mismatch",
            )


def validate_combinations(parameters):
    """Validate the complete shared-model combinations contract.

    The input must not be mutated by this function. Structural and type errors
    use ``parameters.model``/``parameters.combinations[i]...`` paths; v1
    engineering errors from ``validate_model`` are remapped onto the same
    contract paths while preserving the original codes and messages.
    """
    validate_json(parameters, _PARAMETERS_VALIDATOR, prefix=("parameters",))
    _validate_consistency(parameters)

    for index, combination in enumerate(parameters["combinations"]):
        model = compose_model(parameters, combination)
        try:
            validate_model(model)
        except ToolValidationError as exc:
            raise ToolValidationError(
                [_map_validation_error(error, index) for error in exc.errors]
            ) from None
    return None
