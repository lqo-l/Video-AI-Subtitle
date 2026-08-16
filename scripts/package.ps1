$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputRoot = Join-Path $ProjectRoot "dist"
$PackagePath = Join-Path $OutputRoot "youtube-bilingual-assistant.zip"
$StagePath = Join-Path $OutputRoot "package-stage"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath }
if (Test-Path -LiteralPath $StagePath) { Remove-Item -LiteralPath $StagePath -Recurse -Force }
New-Item -ItemType Directory -Force -Path $StagePath | Out-Null

# Moon Modified: build a clean project-root archive. The previous literal-path archive
# put Program.cs at the root and included runtime __pycache__ files, breaking a fresh install.
foreach ($Directory in @("extension", "service", "scripts")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Directory) -Destination (Join-Path $StagePath $Directory) -Recurse -Force
}
Get-ChildItem -LiteralPath (Join-Path $StagePath "service") -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $StagePath "native-host") | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "native-host\Program.cs") -Destination (Join-Path $StagePath "native-host\Program.cs") -Force
foreach ($File in @("requirements.txt", "README.md", "README_zh.md", "LICENSE", ".gitignore")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $File) -Destination (Join-Path $StagePath $File) -Force
}
$ArchiveItems = Get-ChildItem -LiteralPath $StagePath | Select-Object -ExpandProperty FullName
Compress-Archive -LiteralPath $ArchiveItems -DestinationPath $PackagePath -CompressionLevel Optimal
Remove-Item -LiteralPath $StagePath -Recurse -Force
Write-Host "已生成 $PackagePath" -ForegroundColor Green
