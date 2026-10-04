# 楼盖计算书 Tool

`generate_floor_report`读取已有楼盖设计引用，通过Registry调用`check_floor_design`重新只读复核，再使用旧程序的图表及DOCX生成器制作计算书。不会调用设计入口重新选筋，也不调用CAD、云模型或桌面Word。

## 最简运行与验收

从仓库根目录使用固定环境执行：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_report --case demo_a --project-id CSU-REPORT-001
```

这会显式选择完整Demo A模型，经原Controller执行parse→design→check→report，不调用API或CAD。成功为`success: true`、`status: completed`，四步均completed，artifacts包含DOCX、报告依据JSON和生成回执。另可显式选择`sample1`或`changed`；没有隐式默认模板。

在Word打开DOCX；目录及页码使用Word域，需要时选择全文并按F9更新。报告包含旧计算过程、公式代入、图表、编号钢筋长度、完整参数和适用范围，再附独立校核的逐项实际值、限值、结论及来源。校核通过仅表示声明范围通过。

已有设计引用可单独生成报告，必须传入保存该引用的输出根目录及同一项目身份：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_report --design-ref <设计引用> --project-id <原项目编号> --output-root <原输出根目录>
```

已有引用模式不重新设计，且不支持`--cad`或`--revision`；加入`--revision-id <PASS调整记录编号>`可附已完成的调整记录。不能用其他项目的引用或任意文件路径替代编号。

## 受限重设计与出图

```powershell
.\.venv-demo\Scripts\python.exe -m examples.floor_report --request-file demos/revision-a.json --revision --project-id CSU-REVISION-REPORT
```

此入口执行parse→revision→report。报告附逐轮失败原因、授权尺寸改变及诊断依据；最终方案必须通过设计和独立校核。普通请求文件则提供`input_mode: explicit`及完整model，使用相同命令但去掉`--revision`。

新请求/样例模式加`--cad`时，插件在报告成功后添加一次CAD步骤；先打开空闲AutoCAD并满足既有部署条件。报告失败会跳过CAD。当前普通网页及自然语言CLI保持原流程，尚无网页计算书按钮；该功能通过本CLI或注册接口显式启用。

## 统一接口

Tool输入：

```json
{
  "project_id": "CSU-REPORT-001",
  "tool": "generate_floor_report",
  "context": {"unit_system": "SI", "design_code": "GB"},
  "parameters": {"design_result_ref": "floor-<32位十六进制编号>"}
}
```

`revision_id`为唯一可选参数，格式`revision-<32位十六进制编号>`；配置的专业存储解析路径，输入不接受输出文件名/路径。名称和版本为`generate_floor_report`/`1.0.0`。

标准ToolResult返回report_id、completed状态、docx格式、DOCX和依据文件SHA256、设计引用及设计哈希、校核汇总、段落/表格/图片数量和可选调整编号。artifacts为`docx`、`report_evidence`及`report_manifest`，项目数据继续位于Git忽略目录。

## 架构、记录与保护

- `FloorReportTool`：读取不可变设计；校核FAIL/超时/错误立即停止；核对Check身份、项目、引用、设计哈希、判定和覆盖范围。
- `FloorReportAdapter`：每次创建独立报告目录，先存依据，再在隔离Python进程调用旧`figures.generate`、`report.build_docx`。不调用旧`workflow.generate`，因其会重新计算并生成CAD。
- worker明确禁止调用设计/选筋入口；新附录只展示已保存内容及独立Check结果，不修改原公式。
- `report_history.py`：按固定目录和不透明编号读取完整PASS记录，核对项目/最终设计、逐轮输入哈希、文件身份/归属和授权下一候选；不执行历史工具，不续跑失败或RUNNING记录。
- 父进程校验worker协议、DOCX包完整性、实际内容计数及文件哈希，成功回执最后原子、不可覆盖发布。缺失/损坏文件或回执写入失败不返回成功；残留文件不能据此判定完成。

`register_floor_report_workflow`声明普通或受限入口，默认不含CAD。报告前会再只读Check一次，确保直接调用Report Tool也经过校核；即使普通工作流已有Check步骤，也不依赖调用方提供的PASS文本。重复复核会增加少量耗时，不重新设计。

报告生成worker默认60秒时限，前置Check沿用30秒时限；不承诺整个调用硬实时60秒。失败产物保留，当前没有报告中途续跑或自动清理机制。

## 当前验收与限制

自动测试使用真实旧计算、只读Check及DOCX生成，CAD后端明确为模拟，覆盖三原案例、减筋FAIL、归属/校验和、坏记录、超时、坏协议/文件、回执写入失败、重复输出及通用Controller绑定。

本机以阶段10与11已有引用验证普通及调整附录两类报告。DOCX本身不需要桌面Word，但图表生成需要中文字体；正式PDF导出尚未接入Tool。本次视觉验收使用已有Word转换脚本更新独立副本的目录并渲染PDF/PNG，不改变返回DOCX的哈希，不把验收副本称为正式Tool PDF产物。

没有扩大工程计算或独立校核范围，不证明所有输入的版面均通过。记录/哈希用于追溯，不是数字签名。详见[阶段12报告](stages/phase-12.md)、[独立校核范围](floor-check-tool.md)及[技术债](technical-debt.md)。
