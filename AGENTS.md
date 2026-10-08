# StructAgent 协作指引

适用于本仓库所有自动化开发助手和贡献者。项目的`v0.1-demo`为阶段8冻结版本，界面真实DeepSeek→Registry→AutoCAD已通过A/B/C两轮6次出图、保存重开和冻结基线核对。后续工作在新分支开发，优先保持Demo稳定及工程工具可插拔。

- 开始修改前阅读 `README.md`、相关源文件和现有测试。按最小改动接入旧程序，避免重写已经验证的楼盖计算公式。
- `legacy/rc_floor/` 是当前可运行的楼盖程序。设计计算与CAD绘图应逐步通过独立工具和 Adapter 接入；Controller 只依赖 Tool Registry、Schema、ToolResult、Project State，不直接导入楼盖旧程序或调用 RFALL。
- 当前支持的材料组合为梁纵筋HRB400、板筋与箍筋HPB300，以及既有C25/C30/C35/C40混凝土映射。扩大工程范围时同时更新校验、计算依据和测试。
- 不把自然语言模型的原始文本送进工程计算；必须经过结构化解析和参数校验。缺少关键工程参数时明确报告。
- 通用参数解析器不导入楼盖脚本；专业语义契约与证据检查由Tool所属LanguageProfile提供。模板模式提取五项参数；v0.2完整模式使用用户表单和13项有逐字证据的自然语言修改，缺项在云调用前返回。表单描述由专业插件依据既有Schema提供。不能隐式填入模板、不猜单位/缺参、不忽略额外要求；ready仅表示输入契约通过，结构适用范围仍由设计工具校核，Controller保持通用。见 `docs/deepseek-integration.md` 和 `docs/explicit-floor-input.md`。
- Controller使用应用声明的Workflow和ResultBinding，不能执行LLM生成的流程或表达式。专业注册与步骤绑定放在 `tools/<专业>/plugin.py`；任何步骤失败必须停止后续工具，外部工具明确返回布尔metadata.recovery_required。每次重试生成新run_id，禁止自动重放未知完成状态的CAD步骤。见 `docs/agent-controller.md`。
- 楼盖工作流已增加`check_floor_design`关口：只读已存设计，用实配钢筋和既有纯函数复核截面/抗剪约束，不能调用设计入口重新选筋后冒充原方案通过。FAIL使用success=false停止CAD，保留逐项依据和未覆盖范围；独立内力、全项验算尚未实现。见 `docs/floor-check-tool.md`。
- 受限重设计仅显式注册和启用：用户完整输入、尺寸候选、最多4轮及时间预算均为必填。每轮只改一个授权字段的下一候选，重新完整设计和校核；未知错误、引用错配、超时及记录失败立即停止。不得改荷载/材料等受保护字段、扩大授权、自动重放CAD或从残留日志续跑；普通网页仍为单次流程。专业诊断在插件内，通用组合及Controller不导入楼盖程序。见 `docs/bounded-redesign.md`。
- 计算书Tool只读取本项目设计引用，报告前经Registry只读Check，复用旧图表/build_docx；禁止调用旧workflow.generate重新设计和出图。调整附录只接收完整PASS的revision_id，核对每轮实际输入、授权及最终引用；不从历史路径执行代码或续跑。网页报告必须使用应用注入的Controller与专业验证器，保留原设计run_id/终态；完整文件、依据、回执和关联均验证后才可打开/下载。正式PDF尚未接入，见 `docs/floor-report-tool.md` 和 `docs/report-ui.md`。
- 不提交密钥、个人路径、客户工程文件、生成图纸、验证日志或CAD临时文件。公开仓库中仅放可复用源码、匿名样例和测试。
- 新Tool继承 `core.EngineeringTool`，实现 `_execute`；沿用基类 `execute` 的输入与输出校验。完整Envelope及结果规范见 `docs/tool-core.md`，示例见 `examples/dummy_tool.py`。
- 正式应用通过`plugins/*/plugin.json`及PluginContribution接入工具、工作流、语言配置和网页回调，不能在app/Controller重新引入专业分支。工厂仅构建对象，不在加载时执行工程/云/CAD；重复或不兼容声明必须拒绝，不静默覆盖。插件为本地可信Python，API v1依赖留在插件内部，代码更新需重启；测试Echo不进入正常安装目录。见`docs/plugins.md`。
- 楼盖工具使用 `tools/floor/design_tool.py` 和 `design_adapter.py`，通过独立Python进程运行旧引擎。不要把旧引擎目录加入Controller或父进程的全局导入路径。模板必须显式选择；输入/输出约定见 `docs/floor-design-tool.md`。
- CAD工具只接收设计结果引用；文件路径、旧CAD命令和AutoCAD会话管理留在Adapter内。每次生成新图纸/目录；没有本次成功回执与保存重开核对，不得返回成功。不能强制终止用户的AutoCAD进程。详见 `docs/floor-cad-tool.md`。
- 修改后运行适当测试。按 `docs/demo-deployment.md` 创建固定独立环境，以 `requirements-demo.lock` 强制哈希安装，运行环境检查及 `python -m unittest discover -s tests -p "test_*.py"`；再在 `legacy/rc_floor/` 执行同一命令运行原有回归。离线包及安装器见 `docs/offline-deployment.md`，更新依赖同时更新版本、wheel哈希及回归。涉及RFALL时记录AutoCAD实机验证，不能把模拟成功写成实机通过。
- 运行状态以SQLite记录及归属会话为依据；JSON快照用原子写入，设计引用不可覆盖。恢复器只能回收经PID启动时间/命令行确认的本工具桥接进程，以及匹配运行标记/路径的图纸。RECOVERY_REQUIRED不得靠删除日志绕过。未验收边界见 `docs/technical-debt.md`。
- 归档默认保留源文件；只有显式compact且全包/成员/来源校验通过才能清理对应终态产物。保留设计引用、状态数据库和会话隔离证据；恢复不执行工具、不覆盖不同内容。见 `docs/artifact-archive.md`。
- Demo案例与冻结基线在 `demos/`；不要在测试中自动重新生成期望值。`examples.demo_acceptance` 实际调用本机API/CAD，公共CI仅用明确标记的模拟后端验证判定规则。已知失败保持原终态，意外失败停止批次且不自动重试。见 `docs/sentence-demo.md`。
- 本机UI入口是`app.py`与`启动StructAgent.cmd`；UI只调通用Controller、读Project State和标准ToolResult，不导入旧引擎或调用LISP。专业呈现可扩展，不能在Controller增加楼盖分支。UI操作串行，运行中不退出或重复提交；刷新不取消工作，恢复沿用归属检查，图纸仅从成功结果打开。见`docs/demo-ui.md`。
- 在PR中交代改动、保持不变的旧功能、测试结果、风险与后续技术债。多人或多模型接手时先阅读当前分支的PR与Issue，避免覆盖他人的未完成工作。
- 常规开发任务默认委派DSH（现有`devtools/dsh/`、`sdk-minimal`、默认`deepseek-flash`）；安装能力仍为独立可选开发组件，不进入产品Tool Registry。GPT负责工程契约、核心算法、拆分、审核、独立验证、整合及Git交付；Astra按`docs/column-roadmap.md`承担只读工程依据/参考/实现/交付审查，产品内DeepSeek仍只负责后续用户需求解析。DSH只实现冻结契约下的Schema/校验、数据转换、测试、样例、文档及辅助呈现，不自行确定条款、公式、材料/稳定系数、配筋判定或工程范围。
- DSH任务必须指定已提交基线、精确路径、单一目标、既定输入输出/独立期望、验收命令和排除项；默认300秒及每请求4096输出token，一个模块/测试文件，最多两个紧密关联文件；一次一个DSH任务，GPT可处理独立工作，不同时修改其任务文件。GPT读取完整补丁并独立核对必要测试后选择性整合，运行时完成不等于评审通过；没有合适任务或接管时记录原因。
- `max-tokens`、超时和异常保留失败状态；可审核利用部分补丁，不冒称任务完成。同一任务因`max-tokens`中断后只重试一次更小任务，再失败由GPT接管，不误判账户余额。阶段报告分别记录任务终态、采用补丁、GPT验证、Astra复核及最终CI；usage可用才记录，不承诺节省比例。DSH不得自动提交/推送/合并；不得自动重放未知CAD。范围提示与独立clone不是OS沙箱，不复制密钥、真实工程数据或未提交修改，累计费用硬上限尚未实现。见`docs/dsh-development.md`。
- 不移动、删除或重新指向`v0.1-demo`标签，不把新功能推到`release/v0.1-demo`。后续缺陷修复另建分支、回归后发布新补丁标签；新专业参数或算法能力进入v0.2分支。冻结包不带API密钥、运行状态、DWG或本机环境。见`docs/releases/v0.1-demo.md`。

## 节约开发额度的默认执行方式（2026-10-08）

- 常规DSH任务默认`reasoning_effort=off`，保留300秒/4096输出token限制；只在明确复杂且必要时显式设置low/high/max，不靠一味提高输出上限。
- GPT只交接一屏已确定契约、精确输入/输出、相关文件和一条验证命令。DSH负责该模块及紧密关联测试（最多两文件），GPT等待补丁期间不重复实现同一模块；真正含糊项由DSH明确报告，不自行扩大工程范围。
- GPT默认只读终态、<=12行摘要、完整授权diff和必要测试结果；不打印完整events或模型推理，不重读未变源码。用量摘要来自唯一assistant/message事件，不把日志内嵌usage重复相加。
- GPT保留核心工程算法/架构与补丁审核；Astra仅在既定工程关口审查核心依据/增量及关键证据。常规文档或辅助测试不额外启动Astra、不复制整段历史给新Agent。最终CI仍负责全量，不因节约额度降低工程验收。
- 开发改动仅影响DSH时只运行DSH相关专项；已经通过且未受影响的楼盖/柱/CAD测试不在本机重复跑。无法保证具体GPT节省比例，DSH用量不等于GPT账户额度或账单人民币。
