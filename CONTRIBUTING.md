# 协作开发

## 分支与交接

从 `main` 创建任务分支，例如 `tool-core` 或 `floor-adapter`。每个任务尽量只解决一个明确问题；通过Issue写清输入、输出和验收条件。多设备工作先拉取远端更新，再在自己的分支提交。不同模型接手时，以仓库文件、Issue、PR和测试结果作为事实来源，不依赖聊天记录中的未提交状态。

PR说明请包括：触发问题、修改后的行为、变更文件、测试命令与结果、需要AutoCAD手动验证的步骤、未处理的风险。计算或CAD输出变化时附上匿名样例对比。不要在PR中贴密钥、本机绝对路径或客户图纸。

## 本地检查

Windows PowerShell 示例：

```powershell
cd legacy/rc_floor
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
```

这些测试不代替AutoCAD实机验证。修改 `RCFLOOR.lsp` 或CAD调用链时，另用独立测试图纸检查插入、撤销、重做、Esc、异常清理和保存回读。

## 工程范围

现有楼盖程序是首个接入对象。Tool Core和Adapter应维持统一输入、输出与错误边界；未来新增墙、柱、基础工具时不应大幅改动Controller。未经验证不要改变设计公式或静默补齐关键结构参数。
