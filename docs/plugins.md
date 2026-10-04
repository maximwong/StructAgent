# 本地Engineering Plugin接入

阶段14增加本地插件目录发现和API v1。Controller核心不修改，旧CLI注册函数保持可用，旧计算和LISP不迁移。正常安装目录`plugins/`当前只启用RC Floor；测试Echo位于`tests/fixtures/plugins/echo/`，不会随正常启动启用，不代表新增结构设计能力。

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

[app.py](../app.py)只调用加载器、通用Parser/Controller和插件回调，不导入楼盖模块。`create_service`是正式UI与受控验收的共同组合入口。网页仍只支持一个专业WebBinding；报告沿用单步`artifact_report`契约。其他插件可增加工具、语言配置和工作流，多专业网页选择/呈现尚未接入。

## 验证第二个插件

```powershell
.\.venv-demo\Scripts\python.exe -m unittest tests.test_plugins -v
```

专项测试将RC Floor和Echo复制到临时目录，由同一个应用工厂、模拟云响应和不变的Controller执行Echo。也运行真实楼盖设计、只读Check和DOCX；CAD明确模拟。增加目录即可发现能力，不修改应用专业分支或Controller。

真实柱/基础应先审计已有脚本，制作Adapter、Schema、LanguageProfile和Workflow，再新增插件声明。Echo不作为工程验算。正式PDF、完整输入的可选文字描述、网页调整授权另行安排。结果见[阶段14报告](stages/phase-14.md)。
