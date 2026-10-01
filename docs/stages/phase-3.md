# 【阶段3】AutoCAD / RFALL 接入 Tool 系统

验收日期：2026-10-01。实现位于 `feature/floor-cad`，基于阶段2的 `feature/floor-design`；阶段1、2尚未合并时需按PR依赖顺序合并。

## 完成内容

新增 `generate_floor_cad`。通过 FloorCADTool → FloorCADAdapter → Windows STA桥接复用原RFALL路径，完成无AI的设计计算、结果引用保存、参数转换、独立图纸绘制、DWG保存和重开验证。Agent/Registry不需要知道RFALL命令。

旧 `cad_scene.export_drawing` 在独立Python进程运行，保持数据转换和导入隔离。每次出图拥有独立运行编号和目录；完成标记、回执和实体检查必须相符，失败不返回成功图纸。已有用户图纸不作为输出目标。

## 修改文件

`.gitignore` 忽略默认本地工程输出；`tools/floor/__init__.py` 导出CAD工具；`README.md`、`AGENTS.md`、`CONTRIBUTING.md` 更新使用和协作说明；CI步骤名称标明包含CAD契约测试。

## 新增文件

- `tools/floor/cad_tool.py`、`cad_adapter.py`、`cad_bridge.ps1`、`_cad_scene_worker.py`。
- `tools/floor/design_store.py`：最小本地设计结果引用存储。
- `examples/floor_cad.py`：Registry驱动的无AI设计→出图示例。
- `tests/test_floor_cad.py`、`tests/fixtures/cad_baselines.json`。
- `docs/floor-cad-tool.md`、本阶段报告。

运行日志、回执、测试图纸和本机验收脚本保留在忽略目录 `verification/stage3/`，不上传公共仓库。

## 保持不变的旧功能

未修改 `core/`、阶段2设计计算实现或 `legacy/rc_floor/`。原计算公式、材料校验、钢筋长度、图元转换、RFLOAD/RFALL命令和旧GUI启动方式均保持。未接入LLM、Controller或新UI。

## 测试内容

自动测试新增16项：三案例真实数据转换与冻结指纹、中文目录、重复/并发运行隔离、跨项目/无效/损坏引用拒绝、Schema参数校验、失败状态记录、回执编号/重开状态/实体数/DWG存在性校验、进程超时和异常、清理警告。桌面后端在自动测试中模拟，不能据此宣称AutoCAD实机通过。

实机在AutoCAD 2022执行：标准Demo A、changed、sample1、重复Demo A；保存前后逐实体核对类型、图层、线/圆/弧/多段线几何、中文文字、尺寸读数和比例、字体与线型，检查系统变量和撤销组恢复。测试原图纸和预先放置的实体保留。另测未启动、并发占用，以及损坏参数导致绘图失败。

## 测试结果

本地Python 3.12：55项核心/设计/CAD工具测试＋87项原有回归，**142项全部通过**。远端CI执行同一自动测试流程，结果见关联PR检查。

三案例的完整CAD图元JSON及ASCII参数文件与阶段0.1冻结成果完全一致，指纹见 `tests/fixtures/cad_baselines.json`。

| 实机案例 | 实体 | 中文及其他TEXT | DIM | 保存重开 |
| --- | ---: | ---: | ---: | --- |
| Demo A | 2305 | 356 | 218 | 通过 |
| changed | 2334 | 356 | 218 | 通过 |
| sample1 | 2346 | 356 | 218 | 通过 |
| 重复Demo A | 2305 | 356 | 218 | 通过 |

标准与变更案例输出位于本地 `verification/stage3/中文验收/`；连续运行与原实体保留证据位于 `verification/stage3/repeat/` 和 `session-checks-r2.json`。未开启返回 `cad_unavailable`；另一CAD操作持有互斥锁时返回 `cad_busy`；损坏参数返回 `cad_verification_failed`，没有成功artifacts。

## 发现的问题

1. AutoCAD ActiveX尺寸 `Measurement` 已包含标注比例。初版验证器按未缩放几何长度比较，误报“200 expected 400”；独立尺寸对照确认后改为投影长度×比例，旧图元数据和公式不变。
2. Windows默认脚本策略不允许直接执行桥接脚本。沿用旧CAD导出的进程级执行参数，不修改持久安全策略；首次失败记录保留。
3. 初版忙碌验收脚本把交互式画线与后续检查放在同一控制进程，测试时序不可靠。该轮不计通过；分离后连续出图和实体保留通过。并发锁拒绝已实测，不能把它冒充所有交互命令忙碌场景均已覆盖。

## 技术债务

- 超时可返回失败并保留诊断，但不强杀AutoCAD；已提交的CAD命令可能继续运行。挂起会话自动取消/恢复、用户关闭图纸、应用崩溃后的状态协调尚未完整实现。
- 本阶段没有修改旧LISP；撤销/重做/绘图中Esc构造沿用阶段0.1证据，没有把本阶段模拟超时写成完整实机超时验收。
- Store只支持当前设计结果1.0.0，提供项目绑定和意外损坏检测，尚不是通用Project State、权限系统或签名存储。
- 仅验证Windows/AutoCAD 2022；新设备仍需CAD许可、Unicode引擎与脚本信任配置。部署依赖锁定仍待处理。
- 尚无自然语言解析、Agent Controller及Demo UI。

## 当前是否达到阶段验收标准

是。无AI时，Registry调用 `design_floor_system` 后将结果引用交给 `generate_floor_cad`，可生成并回读验证DWG。核心和旧工程代码均保持，命令与文件操作封装在Adapter中。

## 下一阶段建议

阶段4接入云端LLM，先完成自然语言→结构化参数→Schema验证。关键参数缺失时明确返回缺项；继续要求显式使用已确认模板，避免把未确认的梁板几何隐含在解析器中。阶段5再通过Registry建立Controller。
