# 启动 uvicorn + ARQ worker + Vite，记录 PID，启动 watchdog 自动清理
param(
    [int]$IdleMinutes = 30   # 超过此分钟数无 Claude 活动则自动停服务
)

$root       = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$venvBin    = Join-Path $backendDir "venv\Scripts"
$pFile      = Join-Path $root ".dev.pids"
$hbFile     = Join-Path $root ".dev-heartbeat"

# 如果之前有遗留进程，先清理
if (Test-Path $pFile) {
    Write-Host "Cleaning up previous dev processes..."
    & "$PSScriptRoot\dev-stop.ps1"
    Start-Sleep -Seconds 1
}

# 保底：清理端口上的残留进程
foreach ($port in @(8000, 5173)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "Cleared stale process on port $port"
    }
}

$trackedPids = @{}

# ── uvicorn ──────────────────────────────────────────────────────────────────
$uvicorn = Start-Process `
    -FilePath (Join-Path $venvBin "uvicorn.exe") `
    -ArgumentList "main:app --reload --port 8000" `
    -WorkingDirectory $backendDir `
    -PassThru -WindowStyle Minimized
$trackedPids["uvicorn"] = $uvicorn.Id
Write-Host "uvicorn     started (PID $($uvicorn.Id))  → http://localhost:8000"

# ── ARQ worker ───────────────────────────────────────────────────────────────
$arq = Start-Process `
    -FilePath (Join-Path $venvBin "python.exe") `
    -ArgumentList "-m arq app.tasks.worker.WorkerSettings" `
    -WorkingDirectory $backendDir `
    -PassThru -WindowStyle Minimized
$trackedPids["arq"] = $arq.Id
Write-Host "arq worker  started (PID $($arq.Id))"

# ── Vite dev server ──────────────────────────────────────────────────────────
$vite = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList "/c npm run dev" `
    -WorkingDirectory $frontendDir `
    -PassThru -WindowStyle Minimized
$trackedPids["vite"] = $vite.Id
Write-Host "vite        started (PID $($vite.Id))  → http://localhost:5173"

# ── watchdog ─────────────────────────────────────────────────────────────────
$watchdog = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NonInteractive -WindowStyle Hidden -File `"$PSScriptRoot\dev-watchdog.ps1`" -IdleMinutes $IdleMinutes" `
    -PassThru -WindowStyle Hidden
$trackedPids["watchdog"] = $watchdog.Id

# 写 PID 文件 + 初始 heartbeat
$trackedPids | ConvertTo-Json | Out-File -FilePath $pFile  -Encoding utf8
Get-Date -Format o        | Out-File -FilePath $hbFile -Encoding utf8 -NoNewline

Write-Host ""
Write-Host "All services running. Auto-kill after ${IdleMinutes}min of Claude inactivity."
Write-Host "Manual stop: .\scripts\dev-stop.ps1"
