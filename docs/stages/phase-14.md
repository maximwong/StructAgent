# 阶段14：本地Plugin发现与加载

日期：2026-10-04。基于阶段13人工验收补充`33a58e7`，分支`feature/plugin-discovery`，目标`feature/report-ui`，依赖PR #21。用户已明确确认阶段13手动验收完成；PR #21已ready for review，未合并。冻结标签不移动。

## 完成内容

建立PluginContext、Contribution、WebBinding、声明发现器及加载器，返回Registry、工作流、语言配置、插件版本及Schema。启用楼盖插件，复用旧注册和Adapter；应用入口取消楼盖导入，通过插件组合模板、完整参数和报告入口。UI配置名称由组合层注入，保留历史默认值兼容。

独立非工程Echo测试插件证明只加文件即可通过原应用工厂/Controller执行，正常安装目录不启用Echo。目录缺失、全禁用、不兼容API、声明不一致、重复能力和加载异常均不发布可运行Catalog。统一create_service用于正式UI和受控验收，避免临时服务遗漏完整参数组合。

## 修改文件

`app.py`、`ui/service.py`、`ui/static/app.js`、`README.md`、`CONTRIBUTING.md`、`AGENTS.md`、`docs/technical-debt.md`及`.github/workflows/python-tests.yml`。

## 新增文件

`core/plugin_base.py`、`core/plugin_loader.py`、`plugins/rc_floor/plugin.json`、`plugin.py`及`recovery.py`、`examples/plugin_inventory.py`、`tests/plugin_fixture.py`、`tests/test_plugins.py`、`tests/fixtures/plugins/echo/plugin.json`及`plugin.py`、`docs/plugins.md`及本报告。

## 保持不变的旧功能

Controller核心、旧程序、LISP、专业Tool/Adapter、公式、配筋、Demo期望基线和依赖锁均不改动。原CLI和显式受限循环保持原接口；网页不自动调整参数。报告保留原设计状态及独立编号。

## 测试内容

19项专项覆盖目录发现、工具Schema/版本、不执行计算的能力查询、禁用代码不导入、全声明先验证、版本/入口/JSON/身份错误、重复工具/工作流/配置、缺失依赖、导入和工厂失败脱敏、相对导入、独立工具对象、UI配置注入、UTF-8 CLI、无专业导入、第二插件执行及完整参数真实设计/校核/独立DOCX。恢复回调保留原命令、40秒预算及成功门槛，命令验证使用模拟进程，不操作CAD。

全量项目及旧程序回归、固定环境、旧产物哈希、冻结标签及公开文件检查。新自动测试中的CAD/云明确模拟，不计作AutoCAD实机或真实云验收。阶段13人工确认和网络启动环境修复记录保留。

## 测试结果

最终19项专项、276项项目测试及87项旧程序回归通过，共363项。Python 3.12.14与11项固定依赖、JS语法检查通过；能力清单UTF-8输出可读取。36份既有产物及阶段13DOCX哈希保持不变，Controller/专业实现/冻结标签核对通过。公共CI结果见对应PR检查。

新create_service网页烟雾测试在独立8767端口进行，模拟云/CAD、真实计算/报告。完整输入模式正确恢复；设计运行`f696a09f03ef4962bbd4163e5878b2d5`与报告运行`9a432842ff564f348bcbb37766a87447`各自保持独立，页面显示30图、29表、180/180项校核。截图仅本机保存，不重复计作阶段13人工Word/下载验收。

## 发现的问题

初次能力查询在Windows默认GBK下无法输出单位字符，已固定UTF-8并通过子进程验证。完整输入配置名由插件注入，后端不再以固定名称分派；前端按保存记录是否带model恢复参数模式，保留缺参/无效模型的完整模式身份。显式配置名与其他插件静态配置冲突时也拒绝加载。

## 技术债务

API v1仅支持已安装本地可信代码、自足工作流和一个网页专业绑定；未实现跨插件依赖解析、热加载、市场或代码隔离。多专业网页、第二种真实能力、PDF和原T06/T07/T09继续保留。完整表单的文字描述仍为必填，操作简化另行安排。

## 当前是否达到阶段验收标准

达到本阶段本地发现/加载、楼盖接入、测试插件扩展、普通流程保留及回归范围。不宣称新增柱/基础算法或自动多专业网页路由。Git交付通过依赖PR #21的独立PR审查，不自动合并。

## 下一阶段建议

选择已有柱或基础脚本，进行审计和最小Adapter接入，验证第二种真实能力无需改Controller。无现成脚本时不凭空编写公式。接入步骤见[插件说明](../plugins.md)。
