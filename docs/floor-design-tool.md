# design_floor_system

阶段2把完整的旧楼盖计算作为一个工具接入：`FloorDesignTool → FloorDesignAdapter → engine.calculate`。保留板、次梁、主梁、配筋、已有校核及几何数据；此工具不调用AutoCAD，不写报告或图纸文件。

## 最小调用

在仓库根目录运行 `python -m examples.floor_design`，或使用：

```python
from core import ToolRegistry
from tools.floor import FloorDesignTool

registry = ToolRegistry()
registry.register(FloorDesignTool())
result = registry.get("design_floor_system").execute({
    "project_id": "CSU-DEMO-001",
    "tool": "design_floor_system",
    "context": {"unit_system": "SI", "design_code": "GB"},
    "parameters": {
        "input_mode": "template",
        "template_id": "office_floor_demo_v1",
        "span_x": 6000,
        "span_y": 6000,
        "concrete": "C30",
        "steel": "HRB400",
        "live_load": 2.0
    }
})
if not result.success:
    print(result.errors)
else:
    print(result.result["slab"])
```

`context` 仅接受 `unit_system=SI`、`design_code=GB`。本工具沿用旧模型的工程单位：长度mm、作用力kN、应力MPa、面荷载kN/m²；不根据SI标签自动把米换算成毫米，也不声称完成GB规范全项审查。旧程序的五条范围/校核警告完整返回。

## 模板模式

`input_mode=template` 时，上例中的八个参数字段全部必填。模板名不能省略或换成任意路径。模板记录在 `tools/floor/templates/office_floor_demo_v1.json`，内容来自用户确认的Demo A。

| 标准字段 | 旧输入映射 |
| --- | --- |
| span_x | 三个相同的主梁轴跨；次梁间距按三分点布置取span_x/3 |
| span_y | 五个相同的次梁轴跨 |
| concrete | 原映射支持的C25/C30/C35/C40，并从共用材料模块取fc、ft |
| steel | 仅梁纵筋，当前必须HRB400；板筋和箍筋仍为HPB300 |
| live_load | loads.live_kN_m2 |
| project_id | 模板的显示项目名为“project_id 办公楼”；外层metadata保留project_id |

板厚80mm、次梁200×400mm、主梁250×600mm以及支承、恒载、保护层、配筋候选和构造参数沿用模板。跨度改变时不自动加大截面；旧程序会明确拒绝不满足当前模型或已有校核的输入。数值为整数的毫米值保留整数表示，以维持冻结基线的JSON表示；不对非整数尺寸取整。

五个跨度/材料/荷载字段本身不足以定义任意工程。因此不会在未选择模板时猜测其余参数，也不允许混合模板和完整模型输入。

## 完整参数模式

传入 `parameters={"input_mode": "explicit", "model": 完整旧输入对象}`。所有字段结构由Schema验证，样例见 `legacy/rc_floor/sample1.json`、`changed.json` 和 `demo_a.json`。完整模式保留model里的项目显示名称，外层project_id用于本次调用归属。

材料名称与强度必须一致；不会替用户修正冲突值。合法布尔项 `report.allow_arch` 保留，工程数值中的布尔值拒绝。完整输入中的原单位和截面定义均不转换。旧引擎会复制输入，关闭内拱开关时按原逻辑把实际计算中的arch_factor设为1，返回的effective_input反映这一事实；调用者原输入不被修改。

## 输出及后续CAD输入

统一ToolResult中的 `result` 包含：

- `slab`：sections与distribution。
- `secondary_beam`：sections与shear_checks。
- `main_beam`：sections、shear_checks、hanger、suspension。
- `reinforcement.bars`：全部钢筋记录，包含长度、分段、形状及位置。
- `checks`：已有接头检查与材料包络检查。
- `effective_input`：旧引擎实际使用的完整参数。
- `legacy_result`：完整计算快照，供后续CAD/报告Adapter复用；保留原计算书章节和几何数据。

各构件的具体记录字段沿用旧程序，通用Controller不需要解释旧文本。标准结果中的warnings保留旧引擎警告，metadata记录模式、模板、单位及完整快照SHA-256。`success=true` 表示这次计算完成并未触发已有检查拒绝，不表示完成尚未实现的工程全项审查。

本阶段artifacts为空，尚不生成 `design_result_ref` 或持久化项目状态。下一阶段CAD Adapter可复用 `legacy_result`，无需再次设计。CLI默认打印包含 `summary` 的展示摘要；`--full` 才打印完整可传递的ToolResult。

## 隔离与错误

旧模块使用engine、geometry等顶层导入名。Adapter用当前解释器启动独立进程，以绝对路径调用私有 `_legacy_worker.py`，通过UTF-8 JSON传入/返回数据。父进程不增加旧程序导入路径，不解析print日志；旧程序额外标准输出被送到stderr。Python元组在JSON传输中变为数组，与阶段0.1冻结JSON一致。

错误码包括输入 `validation_error`、旧模型/已有校核拒绝 `design_rejected`、计算进程启动/退出错误、`design_timeout` 和 `legacy_protocol_error`。意外Adapter异常由Core转为 `execution_error`。错误结果不创建成果文件。

计算子进程默认限时30秒，可以在构造 `FloorDesignAdapter(timeout_seconds=...)` 时配置。只管理本次创建的Python进程；这不等于解决后续AutoCAD全生命周期超时或进程恢复。所有路径相对模块位置解析，不依赖调用方当前目录或用户机器目录。
