#Requires -Version 5.1

<#
.SYNOPSIS
    Autonomous Phase 4 Risk Management Optimization - No User Interaction Required

.DESCRIPTION
    This script executes Phase 4 optimization autonomously without user prompts.
    It monitors progress, validates results, and generates a comprehensive report.
    
    Features:
    - No user interaction required (fully autonomous)
    - Real-time progress monitoring
    - Automatic validation script execution
    - Automatic report generation
    - Comprehensive logging to file
    - Enhanced error handling and recovery

.PARAMETER Workers
    Number of parallel workers for grid search execution (default: 8)

.PARAMETER SkipValidation
    Skip pre-flight validation checks (use with caution)

.PARAMETER ContinueOnError
    Continue execution even if some backtests fail

.EXAMPLE
    .\run_phase4_autonomous.ps1
    Execute Phase 4 with default settings (8 workers)

.EXAMPLE
    .\run_phase4_autonomous.ps1 -Workers 12 -ContinueOnError
    Execute with 12 workers and continue on errors

.EXAMPLE
    .\run_phase4_autonomous.ps1 -SkipValidation
    Skip validation checks (use only if you're certain environment is ready)

.NOTES
    Author: Autonomous Phase 4 Execution System
    Version: 1.0
    Requires: PowerShell 5.1+, Python 3.8+, Phase 3 results
#>

param(
    [int]$Workers = 8,
    [switch]$SkipValidation,
    [switch]$ContinueOnError
)

# Script configuration
$ScriptName = "Phase 4 Autonomous Execution"
$Version = "1.0"
$StartTime = Get-Date

# Logging setup
$LogDir = "optimization/logs/phase4"
$LogFile = Join-Path $LogDir "phase4_execution_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

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
    Phase3Baseline = @{}
    Phase4Best = @{}
    Top10Results = @()
    ValidationReport = @{}
    ErrorLog = @()
}

try {
    Write-Log "=== $ScriptName v$Version ===" "SUCCESS"
    Write-Log "Start time: $($StartTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Log "Workers: $Workers"
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
    $env:PHASE4_AUTONOMOUS = "true"
    
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

        # Check Phase 4 config file
        $configFile = "optimization/configs/phase4_risk_management.yaml"
        if (-not (Test-Path $configFile)) {
            $errorMsg = "Phase 4 config file not found: $configFile"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Phase 4 config file exists: $configFile" "SUCCESS"

        # Check Phase 3 results
        $phase3Results = "optimization/results/phase3_fine_grid_results_top_10.json"
        if (-not (Test-Path $phase3Results)) {
            $errorMsg = "Phase 3 results not found: $phase3Results"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 1 }
        }
        Write-Log "✓ Phase 3 results exist: $phase3Results" "SUCCESS"

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
    Write-Log "Checking for existing Phase 4 results..."
    
    $resultFiles = @(
        "optimization/results/phase4_risk_management_results.csv",
        "optimization/results/phase4_risk_management_results_top_10.json",
        "optimization/results/phase4_risk_management_results_summary.json"
    )
    
    $existingFiles = $resultFiles | Where-Object { Test-Path $_ }
    
    if ($existingFiles.Count -gt 0) {
        $archiveDir = "optimization/results/archive/phase4"
        if (-not (Test-Path $archiveDir)) {
            New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
        }
        
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $archiveSubDir = Join-Path $archiveDir "phase4_results_$timestamp"
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
        Write-Log "No existing Phase 4 results found to archive"
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
            StopLoss = $phase3Best.parameters.stop_loss_pips
            TakeProfit = $phase3Best.parameters.take_profit_pips
            TrailingActivation = $phase3Best.parameters.trailing_stop_activation_pips
            TrailingDistance = $phase3Best.parameters.trailing_stop_distance_pips
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
        Write-Log "  Risk params: SL=$($ExecutionData.Phase3Baseline.StopLoss), TP=$($ExecutionData.Phase3Baseline.TakeProfit), TA=$($ExecutionData.Phase3Baseline.TrailingActivation), TD=$($ExecutionData.Phase3Baseline.TrailingDistance)"
    }
    catch {
        $errorMsg = "Failed to load Phase 3 baseline: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 1 }
    }

    # Execute grid search
    Write-Log "Starting Phase 4 grid search execution..."
    Write-Log "Command: python optimization/grid_search.py --config optimization/configs/phase4_risk_management.yaml --objective sharpe_ratio --workers $Workers --output optimization/results/phase4_risk_management_results.csv --no-resume --verbose"
    
    $gridSearchStartTime = Get-Date
    
    # Start background progress monitoring
    $monitoringJob = Start-Job -ScriptBlock {
        param($LogFile, $CheckpointFile, $StartTime)
        
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
                    $percentage = [math]::Round(($currentCount / 500) * 100, 1)
                    
                    if ($currentCount -gt $lastCount) {
                        $avgTimePerRun = $elapsed.TotalSeconds / $currentCount
                        $remaining = 500 - $currentCount
                        $etaSeconds = $remaining * $avgTimePerRun
                        $eta = [TimeSpan]::FromSeconds($etaSeconds)
                        
                        Write-Log "Progress: $currentCount/500 ($percentage%) - ETA: $($eta.ToString('hh\:mm\:ss'))" "INFO"
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
    } -ArgumentList $LogFile, "optimization/checkpoints/phase4_risk_management_checkpoint.csv", $gridSearchStartTime
    
    try {
        # Change to project root directory
        $originalLocation = Get-Location
        Set-Location (Split-Path $PSScriptRoot -Parent -Parent)
        
        # Execute grid search with output capture
        $gridSearchOutput = python optimization/grid_search.py --config optimization/configs/phase4_risk_management.yaml --objective sharpe_ratio --workers $Workers --output optimization/results/phase4_risk_management_results.csv --no-resume --verbose 2>&1
        
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
    Write-Log "Validating Phase 4 results..."
    
    # Check output files exist
    $outputFiles = @(
        "optimization/results/phase4_risk_management_results.csv",
        "optimization/results/phase4_risk_management_results_top_10.json",
        "optimization/results/phase4_risk_management_results_summary.json"
    )
    
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
        $csvData = Import-Csv "optimization/results/phase4_risk_management_results.csv"
        $csvRowCount = $csvData.Count
        Write-Log "CSV contains $csvRowCount result rows"
        
        if ($csvRowCount -lt 450) {
            $errorMsg = "Insufficient results: $csvRowCount < 450 (90% of 500)"
            Write-Log $errorMsg "ERROR"
            $ExecutionData.ErrorLog += $errorMsg
            if (-not $ContinueOnError) { exit 2 }
        }
        
        $ExecutionData.CompletedCount = $csvRowCount
        $ExecutionData.SuccessRate = [math]::Round(($csvRowCount / 500) * 100, 1)
        Write-Log "Success rate: $($ExecutionData.SuccessRate)% ($csvRowCount/500)" "SUCCESS"
    }
    catch {
        $errorMsg = "Failed to validate CSV results: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 2 }
    }
    
    # Load best result
    try {
        $top10Data = Get-Content "optimization/results/phase4_risk_management_results_top_10.json" | ConvertFrom-Json
        $bestResult = $top10Data[0]  # Rank 1 result
        
        $ExecutionData.Phase4Best = @{
            RunId = $bestResult.run_id
            SharpeRatio = $bestResult.objective_value
            StopLoss = $bestResult.parameters.stop_loss_pips
            TakeProfit = $bestResult.parameters.take_profit_pips
            TrailingActivation = $bestResult.parameters.trailing_stop_activation_pips
            TrailingDistance = $bestResult.parameters.trailing_stop_distance_pips
            WinRate = $null  # Will be populated from CSV if needed
            TradeCount = $null  # Will be populated from CSV if needed
            TotalPnL = $null  # Will be populated from CSV if needed
            MaxDrawdown = $null  # Will be populated from CSV if needed
            ProfitFactor = $null  # Will be populated from CSV if needed
        }
        
        $ExecutionData.Top10Results = $top10Data
        
        # Populate missing metrics from CSV by matching run_id
        try {
            $csvData = Import-Csv "optimization/results/phase4_risk_management_results.csv"
            $bestCsvRow = $csvData | Where-Object { $_.run_id -eq $ExecutionData.Phase4Best.RunId } | Select-Object -First 1
            
            if ($bestCsvRow) {
                $ExecutionData.Phase4Best.WinRate = [double]$bestCsvRow.win_rate
                $ExecutionData.Phase4Best.TradeCount = [int]$bestCsvRow.trade_count
                $ExecutionData.Phase4Best.TotalPnL = [double]$bestCsvRow.total_pnl
                $ExecutionData.Phase4Best.MaxDrawdown = [double]$bestCsvRow.max_drawdown
                $ExecutionData.Phase4Best.ProfitFactor = [double]$bestCsvRow.profit_factor
                Write-Log "  Metrics populated from CSV" "SUCCESS"
            }
        }
        catch {
            Write-Log "  Warning: Could not populate metrics from CSV: $_" "WARNING"
        }
        
        Write-Log "Best Phase 4 result loaded:" "SUCCESS"
        Write-Log "  Run ID: $($ExecutionData.Phase4Best.RunId)"
        Write-Log "  Sharpe ratio: $($ExecutionData.Phase4Best.SharpeRatio)"
        Write-Log "  Risk params: SL=$($ExecutionData.Phase4Best.StopLoss), TP=$($ExecutionData.Phase4Best.TakeProfit), TA=$($ExecutionData.Phase4Best.TrailingActivation), TD=$($ExecutionData.Phase4Best.TrailingDistance)"
        Write-Log "  Performance: Win rate=$($ExecutionData.Phase4Best.WinRate)%, Trades=$($ExecutionData.Phase4Best.TradeCount), PnL=$$($ExecutionData.Phase4Best.TotalPnL)"
    }
    catch {
        $errorMsg = "Failed to load Phase 4 best result: $_"
        Write-Log $errorMsg "ERROR"
        $ExecutionData.ErrorLog += $errorMsg
        if (-not $ContinueOnError) { exit 2 }
    }

    # Run validation script
    Write-Log "Running Phase 4 validation script..."
    
    try {
        $validationOutput = python optimization/scripts/validate_phase4_results.py --csv optimization/results/phase4_risk_management_results.csv --phase3-sharpe $($ExecutionData.Phase3Baseline.SharpeRatio) --json-output optimization/results/phase4_validation_report.json 2>&1
        
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
        if (Test-Path "optimization/results/phase4_validation_report.json") {
            $ExecutionData.ValidationReport = Get-Content "optimization/results/phase4_validation_report.json" | ConvertFrom-Json
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
        $reportScript = Join-Path $PSScriptRoot "generate_phase4_report.ps1"
        if (Test-Path $reportScript) {
            & $reportScript -ExecutionData $ExecutionData -OutputPath "optimization/results/PHASE4_EXECUTION_REPORT.md"
            Write-Log "Execution report generated: optimization/results/PHASE4_EXECUTION_REPORT.md" "SUCCESS"
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
    Write-Log "=== PHASE 4 AUTONOMOUS EXECUTION COMPLETE ===" "SUCCESS"
    Write-Log "Duration: $($ExecutionData.Duration.ToString('hh\:mm\:ss'))"
    Write-Log "Success rate: $($ExecutionData.SuccessRate)% ($($ExecutionData.CompletedCount)/500)"
    Write-Log "Best Sharpe ratio: $($ExecutionData.Phase4Best.SharpeRatio)"
    
    $improvement = [math]::Round((($ExecutionData.Phase4Best.SharpeRatio - $ExecutionData.Phase3Baseline.SharpeRatio) / $ExecutionData.Phase3Baseline.SharpeRatio) * 100, 1)
    Write-Log "Improvement over Phase 3: +$improvement%"
    
    Write-Log "Best risk management parameters:"
    Write-Log "  Stop Loss: $($ExecutionData.Phase4Best.StopLoss) pips"
    Write-Log "  Take Profit: $($ExecutionData.Phase4Best.TakeProfit) pips"
    Write-Log "  Trailing Activation: $($ExecutionData.Phase4Best.TrailingActivation) pips"
    Write-Log "  Trailing Distance: $($ExecutionData.Phase4Best.TrailingDistance) pips"
    
    Write-Log ""
    Write-Log "Output files:"
    Write-Log "  Results CSV: optimization/results/phase4_risk_management_results.csv"
    Write-Log "  Top 10 JSON: optimization/results/phase4_risk_management_results_top_10.json"
    Write-Log "  Summary JSON: optimization/results/phase4_risk_management_results_summary.json"
    Write-Log "  Validation report: optimization/results/phase4_validation_report.json"
    Write-Log "  Execution report: optimization/results/PHASE4_EXECUTION_REPORT.md"
    Write-Log "  Execution log: $LogFile"
    
    Write-Log ""
    Write-Log "Next steps:"
    Write-Log "  1. Review PHASE4_EXECUTION_REPORT.md for detailed analysis"
    Write-Log "  2. Prepare Phase 5 configuration with Phase 4 best parameters"
    Write-Log "  3. Archive Phase 4 results"
    
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
