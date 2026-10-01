# 【阶段4】云端自然语言参数解析

日期：2026-10-02。交付范围为明确选择办公楼Demo模板后的五参数提取、验证及错误处理。

## 完成内容

- 本机DeepSeek配置及示例占位文件；官方HTTPS接口、禁止重定向、隔离HTTP进程和45秒总时限，无新依赖。
- LLM输出严格JSON → 响应Schema → 独立来源/单位比对 → Tool输入Schema → 标准Envelope。解析阶段不执行工具，失败不返回可执行Envelope。
- 模板必须显式选择；缺项不猜测，未知数值/文字要求不丢弃。梁纵筋HRB400、板筋/箍筋HPB300的组合保持原约束。
- 通用解析器与专业语言Profile分离，新工具可由组合入口注册；未提前实现Controller、UI或复杂Agent决策。

## 修改文件

`README.md`、`AGENTS.md`、`docs/technical-debt.md`。更新当前阶段、接入方法、协作规则及待验证边界。

## 新增文件

`.env.example`、`config.py`；`llm/__init__.py`、`gateway.py`、`_deepseek_worker.py`、`json_utils.py`；`agent/__init__.py`、`parameter_parser.py`；`tools/floor/language_profile.py`；`examples/parse_request.py`；`tests/test_deepseek_gateway.py`、`test_language_parser.py`；`docs/deepseek-integration.md`及本报告。

本地 `.env` 与 `verification/phase-4/` 被Git忽略，不是公共交付文件，不含在PR中。

## 保持不变的旧功能

楼板/次梁/主梁公式、配筋长度、已有校核、旧GUI、设计与CAD Adapter、RFLOAD/RFALL、恢复机制及依赖锁定均未改动。Agent层不引入具体脚本或AutoLISP命令。

## 测试内容

- 新增28项：合法组合、混合长度单位、kPa等价单位、大小写、缺失五项参数、必须选择模板、不支持材料、负值/零跨度、未知要求/歧义；模型布尔值/非有限值、伪造值、换算错误、额外字段及错误工具拒绝。
- 严格JSON：重复字段、NaN/Infinity/数值溢出、数组/空/Markdown/截断；配置及密钥隐藏；HTTP鉴权/余额/限流/5xx/重定向/连接错误；真实停滞工作进程的总超时终止。
- 新注册测试查询Tool/Profile可解析，通用解析器不修改；解析过程不执行Tool。
- 全部原有核心/CAD/状态测试和87项旧程序回归；解析后显式Registry调用的Demo完整结果与冻结哈希一致。
- 真实DeepSeek flash：Demo A 6m×6m/C30/2.0；Demo B 5.4m×6m/C35/2.5，梁纵筋均HRB400。两例均解析、校验并完成本地设计。缺活荷载/板厚变更在本地拦截，不向API提交。

## 测试结果

本机103项根目录测试 + 87项旧程序回归 = **190项通过**。真实两例API解析及设计成功；Demo A完整旧结果SHA256为 `2df9a0a4039145d7eeed5b48f71d1aa9fd9375122dd5fa5b46fc5edc32971bf4`，与阶段0基线一致。最终两请求各约600个token，未记录密钥/请求头。

日志、成功Envelope、设计ToolResult及最初失败对照保存在本机 `verification/phase-4/`。API故障码使用模拟HTTP验证，不能当作实际余额不足/限流/断网实测。本阶段没有重跑AutoCAD实机测试；既有CAD代码未改，原CAD自动回归通过。

## 发现的问题

- 初始提示同时展示完整执行Schema与提取Schema，真实模型有时重复输出input_mode/template_id。校验器成功拦截；已改为唯一的LLM响应Schema，模板/项目字段由应用注入，最终真实两例复验通过。
- 7.2m×6m模板次梁间距2400mm，旧引擎按其单向板长短跨比限制拒绝设计。这是保留的适用范围，解析ready不代表结构设计合格。对应失败证据保留，未修改公式或放宽限制。

## 技术债务

仍保留T06–T08；新增T09记录有限中文表达与真实云服务故障覆盖限制。完整explicit模型自然语言生成、多轮补参、复杂语言/模型评估、桌面取消及更多云服务故障实测继续按Demo优先级安排。

## 当前是否达到阶段验收标准

**达到已声明的Demo模板范围阶段4验收标准**：真实云模型提取标准参数，经严格JSON、Schema及来源验证后可交给Tool；缺项明确反馈，非法结果不能进入计算。尚未完成自动Controller串联和一句话自动出图，不标记阶段5/6完成。

## 下一阶段建议

进入阶段5：以Registry与通用状态驱动解析→设计→CAD工作流，在配置中声明工具依赖/参数绑定；Controller不导入楼盖脚本或CAD命令，任一步失败停止后续执行并记录状态。
