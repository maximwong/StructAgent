# StructAgent

StructAgent 的目标是可扩展的建筑结构设计智能体平台。当前仓库保存已验证的单向板肋梁楼盖程序独立修复版，作为首个工程工具的接入基础。Tool Registry、Agent Controller、LLM解析和统一CAD Adapter 尚未实现；仓库状态为**阶段0.1**，不是最终演示版。

## 当前可用内容

- `legacy/rc_floor/`：原有楼盖程序的独立修复版，保留板、次梁、主梁的连续计算及 RFLOAD/RFALL AutoLISP 命令。
- `legacy/rc_floor/demo_a.json`：确认的6m×6m办公楼演示参数。梁纵筋HRB400，板筋与箍筋HPB300。
- `legacy/rc_floor/tests/`：无需启动AutoCAD的计算、报告与CAD数据回归测试。
- `AGENTS.md`、`CONTRIBUTING.md`：多设备和多模型协作约定。

阶段0.1关闭了材料名称与强度不一致、布尔值参与工程数值计算、RFALL撤销组异常三项缺陷。原有80项加新增7项自动测试在本机通过。AutoCAD实机验收记录和图纸仅保留在原工作区本地，不包含在公共仓库中。

## 在新设备上运行

1. 克隆仓库：`git clone https://github.com/maximwong/StructAgent.git`。
2. 安装 Python 3.12 和 `legacy/rc_floor/requirements.txt` 中的依赖。
3. Windows下运行 `legacy/rc_floor/启动.cmd`。CAD绘图需要本机安装AutoCAD并按现有流程加载 `legacy/rc_floor/RCFLOOR.lsp`。
4. 在 `legacy/rc_floor/` 目录运行 `python -m unittest discover -s tests -p "test_*.py"` 检查无需CAD的回归测试。

`启动.cmd` 会先尝试已有的本机Python运行时，找不到时使用命令行中的 `python`。工程图纸、报告和本机配置请保存在各自设备，不提交到公共仓库。

## 协作方向

下一步按项目计划建立最小 `EngineeringTool`、`ToolResult`、`ToolRegistry`，再通过 Adapter 接入现有楼盖设计和CAD脚本。Agent Controller 只查询 Registry 和统一结果，不直接调用旧程序或 RFALL。新增墙、柱、基础等能力时沿用同一接口。

请通过 Issue 记录任务，使用独立分支和 Pull Request 提交修改，在PR中说明影响范围、验证命令和结果。工程算法变更需要给出样例对比和必要的校核依据。参见 [协作指南](CONTRIBUTING.md)。

当前 [v0.1-demo 里程碑](https://github.com/maximwong/StructAgent/milestone/1) 已列出[Tool Core](https://github.com/maximwong/StructAgent/issues/1)、[楼盖设计接入](https://github.com/maximwong/StructAgent/issues/2)、[CAD接入](https://github.com/maximwong/StructAgent/issues/3)、[一句话出图](https://github.com/maximwong/StructAgent/issues/4)和[稳定演示](https://github.com/maximwong/StructAgent/issues/5)的验收任务。

本项目目前尚未选择开源许可证。公共可见不自动授予再发布或商用许可。
