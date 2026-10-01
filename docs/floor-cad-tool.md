# 楼盖 CAD Tool

`generate_floor_cad` 读取本项目成功计算的结果引用，通过 Adapter 复用现有 CAD 数据转换及 AutoLISP，创建独立图纸、保存 DWG、重新打开并核对。统一Tool接口与旧计算程序保持；旧LISP仅增加可选的本次取消文件检查。

## 运行环境与示例

Windows x64、Python 3.12.14、桌面版 AutoCAD 2022；按照 [固定部署说明](demo-deployment.md) 安装 `requirements-demo.txt`。先打开 AutoCAD 并处理启动/许可提示，使其处于空闲状态。脚本使用 Unicode AutoLISP 引擎；首次在设备上使用时按 AutoCAD 提示手动加载 `legacy/rc_floor/RCFLOOR.lsp`。工具不会修改 AutoCAD 的安全设置。

```powershell
python -m examples.floor_cad
python -m examples.floor_cad --case sample1
python -m examples.floor_cad --case changed --output-root "data/projects/演示工程"
```

示例在无 AI 的情况下调用设计工具、保存结果引用，再调用 CAD 工具。默认使用已确认的 Demo A 完整参数。输出位置由应用配置，工具输入不接受任意文件路径或 CAD 命令。

```python
from core import ToolRegistry
from tools.floor import FloorDesignTool, FloorCADTool
from tools.floor.cad_adapter import FloorCADAdapter
from tools.floor.design_store import FloorDesignStore

store = FloorDesignStore("data/projects/designs")
registry = ToolRegistry()
registry.register(FloorDesignTool())
registry.register(FloorCADTool(store, FloorCADAdapter("data/projects/cad")))
design = registry.get("design_floor_system").execute(design_envelope)
if design.success:
    reference = store.save(design)
    drawing = registry.get("generate_floor_cad").execute({
        "project_id": design_envelope["project_id"],
        "tool": "generate_floor_cad",
        "context": {"unit_system": "SI", "design_code": "GB"},
        "parameters": {"design_result_ref": reference},
    })
```

`design_envelope` 的完整结构见 [设计工具说明](floor-design-tool.md)。本阶段应用示例负责保存引用；这不是 Agent Controller。

## 输入与结果

唯一专业参数 `design_result_ref` 的格式为 `floor-` 加32位小写十六进制编号。引用由本地 Store 生成，不能用文件路径代替。读取时检查标准 ToolResult、设计工具名称/版本、项目归属、输入一致性及 SHA-256。只支持当前设计版本1.0.0；未来版本需明确迁移。校验和用于发现意外修改，不是数字签名或多用户权限系统。

成功结果：

```json
{
  "success": true,
  "tool": "generate_floor_cad",
  "version": "1.0.0",
  "result": {
    "drawing_status": "completed",
    "run_id": "32位运行编号",
    "entities": 2305,
    "reopened": true
  },
  "warnings": ["保留设计工具的适用范围提示"],
  "errors": [],
  "artifacts": [
    {"type": "dwg", "path": "绝对路径/floor.dwg"},
    {"type": "verification", "path": "绝对路径/cad_receipt.json"}
  ],
  "metadata": {"run_directory": "本次输出目录"}
}
```

上例路径和运行编号为说明性占位。实际输出还包含项目、设计引用、设计/图元数据指纹。每次调用创建新运行目录；结果引用文件及已有图纸不被覆盖。

## 执行边界

1. 在独立 Python 进程中调用旧 `cad_scene.export_drawing`，生成原格式参数、图元 JSON 和预览，保持父进程导入隔离。
2. Windows PowerShell STA 桥接连接已打开的 AutoCAD。沿用旧程序的进程级 `-ExecutionPolicy Bypass` 调用，不更改机器/用户的持久执行策略。此调用只执行仓库内固定脚本。
3. 使用当前 Windows 会话的命名互斥锁，避免多个本工具同时控制 AutoCAD。若 CAD 忙碌则返回错误。
4. 创建全新空图，在 Adapter 内加载固定旧脚本、读取本次参数并调用绘图命令。命令结束标记含本次唯一编号。
5. 等待命令退出，再检查系统变量/撤销组恢复，以及所有实体的类型、图层、线/圆/弧/多段线几何、文字、尺寸读数与比例和字体/线型。
6. 保存 DWG，关闭并只读重开，再重复内容核对。只有匹配本次编号的成功回执和非空 DWG 同时存在，才返回成功。

已有用户图纸不用于绘制。正常完成后关闭本工具创建的图纸，不退出 AutoCAD。图纸验证通过但关闭失败时，成功结果附加提醒。

AutoCAD 此路径的 ActiveX `Measurement` 已包含标注比例，因此校验使用几何投影长度乘 `LinearScaleFactor`；不会把已缩放值再当原始距离比较。

## 错误与恢复

| 错误代码 | 含义与处理 |
| --- | --- |
| `invalid_design_reference` | 引用不存在、跨项目、损坏或不是成功设计；重新计算并保存引用 |
| `cad_conversion_failed` | 旧 CAD 数据转换失败；检查运行日志和设计数据 |
| `cad_unavailable` | AutoCAD 未启动/版本不支持，或非 Windows；打开支持的桌面版本 |
| `cad_busy` | CAD 正在执行命令，或另一工具调用持有会话锁；完成当前操作后重试 |
| `cad_unicode_required` | Unicode AutoLISP 引擎未启用；按旧脚本部署说明配置并重启 |
| `cad_start_failed` | 桥接进程无法启动 |
| `cad_timeout` | 超过限时，归属图纸已恢复关闭；重新运行将创建独立新目录 |
| `cad_cancelled` | 收到本次取消请求，失败不返回可交付附件 |
| `cad_recovery_required` | 无法确认/恢复前次会话；阻止新出图，处理桌面状态后运行恢复命令 |
| `cad_verification_failed` | 保存或实体/文字/尺寸核对失败，不返回可交付图纸 |
| `cad_receipt_invalid` | 缺少回执、编号不符、桥接异常退出或图纸缺失 |
| `cad_failed` | 其他绘图/桥接错误，保留具体信息 |

每次运行保存 `run.json`、CAD日志和能够获取到的回执，失败时不返回成功 artifacts。运行文件、DWG和设计引用默认存于被 Git 忽略的 `data/projects/`。这些本地资料仍需自行保管。

场景转换限时60秒；CAD默认240秒，可由应用配置为10–900秒；示例可传 `--cad-timeout`。CAD外围监控使用相同限时，超时终止本次桥接进程并请求协作取消，再执行最多12秒的归属恢复；前次会话恢复批次总预算15秒。它们是分别受限的步骤，不是整个设计→出图任务共用一个240秒预算。

通用SQLite状态存于输出根目录下的 `cad/state.sqlite3`，独立于专业计算。全桌面工具会话日志在 `data/runtime/cad/`，跨输出根目录检查未结束调用。正常历史保留为CLOSED；Python进程退出/PID复用不会把旧RUNNING误当仍在执行或已完成。

恢复匹配AutoCAD进程启动时间、图纸自定义运行标记及记录路径。图纸标记使用 [AutoCAD SummaryInfo API](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-ActiveX-Reference/files/GUID-A029FB49-B0DB-43E4-8888-698E1BF49878.htm)。无法确认归属的图纸不关闭；遗留桥接仅在进程启动时间、固定脚本、运行编号及目录均吻合时回收。不杀AutoCAD，不向用户命令发送Esc。

```powershell
python -m examples.cad_recovery
python -m examples.cad_recovery --output-root "data/projects/演示工程"
```

失败恢复会保留RECOVERY_REQUIRED并阻止新出图；检查弹窗及桌面状态后重试恢复，不能删除未解决日志绕过保护。恢复成功只把中断运行记录为FAILED，随后显式重新运行出图。AutoCAD硬挂起、许可/信任提示及整机断电不是可自动保证恢复的场景，未完整验收项见 [技术债清单](technical-debt.md)。

## 验证范围

自动测试运行真实设计及真实图元转换，CAD 后端用模拟回执验证失败边界，不代表桌面出图。`tests/fixtures/cad_baselines.json` 来自阶段0.1冻结文件，包含三案例完整图元 JSON 指纹与 ASCII 参数文件逐字节指纹。

实机测试结果见 [阶段3报告](stages/phase-3.md)及 [阶段3.1修复报告](stages/phase-3.1.md)。CI 不安装 AutoCAD，也不会运行实际出图示例。
