"""Bounded, independently checked language support for the approved floor template."""

import re
from copy import deepcopy

from agent.parameter_parser import LanguageProfile, ProfileInputError
from .schemas import TEMPLATE_PARAMETERS


FIELDS = ("span_x", "span_y", "concrete", "steel", "live_load")
NUM = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
LENGTH_UNIT = r"(?:mm|毫米|m|米)"
PAIR = re.compile(rf"({NUM})\s*({LENGTH_UNIT})?\s*[×xX*乘]\s*({NUM})\s*({LENGTH_UNIT})", re.I)
LIVE = re.compile(rf"活荷载\s*(?:为|取|采用|[:：=])?\s*({NUM})\s*(?:kN\s*/\s*m(?:²|2|\^2)|kPa)", re.I)
MATERIAL = re.compile(r"(?<![A-Za-z0-9])(C\d+|HRB\d+|HPB\d+)(?!\d)", re.I)


class FloorDemoProfile(LanguageProfile):
    def __init__(self):
        super().__init__(
            name="office_floor_demo_v1", tool="design_floor_system",
            description="已明确选择办公楼单向板肋梁楼盖模板：主梁3跨、次梁5跨，次梁间距span_x/3，"
                        "板80mm、次梁200×400mm、主梁250×600mm、原恒载/支承，板筋及箍筋HPB300。"
                        "输入顺序为主梁轴跨span_x×次梁轴跨span_y，仅提取五项显式参数，材料转为大写。",
            field_schema={"type": "object", "additionalProperties": False,
                          "required": list(FIELDS),
                          "properties": {k: deepcopy(TEMPLATE_PARAMETERS["properties"][k]) for k in FIELDS}},
            fixed_parameters={"input_mode": "template", "template_id": "office_floor_demo_v1"},
            context={"unit_system": "SI", "design_code": "GB"})

    def inspect(self, text):
        """Fail closed outside this Demo grammar; no automatic engineering assumptions."""
        issues, covered, observed = [], [], {}

        def issue(code, message, field=None):
            issues.append({"code": code, "message": message,
                           "path": ["parameters", field] if field else []})

        restricted = ("双向", "基础", "剪力墙", "钢结构", "楼梯", "柱设计", "设计柱", "墙设计", "设计墙",
                      "板厚", "截面", "恒载", "风荷载", "雪荷载", "抗震", "铰接", "悬挑", "荷载组合",
                      "忽略", "不要", "不得", "不用", "改用", "而非", "所有钢筋", "全部钢筋",
                      "RFALL", "generate_floor_cad", "input_mode", "template_id")
        if any(word.casefold() in text.casefold() for word in restricted):
            issue("outside_template_scope", "输入包含模板外的设计/构造要求或修改指令，请明确参数或使用完整工程输入。")
        # Reject nonnumeric changes too: three/five spans are already fixed by template selection.
        if re.search(r"(?:板筋|箍筋).{0,8}HRB\d+", text, re.I):
            issue("unsupported_reinforcement", "板筋和箍筋仅支持HPB300；HRB400仅适用于梁纵筋。")
        if re.search(r"[一二三四五六七八九十]+跨", text):
            issue("outside_template_scope", "跨数由已选模板固定，不接受自然语言修改。")
        pairs = list(PAIR.finditer(text))
        if len(pairs) > 1:
            issue("ambiguous_parameter", "仅接受一组明确的柱网跨度。", "span_x")
        elif pairs:
            match = pairs[0]
            unit_x, unit_y = match[2] or match[4], match[4]
            observed["span_x"] = float(match[1]) * (1 if unit_x.lower() in ("mm", "毫米") else 1000)
            observed["span_y"] = float(match[3]) * (1 if unit_y.lower() in ("mm", "毫米") else 1000)
            covered.append(match.span())
        materials = list(MATERIAL.finditer(text))
        for prefix, field in (("C", "concrete"), ("HRB", "steel")):
            grades = {m[0].upper() for m in materials if m[0].upper().startswith(prefix)}
            if len(grades) > 1:
                issue("ambiguous_parameter", "同一材料存在多个等级，请明确唯一等级。", field)
            elif grades:
                observed[field] = grades.pop()
        for match in materials:
            grade = match[0].upper()
            covered.append(match.span())
            if grade.startswith("HPB") and (grade != "HPB300" or not re.search(
                    r"(?:板筋|箍筋|板筋和箍筋|板筋及箍筋)\s*(?:采用|为|取|[:：=])?\s*$", text[:match.start()])):
                issue("unsupported_reinforcement", "HPB300仅能明确用于板筋和箍筋；梁纵筋须显式给出HRB400。")
        loads = list(LIVE.finditer(text))
        if len(loads) > 1:
            issue("ambiguous_parameter", "活荷载存在多个输入，请明确唯一值。", "live_load")
        elif loads:
            observed["live_load"] = float(loads[0][1])
            covered.append(loads[0].span())
        # Any additional number is a potential unhandled engineering constraint, never silently drop it.
        if any(not any(start <= m.start() and m.end() <= end for start, end in covered)
               for m in re.finditer(NUM, text)):
            issue("unhandled_numeric_requirement", "存在无法归属到五项模板参数的数值，或缺少/不支持的单位。")
        remaining = list(text)
        for start, end in covered:
            remaining[start:end] = " " * (end - start)
        remaining = "".join(remaining)
        # Explicitly bounded vocabulary keeps unhandled nonnumeric constraints from disappearing.
        words = ("帮我", "请", "设计", "一个", "办公楼", "办公", "单向板", "肋梁", "楼盖", "柱网", "跨度",
                 "混凝土", "梁纵筋", "梁纵向钢筋", "钢筋", "板筋", "箍筋", "活荷载", "采用", "使用",
                 "保留", "分别", "要求", "进行", "楼面", "的", "和", "及", "与", "为", "取", "均", "仅")
        for word in sorted(words, key=len, reverse=True):
            remaining = remaining.replace(word, " ")
        if re.sub(r"[\s，,。.;；:：=、()（）]+", "", remaining):
            issue("unhandled_text_requirement", "包含当前解析范围外的文字要求；请仅描述柱网、混凝土、梁纵筋和活荷载。")
        if issues:
            raise ProfileInputError(issues)
        return observed
