"""Frozen phase18 JSON contract, isolated from previous input versions."""
from copy import deepcopy

from .combination_input import COMBINATION_PARAMETERS_SCHEMA
from .materials import CANDIDATE_DIAMETERS_MM
from .schemas import POSITIVE, object_schema

LAYOUTS = ("four_corner_bars", "six_b", "six_h", "eight_perimeter")
COUNTS = dict(zip(LAYOUTS, (4, 6, 6, 8)))
AXES = dict(zip(LAYOUTS, ((), ("h",), ("b",), ("b", "h"))))

PARAMETERS_SCHEMA = deepcopy(COMBINATION_PARAMETERS_SCHEMA)
ties = PARAMETERS_SCHEMA["properties"]["model"]["properties"]["ties"]
ties["properties"].pop("configuration")
ties["required"].remove("configuration")
for key in ("hook_angle_deg", "hook_extension_mm"):
    ties["properties"][key] = deepcopy(POSITIVE)
    ties["required"].append(key)
PARAMETERS_SCHEMA["properties"]["layout_candidates"] = {
    "type": "array", "items": {"enum": list(LAYOUTS)}, "minItems": 1, "maxItems": 4, "uniqueItems": True}
PARAMETERS_SCHEMA["required"].append("layout_candidates")

ACTUAL_SCHEMA = object_schema({
    "layout": {"enum": list(LAYOUTS)}, "bar_count": {"type": "integer", "enum": [4, 6, 8]},
    "bar_diameter_mm": {"type": "number", "enum": list(CANDIDATE_DIAMETERS_MM)},
    "perimeter_closed": {"type": "boolean"}, "crosstie_axes": {"type": "array",
        "items": {"enum": ["b", "h"]}, "uniqueItems": True, "maxItems": 2},
    "crossties_at_every_layer": {"type": "boolean"}, "ends_engage_bars": {"type": "boolean"},
})
