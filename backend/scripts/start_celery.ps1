param(
    [ValidateSet("submit", "sync", "default", "beat", "all")]
    [string]$Role = "all",
    [int]$SubmitConcurrency = 4,
    [int]$SyncConcurrency = 8,
    [int]$DefaultConcurrency = 2,
    [switch]$ShowWindows
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $BackendRoot "storage\logs"

if (-not (Test-Path $Python)) {
    throw "Backend venv not found: $Python"
}

function Stop-ExistingCelery {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $cmd = $_.CommandLine
            if (-not $cmd) { return $false }
            if ($cmd -match 'celery -A app\.celery_app (worker|beat|flower)') { return $true }
            if ($cmd -match 'celery_worker_(submit|sync|default)\.cmd' -or $cmd -match 'celery_beat\.cmd') { return $true }
            if ($_.Name -eq 'powershell.exe' -and $cmd -match 'GEO Celery (Submit|Sync|Default|Beat|Flower)') { return $true }
            return $false
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped old Celery launcher PID $($_.ProcessId)"
        }
    Start-Sleep -Seconds 1
}

function Start-CeleryRole {
    param(
        [string]$Title,
        [string]$LogFile,
        [string[]]$CeleryArgs
    )

    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir | Out-Null
    }

    $logPath = Join-Path $LogDir $LogFile
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$stamp] $Title starting"

    # 不加 -NoExit：Celery 退出后窗口/进程一起结束，不会留空 PowerShell
    $command = @"
Set-Location '$BackendRoot'
`$env:PYTHONPATH='$BackendRoot'
Write-Host '$Title'
try {
    & '$Python' -m celery $($CeleryArgs -join ' ') 2>&1 | Tee-Object -FilePath '$logPath' -Append
} finally {
    `$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path '$logPath' -Value "[`$ts] $Title stopped"
}
"@

    $psArgs = @("-NoProfile", "-Command", $command)
    if ($ShowWindows) {
        Start-Process powershell -ArgumentList $psArgs
    } else {
        Start-Process powershell -WindowStyle Hidden -ArgumentList $psArgs
    }
    Write-Host "Started $Title -> storage\logs\$LogFile"
}

Stop-ExistingCelery
$env:PYTHONPATH = $BackendRoot
Push-Location $BackendRoot

try {
    $roles = @()
    switch ($Role) {
        "submit" { $roles = @("submit") }
        "sync" { $roles = @("sync") }
        "default" { $roles = @("default") }
        "beat" { $roles = @("beat") }
        "all" { $roles = @("submit", "sync", "default", "beat") }
    }

    foreach ($item in $roles) {
        switch ($item) {
            "submit" {
                Start-CeleryRole "GEO Celery Submit Worker" "celery-worker-submit.log" @(
                    "-A", "app.celery_app", "worker",
                    "-Q", "submit",
                    "-n", "submit@$env:COMPUTERNAME",
                    "-c", "$SubmitConcurrency",
                    "--pool=solo",
                    "--loglevel=info"
                )
            }
            "sync" {
                Start-CeleryRole "GEO Celery Sync Worker" "celery-worker-sync.log" @(
                    "-A", "app.celery_app", "worker",
                    "-Q", "sync",
                    "-n", "sync@$env:COMPUTERNAME",
                    "-c", "$SyncConcurrency",
                    "--pool=solo",
                    "--loglevel=info"
                )
            }
            "default" {
                Start-CeleryRole "GEO Celery Default Worker" "celery-worker-default.log" @(
                    "-A", "app.celery_app", "worker",
                    "-Q", "default",
                    "-n", "default@$env:COMPUTERNAME",
                    "-c", "$DefaultConcurrency",
                    "--pool=solo",
                    "--loglevel=info"
                )
            }
            "beat" {
                Start-CeleryRole "GEO Celery Beat" "celery-beat.log" @(
                    "-A", "app.celery_app", "beat",
                    "--loglevel=info"
                )
            }
        }
        if ($roles.Count -gt 1) {
            Start-Sleep -Seconds 1
        }
    }

    if ($ShowWindows) {
        Write-Host ""
        Write-Host "Celery started in visible windows (close automatically when each process exits)."
    } else {
        Write-Host ""
        Write-Host "Celery started in background (no extra windows). Logs: backend\storage\logs\celery-*.log"
        Write-Host "Need live output? Run: .\start_celery.ps1 -Role all -ShowWindows"
    }
    Write-Host "Stop all: .\cleanup_celery_workers.ps1"
}
finally {
    Pop-Location
}
