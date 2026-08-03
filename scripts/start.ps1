$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "尚未安装。请先运行 scripts\install.ps1。"
}
Set-Location -LiteralPath $ProjectRoot
& $PythonPath -m uvicorn service.app.main:app --host 127.0.0.1 --port 8765
