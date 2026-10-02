"""Complete user-supplied models plus locally verified natural-language edits."""

from copy import deepcopy
import math
import re

from agent.parameter_parser import LanguageProfile, ProfileInputError
from core.exceptions import ToolValidationError
from core.validation import make_validator, validate_json
from .design_adapter import CONCRETE_MATERIALS, FloorDesignAdapter, FloorAdapterError
from .language_profile import FloorDemoProfile
from .schemas import EXPLICIT_MODEL, object_schema
from .source_evidence import quoted_value, PAIR, length_value


# Field names describe the public language contract; paths belong to this plugin only.
EDITS = {
    "span_x": ("主梁各轴跨", "geometry.main_axis_spans_mm", "length"),
    "span_y": ("次梁各轴跨", "geometry.secondary_axis_spans_mm", "length"),
    "concrete": ("混凝土等级", "materials.concrete", "material"),
    "steel": ("梁纵筋等级", "materials.beam_steel", "material"),
    "live_load": ("活荷载", "loads.live_kN_m2", "load"),
    "slab_thickness": ("板厚", "slab.h_mm", "length"),
    "secondary_width": ("次梁宽度", "secondary.b_mm", "width"),
    "secondary_height": ("次梁高度", "secondary.h_mm", "height"),
    "main_width": ("主梁宽度", "main.b_mm", "width"),
    "main_height": ("主梁高度", "main.h_mm", "height"),
    "secondary_spacing": ("次梁间距", "geometry.secondary_spacing_mm", "length"),
    "finish_thickness": ("面层厚度", "loads.finish_mm", "length"),
    "plaster_thickness": ("抹灰厚度", "loads.plaster_mm", "length"),
}


def leaves(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, prefix + ("." if prefix else "") + key)
    else:
        yield prefix, deepcopy(value)


def edit_value(field, source):
    quote, index = source["quote"], source["index"]
    if field in ("span_x", "span_y", "concrete", "steel", "live_load"):
        return quoted_value(field, quote, index)
    kind = EDITS[field][2]
    if kind in ("width", "height"):
        pairs = list(PAIR.finditer(quote))
        if pairs:
            if len(pairs) != 1 or index != (0 if kind == "width" else 1):
                raise ValueError("Section must be width by height with explicit units.")
            pair = pairs[0]
            return length_value(pair[1], pair[2] or pair[4]) if index == 0 else length_value(pair[3], pair[4])
    return quoted_value("span_x", quote, index)


def validate_model(model):
    """Reuse the existing schema/material rules before any cloud or engineering call."""
    validator = make_validator(EXPLICIT_MODEL)
    try:
        validate_json(model, validator, prefix=("parameters", "model"))
        FloorDesignAdapter().prepare({"input_mode": "explicit", "model": model}, project_id="input-validation")
    except ToolValidationError as exc:
        missing = []
        issues = []
        for error in validator.iter_errors(model):
            if error.validator == "required":
                for key in error.validator_value:
                    if key not in error.instance:
                        path = [*error.absolute_path, key]
                        joined = ".".join(map(str, path))
                        if joined not in missing:
                            missing.append(joined)
                            issues.append({"code": "missing_parameter", "path": ["parameters", "model", *path],
                                           "message": "请在完整参数表补充：" + joined})
        if missing:
            raise ProfileInputError(issues, missing_fields=missing) from None
        raise ProfileInputError(exc.errors, status="invalid_input") from None
    except FloorAdapterError as exc:
        raise ProfileInputError([{"code": exc.code, "path": exc.path, "message": str(exc)}], status="invalid_input") from None


class FloorExplicitProfile(LanguageProfile):
    def __init__(self, model):
        self.model = deepcopy(model)
        super().__init__(name="floor_explicit_v1", tool="design_floor_system",
            description=(
                "用户已经提交完整工程参数表；原表是本地输入，不是固定模板。只提取本次文字明确要求修改的字段，"
                "未提及的参数和evidence均为null，按已填参数设计也全部null。不能猜值或忽略额外工程要求。"
                "只支持EDITS定义的13项编辑：主梁各轴跨span_x、次梁各轴跨span_y、混凝土concrete、梁纵筋steel、"
                "活载live_load、板厚slab_thickness、次梁宽高secondary_width/secondary_height、"
                "主梁宽高main_width/main_height、次梁间距secondary_spacing、面层厚finish_thickness、抹灰厚plaster_thickness。"
                "长度用mm，活荷载kN/m²。截面一组值按宽×高，例如200×450mm，宽index=0、高index=1；"
                "单独宽或高引用单个长度，index=0。主梁/次梁跨度组合按主梁轴跨×次梁轴跨取index=0/1。"
                "每个修改值必须有原文连续逐字quote和index。支持中文数、不同表达及共享单位，不能猜无单位数字。"
                "主梁3跨、次梁5跨，板筋/箍筋HPB300与梁纵筋HRB400是引擎范围。改变跨数、非三分点布置、"
                "墙柱基础或其他结构能力、预应力为outside_template_scope。其余不在13项内的参数请在表单编辑，"
                "本次文字要求放入clarifications，不能静默忽略；比如容重、支承、保护层、恒载总值、配筋或构造变化。"
                "多组值、否定、矛盾、未明确是宽还是高等为ambiguous_parameter，材料角色冲突为material_assignment_conflict，"
                "无单位为unclear_unit，板筋或箍筋HRB400为unsupported_reinforcement。不要把礼貌用语当工程约束。"
                "原文没要求修改就不输出修改，表单数值不会提供给模型，也不必再次要求用户在文字里重述。"
            ), field_schema=object_schema({"model": deepcopy(EXPLICIT_MODEL)}),
            fixed_parameters={"input_mode": "explicit"}, context={"unit_system": "SI", "design_code": "GB"})

    def inspect(self, text):
        validate_model(self.model)
        return None

    def response_schema(self):
        schema = FloorDemoProfile().response_schema()
        for name in ("parameters", "evidence"):
            section = schema["properties"][name]
            section["required"] = list(EDITS)
            sample = deepcopy(section["properties"]["span_x"])
            for field in EDITS:
                if field not in section["properties"]:
                    section["properties"][field] = deepcopy(sample)
        schema["properties"]["clarifications"]["items"]["properties"]["field"]["enum"] = [*EDITS, None]
        return schema

    def _apply(self, proposal):
        model = deepcopy(self.model)
        for field, value in proposal["parameters"].items():
            if value is None:
                continue
            path = EDITS[field][1].split(".")
            group, key = path
            if field in ("span_x", "span_y"):
                model[group][key] = [int(value) if value == int(value) else value] * len(model[group][key])
            else:
                model[group][key] = float(value) if field == "live_load" else value
            if field == "concrete":
                model["materials"]["fc_MPa"], model["materials"]["ft_MPa"] = CONCRETE_MATERIALS[value]
        return model

    def resolve(self, text, proposal, observed):
        issues = []
        for field, (label, _, _) in EDITS.items():
            value, source = proposal["parameters"][field], proposal["evidence"][field]
            if value is None and source is None:
                continue
            try:
                if value is None or source is None or source["quote"] not in text:
                    raise ValueError("Missing verbatim source.")
                if EDITS[field][2] in ("length", "width", "height") and not re.search(r"(?:mm|cm|m|毫米|厘米|米)(?![A-Za-z])", source["quote"], re.I):
                    raise ProfileInputError([{"code": "unclear_unit", "path": ["parameters", field],
                                              "message": label + "缺少明确长度单位，请补充mm、cm或m。",
                                              "quote": source["quote"]}])
                expected = edit_value(field, source)
                if isinstance(expected, str):
                    matches = value == expected
                else:
                    matches = type(value) in (int, float) and math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9)
                if not matches:
                    raise ValueError("Value differs from source.")
            except ProfileInputError:
                raise
            except (TypeError, ValueError):
                raise ProfileInputError([{"code": "source_mismatch", "path": ["parameters", field],
                                          "message": label + "与原文依据不一致，请重新解析。"}], status="invalid_output") from None
            if (field == "concrete" and value not in CONCRETE_MATERIALS) or (field == "steel" and value != "HRB400"):
                issues.append({"code": "unsupported_material", "path": ["parameters", field], "message": label + "超出当前支持范围。"})
        for item in proposal["clarifications"]:
            if item["quote"] not in text:
                raise ProfileInputError([{"code": "source_mismatch", "path": ["clarifications"], "message": "澄清依据不在原文。"}], status="invalid_output")
            issues.append({"code": item["code"], "path": ["parameters", item["field"]] if item["field"] else [],
                           "message": item["message"], "quote": item["quote"]})
        if re.search(r"(?<![A-Za-z0-9_])(?:RFALL|generate_floor_cad|input_mode|template_id)(?![A-Za-z0-9_])", text, re.I):
            issues.append({"code": "outside_template_scope", "path": [], "message": "请描述设计要求，不要加入底层执行指令。"})
        assign = r"\s*(?:采用|为|取|保留|[:：=])?\s*"
        if re.search(r"混凝土" + assign + r"(?:HRB|HPB)\s*\d+|(?:梁纵筋|梁纵向钢筋|板筋|箍筋)" + assign + r"C\s*\d+", text, re.I):
            issues.append({"code": "material_assignment_conflict", "path": [], "message": "混凝土与钢筋的等级归属冲突。"})
        if re.search(r"(?:板筋|箍筋)" + assign + r"HRB\s*\d+", text, re.I):
            issues.append({"code": "unsupported_reinforcement", "path": [], "message": "板筋和箍筋目前须保留HPB300。"})
        if issues:
            raise ProfileInputError(issues)
        model = self._apply(proposal)
        validate_model(model)
        return {"model": model}

    def source_evidence(self, proposal):
        sources = {path: {"source": "工程参数表", "value": value} for path, value in leaves(self.model)}
        for field, value in proposal["parameters"].items():
            if value is not None:
                sources[EDITS[field][1]] = {**deepcopy(proposal["evidence"][field]), "source": "自然语言修改", "value": value}
                if field == "concrete":
                    for key, strength in zip(("fc_MPa", "ft_MPa"), CONCRETE_MATERIALS[value]):
                        sources["materials." + key] = {"source": "已有材料强度映射", "value": strength}
        return sources
