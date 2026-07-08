param(
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
$E2eRoot = Join-Path $PSScriptRoot ".." "e2e" | Resolve-Path
Push-Location $E2eRoot

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing e2e dependencies..."
    npm install
    npm run install:browsers
}

$BackendRoot = Join-Path $PSScriptRoot ".." "backend" | Resolve-Path
Write-Host "Granting RPA test permissions for platform account..."
Push-Location $BackendRoot
python scripts/grant_rpa_test_permissions.py
Pop-Location

if (-not (Test-Path ".env.rpa")) {
    Copy-Item ".env.rpa.example" ".env.rpa"
    Write-Host "Created .env.rpa from example — edit credentials if needed."
}

if ($Headed) {
    npm run test:headed
} else {
    npm test
}

$reportMd = Join-Path $E2eRoot "report\rpa-test-report.md"
if (Test-Path $reportMd) {
    Write-Host "`nRPA report: $reportMd"
}

Pop-Location
