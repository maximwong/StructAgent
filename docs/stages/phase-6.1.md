# 【阶段6.1：自然语言语义理解】

完成内容：移除楼盖词汇白名单和固定句式入口。正常文字先由DeepSeek理解，提取五项参数、连续逐字原文依据和需要澄清的工程要求；本地核对来源、数值/单位、材料、字段Schema及Tool契约。缺参/歧义/能力范围问题给用户具体澄清，不默认猜值。保留ready的source_evidence供后续UI审核。

修改文件：`agent/parameter_parser.py`、`tools/floor/language_profile.py`、解析/Controller/Demo验收测试，`AGENTS.md`、`README.md`、`docs/deepseek-integration.md`、`docs/sentence-demo.md`、`docs/technical-debt.md`。

新增文件：`tools/floor/source_evidence.py`、`demos/language_cases.json`、`examples/language_acceptance.py`、`tests/semantic_fixtures.py`、`tests/test_source_evidence.py`、`tests/__init__.py`及本报告。

保持不变的旧功能：楼盖计算公式、已选模板、Tool/Registry/ToolResult、通用Controller、CAD Adapter、AutoLISP、原GUI、依赖锁定。LanguageProfile默认的inspect预检查与两字段模型响应仍兼容，第二个专业查询工具无需改Controller。

测试内容：口语/换序/换行/中英文/中文数字、分方向描述、共享单位、小数、m/mm/cm及中文单位；拒绝模型编造引用/数值、错误换算/轴序、布尔/非有限值、未知键/工具、缺单位默认、材料角色冲突及底层命令。缺参、矛盾及模板外要求转澄清；真实设计保持旧基线。完整Demo模拟验收也使用新语义协议，模拟CAD明确标注。

测试结果：核心173项、旧程序87项，共260项通过。真实DeepSeek的12个固定语言案例全部符合预期：8项ready、4项needs_input；响应2.297–3.719秒。真实自由措辞“主梁方向跨6米，次梁方向也是6米……活载按每平方米2.8千牛考虑”完成解析、设计及AutoCAD绘图，success=true/status=completed；DWG保存重开核对2315实体、356文字、218尺寸，用户Drawing1.dwg保留，系统变量一致，工具文档已关闭。证据仅在本机Git忽略的`verification/semantic-language/`。

发现的问题：原实现用局部正则加有限词汇白名单模拟完整语义，普通修饰或换序容易误拒绝；仅补“来一个”无法解决根因。当前将语义理解交给模型，工程数据验证留在本地专业插件。

技术债务：无法承诺无限自然语言都理解正确；参数的语义角色和额外工程要求识别仍依赖模型，原文量值验证并不证明完整语义绝无遗漏。扩充实际误解案例，UI显示参数及依据供核对。复杂纠正、多方案、非常规单位/符号可能仍需澄清；网络/API格式失败仍停止，禁止自动重试。缺参/不支持材料现在也会调用一次模型，改变API次数；当前完整两轮带超时探针为10次，旧阶段6的8次记录保留为历史结果。未重复两轮实机压力测试，CAD代码未改动；T06/T07等仍保留。

当前是否达到阶段验收标准：固定措辞误拒绝的问题已关闭，12项真实语言契约与一次自由措辞端到端验证通过。整个Demo尚未完成UI及正式冻结；不把模型/API故障或真实工程不适用视为可忽略事项。

下一阶段建议：阶段7显示参数/原文依据及澄清提示，继续重复实机验收和收集用户表达；保持Tool/Plugin接口，避免重新引入措辞白名单。
