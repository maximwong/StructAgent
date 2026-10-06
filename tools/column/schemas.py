"""Explicit column input; no defaults, inferred units, or source analysis."""

from .materials import CANDIDATE_DIAMETERS_MM, CONCRETE_FC_MPA


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NUMBER = {"type": "number"}
NONEMPTY = {"type": "string", "minLength": 1, "pattern": r"\S"}
DESIGN_CODE = "GB/T 50010-2010(2024);GB 55008-2021"
UNITS = {"length": "mm", "force": "kN", "moment": "kN.m", "stress": "MPa"}
CONTEXT_SCHEMA = object_schema({
    "unit_system": {"const": "mm,kN,kN.m,MPa"},
    "design_code": {"const": DESIGN_CODE},
})
MATERIAL_INPUT_SCHEMA = object_schema({
    "concrete": {"enum": list(CONCRETE_FC_MPA)},
    "longitudinal_steel": {"const": "HRB400"},
    "tie_steel": {"const": "HPB300"},
})
MATERIAL_INPUT_SCHEMA["properties"].update({
    key: POSITIVE for key in ("fc_MPa", "fy_compression_MPa", "tie_fy_MPa")
})
MODEL_SCHEMA = object_schema({
    "section": object_schema({
        "b_mm": {"type": "number", "minimum": 300},
        "h_mm": {"type": "number", "minimum": 300},
        "cover_to_outer_tie_mm": POSITIVE,
    }),
    "effective_length": object_schema({
        "l0_mm": POSITIVE, "source": NONEMPTY,
        "covers_both_principal_axes": {"type": "boolean", "const": True},
    }),
    "actions": object_schema({
        "N_kN": POSITIVE,
        **{key: {"type": "number", "const": 0} for key in ("Mx_kN_m", "My_kN_m", "Vx_kN", "Vy_kN")},
        "N_includes_gamma0": {"type": "boolean", "const": True},
        "combination_source": NONEMPTY,
    }),
    "materials": MATERIAL_INPUT_SCHEMA,
    "ties": object_schema({
        "configuration": {"const": "single_closed_rectangular"},
        "diameter_mm": POSITIVE, "spacing_mm": POSITIVE,
    }),
    "scope": object_schema({
        "purpose": {"const": "teaching"}, "loading": {"const": "static"},
        "seismic": {"type": "boolean", "const": False},
        "ideal_axial_compression": {"type": "boolean", "const": True},
        "gamma_Rd": {"type": "number", "const": 1},
    }),
})
ACTUAL_SCHEMA = object_schema({
    "bar_count": {"type": "integer", "const": 4},
    "bar_diameter_mm": {"type": "number", "enum": list(CANDIDATE_DIAMETERS_MM)},
    "layout": {"const": "four_corner_bars"},
})
DESIGN_PARAMETERS = object_schema({"model": MODEL_SCHEMA})
CHECK_MODEL_PARAMETERS = object_schema({"model": MODEL_SCHEMA, "actual": ACTUAL_SCHEMA})
CHECK_ROW_SCHEMA = object_schema({
    "id": NONEMPTY, "label": NONEMPTY, "value": NUMBER,
    "relation": {"enum": ["<=", ">="]}, "limit": NUMBER,
    "passed": {"type": "boolean"}, "basis": NONEMPTY,
})
REPORT_SCHEMA = object_schema({
    "status": {"enum": ["PASS", "FAIL"]}, "effective_input": MODEL_SCHEMA,
    "actual": ACTUAL_SCHEMA,
    "materials": object_schema({
        "table_version": NONEMPTY, "concrete": NONEMPTY,
        "longitudinal_steel": NONEMPTY, "tie_steel": NONEMPTY,
        "fc_MPa": POSITIVE, "fy_compression_MPa": POSITIVE, "tie_fy_MPa": POSITIVE,
    }),
    "basis": object_schema({
        "scope_version": NONEMPTY, "design_code": {"const": DESIGN_CODE},
        "units": object_schema({key: {"const": value} for key, value in UNITS.items()}),
        "capacity_formula": NONEMPTY, "area_policy": NONEMPTY,
        "phi_policy": NONEMPTY, "gamma_Rd": {"type": "number", "const": 1},
    }),
    "intermediates": object_schema({key: NUMBER for key in (
        "gross_area_mm2", "slenderness_ratio", "phi_node_ratio", "phi",
        "capacity_required_area_mm2", "minimum_total_area_mm2", "minimum_side_area_mm2",
        "total_area_mm2", "side_area_mm2", "rho_total", "rho_side",
        "Nu_kN", "utilization", "longitudinal_outer_cover_mm",
        "center_spacing_b_mm", "center_spacing_h_mm", "clear_spacing_b_mm", "clear_spacing_h_mm",
        "minimum_tie_diameter_mm", "maximum_tie_spacing_mm",
    )}),
    "checks": {"type": "array", "items": CHECK_ROW_SCHEMA, "minItems": 1},
    "coverage": object_schema({
        "checked": {"type": "array", "items": NONEMPTY, "minItems": 1},
        "not_checked": {"type": "array", "items": NONEMPTY, "minItems": 1},
        "pass_meaning": NONEMPTY,
    }),
})
DESIGN_REPORT_SCHEMA = object_schema({
    "status": {"enum": ["PASS", "FAIL"]}, "effective_input": MODEL_SCHEMA,
    "selected": {"anyOf": [REPORT_SCHEMA, {"type": "null"}]},
    "attempts": {"type": "array", "items": REPORT_SCHEMA, "minItems": 1,
                 "maxItems": len(CANDIDATE_DIAMETERS_MM)},
    "selection_policy": NONEMPTY,
})
