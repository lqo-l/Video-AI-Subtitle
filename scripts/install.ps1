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

Write-Host "依赖安装完成。" -ForegroundColor Green
Write-Host "加载 Chrome 扩展后，请复制扩展 ID 并运行："
Write-Host '.\scripts\install-native-host.ps1 -ExtensionId "你的扩展ID"' -ForegroundColor Cyan
Write-Host "可在扩展的“更多设置”中预下载 Whisper，或提前执行："
Write-Host '.\scripts\download-model.ps1 -Model small -Source auto' -ForegroundColor Cyan
