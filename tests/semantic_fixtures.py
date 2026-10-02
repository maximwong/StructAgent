"""Explicit recorded proposals; these are not produced by the production parser."""

from copy import deepcopy


PARAMETERS = {"span_x": 6000, "span_y": 6000, "concrete": "C30", "steel": "HRB400", "live_load": 2.0}


def floor_proposal(parameters=None, *, pair="6m×6m", load="2.0kN/m²", concrete="C30", steel="HRB400",
                   clarifications=(), evidence=None):
    parameters = deepcopy(PARAMETERS if parameters is None else parameters)
    sources = {"span_x": {"quote": pair, "index": 0}, "span_y": {"quote": pair, "index": 1},
               "concrete": {"quote": concrete, "index": 0}, "steel": {"quote": steel, "index": 0},
               "live_load": {"quote": load, "index": 0}}
    if evidence:
        sources.update(deepcopy(evidence))
    for field in sources:
        if parameters[field] is None:
            sources[field] = None
    return {"tool": "design_floor_system", "parameters": parameters, "evidence": sources,
            "clarifications": deepcopy(list(clarifications))}


def clarification(quote, code="outside_template_scope", field=None):
    return {"code": code, "quote": quote, "field": field, "message": "请明确此项要求；当前办公楼模板不能直接满足。"}
