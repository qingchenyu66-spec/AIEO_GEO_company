# 清理重复 Celery 进程（beat / submit / sync / default / flower）
$ErrorActionPreference = "Stop"

Write-Host "Stopping Celery-related processes..."
$patterns = @(
    "celery -A app.celery_app",
    "celery_worker_submit.cmd",
    "celery_worker_sync.cmd",
    "celery_worker_default.cmd",
    "celery_beat.cmd",
    "celery_flower",
    "start_flower.py"
)

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return $false }
        foreach ($pattern in $patterns) {
            if ($cmd -like "*$pattern*") { return $true }
        }
        return $false
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped PID $($_.ProcessId)"
    }

Start-Sleep -Seconds 1
Write-Host "Celery cleanup finished."
