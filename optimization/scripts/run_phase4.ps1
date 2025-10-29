# Phase 4: Risk Management Parameter Optimization - PowerShell Execution Script
# ============================================================================
#
# This script automates Phase 4 risk management optimization execution with
# environment setup, validation, and error handling.
#
# Purpose: Optimize risk management parameters (stop loss, take profit, trailing stops)
#          using Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35)
#
# Prerequisites: PowerShell 5.1+, Python 3.8+, Phase 3 results available
# Expected runtime: 8-10 hours with 8 workers (500 combinations)
#
# Usage:
#   .\optimization\scripts\run_phase4.ps1
#   .\optimization\scripts\run_phase4.ps1 -Workers 12
#   .\optimization\scripts\run_phase4.ps1 -DryRun
#   .\optimization\scripts\run_phase4.ps1 -NoArchive

param(
    [int]$Workers = 8,           # Number of parallel workers
    [switch]$NoArchive,          # Skip archiving old results
    [switch]$DryRun             # Validate only, don't execute
)

# Script header and parameters
Write-Host "Phase 4: Risk Management Parameter Optimization" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "Workers: $Workers" -ForegroundColor Yellow
Write-Host "NoArchive: $NoArchive" -ForegroundColor Yellow
Write-Host "DryRun: $DryRun" -ForegroundColor Yellow
Write-Host ""

# Environment Variable Setup
# ==========================
Write-Host "Setting up environment variables..." -ForegroundColor Green

# Backtest configuration
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"

# Data and output configuration
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

# Display environment configuration
Write-Host "Environment Configuration:" -ForegroundColor Yellow
Write-Host "  Symbol: $env:BACKTEST_SYMBOL"
Write-Host "  Venue: $env:BACKTEST_VENUE"
Write-Host "  Date Range: $env:BACKTEST_START_DATE to $env:BACKTEST_END_DATE"
Write-Host "  Bar Spec: $env:BACKTEST_BAR_SPEC"
Write-Host "  Catalog: $env:CATALOG_PATH"
Write-Host "  Output: $env:OUTPUT_DIR"
Write-Host ""

# Pre-flight Validation
# ====================
Write-Host "Performing pre-flight validation..." -ForegroundColor Green

# Check Python availability
try {
    $pythonCmd = Get-Command python -ErrorAction Stop
    Write-Host "✓ Python found: $($pythonCmd.Source)" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found. Please install Python 3.8+ and ensure it's in PATH." -ForegroundColor Red
    exit 1
}

# Verify Phase 4 config file exists
if (-not (Test-Path "optimization/configs/phase4_risk_management.yaml")) {
    Write-Host "✗ Phase 4 config file not found: optimization/configs/phase4_risk_management.yaml" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Phase 4 config file found" -ForegroundColor Green

# Verify Phase 3 results exist
if (-not (Test-Path "optimization/results/phase3_fine_grid_results_top_10.json")) {
    Write-Host "✗ Phase 3 results not found. Please complete Phase 3 first." -ForegroundColor Red
    Write-Host "  Expected: optimization/results/phase3_fine_grid_results_top_10.json" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Phase 3 results found" -ForegroundColor Green

# Verify catalog path exists
if (-not (Test-Path $env:CATALOG_PATH)) {
    Write-Host "✗ Catalog path not found: $env:CATALOG_PATH" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Catalog path found" -ForegroundColor Green

# Validate date range
try {
    $startDate = [DateTime]::Parse($env:BACKTEST_START_DATE)
    $endDate = [DateTime]::Parse($env:BACKTEST_END_DATE)
    if ($startDate -ge $endDate) {
        Write-Host "✗ Invalid date range: START_DATE must be before END_DATE" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Date range valid: $startDate to $endDate" -ForegroundColor Green
} catch {
    Write-Host "✗ Invalid date format. Use YYYY-MM-DD format." -ForegroundColor Red
    exit 1
}

# Check required Python packages
try {
    $packages = @("pandas", "pyyaml")
    foreach ($package in $packages) {
        $result = python -c "import $package" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "✗ Python package not found: $package" -ForegroundColor Red
            Write-Host "  Install with: pip install $package" -ForegroundColor Yellow
            exit 1
        }
    }
    Write-Host "✓ Required Python packages found" -ForegroundColor Green
} catch {
    Write-Host "✗ Error checking Python packages" -ForegroundColor Red
    exit 1
}

Write-Host "✓ All pre-flight checks passed" -ForegroundColor Green
Write-Host ""

# Archive Old Results (unless -NoArchive flag set)
# ================================================
if (-not $NoArchive) {
    Write-Host "Checking for existing Phase 4 results..." -ForegroundColor Yellow
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    $filesToArchive = @(
        "optimization/results/phase4_risk_management_results.csv",
        "optimization/results/phase4_risk_management_results_top_10.json",
        "optimization/results/phase4_risk_management_results_summary.json"
    )
    
    foreach ($file in $filesToArchive) {
        if (Test-Path $file) {
            $fileName = Split-Path $file -Leaf
            $archiveDir = "optimization/results/archive/phase4"
            
            # Create archive directory if it doesn't exist
            if (-not (Test-Path $archiveDir)) {
                New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
            }
            
            $newName = "$fileName.old.$timestamp"
            $destinationPath = Join-Path $archiveDir $newName
            try {
                Move-Item -Path $file -Destination $destinationPath -Force
                Write-Host "✓ Archived: $newName" -ForegroundColor Green
            } catch {
                Write-Host "WARNING: Could not archive $file : $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
    Write-Host
}


# Display Execution Summary
# =========================
Write-Host "Phase 4 Configuration Summary:" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan
Write-Host "Total combinations: 500 (5×5×4×5)" -ForegroundColor White
Write-Host "Parameters being optimized:" -ForegroundColor White
Write-Host "  - stop_loss_pips: [15, 20, 25, 30, 35]" -ForegroundColor Gray
Write-Host "  - take_profit_pips: [30, 40, 50, 60, 75]" -ForegroundColor Gray
Write-Host "  - trailing_stop_activation_pips: [22, 25, 28, 32]" -ForegroundColor Gray
Write-Host "  - trailing_stop_distance_pips: [10, 12, 14, 16, 18]" -ForegroundColor Gray
Write-Host ""
Write-Host "Fixed MA parameters (from Phase 3 best):" -ForegroundColor White
Write-Host "  - fast_period: 42" -ForegroundColor Gray
Write-Host "  - slow_period: 270" -ForegroundColor Gray
Write-Host "  - crossover_threshold_pips: 0.35" -ForegroundColor Gray
Write-Host ""
Write-Host "Expected runtime: 8-10 hours with $Workers workers" -ForegroundColor White
Write-Host ""

# Display Phase 3 baseline for comparison
try {
    $phase3Json = Get-Content "optimization/results/phase3_fine_grid_results_top_10.json" | ConvertFrom-Json
    $phase3Best = $phase3Json[0]
    Write-Host "Phase 3 Baseline (for comparison):" -ForegroundColor Yellow
    Write-Host "  Best Sharpe: $($phase3Best.objective_value)" -ForegroundColor Gray
    Write-Host "  Best PnL: `$$($phase3Best.parameters.total_pnl)" -ForegroundColor Gray
    Write-Host "  Win Rate: $($phase3Best.parameters.win_rate)%" -ForegroundColor Gray
    Write-Host "  Trade Count: $($phase3Best.parameters.trade_count)" -ForegroundColor Gray
    Write-Host "  Target: Improve Sharpe ratio to 0.28-0.35 range" -ForegroundColor Yellow
} catch {
    Write-Host "Warning: Could not load Phase 3 baseline data" -ForegroundColor Yellow
}
Write-Host ""

# Prompt for confirmation (unless DryRun)
if ($DryRun) {
    Write-Host "Dry run completed. Configuration validated successfully." -ForegroundColor Green
    Write-Host "Remove -DryRun flag to execute Phase 4 optimization." -ForegroundColor Yellow
    exit 0
}

$confirmation = Read-Host "Continue with Phase 4 execution? (y/n)"
if ($confirmation -ne "y" -and $confirmation -ne "Y") {
    Write-Host "Phase 4 execution cancelled by user." -ForegroundColor Yellow
    exit 0
}

# Execute Grid Search
# ===================
Write-Host "Starting Phase 4 optimization..." -ForegroundColor Green
$startTime = Get-Date
Write-Host "Start time: $startTime" -ForegroundColor Gray

# Build command arguments
$cmdArgs = @(
    "optimization/grid_search.py"
    "--config", "optimization/configs/phase4_risk_management.yaml"
    "--objective", "sharpe_ratio"
    "--workers", $Workers.ToString()
    "--output", "optimization/results/phase4_risk_management_results.csv"
    "--no-resume"
    "--verbose"
)

Write-Host "Executing command:" -ForegroundColor Yellow
Write-Host "python $($cmdArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

# Execute the command
try {
    & python @cmdArgs
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "Error executing grid search: $_" -ForegroundColor Red
    $exitCode = 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "Execution completed at: $endTime" -ForegroundColor Gray
Write-Host "Total duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Gray
Write-Host ""

# Post-execution Validation
# ========================
if ($exitCode -eq 0) {
    Write-Host "Validating Phase 4 results..." -ForegroundColor Green
    
    # Check if output files exist
    $outputFiles = @(
        "optimization/results/phase4_risk_management_results.csv",
        "optimization/results/phase4_risk_management_results_top_10.json",
        "optimization/results/phase4_risk_management_results_summary.json"
    )
    
    $allFilesExist = $true
    foreach ($file in $outputFiles) {
        if (Test-Path $file) {
            Write-Host "✓ $file exists" -ForegroundColor Green
        } else {
            Write-Host "✗ $file missing" -ForegroundColor Red
            $allFilesExist = $false
        }
    }
    
    if ($allFilesExist) {
        # Count CSV rows (should be ~500)
        try {
            $csvData = Import-Csv "optimization/results/phase4_risk_management_results.csv"
            $rowCount = $csvData.Count
            Write-Host "✓ CSV contains $rowCount results (expected: ~500)" -ForegroundColor Green
        } catch {
            Write-Host "✗ Error reading CSV file" -ForegroundColor Red
        }
        
        # Load and display top 3 results
        try {
            $top10Json = Get-Content "optimization/results/phase4_risk_management_results_top_10.json" | ConvertFrom-Json
            Write-Host ""
            Write-Host "Top 3 Phase 4 Results:" -ForegroundColor Cyan
            for ($i = 0; $i -lt [Math]::Min(3, $top10Json.Count); $i++) {
                $result = $top10Json[$i]
                Write-Host "  Rank $($i + 1): Sharpe=$($result.objective_value), SL=$($result.parameters.stop_loss_pips), TP=$($result.parameters.take_profit_pips), TA=$($result.parameters.trailing_stop_activation_pips), TD=$($result.parameters.trailing_stop_distance_pips)" -ForegroundColor Gray
            }
            
            # Compare with Phase 3 baseline
            if ($top10Json -and $top10Json.Count -gt 0 -and $phase3Json -and $phase3Json.Count -gt 0) {
                $phase4Best = $top10Json[0]
                $phase3Best = $phase3Json[0]
                $improvement = (($phase4Best.objective_value - $phase3Best.objective_value) / $phase3Best.objective_value) * 100
                Write-Host ""
                Write-Host "Improvement over Phase 3:" -ForegroundColor Yellow
                $improvementPct = [Math]::Round($improvement, 2)
                Write-Host ('  Sharpe ratio: {0} -> {1} ({2} percent)' -f $phase3Best.objective_value, $phase4Best.objective_value, $improvementPct) -ForegroundColor Gray
            }
        } catch {
            Write-Host "✗ Error reading top 10 JSON file" -ForegroundColor Red
        }
        
        # Display execution statistics
        Write-Host ""
        Write-Host "Execution Statistics:" -ForegroundColor Cyan
        Write-Host "  Total duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Gray
        Write-Host "  Average time per backtest: $([Math]::Round($duration.TotalSeconds / 500, 1)) seconds" -ForegroundColor Gray
        $successRate = [Math]::Round($rowCount / 500 * 100, 1)
        Write-Host ('  Success rate: {0}/500 ({1} percent)' -f $rowCount, $successRate) -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host "✅ Phase 4 Complete!" -ForegroundColor Green
    if ($top10Json -and $top10Json.Count -gt 0) {
        $phase4Best = $top10Json[0]
        Write-Host "Best Sharpe: $($phase4Best.objective_value)" -ForegroundColor Green
        Write-Host "Best params: SL=$($phase4Best.parameters.stop_loss_pips), TP=$($phase4Best.parameters.take_profit_pips), TA=$($phase4Best.parameters.trailing_stop_activation_pips), TD=$($phase4Best.parameters.trailing_stop_distance_pips)" -ForegroundColor Green
        if ($phase3Json -and $phase3Json.Count -gt 0) {
            $phase3Best = $phase3Json[0]
            $improvement = (($phase4Best.objective_value - $phase3Best.objective_value) / $phase3Best.objective_value) * 100
            $improvementPct2 = [Math]::Round($improvement, 2)
            Write-Host ('Improvement: +{0} percent over Phase 3' -f $improvementPct2) -ForegroundColor Green
        }
    }
    
} else {
    Write-Host "❌ Phase 4 execution failed with exit code: $exitCode" -ForegroundColor Red
    Write-Host "Check the logs above for error details." -ForegroundColor Yellow
    Write-Host "Checkpoint file may contain partial results: optimization/checkpoints/phase4_risk_management_checkpoint.csv" -ForegroundColor Yellow
}

# Success Message and Next Steps
# ==============================
if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "Next Steps:" -ForegroundColor Cyan
    Write-Host "1. Review results: cat optimization/results/phase4_risk_management_results_top_10.json" -ForegroundColor Gray
    Write-Host "2. Run validation: python optimization/scripts/validate_phase4_results.py" -ForegroundColor Gray
    Write-Host "3. Update Phase 5 config with Phase 4 best parameters" -ForegroundColor Gray
    Write-Host "4. Document findings in PHASE4_EXECUTION_LOG.md" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Output files:" -ForegroundColor Yellow
    Write-Host "  - optimization/results/phase4_risk_management_results.csv" -ForegroundColor Gray
    Write-Host "  - optimization/results/phase4_risk_management_results_top_10.json" -ForegroundColor Gray
    Write-Host "  - optimization/results/phase4_risk_management_results_summary.json" -ForegroundColor Gray
}

exit $exitCode
