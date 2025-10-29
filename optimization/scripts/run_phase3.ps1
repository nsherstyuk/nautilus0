# Phase 3 Fine Grid Optimization Execution Script (PowerShell)
# Purpose: Execute Phase 3 optimization with proper environment setup and validation
# Date: $(Get-Date)
# Usage: .\optimization\scripts\run_phase3.ps1

param(
    [int]$Workers = 8,
    [switch]$NoArchive,
    [switch]$DryRun
)

# Set error action preference
$ErrorActionPreference = "Stop"

Write-Host "=== Phase 3 Fine Grid Optimization Execution ===" -ForegroundColor Green
Write-Host "Date: $(Get-Date)" -ForegroundColor Cyan
Write-Host "Working Directory: $(Get-Location)" -ForegroundColor Cyan
Write-Host "Workers: $Workers" -ForegroundColor Cyan
Write-Host "Dry Run: $DryRun" -ForegroundColor Cyan
Write-Host

# Environment Variable Setup
Write-Host "Setting up environment variables..." -ForegroundColor Yellow
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

Write-Host "Environment variables configured:" -ForegroundColor Green
Write-Host "  BACKTEST_SYMBOL: $env:BACKTEST_SYMBOL"
Write-Host "  BACKTEST_VENUE: $env:BACKTEST_VENUE"
Write-Host "  BACKTEST_START_DATE: $env:BACKTEST_START_DATE"
Write-Host "  BACKTEST_END_DATE: $env:BACKTEST_END_DATE"
Write-Host "  BACKTEST_BAR_SPEC: $env:BACKTEST_BAR_SPEC"
Write-Host "  CATALOG_PATH: $env:CATALOG_PATH"
Write-Host "  OUTPUT_DIR: $env:OUTPUT_DIR"
Write-Host

# Pre-flight Validation
Write-Host "Performing pre-flight validation..." -ForegroundColor Yellow

try {
    # Check if Python is available
    $pythonCmd = Get-Command python -ErrorAction Stop
    Write-Host "✓ Python is available: $($pythonCmd.Source)" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python is not available. Please install Python and try again." -ForegroundColor Red
    exit 1
}

# Verify config file exists
if (-not (Test-Path "optimization/configs/phase3_fine_grid.yaml")) {
    Write-Host "ERROR: Config file not found: optimization/configs/phase3_fine_grid.yaml" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Config file exists" -ForegroundColor Green

# Verify catalog path exists
if (-not (Test-Path $env:CATALOG_PATH)) {
    Write-Host "ERROR: Catalog path not found: $env:CATALOG_PATH" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Catalog path exists" -ForegroundColor Green

# Validate date range
try {
    $startDate = [DateTime]::Parse($env:BACKTEST_START_DATE)
    $endDate = [DateTime]::Parse($env:BACKTEST_END_DATE)
    if ($startDate -ge $endDate) {
        Write-Host "ERROR: Start date must be before end date" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Date range is valid" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Invalid date format. Use YYYY-MM-DD format." -ForegroundColor Red
    exit 1
}

# Check for required Python packages
Write-Host "Checking Python packages..." -ForegroundColor Yellow
try {
    python -c "import pandas, yaml" 2>$null
    Write-Host "✓ Required Python packages available" -ForegroundColor Green
} catch {
    Write-Host "WARNING: Some Python packages may be missing. Install with: pip install pandas pyyaml" -ForegroundColor Yellow
}

Write-Host "All pre-flight checks passed!" -ForegroundColor Green
Write-Host

# Archive Old Results (unless NoArchive flag is set)
if (-not $NoArchive) {
    Write-Host "Checking for existing Phase 3 results..." -ForegroundColor Yellow
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    $filesToArchive = @(
        "optimization/results/phase3_fine_grid_results.csv",
        "optimization/results/phase3_fine_grid_results_top_10.json",
        "optimization/results/phase3_fine_grid_results_summary.json"
    )
    
    foreach ($file in $filesToArchive) {
        if (Test-Path $file) {
            $newName = "$file.old.$timestamp"
            try {
                Rename-Item $file $newName
                Write-Host "✓ Archived: $newName" -ForegroundColor Green
            } catch {
                Write-Host "WARNING: Could not archive $file : $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
    Write-Host
}

# Dry run mode
if ($DryRun) {
    Write-Host "DRY RUN MODE - Validation only, not executing optimization" -ForegroundColor Cyan
    Write-Host "Command that would be executed:" -ForegroundColor Cyan
    Write-Host "python optimization/grid_search.py --config optimization/configs/phase3_fine_grid.yaml --objective sharpe_ratio --workers $Workers --no-resume --verbose" -ForegroundColor White
    Write-Host
    Write-Host "✓ Dry run completed successfully" -ForegroundColor Green
    exit 0
}

# Execute Grid Search
Write-Host "Starting Phase 3 optimization..." -ForegroundColor Yellow
$startTime = Get-Date
Write-Host "Start time: $startTime" -ForegroundColor Cyan
Write-Host "Configuration: 125 combinations (5×5×5)" -ForegroundColor Cyan
Write-Host "Workers: $Workers" -ForegroundColor Cyan
Write-Host "Expected runtime: 2-3 hours" -ForegroundColor Cyan
Write-Host

try {
    $process = Start-Process -FilePath "python" -ArgumentList @(
        "optimization/grid_search.py",
        "--config", "optimization/configs/phase3_fine_grid.yaml",
        "--objective", "sharpe_ratio",
        "--workers", $Workers.ToString(),
        "--no-resume",
        "--verbose"
    ) -Wait -PassThru -NoNewWindow
    
    $exitCode = $process.ExitCode
} catch {
    Write-Host "ERROR: Failed to execute grid search: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host
Write-Host "Optimization completed at: $endTime" -ForegroundColor Cyan
Write-Host "Duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Cyan
Write-Host "Exit code: $exitCode" -ForegroundColor Cyan

# Post-execution Validation
if ($exitCode -ne 0) {
    Write-Host "ERROR: Grid search failed with exit code $exitCode" -ForegroundColor Red
    Write-Host "Check the logs for details." -ForegroundColor Red
    exit $exitCode
}

Write-Host "Performing post-execution validation..." -ForegroundColor Yellow

# Verify output files were created
$outputFiles = @(
    "optimization/results/phase3_fine_grid_results.csv",
    "optimization/results/phase3_fine_grid_results_top_10.json",
    "optimization/results/phase3_fine_grid_results_summary.json"
)

foreach ($file in $outputFiles) {
    if (Test-Path $file) {
        Write-Host "✓ $file created" -ForegroundColor Green
    } else {
        Write-Host "WARNING: $file not found" -ForegroundColor Yellow
    }
}

# Count CSV rows if available
if (Test-Path "optimization/results/phase3_fine_grid_results.csv") {
    try {
        $csvData = Import-Csv "optimization/results/phase3_fine_grid_results.csv"
        $rowCount = $csvData.Count
        Write-Host "✓ Results CSV has $rowCount rows (expected: ~125)" -ForegroundColor Green
    } catch {
        Write-Host "WARNING: Could not read CSV file" -ForegroundColor Yellow
    }
}

# Display top 3 results if available
if (Test-Path "optimization/results/phase3_fine_grid_results_top_10.json") {
    Write-Host
    Write-Host "Top 3 results:" -ForegroundColor Cyan
    try {
        $jsonData = Get-Content "optimization/results/phase3_fine_grid_results_top_10.json" | ConvertFrom-Json
        for ($i = 0; $i -lt [Math]::Min(3, $jsonData.Count); $i++) {
            $result = $jsonData[$i]
            $sharpe = if ($result.objective_value) { [Math]::Round($result.objective_value, 4) } else { "N/A" }
            $fast = if ($result.parameters.fast_period) { $result.parameters.fast_period } else { "N/A" }
            $slow = if ($result.parameters.slow_period) { $result.parameters.slow_period } else { "N/A" }
            $threshold = if ($result.parameters.crossover_threshold_pips) { $result.parameters.crossover_threshold_pips } else { "N/A" }
            Write-Host "  $($i + 1). Sharpe: $sharpe, Fast: $fast, Slow: $slow, Threshold: $threshold" -ForegroundColor White
        }
    } catch {
        Write-Host "  Error reading results: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host
Write-Host "=== Phase 3 Execution Complete ===" -ForegroundColor Green
Write-Host "Results available in:" -ForegroundColor Cyan
Write-Host "  - optimization/results/phase3_fine_grid_results.csv"
Write-Host "  - optimization/results/phase3_fine_grid_results_top_10.json"
Write-Host "  - optimization/results/phase3_fine_grid_results_summary.json"
Write-Host
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Review results: optimization/results/phase3_fine_grid_results_top_10.json"
Write-Host "2. Update PHASE3_EXECUTION_LOG.md with execution details"
Write-Host "3. Prepare Phase 4 configuration with best MA parameters"
Write-Host
Write-Host "✅ Phase 3 optimization completed successfully!" -ForegroundColor Green
