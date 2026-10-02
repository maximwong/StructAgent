# 【阶段5】Engineering Agent Controller

日期：2026-10-02。目标：Controller只通过Registry、Schema、ToolResult及Project State串联解析、设计与CAD。

## 完成内容

- 实现通用Controller及Workflow/WorkflowStep/ResultBinding。工作流由应用注册，模型只提供经验证的参数，不生成执行程序或步骤。
- 复用SQLite事务状态、进程归属识别和原子文件发布。记录parse/design/cad状态、调用工具及版本、标准结果路径、错误、警告和产物。
- 每次尝试使用新run_id，成功结果独占保存；缺参、解析/设计/绑定/持久化/CAD失败均停止后续步骤。进程退出或外部结果不明时记录中断/待恢复，不自动重放CAD。
- 楼盖工具可选保存已有设计快照并返回metadata.design_result_ref；插件注册模块声明从设计引用到CAD参数的绑定。Controller不认识楼盖脚本、设计引用格式或CAD命令。
- 新增可运行命令入口及无API/CAD副作用的状态查询入口。

## 修改文件

`tools/floor/design_tool.py`：可选注入设计存储，默认调用行为不变，保存失败明确返回失败。

`tools/floor/cad_tool.py`：通过通用布尔metadata.recovery_required传递外部恢复状态；设计引用无效时明确没有启动外部操作。

`README.md`、`AGENTS.md`、`docs/technical-debt.md`：更新阶段、协作和未验收范围。

## 新增文件

`agent/controller.py`、`agent/workflow.py`、`agent/state.py`、`tools/floor/plugin.py`、`examples/agent_workflow.py`、`tests/test_agent_controller.py`、`docs/agent-controller.md`及本报告。

测试日志、JSON状态、DWG及临时验证脚本仅保存在Git忽略的 `verification/phase-5/`。密钥继续仅保留本机.env，不进入提交。

## 保持不变的旧功能

楼板/次梁/主梁公式、配筋、已有校核、CAD转换/绘制算法、RFLOAD/RFALL、CAD归属恢复逻辑及锁定依赖均未修改。原无AI设计/CAD示例继续可用；不传store的FloorDesignTool仍只计算，不创建设计引用。

## 测试内容

- 新增27项Controller/集成测试：成功顺序及持久步骤、外部调用前记录意图、解析失败/缺参、不合法解析状态、项目身份不一致、Schema重新校验、绑定缺失/类型错误、设计拒绝、未知工具、错误配置、未知外部状态、异常与中断、状态/结果不可写、重复运行不覆盖及快照保存失败。
- 第二种测试工程能力只新增工具注册与工作流配置，无需修改Controller；架构测试确认Controller不导入专业工具/旧程序或包含具体CAD命令。
- 真实子进程退出后识别为RECOVERY_REQUIRED，后续步骤不重放；真实楼盖计算与CAD数据转换通过Controller执行，自动测试CAD后端明确为模拟。
- 130项项目测试与87项旧程序回归；完整设计及CAD场景哈希维持阶段0基线。
- 两次真实DeepSeek API超时均在45秒总限时停止，工作流仅parse失败、tool_calls为空、没有CAD产物。随后密钥/模型检查、最小JSON请求成功，再次实时完整工作流成功。
- 记录解析重放到真实CAD，以及实时DeepSeek到真实CAD分别保留独立证据，不混称云端实测。

## 测试结果

本机 **130 + 87 = 217项通过**。

| 实际验证 | 结果 |
| --- | --- |
| 实时DeepSeek → Controller → Registry → 设计 → CAD | 工作流parse/design/cad均completed，success=true |
| CAD实体核对 | 2305实体、356文字、218尺寸，逐场景验证通过 |
| DWG保存及重新打开 | 通过，工具创建的文档已关闭，保留原Drawing1.dwg |
| 系统变量恢复 | CMDECHO、CLAYER、OSMODE、INSUNITS、UNDOCTL前后相同 |
| 设计结果基线 | SHA256 `2df9a0a4039145d7eeed5b48f71d1aa9fd9375122dd5fa5b46fc5edc32971bf4`一致 |
| CAD场景基线 | SHA256 `e6d4f2e9cb98329caa17815f819852b1589cce54870be427ad9b24735780f7e1`一致 |
| 状态重新读取 | SQL终态COMPLETED，步骤及结果保持一致，无需再次调用API/CAD |
| 缺少活荷载 | needs_input，未调用任何工程工具 |
| 早期两次真实API超时 | api_timeout，约45秒终止，未调用设计/CAD；证据保留 |

本机证据索引：`verification/phase-5/acceptance.json`；完整成功记录 `run-3.json`；失败记录 `run-1.json`、`run-2.json`；状态查询 `completed-status.json`；独立重放结果 `recorded-cad-result.json`。DWG、工具输出及完成回执路径由验收索引引用。

## 发现的问题

- 开始两轮云端请求超时；HTTPS可达性、配置密钥及模型可用性后续检查正常，最小请求及完整请求恢复成功。没有证据把早期超时归因于本地代码或特定云端故障，也未修改网络设置、放宽校验或加入自动重试。
- CAD Tool此前仅返回专用错误码，通用Controller无法判断恢复需求。补充统一布尔metadata，控制器不依赖CAD错误名称。
- AutoCAD窗口截图工具返回 `window crop is outside captured monitor`，本轮没有完成视觉截图验收。实机结果依据CAD Adapter逐图元、文字、尺寸、保存/重开及变量回执，不声称视觉检查通过。

## 技术债务

T06–T09仍开放：桌面硬挂起/模态组合、离线制品归档、长期产物容量、复杂自然语言/更多实际云故障与稳定重复演示。当前不做步骤中间续跑；恢复后的历史失败不改为成功，重新执行使用新run_id。最简UI及可视化进度按阶段7实施。

## 当前是否达到阶段验收标准

**达到阶段5声明的Demo范围验收标准。** Controller只通过Registry调用工具，通用状态与失败停止机制通过测试，真实云端到CAD链路通过一次保存重开验收。没有把一次成功当作阶段6/7的连续稳定性全部完成。

## 下一阶段建议

进入阶段6，固定演示启动入口、自然语言案例A/B/C和可复现的结果检查，连续运行并保留失败证据。之后阶段7接最简UI、打开DWG入口及剩余稳定性测试，继续保持Controller与专业脚本解耦。
