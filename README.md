# StructAgent

StructAgent 的目标是可扩展的建筑结构设计智能体平台。**`v0.1-demo`为阶段8冻结版本，本开发分支为`v0.2-dev`**。本机浏览器界面通过既有Controller与Registry完成自然语言解析、楼盖设计和CAD出图。冻结版界面实机A/B/C两轮6/6通过保存重开与基线核对；版本范围、固定部署和后续开发规则见[冻结说明](docs/releases/v0.1-demo.md)。

新设备演示请使用`git clone --branch v0.1-demo --single-branch https://github.com/maximwong/StructAgent.git`，再按部署说明配置环境和本机API。`main`与开发分支不作为已冻结版本的替代；后续功能在新分支开发，不移动此标签。

本机环境已配置后，双击根目录的 **`启动StructAgent.cmd`**，填写自然语言要求、确认演示模板并点击“开始设计”。界面显示参数依据、执行进度、设计摘要、工具日志及“打开CAD图纸”按钮。见 [界面使用说明](docs/demo-ui.md) 和 [阶段7报告](docs/stages/phase-7.md)。

本开发分支新增“完整工程参数（不使用模板）”：填写或导入参数，可直接说“按表单设计”，也可修改板厚、梁截面等13项参数；无需勾选模板。缺项明确提示，完整表单不会隐式填入案例。主梁3跨、次梁5跨等旧引擎边界仍保留。见[使用说明](docs/explicit-floor-input.md)与[本阶段报告](docs/stages/phase-9.md)。切换分支后需退出并重新启动旧UI服务。

当前进一步接入`check_floor_design`：Agent按“设计→独立截面校核→CAD”执行，FAIL即停止出图。UI显示逐项结果和范围，原计算/Controller不改动。仅覆盖实配截面、排布及抗剪约束。见[校核Tool说明](docs/floor-check-tool.md)与[阶段10报告](docs/stages/phase-10.md)。

阶段10.1修复校核记录损坏时的页面异常与判定一致性，保留原历史并禁止从不可确认记录打开CAD。用户已确认手动浏览器验收完成，此前自动验收中止记录保留，见[技术债清理报告](docs/stages/phase-10.1.md)。

阶段11新增显式启用的受限重设计入口：完整模型、允许调整的尺寸候选、最多4轮和时间预算都由用户提供。每轮调用设计及独立校核，最终PASS后才可出图；普通网页仍使用单次流程。运行`python -m examples.floor_revision --request-file demos/revision-a.json`仅计算，加`--cad`才调用真实AutoCAD。见[使用与边界](docs/bounded-redesign.md)及[阶段11报告](docs/stages/phase-11.md)。

阶段12新增`generate_floor_report`，读取已保存设计、只读校核后复用旧生成器输出Word计算书，并可附完整授权调整记录。运行`python -m examples.floor_report --case demo_a --project-id CSU-REPORT-001`通过原Controller完成设计→校核→报告，不调用API/CAD。见[计算书Tool](docs/floor-report-tool.md)与[阶段12报告](docs/stages/phase-12.md)。

阶段13将普通设计的计算书生成、打开及下载接入网页，作为独立操作和运行记录，保留原设计/CAD状态。无需重新调用云模型、设计或出图；文件与归属校验失败停止文档操作。正式PDF和网页调整授权尚未接入；浏览器/文档软件的实机验收状态见[阶段13报告](docs/stages/phase-13.md)，操作步骤见[网页计算书](docs/report-ui.md)。

阶段14增加本地`plugins/*/plugin.json`发现与加载。楼盖工具、语言配置、工作流和网页回调通过插件接入，应用及Controller不导入楼盖模块。用`python -m examples.plugin_inventory`查看能力，测试Echo插件验证增加能力无需改Controller。正常网页仍只支持一个专业，真实柱/基础另行审计接入。见[插件说明](docs/plugins.md)与[阶段14报告](docs/stages/phase-14.md)。

阶段15新增第二种真实工程插件 RC Column：在固定矩形截面上完成教学范围的非抗震、静力、理想纯轴压四角纵筋设计及实际方案独立校核。通过完整JSON输入和原Controller执行“设计→校核”，无需API、AutoCAD或楼盖模板。柱工具不接入网页、自然语言、CAD或计算书；PASS仅表示本版声明检查项通过。见[柱工具使用说明](docs/column-tool.md)、[工程依据与独立参考](docs/column-basis.md)及[阶段15报告](docs/stages/phase-15.md)。

阶段16新增柱网页入口：选择专业、填写或严格导入完整柱Envelope，执行本地设计→校核，或单步复核实际配筋/本项目引用。无需API、AutoCAD或自然语言口令；结果显示配筋、稳定系数、承载力、逐项判定、输入来源与未覆盖范围。同项目历史绑定各自运行，楼盖原入口保持兼容。操作和验收见[柱网页说明](docs/column-ui.md)，实现及验证证据见[阶段16报告](docs/stages/phase-16.md)，后续顺序与模型分工见[柱开发路线](docs/column-roadmap.md)。

阶段17新增来源绑定的柱多组合设计与实配校核Tool，逐组保留完整N/M/V与来源，按原始N识别所有并列控制组合；非零弯矩/剪力继续拒绝。通过现有插件和Controller运行，原单组合网页不变。完整JSON/CLI、5个匿名算例和引用校核见[柱多组合说明](docs/column-combinations.md)，开发及验收证据见[阶段17报告](docs/stages/phase-17.md)。

阶段18新增对称4/6/8筋设计与实配校核：每面按实际根数查面积，输出钢筋坐标、逐段间距及相应拉筋端点，按授权布局搜索最小全PASS方案，固定其它输入。完整JSON/CLI、7个匿名请求和边界见[布置工具说明](docs/column-layouts.md)、[冻结工程契约与手算参考](docs/column-layouts-contract.md)及[阶段18报告](docs/stages/phase-18.md)。原四角筋/多组合工具、单组合网页和Controller保持兼容。

阶段3.1已补充CAD超时/取消恢复、Python退出后的会话协调、持久状态与固定部署环境。详见 [修复报告](docs/stages/phase-3.1.md)、[技术债清单](docs/technical-debt.md) 和 [固定环境部署](docs/demo-deployment.md)。

阶段5.1已修复材料字段归属和超时诊断，补齐 [历史产物归档](docs/artifact-archive.md) 与 [离线安装和制品哈希](docs/offline-deployment.md)。真实链路、取消/超时及离线新环境验证通过，详见 [修复报告](docs/stages/phase-5.1.md)。

阶段6运行方式见 [一句话Demo](docs/sentence-demo.md)，重复实机结果见 [阶段报告](docs/stages/phase-6.md)。批次摘要记录预期失败和完整基线，不自动重试或覆盖旧结果。

## 当前可用内容

开发时可选使用[DeepSeek Harness外部子Agent](docs/dsh-development.md)：GPT下发有范围和时限的小任务，复用本机DSH桌面CLI，在独立代码副本中执行并返回补丁。此开发能力与StructAgent的工程插件和自然语言解析分别配置，不更改产品Controller。

- `legacy/rc_floor/`：原有楼盖程序的独立修复版，保留板、次梁、主梁的连续计算及 RFLOAD/RFALL AutoLISP 命令。
- `legacy/rc_floor/demo_a.json`：确认的6m×6m办公楼演示参数。梁纵筋HRB400，板筋与箍筋HPB300。
- `legacy/rc_floor/tests/`：无需启动AutoCAD的计算、报告与CAD数据回归测试。
- `core/`：EngineeringTool、ToolResult、ToolRegistry、统一校验及通用持久执行状态。
- `tools/floor/`：楼盖设计/CAD Tool、Adapter、隔离计算与数据转换进程、结果引用及已确认的Demo模板。
- `agent/parameter_parser.py`、`llm/`：通用参数解析器、插件提供的语言配置及有总时限的DeepSeek接口。
- `agent/controller.py`、`workflow.py`、`state.py`：通过Registry执行声明式工作流，记录每一步结果与失败/中断状态；`agent/revision.py`提供可配置的受限工具组合。
- `app.py`、`ui/`：本机浏览器界面、后台工作流执行、历史记录及受控恢复/打开图纸，无新增依赖。
- `tools/column/`：独立材料表、确定性纯轴压计算、设计及校核Tool、不可覆盖的设计引用；检查实际配筋时不重新选筋。
- `plugins/`：本地专业插件声明及工厂，启用RC Floor与RC Column；兼容楼盖云网页绑定，并通过可选结构化网页贡献接入本地柱表单和结果。
- `examples/`、`tests/`：可运行示例及391项核心、插件、楼盖/柱设计及校核、受限重设计、计算书、CAD、状态、解析、Controller、归档、部署、Demo与UI测试，其中2项可选DSH进程测试在主环境跳过，开发环境另测；另有87项旧程序回归。
- `demos/`：A/B/C自然语言、预期参数及已冻结的完整设计/CAD场景基线。
- `AGENTS.md`、`CONTRIBUTING.md`：多设备和多模型协作约定。

阶段0.1关闭了材料名称与强度不一致、布尔值参与工程数值计算、RFALL撤销组异常三项缺陷。原有80项加新增7项自动测试在本机通过。AutoCAD实机验收记录和图纸仅保留在原工作区本地，不包含在公共仓库中。

## 在新设备上运行

1. 克隆仓库：`git clone https://github.com/maximwong/StructAgent.git`。
2. 按 [固定部署说明](docs/demo-deployment.md) 创建Python 3.12.14独立环境，以 `requirements-demo.lock` 强制哈希安装并运行环境检查。后续示例中的 `python` 均指该环境的Python。
3. 配置本机`.env`中的DeepSeek API，打开AutoCAD并完成脚本信任提示，然后双击根目录`启动StructAgent.cmd`。原GUI仍可通过`legacy/rc_floor/启动.cmd`运行；CAD依赖说明见部署文档。
4. 在 `legacy/rc_floor/` 目录运行 `python -m unittest discover -s tests -p "test_*.py"` 检查无需CAD的回归测试。

`启动.cmd` 会先尝试已有的本机Python运行时，找不到时使用命令行中的 `python`。工程图纸、报告和本机配置请保存在各自设备，不提交到公共仓库。

## 运行 Tool Core 示例

在仓库根目录执行：

```powershell
python -m examples.dummy_tool
python -m unittest discover -s tests -p 'test_*.py' -v
```

Dummy Tool会通过Registry接收统一Envelope，并输出含 `success`、`result`、`errors` 等字段的JSON。它仅演示框架，不进行结构计算。完整接口见 [Tool Core说明](docs/tool-core.md)，阶段验收见 [阶段1报告](docs/stages/phase-1.md)。

## 通过Registry设计楼盖

在仓库根目录运行：

```powershell
python -m examples.floor_design
python -m examples.floor_design --case sample1
python -m examples.floor_design --case changed
```

默认输出设计摘要和原程序的适用范围警告；加 `--full` 输出完整ToolResult。默认Demo显式选择已确认模板，另外两例使用完整输入。详见 [楼盖工具输入与输出](docs/floor-design-tool.md)及 [阶段2报告](docs/stages/phase-2.md)。该命令只计算并返回数据，不创建图纸或报告文件。

## 通过Registry生成CAD

先打开桌面版AutoCAD 2022并完成部署和脚本加载提示，在仓库根目录运行：

```powershell
python -m examples.floor_cad
python -m examples.floor_cad --case changed
```

示例先计算并保存设计结果引用，再在全新图纸中绘制、保存和重开核对。完成后返回DWG路径；默认结果保存在被Git忽略的 `data/projects/`，重复执行使用不同目录。详见 [CAD工具说明](docs/floor-cad-tool.md) 和 [阶段3报告](docs/stages/phase-3.md)。AutoCAD未开启、忙碌或验证失败时返回错误，不把残留文件视为成功。

中断后运行 `python -m examples.cad_recovery`；自定义输出根目录时同时传 `--output-root`。恢复只处理有归属证据的工具会话，恢复失败会阻止下一次出图。不要删除会话日志绕过保护。

## 用DeepSeek解析自然语言

在本机将 `.env.example` 复制为 `.env`，填入自己的 `DEEPSEEK_API_KEY`。`.env` 已被Git忽略；每台设备独立配置，密钥不要放在聊天、代码或PR中。

```powershell
python -m examples.parse_request --template office_floor_demo_v1 --text "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
```

输出 `ready` 表示参数提取及输入契约校验通过，包含后续工具可使用的Envelope及逐字原文依据；此命令仅解析。口语、换序、中英文、换行及中文数字先交由模型理解，不用词汇白名单拦截。缺项、歧义或模板外要求返回具体澄清；模型格式错误或API失败仍停止后续执行。输入顺序为主梁轴跨×次梁轴跨，梁纵筋HRB400、板筋和箍筋HPB300。使用方法、模板边界和扩展接口见 [DeepSeek接入说明](docs/deepseek-integration.md)，当前语义改进见 [阶段6.1报告](docs/stages/phase-6.1.md)。

## 通过Controller自动完成设计与CAD

完成本机API与CAD部署，打开空闲的AutoCAD 2022后运行：

```powershell
python -m examples.agent_workflow --template office_floor_demo_v1 --text "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
```

该命令会实际创建独立图纸，自动执行解析、设计、独立截面校核及CAD工具。成功返回 `status: completed`，四步均completed，并给出DWG路径。缺参、接口错误、设计拒绝、校核FAIL或CAD失败均停止后续步骤。通过返回的run_id运行 `python -m examples.agent_workflow --status <run_id>` 可查看持久状态，不再调用API/CAD。

每次运行使用独立结果目录；Controller没有楼盖脚本导入或CAD命令。工作流配置、失败恢复及扩展方法见 [Controller说明](docs/agent-controller.md)，实机证据与范围见 [阶段5报告](docs/stages/phase-5.md)。

## 协作方向

阶段20新增本地JSON/CLI教学主梁反力提取与直接落梁非承重墙自重分析，保留8工况及来源，不自动生成柱内力或覆盖旧楼盖。使用与验收见[反力工具说明](docs/floor-reactions.md)和[阶段20计划](docs/floor-wall-reactions-plan.md)。

阶段8已冻结稳定Demo；本分支已接入完整参数、独立截面校核、受限循环、DOCX、本地插件发现及教学纯轴压柱CLI/网页能力。Controller只依赖Registry、Schema、ToolResult和Project State；新增能力通过插件注册工具、语言配置、工作流和专业呈现接入。柱网页沿用阶段15算法范围，不扩展楼盖工程范围。

请通过 Issue 记录任务，使用独立分支和 Pull Request 提交修改，在PR中说明影响范围、验证命令和结果。工程算法变更需要给出样例对比和必要的校核依据。参见 [协作指南](CONTRIBUTING.md)。

当前 [v0.1-demo 里程碑](https://github.com/maximwong/StructAgent/milestone/1) 已列出[Tool Core](https://github.com/maximwong/StructAgent/issues/1)、[楼盖设计接入](https://github.com/maximwong/StructAgent/issues/2)、[CAD接入](https://github.com/maximwong/StructAgent/issues/3)、[一句话出图](https://github.com/maximwong/StructAgent/issues/4)和[稳定演示](https://github.com/maximwong/StructAgent/issues/5)的验收任务。

本项目目前尚未选择开源许可证。公共可见不自动授予再发布或商用许可。

阶段19新增四角筋单向偏压截面 `design_column_eccentric`／`check_column_eccentric`，完整来源绑定JSON/CLI通过原Controller执行设计→实配校核。输入为外部已处理整体及杆件二阶的最终N/M，本地只加一次附加偏心；教学非抗震静力，网页/CAD/报告暂不接入。使用 `python -m examples.column_eccentric --request-file demos/column-eccentric-large.json`，独立实配校核加`--tool-only`。见[使用与范围](docs/column-eccentric-tool.md)、[阶段19](docs/stages/phase-19.md)。
