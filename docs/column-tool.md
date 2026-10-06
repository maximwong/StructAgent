# 教学理想轴压柱Tool v1

`rc_column`为第二个实际结构计算插件，通过现有本地插件加载器、Registry及通用Controller执行。仅提供`design_column`和`check_column_design`，普通工作流为设计→只读实配校核。无需API或AutoCAD；插件工厂只构建工具对象，不计算或生成状态。柱网页、自然语言解析、CAD及计算书尚未提供。

工程依据与独立验收数据见[column-basis.md](column-basis.md)。范围是教学、非抗震、静力、理想纯轴压的单根固定矩形柱：C25/C30/C35/C40、HRB400纵筋、HPB300单封闭矩形箍、4根等径角筋。PASS仅表示声明的检查通过，不能作为实际框架柱全项设计结论。

## 运行本地工作流

在仓库根目录使用固定独立环境：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.column_workflow --request-file demos/column-short.json
.\.venv-demo\Scripts\python.exe -m examples.column_workflow --request-file demos/column-slender.json
.\.venv-demo\Scripts\python.exe -m examples.column_workflow --tool-only --request-file demos/column-check-fail.json
```

前两例执行设计→校核：短柱选择4Φ16，长柱选择4Φ20。第三例是短柱实配4Φ14，校核返回FAIL、`success=false`及逐项判定，进程退出码1；不会重新选筋。完整工程参数均来自本地JSON Envelope，不推断缺项、不调用云模型。`--tool-only`仍经过Controller，执行应用声明的单步校核。可用`--output-root`指定结果目录；默认`data/projects/`由Git忽略。输出UTF-8 JSON，完整输入、工具结果及状态记录可追溯。例子来源明确为匿名教学假设。

## 输入约定

Envelope必填`project_id`、`tool`、`context`、`parameters`。`context`固定如下，工具不换算单位：

```json
{"unit_system":"mm,kN,kN.m,MPa","design_code":"GB/T 50010-2010(2024);GB 55008-2021"}
```

设计`parameters`只有完整`model`。实配校核接收`model`和`actual`，或者本项目`design_result_ref`；两种输入互斥，不能在引用旁覆写材料、内力或配筋。完整例子见[demos/column-short.json](../demos/column-short.json)及[实配FAIL案例](../demos/column-check-fail.json)。

| model分组 | 必填内容与含义 |
| --- | --- |
| section | `b_mm`、`h_mm`均>=300；`cover_to_outer_tie_mm`是表面至最外箍筋外缘的c |
| effective_length | 用户分析得到的`l0_mm`、非空`source`、`covers_both_principal_axes=true`；l0应为覆盖两个主轴的控制有效长度，不是直接猜取层高 |
| actions | `N_kN>0`是已含gamma0最终设计值；同一组合的`Mx_kN_m=My_kN_m=Vx_kN=Vy_kN=0`；`N_includes_gamma0=true`及非空`combination_source`，后者应写明组合标识、来源及同源声明 |
| materials | `concrete`、`longitudinal_steel=HRB400`、`tie_steel=HPB300`；可选`fc_MPa`、`fy_compression_MPa`、`tie_fy_MPa`必须精确匹配独立等级表，不能覆盖表值 |
| ties | `configuration=single_closed_rectangular`、用户固定的`diameter_mm`、`spacing_mm` |
| scope | `purpose=teaching`、`loading=static`、`seismic=false`、`ideal_axial_compression=true`、`gamma_Rd=1` |

实配`actual`必填`bar_count=4`、`layout=four_corner_bars`、`bar_diameter_mm`，支持12/14/16/18/20/22/25/28。输入数值不能是布尔值、字符串、NaN或Infinity，JSON重复键也拒绝。缺项、材料强度冲突、非零弯矩剪力、l0/min(b,h)>50或c+箍径>50拒绝；不自动补齐参数或更换截面。

## 结果、引用和失败规则

纯函数`design_column(model)`搜索固定候选，仅增加纵筋直径，选择最小全部通过方案。返回`status`、`effective_input`、`selected`、完整`attempts`和选择政策。每个实配报告含`materials`、`basis`、`intermediates`、`actual`、`checks`、`coverage`；失败方案保留全部尝试及判定。

设计Tool只在完整PASS且设计快照成功发布后返回`success=true`和`result.design_result_ref`。引用使用`column-`前缀，不接受客户端路径。快照通过原子且不覆盖的方式发布，文件名、快照引用、结果引用及metadata引用绑定一致。读取校验项目归属、整体校验和、报告校验和、Schema和实际计算语义；逐个复算候选前缀、实配报告和最小PASS选择。即使重新计算校验和，伪造PASS、改动钢筋、中间量或跳过较小候选也会拒绝。校验和用于完整性核对，不是对恶意本机管理员的签名认证。

`check_column_design`读取实际配筋和原完整输入复算，不调用设计入口；直接实配校核同样不重新选筋。工程FAIL返回`success=false`、`status=FAIL`、原实配方案和逐项`column_check_failed`错误；普通Controller立即停止流程。引用损坏、归属不符、读取失败或发布失败返回安全错误消息，不回显本机路径、快照内容或异常文本。

Nu采用毛截面A及四筋表，不计箍筋承载增益。phi含轴压稳定影响；节点间采用下一更高长细比的表值，是插件保守政策。检查还包括总/单侧配筋率、两方向净距与中心距、箍径与间距、纵筋保护层与直径。未覆盖环境/耐久/防火保护层、锚固搭接、节点端部、弯钩完整详图、偏压附加偏心、偏压及框架二阶分析、抗震、疲劳、用户源内力和l0分析。

## 专项验证

```powershell
.\.venv-demo\Scripts\python.exe -m unittest tests.test_column_calculation tests.test_column_tools tests.test_column_workflow tests.test_plugins -v
```

独立参考数据已在实现前提交冻结。专项覆盖严格容量/构造边界、真实实配FAIL不重选筋、引用归属及哈希、重新计算哈希后的语义篡改、重复引用不能覆盖、发布异常阻止成功、流程失败停止、柱与楼盖同时加载、工厂无计算/云/CAD/状态副作用、CLI错误退出码。验收误差只用于参考测试，不放宽工程判定。
