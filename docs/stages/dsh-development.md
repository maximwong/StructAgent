# 开发协作增补：GPT → DeepSeek Harness

【阶段】可选开发子Agent接入，2026-10-07；不推进新的工程算法阶段。

完成内容：

- 复用本机DSH桌面版CLI `0.2.0-rc.2`，通过官方Python SDK `0.1.5rc1`和`sdk-minimal`运行明确开发任务。
- 提供异步MCP三接口与同一CLI：开始、查询、取消；注册为`structagent-dsh`。
- 每项任务独立clone和Harness home，从已提交HEAD开始；授权路径、有限时长、每请求输出上限、差异审核与本机证据；不自动应用、提交或推送。
- 密钥由可信配置读取，未复制到任务目录/MCP配置/命令参数。专用配置关闭会话日志上传和插件清单上报。
- Windows Job Object回收本任务子进程；总时限覆盖复制、初始化、模型执行及差异收集，退出清理允许额外短暂耗时。
- 已完成真实委派：DSH只为`tests/test_dsh_bridge.py`新增一个路径边界测试；实际工具日志显示11项通过。GPT阅读补丁、核对范围与日志、整合并独立复测13项通过。

修改文件：`.gitignore`、`AGENTS.md`、`README.md`、`docs/column-roadmap.md`、`docs/technical-debt.md`、`.github/workflows/python-tests.yml`。

新增文件：`devtools/__init__.py`，`devtools/dsh/`内的`__init__.py`、`bridge.py`、`worker.py`、`server.py`、`privacy.patch.yml`、`requirements.txt`、`setup.ps1`；`tests/test_dsh_bridge.py`、`tests/test_dsh_lifecycle.py`；`docs/dsh-development.md`及本报告。

保持不变的旧功能：应用/Controller/专业Registry、楼盖和柱计算、CAD/LISP、网页解析配置、产品依赖锁及`v0.1-demo`标签。网页服务继续在原端口运行，没有重新出图或操作用户DSH桌面会话。

测试内容与结果：

| 检查 | 结果 |
| --- | --- |
| 全量项目回归 | 347项，215.026秒，OK；产品环境未安装pywin32，2项worker生命周期测试跳过 |
| 独立开发环境测试 | 13项，6.501秒，全通过，含上述2项取消/超时真实子进程回收测试；不调用模型 |
| 旧楼盖回归 | 87项，5.596秒，全通过 |
| 固定产品环境检查 | Python3.12.14与11项锁定依赖通过 |
| 真实DeepSeek Harness任务 | completed，仅1个授权文件，无越界；11项实际测试输出与摘要一致 |
| GPT整合 | 阅读diff、git apply检查与应用、独立测试通过；补丁LF回归验证通过 |
| MCP | 初始化、工具发现、实际任务结果读取通过；Codex注册enabled，stdio，不含env密钥 |
| 隐私与冻结 | 本机私有目录被忽略，已知真实密钥不在改动中；远端/本地冻结标签一致 |

全量回归后最后补充的DSH总时限保护由13项受影响测试再次覆盖。CI新增独立pywin32测试环境，产品环境不安装开发依赖。CI状态见本PR，不能把已注册误写成当前对话的工具目录已热刷新。

发现的问题与修复：

1. SDK只有预发布版本，普通pip查询不包含它：显式固定`0.1.5rc1`，复用桌面运行时。
2. pywin32 Job Object匿名名称不能传None：使用空名称，独立子进程验证创建及回收。
3. 本机不同所有者的源Git目录无法clone：仅为此次命令声明源repo和`.git`可信目录，不设置全局通配信任。
4. 将Chat Completions根地址传给DSH导致Messages API HTTP404：开发worker使用官方`/anthropic`根地址，产品配置不变。
5. Windows文本写入转换CRLF导致补丁不适用：按UTF-8字节保留LF，新增完整补丁应用回归。

失败尝试保留原failed记录，不改写成成功。验证日志、私有配置和真实API任务记录只在本机`.dsh-tasks/`及`verification/dsh/`保存。

技术债务：完整权限shell缺乏OS沙箱；没有累计费用硬预算或节省比例统计；主机崩溃/并发CLI预留锁、跨设备/跨平台、DSH升级、Codex热刷新及分支切换后工具可用性仍待完善。SDK复用桌面CLI导致`pip check`提示声明的runtime wheel缺失，已说明。见[详细清单](../technical-debt.md)。

当前是否达到阶段验收标准：**本机CLI真实开发委派、补丁回收、GPT复测、MCP注册及stdio接口达到验收要求。当前对话未发现新增MCP工具；重载后的Codex原生工具展示尚未验收，不影响当前GPT通过CLI委派。**

下一阶段建议：优先将文档、匿名案例、明确边界测试和小模块实现交给DSH；GPT审查整合，Astra保持关键工程依据/算法只读审核。不要同时扩展工程功能或让DSH直接推送/发布。每次主任务确定后再选择适合委派的部分。
