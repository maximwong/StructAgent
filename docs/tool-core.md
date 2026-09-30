# Engineering Tool Core

阶段1提供同步、显式注册的工具接口。核心不导入楼盖、CAD、LLM或UI模块。完整可运行示例为 `python -m examples.dummy_tool`。

## 注册、发现与执行

```python
from core import ToolRegistry
from examples.dummy_tool import DummyTool

registry = ToolRegistry()
registry.register(DummyTool())
capabilities = registry.list_tools()
tool = registry.get("dummy_tool")
result = tool.execute({
    "project_id": "CSU-DEMO-001",
    "tool": "dummy_tool",
    "context": {"unit_system": "SI", "design_code": "GB"},
    "parameters": {"value": 6.0},
})
print(result.to_dict())
```

Registry对每个名称只保存一个版本，重复注册抛出 `ToolDefinitionError`，不覆盖原工具；未找到工具时抛出 `ToolNotFoundError`。发现结果包括名称、版本、描述、完整输入Schema和输出Schema，返回独立副本供未来Controller使用。

## 实现一个工具

继承 `EngineeringTool`，在构造时提供 `name`、`version`、`description`、`parameters_schema` 和 `output_schema`，实现 `_execute(data) -> ToolResult`。示例代码见 `examples/dummy_tool.py`。`_execute` 是未来调用工程Adapter的位置。不要替换基类的 `execute` 执行边界。

基类公开的 `input_schema` 自动包含完整Envelope；`parameters_schema` 只描述其中的 `parameters`。`output_schema` 描述成功结果中的 `result` 对象，不是整个ToolResult。两者必须显式声明 `type: object`。工具名采用小写字母、数字和下划线，并以字母开头；版本和说明必须非空。

执行顺序：输入校验 → 输入副本交给实现 → 检查ToolResult身份及结构 → 校验成功结果 → 返回结果副本。非法输入不会调用 `_execute`。直接调用 `validate(data)` 会在不合法时抛出 `ToolValidationError`，它兼容 `ValueError` 并提供结构化的 `errors`。

## 输入Envelope

`project_id`、`tool`、`context`、`parameters` 全部必填。`context.unit_system` 和 `context.design_code` 是非空字符串，工具可以读取它们；核心不假定某一种单位制或设计规范，也不执行单位换算。具体工具应在自己的校验规则中限制支持范围。context允许添加JSON扩展字段；Envelope最外层不允许未知字段。`tool` 必须与被调用工具名称相同。

参数不会自动补默认值、转换类型或猜测缺失值。数值字段的 `true`、`false` 被Schema拒绝；合法布尔字段可以在参数Schema中明确声明。所有输入与输出仅允许JSON类型，拒绝NaN、Infinity、循环引用、非字符串对象键和Python专用对象。

校验采用JSON Schema Draft 2020-12及 `jsonschema` 的验证器。相关API见 [官方说明](https://python-jsonschema.readthedocs.io/en/stable/validate/)。Schema应自包含，可使用本地 `$defs` 和 `$ref`；参数Schema嵌入Envelope时自动获得独立的Schema资源标识，使本地引用仍指向参数Schema。外部Schema不会联网获取，无法本地解析时返回验证错误。`format` 当前不作为额外验证规则，日期等要求应明确添加校验。

## 标准结果

```json
{
  "success": true,
  "tool": "dummy_tool",
  "version": "1.0.0",
  "result": {"value": 6.0},
  "warnings": [],
  "errors": [],
  "artifacts": [],
  "metadata": {}
}
```

错误项采用 `{"code": "validation_error", "message": "...", "path": ["parameters", "value"]}`。path是字段名和数组下标组成的路径；缺失字段时message说明缺少的名称，path指向所属对象。

- `validation_error`：输入不满足约定，工具未执行。
- `execution_error`：工具实现抛出普通异常。
- `output_validation_error`：返回值类型、工具身份或成功结果不符合约定。
- 业务失败：工具可用 `ToolResult.failure(...)` 返回自己的错误码，例如 `design_failed`；失败结果不要求符合成功输出Schema。

成功结果的errors必须为空，失败结果必须带错误。warnings为字符串列表，metadata为JSON对象，artifacts为至少包含 `type` 和 `path` 的JSON对象列表。核心只检查声明的结构，不代替Adapter检查文件是否实际生成。`to_dict()` 重新验证并返回可序列化的独立副本。ToolResult顶层属性不可重新赋值，内部字典和列表不是深度不可变对象。

普通异常会转换为失败结果；`KeyboardInterrupt` 和 `SystemExit` 等进程控制信号不被吞掉。当前没有重试、超时、进程回收、状态持久化、版本选择或插件目录自动扫描。异常后的资源释放仍由具体Adapter负责。

## 后续接入

阶段2新增FloorDesignTool与FloorDesignAdapter，阶段3新增FloorCADTool与FloorCADAdapter。应用启动时注册实例即可，Registry不增加楼盖/墙/基础分支。未来自动发现插件可以复用相同注册接口。
