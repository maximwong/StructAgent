# 阶段19首批冻结契约与参考

用户确认：教学、非抗震、静力、矩形固定截面、对称四根同径角筋、任一主轴单向偏压；完整JSON/CLI，网页/六八筋偏压后续。新增`design_column_eccentric`和`check_column_eccentric`，不改旧工具/Controller。

首批为截面级最终N/M：同一组合内N>0、一个指定轴的M非零、另一M及Vx/Vy显式零。整体P–Δ和杆件P–δ均须已在外部分析处理，提供声明与同一分析/组合来源；M不得已含附加偏心。未处理二阶或已含ea的输入拒绝，不重复增大。lc记录来源及覆盖弯曲平面，不以旧l0/phi代替二阶；不认证原分析、杆件整体平衡或组合完整性。

parameters仅model/combinations。model沿用阶段17section/materials，ties沿用阶段18diameter_mm/spacing_mm/hook_angle_deg/hook_extension_mm；effective_length为lc_mm/source/analysis_id/covers_bending_plane=true；新增bending_axis枚举x/y，scope为purpose=teaching/loading=static/seismic=false/uniaxial_eccentric_compression=true/gamma_Rd=1。Mx绕x取H=h/B=b，My绕y取H=b/B=h，正弯矩压正深度坐标，负号镜像四角。原材料C25/C30/C35/C40/HRB400/HPB300，显式强度须匹配；允许显式fy_tension_MPa=360、Es_MPa=200000。每组combinations沿用阶段17id/actions/source，actions新增M_includes_gamma0=true（与N同组均含重要性系数，缺失/false拒绝），Mx/My改为任意有限数但仅指定轴非零；新增second_order={analysis_id,combination_id,frame_P_Delta_included:true,member_P_delta_included:true,additional_eccentricity_included:false,source}，analysis/combination必须匹配该组与共同有效长度分析。32组上限，源构件/截面一致、组合/记录ID不重复，布尔数值/非有限/额外字段拒绝。

actual沿用阶段18结构但固定bar_count=4、layout=four_corner_bars、crosstie_axes空，三个布尔声明仍必填（空拉筋每层/端部不适用）。直径候选12/14/16/18/20/22/25/28。总As直接附录A四根列，每层As=As'=总量/2，保证对称平衡；不混用独立舍入两根列。旧v1与阶段18政策不修改。几何、总/侧最小配筋率、3%上限、保护层、箍径/箍距及保守钩声明沿用已验证规则，按原实配检查。

依据：[6.2.1/5/6/7/8/17](https://gf.cabr-fire.com/article-12605.htm)、[材料4.2](https://gf.cabr-fire.com/article-12594.htm)、[GB55008 4.4](https://gf.cabr-fire.com/article-39674.htm)。C25–C40用α1=1、β1=.8、εcu=.0033、Es200000、HRB400 fy=fy'=360MPa。ea=max(20,H/30)，M_demand=abs(M_final)*1e6+N*1000*ea。a=c+dt+d/2，h0=H−a。

σs=clip(Esεcu(β1*h0/x−1),−fy',fy)，按6.2.8-1，不混用线性近似或6.2.17-7/8。由N*1000=fc*B*x+fy'*As'−σs*As固定N求x；M_R=fc*B*x*(H/2−x/2)+(fy'+σs)*As*(H/2−a)。不乘0.9phi。只验证2a<=x<=β1H、受拉应变<=.01、N_kN*1000<=fcBH范围；超出标OUTSIDE_SCOPE，不能说成已经证明承载力不足。更小x的6.2.14特殊分支及全截面受压均后续。

受拉屈服分支直接x=N/(fcB)，界限用等价乘积比较，避免ξb舍入误分；否则Fraction精确有理数单调二分最多256轮保持根区间；80位Decimal仅对区间输出定向舍入。容量用混凝土项区间下界加钢筋项下界保守判定，不用误差放宽PASS；需求落在未分辨的容量区间标INDETERMINATE。判定保存十进制区间证据；输出常规中间量为JSON数值。控制组合按本实配M需求/容量，保留并列，不按最大N；OUTSIDE_SCOPE/INDETERMINATE优先显示，不能有一组未确认仍输出全PASS。

设计按固定候选顺序逐组实配检查，首个全部PASS选中；失败保留全部尝试及各组原因，不自动改截面/材料/长度/内力/箍筋。不支持候选不当作通用结构不可能设计。check接受本项目column-eccentric-UUID引用或完整parameters+actual互斥输入，不调用设计重新选筋。新引用不可覆盖，核项目/版本/哈希及逐候选/逐组复算，FAIL停止原声明式工作流。

## 实现前独立参考

共用B300/H400、C30、c35、dt8/s150、钩135/80、lc3000，φ不参与。4Φ20总1256/每层628，a53、h0347、ea20。

|N kN / 最终M kNm|分支|x mm|σs MPa|M_R kNm|扣Nea后的输入M限值|期望|
|---|---|---:|---:|---:|---:|---|
|500 / 125|大偏压|116.5501165501|360|137.329990862470862|127.329990862470862|PASS，首选4Φ20|
|1200 / 100|小偏压|241.4748469790|98.7374100953|124.459053261368321|100.459053261368321|PASS，首选4Φ20|

前候选4Φ18每层508.5，输入M限值分别115.048230862470862、90.470803793745927，均FAIL。旋转B/H与弯矩轴互换、改变M符号应同容量并改变受压面。另H393、4Φ20、h0340、N755.04：x176恰为ξ界限，M_R146.8068，ea20后输入M限值131.706；界限归大偏压，严格等号通过。以上由Astra仅抄规范常数、未导入产品模块独立求解并审查；被测实现不得生成自己的期望。
