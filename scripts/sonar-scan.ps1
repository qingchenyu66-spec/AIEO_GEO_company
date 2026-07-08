# GEO Monitor local SonarQube scan
# Usage:
#   $env:SONAR_HOST_URL = "http://localhost:9000"
#   $env:SONAR_TOKEN = "<your-token>"
#   .\scripts\sonar-scan.ps1
#
# Optional: .\scripts\sonar-scan.ps1 -SkipCoverage

param(
    [switch]$SkipCoverage
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:SONAR_HOST_URL) {
    $env:SONAR_HOST_URL = "http://localhost:9000"
    Write-Host "SONAR_HOST_URL not set, using default $($env:SONAR_HOST_URL)"
}

if (-not $env:SONAR_TOKEN) {
    Write-Host "[ERROR] SONAR_TOKEN is not set." -ForegroundColor Red
    Write-Host "Generate a token in SonarQube: My Account -> Security -> Generate Token"
    Write-Host 'Then run: $env:SONAR_TOKEN = "your-token"; .\scripts\sonar-scan.ps1'
    exit 1
}

$scanner = Get-Command sonar-scanner -ErrorAction SilentlyContinue
if (-not $scanner) {
    Write-Host "[ERROR] sonar-scanner not found in PATH." -ForegroundColor Red
    exit 1
}

if (-not $SkipCoverage) {
    Write-Host "==> Generating Python coverage (backend/coverage.xml) ..."
    Set-Location "$Root\backend"
    python -m pip install pytest-cov -q 2>$null
    python -m pytest tests/ -q --cov=app --cov-report=xml:coverage.xml --cov-fail-under=0
    if (-not (Test-Path "coverage.xml")) {
        Write-Host "[WARN] coverage.xml was not generated." -ForegroundColor Yellow
    }
    Set-Location $Root
}

Write-Host "==> Running SonarScanner ..."
sonar-scanner -Dproject.settings=sonar-project.properties

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Scan finished: $($env:SONAR_HOST_URL)/dashboard?id=geo_monitor" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Sonar scan failed (exit $LASTEXITCODE). Check SonarQube is running and token is valid." -ForegroundColor Red
    exit $LASTEXITCODE
}
