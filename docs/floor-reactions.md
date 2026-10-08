# 楼盖反力与直接落梁墙荷载（阶段20）

首版为本地完整JSON/CLI教学工具，不调用DeepSeek、CAD或柱工具。`extract_floor_reactions`标准化旧主梁的8种教学荷载布置；`analyze_floor_wall_reactions`在相同模型上增加固定、非承重、居中直接落梁墙的自重。工具成功只表示`MODEL_ANALYZED`，不表示工程设计PASS。

## 明确支持范围

保留旧三跨主梁、共同恒定EI、支座竖向双向约束且无沉降、转角自由和内支座连续的模型。旧次梁荷载通过分担跨度的教学近似传递，部分主梁自重折到两处三分点，因此本结果不是整层/整楼柱内力。墙坐标必须使用旧**计算支座坐标**，不能直接代入柱网轴坐标。归一EI不用于给出实际挠度。

每墙尺寸与重度、洞口、饰面、附加重量及其来源均须显式提供。固定隔墙按永久荷载分类，依据[GB50009第4章](https://gf.cabr-fire.com/article-13339.htm)和[5.1.1表注6](https://gf.cabr-fire.com/article-13342.htm)。这里的`density_kN_m3`指单位体积重量，单位kN/m³，不是质量密度。工具不替用户选取重度，也不认证其变异系数或资料。

矩形洞口只扣除墙与两侧饰面的面投影面积。净总重加上显式附加重量后沿完整墙段均布，这是**总重量折算均布的教学模型**，不证明偏置洞口或局部附加重量的真实作用位置、过梁传力、局部反力、墙刚度或拱效应。洞口侧面、过梁、门窗等重量须在附加重量和来源中显式记录；空饰面数组/零附加重量是用户声明。

既有G/Q已经分项，不再次乘系数；新增墙标准自重只乘原输入`gamma_g`一次。沿用原8种教学布置不能代替完整现行最不利组合；永久作用有利与不利取值尚未自动展开，依据[GB55001 3.1.7(6)、3.1.13](https://gf.cabr-fire.com/m/article-42692.htm)。`baseline_wall_loads_excluded=true`及来源必须明确提供，属于用户声明，不能证明原资料没有重复计入。

板上墙、次梁上墙、承重墙/剪力墙、偏置墙、可移动隔墙、框架侧移、楼层叠加与柱联动均不支持。所有结果`column_input_ready=false`；加墙结果`floor_design_recheck_required=true`。不得继续使用旧楼盖配筋并解释为新荷载下已通过。

## 本机快速验证（PowerShell）

在本阶段分支仓库根目录运行；Python使用已部署固定环境。每个命令明确选择匿名6×6m模板，保存新楼盖设计引用和请求，再通过原Controller执行一个反力步骤，不生成CAD。

```powershell
& .\.venv-demo\Scripts\python.exe -m examples.floor_reaction_demo --case baseline --output-root .\data\projects\reaction-acceptance
& .\.venv-demo\Scripts\python.exe -m examples.floor_reaction_demo --case wall-opening --output-root .\data\projects\reaction-acceptance
& .\.venv-demo\Scripts\python.exe -m examples.floor_reaction_demo --case wall-cross-support --output-root .\data\projects\reaction-acceptance
```

应返回`success:true`、`status:completed`，仅有一个`analysis`工具调用。其`result_path`指向标准ToolResult。结果有8个pattern，逐组保留基线/墙增量/合计反力，力和力矩平衡精确字符串均为`"0"`。控制值附所有并列控制pattern，不能将各支座独立极值拼成一个共同组合。

洞口案例：墙长4m、高3m、厚0.2m、重度8kN/m³，双面15mm/20kN/m³饰面；1×2m洞口及2kN附加重量。净标准总重24kN，原`gamma_g=1.3`后31.2kN，设计线荷载7.8kN/m。跨支座案例墙段为计算坐标4–8m，无洞口或附加重量，净标准重26.4kN。

生成的`request-floor-….json`包含本机新引用，可以再次直接执行：

```powershell
& .\.venv-demo\Scripts\python.exe -m examples.floor_reactions --request-file .\data\projects\reaction-acceptance\request-floor-实际编号.json --output-root .\data\projects\reaction-acceptance
```

公开`demos/floor-reactions-*.json`的全零引用是占位符，不能直接作为真实工程引用。使用自身工程时替换为**同一output-root中本项目已有完整设计引用**，并填写支座映射、墙参数、全部声明及来源。工具不从文件名推断工程归属，不自动调用设计入口补建引用。

## 结果与引用

数值同时保存显示值`value`和精确有理数`exact`；后续分析只使用精确值。负反力保留。合计出现负反力时标记`support_contact_review_required=true`，只意味着双向模型需另核支座抗拔/脱空，不自动进行仅受压接触分析。墙增量单独为负不必代表合计支座抬起。

新引用`floor-reactions-UUID`保存于`reaction-results/`且不覆盖旧引用。读取核对项目、工具/版本、Schema、完整内容哈希，并从原完整设计输入重新验证跨度/G/Q/8工况及所有旧分段响应，再复算墙分析。修改反力后重新哈希仍会被拒绝。哈希是本机完整性机制，不是资料签名或恶意本地用户隔离。

每次执行新建run与反力引用；旧设计文件字节保持不变。Controller未添加楼盖/墙分支，插件`rc_floor`声明两个单步工作流；CLI通过专业无关本地Envelope解析器和Registry选择预先声明工作流，不运行LLM生成的步骤。

## 分析与独立参考

新的有理数Hermite梁内核不修改旧点荷载求解器。集中力按形函数取值，任意墙段均布按形函数积分，并在跨支座处拆分积分；三个完整跨单元用于支座端部响应，依据[TU Delft梁单元式4.20–4.30与刚度矩阵](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html)。不将墙均布荷载伪装成两个三分点集中力。

实现前冻结的`tests/fixtures/floor_reaction_references.json`来自Astra独立三弯矩法。3×6m/q=10kN/m满布反力为24/66/66/24kN；局部1–5m为448/27、83/3、−46/9、23/27kN；跨支座4–8m为29/27、1016/27、41/27、−2/9kN。测试还核镜像、单跨、原三分点荷载及独立基向量。

旧浮点数据与精确模型的1e−8相对/绝对容差只用于旧格式来源一致性，不用于结构承载力判定。新模型平衡残差严格为零，不能把旧浮点结果称为精确值。
