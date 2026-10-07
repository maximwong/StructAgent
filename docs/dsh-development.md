# GPT → DeepSeek Harness 开发协作

这是可选的**开发工具**，不加入 EngineeringTool Registry，不更改网页、Controller、工程算法或生产依赖。GPT负责拆解、审查、整合与交付；DeepSeek Harness在独立代码副本内完成明确的小任务；Astra仍承担关键工程依据和算法审查。它不能直接代替工程审核或把自己的测试声明作为验收结论。

## 本机接入方式

复用用户已安装的DeepSeek Harness桌面版中的`resources/runtime/cli/bin/dsh.cmd`。桌面客户端Chromium版本与CLI版本不同；当前实测CLI为`0.2.0-rc.2`。桥接使用官方Python SDK `0.1.5rc1`、`sdk-minimal`及JSON-RPC stdio，通过`dsh_bin`显式选择桌面运行时。桌面运行时更新后需重新做接口冒烟验证。无需打开桌面GUI，也不读取其历史会话或个人配置。

依据：[官方Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[SDK教程](https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk)、[桌面程序](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)、[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。官方Harness仍为开发预览。

在仓库根目录的PowerShell中安装，`-Python`指向Python 3.12，`-Codex`可传本机Codex CLI绝对路径：

```powershell
.\devtools\dsh\setup.ps1 -DshCli 'D:\DSH\resources\runtime\cli\bin\dsh.cmd' -Python '.\.venv-demo\Scripts\python.exe'
```

独立环境`.venv-dsh`只安装开发依赖，`.venv-demo`不变。为复用桌面运行时，SDK以`--no-deps`安装并显式安装所需库；`pip check`会提示未安装SDK声明的同版本runtime wheel，这是此安装方式的已知限制，运行时由`dsh_bin`提供。没有安装第二份72MB运行时。此首版仅支持Windows。

密钥读取本仓库已有`.env`或环境变量，仍经`config.load_settings`校验；不写入MCP配置、不放入命令参数或任务副本。可在本机被忽略的`.dsh-tasks/config.json`修改`dsh_bin`和开发模型`model`。该配置不含密钥。默认开发模型为`deepseek-flash`，不改变网页解析模型。

DSH官方适配器使用Messages API，固定官方根地址为`https://api.deepseek.com/anthropic`，与产品Chat Completions根地址不同。不能把网页的base_url直接传入Harness，否则会得到HTTP 404；此配置仅在开发worker中生效。

## GPT可调用的接口

| 开发工具 | 行为 |
| --- | --- |
| `start_deepseek_task` | 接收任务、允许修改的文件/目录、总时间上限及每请求输出上限，立即返回task_id |
| `get_deepseek_task` | 读取终态、摘要、改动文件、越界记录和补丁路径 |
| `cancel_deepseek_task` | 请求停止；只回收本任务拥有的运行时与子进程 |

注册名为`structagent-dsh`。Codex当前对话可能尚未刷新工具目录，重新打开/重载后发现MCP；当前GPT也可用同一CLI即时调用：

```powershell
.\.venv-dsh\Scripts\python.exe -m devtools.dsh.bridge start --task '阅读指定模块，补充明确的边界测试，运行相关测试并汇报。' --allow 'tests/test_example.py' --timeout 300 --max-tokens 4096
.\.venv-dsh\Scripts\python.exe -m devtools.dsh.bridge get '<返回的task_id>'
.\.venv-dsh\Scripts\python.exe -m devtools.dsh.bridge cancel '<返回的task_id>'
```

任务从源仓库**已提交的HEAD**复制；未提交修改不传入、不覆盖。副本移除Git远程，不自动提交/推送/合并。修改范围是精确文件名或末尾带`/`的目录前缀。完成时从基线收集已有、新增、已提交的全部Git差异，超范围或符号链接改动返回`scope_violation`；GPT必须读补丁、重跑必要测试，然后选择性整合。任务完成只表示运行时成功结束，不等于代码通过评审。

默认串行，一个任务300秒、每请求最多4096输出token；可设置30–900秒及256–8192 token。**输出上限不是整项累计token或费用上限**；输入上下文、多次请求及服务重试仍计费。首版不提供累计费用硬限额，不承诺节省比例。适合样例、文档、明确测试、小模块修复；工程条款、公式、重要架构与最终审查继续交给GPT/Astra。

## 隔离、证据与退出

每项任务拥有独立Git clone、Harness home和会话，`.dsh-tasks/<task_id>/`保存请求、状态、事件、摘要及`changes.patch`。这些本机记录、开发环境均被Git忽略。会话日志上传和插件清单上报在专用patch中关闭；没有web工具或嵌套子Agent。模型运行所需代码与任务仍会发送至DeepSeek API。

**独立clone不是操作系统安全沙箱。**`sdk-minimal`使用本地完整权限shell，范围限制是提示约束加事后差异审核，不能阻止任意系统操作。只委派可信的匿名开发任务，不应让它处理客户资料或密钥。此版没有容器/ACL隔离；它只适用于已经授权的本机开发协作。

Windows Job Object的kill-on-close约束用于回收本worker及其后代。取消通过任务标记通知worker；总时限由worker监测，关闭SDK后再收集差异。用户已打开的DSH、AutoCAD和网页服务不归此任务所有。重启主机等导致缺少终态时记录`interrupted`，不报成功。断电后的清理、外部逃逸进程、MCP热加载、累计成本预算及预发布运行时升级兼容仍属后续开发债务。

离线测试：`python -m unittest tests.test_dsh_bridge -v`。真实任务的测试声明须由GPT再次执行核对；日志保留本机，不上传公开仓库。
