# 本地稳定性分流：同一套 app，三端口模拟快/重/回调（配合 deploy/nginx 或分别打）
# 用法：
#   cd backend\scripts
#   .\start_api_split.ps1
# 默认：快 8001 / 重 8002 / 回调 8003（均 --reload）
param(
    [int]$FastPort = 8001,
    [int]$HeavyPort = 8002,
    [int]$CallbackPort = 8003,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$backendRoot = Split-Path $PSScriptRoot -Parent
$venvPython = Join-Path $backendRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $backendRoot "storage\logs"

if (-not (Test-Path $venvPython)) {
    Write-Error "未找到虚拟环境: $venvPython"
}
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Stop-Port([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            if ($_ -and $_ -ne 0) {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
        }
}

Write-Host "清理 8001/8002/8003 旧进程..."
Stop-Port $FastPort
Stop-Port $HeavyPort
Stop-Port $CallbackPort
Start-Sleep -Seconds 1

$env:PYTHONPATH = $backendRoot
Set-Location $backendRoot
Write-Host "执行数据库迁移..."
& $venvPython -m alembic upgrade head

$reloadArgs = @()
if (-not $NoReload) {
    $reloadArgs = @("--reload", "--reload-dir", "app")
}

function Start-UvicornRole([string]$Title, [int]$Port, [string]$LogFile) {
    $logPath = Join-Path $logDir $LogFile
    $argList = @(
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", "$Port"
    ) + $reloadArgs
    $command = @"
Set-Location '$backendRoot'
`$env:PYTHONPATH='$backendRoot'
Write-Host '$Title -> http://127.0.0.1:$Port'
& '$venvPython' $($argList -join ' ') 2>&1 | Tee-Object -FilePath '$logPath' -Append
"@
    Start-Process powershell -WindowStyle Minimized -ArgumentList @("-NoProfile", "-Command", $command)
    Write-Host "Started $Title (port $Port) -> storage\logs\$LogFile"
}

# 2026-08-21 - 本地三进程同码不同口，便于对照桌面方案 Nginx 分流
Start-UvicornRole "GEO API Fast" $FastPort "api-fast.log"
Start-Sleep -Seconds 1
Start-UvicornRole "GEO API Heavy" $HeavyPort "api-heavy.log"
Start-Sleep -Seconds 1
Start-UvicornRole "GEO API Callback" $CallbackPort "api-callback.log"

Write-Host ""
Write-Host "Fast     http://127.0.0.1:$FastPort"
Write-Host "Heavy    http://127.0.0.1:$HeavyPort"
Write-Host "Callback http://127.0.0.1:$CallbackPort"
Write-Host "Vite 仍可只代理 8001；要完整分流需本地 Nginx 指向三端口。"
