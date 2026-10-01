# StructAgent

StructAgent 的目标是可扩展的建筑结构设计智能体平台。当前已完成**阶段4：DeepSeek自然语言参数解析**，可将已明确选择Demo模板的输入解析为经过本地校验的Tool Envelope。原有Tool Registry的 `design_floor_system` → `generate_floor_cad` 无AI设计出图链路继续可用。自动串联解析、设计和CAD的Agent Controller将在阶段5实现。

阶段3.1已补充CAD超时/取消恢复、Python退出后的会话协调、持久状态与固定部署环境。详见 [修复报告](docs/stages/phase-3.1.md)、[技术债清单](docs/technical-debt.md) 和 [固定环境部署](docs/demo-deployment.md)。

## 当前可用内容

- `legacy/rc_floor/`：原有楼盖程序的独立修复版，保留板、次梁、主梁的连续计算及 RFLOAD/RFALL AutoLISP 命令。
- `legacy/rc_floor/demo_a.json`：确认的6m×6m办公楼演示参数。梁纵筋HRB400，板筋与箍筋HPB300。
- `legacy/rc_floor/tests/`：无需启动AutoCAD的计算、报告与CAD数据回归测试。
- `core/`：EngineeringTool、ToolResult、ToolRegistry、统一校验及通用持久执行状态。
- `tools/floor/`：楼盖设计/CAD Tool、Adapter、隔离计算与数据转换进程、结果引用及已确认的Demo模板。
- `agent/parameter_parser.py`、`llm/`：通用参数解析器、插件提供的语言配置及有总时限的DeepSeek接口。
- `examples/`、`tests/`：可运行示例及103项核心、设计、CAD、状态与解析测试，另有87项旧程序回归。
- `AGENTS.md`、`CONTRIBUTING.md`：多设备和多模型协作约定。

阶段0.1关闭了材料名称与强度不一致、布尔值参与工程数值计算、RFALL撤销组异常三项缺陷。原有80项加新增7项自动测试在本机通过。AutoCAD实机验收记录和图纸仅保留在原工作区本地，不包含在公共仓库中。

## 在新设备上运行

1. 克隆仓库：`git clone https://github.com/maximwong/StructAgent.git`。
2. 按 [固定部署说明](docs/demo-deployment.md) 创建Python 3.12.14独立环境，安装 `requirements-demo.txt` 并运行环境检查。后续示例中的 `python` 均指该环境的Python。
3. Windows下运行 `legacy/rc_floor/启动.cmd`。CAD绘图需要本机安装AutoCAD并按现有流程加载 `legacy/rc_floor/RCFLOOR.lsp`。
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

输出 `ready` 表示参数提取及输入契约校验通过，包含后续工具可使用的Envelope；此命令仅解析。缺项、歧义、模板外要求、模型JSON错误或API失败会返回对应状态，禁止带着失败结果继续设计。输入顺序为主梁轴跨×次梁轴跨，梁纵筋HRB400、板筋和箍筋HPB300。当前使用明确限定的中文Demo表达范围；使用方法、模板限制和扩展接口见 [DeepSeek接入说明](docs/deepseek-integration.md)，验收见 [阶段4报告](docs/stages/phase-4.md)。

## 协作方向

下一步为阶段5：建立Agent Controller，使其只查询Registry和统一结果，将经过校验的解析结果串联到设计及CAD工具，不直接调用旧程序或CAD命令。新增墙、柱、基础等能力时沿用同一接口。

请通过 Issue 记录任务，使用独立分支和 Pull Request 提交修改，在PR中说明影响范围、验证命令和结果。工程算法变更需要给出样例对比和必要的校核依据。参见 [协作指南](CONTRIBUTING.md)。

当前 [v0.1-demo 里程碑](https://github.com/maximwong/StructAgent/milestone/1) 已列出[Tool Core](https://github.com/maximwong/StructAgent/issues/1)、[楼盖设计接入](https://github.com/maximwong/StructAgent/issues/2)、[CAD接入](https://github.com/maximwong/StructAgent/issues/3)、[一句话出图](https://github.com/maximwong/StructAgent/issues/4)和[稳定演示](https://github.com/maximwong/StructAgent/issues/5)的验收任务。

本项目目前尚未选择开源许可证。公共可见不自动授予再发布或商用许可。
