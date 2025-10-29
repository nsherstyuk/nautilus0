# Live Trading Startup Script with Environment Setup
# ============================================

# Usage:
#   .\live\run_live_with_env.ps1
#
# Prerequisites:
#   - .env.phase6 file exists with IBKR settings
#   - .venv312 virtual environment is set up
#   - IBKR TWS/Gateway is running on port 7497
#   - API is enabled in TWS settings
#
# What this script does:
#   1. Activates .venv312 virtual environment
#   2. Backs up current .env file (if exists)
#   3. Copies .env.phase6 to .env
#   4. Runs python live/run_live.py
#
# To stop: Press Ctrl+C
# To rollback: Copy the backup file back to .env

# Error Handling Setup
$ErrorActionPreference = 'Stop'

# Color constants for output
$Cyan = 'Cyan'
$Green = 'Green'
$Yellow = 'Yellow'
$Red = 'Red'
$Gray = 'Gray'

param([CmdletBinding()])

$scriptDir = $PSScriptRoot
$repoRoot = Split-Path $scriptDir -Parent

# Main execution with error handling
try {
    # Step 1: Display Header
    Write-Host "============================================================" -ForegroundColor $Cyan
    Write-Host "Live Trading Startup with Phase 6 Configuration" -ForegroundColor $Cyan
    Write-Host "============================================================" -ForegroundColor $Cyan
    Write-Host ""

    # Step 2: Virtual Environment Activation
    Write-Host "[1/4] Activating virtual environment..." -ForegroundColor $Cyan
    $venvPath = Join-Path $repoRoot '.venv312\Scripts\Activate.ps1'
    if (-not (Test-Path $venvPath)) {
        Write-Host "✗ Virtual environment activation script not found: $venvPath" -ForegroundColor $Red
        exit 1
    }
    & $venvPath
    if (-not ($env:VIRTUAL_ENV -and $env:VIRTUAL_ENV -like '*\.venv312*')) {
        Write-Host "✗ Failed to activate virtual environment: VIRTUAL_ENV not set or incorrect path" -ForegroundColor $Red
        exit 1
    }
    $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Path
    if (-not $pythonPath -or $pythonPath -notlike '*\.venv312\*') {
        Write-Host "✗ Python executable not found in .venv312: $pythonPath" -ForegroundColor $Red
        exit 1
    }
    Write-Host "✓ Virtual environment activated (.venv312)" -ForegroundColor $Green
    Write-Host ""

    # Step 3: Backup Current .env File
    Write-Host "[2/4] Backing up current .env file..." -ForegroundColor $Cyan
    $envFile = Join-Path $repoRoot '.env'
    $backupPath = $null
    $backupCreated = $false
    if (Test-Path -LiteralPath $envFile) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupPath = Join-Path $repoRoot ".env.backup.$timestamp"
        Copy-Item -LiteralPath $envFile -Destination $backupPath -Force
        Write-Host "✓ Backup created: $backupPath" -ForegroundColor $Green
        $backupCreated = $true
    } else {
        Write-Host "ℹ No existing .env file found (first run)" -ForegroundColor $Gray
    }
    Write-Host ""

    # Step 4: Copy .env.phase6 to .env
    Write-Host "[3/4] Activating Phase 6 configuration..." -ForegroundColor $Cyan
    $phase6Env = Join-Path $repoRoot '.env.phase6'
    if (-not (Test-Path -LiteralPath $phase6Env)) {
        Write-Host "✗ .env.phase6 file not found. Please ensure it exists with Phase 6 parameters." -ForegroundColor $Red
        exit 1
    }
    Copy-Item -LiteralPath $phase6Env -Destination $envFile -Force
    if (-not (Test-Path -LiteralPath $envFile)) {
        Write-Host "✗ Failed to copy .env.phase6 to .env" -ForegroundColor $Red
        exit 1
    }
    Write-Host "✓ Phase 6 configuration activated (.env.phase6 → .env)" -ForegroundColor $Green
    Write-Host "ℹ Using Phase 6 optimized parameters for live trading." -ForegroundColor $Gray
    Write-Host ""

    # Step 5: Pre-Flight Checks
    Write-Host "[4/4] Starting live trading system..." -ForegroundColor $Cyan
    Write-Host "------------------------------------------------------------"
    Write-Host "Pre-flight checklist:" -ForegroundColor $Cyan
    Write-Host " ✓ Virtual environment: .venv312" -ForegroundColor $Gray
    Write-Host " ✓ Configuration: .env.phase6" -ForegroundColor $Gray
    if ($backupCreated) {
        Write-Host " ✓ Backup created: $backupPath" -ForegroundColor $Gray
    }
    Write-Host " ✓ IBKR settings: Loaded from .env" -ForegroundColor $Gray
    Write-Host ""
    Write-Host "⚠ Ensure IBKR TWS/Gateway is running on port 7497 (paper trading)" -ForegroundColor $Yellow
    Write-Host "⚠ Ensure API is enabled in TWS settings" -ForegroundColor $Yellow
    Write-Host ""

    # Step 6: Execute Live Trading Script
    $pythonScript = Join-Path $repoRoot 'live\run_live.py'
    Write-Host "Executing: python $pythonScript" -ForegroundColor $Gray
    Write-Host "------------------------------------------------------------"
    Write-Host ""
    python $pythonScript
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and $exitCode -ne 130 -and $exitCode -ne 3221225786) {
        Write-Host "✗ Live trading script exited with error code: $exitCode" -ForegroundColor $Red
        exit 1
    }
} catch [System.Management.Automation.PipelineStoppedException] {
    Write-Host "`n✓ Live trading stopped by user" -ForegroundColor $Yellow
    exit 130
} catch [System.OperationCanceledException] {
    Write-Host "`n✓ Operation cancelled" -ForegroundColor $Yellow
    exit 130
} catch {
    Write-Host "`n✗ Error: $($_.Exception.Message)" -ForegroundColor $Red
    if ($PSBoundParameters['Verbose']) {
        Write-Verbose $_.ScriptStackTrace
    }
    exit 1
} finally {
    Write-Host "------------------------------------------------------------" -ForegroundColor $Gray
    Write-Host "Session ended" -ForegroundColor $Gray
    if ($backupCreated) {
        Write-Host "`nTo rollback: Copy-Item -LiteralPath '$backupPath' -Destination '$envFile' -Force" -ForegroundColor $Yellow
    }
}
