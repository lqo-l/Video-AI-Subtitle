# Moon Begin
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Digest,
    [Parameter(Mandatory = $true)][string]$Version,
    [int]$HostPid = 0,
    [string]$ExtensionId = "",
    [switch]$Finalize
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$UpdateRoot = Join-Path $env:LOCALAPPDATA "YouTubeBilingualAssistant\updates"
$RunRoot = Join-Path $UpdateRoot ("run-" + [guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $RunRoot "update.zip"
$StagePath = Join-Path $RunRoot "stage"
$BackupPath = Join-Path $RunRoot "backup"
$ManagedDirectories = @("extension", "service", "scripts")
$ManagedFiles = @("requirements.txt", "README.md", "README_zh.md", "LICENSE", ".gitignore", "native-host\Program.cs")

function Write-UpdateLog([string]$Message) {
    Write-Output ("[update] " + $Message)
}

function Restore-Backup {
    foreach ($relative in $ManagedDirectories) {
        $target = Join-Path $ProjectRoot $relative
        $backup = Join-Path $BackupPath $relative
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $target -Force }
    }
    foreach ($relative in $ManagedFiles) {
        $target = Join-Path $ProjectRoot $relative
        $backup = Join-Path $BackupPath $relative
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
        if (Test-Path -LiteralPath $backup) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Move-Item -LiteralPath $backup -Destination $target -Force
        }
    }
}

if ($Finalize) {
    try {
        if ($HostPid -gt 0) {
            while (Get-Process -Id $HostPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 200 }
        }
        & (Join-Path $ProjectRoot "scripts\install-native-host.ps1") -ExtensionId $ExtensionId
        Write-UpdateLog "本机启动器已重新注册"
        exit 0
    }
    catch {
        Write-Error "本机启动器更新失败：$_"
        exit 1
    }
}

try {
    $releaseUri = [Uri]$Url
    if ($releaseUri.Scheme -ne "https" -or $releaseUri.Host -ne "github.com") { throw "更新地址无效" }
    if ($Digest -notmatch "^sha256:([0-9a-fA-F]{64})$") { throw "更新包缺少有效的 SHA-256 校验信息" }

    New-Item -ItemType Directory -Force -Path $RunRoot, $StagePath, $BackupPath | Out-Null
    Write-UpdateLog "正在下载 v$Version"
    Invoke-WebRequest -Uri $Url -OutFile $ArchivePath -UseBasicParsing
    $actualDigest = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualDigest -ne $Matches[1].ToLowerInvariant()) { throw "下载包校验失败，文件未替换" }

    Write-UpdateLog "正在校验并解压"
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $StagePath -Force
    foreach ($relative in $ManagedDirectories + $ManagedFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $StagePath $relative))) { throw "更新包不完整，缺少 $relative" }
    }

    Write-UpdateLog "正在替换程序文件"
    foreach ($relative in $ManagedDirectories) {
        $target = Join-Path $ProjectRoot $relative
        $backup = Join-Path $BackupPath $relative
        if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination $backup -Force }
        Move-Item -LiteralPath (Join-Path $StagePath $relative) -Destination $target -Force
    }
    foreach ($relative in $ManagedFiles) {
        $target = Join-Path $ProjectRoot $relative
        $backup = Join-Path $BackupPath $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target), (Split-Path -Parent $backup) | Out-Null
        if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination $backup -Force }
        Move-Item -LiteralPath (Join-Path $StagePath $relative) -Destination $target -Force
    }
    Remove-Item -LiteralPath $BackupPath -Recurse -Force
    # The current native host is still running and cannot be overwritten on Windows.
    # Recompile it immediately after Chrome closes this update connection.
    $finalizer = "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\update.ps1`" -Url `"$Url`" -Digest `"$Digest`" -Version `"$Version`" -HostPid $HostPid -ExtensionId `"$ExtensionId`" -Finalize"
    Start-Process -FilePath "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $finalizer -WindowStyle Hidden
    Write-UpdateLog "v$Version 已完成"
    exit 0
}
catch {
    Write-Error $_
    if (Test-Path -LiteralPath $BackupPath) {
        try { Restore-Backup } catch { Write-Error "恢复备份失败：$_" }
    }
    exit 1
}
finally {
    if (Test-Path -LiteralPath $RunRoot) { Remove-Item -LiteralPath $RunRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
# Moon End
