# 四角筋单向偏压柱：阶段19 JSON／CLI

新增 `design_column_eccentric` 与 `check_column_eccentric`，柱插件1.4.0通过原Registry及Controller声明式工作流执行“设计→实配校核”。加载插件仅创建对象，无云调用、计算或文件写入。楼盖、纯轴压柱、4/6/8筋轴压工具与网页继续使用原接口。本阶段不提供偏压网页、CAD、计算书或自然语言解析。

## 使用条件

教学、非抗震、静力，矩形固定截面，对称四根同直径角筋，任选一个主轴的非零弯矩；另一轴弯矩及两方向剪力均显式为零。输入为**同一最终基本组合、同一截面的 N/M**，N、M均已含结构重要性系数。它不是楼盖反力自动传给柱的全结构分析。

最终弯矩必须已由外部分析处理框架P–Δ和杆件P–δ，且**尚未含附加偏心**。每组必填`second_order`来源及两项已处理声明、附加偏心未计入声明，analysis_id/combination_id须与力向量及共同长度来源一致。工具不会验证原分析真实性，也不自行放大未经处理的弯矩。`lc_mm`记录计算长度及来源，不能拿旧轴压工具的l0/φ替代二阶分析。

完整匿名输入见`demos/column-eccentric-large.json`及`column-eccentric-small.json`，不要只填N和M。Envelope必须含project_id、tool、context及parameters。单位为mm、kN、kN.m、MPa，规范字段为`GB/T 50010-2010(2024);GB 55008-2021`。材料只支持C25/C30/C35/C40、HRB400纵筋、HPB300箍筋；显式强度冲突、缺项、布尔数值、非有限数值、额外字段、来源错配、不支持内力会被拒绝。

## 命令行验收

在仓库根目录的PowerShell中，每条命令单独执行。若没有`.venv-demo`，先按`docs/demo-deployment.md`安装固定环境。

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_eccentric --request-file .\demos\column-eccentric-large.json --output-root .\data\projects\eccentric-acceptance
.\.venv-demo\Scripts\python.exe -m examples.column_eccentric --request-file .\demos\column-eccentric-small.json --output-root .\data\projects\eccentric-acceptance
.\.venv-demo\Scripts\python.exe -m examples.column_eccentric --request-file .\demos\column-eccentric-weak-actual.json --tool-only --output-root .\data\projects\eccentric-acceptance
```

前两条应success=true，设计和校核均PASS，实配4Φ20。第三条使用原模型＋实际4Φ18，应success=false、校核FAIL，保留失败逐项记录，不重新选筋。成功返回码0，失败返回码1；第三条退出1是预期结果。

Agent状态在`column-eccentric-agent/<run_id>/`，独立设计快照在`column-eccentric-designs/column-eccentric-<UUID>.json`。引用校核使用同项目Envelope、tool=`check_column_eccentric`、parameters只包含`design_result_ref`并添加`--tool-only`。完整模型＋actual与引用互斥。引用不可覆盖，项目/版本/哈希/全部已发布候选和组合都需通过检查，损坏或外项目引用失败。不要取旧轴压引用或直接修改快照内容。

## 工程依据与数值判定

矩形偏压采用GB/T50010 6.2.17，钢筋应力采用6.2.8-1；6.2.18的I形截面公式不适用。本工具取α1=1、β1=0.8、εcu=0.0033、Es=200000MPa、fy=fy'=360MPa，材料限于C25–C40。附加偏心按6.2.5取ea=max(20,H/30)，需求为abs(M_final)+N*ea。完整公式、来源链接、独立算例与主轴约定见[冻结契约](column-eccentric-contract.md)。

固定N求平衡根，不乘纯轴压0.9φ。只验证`2a<=x<=β1H`、`N_kN*1000<=fcBH`及受拉应变不超过0.01；更小x需6.2.14特殊处理，全深度受压也另行开发。超出范围为`OUTSIDE_SCOPE`，不能解释为已经证明该结构承载力不足。

面积直接采用附录A四根总面积，两层各一半，避免两根面积列的独立舍入打破对称平衡。沿用总/侧最小配筋率、3%插件上限、保护层、间距和箍筋检查；箍钩只支持135度并检查声明长度，未检查实际加工或施工。无可行候选不会改截面或其他用户参数。

数值核心用精确有理数求残差及包围根，最多256次二分；容量计算保存严格保守上下界和精确分数字符串，80位Decimal仅用于上下界定向舍入展示。需求不超过下界才可能PASS，超过上界为FAIL，中间无法分辨为`INDETERMINATE`。不会用显示小数或误差容许值决定PASS；弯矩符号保留，负号只镜像压面。控制组合按本实配的弯矩需求/容量比，不按最大轴力，保存并列。

独立参考在实现前冻结：N500/M125的大偏压MR=137.3299908625；N1200/M100的小偏压MR=124.4590532614。4Φ18两例均不通过。H393/N755.04的界限MR=146.8068、输入M限值131.706，严格等号PASS。额外x200参考N923.26176、输入M124.20880608的真实等号位于有限二分未分辨区间，本实现保守返回INDETERMINATE；略低/略高分别PASS/FAIL。

PASS不包括外部分析、组合完整性、整体平衡、抗震/双向偏压/剪力、耐久防火、锚固搭接、节点端部及完整构造认可。用户必须保留原分析材料；来源字符串一致不是工程真实性认证。
