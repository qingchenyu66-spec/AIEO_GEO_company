param(
    [ValidateSet("install", "uninstall", "status", "start", "stop")]
    [string]$Action = "install"
)

$ErrorActionPreference = "Stop"

function Invoke-SchTasks {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $output = & schtasks @Args 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($exitCode -ne 0) {
        throw ($output | Out-String).Trim()
    }
    return $output
}

$BackendRoot = Split-Path -Parent $PSScriptRoot
$BeatVbs = Join-Path $PSScriptRoot "celery_beat_hidden.vbs"
$SubmitVbs = Join-Path $PSScriptRoot "celery_worker_submit_hidden.vbs"
$SyncVbs = Join-Path $PSScriptRoot "celery_worker_sync_hidden.vbs"
$FlowerVbs = Join-Path $PSScriptRoot "celery_flower_hidden.vbs"

$BeatTaskName = "GEO-Celery-Beat"
$SubmitTaskName = "GEO-Celery-Worker-Submit"
$SyncTaskName = "GEO-Celery-Worker-Sync"
$FlowerTaskName = "GEO-Celery-Flower"
$LegacyTasks = @("GEO-Monitor-Submit", "GEO-Monitor-Sync")

function Test-TaskExists([string]$Name) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = schtasks /Query /TN $Name
    $exists = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
    return $exists
}

function Remove-CeleryTask([string]$Name) {
    if (Test-TaskExists $Name) {
        Invoke-SchTasks /Delete /TN $Name /F | Out-Null
        Write-Host "Removed task: $Name"
    }
}

function Disable-LegacyMonitorTasks {
    foreach ($name in $LegacyTasks) {
        if (Test-TaskExists $name) {
            schtasks /Change /TN $name /DISABLE | Out-Null
            Write-Host "Disabled legacy task: $name"
        }
    }
}

function Install-CeleryTasks {
    foreach ($path in @($BeatVbs, $SubmitVbs, $SyncVbs, $FlowerVbs)) {
        if (-not (Test-Path $path)) {
            throw "Missing script: $path"
        }
    }
    if (-not (Test-Path (Join-Path $BackendRoot ".venv\Scripts\python.exe"))) {
        throw "Backend venv not found. Run setup in $BackendRoot first."
    }

    Remove-CeleryTask $BeatTaskName
    Remove-CeleryTask $SubmitTaskName
    Remove-CeleryTask $SyncTaskName
    Remove-CeleryTask $FlowerTaskName

    Invoke-SchTasks /Create `
        /TN $BeatTaskName `
        /TR "wscript.exe `"$BeatVbs`"" `
        /SC ONLOGON `
        /RL LIMITED `
        /F | Out-Null

    Invoke-SchTasks /Create `
        /TN $SubmitTaskName `
        /TR "wscript.exe `"$SubmitVbs`"" `
        /SC ONLOGON `
        /RL LIMITED `
        /F | Out-Null

    Invoke-SchTasks /Create `
        /TN $SyncTaskName `
        /TR "wscript.exe `"$SyncVbs`"" `
        /SC ONLOGON `
        /RL LIMITED `
        /F | Out-Null

    Invoke-SchTasks /Create `
        /TN $FlowerTaskName `
        /TR "wscript.exe `"$FlowerVbs`"" `
        /SC ONLOGON `
        /RL LIMITED `
        /F | Out-Null

    Disable-LegacyMonitorTasks

    Write-Host "Installed Celery logon tasks:"
    Write-Host "  $BeatTaskName"
    Write-Host "  $SubmitTaskName"
    Write-Host "  $SyncTaskName"
    Write-Host "  $FlowerTaskName"
    Write-Host "Flower dashboard: http://127.0.0.1:5555"
    Write-Host "Logs:"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\celery-beat.log')"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\celery-worker-submit.log')"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\celery-worker-sync.log')"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\celery-flower.log')"
}

function Show-CeleryTaskStatus {
    foreach ($name in @($BeatTaskName, $SubmitTaskName, $SyncTaskName, $FlowerTaskName) + $LegacyTasks) {
        if (Test-TaskExists $name) {
            Write-Host "=== $name ==="
            schtasks /Query /TN $name /V /FO LIST | Select-String "TaskName|Status|Scheduled Task State|Next Run|Last Run|Task To Run"
            Write-Host ""
        } else {
            Write-Host "$name : not installed"
        }
    }
}

function Start-CeleryProcesses {
    foreach ($vbs in @($SubmitVbs, $SyncVbs, $BeatVbs, $FlowerVbs)) {
        Start-Process wscript.exe -ArgumentList "`"$vbs`"" -WindowStyle Hidden
        Start-Sleep -Seconds 1
    }
    Write-Host "Started Celery beat/submit/sync/flower in background."
    Write-Host "Flower: http://127.0.0.1:5555"
}

function Stop-CeleryProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -like "*celery -A app.celery_app beat*" -or
                $_.CommandLine -like "*celery -A app.celery_app worker -Q submit*" -or
                $_.CommandLine -like "*celery -A app.celery_app worker -Q sync*" -or
                $_.CommandLine -like "*celery -A app.celery_app flower*" -or
                $_.CommandLine -like "*start_flower.py*"
            )
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped PID $($_.ProcessId)"
        }
}

switch ($Action) {
    "install" { Install-CeleryTasks }
    "uninstall" {
        Remove-CeleryTask $BeatTaskName
        Remove-CeleryTask $SubmitTaskName
        Remove-CeleryTask $SyncTaskName
        Remove-CeleryTask $FlowerTaskName
    }
    "status" { Show-CeleryTaskStatus }
    "start" { Start-CeleryProcesses }
    "stop" { Stop-CeleryProcesses }
}
