# Windows x64 离线环境

阶段5.1已在本机制作并验证CPython 3.12.14运行时及11个固定依赖的离线包。可复用源码、依赖SHA256和运行时归档SHA256在仓库；二进制包仅在本机 `verification/phase-5.1/offline/bundle/`，未上传公共仓库，也不是v0.1-demo冻结发布。

`deployment/offline-lock.json` 是受Git版本管理的制品清单，`requirements-demo.lock` 是相同11个wheel的pip哈希锁。全部wheel与官方PyPI对应版本的文件摘要核对通过。运行时来源为本机已有的CPython独立构建，打包时排除site-packages、缓存及脚本启动器，保留标准库、ensurepip、DLL、Tcl和许可证文件。它不包含AutoCAD、API密钥、项目状态或图纸。

已有匹配Python的设备可按哈希在线安装：

```powershell
python -m pip install --only-binary=:all: --require-hashes -r requirements-demo.lock
```

仅支持Windows x64 / CPython 3.12；其他平台的wheel不在此锁范围。pip的哈希安装与离线来源选项依据 [安全安装文档](https://pip.pypa.io/en/stable/topics/secure-installs/) 和 [下载文档](https://pip.pypa.io/en/stable/cli/pip_download/)。不要为了安装成功关闭哈希校验。

## 在另一台设备安装

先复制匹配的仓库版本和完整 `bundle/` 到新设备。建议将bundle放在仓库 `data/runtime/offline-bundle/`；该目录被Git忽略。

如果已有Python，从仓库根目录执行：

```powershell
python -m deployment.offline verify --bundle data/runtime/offline-bundle
python -m deployment.offline install --bundle data/runtime/offline-bundle --destination data/runtime/offline-demo
data/runtime/offline-demo/venv/Scripts/python.exe -m examples.environment_check
```

目标安装目录必须不存在。安装器对照仓库锁核对manifest、运行时、全部wheel和requirements，检查压缩包路径，再创建新环境。依赖安装强制 `--isolated --no-index --only-binary=:all: --require-hashes`，不会联网补包；损坏/缺失包或已有目标环境均停止。失败环境保留用于诊断，重新尝试使用新的目标目录。

如果新设备没有Python，先在PowerShell核对锁中的运行时摘要，再解压出启动用Python：

```powershell
$demoBundle = (Resolve-Path data/runtime/offline-bundle).Path
$demoLock = Get-Content deployment/offline-lock.json -Raw | ConvertFrom-Json
$demoZip = Join-Path $demoBundle 'runtime.zip'
if ((Get-FileHash -LiteralPath $demoZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $demoLock.runtime.sha256) {
    throw 'Runtime checksum mismatch'
}
if (Test-Path -LiteralPath data/runtime/offline-bootstrap) { throw 'Bootstrap destination must be new' }
Expand-Archive -LiteralPath $demoZip -DestinationPath data/runtime/offline-bootstrap
data/runtime/offline-bootstrap/python.exe -m deployment.offline install --bundle data/runtime/offline-bundle --destination data/runtime/offline-demo
data/runtime/offline-demo/venv/Scripts/python.exe -m examples.environment_check
```

随后运行根目录回归及 `legacy/rc_floor/` 的原回归。API密钥依旧每台设备独立配置；自然语言云解析需要网络，AutoCAD需要单独安装、许可及脚本信任配置。离线安装成功不表示这些外部服务也可离线运行。

## 维护包

固定依赖下载到新的wheel目录后，使用同一个匹配运行时构建：

```powershell
python -m pip download --only-binary=:all: --no-deps -r requirements-demo.lock --dest data/runtime/wheels
python -m deployment.offline build --runtime-source <运行时目录> --wheelhouse data/runtime/wheels --bundle data/runtime/new-bundle
```

输出目录必须是新的且不在输入目录内。成员排序和时间戳固定；本机重复构建与仓库锁完全一致。来源构建变化也可能使运行时摘要变化；构建器会拒绝不同制品，需要独立审核和完整回归后再更新锁，不能直接覆盖已验收包。阶段8仍需建立正式发布与冻结归档。
