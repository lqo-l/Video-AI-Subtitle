$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $env:LOCALAPPDATA "YouTubeBilingualAssistant"

# Moon Begin: silent entry point used by the Windows logon task.
try {
    $Health = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2
    if ($Health.ok) { exit 0 }
} catch {
    # Expected when the service has not started yet.
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "尚未安装本机服务。"
}

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
Set-Location -LiteralPath $ProjectRoot
$LogPath = Join-Path $LogDirectory "service.log"
& $PythonPath -m uvicorn service.app.main:app --host 127.0.0.1 --port 8765 *>> $LogPath
# Moon End
