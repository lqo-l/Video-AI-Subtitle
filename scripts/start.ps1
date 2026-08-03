$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "尚未安装。请先运行 scripts\install.ps1。"
}

# Moon Add: repeated manual or startup launches must not compete for port 8765.
try {
    $Health = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2
    if ($Health.ok) {
        Write-Host "本机服务已经运行，无需重复启动。" -ForegroundColor Green
        exit 0
    }
} catch {
    # No healthy instance is running; continue with normal startup.
}

Set-Location -LiteralPath $ProjectRoot
& $PythonPath -m uvicorn service.app.main:app --host 127.0.0.1 --port 8765
