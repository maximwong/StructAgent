# 柱多组合设计与实配校核

阶段17通过`design_column_combinations`、`check_column_combinations`接入`rc_column` API v1插件。插件版本1.2.0；两个新增Tool版本1.0.0。原`design_column`、`check_column_design`及阶段16网页保持单组合接口。完整契约见[开发计划](column-combinations-plan.md)，工程依据与固定表值复用[柱计算依据](column-basis.md)，未新增偏压、抗震、反力分析或墙传力算法。

## 输入与来源

外层仍为`project_id/tool/context/parameters`。单位固定为mm、kN、kN·m、MPa；规范字符串沿用`GB/T 50010-2010(2024);GB 55008-2021`。必须显式提供所有字段，不补零、不猜单位。

`parameters.model`包含共同截面、材料、箍筋、适用范围和覆盖两主轴的控制有效长度，去掉原`actions`；`effective_length`新增必填`analysis_id`。所有组合必须使用该共同模型及同一个控制有效长度，其适用性由输入方确认。

`parameters.combinations`为1至32个完整组合，每组包含：

- 唯一`combination_id`和完整`actions`：`N_kN`、`Mx_kN_m`、`My_kN_m`、`Vx_kN`、`Vy_kN`、`N_includes_gamma0=true`、`combination_source`。
- `source.analysis_id/member_id/section_id/combination_id/force_record_id/description/unit_system/same_force_vector`；单位字符串为`mm,kN,kN.m,MPa`，同向量声明必须为布尔`true`。
- 全部组合绑定同一分析、同一构件及截面；组合ID匹配所在组合、分析ID匹配有效长度来源、记录ID唯一。ID长度1至128，允许中文，不允许空格、制表符、换行或Unicode空白。

例如匿名样例中的每组N/M/V都来自一条完整声明记录。不能把不同组合的最大N、M、V拼接成一个向量。当前仍要求N为正、M和V均为零；非零即拒绝，不作理想轴压假设替代真实内力。布尔工程数值、非有限数值、材料冲突、缺项和额外字段均拒绝。

来源一致性是声明之间的核对，**不认证外部分析的真实性、正确性或组合完整性**。本版不读取其他软件的原始分析文件，不自动计算有效长度或楼盖反力。

## 本地运行与预期结果

打开PowerShell，进入自己的StructAgent目录。以下每段是完整命令，不追加自然语言。无需DeepSeek或AutoCAD。

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_combinations --request-file .\demos\column-combinations-short.json --output-root .\data\projects\column-combination-acceptance
```

| 文件 | 输入/预期 |
| --- | --- |
| `column-combinations-short.json` | 300×300、l0=900、N=1200/1400：4Φ16，Nu=1418.796kN，ULS-2控制，设计与校核完成 |
| `column-combinations-slender.json` | 同截面、l0=6000、N=900/1170：4Φ20，Nu=1173.933kN，ULS-2控制 |
| `column-combinations-tied.json` | N=1400/1200/1400：4Φ16，ULS-1与ULS-3均控制，保持原顺序 |
| `column-combinations-capacity-failure.json` | N=1200/10000：8个候选全部失败，selected=null，后续校核跳过，无成功设计引用 |
| `column-combinations-check-fail.json` | N=1200/1400、实际4Φ14：逐组PASS/FAIL，整体FAIL，保留实际方案 |

实际方案校核使用明确入口：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_combinations --request-file .\demos\column-combinations-check-fail.json --tool-only --output-root .\data\projects\column-combination-acceptance
```

预期失败会返回`success=false`及退出码1，这表示设计或校核拒绝，不是命令未运行。成功退出码0。CLI严格读取JSON，拒绝重复键、NaN/Infinity和指数溢出。

## 结果查看

CLI输出包含run_id、步骤状态和tool_calls。每个调用的`result_path`指向本次完整ToolResult；不要按目录更新时间猜测结果归属。设计结果`result.selected`包含实际钢筋、逐组结果、控制组合和覆盖范围；每组`report.intermediates`包含phi、Nu、利用率等。顶层`result.attempts`保留从12至首次通过直径的全部固定候选，每个候选包含每一组。

可按输出中的路径查看本次设计：

```powershell
$columnSetResult = Get-Content -LiteralPath '替换为本次design调用的result_path' -Raw -Encoding UTF8 | ConvertFrom-Json
$columnSetResult.result.selected.actual
$columnSetResult.result.selected.controlling_combination_ids
$columnSetResult.result.selected.combination_results | ForEach-Object { $_.combination_id; $_.report.intermediates | Select-Object phi, Nu_kN, utilization }
```

固定共同模型使同一实际配筋的承载力在各组相同，因此控制组合按**原始N值**比较，保留所有精确并列；不按显示舍入后的利用率选择。共同构造失败仍判整体FAIL，不能因容量控制组通过而忽略其他检查。

## 引用与工作流

`rc_column_combinations`声明设计→校核，通过ResultBinding传递`design_result_ref`。Controller核心无需修改。设计失败或引用发布失败停止后续步骤；实际方案校核不会调用设计入口重新选筋。

保存引用使用`column-set-<32位ID>`及独立`column-combination-designs`目录，不能替代原单组合引用。读取核对项目、工具和版本、两层内容哈希及每个实际候选的完整复算；不可覆盖保存。校验和只保护内容一致性，不是身份签名或抵抗恶意本机用户的认证。

引用校核JSON的parameters只能含`design_result_ref`，与`model/combinations/actual`互斥；保留设计时的project_id和context。例如：

```json
{
  "project_id": "TEACHING-COLUMN-SET-SHORT",
  "tool": "check_column_combinations",
  "context": {"unit_system": "mm,kN,kN.m,MPa", "design_code": "GB/T 50010-2010(2024);GB 55008-2021"},
  "parameters": {"design_result_ref": "替换为本项目成功设计的column-set引用"}
}
```

使用同一个output-root及`--tool-only`执行该文件。示例中的占位引用不合法，必须替换。

## 验收边界

仅教学、非抗震、静力、理想纯轴压、矩形固定截面、四根同径角部纵筋及单个封闭矩形箍。有效长度为用户提供的两主轴控制值，组合轴力已含重要性系数。PASS只表示提交组合和声明检查项通过，不代表偏压、附加偏心、框架二阶、上游分析、完整构造或实际工程批准。

阶段17没有多组合网页表单、柱CAD或柱报告；当前网页单组合结果仍按阶段16说明验收。本阶段匿名CLI是可复现验收入口。真实工程来源导入、签名及墙/楼盖联动后续单独开发。
