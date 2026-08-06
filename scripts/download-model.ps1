# Moon Begin
param(
    [ValidateSet("tiny", "base", "small", "medium")]
    [string]$Model = "small",
    [ValidateSet("auto", "mirror", "official")]
    [string]$Source = "auto",
    [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "尚未安装依赖，请先运行 .\scripts\install.ps1"
}

$env:YTBA_DOWNLOAD_MODEL = $Model
$env:YTBA_DOWNLOAD_SOURCE = $Source
$env:YTBA_DOWNLOAD_PATH = $ModelPath
$downloadCode = @'
import os
from service.app.pipeline import _prepare_whisper_model

def show(percent, downloaded, total, speed, source):
    size = lambda value: f"{value / 1024 / 1024:.1f} MB"
    detail = f"{size(downloaded)} / {size(total)}" if total else "正在连接"
    rate = f" · {size(speed)}/s" if speed else ""
    print(f"\r[{source}] {percent:3d}% · {detail}{rate}", end="", flush=True)

path = _prepare_whisper_model(
    os.environ["YTBA_DOWNLOAD_MODEL"], show,
    os.environ.get("YTBA_DOWNLOAD_PATH", ""),
    os.environ.get("YTBA_DOWNLOAD_SOURCE", "auto"),
)
print(f"\n模型已准备完成：{path}")
'@
Push-Location $ProjectRoot
try {
    $downloadCode | & $PythonPath -
} finally {
    Pop-Location
    Remove-Item Env:YTBA_DOWNLOAD_MODEL, Env:YTBA_DOWNLOAD_SOURCE, Env:YTBA_DOWNLOAD_PATH -ErrorAction SilentlyContinue
}
# Moon End
