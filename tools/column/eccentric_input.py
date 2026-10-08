"""Strict phase19 uniaxial eccentric column input contract.

Owns only the JSON input contract for section-level final N/M eccentric
compression. It reuses the phase17 shared model, phase18 tie detailing and
source-consistency rules, and never re-implements eccentric resistance
algorithms or the legacy ``validate_model`` (which assumes ideal axial
compression).
"""

from copy import deepcopy
from decimal import Decimal, localcontext

from core.validation import make_validator, reject, validate_json

from .combination_input import (COMBINATION_SCHEMA, COMMON_MODEL_SCHEMA, ID_SCHEMA,
                                _validate_consistency)
from .materials import (CANDIDATE_DIAMETERS_MM, CONCRETE_FC_MPA,
                        LONGITUDINAL_FY_COMPRESSION_MPA, TIE_FY_MPA)
from .schemas import NONEMPTY, POSITIVE, object_schema

# --- Model -----------------------------------------------------------------
# Same base as the shared combination model: section/materials/effective_length
# (with traceability analysis_id), ties, scope and actions.
_MODEL_SCHEMA = deepcopy(COMMON_MODEL_SCHEMA)

# ties reuse phase18 fields; configuration is fixed and not applicable.
_TIES_SCHEMA = _MODEL_SCHEMA["properties"]["ties"]
_TIES_SCHEMA["properties"].pop("configuration")
_TIES_SCHEMA["required"].remove("configuration")
for _key in ("hook_angle_deg", "hook_extension_mm"):
    _TIES_SCHEMA["properties"][_key] = deepcopy(POSITIVE)
    _TIES_SCHEMA["required"].append(_key)

# scope of the eccentric contract: single-axis eccentric compression.
_MODEL_SCHEMA["properties"]["scope"] = object_schema({
    "purpose": {"const": "teaching"},
    "loading": {"const": "static"},
    "seismic": {"type": "boolean", "const": False},
    "uniaxial_eccentric_compression": {"type": "boolean", "const": True},
    "gamma_Rd": {"type": "number", "const": 1},
})

# effective_length records the declared bending plane covered by the analysis.
_MODEL_SCHEMA["properties"]["effective_length"] = object_schema({
    "lc_mm": deepcopy(POSITIVE), "source": deepcopy(NONEMPTY),
    "analysis_id": deepcopy(ID_SCHEMA), "covers_bending_plane": {"type": "boolean", "const": True},
})

# bending_axis selects which principal axis the single nonzero moment acts on.
_MODEL_SCHEMA["properties"]["bending_axis"] = {"enum": ["x", "y"]}
_MODEL_SCHEMA["required"].append("bending_axis")

# Optional explicit material strengths; when present they must match the grade.
_MATERIALS_SCHEMA = _MODEL_SCHEMA["properties"]["materials"]
for _key in ("fy_tension_MPa", "Es_MPa"):
    _MATERIALS_SCHEMA["properties"][_key] = deepcopy(POSITIVE)

# --- Actions ---------------------------------------------------------------
# Section-level final N/M for one combination: N>0; exactly the selected axis
# may carry a nonzero moment; the other moment and both shears are explicitly
# zero. Moments are finite numbers with no magnitude restriction.
_ACTIONS_SCHEMA = object_schema({
    "N_kN": deepcopy(POSITIVE),
    "Mx_kN_m": {"type": "number"}, "My_kN_m": {"type": "number"},
    "Vx_kN": {"type": "number", "const": 0}, "Vy_kN": {"type": "number", "const": 0},
    "N_includes_gamma0": {"type": "boolean", "const": True},
    "M_includes_gamma0": {"type": "boolean", "const": True},
    "combination_source": deepcopy(NONEMPTY),
})

# --- Second order ----------------------------------------------------------
# Both frame P-Delta and member P-delta must be declared already handled
# externally, on the same analysis/combination as the group and common length.
_SECOND_ORDER_SCHEMA = object_schema({
    "analysis_id": deepcopy(ID_SCHEMA),
    "combination_id": deepcopy(ID_SCHEMA),
    "frame_P_Delta_included": {"type": "boolean", "const": True},
    "member_P_delta_included": {"type": "boolean", "const": True},
    "additional_eccentricity_included": {"type": "boolean", "const": False},
    "source": deepcopy(NONEMPTY),
})

_SOURCE_SCHEMA = COMBINATION_SCHEMA["properties"]["source"]

COMBINATION_SCHEMA = object_schema({
    "combination_id": deepcopy(ID_SCHEMA),
    "actions": _ACTIONS_SCHEMA,
    "source": deepcopy(_SOURCE_SCHEMA),
    "second_order": deepcopy(_SECOND_ORDER_SCHEMA),
})

PARAMETERS_SCHEMA = object_schema({
    "model": _MODEL_SCHEMA,
    "combinations": {
        "type": "array",
        "items": COMBINATION_SCHEMA,
        "minItems": 1,
        "maxItems": 32,
    },
})

# --- Actual ----------------------------------------------------------------
# Phase18 actual structure, fixed to a symmetric four corner-bar scheme with no
# crossties; the three boolean declarations remain mandatory (empty crossties
# mean per-layer/end crosstie declarations are not applicable but still typed).
ACTUAL_SCHEMA = object_schema({
    "bar_count": {"type": "integer", "const": 4},
    "bar_diameter_mm": {"type": "number", "enum": list(CANDIDATE_DIAMETERS_MM)},
    "layout": {"const": "four_corner_bars"},
    "perimeter_closed": {"type": "boolean"},
    "crosstie_axes": {"type": "array", "maxItems": 0},
    "crossties_at_every_layer": {"type": "boolean"},
    "ends_engage_bars": {"type": "boolean"},
})

_PARAMETERS_VALIDATOR = make_validator(PARAMETERS_SCHEMA)
_ACTUAL_VALIDATOR = make_validator(ACTUAL_SCHEMA)

__all__ = ["PARAMETERS_SCHEMA", "ACTUAL_SCHEMA", "validate_parameters", "validate_actual"]


def _validate_eccentric_consistency(parameters):
    """Preserve all shared source consistency, then add eccentric rules."""
    combinations = parameters["combinations"]
    analysis_id = parameters["model"]["effective_length"]["analysis_id"]

    # Reuse the phase17 source-identity checks without rebuilding the model.
    _validate_consistency(parameters)

    for index, combination in enumerate(combinations):
        actions = combination["actions"]
        axis = parameters["model"]["bending_axis"]
        second_order = combination["second_order"]

        if second_order["analysis_id"] != analysis_id:
            reject(
                "second_order.analysis_id must match model.effective_length.analysis_id.",
                ("parameters", "combinations", index, "second_order", "analysis_id"),
                "column_combination_analysis_mismatch",
            )
        if second_order["combination_id"] != combination["combination_id"]:
            reject(
                "second_order.combination_id must match the containing combination_id.",
                ("parameters", "combinations", index, "second_order", "combination_id"),
                "column_combination_source_mismatch",
            )

        active = actions["Mx_kN_m"] if axis == "x" else actions["My_kN_m"]
        inactive_key = "My_kN_m" if axis == "x" else "Mx_kN_m"
        inactive = actions[inactive_key]
        if active == 0:
            reject(
                f"The active bending axis {axis} moment must be nonzero.",
                ("parameters", "combinations", index, "actions",
                 "Mx_kN_m" if axis == "x" else "My_kN_m"),
                "column_eccentric_action_scope",
            )
        if inactive != 0:
            reject(
                "Only the bending_axis moment may be nonzero; the other axis must be zero.",
                ("parameters", "combinations", index, "actions", inactive_key),
                "column_eccentric_action_scope",
            )


def _validate_materials(model):
    material = model["materials"]
    expected = {"fc_MPa": CONCRETE_FC_MPA[material["concrete"]],
                "fy_compression_MPa": LONGITUDINAL_FY_COMPRESSION_MPA[material["longitudinal_steel"]],
                "tie_fy_MPa": TIE_FY_MPA[material["tie_steel"]],
                "fy_tension_MPa": LONGITUDINAL_FY_COMPRESSION_MPA[material["longitudinal_steel"]],
                "Es_MPa": "200000"}
    with localcontext() as ctx:
        ctx.prec = 60
        for key, value in expected.items():
            if key in material and Decimal(str(material[key])) != Decimal(value):
                reject(
                    f"Explicit {key}={material[key]} conflicts with grade table value {value}MPa.",
                    ("parameters", "model", "materials", key),
                    "column_material_conflict",
                )


def _validate_scope(model):
    section = model["section"]
    ties = model["ties"]
    with localcontext() as ctx:
        ctx.prec = 60
        if Decimal(str(section["cover_to_outer_tie_mm"])) + Decimal(str(ties["diameter_mm"])) > 50:
            reject(
                "Longitudinal outer cover c+dt >50mm requires measures outside this contract.",
                ("parameters", "model", "section", "cover_to_outer_tie_mm"),
                "column_scope_error",
            )


def validate_parameters(parameters):
    """Validate the complete eccentric parameters contract.

    Structural and type errors use ``parameters.model``/``parameters.combinations[i]``
    paths; cross-field rules use the same contract paths. The input is not mutated.
    """
    validate_json(parameters, _PARAMETERS_VALIDATOR, prefix=("parameters",))
    _validate_materials(parameters["model"])
    _validate_scope(parameters["model"])
    _validate_eccentric_consistency(parameters)
    return None


def validate_actual(actual):
    """Validate one fixed four corner-bar actual scheme; return None on success."""
    validate_json(actual, _ACTUAL_VALIDATOR, prefix=("actual",))
    if actual["crosstie_axes"]:
        reject(
            "crosstie_axes must be empty for the four corner-bar scheme.",
            ("actual", "crosstie_axes"),
            "column_eccentric_actual_scope",
        )
    return None
