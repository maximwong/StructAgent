# StructAgent

StructAgent 的目标是可扩展的建筑结构设计智能体平台。当前已接入**阶段3：楼盖 CAD Tool / Adapter**，可通过Tool Registry完成 `design_floor_system` → `generate_floor_cad` 的无AI设计出图链路。Agent Controller和LLM解析尚未实现。

## 当前可用内容

- `legacy/rc_floor/`：原有楼盖程序的独立修复版，保留板、次梁、主梁的连续计算及 RFLOAD/RFALL AutoLISP 命令。
- `legacy/rc_floor/demo_a.json`：确认的6m×6m办公楼演示参数。梁纵筋HRB400，板筋与箍筋HPB300。
- `legacy/rc_floor/tests/`：无需启动AutoCAD的计算、报告与CAD数据回归测试。
- `core/`：EngineeringTool、ToolResult、ToolRegistry及统一校验。
- `tools/floor/`：楼盖设计/CAD Tool、Adapter、隔离计算与数据转换进程、结果引用及已确认的Demo模板。
- `examples/`、`tests/`：可运行示例、21项核心测试、18项楼盖设计测试和16项CAD工具测试。
- `AGENTS.md`、`CONTRIBUTING.md`：多设备和多模型协作约定。

阶段0.1关闭了材料名称与强度不一致、布尔值参与工程数值计算、RFALL撤销组异常三项缺陷。原有80项加新增7项自动测试在本机通过。AutoCAD实机验收记录和图纸仅保留在原工作区本地，不包含在公共仓库中。

## 在新设备上运行

1. 克隆仓库：`git clone https://github.com/maximwong/StructAgent.git`。
2. 安装 Python 3.12，在仓库根目录执行 `python -m pip install -r requirements-dev.txt` 安装开发及旧程序依赖。
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

## 协作方向

下一步为阶段4：接入云端LLM，将自然语言转换成经过Schema验证的工程参数。之后建立Agent Controller，使其只查询Registry和统一结果，不直接调用旧程序或CAD命令。新增墙、柱、基础等能力时沿用同一接口。

请通过 Issue 记录任务，使用独立分支和 Pull Request 提交修改，在PR中说明影响范围、验证命令和结果。工程算法变更需要给出样例对比和必要的校核依据。参见 [协作指南](CONTRIBUTING.md)。

当前 [v0.1-demo 里程碑](https://github.com/maximwong/StructAgent/milestone/1) 已列出[Tool Core](https://github.com/maximwong/StructAgent/issues/1)、[楼盖设计接入](https://github.com/maximwong/StructAgent/issues/2)、[CAD接入](https://github.com/maximwong/StructAgent/issues/3)、[一句话出图](https://github.com/maximwong/StructAgent/issues/4)和[稳定演示](https://github.com/maximwong/StructAgent/issues/5)的验收任务。

本项目目前尚未选择开源许可证。公共可见不自动授予再发布或商用许可。
