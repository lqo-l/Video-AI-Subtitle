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

function Write-UpdateProgress([string]$Stage, [long]$Downloaded, [long]$Total, [double]$Speed = 0) {
    Write-Output ("YTBA_UPDATE_PROGRESS|" + $Stage + "|" + $Downloaded + "|" + $Total + "|" + $Speed.ToString("0.0", [Globalization.CultureInfo]::InvariantCulture))
}

function Download-UpdateArchive {
    param([string]$SourceUrl, [string]$Destination)
    $request = [Net.HttpWebRequest]::Create($SourceUrl)
    $request.AllowAutoRedirect = $true
    $request.Timeout = 30000
    $response = $request.GetResponse()
    try {
        $total = [long]$response.ContentLength
        $input = $response.GetResponseStream()
        $output = [IO.File]::Open($Destination, [IO.FileMode]::Create, [IO.FileAccess]::Write)
        try {
            $buffer = New-Object byte[] (1024 * 128)
            $downloaded = [long]0
            $clock = [Diagnostics.Stopwatch]::StartNew()
            $lastReport = -1
            while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $output.Write($buffer, 0, $read)
                $downloaded += $read
                if ($downloaded - $lastReport -ge 131072 -or ($total -gt 0 -and $downloaded -eq $total)) {
                    $speed = $downloaded / [Math]::Max(0.001, $clock.Elapsed.TotalSeconds)
                    Write-UpdateProgress "正在下载更新包" $downloaded $total $speed
                    $lastReport = $downloaded
                }
            }
        }
        finally {
            $output.Dispose()
            $input.Dispose()
        }
    }
    finally { $response.Dispose() }
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
    $currentVersion = (Get-Content -Raw (Join-Path $ProjectRoot "extension\manifest.json") | ConvertFrom-Json).version
    Write-UpdateLog "更新目标：$ProjectRoot（当前版本：$currentVersion，目标版本：$Version）"
    Write-UpdateProgress "正在连接更新服务器" 0 0 0
    Download-UpdateArchive -SourceUrl $Url -Destination $ArchivePath
    Write-UpdateProgress "正在校验更新包" 1 1 0
    $actualDigest = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualDigest -ne $Matches[1].ToLowerInvariant()) { throw "下载包校验失败，文件未替换" }

    Write-UpdateLog "正在校验并解压"
    Write-UpdateProgress "正在校验并解压" 1 1 0
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $StagePath -Force
    foreach ($relative in $ManagedDirectories + $ManagedFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $StagePath $relative))) { throw "更新包不完整，缺少 $relative" }
    }

    Write-UpdateLog "正在替换程序文件"
    Write-UpdateProgress "正在替换程序文件" 1 1 0
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
    $installedVersion = (Get-Content -Raw (Join-Path $ProjectRoot "extension\manifest.json") | ConvertFrom-Json).version
    if ([string]$installedVersion -ne [string]$Version) {
        throw "更新目录版本校验失败：预期 $Version，实际 $installedVersion，目录 $ProjectRoot"
    }
    Remove-Item -LiteralPath $BackupPath -Recurse -Force
    # The current native host is still running and cannot be overwritten on Windows.
    # Recompile it immediately after Chrome closes this update connection.
    $finalizer = "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\update.ps1`" -Url `"$Url`" -Digest `"$Digest`" -Version `"$Version`" -HostPid $HostPid -ExtensionId `"$ExtensionId`" -Finalize"
    Start-Process -FilePath "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $finalizer -WindowStyle Hidden
    Write-UpdateLog "v$Version 已完成"
    Write-UpdateProgress "更新完成，正在重载扩展" 1 1 0
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
