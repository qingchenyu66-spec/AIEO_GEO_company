param(
    [ValidateSet("submit", "sync", "beat", "all")]
    [string]$Role = "all",
    [int]$SubmitConcurrency = 4,
    [int]$SyncConcurrency = 8
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Backend venv not found: $Python"
}

$env:PYTHONPATH = $BackendRoot
Push-Location $BackendRoot

function Start-CeleryWindow {
    param(
        [string]$Title,
        [string[]]$CeleryArgs
    )
    $argText = ($CeleryArgs | ForEach-Object {
        if ($_ -match '[\s"]') { "'$($_ -replace "'", "''")'" } else { $_ }
    }) -join ', '
    $command = @"
Set-Location '$BackendRoot'
`$env:PYTHONPATH='$BackendRoot'
Write-Host '$Title'
& '$Python' -m celery $($CeleryArgs -join ' ')
"@
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $command)
    Write-Host "Started $Title"
}

try {
    switch ($Role) {
        "submit" {
            Start-CeleryWindow "GEO Celery Submit Worker" @(
                "-A", "app.celery_app", "worker",
                "-Q", "submit",
                "-n", "submit@localhost",
                "-c", "$SubmitConcurrency",
                "--pool=solo",
                "--loglevel=info"
            )
        }
        "sync" {
            Start-CeleryWindow "GEO Celery Sync Worker" @(
                "-A", "app.celery_app", "worker",
                "-Q", "sync",
                "-n", "sync@localhost",
                "-c", "$SyncConcurrency",
                "--pool=solo",
                "--loglevel=info"
            )
        }
        "beat" {
            Start-CeleryWindow "GEO Celery Beat" @(
                "-A", "app.celery_app", "beat",
                "--loglevel=info"
            )
        }
        "all" {
            Start-CeleryWindow "GEO Celery Submit Worker" @(
                "-A", "app.celery_app", "worker",
                "-Q", "submit",
                "-n", "submit@localhost",
                "-c", "$SubmitConcurrency",
                "--pool=solo",
                "--loglevel=info"
            )
            Start-Sleep -Seconds 1
            Start-CeleryWindow "GEO Celery Sync Worker" @(
                "-A", "app.celery_app", "worker",
                "-Q", "sync",
                "-n", "sync@localhost",
                "-c", "$SyncConcurrency",
                "--pool=solo",
                "--loglevel=info"
            )
            Start-Sleep -Seconds 1
            Start-CeleryWindow "GEO Celery Beat" @(
                "-A", "app.celery_app", "beat",
                "--loglevel=info"
            )
            Write-Host ""
            Write-Host "Celery workers and beat started in separate windows."
            Write-Host "Linux production should drop --pool=solo and run prefork workers."
        }
    }
}
finally {
    Pop-Location
}
