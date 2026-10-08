"""Wall load input contracts for wall_schema. Declarations only."""

from tools.floor.schemas import NUMBER, NONEMPTY, POSITIVE, object_schema

WALL_ID = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"^\S+$", "not": {"pattern": r"\s"}}
START = {**NUMBER}
BOTTOM = {**NUMBER}
X_LOCAL = {**NUMBER}
ADDITIONAL_WEIGHT = {**NUMBER}
WIDTH = {**POSITIVE}
HEIGHT = {**POSITIVE}
THICKNESS = {**POSITIVE}
DENSITY = {**POSITIVE}
END = {**POSITIVE}

OPENING = object_schema({
    "opening_id": WALL_ID,
    "x_local_mm": X_LOCAL,
    "bottom_mm": BOTTOM,
    "width_mm": WIDTH,
    "height_mm": HEIGHT,
})

FINISH = object_schema({
    "side": {"enum": ["left", "right"]},
    "thickness_mm": THICKNESS,
    "density_kN_m3": DENSITY,
})

SOURCE = object_schema({
    "load_record_id": WALL_ID,
    "description": NONEMPTY,
    "geometry_source": NONEMPTY,
    "density_source": NONEMPTY,
    "finish_source": NONEMPTY,
    "additional_weight_source": NONEMPTY,
})

WALL = object_schema({
    "wall_id": WALL_ID,
    "member_id": WALL_ID,
    "start_mm": START,
    "end_mm": END,
    "height_mm": HEIGHT,
    "thickness_mm": THICKNESS,
    "density_kN_m3": DENSITY,
    "fixed": {"type": "boolean", "const": True},
    "non_load_bearing": {"type": "boolean", "const": True},
    "direct_on_beam": {"type": "boolean", "const": True},
    "centred_on_beam": {"type": "boolean", "const": True},
    "weight_basis": {"const": "characteristic"},
    "load_model": {"const": "uniform_equivalent_over_wall_length"},
    "openings": {"type": "array", "items": OPENING, "minItems": 0, "maxItems": 16},
    "finishes": {"type": "array", "items": FINISH, "minItems": 0, "maxItems": 2},
    "additional_weight_kN": ADDITIONAL_WEIGHT,
    "source": SOURCE,
})

WALL_SCHEMA = WALL
