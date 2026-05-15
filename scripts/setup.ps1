$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

Write-Host "Setting up Naukri Apply Assistant..." -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python was not found on PATH." -ForegroundColor Red
    Write-Host "Install Python 3.11 or newer from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'."
    exit 1
}

$pythonVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $pythonVersion.Split(".")
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    Write-Host "Python 3.11 or newer is required. Found Python $pythonVersion." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
else {
    Write-Host "Virtual environment already exists. Reusing .venv." -ForegroundColor Yellow
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Could not find .venv Python at $VenvPython." -ForegroundColor Red
    exit 1
}

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip

Write-Host "Installing project dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install -e ".[dev]"

Write-Host "Installing Playwright Chromium browser..." -ForegroundColor Cyan
& $VenvPython -m playwright install chromium

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next commands:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  naukri-assistant init"
Write-Host "  naukri-assistant login"
Write-Host "  naukri-assistant run"
