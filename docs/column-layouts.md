# 对称4/6/8筋柱：完整JSON与CLI

阶段18新增`design_column_layouts`、`check_column_layouts`，通过同一Plugin Registry与原Controller执行设计→校核。原单组合和多组合四角筋工具及网页继续保留；此版新布置尚未接网页、自然语言、CAD或计算书。

适用范围仍为教学、非抗震、静力、理想纯轴压矩形柱。N为用户已组合且含重要性系数的设计轴力，同一组合的Mx/My/Vx/Vy必须全部显式为零。有效长度须来自同一分析且覆盖两主轴；来源一致性不代表外部分析真实或完整。支持C25/C30/C35/C40、HRB400纵筋、HPB300箍筋；保护层及截面范围沿用旧柱Tool。

## 在PowerShell运行

先单独切换到克隆的StructAgent目录，再执行命令；不要把两条命令粘成一行。以下Python来自按固定部署说明建立的环境。

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_layouts --request-file demos/column-layouts-eight.json --output-root data/projects/column-layout-acceptance
```

成功显示`success: true`，步骤parse/design/check均completed。数据写入`column-layouts-agent/<run_id>/`（design.json、check.json及状态），引用写入`column-layout-designs/column-layout-<UUID>.json`，重复执行生成新引用。

提供七个匿名完整请求，显式载入后可编辑，不在缺参时隐式套用案例：

|请求文件|输入及预期|
|---|---|
|`demos/column-layouts-four.json`|300×300、N最大1300kN，只授权四筋；选择4Φ14|
|`demos/column-layouts-six-b.json`|500×300、N最大2000kN，只授权six_b；选择6Φ14，h轴拉筋|
|`demos/column-layouts-six-h.json`|300×500、N最大2000kN，只授权six_h；选择6Φ14，b轴拉筋|
|`demos/column-layouts-eight.json`|500×500、N最大3500kN，授权全部布局；选择8Φ16及两轴拉筋|
|`demos/column-layouts-check-fail.json`|实配8Φ14，容量够但总/面最小配筋率不足；FAIL|
|`demos/column-layouts-ties-fail.json`|实配8Φ16漏h轴拉筋；FAIL，不能自动补齐|
|`demos/column-layouts-design-fail.json`|500×500仅授权six_b，另一方向间距超限；候选耗尽FAIL，校核skipped|

实配校核加`--tool-only`，工具名必须是`check_column_layouts`：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_layouts --request-file demos/column-layouts-check-fail.json --tool-only --output-root data/projects/column-layout-acceptance
```

FAIL是预期工程判定，退出码1；成功退出码0。无可行设计保留全部授权候选和逐组失败，不发布成功引用；缺项、非有限/布尔数值、材料冲突、不支持受力或来源错配为结构化输入错误。

## 输入与实际方案

外层Envelope及model/combinations来源沿用[阶段17契约](column-combinations.md)，新增：

- `layout_candidates`：1–4个唯一值，四角`four_corner_bars`、上下b面中筋`six_b`、左右h面中筋`six_h`、四面中筋`eight_perimeter`。仅授权设计搜索，实配校核不会据此换布局。
- `model.ties`：显式diameter_mm、spacing_mm、hook_angle_deg、hook_extension_mm，不再使用旧configuration。设计固定各布局拓扑，同径同距，不调整箍径/箍距。
- 实配`actual`：layout、匹配的bar_count、bar_diameter_mm、perimeter_closed、crosstie_axes、crossties_at_every_layer、ends_engage_bars均必填。四角无拉筋轴；six_b需h、six_h需b、八筋需b/h。轴数组次序不影响物理判定，不得重复。错误支持范围内拓扑或声明false返回FAIL，未知字段/轴及根数错配拒绝。
- 每层全部拉筋双端钩住对应中筋，与周边闭合箍共同约束；四角没有拉筋，every-layer/end-engagement标为不适用。结果的端点是声明布置校核，非现场或加工验收。

引用方式与完整实际模型方式互斥，引用必须属于请求project_id：

```json
{
  "project_id": "TEACHING-LAYOUT-EIGHT",
  "tool": "check_column_layouts",
  "context": {
    "unit_system": "mm,kN,kN.m,MPa",
    "design_code": "GB/T 50010-2010(2024);GB 55008-2021"
  },
  "parameters": {"design_result_ref": "column-layout-替换为本项目实际32位引用"}
}
```

保存为UTF-8 JSON后同样使用`--tool-only`。上面的占位引用不可直接运行。旧column-/column-set-引用不能混用；归属/哈希/输入/候选/实配/逐组结果损坏都停止，校核不重新设计。

## 结果与判定

`selected.actual`为所选实配，`combination_results`保留所有输入组合、来源和结果。每组报告含截面中心原点下的bars坐标、faces各面筋ID/面积/配筋率/逐段中心与净距、required_crossties轴与端点、中间量和逐项checks。完整N/M/V在effective_input内保留。原始最大N识别控制组合，所有并列ID按输入顺序保留；构造失败单列，不能只读容量通过。

总面积查附录A.0.1实际4/6/8根列；各面查2/3根列。总与面表值存在独立整mm²舍入，不能把面面积反算总量；旧v1四筋面面积As/2保持原值，新工具可能相差0.5mm²。设计按总表面积、根数、直径及固定布局顺序选最小全PASS方案。独立依据、坐标约定和手算参考见[冻结契约](column-layouts-contract.md)。

135°及平直段至少max(10dt,75mm)为保守插件政策，并非本范围矩形箍的规范原文强制值。轴压稳定系数φ已按原规则考虑；未核施工加工半径/完整长度、双轴拉筋z错层及碰撞、环境防火、锚固搭接、节点、偏压及其二阶效应、抗震和框架整体二阶分析。结果PASS仅代表声明的检查范围，不是完整工程或施工图批准。
