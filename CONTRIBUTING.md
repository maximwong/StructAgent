# 协作开发

## 分支与交接

v0.2工作从 `develop/v0.2` 创建任务分支；若依赖尚未合并的功能，则从对应功能分支继续并以它为PR目标。不要移动`v0.1-demo`标签或向冻结分支添加新功能。每个任务尽量只解决一个明确问题；通过Issue写清输入、输出和验收条件。多设备工作先拉取远端更新，再在自己的分支提交。不同模型接手时，以仓库文件、Issue、PR和测试结果作为事实来源，不依赖聊天记录中的未提交状态。

PR说明请包括：触发问题、修改后的行为、变更文件、测试命令与结果、需要AutoCAD手动验证的步骤、未处理的风险。计算或CAD输出变化时附上匿名样例对比。不要在PR中贴密钥、本机绝对路径或客户图纸。

## 本地检查

Windows PowerShell 示例：

```powershell
python -m pip install -r requirements-demo.txt
python -m pip check
python -m examples.environment_check
python -m unittest discover -s tests -p 'test_*.py' -v
python -m examples.dummy_tool
python -m examples.floor_design
cd legacy/rc_floor
python -m unittest discover -s tests -p 'test_*.py'
```

以上从仓库根目录开始，使用 [固定独立Python环境](docs/demo-deployment.md)。阶段10.1前一套225项，后一套87项，共312项。CAD自动测试使用真实设计和数据转换，绘图后端为模拟；部分边界测试启动真实PowerShell辅助进程，但不操作桌面CAD，不能把它写成AutoCAD出图通过。新Tool按照 [统一接口](docs/tool-core.md) 实现 `_execute`，由应用启动代码显式注册；通用核心不导入具体工程工具。

楼盖基线指纹位于 `tests/fixtures/floor_baselines.json`，来自阶段0.1冻结成果，不由当前计算结果自动更新。设计结果变化时必须解释工程原因并提供对比，不能仅更新指纹使测试通过。当前三个案例在Windows/Python 3.12验证；新平台的数值差异应先调查。

CAD图元和参数文件指纹位于 `tests/fixtures/cad_baselines.json`，同样来自阶段0.1。桌面验收运行 `python -m examples.floor_cad`，先确保AutoCAD 2022空闲；所有测试在工具新建的图纸执行。图纸、运行日志和本机绝对路径不提交到公共仓库。基于尚未合并的阶段分支继续工作时，以对应分支为PR目标，按依赖顺序合并后再调整后续PR目标。

这些测试不代替AutoCAD实机验证。修改 `RCFLOOR.lsp` 或CAD调用链时，另用独立测试图纸检查插入、撤销、重做、Esc、异常清理和保存回读。

## 工程范围

现有楼盖程序是首个接入对象。Tool Core和Adapter应维持统一输入、输出与错误边界；未来新增墙、柱、基础工具时不应大幅改动Controller。未经验证不要改变设计公式或静默补齐关键结构参数。
