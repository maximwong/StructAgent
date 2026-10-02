# 【阶段2】楼盖设计Tool与Adapter

## 完成内容

新增design_floor_system，经Registry完成板、次梁、主梁、配筋及既有校核的完整计算。统一Envelope支持显式Demo模板或完整模型；Adapter映射参数、调用原引擎、整理标准构件结果并保留完整快照和警告。

旧引擎运行在独立Python进程，通过结构化JSON通信，避免通用模块名和全局导入路径影响其他工具。包含计算限时、启动/退出错误和协议错误返回。

## 修改文件

`README.md`、`AGENTS.md`、`CONTRIBUTING.md`、`docs/tool-core.md` 更新接手说明；`.github/workflows/python-tests.yml` 加入楼盖示例及工具测试。

## 新增文件

- `tools/__init__.py`、`tools/floor/__init__.py`。
- `tools/floor/design_tool.py`、`design_adapter.py`、`_legacy_worker.py`、`schemas.py`。
- `tools/floor/templates/office_floor_demo_v1.json`。
- `examples/floor_design.py`。
- `tests/test_floor_design.py`、`tests/fixtures/floor_baselines.json`。
- `docs/floor-design-tool.md` 与本报告。

## 保持不变的旧功能

未修改 `core/` 或 `legacy/rc_floor/`。计算公式、已有输入校验、板/次梁/主梁连续流程、钢筋长度、原启动方式及AutoLISP全部保持。未增加LLM、Controller或CAD调用。

## 测试内容

三案例并行执行及完整快照/钢筋指纹、Demo模板映射、保留警告和既有检查、缺参、错误单位/规范标签、未知模板、材料强度冲突、布尔数值、合法开关、计算拒绝后重试、父进程模块名冲突、中文工作目录、计算限时/启动/退出/协议错误，以及原有回归。进程故障用模拟响应注入，三个设计案例和旧模型拒绝均实际调用原引擎。

运行命令（前两项在仓库根目录，最后一项在legacy/rc_floor）：

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
python -m examples.floor_design
python -m unittest discover -s tests -p 'test_*.py'
```

## 测试结果

本地Python 3.12：39项核心/楼盖工具测试和87项原有回归全部通过，共126项。Demo A正常返回6个板截面、4个次梁截面、4个主梁截面和30条钢筋记录。远端CI按同一流程执行，结果见关联PR检查。

| 案例 | 阶段0.1完整结果SHA-256 | 对比 |
| --- | --- | --- |
| sample1 | 89128dedcbbe9ee9078f83a7bc95f4560ffaa50c394f2751adda841426001465 | 一致 |
| changed | 7f63df451462cc55b91c26a142a7070183b116fc0d2b55ddd7a0e18d0b1cfcec | 一致 |
| demo_a | 2df9a0a4039145d7eeed5b48f71d1aa9fd9375122dd5fa5b46fc5edc32971bf4 | 一致 |

指纹来自原先冻结的阶段0.1成果，不根据新输出重新设定。完整快照含所有计算、检查、钢筋长度与几何数据；另外单独比较钢筋记录指纹。未运行CAD实机测试，因为本阶段没有修改或调用CAD。

## 发现的问题

简化的五个参数不足以定义完整模型，现要求显式指定已确认模板。旧引擎限定主梁三跨、次梁五跨和三分点荷载，模板明确映射span_x/3间距，旧适用性检查保留。导入隔离避免旧engine等顶层名称污染父进程。整数毫米值在映射时保留整数表示，修复了初次模板转换造成的JSON指纹差异；命令行输出显式采用UTF-8。

## 技术债务

完整结果暂保存在内存中，尚无结果引用和Project State持久化。构件记录保留旧字段，后续独立校核/报告工具可继续规范。当前计算超时只覆盖本次Python子进程；AutoCAD回执、CAD全生命周期超时和恢复、工程文件隔离及部署依赖锁定仍待后续处理。

## 当前是否达到阶段验收标准

是。Registry可独立获取并执行design_floor_system，完整楼盖计算和三案例基线一致性已通过。阶段1 PR尚未合并时，阶段2 PR以其分支为基础，代码依赖关系需按PR顺序合并。

## 下一阶段建议

阶段3接入generate_floor_cad，通过FloorCADAdapter复用设计快照和现有CAD数据转换/RFALL，完成无AI的设计→出图链路，并验证完成回执和错误处理。
