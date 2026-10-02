# 固定 Demo 环境

基线：Windows x64、CPython 3.12.14、桌面 AutoCAD 2022。Python 包及其传递依赖全部固定在 `requirements-demo.txt`；Python 版本在 `.python-version`。使用本机 NTFS 磁盘存放项目数据，不把 SQLite 或原子快照放在网络共享盘。

已有匹配 Python 时，从仓库根目录执行：

```powershell
python -m venv .venv-demo
.venv-demo/Scripts/python.exe -m pip install --only-binary=:all: --require-hashes -r requirements-demo.lock
.venv-demo/Scripts/python.exe -m pip check
.venv-demo/Scripts/python.exe -m examples.environment_check
.venv-demo/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
```

环境检查不通过时不要开始演示。它检查 Python 的完整版本、位数、Windows 平台及全部固定包版本；它不替代 AutoCAD 许可、Unicode 引擎、脚本信任和启动提示的人工配置。不要使用 `--system-site-packages`。

新设备没有该 Python 时，可先在一个已有 Python 环境安装固定的安装工具，随后创建独立 Demo 环境：

```powershell
python -m pip install uv==0.12.21
uv python install 3.12.14
uv venv --seed --python 3.12.14 .venv-demo
.venv-demo/Scripts/python.exe -m pip install --only-binary=:all: --require-hashes -r requirements-demo.lock
.venv-demo/Scripts/python.exe -m examples.environment_check
```

uv 使用 Astral 的 Python 独立构建；这与 `actions/setup-python` 的 Windows 构建来源不同。本仓库 CI 固定 uv 安装器及 Python 版本，并在新环境运行同样的检查和回归。安装方式依据 [uv 官方 GitHub Actions 文档](https://docs.astral.sh/uv/guides/integration/github/) 和 [Python 版本文档](https://docs.astral.sh/uv/concepts/python-versions/)。阶段5.1已补充依赖SHA256锁、运行时归档及离线安装器，见 [离线部署说明](offline-deployment.md)；阶段8仍需完成正式版本发布与冻结。

旧 GUI 仍可使用原启动方式。需要确保使用本次独立环境时，执行 `.venv-demo/Scripts/python.exe legacy/rc_floor/app.py` 前先查阅旧入口说明；工具示例直接使用上述 Python 的绝对/相对可执行路径，避免启动器选择其他运行时。

桌面 CAD：先打开 AutoCAD 2022，处理启动及加载提示，使程序空闲；然后运行：

```powershell
.venv-demo/Scripts/python.exe -m examples.floor_cad
.venv-demo/Scripts/python.exe -m examples.cad_recovery
```

`cad_recovery` 不把中断的旧任务变成成功任务。恢复后显式重新运行出图；每次创建新目录。详见 [CAD 工具恢复说明](floor-cad-tool.md)。
