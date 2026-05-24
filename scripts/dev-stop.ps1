# 停止所有开发服务（读 .dev.pids，按 PID 杀进程，保底按端口清理）
param([switch]$Quiet)

$root  = Join-Path $PSScriptRoot ".."
$root  = (Resolve-Path $root).Path
$pFile = Join-Path $root ".dev.pids"
$hbFile = Join-Path $root ".dev-heartbeat"

if (-not (Test-Path $pFile)) {
    if (-not $Quiet) { Write-Host "No dev processes found (.dev.pids missing)" }
    exit 0
}

$pids    = Get-Content $pFile -Raw | ConvertFrom-Json
$stopped = 0

foreach ($name in $pids.PSObject.Properties.Name) {
    $id   = [int]$pids.$name
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($proc) {
        # 杀子进程（vite/npm 会 spawn node 子进程）
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        if (-not $Quiet) { Write-Host "Stopped $name (PID $id)" }
        $stopped++
    }
}

# 保底：按端口强杀残留进程
foreach ($port in @(8000, 5173)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        if (-not $Quiet) { Write-Host "Force-killed stale process on port $port" }
    }
}

Remove-Item $pFile  -ErrorAction SilentlyContinue
Remove-Item $hbFile -ErrorAction SilentlyContinue

if (-not $Quiet) { Write-Host "Done. $stopped service(s) stopped." }
