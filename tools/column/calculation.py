"""Pure column design and actual-scheme checks; no store/CAD/floor dependency."""

from copy import deepcopy
from decimal import Decimal, localcontext

from core.validation import ensure_json, make_validator, reject, validate_json
from .materials import (CANDIDATE_DIAMETERS_MM, CONCRETE_FC_MPA, FOUR_BAR_AREA_MM2,
                        LONGITUDINAL_FY_COMPRESSION_MPA, MATERIAL_TABLE_VERSION, PHI_TABLE, TIE_FY_MPA)
from .schemas import ACTUAL_SCHEMA, DESIGN_CODE, MODEL_SCHEMA, UNITS

_MODEL_VALIDATOR = make_validator(MODEL_SCHEMA)
_ACTUAL_VALIDATOR = make_validator(ACTUAL_SCHEMA)
D = Decimal
COVERAGE = {
    "checked": ["ideal axial capacity including phi stability coefficient", "total and single-side reinforcement ratios",
                "two-axis corner-bar clear and center spacing", "tie diameter and spacing", "longitudinal cover versus bar diameter"],
    "not_checked": ["environment, durability and fire cover", "anchorage and laps", "joints and member ends",
                    "tie hooks and full detailing", "eccentric compression and additional eccentricity",
                    "eccentric second-order effects and frame second-order analysis", "seismic design", "fatigue",
                    "source force and effective-length analysis"],
    "pass_meaning": "PASS means only every declared v1 check passes; it is not complete engineering approval.",
}
BASIS = {
    "scope_version": "ideal-static-axial-column-v1", "design_code": DESIGN_CODE, "units": UNITS,
    "capacity_formula": "Nu=0.9*phi*(fc*b*h+fy_compression*As)/1000; N already includes gamma0; gamma_Rd=1",
    "area_policy": "gross concrete area; Appendix A FOUR-BAR column directly; no tie confinement gain",
    "phi_policy": "next-higher l0/min(b,h) table node, conservative plugin policy, not normative interpolation",
    "gamma_Rd": 1,
}


def validate_model(model):
    """Structured ValueError-compatible validation, used by pure and Tool APIs."""
    validate_json(model, _MODEL_VALIDATOR, prefix=("model",))
    with localcontext() as ctx:
        ctx.prec = 60
        section, ties = model["section"], model["ties"]
        ratio = D(str(model["effective_length"]["l0_mm"])) / min(D(str(section["b_mm"])), D(str(section["h_mm"])))
        if ratio > 50:
            reject("l0/min(b,h) must be <=50 in column v1.", ("model", "effective_length", "l0_mm"), "column_scope_error")
        if D(str(section["cover_to_outer_tie_mm"])) + D(str(ties["diameter_mm"])) > 50:
            reject("Longitudinal outer cover c+dt >50mm requires measures outside column v1.",
                   ("model", "section", "cover_to_outer_tie_mm"), "column_scope_error")
        material = model["materials"]
        expected = {"fc_MPa": CONCRETE_FC_MPA[material["concrete"]],
                    "fy_compression_MPa": LONGITUDINAL_FY_COMPRESSION_MPA[material["longitudinal_steel"]],
                    "tie_fy_MPa": TIE_FY_MPA[material["tie_steel"]]}
        for key, value in expected.items():
            if key in material and D(str(material[key])) != D(value):
                reject(f"Explicit {key}={material[key]} conflicts with grade table value {value}MPa.",
                       ("model", "materials", key), "column_material_conflict")


def validate_actual(actual):
    validate_json(actual, _ACTUAL_VALIDATOR, prefix=("actual",))


def _number(value):
    result = float(value)
    ensure_json(result)
    return result


def check_column(model, actual):
    """Check the supplied actual bars directly; never invoke design or replace bars."""
    validate_model(model)
    validate_actual(actual)
    with localcontext() as ctx:
        ctx.prec = 60
        b, h, c = (D(str(model["section"][key])) for key in ("b_mm", "h_mm", "cover_to_outer_tie_mm"))
        dt, spacing = (D(str(model["ties"][key])) for key in ("diameter_mm", "spacing_mm"))
        dia = D(str(actual["bar_diameter_mm"]))
        area = b * h
        ratio = D(str(model["effective_length"]["l0_mm"])) / min(b, h)
        node, phi_string = next((node, phi) for node, phi in PHI_TABLE if ratio <= node)
        phi = D(phi_string)
        material = model["materials"]
        fc = D(CONCRETE_FC_MPA[material["concrete"]])
        fy = D(LONGITUDINAL_FY_COMPRESSION_MPA[material["longitudinal_steel"]])
        tie_fy = D(TIE_FY_MPA[material["tie_steel"]])
        steel = D(FOUR_BAR_AREA_MM2[int(dia)])
        side_steel, rho, side_rho = steel / 2, steel / area, steel / (2 * area)
        force = D(str(model["actions"]["N_kN"]))
        capacity = D("0.9") * phi * (fc * area + fy * steel) / 1000
        required = max(D(0), (force * 1000 / (D("0.9") * phi) - fc * area) / fy)
        centers = {"b": b - 2 * (c + dt + dia / 2), "h": h - 2 * (c + dt + dia / 2)}
        tie_min = max(D(6), dia / 4)
        spacing_max = min(D(400), b, h, 15 * dia)
        intermediates = {
            "gross_area_mm2": area, "slenderness_ratio": ratio, "phi_node_ratio": D(node), "phi": phi,
            "capacity_required_area_mm2": required, "minimum_total_area_mm2": D(".0055") * area,
            "minimum_side_area_mm2": D(".002") * area, "total_area_mm2": steel, "side_area_mm2": side_steel,
            "rho_total": rho, "rho_side": side_rho, "Nu_kN": capacity, "utilization": force / capacity,
            "longitudinal_outer_cover_mm": c + dt,
            **{f"center_spacing_{axis}_mm": val for axis, val in centers.items()},
            **{f"clear_spacing_{axis}_mm": val - dia for axis, val in centers.items()},
            "minimum_tie_diameter_mm": tie_min, "maximum_tie_spacing_mm": spacing_max,
        }
        checks = []

        def check(identifier, label, value, relation, limit, basis):
            passed = value <= limit if relation == "<=" else value >= limit
            checks.append({"id": identifier, "label": label, "value": _number(value),
                           "relation": relation, "limit": _number(limit), "passed": passed, "basis": basis})

        check("axial_capacity", "ideal axial compression capacity", force, "<=", capacity, "GB/T50010 6.2.15")
        check("total_ratio_min", "minimum total reinforcement ratio", rho, ">=", D(".0055"), "GB55008 4.4.6")
        check("side_ratio_min", "minimum reinforcement ratio on each symmetric side", side_rho, ">=", D(".002"), "GB55008 4.4.6")
        check("total_ratio_max", "plugin maximum reinforcement ratio", rho, "<=", D(".03"), "plugin scope; GB/T50010 6.2.15,9.3.1")
        for axis, center in centers.items():
            check(f"clear_spacing_{axis}", f"{axis}-direction clear spacing", center - dia, ">=", D(50), "GB/T50010 9.3.1")
            check(f"center_spacing_{axis}", f"{axis}-direction center spacing", center, "<=", D(300), "GB/T50010 9.3.1")
        check("tie_diameter", "minimum tie diameter", dt, ">=", tie_min, "GB/T50010 9.3.2")
        check("tie_spacing", "maximum tie spacing", spacing, "<=", spacing_max, "GB/T50010 9.3.2")
        check("longitudinal_cover", "longitudinal outer cover versus diameter", c + dt, ">=", dia, "GB/T50010 8.2.1")
        report = {
            "status": "PASS" if all(row["passed"] for row in checks) else "FAIL",
            "effective_input": deepcopy(model), "actual": deepcopy(actual), "basis": deepcopy(BASIS),
            "materials": {"table_version": MATERIAL_TABLE_VERSION,
                          **{key: material[key] for key in ("concrete", "longitudinal_steel", "tie_steel")},
                          "fc_MPa": _number(fc), "fy_compression_MPa": _number(fy), "tie_fy_MPa": _number(tie_fy)},
            "intermediates": {key: _number(value) for key, value in intermediates.items()},
            "checks": checks, "coverage": deepcopy(COVERAGE),
        }
        ensure_json(report)
        return report


def design_column(model):
    """Select the first all-PASS fixed four-corner candidate and retain attempts."""
    validate_model(model)
    attempts = []
    selected = None
    for diameter in CANDIDATE_DIAMETERS_MM:
        actual = {"bar_count": 4, "bar_diameter_mm": diameter, "layout": "four_corner_bars"}
        report = check_column(model, actual)
        attempts.append(report)
        if report["status"] == "PASS":
            selected = deepcopy(report)
            break
    return {"status": "PASS" if selected is not None else "FAIL", "effective_input": deepcopy(model),
            "selected": selected, "attempts": attempts,
            "selection_policy": "first all-PASS diameter in [12,14,16,18,20,22,25,28]; all other user inputs fixed"}
