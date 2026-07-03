# 启动 GEO 后端 API（清理占用端口后单实例运行）
param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"
$backendRoot = Split-Path $PSScriptRoot -Parent
$venvPython = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "未找到虚拟环境: $venvPython"
}

Write-Host "清理端口 $Port 上的旧进程..."
Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        if ($_ -and $_ -ne 0) {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }
# uvicorn --reload 父进程退出后，Windows 上可能残留 spawn_main 子进程仍占用端口
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match 'uvicorn app\.main:app' -or
        $_.CommandLine -match 'multiprocessing\.spawn import spawn_main'
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

$env:PYTHONPATH = $backendRoot
Set-Location $backendRoot
Write-Host "执行数据库迁移..."
& $venvPython -m alembic upgrade head
Write-Host "启动 uvicorn -> http://127.0.0.1:$Port"
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload --reload-dir app
