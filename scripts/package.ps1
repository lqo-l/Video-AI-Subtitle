$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputRoot = Join-Path $ProjectRoot "dist"
$PackagePath = Join-Path $OutputRoot "youtube-bilingual-assistant.zip"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath }

$Items = @("extension", "native-host\Program.cs", "service", "scripts", "requirements.txt", "README.md", "README_zh.md", "LICENSE", ".gitignore") | ForEach-Object { Join-Path $ProjectRoot $_ }
Compress-Archive -LiteralPath $Items -DestinationPath $PackagePath -CompressionLevel Optimal
Write-Host "已生成 $PackagePath" -ForegroundColor Green
