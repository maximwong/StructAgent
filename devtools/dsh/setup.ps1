param(
    [Parameter(Mandatory=$true)][string]$DshCli,
    [string]$Python = 'python',
    [string]$Model = 'deepseek-flash',
    [string]$Codex = 'codex'
)
$ErrorActionPreference = 'Stop'
$DshRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DshLauncher = (Resolve-Path -LiteralPath $DshCli).Path
$DshEnv = Join-Path $DshRepo '.venv-dsh'
& $Python -m venv $DshEnv
if ($LASTEXITCODE -ne 0) { throw 'Cannot create developer environment' }
$DshPython = Join-Path $DshEnv 'Scripts\python.exe'
& $DshPython -m pip install --index-url https://pypi.org/simple --no-deps -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cannot install developer dependencies' }
# SDK metadata requires its bundled runtime. We intentionally use dsh_bin to reuse the desktop CLI.
& $DshPython -m pip install --index-url https://pypi.org/simple 'pydantic-core==2.46.5' 'annotated-types==0.8.0' 'typing-extensions==4.16.0' 'typing-inspection==0.4.4'
if ($LASTEXITCODE -ne 0) { throw 'Cannot install SDK supporting dependencies' }
$DshPrivate = Join-Path $DshRepo '.dsh-tasks'
New-Item -ItemType Directory -Path $DshPrivate -Force | Out-Null
@{dsh_bin=$DshLauncher; model=$Model} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DshPrivate 'config.json') -Encoding utf8
& $Codex mcp add structagent-dsh -- $DshPython (Join-Path $PSScriptRoot 'server.py')
if ($LASTEXITCODE -ne 0) { throw 'Cannot register developer MCP server' }
Write-Output 'Developer bridge installed. Restart/reload Codex if this chat has not discovered the tools.'
