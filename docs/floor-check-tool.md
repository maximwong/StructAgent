# 独立楼盖校核Tool

`check_floor_design`（1.0.0）读取本项目已保存的设计引用，对实配钢筋做独立执行的截面复核，不重新选筋，不调用LLM或CAD。当前工作流为：

```text
自然语言解析 → design_floor_system → check_floor_design → generate_floor_cad
```

专业插件声明步骤及结果绑定；Controller代码不需要修改。CAD步骤的引用来自校核通过结果。直接使用历史`FloorCADTool`/`examples.floor_cad`接口仍保留原行为；新的Agent工作流才增加这个校核关口。

## 审计结论与复用

原`legacy_core.run`混合内力计算、配筋选择及剪力设计，`engine.calculate`继续执行承载力、配筋几何、搭接和材料包络检查。不能重新调用这些入口后，把重新选择出的方案当作原方案的校核结果。

本工具在隔离子进程中复用以下既有纯计算函数，原源码不修改：

| 原函数 | 本次用途 |
| --- | --- |
| `legacy_core.area`、`layout` | 从直径/根数或间距重算面积、钢筋坐标、排数和有效高度 |
| `engine.capacity`、`legacy_core.provided_x` | 由实配面积和重算截面求受弯承载力与实配受压区 |
| `legacy_core.flexure` | 用零需求取得同一最小配筋规则，不重新选择钢筋 |
| `legacy_core.shear` | 用已存剪力和重算有效高度取得强度、最小配箍率及间距上限，再检查原实配间距；不采用其重新给出的建议间距冒充实配 |
| `engine.check_input`、`legacy_core.validate` | 核对原模型适用范围、材料及构造输入 |

另按原`beam_design`的取值顺序，重算翼缘宽度和正筋端部容纳条件。每个检查项附来源函数、实际值、比较符、限值、单位及通过状态。浮点比较采用`1e-7 + 1e-8 × max(|actual|, |limit|)`容差。

这里的“独立”指工具执行、结果持久化和实配复核边界独立；公式仍复用原教学引擎，不构成第二套规范或独立内力分析方法。

## 输入与结果

输入沿用统一Envelope，参数仅含`design_result_ref`。项目标识、引用格式、存储归属、整体及旧结果哈希均由既有DesignStore检查；标准结果与旧结果的截面/抗剪记录还须一致。

```json
{
  "project_id": "CSU-DEMO-001",
  "tool": "check_floor_design",
  "context": {"unit_system": "SI", "design_code": "GB"},
  "parameters": {"design_result_ref": "floor-替换为本项目的32位引用编号"}
}
```

通过时返回标准ToolResult，`success=true`、`result.status=PASS`；`result`包括`checks`、`summary`、原设计引用及`coverage`。未通过时`success=false`、`result.status=FAIL`，仍保存完整明细和`design_check_failed`错误。此工具的success含义是“允许工作流继续”，因此已正常执行但工程检查未通过也返回false。

超时、引用损坏、输入不完整或协议错误属于执行失败，不会返回PASS，也不伪造工程FAIL明细。默认子进程时限30秒。任何失败均通过原通用Controller停止后续CAD；不触发CAD恢复，不自动重试或自动修改关键工程参数。

本次成功样例有180项检查，包含一致性检查，不能理解为180项独立规范验算。覆盖：板/梁受弯承载力、实配受压区、最小配筋、梁净距/排布/端部容纳、板筋间距、梁抗剪和箍筋间距约束。

**输入弯矩、剪力和计算跨度仍取自保存的设计分析结果。** 荷载组合与内力分析、分布筋/吊筋/附加箍筋、锚固搭接/材料包络/下料长度，以及裂缝挠度、抗震、耐久性、防火和节点碰撞不在本版独立复核范围；原设计程序已有检查继续保留。PASS只适用于声明范围。

## 使用与验收

新版UI显示四步进度和“独立校核”卡片，可展开范围与逐项结果。FAIL显示失败项并跳过CAD；修正输入后开始新运行，历史失败不会被改写。旧历史没有校核步骤时显示未执行，不补造PASS。

只校核已存设计可运行：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_check --project-id "实际项目标识" --design-result-ref "实际floor引用" --output-root .\data\projects
```

项目标识和引用取自设计ToolResult的`metadata`，不能用另一个UI项目显示名称代替。该命令只读原设计；成功退出码0，其他情况1，完整ToolResult输出为JSON。Agent模式会自动调用，无需用户输入此命令。

校核器能发现减少钢筋、放大箍筋间距、伪造已存承载力和无效排布。相关反例为测试中构造的候选结果，未将其提交给真实CAD。现有设计器仍可能在形成设计引用前拒绝不足方案；尚未实现完整的FAIL→自动诊断→改参→再设计闭环。后续需要明确候选参数范围和迭代上限。验收记录见[阶段10报告](stages/phase-10.md)。
