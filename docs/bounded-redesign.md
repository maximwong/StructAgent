# 受限重设计（阶段11）

当前为显式启用的结构化请求入口。普通网页、自然语言解析和原来的“设计→校核→CAD”流程保持单次执行。该入口不调用LLM，不让模型生成工作流或自行决定工程参数。

## 使用与验收

在仓库根目录，使用已安装的固定环境运行：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_revision --request-file demos/revision-a.json
```

默认只设计、校核和保存记录。样例主梁宽从100mm开始，授权候选为100、125、150、250mm，最大4轮，计算时间预算180秒。真实旧引擎先拒绝100和125mm方案：次梁正筋还受主梁支座直段容纳约束；第三轮150mm方案通过既有设计及182项独立检查。这只是本样例的可行候选，不代表最优尺寸或全项规范审查通过。

需要出图时，先打开AutoCAD 2022，完成部署说明中的启动和脚本信任提示，并保持空闲，再运行：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_revision --request-file demos/revision-a.json --cad
```

`--cad`通过原Controller执行声明式`floor_revision`流程。只有受限设计工具最终成功并持久保存后，才调用一次`generate_floor_cad`。成功须为`success: true`、`status: completed`，parse/revision/cad均completed，且CAD返回保存重开及场景验证回执。不能仅凭revision为PASS判定出图完成。默认产物在被Git忽略的`data/projects/`；可用`--output-root`指定独立目录，重复运行生成新编号。

## 请求与授权

请求包含四个必填项：

| 字段 | 约束 |
| --- | --- |
| initial_parameters | 完整`input_mode: explicit`模型；沿用[完整输入契约](explicit-floor-input.md)及旧算法适用范围，不自动套模板 |
| allowed_changes | 明确的字段到候选列表；至少一个字段，每个列表1至8个正数、严格递增，第一项等于初始值 |
| max_attempts | 1至4，包含初始计算轮次 |
| time_budget_seconds | 大于0且不超过240秒的有限数值，不能是布尔值 |

仅可授权`model.slab.h_mm`、`model.secondary.b_mm`、`model.secondary.h_mm`、`model.main.b_mm`、`model.main.h_mm`。梁高候选不超过800mm，其余候选上限2000mm；通过输入校验不等于通过旧引擎。荷载、材料、支承、跨度、配筋构造及report等其他字段不能修改。

每轮只能改一个已授权字段，取当前值之后的下一候选；不能跳过、降低尺寸、重复方案或按模型建议扩大授权。先校验整个请求，再计算；每次建议还会独立校验实际参数差异、候选值和修改记录。无匹配诊断规则、候选耗尽或轮数达到上限时停止，不输出最终可出图引用。

## 工程反馈与停止条件

`propose_floor_revision`使用专业插件内的小范围规则，识别原设计器的配筋/排布不足、主次梁高度关系等明确拒绝，以及独立Check的部分截面、配筋、间距、抗剪失败。某些增厚/加宽建议也可能继续失败；必须重新完整设计并校核，不能编辑已保存钢筋使报告通过。

设计器经常在生成引用前拒绝方案，故循环同时支持明确的`design_rejected`和`design_check_failed`。未知工程拒绝、数据一致性失败、引用错误、超时、坏结果、工具异常和待恢复状态立即停止。失败Check的引用也必须与本轮设计一致。

时间预算为调用之间检查的合作式预算：现有设计和校核子进程各有30秒超时；当前调用及记录写入可能使实际耗时超过总预算，超预算后不再开始下一项计算或CAD。该预算不包括后续CAD，CAD继续使用已有独立超时/归属恢复规则，不宣称硬实时总时限。

## 架构与记录

`agent/revision.py`的`BoundedRevisionTool`只依赖Registry、Schema、ToolResult及持久记录；`RevisionSpec`声明子工具、引用绑定和允许重试的错误码。楼盖诊断规则、输入Schema及两种工作流的注册位于`tools/floor/`。Controller核心不修改；测试用另一组非楼盖工具验证相同组合接口。插件自动扫描及第二种生产结构能力仍属后续阶段。

每次在`revisions/revision-<新编号>/`保存：

- `input.json`：完整初始请求及授权；不可覆盖。
- `attempt-NN/input.json`、`design.json`、`check.json`、`diagnosis.json`：实际执行的输入及结果；未执行步骤无文件。
- `state.json`：当前步骤与历史摘要，原子更新。
- `result.json`：最终标准ToolResult；不可覆盖，先发布完整结果再写终态。

记录失败时外层返回失败并禁止CAD；进程中断或最终状态写入失败可能留下RUNNING/不完整日志。不能仅凭某个结果文件或目录认定执行完成，须以外层成功结果及完整终态判断。当前不自动协调、恢复或从中间轮次续跑该日志；人工检查后开启新运行，保留原记录。记录不是数字签名，也不承诺抵抗本机文件篡改。

## 验证与当前边界

自动测试覆盖真实拒绝后通过、上限与候选耗尽、非法授权、超时/中断、恶意建议、引用错配、记录失败、重复记录保留及CAD调用门槛。Check FAIL后重设计的故障分支使用明确标注的模拟失败，后续设计和Check为真实计算；公共测试CAD后端为模拟。真实桌面结果另见[阶段报告](stages/phase-11.md)。

尚未覆盖全部规范、独立内力重算或所有尺寸调整规则；专业拒绝诊断仍依赖旧引擎少量精确错误文本，后续应提供结构化工程失败码。未增加网页授权交互、LLM诊断、多轮补参、自动优化或崩溃后续跑能力。
