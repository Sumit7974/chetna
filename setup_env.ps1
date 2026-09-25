<#
.SYNOPSIS
    Chetna - AI Flood Early-Warning System (B2 Lead Setup Script for PowerShell)
.DESCRIPTION
    Creates Python 3.10+ virtual environment, installs required B2/GIS dependencies,
    scaffolds core project directories, and generates .env.example configuration.
#>

[CmdletBinding()]
param (
    [switch]$SkipDeps,
    [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

function Write-Info    { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[SUCCESS] $args" -ForegroundColor Green }
function Write-Warn    { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err     { Write-Host "[ERROR] $args" -ForegroundColor Red }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "    CHETNA: AI Flood Early-Warning System - B2 Environment Setup      " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Detect Python 3.10+
Write-Info "Checking Python installation..."
$pyBin = $null
foreach ($cmd in @("python", "py", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $check = & $cmd -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>$null
        if ($check -eq "1") {
            $pyBin = $cmd
            break
        }
    }
}

if (-not $pyBin) {
    Write-Err "Python 3.10 or higher is required and was not found in PATH."
    exit 1
}

$pyVer = & $pyBin -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Success "Found compatible Python: $pyBin (v$pyVer)"

# 2. Setup Virtual Environment
if (-not (Test-Path $VenvDir)) {
    Write-Info "Creating virtual environment in '$VenvDir'..."
    & $pyBin -m venv $VenvDir
    Write-Success "Virtual environment created."
} else {
    Write-Info "Virtual environment directory '$VenvDir' already exists."
}

$pipBin = Join-Path $VenvDir "Scripts\pip.exe"
$pyVenv = Join-Path $VenvDir "Scripts\python.exe"

# 3. Install Dependencies
if (-not $SkipDeps) {
    Write-Info "Upgrading pip, setuptools, and wheel..."
    & $pyVenv -m pip install --upgrade pip setuptools wheel

    Write-Info "Installing B2 dependencies from requirements.txt..."
    Write-Info "[NOTE] sqlite3 is included in the standard library."
    if (Test-Path "requirements.txt") {
        & $pipBin install -r requirements.txt
    } else {
        & $pipBin install requests twilio python-telegram-bot python-dotenv pandas pytest pytest-mock
    }
    Write-Success "Dependencies installed successfully."
} else {
    Write-Warn "Skipping dependency installation (-SkipDeps)."
}

# 4. Scaffolding Directories
Write-Info "Scaffolding core directories..."
$dirs = @("config", "database", "simulators", "alerts", "tests", "data")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Info "  Created $d/"
    }
    if ($d -ne "data" -and -not (Test-Path (Join-Path $d "__init__.py"))) {
        New-Item -ItemType File -Path (Join-Path $d "__init__.py") -Force | Out-Null
    }
}
Write-Success "Directory structure ready."

# 5. Environment template
if (-not (Test-Path ".env.example")) {
    Copy-Item "config\.env.template" ".env.example" -ErrorAction SilentlyContinue
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Warn "Created local '.env' from '.env.example' (ALERT_DRY_RUN is enabled)."
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "           B2 Environment Setup Completed Successfully!               " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Activate virtual environment: .\$VenvDir\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "  2. Edit credentials:             notepad .env" -ForegroundColor Cyan
Write-Host "  3. Run tests:                    pytest -v" -ForegroundColor Cyan
Write-Host ""
