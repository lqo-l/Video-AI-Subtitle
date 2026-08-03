$ErrorActionPreference = "Stop"
$TaskName = "YouTubeBilingualAssistant"
$BackgroundScript = Join-Path $PSScriptRoot "start-background.ps1"

if (-not (Test-Path -LiteralPath $BackgroundScript)) {
    throw "找不到后台启动脚本：$BackgroundScript"
}

# Moon Begin: register a per-user, non-elevated, hidden logon task.
$PowerShellPath = (Get-Command powershell.exe).Source
$Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$BackgroundScript`""
$Action = New-ScheduledTaskAction -Execute $PowerShellPath -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "后台启动 YouTube 双语字幕助手本机服务" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "已启用登录自启动，并已在后台启动服务。" -ForegroundColor Green
# Moon End
