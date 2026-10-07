# 阶段17实施契约：内力来源与多组合

2026-10-07用户授权使用DSH并开始阶段17，阶段16人工检查已确认正常。分支从已通过CI的DSH接入提交57805be建立，依赖PR25/24/23/22；不合并上游PR，不改变冻结版。

范围：保留单组合v1工具、公式、材料表及引用协议。新增`design_column_combinations`和`check_column_combinations`及声明式设计→校核工作流，首轮交付完整JSON/CLI。多组合网页、楼盖反力/墙荷载、偏压/抗剪不混入本阶段；任何组合非零M/V拒绝。所有组合共用固定截面、材料、箍筋、双主轴控制有效长度和四角筋范围。

参数只有`model`与`combinations`。`model`使用v1 MODEL_SCHEMA去掉`actions`；`effective_length`增加必填`analysis_id`。每一组合为：

```json
{
  "combination_id": "ULS-1",
  "actions": {"N_kN":1400,"Mx_kN_m":0,"My_kN_m":0,"Vx_kN":0,"Vy_kN":0,"N_includes_gamma0":true,"combination_source":"匿名教学假设"},
  "source": {"analysis_id":"TEACHING-ANALYSIS-1","member_id":"C1","section_id":"BOTTOM","combination_id":"ULS-1","force_record_id":"ROW-1","description":"同一分析输出记录的完整内力向量","unit_system":"mm,kN,kN.m,MPa","same_force_vector":true}
}
```

1–32组；ID为1–128字符且不含空白，支持中文。组合ID、force_record_id各自唯一。来源组合ID必须与本组一致，analysis_id与共同有效长度analysis_id一致；各组member_id、section_id相同。source绑定完整五分量，显式声明same_force_vector=true；不拼接不同组合极值，不自动猜来源/填零/换算单位。来源校验只能确认声明一致，不能验证外部分析真实性。

DSH负责`tools/column/combination_input.py`及`tests/test_column_combination_input.py`。接口导出COMMON_MODEL_SCHEMA、COMBINATION_SCHEMA、COMBINATION_PARAMETERS_SCHEMA；`validate_combinations(parameters)`验证全部输入，返回None，不修改输入；`compose_model(parameters, combination)`复制model，移除仅用于追溯的effective_length.analysis_id，插入该组合actions，得到完整v1 model。逐组调用既有validate_model，工程错误path映射为parameters.model或parameters.combinations[index].actions，保持ToolValidationError兼容。不得修改既有schemas.py/calculation.py。

GPT负责组合纯函数、独立实配校核、结果语义验证/不可覆盖引用、Tool、Registry/插件/CLI、独立参考和集成测试。每个固定直径候选都逐组执行原check_column，所有检查全部通过才可选；不只提取最大N后丢掉其他组合。不调用design_column来伪造校核。容量控制组按共同容量下的最大原始N精确比较，同值全部列出，顺序随用户输入；与构造项的FAIL分开记录。

独立参考沿用阶段15冻结短柱/细长柱数值：短柱N=1200/1400选择4Φ16，Nu=1418.796；同值两组均控制。细长柱N=900/1170选择4Φ20，Nu=1173.933。4Φ14短柱只在1400组容量FAIL，仍检查1200组；所有候选耗尽保持FAIL。新期望在组合实现前固定，不由被测代码生成。

Astra先只读检查本契约及参考，再检查指定实现提交、修复涉及部分；DSH输出补丁经GPT核对范围和实际测试后整合。交付运行产品与旧楼盖回归、插件共存/加载无执行、Controller零差异、跨项目/哈希重算后的语义篡改、失败停止及CLI复测。新增引用前缀`column-set-`，与v1 `column-`分离，校核保存引用或完整model/combinations/actual互斥。

PASS限于原教学轴压声明检查，不是源分析认可、整体设计或完整工程验收。网页阶段16保持单组合输入，阶段17说明必须明确此入口边界。
