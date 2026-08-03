$ErrorActionPreference = "Stop"
$TaskName = "YouTubeBilingualAssistant"

# Moon Add: removing the task does not terminate an in-progress translation.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已关闭登录自启动。当前服务会继续运行到本次注销或重启。" -ForegroundColor Yellow
} else {
    Write-Host "登录自启动尚未启用。"
}
