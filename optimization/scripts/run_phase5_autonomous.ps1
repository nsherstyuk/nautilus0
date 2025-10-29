#Requires -Version 5.1

<#
.SYNOPSIS
    Autonomous Phase 5 Filter Optimization - No User Interaction Required

.DESCRIPTION
    This script executes Phase 5 filter optimization autonomously without user prompts.
    It monitors progress, validates results, and generates a comprehensive report.
    
    Features:
    - No user interaction required (fully autonomous)
    - Real-time progress monitoring
    - Automatic validation script execution
    - Automatic report generation
    - Comprehensive logging to file
    - Enhanced error handling and recovery
    - Support for both full and reduced configurations

.PARAMETER Workers
    Number of parallel workers for grid search execution (default: 8)

.PARAMETER UseReduced
    Use reduced configuration (108 combinations, ~2 hours) instead of full (2,400 combinations, ~40 hours)

.PARAMETER SkipValidation
    Skip pre-flight validation checks (use with caution)

.PARAMETER ContinueOnError
    Continue execution even if some backtests fail

.EXAMPLE
    .\run_phase5_autonomous.ps1
    Execute Phase 5 with default settings (8 workers, full configuration)

.EXAMPLE
    .\run_phase5_autonomous.ps1 -UseReduced
    Execute with reduced configuration (108 combinations, ~2 hours)

.EXAMPLE
    .\run_phase5_autonomous.ps1 -Workers 12 -UseReduced
    Execute with 12 workers and reduced configuration

.EXAMPLE
    .\run_phase5_autonomous.ps1 -SkipValidation
    Skip validation checks (use only if you're certain environment is ready)

.NOTES
    Author: Autonomous Phase 5 Execution System
    Version: 1.0
    Requires: PowerShell 5.1+, Python 3.8+, Phase 3 and Phase 4 results
#>

param(
    [int]$Workers = 8,
    [switch]$UseReduced,
    [switch]$SkipValidation,
    [switch]$ContinueOnError
)

# Script configuration
$ScriptName = "Phase 5 Autonomous Execution"
$Version = "1.0"
$StartTime = Get-Date

# Logging setup
$LogDir = "optimization/logs/phase5"
$LogFile = Join-Path $LogDir "phase5_execution_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Create log directory if it doesn't exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Logging function
function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogEntry = "[$Timestamp] [$Level] $Message"
    
    # Write to console with color coding
    switch ($Level) {
        "SUCCESS" { Write-Host $LogEntry -ForegroundColor Green }
        "WARNING" { Write-Host $LogEntry -ForegroundColor Yellow }
        "ERROR"   { Write-Host $LogEntry -ForegroundColor Red }
        default   { Write-Host $LogEntry -ForegroundColor White }
    }
    
    # Write to log file
    Add-Content -Path $LogFile -Value $LogEntry
}

# Initialize execution data collection
$ExecutionData = @{
    StartTime = $StartTime
    EndTime = $null
    Duration = $null
    SuccessRate = 0
    CompletedCount = 0
    FailedCount = 0
    Workers = $Workers
    UseReduced = $UseReduced
    Phase3Baseline = @{}
    Phase4Baseline = @{}
    Phase5Best = @{}
    Top10Results = @()
    ValidationReport = @{}
    ErrorLog = @()
}

try {
    Write-Log "=== $ScriptName v$Version ===" "SUCCESS"
    Write-Log "Start time: $($StartTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Log "Workers: $Workers"
    Write-Log "Use reduced: $UseReduced"
    Write-Log "Skip validation: $SkipValidation"
    Write-Log "Continue on error: $ContinueOnError"
    Write-Log "Log file: $LogFile"

    # Environment variable setup
    Write-Log "Setting up environment variables..."
    
    $env:BACKTEST_SYMBOL = "EUR/USD"
    $env:BACKTEST_VENUE = "IDEALPRO"
    $env:BACKTEST_START_DATE = "2025-01-01"
    $env:BACKTEST_END_DATE = "2025-07-31"
    $env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
    $env:CATALOG_PATH = "data/historical"
    $env:OUTPUT_DIR = "logs/backtest_results"
    $env:PHASE5_AUTONOMOUS = "true"
    
    Write-Log "Environment variables set successfully" "SUCCESS"
    Write-Log "Final resolved values:"
    Write-Log "  BACKTEST_SYMBOL: $env:BACKTEST_SYMBOL"
    Write-Log "  BACKTEST_VENUE: $env:BACKTEST_VENUE"
    Write-Log "  BACKTEST_START_DATE: $env:BACKTEST_START_DATE"
    Write-Log "  BACKTEST_END_DATE: $env:BACKTEST_END_DATE"
    Write-Log "  BACKTEST_BAR_SPEC: $env:BACKTEST_BAR_SPEC"
    Write-Log "  CATALOG_PATH: $env:CATALOG_PATH"
    Write-Log "  OUTPUT_DIR: $env:OUTPUT_DIR"

    # Pre-flight validation
    if (-not $SkipValidation) {
        Write-Log "Running pre-flight validation..."
        
        # Check Python availability
        try {
            $pythonVersion = python --version 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Python not found or not accessible"
            }
            Write-Log "✓ Python available: $pythonVersion" "SUCCESS"
        }
        catch {
            $errorMsg = "Python validation failed: $_"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }

        # Check Phase 5 config file (both full and reduced versions)
        if ($UseReduced) {
            $configFile = "optimization/configs/phase5_filters_reduced.yaml"
            $outputFile = "optimization/results/phase5_filters_reduced_results.csv"
            $checkpointFile = "optimization/checkpoints/phase5_filters_reduced_checkpoint.csv"
            $expectedCombinations = 108
        } else {
            $configFile = "optimization/configs/phase5_filters.yaml"
            $outputFile = "optimization/results/phase5_filters_results.csv"
            $checkpointFile = "optimization/checkpoints/phase5_filters_checkpoint.csv"
            $expectedCombinations = 2400
        }

        if (-not (Test-Path $configFile)) {
            $errorMsg = "Phase 5 config file not found: $configFile"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Phase 5 config file exists: $configFile" "SUCCESS"

        # Check Phase 3 results
        $phase3Results = "optimization/results/phase3_fine_grid_results_top_10.json"
        if (-not (Test-Path $phase3Results)) {
            $errorMsg = "Phase 3 results not found: $phase3Results"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Phase 3 results exist: $phase3Results" "SUCCESS"

        # Check Phase 4 results
        $phase4Results = "optimization/results/phase4_risk_management_results_top_10.json"
        if (-not (Test-Path $phase4Results)) {
            $errorMsg = "Phase 4 results not found: $phase4Results"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Phase 4 results exist: $phase4Results" "SUCCESS"

        # Check catalog path
        if (-not (Test-Path $env:CATALOG_PATH)) {
            $errorMsg = "Catalog path not found: $env:CATALOG_PATH"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Catalog path exists: $env:CATALOG_PATH" "SUCCESS"

        # Validate date range
        try {
            $startDate = [DateTime]::Parse($env:BACKTEST_START_DATE)
            $endDate = [DateTime]::Parse($env:BACKTEST_END_DATE)
            if ($endDate -le $startDate) {
                throw "End date must be after start date"
            }
            Write-Log "✓ Date range valid: $($env:BACKTEST_START_DATE) to $($env:BACKTEST_END_DATE)" "SUCCESS"
        }
        catch {
            $errorMsg = "Date validation failed: $_"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }

        # Check required Python packages
        $requiredPackages = @("pandas", "numpy", "yaml", "pathlib")
        foreach ($package in $requiredPackages) {
            try {
                python -c "import $package" 2>$null
                if ($LASTEXITCODE -ne 0) {
                    throw "Package not available"
                }
                Write-Log "✓ Python package available: $package" "SUCCESS"
            }
            catch {
                $errorMsg = "Required Python package not found: $package"
                Write-Log $errorMsg "ERROR"
                $ExecutionData.ErrorLog += $errorMsg
                if (-not $ContinueOnError) { exit 1 }
            }
        }

        Write-Log "Pre-flight validation completed successfully" "SUCCESS"
    }
    else {
        Write-Log "Skipping pre-flight validation (user requested)" "WARNING"
    }

    # Archive old results
    Write-Log "Checking for existing Phase 5 results..."
    
    if ($UseReduced) {
        $resultFiles = @(
            "optimization/results/phase5_filters_reduced_results.csv",
            "optimization/results/phase5_filters_reduced_results_top_10.json",
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    } else {
        $resultFiles = @(
            "optimization/results/phase5_filters_results.csv",
            "optimization/results/phase5_filters_results_top_10.json",
            "optimization/results/phase5_filters_results_summary.json"
        )
    }
    
    $existingFiles = $resultFiles | Where-Object { Test-Path $_ }
    
    if ($existingFiles.Count -gt 0) {
        $archiveDir = "optimization/results/archive/phase5"
        if (-not (Test-Path $archiveDir)) {
            New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
        }
        
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $archiveSubDir = Join-Path $archiveDir "phase5_results_$timestamp"
        New-Item -ItemType Directory -Path $archiveSubDir -Force | Out-Null
        
        foreach ($file in $existingFiles) {
            $fileName = Split-Path $file -Leaf
            $archivePath = Join-Path $archiveSubDir $fileName
            Copy-Item $file $archivePath
            Write-Log "Archived: $file -> $archivePath"
        }
        
        Write-Log "Archived $($existingFiles.Count) existing result files to: $archiveSubDir" "SUCCESS"
    }
    else {
        Write-Log "No existing Phase 5 results found to archive"
    }

    # Load Phase 3 baseline
    Write-Log "Loading Phase 3 baseline results..."
    
    try {
        $phase3Data = Get-Content "optimization/results/phase3_fine_grid_results_top_10.json" | ConvertFrom-Json
        $phase3Best = $phase3Data[0]  # Rank 1 result
        
        $ExecutionData.Phase3Baseline = @{
            SharpeRatio = $phase3Best.objective_value
            FastPeriod = $phase3Best.parameters.fast_period
            SlowPeriod = $phase3Best.parameters.slow_period
            Threshold = $phase3Best.parameters.crossover_threshold_pips
            WinRate = $null  # Will be populated from CSV if needed
            TradeCount = $null  # Will be populated from CSV if needed
            TotalPnL = $null  # Will be populated from CSV if needed
            MaxDrawdown = $null  # Will be populated from CSV if needed
        }
        
        # Populate missing Phase 3 metrics from CSV if available
        try {
            $phase3CsvPath = "optimization/results/phase3_fine_grid_results.csv"
            if (Test-Path $phase3CsvPath) {
                $phase3CsvData = Import-Csv $phase3CsvPath
                $phase3CsvRow = $phase3CsvData | Where-Object { $_.run_id -eq $phase3Best.run_id } | Select-Object -First 1
                
                if ($phase3CsvRow) {
                    $ExecutionData.Phase3Baseline.WinRate = [double]$phase3CsvRow.win_rate
                    $ExecutionData.Phase3Baseline.TradeCount = [int]$phase3CsvRow.trade_count
                    $ExecutionData.Phase3Baseline.TotalPnL = [double]$phase3CsvRow.total_pnl
                    if ($phase3CsvRow.max_drawdown) {
                        $ExecutionData.Phase3Baseline.MaxDrawdown = [double]$phase3CsvRow.max_drawdown
                    }
                    Write-Log "  Phase 3 metrics populated from CSV" "SUCCESS"
                }
            }
        }
        catch {
            Write-Log "  Warning: Could not populate Phase 3 metrics from CSV: $_" "WARNING"
        }
        
        Write-Log "Phase 3 baseline loaded:" "SUCCESS"
        Write-Log "  Sharpe ratio: $($ExecutionData.Phase3Baseline.SharpeRatio)"
        Write-Log "  MA params: fast=$($ExecutionData.Phase3Baseline.FastPeriod), slow=$($ExecutionData.Phase3Baseline.SlowPeriod), threshold=$($ExecutionData.Phase3Baseline.Threshold)"
    }
    catch {
        $errorMsg = "Failed to load Phase 3 baseline: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 1 }
    }

    # Load Phase 4 baseline
    Write-Log "Loading Phase 4 baseline results..."
    
    try {
        $phase4Data = Get-Content "optimization/results/phase4_risk_management_results_top_10.json" | ConvertFrom-Json
        $phase4Best = $phase4Data[0]  # Rank 1 result
        
        $ExecutionData.Phase4Baseline = @{
            SharpeRatio = $phase4Best.objective_value
            StopLoss = $phase4Best.parameters.stop_loss_pips
            TakeProfit = $phase4Best.parameters.take_profit_pips
            TrailingActivation = $phase4Best.parameters.trailing_stop_activation_pips
            TrailingDistance = $phase4Best.parameters.trailing_stop_distance_pips
            WinRate = $null  # Will be populated from CSV if needed
            TradeCount = $null  # Will be populated from CSV if needed
            TotalPnL = $null  # Will be populated from CSV if needed
            MaxDrawdown = $null  # Will be populated from CSV if needed
        }
        
        # Populate missing Phase 4 metrics from CSV if available
        try {
            $phase4CsvPath = "optimization/results/phase4_risk_management_results.csv"
            if (Test-Path $phase4CsvPath) {
                $phase4CsvData = Import-Csv $phase4CsvPath
                $phase4CsvRow = $phase4CsvData | Where-Object { $_.run_id -eq $phase4Best.run_id } | Select-Object -First 1
                
                if ($phase4CsvRow) {
                    $ExecutionData.Phase4Baseline.WinRate = [double]$phase4CsvRow.win_rate
                    $ExecutionData.Phase4Baseline.TradeCount = [int]$phase4CsvRow.trade_count
                    $ExecutionData.Phase4Baseline.TotalPnL = [double]$phase4CsvRow.total_pnl
                    if ($phase4CsvRow.max_drawdown) {
                        $ExecutionData.Phase4Baseline.MaxDrawdown = [double]$phase4CsvRow.max_drawdown
                    }
                    Write-Log "  Phase 4 metrics populated from CSV" "SUCCESS"
                }
            }
        }
        catch {
            Write-Log "  Warning: Could not populate Phase 4 metrics from CSV: $_" "WARNING"
        }
        
        Write-Log "Phase 4 baseline loaded:" "SUCCESS"
        Write-Log "  Sharpe ratio: $($ExecutionData.Phase4Baseline.SharpeRatio)"
        Write-Log "  Risk params: SL=$($ExecutionData.Phase4Baseline.StopLoss), TP=$($ExecutionData.Phase4Baseline.TakeProfit), TA=$($ExecutionData.Phase4Baseline.TrailingActivation), TD=$($ExecutionData.Phase4Baseline.TrailingDistance)"
    }
    catch {
        $errorMsg = "Failed to load Phase 4 baseline: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 1 }
    }

    # Execute grid search
    Write-Log "Starting Phase 5 grid search execution..."
    $configFile = if ($UseReduced) { "optimization/configs/phase5_filters_reduced.yaml" } else { "optimization/configs/phase5_filters.yaml" }
    $outputFile = if ($UseReduced) { "optimization/results/phase5_filters_reduced_results.csv" } else { "optimization/results/phase5_filters_results.csv" }
    $checkpointFile = if ($UseReduced) { "optimization/checkpoints/phase5_filters_reduced_checkpoint.csv" } else { "optimization/checkpoints/phase5_filters_checkpoint.csv" }
    $expectedCombinations = if ($UseReduced) { 108 } else { 2400 }
    
    Write-Log "Command: python optimization/grid_search.py --config $configFile --objective sharpe_ratio --workers $Workers --output $outputFile --no-resume --verbose"
    
    $gridSearchStartTime = Get-Date
    
    # Start background progress monitoring
    $monitoringJob = Start-Job -ScriptBlock {
        param($LogFile, $CheckpointFile, $StartTime, $ExpectedCombinations)
        
        function Write-Log {
            param([string]$Message, [string]$Level = "INFO")
            $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $LogEntry = "[$Timestamp] [$Level] $Message"
            Add-Content -Path $LogFile -Value $LogEntry
        }
        
        $lastCount = 0
        $stallCount = 0
        $maxStallMinutes = 30
        
        while ($true) {
            Start-Sleep -Seconds 300  # 5 minutes
            
            try {
                if (Test-Path $CheckpointFile) {
                    $csvData = Import-Csv $CheckpointFile
                    $currentCount = $csvData.Count
                    $elapsed = (Get-Date) - $StartTime
                    $percentage = [math]::Round(($currentCount / $ExpectedCombinations) * 100, 1)
                    
                    if ($currentCount -gt $lastCount) {
                        $avgTimePerRun = $elapsed.TotalSeconds / $currentCount
                        $remaining = $ExpectedCombinations - $currentCount
                        $etaSeconds = $remaining * $avgTimePerRun
                        $eta = [TimeSpan]::FromSeconds($etaSeconds)
                        
                        Write-Log "Progress: $currentCount/$ExpectedCombinations ($percentage%) - ETA: $($eta.ToString('hh\:mm\:ss'))" "INFO"
                        $lastCount = $currentCount
                        $stallCount = 0
                    }
                    else {
                        $stallCount++
                        if ($stallCount -ge ($maxStallMinutes / 5)) {
                            Write-Log "WARNING: No progress for $($stallCount * 5) minutes. Grid search may be stalled." "WARNING"
                        }
                    }
                }
                else {
                    Write-Log "Checkpoint file not found yet. Grid search may still be starting." "INFO"
                }
            }
            catch {
                Write-Log "Error monitoring progress: $_" "ERROR"
            }
        }
    } -ArgumentList $LogFile, $checkpointFile, $gridSearchStartTime, $expectedCombinations
    
    try {
        # Change to project root directory
        $originalLocation = Get-Location
        Set-Location (Split-Path $PSScriptRoot -Parent -Parent)
        
        # Execute grid search with output capture
        $gridSearchOutput = python optimization/grid_search.py --config $configFile --objective sharpe_ratio --workers $Workers --output $outputFile --no-resume --verbose 2>&1
        
        $gridSearchExitCode = $LASTEXITCODE
        $gridSearchEndTime = Get-Date
        $gridSearchDuration = $gridSearchEndTime - $gridSearchStartTime
        
        # Stop monitoring job
        Stop-Job $monitoringJob -PassThru | Remove-Job
        
        # Log grid search output
        Write-Log "Grid search completed in $($gridSearchDuration.ToString('hh\:mm\:ss'))"
        Write-Log "Exit code: $gridSearchExitCode"
        
        # Log output to file
        $gridSearchOutput | ForEach-Object { Write-Log "GRID_SEARCH: $_" }
        
        if ($gridSearchExitCode -ne 0) {
            throw "Grid search failed with exit code $gridSearchExitCode"
        }
        
        Write-Log "Grid search execution completed successfully" "SUCCESS"
    }
    catch {
        # Stop monitoring job on error
        Stop-Job $monitoringJob -PassThru | Remove-Job
        
        $errorMsg = "Grid search execution failed: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 4 }
    }
    finally {
        # Restore original location
        Set-Location $originalLocation
    }

    # Post-execution validation
    Write-Log "Validating Phase 5 results..."
    
    # Check output files exist
    $outputFiles = if ($UseReduced) {
        @(
            "optimization/results/phase5_filters_reduced_results.csv",
            "optimization/results/phase5_filters_reduced_results_top_10.json",
            "optimization/results/phase5_filters_reduced_results_summary.json"
        )
    } else {
        @(
            "optimization/results/phase5_filters_results.csv",
            "optimization/results/phase5_filters_results_top_10.json",
            "optimization/results/phase5_filters_results_summary.json"
        )
    }
    
    foreach ($file in $outputFiles) {
        if (-not (Test-Path $file)) {
            $errorMsg = "Required output file not found: $file"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 2 }
        }
        Write-Log "✓ Output file exists: $file" "SUCCESS"
    }
    
    # Count CSV rows
    try {
        $csvData = Import-Csv $outputFile
        $csvRowCount = $csvData.Count
        Write-Log "CSV contains $csvRowCount result rows"
        
        $minExpected = [math]::Round($expectedCombinations * 0.9)  # 90% of expected
        if ($csvRowCount -lt $minExpected) {
            $errorMsg = "Insufficient results: $csvRowCount < $minExpected (90% of $expectedCombinations)"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 2 }
        }
        
        $ExecutionData.CompletedCount = $csvRowCount
        $ExecutionData.SuccessRate = [math]::Round(($csvRowCount / $expectedCombinations) * 100, 1)
        Write-Log "Success rate: $($ExecutionData.SuccessRate)% ($csvRowCount/$expectedCombinations)" "SUCCESS"
    }
    catch {
        $errorMsg = "Failed to validate CSV results: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 2 }
    }
    
    # Load best result
    try {
        $top10File = if ($UseReduced) { "optimization/results/phase5_filters_reduced_results_top_10.json" } else { "optimization/results/phase5_filters_results_top_10.json" }
        $top10Data = Get-Content $top10File | ConvertFrom-Json
        $bestResult = $top10Data[0]  # Rank 1 result
        
        $ExecutionData.Phase5Best = @{
            RunId = $bestResult.run_id
            SharpeRatio = $bestResult.objective_value
            DmiEnabled = $bestResult.parameters.dmi_enabled
            DmiPeriod = $bestResult.parameters.dmi_period
            StochPeriodK = $bestResult.parameters.stoch_period_k
            StochPeriodD = $bestResult.parameters.stoch_period_d
            StochBullishThreshold = $bestResult.parameters.stoch_bullish_threshold
            StochBearishThreshold = $bestResult.parameters.stoch_bearish_threshold
            WinRate = $null  # Will be populated from CSV if needed
            TradeCount = $null  # Will be populated from CSV if needed
            TotalPnL = $null  # Will be populated from CSV if needed
            MaxDrawdown = $null  # Will be populated from CSV if needed
            ProfitFactor = $null  # Will be populated from CSV if needed
        }
        
        $ExecutionData.Top10Results = $top10Data
        
        # Populate missing metrics from CSV by matching run_id
        try {
            $csvData = Import-Csv $outputFile
            $bestCsvRow = $csvData | Where-Object { $_.run_id -eq $ExecutionData.Phase5Best.RunId } | Select-Object -First 1
            
            if ($bestCsvRow) {
                $ExecutionData.Phase5Best.WinRate = [double]$bestCsvRow.win_rate
                $ExecutionData.Phase5Best.TradeCount = [int]$bestCsvRow.trade_count
                $ExecutionData.Phase5Best.TotalPnL = [double]$bestCsvRow.total_pnl
                $ExecutionData.Phase5Best.MaxDrawdown = [double]$bestCsvRow.max_drawdown
                $ExecutionData.Phase5Best.ProfitFactor = [double]$bestCsvRow.profit_factor
                Write-Log "  Metrics populated from CSV" "SUCCESS"
            }
        }
        catch {
            Write-Log "  Warning: Could not populate metrics from CSV: $_" "WARNING"
        }
        
        Write-Log "Best Phase 5 result loaded:" "SUCCESS"
        Write-Log "  Run ID: $($ExecutionData.Phase5Best.RunId)"
        Write-Log "  Sharpe ratio: $($ExecutionData.Phase5Best.SharpeRatio)"
        Write-Log "  Filter params: DMI=$($ExecutionData.Phase5Best.DmiEnabled), DMI_Period=$($ExecutionData.Phase5Best.DmiPeriod), Stoch_K=$($ExecutionData.Phase5Best.StochPeriodK), Stoch_D=$($ExecutionData.Phase5Best.StochPeriodD)"
        Write-Log "  Performance: Win rate=$($ExecutionData.Phase5Best.WinRate)%, Trades=$($ExecutionData.Phase5Best.TradeCount), PnL=$$($ExecutionData.Phase5Best.TotalPnL)"
    }
    catch {
        $errorMsg = "Failed to load Phase 5 best result: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 2 }
    }

    # Run validation script
    Write-Log "Running Phase 5 validation script..."
    
    try {
        $validationOutput = python optimization/scripts/validate_phase5_results.py --csv $outputFile --phase4-sharpe $($ExecutionData.Phase4Baseline.SharpeRatio) --expected-combinations $expectedCombinations --json-output optimization/results/phase5_validation_report.json 2>&1
        
        $validationExitCode = $LASTEXITCODE
        
        # Log validation output
        $validationOutput | ForEach-Object { Write-Log "VALIDATION: $_" }
        
        if ($validationExitCode -eq 1) {
            $errorMsg = "Critical validation failure (exit code 1)"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 3 }
        }
        elseif ($validationExitCode -eq 2) {
            Write-Log "Validation completed with warnings (exit code 2)" "WARNING"
        }
        else {
            Write-Log "Validation completed successfully (exit code 0)" "SUCCESS"
        }
        
        # Load validation report
        if (Test-Path "optimization/results/phase5_validation_report.json") {
            $ExecutionData.ValidationReport = Get-Content "optimization/results/phase5_validation_report.json" | ConvertFrom-Json
        }
    }
    catch {
        $errorMsg = "Validation script execution failed: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 3 }
    }

    # Generate execution report
    Write-Log "Generating comprehensive execution report..."
    
    try {
        # Set end time and calculate duration
        $ExecutionData.EndTime = Get-Date
        $ExecutionData.Duration = $ExecutionData.EndTime - $ExecutionData.StartTime
        
        # Call report generation script
        $reportScript = Join-Path $PSScriptRoot "generate_phase5_report.ps1"
        if (Test-Path $reportScript) {
            & $reportScript -ExecutionData $ExecutionData -OutputPath "optimization/results/PHASE5_EXECUTION_REPORT.md"
            Write-Log "Execution report generated: optimization/results/PHASE5_EXECUTION_REPORT.md" "SUCCESS"
        }
        else {
            Write-Log "Report generation script not found: $reportScript" "WARNING"
        }
    }
    catch {
        $errorMsg = "Report generation failed: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 5 }
    }

    # Success summary
    Write-Log "=== PHASE 5 AUTONOMOUS EXECUTION COMPLETE ===" "SUCCESS"
    Write-Log "Duration: $($ExecutionData.Duration.ToString('hh\:mm\:ss'))"
    Write-Log "Success rate: $($ExecutionData.SuccessRate)% ($($ExecutionData.CompletedCount)/$expectedCombinations)"
    Write-Log "Best Sharpe ratio: $($ExecutionData.Phase5Best.SharpeRatio)"
    
    $improvement = [math]::Round((($ExecutionData.Phase5Best.SharpeRatio - $ExecutionData.Phase4Baseline.SharpeRatio) / $ExecutionData.Phase4Baseline.SharpeRatio) * 100, 1)
    if ($improvement -gt 0) {
        Write-Log "Improvement over Phase 4: +$improvement%" "SUCCESS"
    } else {
        Write-Log "Change vs Phase 4: $improvement%" "WARNING"
    }
    
    Write-Log "Best filter parameters:"
    Write-Log "  DMI Enabled: $($ExecutionData.Phase5Best.DmiEnabled)"
    Write-Log "  DMI Period: $($ExecutionData.Phase5Best.DmiPeriod)"
    Write-Log "  Stochastic K: $($ExecutionData.Phase5Best.StochPeriodK)"
    Write-Log "  Stochastic D: $($ExecutionData.Phase5Best.StochPeriodD)"
    Write-Log "  Bullish Threshold: $($ExecutionData.Phase5Best.StochBullishThreshold)"
    Write-Log "  Bearish Threshold: $($ExecutionData.Phase5Best.StochBearishThreshold)"
    
    Write-Log ""
    Write-Log "Output files:"
    foreach ($file in $outputFiles) {
        Write-Log "  $file"
    }
    Write-Log "  Validation report: optimization/results/phase5_validation_report.json"
    Write-Log "  Execution report: optimization/results/PHASE5_EXECUTION_REPORT.md"
    Write-Log "  Execution log: $LogFile"
    
    Write-Log ""
    Write-Log "Next steps:"
    Write-Log "  1. Review PHASE5_EXECUTION_REPORT.md for detailed analysis"
    Write-Log "  2. Analyze filter impact on win rate and trade count"
    if ($UseReduced) {
        Write-Log "  3. If results are promising, run full version: .\optimization\scripts\run_phase5_autonomous.ps1"
    } else {
        Write-Log "  3. Prepare Phase 6 configuration with Phase 5 best filter parameters"
    }
    Write-Log "  4. Archive Phase 5 results"
    
    Write-Log "Autonomous execution completed successfully!" "SUCCESS"
    exit 0
}
catch {
    $errorMsg = "Fatal error in autonomous execution: $_"
    Write-Log $errorMsg "ERROR"
    $ExecutionData.ErrorLog += $errorMsg
    
    # Set end time for error case
    $ExecutionData.EndTime = Get-Date
    $ExecutionData.Duration = $ExecutionData.EndTime - $ExecutionData.StartTime
    
    Write-Log "Autonomous execution failed!" "ERROR"
    Write-Log "Check log file for details: $LogFile"
    exit 1
}

