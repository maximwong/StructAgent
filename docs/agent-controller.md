# Engineering Agent Controller（阶段5）

Controller接收自然语言及显式模板选择，调用参数解析器，再通过Registry顺序执行工作流。它不导入专业Tool/Adapter或旧计算程序，不包含任何具体CAD命令。

## 运行及查看状态

先按 [固定环境部署](demo-deployment.md) 与 [DeepSeek接入说明](deepseek-integration.md) 配置本机环境、API密钥和已信任的CAD脚本。打开AutoCAD 2022，保持空闲。

在项目根目录运行（此命令会实际创建新的测试图纸并保存）：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.agent_workflow --template office_floor_demo_v1 --text "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
```

可用 `--text-file request.txt` 读取UTF-8要求。默认输出根目录为仓库下 `data/projects/`；`--output-root` 可指定独立验证目录。每次调用生成不同的run_id、设计引用、结果文件和CAD目录，不覆盖先前运行。

成功时返回 `success: true`、`status: completed`；当前v0.2楼盖插件声明`steps.parse/design/check/cad`四步均为completed，`artifacts`包含DWG与验证回执路径。Controller只有收到有效ToolResult并持久保存结果后才完成步骤；解析ready不代表整个设计出图完成。独立校核FAIL返回success=false，由通用停止逻辑跳过CAD，Controller无需改动。见[校核Tool](floor-check-tool.md)。

用返回的run_id查看状态（自定义输出根目录时传相同的 `--output-root`）：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.agent_workflow --status <run_id>
```

状态查询不加载API配置，也不运行工程或CAD工具。可在另一个终端轮询查看current_task、steps及tool_calls。运行结束成功返回退出码0，缺参/错误/中断返回1。

## 接口与专业边界

- `agent/controller.py`：只使用Registry、Schema、ToolResult、解析结果和持久状态。
- `agent/workflow.py`：`Workflow` / `WorkflowStep` / `ResultBinding`声明步骤、固定参数及前序结果字段绑定。配置由应用提供，不能由模型生成。
- `agent/state.py`：复用 `core.ProjectStateStore` 的SQLite事务、进程归属和终态保护；每步ToolResult独占原子发布。
- `tools/floor/plugin.py`：在组合入口注册楼盖设计、独立校核与CAD工具，并提供工作流配置。此模块由CLI导入，Controller不导入。
- `FloorDesignTool(store=...)`：计算成功后复用已有设计存储，返回 `metadata.design_result_ref`。不传store时保持原有无持久输出行为。

楼盖工作流配置如下：

```python
Workflow("floor_design", (
    WorkflowStep("design", "design_floor_system"),
    WorkflowStep("check", "check_floor_design",
        bindings={"design_result_ref": ResultBinding(
            "design", ("metadata", "design_result_ref"))}),
    WorkflowStep("cad", "generate_floor_cad", external_effects=True,
        bindings={"design_result_ref": ResultBinding(
            "check", ("result", "design_result_ref"))}),
))
```

首步参数来自通过校验的解析Envelope。后续参数从声明的前序成功ToolResult路径获取，项目身份和context沿用原Envelope；绑定缺项或Schema不符则停止。固定参数和绑定不能重名，禁止向后引用、重复步骤及未知工具。路径只访问字典键或列表下标，不执行表达式、脚本或动态导入。

解析到的工具名称查找唯一工作流；每个入口工具只允许配置一条工作流。增加墙、柱、基础等能力时，注册Tool、LanguageProfile与Workflow即可。测试中的第二种工程工具只替换注册配置，未修改Controller。生产自动扫描插件目录仍按原路线放在后续版本。

阶段11另提供显式注册的`floor_revision`流程，入口为`design_floor_with_revisions`，内部通过Registry组合设计、校核和专业建议工具；最终引用再绑定到CAD。初始完整参数、允许的候选及上限从结构化请求输入，普通自然语言/UI流程不自动切换。Controller及其失败停止规则保持不变，详见[受限重设计](bounded-redesign.md)。

## 状态及失败处理

默认状态数据库为 `data/projects/agent/state.sqlite3`，ToolResult位于 `agent/<run_id>/<step>.json`。SQL记录是状态依据；结果JSON只保存完整、不可覆盖的步骤输出。原始自然语言和API密钥不写入工作流记录，保留解析后的Envelope、错误、警告、产物与步骤事件。

| 状态 | 行为 |
| --- | --- |
| running | 记录当前步骤；调用有外部副作用的工具前持久写入external_started |
| needs_input / invalid_input / invalid_output / error | 本次解析尝试终止；补参后开启新run_id，不重用旧结果 |
| failed | 已知失败，后续pending步骤改为skipped，保留成功前序结果和错误 |
| completed | 全部步骤校验与持久化成功 |
| interrupted | 执行被中断或原进程退出，不自动重放步骤 |
| recovery_required | 外部调用结果/清理状态不确定；保留证据，按工具的恢复流程处理 |

SQLite核心状态只有RUNNING/COMPLETED/FAILED/INTERRUPTED/RECOVERY_REQUIRED；需要补参等业务状态保存在metadata.status，本次尝试在数据库中终结为FAILED。

外部工具失败后，通过通用 `metadata.recovery_required` 明确告知是否需要恢复，值必须是布尔值。未明确证明清理完成的外部失败按需要恢复处理。CAD Tool对已知的正常失败返回false，对待恢复会话返回true；Controller不匹配CAD专用错误码。

进程退出后的状态查询会识别旧进程归属并显示中断/待恢复，后续未执行步骤显示skipped。不会因为存在DWG文件就推定成功，也不会自动重复CAD调用。CAD会话仍由已有Adapter负责归属校验、恢复与隔离；可用 `python -m examples.cad_recovery --output-root <同一输出根目录>` 按既有流程恢复。

已有工作流记录保留当时的中断/待恢复结论；CAD后续完成恢复不会自动把历史工作流改成completed，重新执行需要新run_id。当前不实现从中间步骤续跑、全局跨工具取消按钮或跨设备共享数据库。持久状态写入失败立即停止，返回state_saved:false，需要检查最后的持久记录。

阶段5.1中状态查询使用主键，协调只检查索引中的RUNNING记录；确认原进程退出时，仍在running的工具调用同步显示interrupted。已知的CAD待恢复故障不伪称进程崩溃。汇总warnings去重，步骤ToolResult保留原始警告。终态产物可按 [归档说明](artifact-archive.md) 手动归档和恢复；状态查询附加artifact_archive路径及requires_restore，不重写执行结论。

## 测试

```powershell
.\.venv-demo\Scripts\python.exe -m unittest discover -s tests -p test_agent_controller.py -v
```

覆盖顺序调用、结果绑定、重复运行、失败停止、参数重新校验、异常/中断、状态不可写、引用不可保存、第二种工具注册及真实子进程退出。集成自动测试使用真实楼盖计算和CAD数据转换，但CAD后端明确为模拟；实机验收另见 [阶段5报告](stages/phase-5.md)。
