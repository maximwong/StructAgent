# 阶段12：独立楼盖计算书 Tool

日期：2026-10-04。基于阶段11提交`bfccb88`，分支`feature/floor-report-tool`；PR目标`feature/bounded-redesign`，依赖阶段11 PR #19。此阶段交付DOCX工具与显式CLI，未发布v0.2正式版。

## 完成内容

- 新增`generate_floor_report`/`1.0.0`，仅接收同一项目的设计引用及可选完整PASS调整编号；报告前通过Registry重新只读Check。
- 复用旧图表和DOCX生成器，保留计算过程、公式代入、钢筋长度、参数和原适用范围；附完整逐项校核依据、实际值、限值、来源与未覆盖项目。
- 可附真实调整历史，核对逐轮输入、诊断、授权下一候选和最终引用；不执行历史工具、不续跑残留记录。
- 隔离worker禁止重新设计或选筋。每次独立输出目录，核对DOCX完整性、计数和哈希，成功回执最后发布；超时、坏协议、坏引用或发布失败不返回成功。
- 专业插件声明普通/受限报告流程，可显式在报告成功后追加一次CAD；Controller核心保持通用。

## 修改文件

`tools/floor/plugin.py`、`README.md`、`AGENTS.md`、`CONTRIBUTING.md`、`docs/technical-debt.md`。

## 新增文件

`tools/floor/report_tool.py`、`report_adapter.py`、`_report_worker.py`、`report_builder.py`、`report_history.py`；`examples/floor_report.py`、`tests/test_floor_report.py`、`docs/floor-report-tool.md`及本报告。生成DOCX、PDF验收副本、图片与日志只保留在被忽略的本机验证目录。

## 保持不变的旧功能

旧引擎、公式、材料与构造范围、选筋、LISP、Design/Check/CAD工具、Controller、普通UI、云解析、依赖锁及既有期望基线未改动。冻结`v0.1-demo`仍指向`00c41e0119102ecc7f22cb19440f7c7020622c17`。默认网页不会自动生成报告或调整尺寸。

## 测试内容

11项新测试覆盖原样例/changed/Demo A真实设计与报告、只读保护、重复输出、项目归属与校验和、减筋FAIL、损坏Check及历史、worker超时/协议/文件、回执发布失败、通用绑定及报告失败阻止CAD。自动CAD后端为明确模拟，工程计算、Check与DOCX生成真实。

本机通过CLI执行原Controller完整报告流程；另读取阶段10/11已保存方案生成普通报告及三轮调整附录。渲染工具因本机无LibreOffice不能完成，改用已有Word脚本仅更新独立副本的目录并导出PDF/PNG，逐页按原分辨率检查全部页面，未修改正式DOCX。

## 测试结果

本机248项项目测试、87项旧程序测试通过，共335项；最后目录样式和调整中文说明修改后再次运行11项针对测试全部通过。公共CI另核验最终提交，状态见PR检查。

CLI运行`d4da35562a814a9fba028799ac70389a`成功，parse/design/check/report均completed，不调用CAD或云API。

普通报告`report-65898bfe45ea4c309a5b32a12223173f`对应180/180项校核，788段落、29表、30图，Word副本61页；受限报告`report-d8d3649ad1d54b93bd8791bde6587c26`对应182/182项校核，806段落、29表、30图，副本62页，记录主梁宽100→125→150mm的三轮实际过程。共123页逐页视觉检查通过，未见文字/图表裁切或重叠。

正式DOCX SHA256分别为`70b472ebae965d65d054701e98aeeeff8c55c52dd1b2f5db4ca0577da314148a`、`12c945cd5c98b6b129905fd5ed3b08d388bf2eb2bf22d2e4b4581bf623f1e419`；渲染后仍一致。报告回执、依据及计数另核对。阶段10/11既有产物按已存哈希复核；首次CAD未开启的失败记录保留，未重新出图或改写历史。

## 发现的问题

旧`workflow.generate`同时重新计算并生成CAD，不能直接当作报告入口；现仅复用已存结果的图表/build_docx。新增附录导致目录多出一页，调整新报告的Word内置目录样式后两类报告均为单页目录；旧报告实现未改动。生成成功必须以文件及回执共同完整为准，不能仅依赖worker成功文本。

## 技术债务

正式PDF、网页打开/下载入口、报告失败产物自动清理未接入；目录与页码依赖Word更新域，不把验收PDF副本称为Tool正式产物。两个样例视觉通过不保证所有输入的版面。报告/历史哈希用于追溯，不是数字签名。worker60秒与Check30秒分别限时，不保证整个调用硬实时60秒。

独立内力、全项规范审查、循环日志恢复与总预算、专业结构化失败码、CAD硬故障、第二台设备与真实云异常等原技术债继续保留，见[技术债清单](../technical-debt.md)。

## 当前是否达到阶段验收标准

达到本阶段独立DOCX工具、只读校核、普通及完整PASS调整附录、通用Controller流程和本机版面验收范围。报告后一次CAD仅由模拟验证绑定与停止规则；此前真实CAD证据保留，不重复计作本阶段实机报告→CAD验收。尚无网页计算书按钮和正式PDF导出。

## 下一阶段建议

先审查依赖PR，再将计算书打开/下载接入现有网页，复用相同Tool和项目归属规则；随后推进插件发现及第二种专业工具验证。正式PDF与工程范围扩展分别明确验收，不改冻结Demo。

使用方法见[计算书工具说明](../floor-report-tool.md)。
