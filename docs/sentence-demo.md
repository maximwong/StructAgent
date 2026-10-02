# 一句话出图与重复验收

Demo使用已明确选择的 `office_floor_demo_v1`：梁纵筋HRB400、板筋/箍筋HPB300，主梁3跨、次梁5跨，板80mm及既定截面/支承/恒载。自然语言只给出柱网、混凝土、梁纵筋和活荷载；模型不猜测关键工程参数，也不修改模板。

在已配置本机.env、固定Python环境和空闲AutoCAD 2022的设备，从仓库根目录执行：

```powershell
.venv-demo/Scripts/python.exe -m examples.agent_workflow --template office_floor_demo_v1 --text "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
```

入口通过Controller与Registry依次完成解析、输入校验、完整楼盖设计、CAD生成。只有本次DWG保存、重开与场景核验成功才显示completed，返回的artifacts给出DWG和回执路径。默认文件位于Git忽略的 `data/projects/`，每次使用独立运行编号。

这是命令行Demo。阶段7已提供最简UI及“打开CAD”按钮；双击根目录`启动StructAgent.cmd`即可输入设计内容，无需PowerShell命令，见[界面说明](demo-ui.md)。旧GUI、工程计算和AutoLISP继续保持原行为。

阶段6.1已移除措辞白名单：也可说“麻烦帮我算一下……活载按每平方米2.8千牛考虑”，或换序、换行、中英文及中文数字。原文值和单位仍必须明确，缺参或工程要求超出已选模板时返回具体澄清。`python -m examples.language_acceptance` 可单独实测12项语言/澄清案例，不执行设计或CAD，详见 [阶段6.1报告](stages/phase-6.1.md)。当前完整批次的缺参/C50探针也会先调用模型，正式两轮带超时探针共10次API调用；旧报告中的8次是旧解析流程的历史实测结果。

## 固定案例

| 案例 | 柱网 | 混凝土 | 梁纵筋 | 活荷载kN/m² |
| --- | --- | --- | --- | --- |
| A | 6m×6m | C30 | HRB400 | 2.0 |
| B | 5.4m×6m | C30 | HRB400 | 2.0 |
| C | 6m×6m | C35 | HRB400 | 3.0 |

自然语言及预期参数位于 `demos/floor_cases.json`。A沿用既有阶段0基线；B/C先用旧引擎和旧CAD转换流程做无AI预检查，其冻结摘要在 `demos/floor_baselines.json`。参数解析成功不代表结构适用范围通过，原校核继续执行。

## 连续验收

```powershell
.venv-demo/Scripts/python.exe -m examples.demo_acceptance --rounds 2 --timeout-probe
```

该命令实际调用云API与桌面AutoCAD，有相应API费用。先验证缺活荷载、不支持C50以及7.2m×6m超出既有模型适用范围；随后运行A/B/C两轮。第一轮之后把独立工具图纸的CAD预算设为10秒，用一次已知失败检查恢复，再继续第二轮。全部步骤连续使用同一个输出根目录，失败历史也保留。

`--rounds` 范围1–3，正式重复验收使用2轮或更多；不带 `--timeout-probe` 时不缩短CAD时限。`--output-root <目录>` 可以指定本机测试位置。默认 `data/projects/demo/acceptance/<suite_id>/summary.json` 保存进度及最终验收；工作流SQL、设计引用和CAD产物仍按原布局保存。

验收同时检查实际解析参数、完整设计和保存的CAD场景摘要、实体/文字/尺寸、DWG保存重开、工具文档关闭、系统变量、用户原图列表、唯一工作流/设计/CAD编号。每个成功案例记录7份输出的文件摘要，之后逐次复核旧文件没有变化。DWG字节摘要用于各自文件的完整性检查；不同DWG的时间戳等可能不同，不要求两次DWG字节完全相同。

summary.success=true表示计划内正常案例及失败探针都符合预期；失败探针对应的工作流仍是failed/needs_input/invalid_input，不改写为成功。任何意外API错误、待恢复CAD会话、基线不一致或旧文件变化都会停止后续案例，不自动重试。修复后重新执行生成新的suite_id/run_id；禁止删除恢复日志绕过隔离。

公共CI使用记录解析和明确标记的模拟CAD，只验证验收脚本的判定逻辑；实机证据的evidence_kind为live，图纸和日志只留本机。阶段结果见 [阶段6报告](stages/phase-6.md)。
