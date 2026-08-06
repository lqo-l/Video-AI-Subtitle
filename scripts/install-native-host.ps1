param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$HostDirectory = Join-Path $ProjectRoot "native-host"
$SourcePath = Join-Path $HostDirectory "Program.cs"
$ExecutablePath = Join-Path $HostDirectory "youtube-bilingual-native-host.exe"
$ManifestPath = Join-Path $HostDirectory "com.moon.youtube_bilingual_assistant.json"
$Compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path -LiteralPath $Compiler)) { throw "未找到 .NET Framework C# 编译器。" }

# Moon Begin: compile and register Chrome's user-scoped Native Messaging host.
& $Compiler /nologo /target:exe /out:$ExecutablePath /reference:System.Web.Extensions.dll $SourcePath
if ($LASTEXITCODE -ne 0) { throw "本机启动器编译失败。" }

$Manifest = @{
    name = "com.moon.youtube_bilingual_assistant"
    description = "视频 AI 双语字幕助手本机启动器"
    path = $ExecutablePath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($ManifestPath, $Manifest, (New-Object System.Text.UTF8Encoding($false)))

$RegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.moon.youtube_bilingual_assistant"
New-Item -Path $RegistryPath -Force | Out-Null
Set-Item -Path $RegistryPath -Value $ManifestPath
Write-Host "本机启动器已注册。扩展点击处理时会自动启动服务。" -ForegroundColor Green
# Moon End
