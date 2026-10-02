"""Floor input contracts. Engineering checks remain in the legacy engine."""


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


NUMBER = {"type": "number", "minimum": 0}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
TEXT = {"type": "string"}
NONEMPTY = {"type": "string", "minLength": 1, "pattern": r"\S"}
OPTIONS = {"type": "array", "items": POSITIVE, "minItems": 1}

GEOMETRY = object_schema({
    "secondary_axis_spans_mm": {**OPTIONS, "minItems": 5, "maxItems": 5},
    "main_axis_spans_mm": {**OPTIONS, "minItems": 3, "maxItems": 3},
    **{key: NUMBER for key in (
        "secondary_spacing_mm", "wall_axis_to_inner_face_mm", "slab_bearing_mm",
        "secondary_bearing_mm", "main_bearing_mm", "column_width_mm")},
})
LOADS = object_schema({key: NUMBER for key in (
    "concrete_kN_m3", "finish_mm", "finish_kN_m3", "plaster_mm", "plaster_kN_m3",
    "live_kN_m2", "gamma_g", "gamma_q")})
MATERIALS = object_schema({
    "concrete": {"enum": ["C25", "C30", "C35", "C40"]},
    "slab_steel": {"const": "HPB300"}, "beam_steel": {"const": "HRB400"},
    "stirrup_steel": {"const": "HPB300"},
    **{key: NUMBER for key in (
        "fc_MPa", "ft_MPa", "alpha1", "slab_fy_MPa", "beam_fy_MPa",
        "stirrup_fy_MPa", "xi_elastic_limit", "xi_plastic_limit")},
})
SLAB = object_schema({
    **{key: NUMBER for key in ("h_mm", "cover_mm", "arch_factor", "distribution_diameter_mm")},
    "main_diameters_mm": OPTIONS, "spacings_mm": OPTIONS,
})
BEAM_PROPERTIES = {
    **{key: NUMBER for key in (
        "b_mm", "h_mm", "cover_mm", "stirrup_diameter_mm", "extra_top_mm", "max_stirrup_spacing_mm")},
    "stirrup_legs": {"type": "integer", "const": 2},
}
EXPLICIT_MODEL = object_schema({
    "project": NONEMPTY, "basis": NONEMPTY, "geometry": GEOMETRY, "loads": LOADS,
    "materials": MATERIALS, "slab": SLAB, "secondary": object_schema(BEAM_PROPERTIES),
    "main": object_schema({
        **BEAM_PROPERTIES, "support_moment": {"enum": ["axis", "face"]},
        "hanger_diameter_mm": NUMBER, "hanger_angle_deg": NUMBER,
    }),
    "detailing": object_schema({
        "beam_diameters_mm": OPTIONS, "maximum_rows": {"type": "integer", "enum": [1, 2]},
        **{key: NUMBER for key in ("aggregate_mm", "slab_support_extension_ratio", "slab_wall_extension_ratio")},
    }),
    "report": object_schema({
        **{key: TEXT for key in ("author", "class_name", "student_id", "date")},
        **{key: NUMBER for key in (
            "anchor_ribbed_factor", "anchor_plain_factor", "lap_factor", "max_stock_mm",
            "top_extension_ratio", "stirrup_hook_tail_d", "stirrup_bend_inner_d")},
        "allow_arch": {"type": "boolean"},
    }),
})
TEMPLATE_PARAMETERS = object_schema({
    "input_mode": {"const": "template"},
    "template_id": {"const": "office_floor_demo_v1"},
    "span_x": {**POSITIVE, "description": "主梁轴跨(mm)；次梁间距按模板取span_x/3。"},
    "span_y": {**POSITIVE, "description": "次梁轴跨(mm)，固定五个等轴跨。"},
    "concrete": {"enum": ["C25", "C30", "C35", "C40"]},
    "steel": {"const": "HRB400", "description": "仅梁纵筋；板筋和箍筋仍为HPB300。"},
    "live_load": {**NUMBER, "description": "楼面活荷载(kN/m²)。"},
})
EXPLICIT_PARAMETERS = object_schema({"input_mode": {"const": "explicit"}, "model": EXPLICIT_MODEL})
PARAMETERS_SCHEMA = {
    "type": "object",
    "required": ["input_mode"],
    "properties": {"input_mode": {"enum": ["template", "explicit"]}},
    "allOf": [{
        "if": {"properties": {"input_mode": {"const": "template"}}},
        "then": TEMPLATE_PARAMETERS, "else": EXPLICIT_PARAMETERS,
    }],
}
CONTEXT_SCHEMA = {
    "type": "object", "required": ["unit_system", "design_code"],
    "properties": {"unit_system": {"const": "SI"}, "design_code": {"const": "GB"}},
}

OBJECT = {"type": "object"}
ROWS = {"type": "array", "items": OBJECT, "minItems": 1}
OUTPUT_SCHEMA = object_schema({
    "slab": object_schema({"sections": ROWS, "distribution": OBJECT}),
    "secondary_beam": object_schema({"sections": ROWS, "shear_checks": ROWS}),
    "main_beam": object_schema({
        "sections": ROWS, "shear_checks": ROWS, "hanger": OBJECT, "suspension": OBJECT,
    }),
    "reinforcement": object_schema({"bars": ROWS}),
    "checks": object_schema({"joints": ROWS, "material": ROWS}),
    "effective_input": EXPLICIT_MODEL,
    "legacy_result": {
        "type": "object", "required": [
            "input", "loads", "spans", "slab", "secondary", "main", "bars",
            "joint_checks", "material_checks", "drawing_geometry", "chapters", "warnings",
        ],
    },
})
