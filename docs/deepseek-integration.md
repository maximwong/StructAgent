# DeepSeek接入与工程参数解析

阶段4只做自然语言到标准Envelope。模型不能执行设计、绘图、文件命令或改变工程模板；应用随后必须检查解析状态，设计工具仍负责适用范围及既有验算。

## 每台设备的本地配置

先按 [固定环境部署](demo-deployment.md) 建立Python 3.12.14环境。本次使用标准库HTTP请求，无需新增SDK或修改依赖锁定。

```powershell
Copy-Item .env.example .env
```

用本机编辑器打开 `.env`，将 `DEEPSEEK_API_KEY` 占位符替换为自己的密钥。已有配置时直接编辑，不用上述命令覆盖。配置默认官方地址 `https://api.deepseek.com`、模型 `deepseek-flash`、整个调用45秒上限；允许 `deepseek-v4-pro`，本阶段只实测flash。环境变量优先于仓库根目录 `.env`，不扫描其他目录。

`.env`、工程产物及本地验证日志被Git忽略；`.env.example`只有占位符。每台设备独立设置自己的密钥，不使用GitHub Secrets分发本地密钥，不在公共CI调用付费接口。接口拒绝其他地址和HTTP重定向，密钥通过工作进程stdin传递，不放在进程命令行。错误不携带响应原文、请求头或密钥；配置对象的repr隐藏密钥。

当前接口、模型及JSON模式依据 [官方Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)。请求为非流式、非思考模式、JSON Object输出，提示中给出唯一响应Schema；仍在本地拒绝截断、空响应、重复字段、非对象和非有限数值。

## 运行

以下 `python` 指独立环境的解释器，Windows也可直接写 `.venv-demo\Scripts\python.exe`。

```powershell
python -m examples.parse_request --template office_floor_demo_v1 --text "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"
```

也可以把要求保存为UTF-8文本，再使用 `--text-file request.txt`。加入 `--output data/projects/demo/parse-result.json` 可独占保存JSON；已有输出文件不会被覆盖。解析成功退出码0，缺项/冲突/API失败等退出码1。命令不执行设计或CAD。

```json
{
  "status": "ready",
  "envelope": {
    "project_id": "CSU-DEMO-001",
    "tool": "design_floor_system",
    "context": {"unit_system": "SI", "design_code": "GB"},
    "parameters": {
      "input_mode": "template", "template_id": "office_floor_demo_v1",
      "span_x": 6000, "span_y": 6000,
      "concrete": "C30", "steel": "HRB400", "live_load": 2.0
    }
  },
  "errors": [], "missing_fields": [], "metadata": {}
}
```

`ready`仅代表来源、单位及输入契约通过，不等于结构设计合格。后续只能将ready中的Envelope交给Registry，再检查ToolResult.success。没有参数或出错时 `envelope` 为null，不继续调用工具。

## 当前语言范围与模板边界

必须显式选择 `office_floor_demo_v1`，其余构造及支承/恒载沿用 [已确认模板](floor-design-tool.md)。五项关键值不默认、不猜测：

| 字段 | 明确输入 | 标准值 |
| --- | --- | --- |
| span_x / span_y | 一组柱网，如6m×6m、6×6m、5400mm×6000mm、5.4米×6米 | 第一项主梁轴跨，第二项次梁轴跨，均mm |
| concrete | C25 / C30 / C35 / C40 | 原等级大写 |
| steel | 梁纵筋HRB400；已选模板中单独HRB400也明确指梁纵筋 | HRB400；板筋/箍筋保留HPB300 |
| live_load | “活荷载2.0kN/m²”，也接受kN/m2、kN/m^2、kPa | kN/m² |

阶段6.1取消有限词汇白名单。输入措辞、顺序、礼貌用语、换行、中英文及中文数字先由模型理解；不要求用户套固定句式。例如“麻烦帮我算一下，主梁方向跨6米，次梁方向也是6米，混凝土C30、梁纵筋HRB400，活载按每平方米2.8千牛考虑”可解析。长度原文支持m/mm/cm、米/毫米/厘米及对应英文，荷载支持kN/m²等写法、kPa和中文千牛每平方米。

模型必须返回唯一Schema中的`tool`、`parameters`、`evidence`、`clarifications`。五个参数都要有键，未给出/不明确时为null；每个明确值有连续逐字原文quote及index。跨度成对时index为0/1，单独长度/等级/荷载为0。本地校验引用确实出现在原文中，独立换算数值及单位并核对材料等级，再验证Tool输入；ready结果的source_evidence保留已校验依据。缺参不使用模板/常识补值，无单位不猜测。已注册工具或底层命令不能由模型改变。

模型同时检查完整语义中的额外工程要求、歧义、材料角色与模板变化，逐项返回带原文quote的澄清。本地还有直接命令/明确材料角色冲突检查。正常聊天修饰语和出图请求无需澄清；改变板厚/截面/跨数/支承、双向板、基础等仍不在此模板能力内。语义归属和额外要求识别依赖模型，不能宣称对无限表达完全正确；原文数量/单位验证及结构计算校核继续保留。新措辞不需要扩充白名单，实际误解应作为语义回归案例处理。

与旧解析流程不同，缺参、不支持材料等有效文字请求现在也先调用API再校验，有一次解析费用；不自动重试。历史 [口语前缀修复报告](stages/phase-6-prefix-fix.md) 保留，当前行为以 [阶段6.1报告](stages/phase-6.1.md) 为准。

模板次梁间距为span_x/3。试验7.2m×6m时可解析出参数，但旧引擎按其单向板长短跨比限制返回design_rejected；不通过改公式或静默改变跨度规避。完整工程参数仍可直接使用旧设计工具的explicit入口，尚未开放给LLM生成。

## 返回状态与接口故障

| 状态 | 含义及下一步 |
| --- | --- |
| needs_input | 缺少模板/必要参数、歧义或模板外要求；查看missing_fields和errors.path，补充要求后重试 |
| invalid_input | 请求类型/长度错误，或模型提取后发现不支持材料/数值范围错误；改正输入 |
| invalid_output | 模型JSON的Schema或来源数值不匹配；本次结果不执行，人工检查后重新请求 |
| error | API/配置/格式失败；按code处理，不认为设计完成 |
| ready | 已校验的Envelope；可进入后续设计流程，仍需检查工具结果 |

API错误包括 `api_authentication_failed`、`api_balance_insufficient`、`api_rate_limited`、`api_unavailable`、`api_connection_failed`、`api_timeout`、`api_incomplete_response` 和 `api_invalid_json`。整个请求由独立进程执行，超时终止并等待该HTTP工作进程；不涉及AutoCAD。无自动重试，避免重复计费或无限等待。

阶段5.1的安全诊断附在ParseResult.metadata：model、elapsed_seconds、request_stage及已收到的http_status/数值usage。请求阶段为opening_response、reading_body、decoding_response或completed；没有阶段消息时为worker。总时限中断也保留最后阶段。诊断不包含请求头、密钥、原始响应或未知元数据；opening_response不区分DNS/TLS/云服务等待，不能凭它认定外部故障根因。URLError封装的socket超时同样返回api_timeout。

已确认的“板筋及箍筋保留HPB300”可以通过；混凝土与钢筋等级写反时返回material_assignment_conflict并停止设计/CAD。澄清属于needs_input，用户按具体提示补充后重新请求。

## 扩展与验证

通用 `ParameterParser` 只依赖Registry、工具描述/输入校验、Gateway和 `LanguageProfile`。工程插件提供字段Schema、固定参数和context：`inspect(text)`可预检查或返回None将理解交给模型，`response_schema()`声明响应，`resolve(text, proposal, observed)`核验并返回参数或澄清，`source_evidence(proposal)`输出审核依据。旧inspect预检查接口及默认两字段响应保留兼容，第二个查询工具测试继续通过。解析器和Controller不导入专业Adapter/旧引擎，也不按floor/wall/foundation写分支。

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

自动测试只使用假凭据和模拟HTTP，不连接云服务。真实调用和设计基线证据只在本机 `verification/phase-4/`，不提交到公共仓库。阶段验收及故障覆盖限制见 [阶段4报告](stages/phase-4.md)。

当前语义验收可运行`python -m examples.language_acceptance`，12个案例定义在`demos/language_cases.json`，分别检查8种正常表述和4项预期澄清；这是实际API调用，默认结果在`data/projects/language-acceptance/`，不执行设计/CAD。本次本机证据在`verification/semantic-language/`，不提交公共仓库。
