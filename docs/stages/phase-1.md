# 【阶段1】Engineering Tool Core

## 完成内容

建立EngineeringTool、ToolResult和ToolRegistry。工具通过统一Envelope执行，发现接口返回名称、版本、描述和输入/输出Schema。输入与输出都验证，非法输入不执行工具；普通异常转换为结构化错误。Dummy Tool能注册、发现、独立执行，第二种测试工具无需修改核心即可接入。

## 修改文件

`README.md`、`AGENTS.md`、`CONTRIBUTING.md` 更新当前阶段、接入规范与测试命令；`.github/workflows/python-tests.yml` 增加Tool Core测试和Dummy示例，并保留旧程序回归。

## 新增文件

- `core/__init__.py`、`exceptions.py`、`validation.py`、`tool_base.py`、`tool_result.py`、`tool_registry.py`。
- `examples/__init__.py`、`examples/dummy_tool.py`。
- `tests/test_tool_core.py`。
- `requirements.txt`、`requirements-dev.txt`。
- `docs/tool-core.md` 与本报告。

## 保持不变的旧功能

`legacy/rc_floor/` 下的源码、材料校验、计算公式、启动脚本、AutoLISP命令及原测试文件均未修改。阶段0.1的楼盖程序继续独立运行。通用核心不导入旧程序。

## 测试内容

注册与发现、重复名称、未知工具、第二工具接入、Schema定义错误、输入缺字段、错误工具名、数值中的布尔值与非有限值、非JSON对象及循环引用、输入副本隔离、执行异常、输出不合法、业务失败、KeyboardInterrupt、本地Schema引用、外部Schema不联网解析、结果序列化和副本隔离。

在仓库根目录运行：

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
python -m examples.dummy_tool
```

在 `legacy/rc_floor/` 下运行：

```powershell
python -m unittest discover -s tests -p 'test_*.py'
```

## 测试结果

本地Python 3.12环境：21项Tool Core测试、87项原有回归全部通过，共108项。Dummy示例输出success=true及完整结果Envelope。本地验证依赖为jsonschema 4.26.0、referencing 0.37.0。GitHub Actions按相同命令在Windows/Python 3.12运行，远端结果以关联PR的检查为准。

## 发现的问题

参数Schema包入Envelope后，本地引用可能改变解析根。实现通过嵌入独立Schema资源保留其含义，测试覆盖 `$defs` / `$ref` 的正反例。Python允许布尔值参与数值运算以及NaN/Infinity，工具边界现在明确区分JSON类型并拒绝非有限数值。

## 技术债务

阶段0.1保留的CAD完成回执、全生命周期超时、进程回收、旧数据隔离和部署依赖锁定仍未处理。工具目前同步执行、显式注册、每个名称一个版本。Project State、Controller、LLM、Adapter和自动插件发现按后续阶段实施。

## 当前是否达到阶段验收标准

是。Dummy Tool已完成注册、获取、执行、标准结果返回；错误场景和扩展工具接入有自动测试覆盖。该结论限于Tool Core，尚未通过Registry运行楼盖计算或CAD绘图。

## 下一阶段建议

按Issue #2实现design_floor_system：FloorDesignTool → FloorDesignAdapter → 现有楼盖连续计算流程。复用现有输入校验和计算入口，并验证三个标准案例的计算及配筋数据一致性。
