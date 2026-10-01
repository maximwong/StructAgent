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

局部数值/材料识别独立检查模型提取结果。未知数字或文字约束、多个柱网/荷载/等级、无单位、双向板、板厚/截面/跨数变化、板筋或箍筋HRB400等均返回待补充/纠正，不忽略约束。当前使用有限中文词汇及上述表达；复杂叙述、英文、多方案、自由推理不在验收范围。不要把整个模板或JSON放进自然语言要求。

模板次梁间距为span_x/3。试验7.2m×6m时可解析出参数，但旧引擎按其单向板长短跨比限制返回design_rejected；不通过改公式或静默改变跨度规避。完整工程参数仍可直接使用旧设计工具的explicit入口，尚未开放给LLM生成。

## 返回状态与接口故障

| 状态 | 含义及下一步 |
| --- | --- |
| needs_input | 缺少模板/必要参数、歧义或模板外要求；查看missing_fields和errors.path，补充要求后重试 |
| invalid_input | 不支持材料或数值范围错误；改正输入，尚未调用云接口 |
| invalid_output | 模型JSON的Schema或来源数值不匹配；本次结果不执行，人工检查后重新请求 |
| error | API/配置/格式失败；按code处理，不认为设计完成 |
| ready | 已校验的Envelope；可进入后续设计流程，仍需检查工具结果 |

API错误包括 `api_authentication_failed`、`api_balance_insufficient`、`api_rate_limited`、`api_unavailable`、`api_connection_failed`、`api_timeout`、`api_incomplete_response` 和 `api_invalid_json`。整个请求由独立进程执行，超时终止并等待该HTTP工作进程；不涉及AutoCAD。无自动重试，避免重复计费或无限等待。

## 扩展与验证

通用 `ParameterParser` 只依赖Registry、工具描述/输入校验、Gateway和 `LanguageProfile`。工程插件提供字段Schema、固定参数、context及 `inspect(text)` 来源检查。组合入口注册新工具和新profile即可；解析器不导入专业Adapter/旧引擎，也不按floor/wall/foundation写分支。第二个测试查询工具已验证注册后可解析，不修改通用解析器。

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

自动测试只使用假凭据和模拟HTTP，不连接云服务。真实调用和设计基线证据只在本机 `verification/phase-4/`，不提交到公共仓库。阶段验收及故障覆盖限制见 [阶段4报告](stages/phase-4.md)。
