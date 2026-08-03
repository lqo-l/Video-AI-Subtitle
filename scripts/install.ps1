$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python。请安装 Python 3.11 x64 后重试。"
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    python -m venv $VenvPath
}

$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "未找到 ffmpeg。请执行 winget install Gyan.FFmpeg，之后重新打开终端。"
}

& (Join-Path $PSScriptRoot "enable-autostart.ps1")

Write-Host "安装完成。本机服务将随 Windows 登录自动在后台启动。" -ForegroundColor Green
Write-Host "首次使用 Whisper 时会自动下载所选模型。"
