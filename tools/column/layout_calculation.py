"""Deterministic symmetric layouts; check actual bars and declared restraint only."""
from copy import deepcopy
from decimal import Decimal, localcontext
from itertools import combinations

from core.validation import ensure_json, make_validator, validate_json
from .calculation import check_column
from .combination_input import compose_model
from .layout_input import ACTUAL_SCHEMA, AXES, COUNTS, LAYOUTS, PARAMETERS_SCHEMA, validate_actual, validate_parameters
from .materials import CANDIDATE_DIAMETERS_MM
from .schemas import CHECK_ROW_SCHEMA, NONEMPTY, NUMBER, POSITIVE, REPORT_SCHEMA, object_schema

# Literal Appendix A.0.1 columns, independently read from the original table.
AREA_TABLE = {
    12: {2: 226, 3: 339, 4: 452, 6: 678, 8: 904},
    14: {2: 308, 3: 461, 4: 615, 6: 923, 8: 1231},
    16: {2: 402, 3: 603, 4: 804, 6: 1206, 8: 1608},
    18: {2: 509, 3: 763, 4: 1017, 6: 1527, 8: 2036},
    20: {2: 628, 3: 942, 4: 1256, 6: 1884, 8: 2513},
    22: {2: 760, 3: 1140, 4: 1520, 6: 2281, 8: 3041},
    25: {2: 982, 3: 1473, 4: 1964, 6: 2945, 8: 3927},
    28: {2: 1232, 3: 1847, 4: 2463, 6: 3695, 8: 4926},
}
SELECTION_POLICY = "ascending Appendix A total area, count, diameter, fixed layout order; authorized layouts only; all other inputs fixed"
CONTROL_POLICY = "maximum exact supplied N; retain all tied combinations in input order"
COVERAGE = {
    "checked": ["every supplied ideal axial combination", "unique total and actual face nominal areas",
        "coordinates, every face segment and all bar-pair clear distances", "tie diameter/spacing and longitudinal cover",
        "declared closed perimeter, crosstie axes/every-layer/end engagement and conservative hook policy"],
    "not_checked": ["external analysis truth, effective length and complete combinations", "eccentric compression and additional eccentricity",
        "eccentric second-order effects and frame second-order analysis",
        "seismic design", "environment/fire cover", "anchorage, laps, joints and member ends",
        "fabricated hook radii/lengths, crosstie z staggering, collisions and full construction detailing"],
    "pass_meaning": "PASS is limited to supplied ideal axial inputs and declared restraints; not full engineering approval or a construction drawing.",
}
D = Decimal

BAR_SCHEMA = object_schema({"id": NONEMPTY, "x_mm": NUMBER, "y_mm": NUMBER})
SEGMENT_SCHEMA = object_schema({"bar_ids": {"type": "array", "items": NONEMPTY, "minItems": 2, "maxItems": 2},
    "center_mm": NUMBER, "clear_mm": NUMBER})
FACE_SCHEMA = object_schema({"face": {"enum": ["b_minus", "b_plus", "h_minus", "h_plus"]},
    "bar_ids": {"type": "array", "items": NONEMPTY, "minItems": 2, "maxItems": 3},
    "area_mm2": NUMBER, "rho": NUMBER,
    "segments": {"type": "array", "items": SEGMENT_SCHEMA, "minItems": 1, "maxItems": 2}})
TIE_SCHEMA = object_schema({"axis": {"enum": ["b", "h"]},
    "end_bar_ids": {"type": "array", "items": NONEMPTY, "minItems": 2, "maxItems": 2}})
SINGLE_SCHEMA = object_schema({
    "status": {"enum": ["PASS", "FAIL"]}, "actual": ACTUAL_SCHEMA,
    "materials": REPORT_SCHEMA["properties"]["materials"], "basis": REPORT_SCHEMA["properties"]["basis"],
    "intermediates": object_schema({key: NUMBER for key in ("gross_area_mm2", "phi", "phi_node_ratio", "slenderness_ratio",
        "total_area_mm2", "rho_total", "Nu_kN", "utilization", "capacity_required_area_mm2",
        "minimum_total_area_mm2", "minimum_side_area_mm2", "minimum_tie_diameter_mm", "maximum_tie_spacing_mm",
        "longitudinal_outer_cover_mm", "minimum_pair_clear_mm")}),
    "bars": {"type": "array", "items": BAR_SCHEMA, "minItems": 4, "maxItems": 8},
    "faces": {"type": "array", "items": FACE_SCHEMA, "minItems": 4, "maxItems": 4},
    "required_crossties": {"type": "array", "items": TIE_SCHEMA, "maxItems": 2},
    "checks": {"type": "array", "items": CHECK_ROW_SCHEMA, "minItems": 1},
})
CHECK_SCHEMA = object_schema({"status": {"enum": ["PASS", "FAIL"]}, "effective_input": PARAMETERS_SCHEMA,
    "actual": ACTUAL_SCHEMA, "combination_results": {"type": "array", "minItems": 1, "maxItems": 32,
        "items": object_schema({"combination_id": NONEMPTY,
            "source": PARAMETERS_SCHEMA["properties"]["combinations"]["items"]["properties"]["source"],
            "report": SINGLE_SCHEMA})},
    "controlling_combination_ids": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "maximum_utilization": POSITIVE, "capacity_control_policy": {"const": CONTROL_POLICY},
    "coverage": REPORT_SCHEMA["properties"]["coverage"]})
DESIGN_SCHEMA = object_schema({"status": {"enum": ["PASS", "FAIL"]}, "effective_input": PARAMETERS_SCHEMA,
    "selected": {"anyOf": [CHECK_SCHEMA, {"type": "null"}]},
    "attempts": {"type": "array", "items": CHECK_SCHEMA, "minItems": 1, "maxItems": 32},
    "selection_policy": {"const": SELECTION_POLICY}})
REFERENCE_SCHEMA = {"type": "string", "pattern": r"^column-layout-[0-9a-f]{32}$"}
DESIGN_OUTPUT = object_schema({**DESIGN_SCHEMA["properties"], "design_result_ref": REFERENCE_SCHEMA})
CHECK_OUTPUT = deepcopy(CHECK_SCHEMA)
CHECK_OUTPUT["properties"]["design_result_ref"] = REFERENCE_SCHEMA


def _legacy_model(parameters, group):
    model = compose_model(parameters, group)
    model["ties"] = {"configuration": "single_closed_rectangular",
        **{key: model["ties"][key] for key in ("diameter_mm", "spacing_mm")}}
    return model


def candidate_actual(layout, diameter):
    return {"layout": layout, "bar_count": COUNTS[layout], "bar_diameter_mm": diameter,
        "perimeter_closed": True, "crosstie_axes": list(AXES[layout]),
        "crossties_at_every_layer": True, "ends_engage_bars": True}


def candidate_sequence(parameters):
    candidates = [candidate_actual(layout, diameter) for layout in LAYOUTS
        if layout in parameters["layout_candidates"] for diameter in CANDIDATE_DIAMETERS_MM]
    return sorted(candidates, key=lambda row: (AREA_TABLE[int(row["bar_diameter_mm"])][row["bar_count"]],
        row["bar_count"], row["bar_diameter_mm"], LAYOUTS.index(row["layout"])))


def _check_single(parameters, group, actual):
    """Reuse verified v1 material/phi/tie rules, replace all four-bar-specific checks."""
    model = _legacy_model(parameters, group)
    diameter = actual["bar_diameter_mm"]
    base = check_column(model, {"bar_count": 4, "bar_diameter_mm": diameter, "layout": "four_corner_bars"})
    with localcontext() as context:
        context.prec = 60
        b, h, c = (D(str(model["section"][key])) for key in ("b_mm", "h_mm", "cover_to_outer_tie_mm"))
        dt = D(str(model["ties"]["diameter_mm"]))
        dia = D(str(diameter))
        x, y = b / 2 - c - dt - dia / 2, h / 2 - c - dt - dia / 2
        points = {"BL": (-x, -y), "BR": (x, -y), "TR": (x, y), "TL": (-x, y)}
        layout = actual["layout"]
        if layout in ("six_b", "eight_perimeter"):
            points.update(BM=(D(0), -y), TM=(D(0), y))
        if layout in ("six_h", "eight_perimeter"):
            points.update(LM=(-x, D(0)), RM=(x, D(0)))
        face_ids = {"b_minus": ["BL", "BM", "BR"], "b_plus": ["TL", "TM", "TR"],
                    "h_minus": ["BL", "LM", "TL"], "h_plus": ["BR", "RM", "TR"]}
        area = b * h
        steel = D(AREA_TABLE[int(dia)][actual["bar_count"]])
        fc, fy = (D(str(base["materials"][key])) for key in ("fc_MPa", "fy_compression_MPa"))
        phi = D(str(base["intermediates"]["phi"]))
        capacity = D(".9") * phi * (fc * area + fy * steel) / 1000
        force = D(str(group["actions"]["N_kN"]))
        # Keep only genuinely layout-independent v1 checks.
        checks = [deepcopy(row) for row in base["checks"]
            if row["id"] in ("tie_diameter", "tie_spacing", "longitudinal_cover")]

        def check(identifier, value, relation, limit, basis):
            checks.append({"id": identifier, "label": identifier.replace("_", " "), "value": float(value),
                "relation": relation, "limit": float(limit),
                "passed": value <= limit if relation == "<=" else value >= limit, "basis": basis})

        check("axial_capacity", force, "<=", capacity, "GB/T50010 6.2.15")
        check("total_ratio_min", steel / area, ">=", D(".0055"), "GB55008 4.4.6")
        check("total_ratio_max", steel / area, "<=", D(".03"), "plugin scope")
        faces = []
        for face, ids in face_ids.items():
            ids = [identifier for identifier in ids if identifier in points]
            face_area = D(AREA_TABLE[int(dia)][len(ids)])
            check(face + "_ratio_min", face_area / area, ">=", D(".002"), "GB55008 4.4.6")
            segments = []
            for index, (left, right) in enumerate(zip(ids, ids[1:])):
                center = sum((points[left][axis] - points[right][axis]) ** 2 for axis in (0, 1)).sqrt()
                clear = center - dia
                segments.append({"bar_ids": [left, right], "center_mm": float(center), "clear_mm": float(clear)})
                check(f"{face}_{index}_clear", clear, ">=", D(50), "GB/T50010 9.3.1")
                check(f"{face}_{index}_center", center, "<=", D(300), "GB/T50010 9.3.1")
            faces.append({"face": face, "bar_ids": ids, "area_mm2": float(face_area),
                "rho": float(face_area / area), "segments": segments})
        minimum_clear = min(sum((a[axis] - z[axis]) ** 2 for axis in (0, 1)).sqrt() - dia
            for a, z in combinations(points.values(), 2))
        check("all_bar_pairs_clear", minimum_clear, ">=", D(50), "plugin geometric non-overlap and clear-distance policy")
        topology = [("b", ["LM", "RM"]), ("h", ["BM", "TM"])]
        required = [{"axis": axis, "end_bar_ids": ids} for axis, ids in topology if axis in AXES[layout]]
        for identifier, condition in (("perimeter_closed", actual["perimeter_closed"]),
                ("crosstie_axes", set(actual["crosstie_axes"]) == set(AXES[layout])),
                ("every_layer", not required or actual["crossties_at_every_layer"]),
                ("end_engagement", not required or actual["ends_engage_bars"])):
            basis_note = ("not applicable: empty crosstie set" if not required and identifier in ("every_layer", "end_engagement")
                else "plugin declared restraint topology; no fabrication approval")
            check(identifier, D(int(condition)), ">=", D(1), basis_note)
        ties = parameters["model"]["ties"]
        check("hook_angle_min", D(str(ties["hook_angle_deg"])), ">=", D(135), "plugin conservative hook policy")
        check("hook_angle_max", D(str(ties["hook_angle_deg"])), "<=", D(135), "plugin supported hook geometry only")
        check("hook_extension", D(str(ties["hook_extension_mm"])), ">=", max(10 * dt, D(75)), "plugin conservative hook policy")
        intermediate_keys = SINGLE_SCHEMA["properties"]["intermediates"]["properties"]
        intermediates = {key: deepcopy(base["intermediates"][key]) for key in intermediate_keys if key in base["intermediates"]}
        intermediates.update(total_area_mm2=float(steel), rho_total=float(steel / area), Nu_kN=float(capacity),
            utilization=float(force / capacity), minimum_pair_clear_mm=float(minimum_clear))
        basis = deepcopy(base["basis"])
        basis.update(scope_version="ideal-static-axial-column-layouts-v1",
            area_policy="gross concrete area; Appendix A direct unique 4/6/8 total and 2/3 face columns, independent table rounding; no confinement gain")
        report = {"status": "PASS" if all(row["passed"] for row in checks) else "FAIL", "actual": deepcopy(actual),
            "materials": deepcopy(base["materials"]), "basis": basis, "intermediates": intermediates,
            "bars": [{"id": key, "x_mm": float(point[0]), "y_mm": float(point[1])} for key, point in points.items()],
            "faces": faces, "required_crossties": required, "checks": checks}
        ensure_json(report)
        return report


def check_column_layouts(parameters, actual):
    validate_parameters(parameters)
    validate_actual(actual)
    rows = [{"combination_id": group["combination_id"], "source": deepcopy(group["source"]),
        "report": _check_single(parameters, group, actual)} for group in parameters["combinations"]]
    maximum = max(D(str(group["actions"]["N_kN"])) for group in parameters["combinations"])
    controls = [index for index, group in enumerate(parameters["combinations"]) if D(str(group["actions"]["N_kN"])) == maximum]
    return {"status": "PASS" if all(row["report"]["status"] == "PASS" for row in rows) else "FAIL",
        "effective_input": deepcopy(parameters), "actual": deepcopy(actual), "combination_results": rows,
        "controlling_combination_ids": [rows[index]["combination_id"] for index in controls],
        "maximum_utilization": rows[controls[0]]["report"]["intermediates"]["utilization"],
        "capacity_control_policy": CONTROL_POLICY, "coverage": deepcopy(COVERAGE)}


def design_column_layouts(parameters):
    validate_parameters(parameters)
    attempts, selected = [], None
    for actual in candidate_sequence(parameters):
        report = check_column_layouts(parameters, actual)
        attempts.append(report)
        if report["status"] == "PASS":
            selected = deepcopy(report)
            break
    return {"status": "PASS" if selected else "FAIL", "effective_input": deepcopy(parameters),
        "selected": selected, "attempts": attempts, "selection_policy": SELECTION_POLICY}


def validate_check_semantics(report, parameters, actual):
    validate_json(report, make_validator(CHECK_SCHEMA))
    if report != check_column_layouts(deepcopy(parameters), deepcopy(actual)):
        raise ValueError("Layout check differs from original input and actual scheme")


def validate_design_semantics(report):
    validate_json(report, make_validator(DESIGN_SCHEMA))
    parameters = report["effective_input"]
    validate_parameters(parameters)
    candidates = candidate_sequence(parameters)
    selected = None
    if len(report["attempts"]) > len(candidates):
        raise ValueError("Unauthorized candidates")
    for index, attempt in enumerate(report["attempts"]):
        validate_check_semantics(attempt, parameters, candidates[index])
        if attempt["status"] == "PASS":
            if index != len(report["attempts"]) - 1:
                raise ValueError("Continued after PASS")
            selected = attempt
    if (report["selected"] != selected or report["status"] != ("PASS" if selected else "FAIL")
            or selected is None and len(report["attempts"]) != len(candidates)):
        raise ValueError("Layout candidate prefix or status mismatch")
