# 【阶段20】旧楼盖反力标准化与直接落梁墙自重

## 完成内容

新增`extract_floor_reactions`、`analyze_floor_wall_reactions`、独立精确梁内核、旧来源Adapter、不可覆盖结果引用及完整JSON/CLI工作流。保留8工况同源基线/墙增量/总反力、精确平衡、逐支座控制工况和并列；不拼接独立极值作为组合。新增墙标记旧楼盖需重校，所有结果禁止直接作为柱设计内力。

## 修改文件

`plugins/rc_floor/plugin.py`、`plugin.json`（1.1.0，增加两工具及单步工作流）；`tools/floor/reaction_input.py`落实双向支座和忽略墙刚度必填；插件清单与工作流数量测试、README、技术债。未增加原Controller专业分支。

## 新增文件

`tools/floor/reaction_calculation.py`、`reaction_adapter.py`、`reaction_store.py`、`reaction_tools.py`；前置冻结`wall_schema.py`、`reaction_input.py`及计划/独立fixture；`agent/local_parser.py`；`examples/floor_reactions.py`、`floor_reaction_demo.py`；3个匿名JSON案例；`tests/test_floor_reactions.py`；`docs/floor-reactions.md`及本报告。

## 保持不变的旧功能

旧楼盖算法与校核、全部柱工具、旧LISP、Controller核心及冻结`v0.1-demo`保持原实现。旧设计引用文件在新增墙分析前后字节相同。没有改网页；产品验证链路不调用云模型/CAD，也不自动触发柱设计。开发辅助DSH调用单独记录。

## 测试内容

独立三弯矩参考：单跨、三跨满布、三分点点载及3个基向量、非对称局部/跨支座均布与镜像、支座点载；净墙重26.4/22/24/31.2kN；8工况精确叠加与控制；负增量与负合计的区别；异常数值/布尔、墙段与洞口重叠/越界、支座/墙/来源重复、错误坐标/单位、损坏或重哈希来源与结果、外项目、存储失败、原Controller及真实CLI。另执行既有全量与旧楼盖回归。

## 测试结果

初始10项专项通过；全量开始后追加的负反力/存储失败2项单独通过。柱网页/CLI/插件集成48项中47项通过，一项旧工作流数量期望5需调整为7，已修正并在全量确认通过。本机全量423项（421通过、2项可选DSH环境跳过），393.119秒；加上上述追加2项，全部425项均有本机结果。87项旧程序回归通过（5.698秒）。3个匿名CLI案例均返回completed，真实本地Tool结果，不调用模型或CAD；全部3个公开请求Schema验证通过。固定Python3.12.14及11项锁定依赖环境检查通过。最终提交CI与本机结果分开记录。

Astra第一依据关口冻结前修正墙重参考；第二核心关口通过，额外以独立三弯矩法对27组等跨/非等跨、局部均布/跨支座/支座点载及叠加核对，反力、端弯矩和力/矩平衡精确一致；无核心阻断。834a28c交付增量审查发现跨支座样例的0kN与来源文字2kN矛盾，已改明确0kN来源；产品链路无云与开发DSH调用的主语已澄清。Astra核实两项修订及3个实际CLI结果后，第三交付关口通过，未发现其他阻断。最后增量只改案例来源/文档，无须重跑未受影响的核心测试。

## 发现的问题

审计确认旧主梁模型不等于整层柱内力；旧求解器仅点载，因此墙均布不能转成两点载冒称等效。墙重草稿算术已在实现前修正并冻结。阶段19最终CI首次发生旧柱UI/CLI等待超时（其本机对应集成通过）；保留失败并只重试该失败任务，最终状态另核，不能以历史CI通过替代。

## 技术债务

整层/多层传力、全规范最不利组合、局部洞口/过梁传力、承重墙/板上墙、支承接触与刚度、加墙后的楼盖完整重设计/校核、网页/CAD/计算书均不在首版内。DSH预算是每请求输出/任务时间约束，不是累计费用硬上限。详见`technical-debt.md`的R01–R06。

## 当前是否达到阶段验收标准

实现、全部本机测试与三关口独立审查满足首版教学JSON/CLI功能验收；Git提交与CI证据单独核对，最终远端状态以[PR31 Checks](https://github.com/maximwong/StructAgent/pull/31/checks)为准，CI未通过时不宣称Git交付完成。没有网页或CAD人工验收事项。结论仅适用于明确教学模型，不构成整层结构或柱设计批准。

阶段20提交位于[feature/floor-wall-reactions](https://github.com/maximwong/StructAgent/tree/feature/floor-wall-reactions)，[PR31](https://github.com/maximwong/StructAgent/pull/31)依赖阶段19[PR30](https://github.com/maximwong/StructAgent/pull/30)，未自动合并。

## 下一阶段建议

本次任务到阶段20结束。阶段21应另立项锁定楼盖—柱内力映射及整层/组合来源，不能直接将本次各支座极值送给柱工具。

## 多模型交付记录

GPT实现工程核心、来源/引用、集成和验证。DSH任务5ca77c93a35c428197f1b1fbb672b024仅冻结墙Schema（off、120秒、2048输出token每请求），completed、4次请求；input6849/output1067/cacheRead15488/total23404。GPT完整审补丁并修正Schema嵌入层级、ID及布尔类型后采用，DSH编译通过不代替工程测试。不再委派重复核心任务；Astra仅既定工程关口只读审查。
