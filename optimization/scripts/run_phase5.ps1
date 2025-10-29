# Phase 5: Filter Parameter Optimization (DMI and Stochastic) - PowerShell Execution Script
# ===========================================================================================
#
# This script automates Phase 5 filter optimization execution with
# environment setup, validation, and error handling.
#
# Purpose: Optimize DMI and Stochastic filter parameters using Phase 3 best MA 
#          and Phase 4 best risk management parameters
#
# Prerequisites: PowerShell 5.1+, Python 3.8+, Phase 3 and Phase 4 results available
# Expected runtime: ~40 hours with 8 workers (2,400 combinations) or ~2 hours (108 combinations)
#
# Usage:
#   .\optimization\scripts\run_phase5.ps1
#   .\optimization\scripts\run_phase5.ps1 -Workers 12
#   .\optimization\scripts\run_phase5.ps1 -UseReduced
#   .\optimization\scripts\run_phase5.ps1 -DryRun
#   .\optimization\scripts\run_phase5.ps1 -NoArchive

param(
    [int]$Workers = 8,           # Number of parallel workers
    [switch]$NoArchive,          # Skip archiving old results
    [switch]$DryRun,             # Validate only, don't execute
    [switch]$UseReduced,         # Use reduced configuration (108 combinations, ~2 hours)
    [switch]$UseMedium           # Use medium configuration (324 combinations, ~6 hours)
)

# Script header and parameters
Write-Host "Phase 5: Filter Parameter Optimization (DMI and Stochastic)" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "Workers: $Workers" -ForegroundColor Yellow
Write-Host "NoArchive: $NoArchive" -ForegroundColor Yellow
Write-Host "DryRun: $DryRun" -ForegroundColor Yellow
Write-Host "UseReduced: $UseReduced" -ForegroundColor Yellow
Write-Host "UseMedium: $UseMedium" -ForegroundColor Yellow
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

# Verify Phase 5 config file exists (check all versions)
$configFile = if ($UseReduced) { "optimization/configs/phase5_filters_reduced.yaml" } elseif ($UseMedium) { "optimization/configs/phase5_filters_medium.yaml" } else { "optimization/configs/phase5_filters.yaml" }
if (-not (Test-Path $configFile)) {
    Write-Host "✗ Phase 5 config file not found: $configFile" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Phase 5 config file found: $configFile" -ForegroundColor Green

# Verify Phase 3 results exist
if (-not (Test-Path "optimization/results/phase3_fine_grid_results_top_10.json")) {
    Write-Host "✗ Phase 3 results not found. Please complete Phase 3 first." -ForegroundColor Red
    Write-Host "  Expected: optimization/results/phase3_fine_grid_results_top_10.json" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Phase 3 results found" -ForegroundColor Green

# Verify Phase 4 results exist
if (-not (Test-Path "optimization/results/phase4_risk_management_results_top_10.json")) {
    Write-Host "✗ Phase 4 results not found. Please complete Phase 4 first." -ForegroundColor Red
    Write-Host "  Expected: optimization/results/phase4_risk_management_results_top_10.json" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Phase 4 results found" -ForegroundColor Green

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
    Write-Host "Checking for existing Phase 5 results..." -ForegroundColor Yellow
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    $filesToArchive = if ($UseReduced) {
        @(
            "optimization/results/phase5_filters_reduced_results.csv",
            "optimization/results/phase5_filters_reduced_results_top_10.json",
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    } elseif ($UseMedium) {
        @(
            "optimization/results/phase5_filters_medium_results.csv",
            "optimization/results/phase5_filters_medium_results_top_10.json",
            "optimization/results/phase5_filters_medium_results_summary.json"
        )
    } else {
        @(
            "optimization/results/phase5_filters_results.csv",
            "optimization/results/phase5_filters_results_top_10.json",
            "optimization/results/phase5_filters_results_summary.json"
        )
    }
    
    foreach ($file in $filesToArchive) {
        if (Test-Path $file) {
            $fileName = Split-Path $file -Leaf
            $archiveDir = "optimization/results/archive/phase5"
            
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
# ====================
Write-Host "Phase 5 Configuration Summary:" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

if ($UseReduced) {
    Write-Host "Configuration: REDUCED VERSION" -ForegroundColor Yellow
    Write-Host "Total combinations: 108 (1×3×3×3×2×2)" -ForegroundColor White
    Write-Host "Expected runtime: ~2 hours with $Workers workers" -ForegroundColor White
    Write-Host ""
    Write-Host "Parameters being optimized:" -ForegroundColor White
    Write-Host "  - dmi_enabled: [true] (1 value - keep enabled)" -ForegroundColor Gray
    Write-Host "  - dmi_period: [10, 14, 18] (3 values - fast, baseline, slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_k: [10, 14, 18] (3 values - fast, baseline, slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_d: [3, 5, 7] (3 values - keep all)" -ForegroundColor Gray
    Write-Host "  - stoch_bullish_threshold: [20, 30] (2 values - aggressive vs baseline)" -ForegroundColor Gray
    Write-Host "  - stoch_bearish_threshold: [70, 80] (2 values - baseline vs aggressive)" -ForegroundColor Gray
} elseif ($UseMedium) {
    Write-Host "Configuration: MEDIUM VERSION" -ForegroundColor Yellow
    Write-Host "Total combinations: 324 (2×3×3×2×3×3)" -ForegroundColor White
    Write-Host "Expected runtime: ~6 hours with $Workers workers" -ForegroundColor White
    Write-Host ""
    Write-Host "Parameters being optimized:" -ForegroundColor White
    Write-Host "  - dmi_enabled: [true, false] (2 values - test DMI filter value)" -ForegroundColor Gray
    Write-Host "  - dmi_period: [10, 14, 18] (3 values - fast, baseline, slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_k: [10, 14, 18] (3 values - fast, baseline, slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_d: [3, 5] (2 values - minimal vs moderate smoothing)" -ForegroundColor Gray
    Write-Host "  - stoch_bullish_threshold: [20, 30, 35] (3 values - aggressive to conservative)" -ForegroundColor Gray
    Write-Host "  - stoch_bearish_threshold: [70, 75, 80] (3 values - baseline to aggressive)" -ForegroundColor Gray
} else {
    Write-Host "Configuration: FULL VERSION" -ForegroundColor Yellow
    Write-Host "Total combinations: 2,400 (2×5×5×3×4×4)" -ForegroundColor White
    Write-Host "Expected runtime: ~40 hours with $Workers workers" -ForegroundColor White
    Write-Host ""
    Write-Host "Parameters being optimized:" -ForegroundColor White
    Write-Host "  - dmi_enabled: [true, false] (2 values - test DMI filter value)" -ForegroundColor Gray
    Write-Host "  - dmi_period: [10, 12, 14, 16, 18] (5 values - fast to slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_k: [10, 12, 14, 16, 18] (5 values - fast to slow)" -ForegroundColor Gray
    Write-Host "  - stoch_period_d: [3, 5, 7] (3 values - minimal to high smoothing)" -ForegroundColor Gray
    Write-Host "  - stoch_bullish_threshold: [20, 25, 30, 35] (4 values - aggressive to conservative)" -ForegroundColor Gray
    Write-Host "  - stoch_bearish_threshold: [65, 70, 75, 80] (4 values - conservative to aggressive)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Fixed MA parameters (from Phase 3 best):" -ForegroundColor White
Write-Host "  - fast_period: 42" -ForegroundColor Gray
Write-Host "  - slow_period: 270" -ForegroundColor Gray
Write-Host "  - crossover_threshold_pips: 0.35" -ForegroundColor Gray
Write-Host ""
Write-Host "Fixed risk parameters (from Phase 4 best):" -ForegroundColor White
Write-Host "  - stop_loss_pips: 35" -ForegroundColor Gray
Write-Host "  - take_profit_pips: 50" -ForegroundColor Gray
Write-Host "  - trailing_stop_activation_pips: 22" -ForegroundColor Gray
Write-Host "  - trailing_stop_distance_pips: 12" -ForegroundColor Gray
Write-Host ""

# Display Phase 3 and Phase 4 baselines for comparison
try {
    $phase3Json = Get-Content "optimization/results/phase3_fine_grid_results_top_10.json" | ConvertFrom-Json
    $phase3Best = $phase3Json[0]
    Write-Host "Phase 3 Baseline (for comparison):" -ForegroundColor Yellow
    Write-Host "  Best Sharpe: $($phase3Best.objective_value)" -ForegroundColor Gray
} catch {
    Write-Host "Warning: Could not load Phase 3 baseline data" -ForegroundColor Yellow
}

try {
    $phase4Json = Get-Content "optimization/results/phase4_risk_management_results_top_10.json" | ConvertFrom-Json
    $phase4Best = $phase4Json[0]
    Write-Host ""
    Write-Host "Phase 4 Baseline (for comparison):" -ForegroundColor Yellow
    Write-Host "  Best Sharpe: $($phase4Best.objective_value)" -ForegroundColor Gray
    Write-Host "  Target: Maintain or improve Phase 4 Sharpe ratio of $($phase4Best.objective_value)" -ForegroundColor Yellow
} catch {
    Write-Host "Warning: Could not load Phase 4 baseline data" -ForegroundColor Yellow
}

Write-Host ""

# Important warning for full version
if (-not $UseReduced) {
    Write-Host "⚠️  WARNING: Full version will take ~40 hours!" -ForegroundColor Red
    Write-Host "Consider using -UseReduced flag for faster iteration (~2 hours)" -ForegroundColor Yellow
    Write-Host ""
}

# Prompt for confirmation (unless DryRun)
if ($DryRun) {
    Write-Host "Dry run completed. Configuration validated successfully." -ForegroundColor Green
    Write-Host "Remove -DryRun flag to execute Phase 5 optimization." -ForegroundColor Yellow
    exit 0
}

$confirmation = Read-Host "Continue with Phase 5 execution? (y/n)"
if ($confirmation -ne "y" -and $confirmation -ne "Y") {
    Write-Host "Phase 5 execution cancelled by user." -ForegroundColor Yellow
    exit 0
}

# Execute Grid Search
# ===================
Write-Host "Starting Phase 5 optimization..." -ForegroundColor Green
$startTime = Get-Date
Write-Host "Start time: $startTime" -ForegroundColor Gray

# Determine output file based on configuration
$outputFile = if ($UseReduced) { "optimization/results/phase5_filters_reduced_results.csv" } elseif ($UseMedium) { "optimization/results/phase5_filters_medium_results.csv" } else { "optimization/results/phase5_filters_results.csv" }

# Build command arguments
$cmdArgs = @(
    "optimization/grid_search.py"
    "--config", $configFile
    "--objective", "sharpe_ratio"
    "--workers", $Workers.ToString()
    "--output", $outputFile
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
    Write-Host "Validating Phase 5 results..." -ForegroundColor Green
    
    # Check if output files exist
    $outputFiles = if ($UseReduced) {
        @(
            "optimization/results/phase5_filters_reduced_results.csv",
            "optimization/results/phase5_filters_reduced_results_top_10.json",
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    } elseif ($UseMedium) {
        @(
            "optimization/results/phase5_filters_medium_results.csv",
            "optimization/results/phase5_filters_medium_results_top_10.json",
            "optimization/results/phase5_filters_medium_results_summary.json"
        )
    } else {
        @(
            "optimization/results/phase5_filters_results.csv",
            "optimization/results/phase5_filters_results_top_10.json",
            "optimization/results/phase5_filters_results_summary.json"
        )
    }
    
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
        # Count CSV rows
        $expectedRows = if ($UseReduced) { 108 } elseif ($UseMedium) { 324 } else { 2400 }
        try {
            $csvData = Import-Csv $outputFile
            $rowCount = $csvData.Count
            Write-Host "✓ CSV contains $rowCount results (expected: ~$expectedRows)" -ForegroundColor Green
        } catch {
            Write-Host "✗ Error reading CSV file" -ForegroundColor Red
        }
        
        # Load and display top 3 results
        try {
            $top10File = if ($UseReduced) { "optimization/results/phase5_filters_reduced_results_top_10.json" } elseif ($UseMedium) { "optimization/results/phase5_filters_medium_results_top_10.json" } else { "optimization/results/phase5_filters_results_top_10.json" }
            $top10Json = Get-Content $top10File | ConvertFrom-Json
            Write-Host ""
            Write-Host "Top 3 Phase 5 Results:" -ForegroundColor Cyan
            for ($i = 0; $i -lt [Math]::Min(3, $top10Json.Count); $i++) {
                $result = $top10Json[$i]
                Write-Host "  Rank $($i + 1): Sharpe=$($result.objective_value), DMI=$($result.parameters.dmi_enabled), DMI_Period=$($result.parameters.dmi_period), Stoch_K=$($result.parameters.stoch_period_k), Stoch_D=$($result.parameters.stoch_period_d)" -ForegroundColor Gray
            }
            
            # Compare with Phase 4 baseline
            if ($top10Json -and $top10Json.Count -gt 0 -and $phase4Json -and $phase4Json.Count -gt 0) {
                $phase5Best = $top10Json[0]
                $phase4Best = $phase4Json[0]
                $improvement = (($phase5Best.objective_value - $phase4Best.objective_value) / $phase4Best.objective_value) * 100
                Write-Host ""
                Write-Host "Improvement over Phase 4:" -ForegroundColor Yellow
                $improvementPct = [Math]::Round($improvement, 2)
                Write-Host ('  Sharpe ratio: {0} -> {1} ({2} percent)' -f $phase4Best.objective_value, $phase5Best.objective_value, $improvementPct) -ForegroundColor Gray
            }
        } catch {
            Write-Host "✗ Error reading top 10 JSON file" -ForegroundColor Red
        }
        
        # Display execution statistics
        Write-Host ""
        Write-Host "Execution Statistics:" -ForegroundColor Cyan
        Write-Host "  Total duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Gray
        $avgTimePerBacktest = [Math]::Round($duration.TotalSeconds / $expectedRows, 1)
        Write-Host "  Average time per backtest: $avgTimePerBacktest seconds" -ForegroundColor Gray
        $successRate = [Math]::Round($rowCount / $expectedRows * 100, 1)
        Write-Host ('  Success rate: {0}/{1} ({2} percent)' -f $rowCount, $expectedRows, $successRate) -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host "✅ Phase 5 Complete!" -ForegroundColor Green
    if ($top10Json -and $top10Json.Count -gt 0) {
        $phase5Best = $top10Json[0]
        Write-Host "Best Sharpe: $($phase5Best.objective_value)" -ForegroundColor Green
        Write-Host "Best params: DMI=$($phase5Best.parameters.dmi_enabled), DMI_Period=$($phase5Best.parameters.dmi_period), Stoch_K=$($phase5Best.parameters.stoch_period_k), Stoch_D=$($phase5Best.parameters.stoch_period_d)" -ForegroundColor Green
        if ($phase4Json -and $phase4Json.Count -gt 0) {
            $phase4Best = $phase4Json[0]
            $improvement = (($phase5Best.objective_value - $phase4Best.objective_value) / $phase4Best.objective_value) * 100
            $improvementPct2 = [Math]::Round($improvement, 2)
            if ($improvement -gt 0) {
                Write-Host ('Improvement: +{0} percent over Phase 4' -f $improvementPct2) -ForegroundColor Green
            } else {
                Write-Host ('Change: {0} percent vs Phase 4' -f $improvementPct2) -ForegroundColor Yellow
            }
        }
    }
    
} else {
    Write-Host "❌ Phase 5 execution failed with exit code: $exitCode" -ForegroundColor Red
    Write-Host "Check the logs above for error details." -ForegroundColor Yellow
    $checkpointFile = if ($UseReduced) { "optimization/checkpoints/phase5_filters_reduced_checkpoint.csv" } else { "optimization/checkpoints/phase5_filters_checkpoint.csv" }
    Write-Host "Checkpoint file may contain partial results: $checkpointFile" -ForegroundColor Yellow
}

# Success Message and Next Steps
# ==============================
if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "Next Steps:" -ForegroundColor Cyan
    $top10File = if ($UseReduced) { "optimization/results/phase5_filters_reduced_results_top_10.json" } elseif ($UseMedium) { "optimization/results/phase5_filters_medium_results_top_10.json" } else { "optimization/results/phase5_filters_results_top_10.json" }
    Write-Host "1. Review results: cat $top10File" -ForegroundColor Gray
    if ($UseReduced) {
        Write-Host "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_reduced_results.csv --expected-combinations 108" -ForegroundColor Gray
    } elseif ($UseMedium) {
        Write-Host "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_medium_results.csv --expected-combinations 324" -ForegroundColor Gray
    } else {
        Write-Host "2. Run validation: python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_results.csv --expected-combinations 2400" -ForegroundColor Gray
    }
    if ($UseReduced) {
        Write-Host "3. If results are promising, run medium version: .\optimization\scripts\run_phase5.ps1 -UseMedium" -ForegroundColor Gray
    } elseif ($UseMedium) {
        Write-Host "3. If results are promising, run full version: .\optimization\scripts\run_phase5.ps1" -ForegroundColor Gray
    } else {
        Write-Host "3. Analyze filter impact on win rate and trade count" -ForegroundColor Gray
    }
    Write-Host "4. Update Phase 6 config with Phase 5 best filter parameters" -ForegroundColor Gray
    Write-Host "5. Document findings in PHASE5_EXECUTION_LOG.md" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Output files:" -ForegroundColor Yellow
    foreach ($file in $outputFiles) {
        Write-Host "  - $file" -ForegroundColor Gray
    }
}

exit $exitCode
