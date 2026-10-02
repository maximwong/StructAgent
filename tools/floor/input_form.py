"""Floor-owned presentation descriptors derived from the existing full input schema."""

import json
from pathlib import Path
from .schemas import EXPLICIT_MODEL

GROUPS = {"project": "工程信息", "basis": "工程信息", "geometry": "柱网与支承（mm）",
          "loads": "荷载与组合", "materials": "材料及强度（MPa）", "slab": "板截面与配筋候选（mm）",
          "secondary": "次梁截面与构造（mm）", "main": "主梁截面与构造（mm）",
          "detailing": "配筋与布置", "report": "构造和计算书信息"}
LABELS = {
    "project": "工程显示名称", "basis": "计算依据与荷载组合说明",
    "secondary_axis_spans_mm": "次梁五个轴跨", "main_axis_spans_mm": "主梁三个轴跨",
    "secondary_spacing_mm": "次梁间距", "wall_axis_to_inner_face_mm": "墙轴线至内侧面距离",
    "slab_bearing_mm": "板支承长度", "secondary_bearing_mm": "次梁支承长度",
    "main_bearing_mm": "主梁支承长度", "column_width_mm": "柱宽",
    "concrete_kN_m3": "混凝土容重（kN/m³）", "finish_mm": "面层厚度（mm）",
    "finish_kN_m3": "面层容重（kN/m³）", "plaster_mm": "抹灰厚度（mm）",
    "plaster_kN_m3": "抹灰容重（kN/m³）", "live_kN_m2": "活荷载（kN/m²）",
    "gamma_g": "恒载分项系数", "gamma_q": "活载分项系数",
    "concrete": "混凝土等级", "slab_steel": "板筋等级", "beam_steel": "梁纵筋等级",
    "stirrup_steel": "箍筋等级", "fc_MPa": "混凝土抗压强度", "ft_MPa": "混凝土抗拉强度",
    "alpha1": "混凝土应力系数α1", "slab_fy_MPa": "板筋强度", "beam_fy_MPa": "梁纵筋强度",
    "stirrup_fy_MPa": "箍筋强度", "xi_elastic_limit": "弹性受压区限值", "xi_plastic_limit": "塑性受压区限值",
    "h_mm": "截面高度/板厚", "b_mm": "截面宽度", "cover_mm": "保护层厚度",
    "arch_factor": "内拱折减系数", "distribution_diameter_mm": "分布筋直径",
    "main_diameters_mm": "板受力筋直径候选", "spacings_mm": "板筋间距候选",
    "stirrup_diameter_mm": "箍筋直径", "stirrup_legs": "箍筋肢数", "extra_top_mm": "顶筋附加距离",
    "max_stirrup_spacing_mm": "最大箍筋间距", "support_moment": "支座弯矩位置（axis轴线/face边缘）",
    "hanger_diameter_mm": "吊筋直径", "hanger_angle_deg": "吊筋角度（°）",
    "beam_diameters_mm": "梁纵筋直径候选（mm）", "maximum_rows": "钢筋最大排数",
    "aggregate_mm": "骨料粒径（mm）", "slab_support_extension_ratio": "板支座伸出比例",
    "slab_wall_extension_ratio": "板墙端伸出比例", "author": "编制人（可空）",
    "class_name": "班级（可空）", "student_id": "编号（可空）", "date": "日期（可空）",
    "anchor_ribbed_factor": "带肋筋锚固系数（d）", "anchor_plain_factor": "光圆筋锚固系数（d）",
    "lap_factor": "搭接系数", "max_stock_mm": "原材长度（mm）", "top_extension_ratio": "次梁顶筋伸出比例",
    "stirrup_hook_tail_d": "箍筋平直段系数（d）", "stirrup_bend_inner_d": "箍筋弯曲内径系数（d）",
    "allow_arch": "启用内拱折减",
}


def floor_input_form():
    fields = []
    def walk(schema, path=()):
        if schema.get("type") == "object":
            for key, child in schema["properties"].items():
                walk(child, (*path, key))
        else:
            fields.append({"path": ".".join(path), "group": GROUPS[path[0]], "label": LABELS[path[-1]], "schema": schema})
    walk(EXPLICIT_MODEL)
    example = json.loads((Path(__file__).with_name("templates") / "office_floor_demo_v1.json").read_text(encoding="utf-8-sig"))
    return {"fields": fields, "example": example,
            "notice": "所有参数来自表单或你主动导入的案例；不会自动补齐缺项。主梁3跨、次梁5跨及三分点布置仍由旧引擎限定。"}
