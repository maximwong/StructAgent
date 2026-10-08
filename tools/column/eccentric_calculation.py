"""Section-only uniaxial eccentric checks; exact rational equilibrium intervals.

No axial phi, frame solver, CAD, store, or design call in the actual check.
"""
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction

from core.validation import ensure_json, make_validator, validate_json
from .eccentric_input import PARAMETERS_SCHEMA, ACTUAL_SCHEMA, validate_parameters, validate_actual
from .materials import CONCRETE_FC_MPA, FOUR_BAR_AREA_MM2, CANDIDATE_DIAMETERS_MM
from .schemas import object_schema, NONEMPTY

F = lambda value: Fraction(str(value))
STATUSES = ["PASS", "FAIL", "OUTSIDE_SCOPE", "INDETERMINATE"]
REFERENCE_SCHEMA = {"type": "string", "pattern": r"^column-eccentric-[0-9a-f]{32}$"}
COVERAGE = {
    "checked": ["GB6.2.17 rectangular section N/M equilibrium with GB6.2.8-1 steel strain",
                "additional eccentricity once", "four-bar ratios, spacing, cover and tie declarations"],
    "not_checked": ["external force analysis and combinations completeness", "frame P-Delta and member P-delta analysis",
                    "whole-member equilibrium", "biaxial, shear, seismic and fatigue", "x<2a special branch and whole-depth compression",
                    "durability/fire, laps, anchorage, joints and member ends"],
    "pass_meaning": "PASS covers only declared section and detailing checks; external second-order declarations are not certified.",
}
BASIS = {"version": "rectangular-uniaxial-four-corner-v1", "clauses": "GB/T50010-2010(2024) 6.2.5/6/7/8-1/17; GB55008 4.4.6",
         "area_policy": "Appendix A four-bar total, divided equally between two layers",
         "numerical_policy": "exact rational equilibrium/bisection; conservative capacity interval; no PASS tolerance",
         "second_order_policy": "external final section moments include frame and member second order, exclude ea; add N*max(20,H/30) once"}

# Detailed numeric/check payloads are recursively JSON checked and semantically
# recomputed below; envelope identity and report topology remain schema constrained.
GROUP_SCHEMA = object_schema({"combination_id": NONEMPTY, "status": {"enum": STATUSES},
    "actions": {"type": "object"}, "source": {"type": "object"}, "second_order": {"type": "object"},
    "intermediates": {"type": "object"}, "checks": {"type": "array", "minItems": 1, "items": {"type": "object"}}})
CHECK_OUTPUT = object_schema({"status": {"enum": STATUSES}, "effective_input": PARAMETERS_SCHEMA,
    "actual": ACTUAL_SCHEMA, "combination_results": {"type": "array", "minItems": 1, "maxItems": 32, "items": GROUP_SCHEMA},
    "controlling_combinations": {"type": "array", "items": NONEMPTY}, "basis": {"type": "object"}, "coverage": {"type": "object"}})
CHECK_OUTPUT["properties"]["design_result_ref"] = REFERENCE_SCHEMA
DESIGN_OUTPUT = object_schema({"status": {"enum": ["PASS", "FAIL"]}, "effective_input": PARAMETERS_SCHEMA,
    "selected": {"anyOf": [CHECK_OUTPUT, {"type": "null"}]},
    "attempts": {"type": "array", "minItems": 1, "maxItems": 8, "items": CHECK_OUTPUT}, "selection_policy": NONEMPTY})
DESIGN_OUTPUT["properties"]["design_result_ref"] = REFERENCE_SCHEMA


def number(value):
    result = float(value)
    ensure_json(result)
    return result


def bound_string(value, upper=False):
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_CEILING if upper else ROUND_FLOOR
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def _construction(model, actual):
    b, h, c = (F(model["section"][key]) for key in ("b_mm", "h_mm", "cover_to_outer_tie_mm"))
    ties = model["ties"]
    dt, s = F(ties["diameter_mm"]), F(ties["spacing_mm"])
    d = F(actual["bar_diameter_mm"])
    area = F(FOUR_BAR_AREA_MM2[int(d)])
    checks = []

    def add(key, value, relation, limit, basis):
        checks.append({"id": key, "value": number(value), "relation": relation, "limit": number(limit),
                       "passed": value <= limit if relation == "<=" else value >= limit, "basis": basis})

    add("total_ratio_min", area/(b*h), ">=", F(".0055"), "GB55008 4.4.6")
    add("side_ratio_min", area/(2*b*h), ">=", F(".002"), "GB55008 4.4.6")
    add("total_ratio_max", area/(b*h), "<=", F(".03"), "plugin scope, not an automatic capacity increase")
    for axis, length in (("b", b), ("h", h)):
        center = length-2*(c+dt+d/2)
        add("clear_spacing_"+axis, center-d, ">=", F(50), "GB50010 9.3.1")
        add("center_spacing_"+axis, center, "<=", F(300), "GB50010 9.3.1")
    add("tie_diameter", dt, ">=", max(F(6), d/4), "GB50010 9.3.2")
    add("tie_spacing", s, "<=", min(F(400), b, h, 15*d), "GB50010 9.3.2")
    add("longitudinal_cover", c+dt, ">=", d, "GB50010 8.2.1")
    add("hook_angle", F(ties["hook_angle_deg"]), ">=", F(135), "conservative plugin hook declaration")
    add("hook_angle_max", F(ties["hook_angle_deg"]), "<=", F(135), "plugin supported hook geometry only")
    add("hook_extension", F(ties["hook_extension_mm"]), ">=", max(10*dt,F(75)), "conservative plugin hook declaration")
    add("perimeter_closed", F(int(actual["perimeter_closed"])), ">=", F(1), "GB50010 9.3.2; declared, not inspected")
    return checks


def _section(model, combination, actual):
    """Find the unique N-equilibrium root in the declared section domain."""
    sec = model["section"]
    H, B = (F(sec["h_mm"]), F(sec["b_mm"])) if model["bending_axis"] == "x" else (F(sec["b_mm"]), F(sec["h_mm"]))
    d, dt, c = F(actual["bar_diameter_mm"]), F(model["ties"]["diameter_mm"]), F(sec["cover_to_outer_tie_mm"])
    a = c+dt+d/2
    h0, beta, Es_eps, fy = H-a, F(".8"), F(660), F(360)
    fc = F(CONCRETE_FC_MPA[model["materials"]["concrete"]])
    As = F(FOUR_BAR_AREA_MM2[int(d)])/2
    N = F(combination["actions"]["N_kN"])*1000
    M = F(combination["actions"]["M"+model["bending_axis"]+"_kN_m"])
    ea = max(F(20), H/30)
    demand = abs(M)*1000000+N*ea
    lo, hi = 2*a, beta*H
    checks = _construction(model, actual)
    info = {"B_mm": number(B), "H_mm": number(H), "a_mm": number(a), "h0_mm": number(h0),
            "total_area_mm2": number(2*As), "side_area_mm2": number(As), "fc_MPa": number(fc),
            "fy_MPa": 360, "Es_MPa": 200000, "beta1": .8, "epsilon_cu": .0033,
            "ea_mm": number(ea), "demand_kN_m": number(demand/1000000),
            "compression_face": "positive_depth" if M>0 else "negative_depth"}

    def stress(x):
        return min(fy,max(-fy,Es_eps*(beta*h0/x-1)))

    def equilibrium(x):
        return fc*B*x+fy*As-stress(x)*As-N

    if lo>hi or N>fc*B*H or equilibrium(lo)>0 or equilibrium(hi)<0:
        info["scope_reason"] = "N equilibrium outside 2a<=x<=beta1*H or N>fc*B*H"
        checks.append({"id":"section_scope", "passed":False,"basis":"GB6.2.17 scope; deferred GB6.2.14/full compression"})
        return "OUTSIDE_SCOPE", info, checks, None

    trial = N/(fc*B)
    if lo<=trial<=hi and trial*(Es_eps+fy)<=beta*Es_eps*h0:
        lo=hi=trial
    elif equilibrium(lo)==0:
        hi=lo
    elif equilibrium(hi)==0:
        lo=hi
    else:
        for _ in range(256):
            middle=(lo+hi)/2
            residual=equilibrium(middle)
            if residual==0:
                lo=hi=middle
                break
            if residual<0:
                lo=middle
            else:
                hi=middle

    # Exact rational intervals make every bound independently reproducible.
    concrete=lambda x: fc*B*x*(H/2-x/2)
    steel=lambda x: (fy+stress(x))*As*(H/2-a)
    conc_upper=max(concrete(lo),concrete(hi))
    if lo<=H/2<=hi:
        conc_upper=max(conc_upper,concrete(H/2))
    lower=min(concrete(lo),concrete(hi))+steel(hi)
    upper=conc_upper+steel(lo)
    strain_lo=(beta*h0/hi-1)*F(".0033")
    strain_hi=(beta*h0/lo-1)*F(".0033")
    yield_bound=beta*Es_eps*h0/(Es_eps+fy)
    branch="large" if hi<=yield_bound else "small" if lo>yield_bound else "indeterminate"
    info.update(x_mm=number((lo+hi)/2), sigma_s_MPa=number(stress((lo+hi)/2)),
                capacity_kN_m=number(lower/1000000), input_moment_limit_kN_m=number((lower-N*ea)/1000000),
                utilization=number(demand/lower) if lower>0 else None, eccentricity_class=branch,
                x_interval_mm=[bound_string(lo),bound_string(hi,True)],
                capacity_interval_N_mm=[bound_string(lower),bound_string(upper,True)],
                demand_N_mm_exact=str(demand), x_interval_exact=[str(lo),str(hi)],
                capacity_interval_exact=[str(lower),str(upper)])
    if strain_lo>F(".01"):
        checks.append({"id":"tensile_strain_scope","passed":False,"basis":"GB6.2.1 epsilon_s<=0.01"})
        return "OUTSIDE_SCOPE",info,checks,None
    scope_confirmed = strain_hi<=F(".01") and branch!="indeterminate"
    capacity_pass = demand<=lower
    capacity_fail = demand>upper
    checks.append({"id":"eccentric_capacity","passed":capacity_pass,"basis":"GB6.2.17,6.2.8-1; conservative interval, no tolerance",
                   "value":number(demand/1000000),"relation":"<=","limit":number(lower/1000000)})
    if not scope_confirmed or not(capacity_pass or capacity_fail):
        checks.append({"id":"numerical_confirmation","passed":False,
                       "basis":"unresolved exact interval; no tolerance may authorize PASS"})
        return "INDETERMINATE",info,checks,None
    status="PASS" if all(row["passed"] for row in checks) else "FAIL"
    return status,info,checks,demand/lower if lower>0 else None


def check_column_eccentric(parameters, actual):
    validate_parameters(parameters)
    validate_actual(actual)
    groups, ratios = [], []
    for group in parameters["combinations"]:
        status, info, checks, ratio = _section(parameters["model"], group, actual)
        groups.append({"combination_id":group["combination_id"], "status":status,
                       **{k:deepcopy(group[k]) for k in ("actions","source","second_order")},
                       "intermediates":info,"checks":checks})
        ratios.append(ratio)
    status=next((s for s in ("OUTSIDE_SCOPE","INDETERMINATE","FAIL") if any(g["status"]==s for g in groups)),"PASS")
    valid=[r for r in ratios if r is not None]
    controls=[g["combination_id"] for g,r in zip(groups,ratios) if r==max(valid)] if valid else []
    report={"status":status,"effective_input":deepcopy(parameters),"actual":deepcopy(actual),
            "combination_results":groups,"controlling_combinations":controls,"basis":deepcopy(BASIS),"coverage":deepcopy(COVERAGE)}
    ensure_json(report)
    return report


def design_column_eccentric(parameters):
    validate_parameters(parameters)
    attempts=[]
    for diameter in CANDIDATE_DIAMETERS_MM:
        actual=candidate_actual(diameter)
        report=check_column_eccentric(parameters,actual)
        attempts.append(report)
        if report["status"]=="PASS":
            return {"status":"PASS","effective_input":deepcopy(parameters),"selected":deepcopy(report),"attempts":attempts,
                    "selection_policy":"first four-bar area candidate passing all sourced combinations, no changes to supplied model"}
    return {"status":"FAIL","effective_input":deepcopy(parameters),"selected":None,"attempts":attempts,
            "selection_policy":"no verified candidate within plugin scope; not proof of general structural infeasibility"}


def validate_check_semantics(report, parameters, actual):
    validate_json(report,make_validator(CHECK_OUTPUT))
    if report!=check_column_eccentric(parameters,actual):
        raise ValueError("Eccentric actual check differs from deterministic recomputation")


def validate_design_semantics(report):
    validate_json(report,make_validator(DESIGN_OUTPUT))
    parameters=report["effective_input"]
    validate_parameters(parameters)
    attempts=report["attempts"]
    for index, attempt in enumerate(attempts):
        # Verify the published prefix only; reference checks never enter design
        # or search for/reselect an alternative to the saved actual bars.
        validate_check_semantics(attempt, parameters, candidate_actual(CANDIDATE_DIAMETERS_MM[index]))
        if index<len(attempts)-1 and attempt["status"]=="PASS":
            raise ValueError("Candidate prefix continued past its first PASS")
    if report["status"]=="PASS":
        if attempts[-1]["status"]!="PASS" or report["selected"]!=attempts[-1]:
            raise ValueError("Published selected actual does not match first PASS")
        policy="first four-bar area candidate passing all sourced combinations, no changes to supplied model"
    else:
        if len(attempts)!=8 or any(a["status"]=="PASS" for a in attempts) or report["selected"] is not None:
            raise ValueError("Failed candidate history incomplete")
        policy="no verified candidate within plugin scope; not proof of general structural infeasibility"
    if report["selection_policy"]!=policy:
        raise ValueError("Unexpected selection policy")


def candidate_actual(diameter):
    return {"bar_count":4,"bar_diameter_mm":diameter,"layout":"four_corner_bars","perimeter_closed":True,
            "crosstie_axes":[],"crossties_at_every_layer":False,"ends_engage_bars":False}
