# StructAgent 协作指引

适用于本仓库所有自动化开发助手和贡献者。项目当前已完成阶段4自然语言参数解析及真实DeepSeek验证；下一步是阶段5Agent Controller。优先提高可演示链路的稳定性，并保持未来工程工具可插拔。

- 开始修改前阅读 `README.md`、相关源文件和现有测试。按最小改动接入旧程序，避免重写已经验证的楼盖计算公式。
- `legacy/rc_floor/` 是当前可运行的楼盖程序。设计计算与CAD绘图应逐步通过独立工具和 Adapter 接入；Controller 只依赖 Tool Registry、Schema、ToolResult、Project State，不直接导入楼盖旧程序或调用 RFALL。
- 当前支持的材料组合为梁纵筋HRB400、板筋与箍筋HPB300，以及既有C25/C30/C35/C40混凝土映射。扩大工程范围时同时更新校验、计算依据和测试。
- 不把自然语言模型的原始文本送进工程计算；必须经过结构化解析和参数校验。缺少关键工程参数时明确报告。
- 通用参数解析器不导入楼盖脚本；专业语言范围与证据检查由Tool所属的LanguageProfile提供。解析阶段不执行工具。当前只支持显式选择的办公楼Demo模板，不静默忽略未知文字/数值约束；ready仅表示输入契约通过，结构适用范围仍由设计工具校核。见 `docs/deepseek-integration.md`。
- 不提交密钥、个人路径、客户工程文件、生成图纸、验证日志或CAD临时文件。公开仓库中仅放可复用源码、匿名样例和测试。
- 新Tool继承 `core.EngineeringTool`，实现 `_execute`；沿用基类 `execute` 的输入与输出校验。完整Envelope及结果规范见 `docs/tool-core.md`，示例见 `examples/dummy_tool.py`。
- 楼盖工具使用 `tools/floor/design_tool.py` 和 `design_adapter.py`，通过独立Python进程运行旧引擎。不要把旧引擎目录加入Controller或父进程的全局导入路径。模板必须显式选择；输入/输出约定见 `docs/floor-design-tool.md`。
- CAD工具只接收设计结果引用；文件路径、旧CAD命令和AutoCAD会话管理留在Adapter内。每次生成新图纸/目录；没有本次成功回执与保存重开核对，不得返回成功。不能强制终止用户的AutoCAD进程。详见 `docs/floor-cad-tool.md`。
- 修改后运行适当测试。按 `docs/demo-deployment.md` 创建固定独立环境，安装 `requirements-demo.txt`，运行环境检查及 `python -m unittest discover -s tests -p "test_*.py"`；再在 `legacy/rc_floor/` 执行同一命令运行原有回归。涉及RFALL时记录AutoCAD实机验证，不能把模拟成功写成实机通过。
- 运行状态以SQLite记录及归属会话为依据；JSON快照用原子写入，设计引用不可覆盖。恢复器只能回收经PID启动时间/命令行确认的本工具桥接进程，以及匹配运行标记/路径的图纸。RECOVERY_REQUIRED不得靠删除日志绕过。未验收边界见 `docs/technical-debt.md`。
- 在PR中交代改动、保持不变的旧功能、测试结果、风险与后续技术债。多人或多模型接手时先阅读当前分支的PR与Issue，避免覆盖他人的未完成工作。
