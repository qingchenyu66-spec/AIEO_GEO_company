# 启动 GEO 后端 API（清理占用端口后单实例运行）
param(
    [int]$Port = 8000
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
Start-Sleep -Seconds 1

$env:PYTHONPATH = $backendRoot
Set-Location $backendRoot
Write-Host "启动 uvicorn -> http://127.0.0.1:$Port"
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload --reload-dir app
