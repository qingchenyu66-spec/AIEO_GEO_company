param(
    [ValidateSet("install", "uninstall", "status")]
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
$SubmitVbs = Join-Path $PSScriptRoot "run_due_scheduled_tasks_hidden.vbs"
$SyncVbs = Join-Path $PSScriptRoot "sync_pending_monitor_tasks_hidden.vbs"
$SubmitTaskName = "GEO-Monitor-Submit"
$SyncTaskName = "GEO-Monitor-Sync"

function Test-TaskExists([string]$Name) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = schtasks /Query /TN $Name
    $exists = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
    return $exists
}

function Remove-MonitorTask([string]$Name) {
    if (Test-TaskExists $Name) {
        Invoke-SchTasks /Delete /TN $Name /F | Out-Null
        Write-Host "Removed task: $Name"
    }
}

function Install-MonitorTasks {
    if (-not (Test-Path $SubmitVbs)) {
        throw "Missing script: $SubmitVbs"
    }
    if (-not (Test-Path $SyncVbs)) {
        throw "Missing script: $SyncVbs"
    }
    if (-not (Test-Path (Join-Path $BackendRoot ".venv\Scripts\python.exe"))) {
        throw "Backend venv not found. Run setup in $BackendRoot first."
    }

    Remove-MonitorTask $SubmitTaskName
    Remove-MonitorTask $SyncTaskName

    # Submit due schedules every 10 minutes between 09:00 and 21:00.
    Invoke-SchTasks /Create `
        /TN $SubmitTaskName `
        /TR "wscript.exe `"$SubmitVbs`"" `
        /SC MINUTE `
        /MO 10 `
        /ST 09:00 `
        /DU 12:00 `
        /RL LIMITED `
        /F | Out-Null

    Invoke-SchTasks /Create `
        /TN $SyncTaskName `
        /TR "wscript.exe `"$SyncVbs`"" `
        /SC MINUTE `
        /MO 5 `
        /RL LIMITED `
        /F | Out-Null

    Write-Host "Installed Windows scheduled tasks:"
    Write-Host "  $SubmitTaskName  -> every 10 min, 09:00-21:00, submit due monitor jobs"
    Write-Host "  $SyncTaskName    -> every 5 min, sync pending monitor results"
    Write-Host "Logs:"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\scheduler.log')"
    Write-Host "  $(Join-Path $BackendRoot 'storage\logs\sync.log')"
}

function Show-MonitorTaskStatus {
    foreach ($name in @($SubmitTaskName, $SyncTaskName)) {
        if (Test-TaskExists $name) {
            Write-Host "=== $name ==="
            Invoke-SchTasks /Query /TN $name /V /FO LIST | Select-String "TaskName|Status|Next Run Time|Last Run Time|Last Result|Task To Run"
            Write-Host ""
        } else {
            Write-Host "$name : not installed"
        }
    }
}

switch ($Action) {
    "install" { Install-MonitorTasks }
    "uninstall" {
        Remove-MonitorTask $SubmitTaskName
        Remove-MonitorTask $SyncTaskName
    }
    "status" { Show-MonitorTaskStatus }
}
