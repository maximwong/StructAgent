# 【阶段19】四角筋单向偏压 JSON／CLI

## 完成内容

用户确认先完整验证四角筋偏压。新增来源绑定的`design_column_eccentric`与`check_column_eccentric`，固定矩形截面，两主轴任选一个，1–32组最终N/M，逐组大/小偏压实配复算。按四角同径筋候选顺序选首个全部PASS方案，失败保存全部尝试，不改截面、材料、长度、内力或箍筋。

整体及杆件二阶均由外部分析处理，输入须明确N、M已含重要性系数且M未含附加偏心，插件仅加一次Nea。未处理、重复计入或来源错配均拒绝。新增范围不会套用旧轴压φ。

精确有理数平衡与包围根、保守容量区间、严格等号；未分辨边界为INDETERMINATE，范围外为OUTSIDE_SCOPE。按实际弯矩需求/容量控制组合，保留并列；不按最大轴力判断。引用不可覆盖，完整模型＋实际方案与本项目引用两条路径互斥，均不进入设计入口。

柱插件1.4.0只声明实际实现的8个工具，新增设计→校核和独立校核工作流。原Controller和网页绑定不修改；无云/CAD操作。

## 修改文件

- `tools/column/plugin.py`、`plugins/rc_column/plugin.py`、`plugin.json`：声明式注册。
- `tests/test_plugins.py`、`tests/test_column_workflow.py`：能力清单新增两工具。
- `README.md`、`docs/column-roadmap.md`、`docs/technical-debt.md`：入口、范围及债务。

## 新增文件

- `tools/column/eccentric_input.py`、`eccentric_calculation.py`、`eccentric_store.py`、`eccentric_tools.py`。
- `examples/column_eccentric.py`。
- `tests/test_column_eccentric.py`、`tests/fixtures/column_eccentric_references.json`。
- `demos/column-eccentric-large.json`、`column-eccentric-small.json`、`column-eccentric-weak-actual.json`。
- `docs/column-eccentric-contract.md`、`column-eccentric-tool.md`及本报告。

## 保持不变的旧功能

楼盖核心计算/LISP、纯轴压单组合与多组合、阶段18轴压布筋、楼盖及单组合柱网页、Controller核心、依赖锁及v0.1-demo标签保持原内容。开发在独立`feature/column-eccentric`工作树，以PR29的bb8d5c1为基线；原工作区的README/app/UI未提交修改保留，不复制或覆盖。

## 测试内容

实现前冻结大偏压、小偏压、4Φ18前候选及大小偏压交界参考；另独立指定x200核对真实等容量未分辨边界。测试含反号/主轴旋转、严格等号及两侧、精确根和容量区间、控制组合及并列、超范围、箍钩及其它构造失败、候选耗尽、缺参/布尔/非有限/材料冲突、来源与二阶声明、引用伪造/删候选/外项目、实配弱化、设计入口禁止调用、原Controller失败停止及CLI严格JSON。

## 测试结果

- 固定环境Python3.12.14及锁定11包检查通过。
- 本机完整主测试411项通过，2项可选DSH生命周期测试跳过；旧楼盖87项通过。
- 最后引用验证修复及新增数值不确定边界后，42项受影响的柱偏压/Controller/插件专项全部通过。没有重复未受修改影响的旧楼盖全量；最终CI负责最新提交全量。
- 三个公开匿名JSON经实际CLI运行：大/小偏压完成设计→校核且4Φ20/PASS；弱化4Φ18只校核且FAIL。完整状态及快照保留于本机忽略的verification目录，不提交公开仓库。
- 未运行云模型、AutoCAD或浏览器，本阶段无这些入口，不将旧验收冒充新增功能验收。命令行验收步骤见[使用说明](../column-eccentric-tool.md)。

## 发现的问题

引用完整性验证最初调用设计入口，独立审查与GPT均定位；已改为只复核发布的候选前缀和实际方案。测试把设计入口改为抛错，引用和直接实配均正常复核，问题关闭。

首轮契约未明确M已含重要性系数，依据审查补齐必填`M_includes_gamma0=true`；缺失/false拒绝。

## 多模型记录

- GPT负责工程契约、精确求解、工具集成、独立测试、文档与Git交付。
- DSH任务`7cef841a97a94e7d944eaf95b08bdf6f`：基线2e26b90，只授权输入模块，reasoning_effort=off、300秒/每请求4096输出token。终态timed_out，无正式changes.patch；保留失败，不写成完成。GPT完整检查工作副本输入骨架后采用其中部分并修正lc/内力字段及重要性声明，专项验证通过；未继续重复调用。
- DSH可得usage为input19033/output8758/cacheRead459392/cacheWrite0/total487183，是多请求累计token证据，不是余额不足或人民币账单。当前每请求上限不等于任务累计费用上限，本次不能宣称节省额度。
- Astra依据关口：官方公式原图、材料/最小配筋、独立参考及单位；补齐M声明后通过。
- Astra实现关口：只读审查及独立200位二次解对照C25/C30/C35/C40的小偏压根/容量区间，引用禁止设计探针及混合PASS/OUTSIDE_SCOPE验证；发现的设计入口问题修复后无未解决阻断项。

## 技术债务

外部二阶/组合与来源未认证，lc不自动求得；特殊小x与全深度受压、双向及六八筋偏压、抗剪抗震、完整构造另立依据。偏压网页、自然语言、CAD和报告未开发。数值不可确认保留INDETERMINATE。DSH累计费用/请求数量硬上限尚未实施。本阶段不关闭上述边界。

## 当前是否达到阶段验收标准

代码、独立参考、专项与CLI已满足用户确认的教学非抗震静力四角筋截面范围；交付关口需以最终提交CI和Astra复核为准。不是完整工程柱设计或外部分析认证。Git交付后最终证据追加下方，不自动合并依赖PR或移入冻结版。

## 下一阶段建议

按原路线进入阶段20上游反力与荷载来源；先锁定传力/墙荷载边界及独立平衡参考。阶段19的二阶最终N/M仍须由外部分析提供，不能直接把纯楼盖反力当成偏压柱的完整输入。用户验收阶段19后再启动。
