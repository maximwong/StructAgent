# 阶段20：旧反力标准化与直接落梁墙荷载

用户授权持续开发至阶段20完成；首版为教学JSON/CLI，不自动进入21。根据既有路线，支持固定、非承重、居中直接落在旧三跨主梁模型上的墙，独立附加自重分析；不改旧计算、Controller、LISP或v0.1-demo。公开交付依赖阶段19 PR30。

## 审计结论

`legacy/rc_floor/beam_solver.py`已有常EI连续梁刚度法，支座只固定竖向位移，跨内两个三分点集中荷载；每跨活载开关，共8种。`legacy_core.run`将次梁线荷载乘分担跨度近似传给主梁，并将部分主梁自重折为集中力。该模型不是逐次梁真实支座传力，也不包含直接支座剩余自重、柱墙自重或整层/整楼组合。原报告已有此限制。实际计算跨度与柱网轴跨度不同，不得把墙坐标默认为轴网。

旧求解器不支持跨内均布荷载。新增独立分析内核只扩展这一缺口，保留原engine及结果；标准化时先核原输入对应的跨度/G/Q以及8工况反力。不得只取各支座独立极值拼成同一内力组合。

## 工具与契约

- `extract_floor_reactions`：读取本项目完整旧floor设计引用，核跨度、荷载及8工况；用户显式提供支座ID映射和来源，输出逐工况支座反力与控制工况。
- `analyze_floor_wall_reactions`：相同引用/映射，增加墙数组；读取旧基线、计算明确等效均布墙自重，逐工况输出基线、墙增量及合计反力，保留同一pattern和来源。
- 两者只经Registry/Plugin及原Controller调用，新增独立单步工作流；CLI完整JSON，不云解析/网页/CAD/报告。新增不可覆盖`floor-reactions-UUID`引用与项目/版本/内容/来源验证，供后续21显式读取，不自动调用柱工具。

parameters共同字段为`design_result_ref`、`beam_binding`、`scope`，墙工具另加`walls`。beam_binding={member_id,support_ids（4个唯一ID）,coordinate_system:"legacy_main_beam_calculation_supports_mm",source}。scope={purpose:"teaching",beam_model:"legacy_main_beam_constant_EI",baseline_wall_loads_excluded:true,baseline_exclusion_source（必填）,global_frame_analysis:false}。Envelope沿用楼盖context，参数长度mm、密度kN/m3、力kN、分析内部长度m。基线排除声明不是原工程资料认证。

每墙必填：wall_id、member_id、start_mm/end_mm、height_mm、thickness_mm、density_kN_m3；fixed=true、non_load_bearing=true、direct_on_beam=true、centred_on_beam=true、weight_basis="characteristic"、load_model="uniform_equivalent_over_wall_length"；openings、finishes、additional_weight_kN（显式0可）、source。source={load_record_id,description,geometry_source,density_source,finish_source,additional_weight_source}，所有来源非空。墙数1–8，ID及load_record_id唯一，member_id匹配binding；墙区间在计算支座坐标总长内，端点允许，墙区间不重叠，可相接；不得静默按另一轴网坐标定位。

openings为0–16个矩形={opening_id,x_local_mm,bottom_mm,width_mm,height_mm}，坐标相对墙左下角，尺寸正值、坐标非负、位于墙内、不得相互面积重叠；净面积必须正。finishes为0–2项={side:"left"|"right",thickness_mm,density_kN_m3}，侧唯一、厚/密度正值；空数组明确表示无饰面。未建模洞口侧面/过梁/门窗等质量由additional_weight_kN和来源显式提供，非负；不会猜构件质量。洞口仅扣除墙及两面饰面的面投影面积，不分析局部过梁传力或洞口引起的刚度/拱效应。用户须明确采用等效均布，而非声称真实局部支承分布。

墙特征总重`Wk = (L*H-sum(opening area))*(t*density+sum(finish thickness*density)) + additional_weight`（先转换m），`qk=Wk/L`；设计附加线荷载沿用本设计输入gamma_g一次，全部8工况同样计入。既有G/Q已是原组合分项后的集中力，不再二次乘分项系数。固定墙按永久荷载分类，不支持可移动隔墙。原基线组合不自动升级为全规范组合，γ0及全层传力未认证，结果`column_input_ready=false`。

成功表示所声明模型分析完成，不是楼盖/柱设计PASS。有墙时`floor_design_recheck_required=true`，不覆盖旧设计、不把旧配筋视为新荷载下通过。不修改CAD/报告。板上墙、次梁上墙、承重墙/剪力墙共同受力、支承刚度、楼层叠加及阶段21楼盖—柱联动均排除。

## 分析与独立验证

采用Euler–Bernoulli三跨、同一常EI、支座竖向零位移/自由转角模型。每完整跨一个Hermite梁单元，三分点集中力用形函数N(x)的精确一致荷载，墙任意区间均布用积分N(x)q，不等分成三分点集中力。归一EI=1只用于反力，不输出有物理意义的绝对位移。Fraction精确解4个支座转角，全局力及力矩残差应严格0；JSON显示数值与精确分数字符串并存，负反力保留并提醒支座抗拔未验证。

基线核查：本地严格输入校验；从输入独立复核原三跨计算跨度、G/Q表达式（保留教学近似）；原8工况pattern唯一完整、每组四个反力/残差/跨度一致。与精确反力比较只用固定1e-8相对/绝对容差核旧浮点格式；该容差不用于工程承载力PASS。异常、引用错配、非有限、布尔数值、重复/重叠、额外字段、单位或范围错误全部拒绝。

实现前冻结独立解析/三弯矩参考，Astra只读核对；至少单跨满布、三跨满布、仅第一跨局部段、第三点旧力、镜像、跨支座墙段及净墙重。测试不调用被测实现生成期望。再测试旧8工况回归、平衡、来源/支座/洞口/饰面/重复计入、旧引用不变、逐工况控制/并列、负反力、损坏/伪造/外项目引用、原Controller和柱/楼盖插件共存。

主要依据：[GB50009永久荷载](https://gf.cabr-fire.com/article-13339.htm)、[GB50009 5.1固定隔墙及楼面活荷载区分](https://gf.cabr-fire.com/article-13342.htm)、[Delft Hermite梁刚度与一致荷载公式](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html)。容重与自重由用户明示来源，不内置猜测表值。旧gamma_g/gamma_q只按原教学模型继承，不宣称完成现行全组合审核。

## 分工与交付

GPT负责荷载/来源工程契约、精确分析核心、旧Adapter、引用/工具/插件/CLI集成和独立验证；DSH仅冻结纯Schema小文件，短任务、明确可用解释器，避免阶段19反复尝试的消耗；Astra按依据参考、核心实现和最终交付三关口只读审查。提交源码、匿名案例、独立期望、使用说明、技术债和阶段报告，回归/CI通过后交付依赖PR30的PR，不自动合并。

