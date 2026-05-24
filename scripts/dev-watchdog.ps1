# 独立后台进程：监控 .dev-heartbeat，超过 $IdleMinutes 分钟无活动则自动停服务
param(
    [int]$IdleMinutes = 30
)

$root   = Split-Path -Parent $PSScriptRoot
$hbFile = Join-Path $root ".dev-heartbeat"
$pFile  = Join-Path $root ".dev.pids"
$stop   = Join-Path $PSScriptRoot "dev-stop.ps1"

while ($true) {
    Start-Sleep -Seconds 60

    # .dev.pids 不存在说明服务已被手动停止，watchdog 退出
    if (-not (Test-Path $pFile)) { exit 0 }

    $ref = if (Test-Path $hbFile) { (Get-Item $hbFile).LastWriteTime } `
           else                   { (Get-Item $pFile).LastWriteTime  }

    $idle = ((Get-Date) - $ref).TotalMinutes
    if ($idle -gt $IdleMinutes) {
        & $stop --quiet
        exit 0
    }
}
