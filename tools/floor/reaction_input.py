"""Complete local reaction input; positions use calculation supports, not grid axes."""
from copy import deepcopy
from fractions import Fraction

from core.validation import make_validator, reject, validate_json
from .schemas import NONEMPTY, object_schema
from .design_store import REFERENCE
from .wall_schema import WALL_SCHEMA

ID={"type":"string","minLength":1,"maxLength":128,"pattern":r"^\S+$","not":{"pattern":r"\s"}}
BINDING=object_schema({"member_id":ID,"support_ids":{"type":"array","items":ID,"minItems":4,"maxItems":4,"uniqueItems":True},
    "coordinate_system":{"const":"legacy_main_beam_calculation_supports_mm"},"source":NONEMPTY})
SCOPE=object_schema({"purpose":{"const":"teaching"},"beam_model":{"const":"legacy_main_beam_constant_EI"},
    "baseline_wall_loads_excluded":{"type":"boolean","const":True},"baseline_exclusion_source":NONEMPTY,
    "global_frame_analysis":{"type":"boolean","const":False}})
EXTRACT_PARAMETERS=object_schema({"design_result_ref":REFERENCE,"beam_binding":BINDING,"scope":SCOPE})
WALL_PARAMETERS=object_schema({**EXTRACT_PARAMETERS["properties"],"walls":{"type":"array","minItems":1,"maxItems":8,"items":WALL_SCHEMA}})


def validate_parameters(parameters, *, walls=False):
    validate_json(parameters,make_validator(WALL_PARAMETERS if walls else EXTRACT_PARAMETERS),prefix=("parameters",))
    if not walls:
        return
    identifiers=set();records=set();intervals=[]
    for index, wall in enumerate(parameters["walls"]):
        prefix=("parameters","walls",index)
        def refuse(message,field,code="wall_scope_error"):
            reject(message,(*prefix,*field),code)
        if wall["wall_id"] in identifiers or wall["source"]["load_record_id"] in records:
            refuse("Each wall and source load record must be unique.",("wall_id",),"wall_duplicate")
        identifiers.add(wall["wall_id"]);records.add(wall["source"]["load_record_id"])
        if wall["member_id"]!=parameters["beam_binding"]["member_id"]:
            refuse("Wall must bind to the selected main beam model.",("member_id",))
        start,end=Fraction(str(wall["start_mm"])),Fraction(str(wall["end_mm"]))
        if start>=end:
            refuse("start_mm must be strictly before end_mm.",("end_mm",))
        if any(max(start,a)<min(end,b) for a,b in intervals):
            refuse("Overlapping wall intervals on the same beam are not supported.",("start_mm",),"wall_overlap")
        intervals.append((start,end))
        length,height=end-start,Fraction(str(wall["height_mm"]))
        rectangles=[];opening_ids=set()
        for j, opening in enumerate(wall["openings"]):
            if opening["opening_id"] in opening_ids:
                refuse("Opening IDs must be unique within a wall.",("openings",j,"opening_id"),"wall_duplicate")
            opening_ids.add(opening["opening_id"])
            x,y,w,h=(Fraction(str(opening[k])) for k in ("x_local_mm","bottom_mm","width_mm","height_mm"))
            if x+w>length or y+h>height:
                refuse("Opening rectangle must fit within the declared wall.",("openings",j))
            if any(max(x,a)<min(x+w,b) and max(y,c)<min(y+h,d) for a,b,c,d in rectangles):
                refuse("Opening rectangles may touch but must not overlap in area.",("openings",j),"wall_opening_overlap")
            rectangles.append((x,x+w,y,y+h))
        if sum((b-a)*(d-c) for a,b,c,d in rectangles)>=length*height:
            refuse("Net wall face area must remain positive.",("openings",))
        if len({f["side"] for f in wall["finishes"]})!=len(wall["finishes"]):
            refuse("Only one finish per declared side is supported.",("finishes",),"wall_duplicate")


def validate_positions(parameters, span_lengths_m):
    total_mm=sum(Fraction(str(x)) for x in span_lengths_m)*1000
    for index,wall in enumerate(parameters.get("walls",[])):
        if Fraction(str(wall["end_mm"]))>total_mm:
            reject("Wall lies beyond calculation-support coordinates; grid-axis positions cannot be inferred.",
                   ("parameters","walls",index,"end_mm"),"wall_coordinate_error")
