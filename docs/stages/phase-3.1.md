# 【阶段3.1】Demo前技术债修复

日期：2026-10-02。分支 `fix/cad-lifecycle`，基于阶段3的 `feature/floor-cad`。原项目、阶段0基线和已冻结指纹不修改。

## 完成内容

1. 超时/取消/桥接异常后有界恢复。取消文件仅属于本次运行，RFALL在实体之间检查；恢复器只处理具备运行标记和路径证据的图纸。保存并重开验证仍是成功前提。
2. 检查原Python进程及桥接进程的启动时间，拒绝把复用PID当原进程。恢复遗留桥接时还检查可执行文件、固定脚本、运行编号及目录；不终止AutoCAD。归属不明和无法响应时保持RECOVERY_REQUIRED，阻止下一次出图。
3. 通用SQLite ProjectStateStore与原子JSON写入。独立运行历史、事务、终态约束、真实进程退出协调均可由未来Controller复用；不依赖楼盖实现。设计引用采用不可覆盖的完整快照发布。
4. 固定Python与11项直接/传递依赖，干净虚拟环境安装、环境检查及CI部署。新增恢复命令和超时配置参数。

## 修改文件

`core/__init__.py`；`tools/floor/cad_adapter.py`、`cad_bridge.ps1`、`design_store.py`；`examples/floor_cad.py`；`legacy/rc_floor/RCFLOOR.lsp`；`tests/test_floor_cad.py`；CI、忽略规则及README/协作/CAD说明。

LISP仅添加本次取消文件检查，不改变计算、图元构造、撤销组创建或既有异常清理函数。测试中的UTF8读取和目录创建按新增状态存储调整，没有放宽原有结果断言。

## 新增文件

- `core/persistence.py`、`process_identity.py`、`project_state.py`。
- `tools/floor/cad_message_filter.cs`；`examples/cad_recovery.py`、`environment_check.py`。
- `.python-version`、`requirements-demo.txt`。
- `tests/test_persistence.py`、`test_cad_lifecycle.py`。
- `docs/demo-deployment.md`、`technical-debt.md`、本报告。

## 保持不变的旧功能

板、次梁、主梁连续计算、材料校验、钢筋长度、既有公式、三案例完整设计结果及CAD参数/图元数据保持冻结基线。原GUI启动、RFLOAD/RFALL命令保持。Controller、LLM和新UI未在本次引入。

## 测试内容

原有计算/CAD契约回归；原子替换失败保留旧快照；不可覆盖引用；非法JSON；持久项目历史及终态保护；并发插件记录；活进程/未知进程/PID复用；真实Python退出；CAD有界恢复、归属不明阻断及无关PowerShell保护；真实Windows PowerShell原子写入。

CAD实机包括正常Demo A、恢复后changed、中文路径sample1、10秒超时、逐实体绘图中取消、Python退出码9遗留桥接恢复、已提前关闭的工具图纸及归属标记冲突保护。正常图纸逐实体核对并保存、关闭、只读重开。恢复前后的既有Drawing1保持，未当作绘图或清理目标。

## 测试结果

本机独立 `.venv-demo`：75项工具/状态测试＋87项旧程序回归，共**162项**。包安装不继承系统环境，`pip check`与完整版本检查通过。三案例设计和CAD数据指纹与阶段0.1一致。远端CI状态以本修复PR为准，不把本地测试冒充CI或桌面验收。

| 实机项目 | 结果/本地证据 |
| --- | --- |
| Demo A | 2305实体、356TEXT、218DIM，保存重开通过；`verification/debt-repair/normal/` |
| 超时 | 返回cad_timeout，无artifacts；2305实体的工具图纸恢复关闭，恢复耗时约0.6秒；`timeout/` |
| 绘图中取消 | 部分绘图被终止，最终返回cad_cancelled；系统变量及UNDOCTL恢复，工具图纸关闭；`cancel/`与`cancel-result.json` |
| Python异常退出 | 子进程退出码9，原桥接进程回收、无孤立图纸，状态最终FAILED；`crash-result.json` |
| 恢复后changed | 2334实体、356TEXT、218DIM，保存重开通过；`after-recovery/` |
| 中文路径sample1 | 2346实体、356TEXT、218DIM，保存重开通过；`中文复跑/` |
| 提前关闭图纸 | 会话确认为CLOSED；`document-recovery-result.json` |
| 归属标记不同 | 返回失败、保留测试实体/图纸、保持RECOVERY_REQUIRED；同上 |

实际Esc、连续插入、单步撤销、重做的完整证据沿用阶段0.1；本次补充了新的取消文件路径实机证据，不宣称重新执行了所有人工Esc组合。日志、DWG、完整本机路径和验收脚本均留在Git忽略的`verification/debt-repair/`，公共仓库仅提交可复用源码、测试与匿名结论。

## 发现的问题

Windows PowerShell 5.1将File.Replace的普通$null转为空字符串，导致已有JSON替换失败；改用NullString并新增真实PowerShell回归。绘图已收到取消但命令同步返回时，原验证器可能先报实体不足；命令结束后补做取消/时间检查，明确分类cad_cancelled。

首轮取消验收观察器遇到瞬时文件共享冲突而退出，未触发取消；该轮不计取消通过，修复观察器并复测。图纸恢复验收器缺少COM重试时也不计通过；独立复测已通过。Windows CI Python安装清单缺少3.12.14构建，改用固定uv及Python独立构建，避免默默改用另一补丁版本。

## 技术债务

已修复T02–T05在当前Demo范围的常规路径。AutoCAD硬挂起/桌面重启组合、离线制品哈希及日志归档仍保留，不宣称全部技术债归零。完整边界见 [技术债清单](../technical-debt.md)。

## 当前是否达到阶段验收标准

是，在本报告明确的Demo范围内通过：162项本地自动测试、三案例实机保存重开及异常恢复通过。远端CI另由PR检查记录。未验收的硬挂起场景维持开放，不能删除日志解除隔离。此修复维持统一Tool接口，未来新增工程能力不需要修改通用状态存储。

## 下一阶段建议

进入阶段4自然语言参数解析；阶段7继续补充硬挂起、桌面重启和最终UI稳定性实测。先合并阶段1→2→3→本修复的依赖PR，再按新分支开发；不要覆盖稳定基线。
