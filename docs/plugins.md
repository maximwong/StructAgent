# 本地Engineering Plugin接入

阶段14增加本地插件目录发现和API v1。Controller核心不修改，旧CLI注册函数保持可用，旧计算和LISP不迁移。阶段15的正常安装目录`plugins/`启用RC Floor和RC Column；阶段16增加可选结构化网页贡献，柱提供教学纯轴压设计与校核的本地网页，没有CAD、报告或自然语言声明。测试Echo位于`tests/fixtures/plugins/echo/`，不会随正常启动启用，不代表新增结构设计能力。

## 查看能力与启动

在仓库根目录使用固定环境：

```powershell
.\.venv-demo\Scripts\python.exe -m examples.plugin_inventory
```

输出插件ID、版本、API版本、工具描述、输入/输出Schema、工作流入口和语言配置。这里只构建对象，不调用API、计算或CAD。输出为UTF-8，避免Windows默认编码无法输出单位字符。

网页仍用原启动文件。切换开发分支后先在空闲时退出旧程序，再双击`启动StructAgent.cmd`。源码修改不会更新已运行进程，插件代码更新后必须重启；不提供热加载/卸载。正式验收从普通本机环境启动，限制联网的开发沙箱会造成API连接权限错误，不通过改密钥或放宽工程校验解决。

## 声明与工厂

```text
plugins/
  rc_floor/
    plugin.json
    plugin.py
  rc_column/
    plugin.json
    plugin.py
```

示例见[楼盖声明](../plugins/rc_floor/plugin.json)。必填字段为`id`、`name`、`version`、`api_version`、`description`、`entry_point`、`tools`；`enabled`可选，默认true。ID须等于目录名，使用以字母开头的小写字母、数字和下划线；版本使用三段数字，API版本仅支持整数1。入口固定为本目录`plugin.py`中的命名函数，例如`plugin.py:create_plugin`，不接受路径、表达式或任意模块字符串。

先验证全部JSON声明，再导入启用插件。禁用项不会导入Python；工具声明必须与实际注册一致。重复工具/工作流入口/名称/语言配置、未知工具绑定和不兼容API均使加载失败，不覆盖能力、不发布部分Catalog。错误不回显插件异常中的秘密或路径。

插件是已安装、已审查的本地Python代码，与应用拥有相同权限；此机制不是代码沙箱，不下载或安装外部扩展。导入和工厂只负责构建/注册对象，不应执行计算、联网或操作CAD；加载失败不能撤销插件自行造成的外部副作用。

`create_plugin(context)`接收`PluginContext(output_root, options)`，返回[PluginContribution](../core/plugin_base.py)：

- `registry`：本插件ToolRegistry，工具沿用EngineeringTool校验及ToolResult。
- `workflows`：应用声明的Workflow和ResultBinding；同一入口只能对应一个工作流。
- `profiles`：专业LanguageProfile，引用本插件工作流入口。
- `web`：可选PluginWebBinding，提供模板/完整输入配置、表单、报告源及文件验证器、CAD恢复回调。

楼盖工厂复用既有注册函数和Adapter，注册四个普通工具。受限重设计仍通过旧显式CLI启用，不加入普通网页。API v1工作流依赖留在同一插件内，未实现跨插件依赖排序和版本范围协商。

[app.py](../app.py)只调用加载器、通用Parser/Controller和插件回调，不导入楼盖或柱模块。`create_service`是正式UI与受控验收的共同组合入口。保留唯一旧式WebBinding及其报告/CAD契约，同时允许多个插件提供结构化网页贡献；专业列表由已加载的贡献生成。报告沿用单步`artifact_report`契约。完整的多专业云解析绑定和跨插件工作流仍未接入。

## 可选结构化网页贡献（阶段16）

`PluginContribution.structured_web`默认空tuple，追加在既有字段之后，保持API v1和旧工厂位置参数兼容。每个`StructuredWebBinding`声明专业ID/名称、操作、表单、完整请求校验和只读呈现回调。每个`StructuredWebOperation`只绑定本插件已注册的工作流及其入口工具；重复专业/操作、缺失或错配入口均拒绝，不发布部分能力。同一插件不能同时贡献旧式WebBinding与结构化绑定，避免专业身份、配置和页面分支冲突。

应用负责构建本地`StructuredParser`与原Controller，输入仍是完整Envelope；不构建云模型，不推断关键字段。柱声明设计和单步校核操作，后者的实际方案与引用模式共用一个校核入口，输入互斥由原Schema验证。表单由插件按Schema描述；数据导入在填表前严格验证，展示回调提供中文摘要及逐项结果。加载工厂不执行计算或创建运行。

结构化运行写入与网页一致的`agent`状态目录，每个job在创建运行时绑定自己的run_id。历史按专业/项目筛选后截取最近记录，不用项目最后一次结果代替旧job。记录类型及必要字段受检查；损坏的结构化模式标识不能退回楼盖呈现。结构化专业不提供的CAD/报告操作在服务端也拒绝。插件更新仍需重启，无新增包依赖。详见[柱网页](column-ui.md)和[阶段16报告](stages/phase-16.md)。

## 验证第二个插件

```powershell
.\.venv-demo\Scripts\python.exe -m unittest tests.test_plugins -v
```

专项测试将RC Floor和Echo复制到临时目录，由同一个应用工厂、模拟云响应和不变的Controller执行Echo。也运行真实楼盖设计、只读Check和DOCX；CAD明确模拟。增加目录即可发现能力，不修改应用专业分支或Controller。

阶段15已接入真实柱计算插件。没有可复用柱脚本，因此先核对条款、固定独立参考数据，再实现确定性计算模块；设计和校核通过Adapter接入统一Tool。插件只声明已实现工具及工作流，不必为了注册工具而提供LanguageProfile或WebBinding。完整JSON经本地校验后交给原Controller，设计引用通过ResultBinding传给校核；楼盖绑定继续使用原网页。用[柱工具CLI](column-tool.md)验证第二种工程能力，依据及范围见[工程说明](column-basis.md)。

未来基础等专业仍须审计已有脚本或锁定新算法依据，再实现Tool和Workflow。Echo不作为工程验算。正式PDF、完整输入的可选文字描述、网页调整授权另行安排。阶段14历史结果见[原报告](stages/phase-14.md)。
