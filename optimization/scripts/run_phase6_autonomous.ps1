# Phase 6: Parameter Refinement and Sensitivity Analysis - Autonomous Execution
# Fully autonomous Phase 6 execution without user prompts, including automatic analysis tool execution

param(
    [int]$Workers = 8,
    [switch]$SkipValidation,
    [switch]$ContinueOnError
)

# Script metadata
$ScriptName = "Phase 6: Parameter Refinement and Sensitivity Analysis - Autonomous"
$ScriptVersion = "1.0"
$ConfigFile = "optimization/configs/phase6_refinement.yaml"
$ExpectedRuntime = "4-6 hours"

# Create logs directory
$LogDir = "optimization/logs/phase6"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = "$LogDir/phase6_autonomous_$Timestamp.log"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# Function to write to both console and log
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $LogEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
    Write-Host $LogEntry
    Add-Content -Path $LogFile -Value $LogEntry
}

# Function to write error and exit
function Write-ErrorAndExit {
    param([string]$Message, [int]$ExitCode = 1)
    Write-Log $Message "ERROR"
    if (-not $ContinueOnError) {
        exit $ExitCode
    }
}

Write-Log "================================================"
Write-Log "  $ScriptName"
Write-Log "  Version: $ScriptVersion"
Write-Log "  Log file: $LogFile"
Write-Log "================================================"

# Environment Variable Setup
Write-Log "Setting up environment variables..."

$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

Write-Log "Environment variables configured"

# Pre-flight Validation
if (-not $SkipValidation) {
    Write-Log "Performing pre-flight validation..."

    # Check Python availability
    try {
        $pythonVersion = python --version 2>&1
        Write-Log "Python found: $pythonVersion"
    } catch {
        Write-ErrorAndExit "Python not found or not in PATH"
    }

    # Verify Phase 6 config exists
    if (-not (Test-Path $ConfigFile)) {
        Write-ErrorAndExit "Phase 6 config not found: $ConfigFile"
    }
    Write-Log "Phase 6 config found: $ConfigFile"

    # Verify Phase 5 results exist
    $phase5Results = "optimization/results/phase5_filters_results_top_10.json"
    if (-not (Test-Path $phase5Results)) {
        Write-ErrorAndExit "Phase 5 results not found: $phase5Results"
    }
    Write-Log "Phase 5 results found: $phase5Results"

    # Verify catalog path exists
    if (-not (Test-Path $env:CATALOG_PATH)) {
        Write-ErrorAndExit "Catalog path not found: $env:CATALOG_PATH"
    }
    Write-Log "Catalog path found: $env:CATALOG_PATH"

    # Check required Python packages
    $requiredPackages = @("pandas", "yaml", "numpy", "scipy")
    foreach ($package in $requiredPackages) {
        try {
            python -c "import $package" 2>$null
            Write-Log "Package $package verified"
        } catch {
            Write-ErrorAndExit "Package $package not found. Please install: pip install $package"
        }
    }

    Write-Log "All pre-flight checks passed"
} else {
    Write-Log "Skipping pre-flight validation"
}

# Archive Old Results
Write-Log "Archiving old Phase 6 results..."

$archiveDir = "optimization/results/archive/phase6_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$phase6Files = @(
    "optimization/results/phase6_refinement_results.csv",
    "optimization/results/phase6_refinement_results_top_10.json",
    "optimization/results/phase6_refinement_results_summary.json",
    "optimization/results/phase6_refinement_results_pareto_frontier.json",
    "optimization/results/phase6_sensitivity_analysis.json",
    "optimization/results/phase6_top_5_parameters.json",
    "optimization/results/PHASE6_ANALYSIS_REPORT.md"
)

$filesToArchive = @()
foreach ($file in $phase6Files) {
    if (Test-Path $file) {
        $filesToArchive += $file
    }
}

if ($filesToArchive.Count -gt 0) {
    New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    foreach ($file in $filesToArchive) {
        $fileName = Split-Path $file -Leaf
        Copy-Item $file "$archiveDir/$fileName"
        Remove-Item $file -Force
    }
    Write-Log "Archived $($filesToArchive.Count) files to $archiveDir"
} else {
    Write-Log "No old Phase 6 files to archive"
}

# Load Phase 5 Baseline
Write-Log "Loading Phase 5 baseline..."
try {
    $phase5Data = Get-Content $phase5Results | ConvertFrom-Json
    $phase5Best = $phase5Data[0]
    # Read objective_value from Phase 5 top_10 JSON for the best Sharpe
    $phase5Sharpe = $phase5Best.objective_value
    # Access parameters via parameters.fast_period, etc.
    $params = $phase5Best.parameters
    Write-Log "Phase 5 best Sharpe: $phase5Sharpe"
    Write-Log "Phase 5 parameters: fast=$($params.fast_period), slow=$($params.slow_period), threshold=$($params.crossover_threshold_pips)"
} catch {
    Write-ErrorAndExit "Could not load Phase 5 baseline: $_"
}

Write-Log "Target: Maintain or improve Phase 5 Sharpe ($phase5Sharpe), generate robust Pareto frontier"
Write-Log "IMPORTANT: Using --pareto flag for multi-objective analysis"

# Execute Grid Search with Pareto Analysis
Write-Log "Executing Phase 6 parameter refinement with Pareto analysis..."

$startTime = Get-Date
$command = @(
    "python", "optimization/grid_search.py",
    "--config", "optimization/configs/phase6_refinement.yaml",
    "--objective", "sharpe_ratio",
    "--pareto", "sharpe_ratio", "total_pnl", "max_drawdown",
    "--workers", $Workers.ToString(),
    "--output", "optimization/results/phase6_refinement_results.csv",
    "--no-resume",
    "--verbose"
)

Write-Log "Command: $($command -join ' ')"

try {
    # Stream output to log file
    & $command[0] $command[1..($command.Length-1)] 2>&1 | Tee-Object -FilePath "$LogDir/grid_search_output.log"
    $exitCode = $LASTEXITCODE
} catch {
    Write-ErrorAndExit "Grid search execution failed: $_"
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Log "Grid search completed in $($duration.ToString('hh\:mm\:ss'))"

if ($exitCode -ne 0) {
    Write-ErrorAndExit "Grid search failed with exit code $exitCode"
}

Write-Log "Grid search completed successfully"

# Progress Monitoring
Write-Log "Monitoring progress..."

$checkpointFile = "optimization/checkpoints/phase6_refinement_checkpoint.csv"
$lastProgressTime = Get-Date

while ($true) {
    Start-Sleep -Seconds 300  # Check every 5 minutes
    
    if (Test-Path $checkpointFile) {
        try {
            $checkpointData = Import-Csv $checkpointFile
            $completedRuns = $checkpointData.Count
            $currentTime = Get-Date
            $elapsed = $currentTime - $startTime
            
            Write-Log "Progress: $completedRuns runs completed in $($elapsed.ToString('hh\:mm\:ss'))"
            
            # Check if grid search is still running
            $gridSearchProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*grid_search*" }
            if ($gridSearchProcesses.Count -eq 0) {
                Write-Log "Grid search process completed"
                break
            }
        } catch {
            Write-Log "Could not read checkpoint file: $_"
        }
    } else {
        Write-Log "Checkpoint file not found, grid search may not have started"
    }
}

# Post-execution Validation
Write-Log "Validating Phase 6 results..."

$requiredFiles = @(
    "optimization/results/phase6_refinement_results.csv",
    "optimization/results/phase6_refinement_results_top_10.json",
    "optimization/results/phase6_refinement_results_summary.json",
    "optimization/results/phase6_refinement_results_pareto_frontier.json"
)

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Log "✓ $file"
    } else {
        Write-ErrorAndExit "✗ $file not found"
    }
}

# Count CSV rows
try {
    $csvData = Import-Csv "optimization/results/phase6_refinement_results.csv"
    $rowCount = $csvData.Count
    Write-Log "Results CSV contains $rowCount rows"
} catch {
    Write-ErrorAndExit "Could not read results CSV: $_"
}

# Load and display Pareto frontier size
try {
    $paretoData = Get-Content "optimization/results/phase6_refinement_results_pareto_frontier.json" | ConvertFrom-Json
    $frontierSize = $paretoData.frontier.Count
    Write-Log "Pareto frontier contains $frontierSize non-dominated solutions"
} catch {
    Write-ErrorAndExit "Could not read Pareto frontier JSON: $_"
}

Write-Log "All Phase 6 results validated"

# Run Analysis Tools Automatically
Write-Log "Running Phase 6 analysis tools automatically..."

# Execute sensitivity analysis
Write-Log "Running parameter sensitivity analysis..."
try {
    $sensitivityOutput = python optimization/tools/analyze_parameter_sensitivity.py --csv optimization/results/phase6_refinement_results.csv --objectives sharpe_ratio total_pnl max_drawdown 2>&1
    $sensitivityOutput | Add-Content -Path "$LogDir/sensitivity_analysis_output.log"
    
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorAndExit "Sensitivity analysis failed with exit code $LASTEXITCODE"
    }
    Write-Log "Sensitivity analysis completed successfully"
} catch {
    Write-ErrorAndExit "Sensitivity analysis failed: $_"
}

# Execute Pareto top 5 selection
Write-Log "Running Pareto top 5 selection..."
try {
    $paretoOutput = python optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json --output optimization/results/phase6_top_5_parameters.json 2>&1
    $paretoOutput | Add-Content -Path "$LogDir/pareto_selection_output.log"
    
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorAndExit "Pareto top 5 selection failed with exit code $LASTEXITCODE"
    }
    Write-Log "Pareto top 5 selection completed successfully"
} catch {
    Write-ErrorAndExit "Pareto top 5 selection failed: $_"
}

# Generate comprehensive analysis report
Write-Log "Generating comprehensive analysis report..."
try {
    $reportOutput = python optimization/tools/generate_phase6_analysis_report.py --results-dir optimization/results --output optimization/results/PHASE6_ANALYSIS_REPORT.md 2>&1
    $reportOutput | Add-Content -Path "$LogDir/report_generation_output.log"
    
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorAndExit "Report generation failed with exit code $LASTEXITCODE"
    }
    Write-Log "Comprehensive analysis report generated successfully"
} catch {
    Write-ErrorAndExit "Report generation failed: $_"
}

Write-Log "All analysis tools completed successfully"

# Generate Execution Summary
Write-Log "Generating execution summary..."

$totalDuration = (Get-Date) - $startTime
$executionSummary = @{
    "execution_date" = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "duration_hours" = $totalDuration.TotalHours
    "workers" = $Workers
    "total_runs" = $rowCount
    "pareto_frontier_size" = $frontierSize
    "phase5_baseline_sharpe" = $phase5Sharpe
    "log_file" = $LogFile
    "output_files" = @(
        "optimization/results/phase6_refinement_results.csv",
        "optimization/results/phase6_refinement_results_top_10.json",
        "optimization/results/phase6_refinement_results_summary.json",
        "optimization/results/phase6_refinement_results_pareto_frontier.json",
        "optimization/results/phase6_sensitivity_analysis.json",
        "optimization/results/phase6_top_5_parameters.json",
        "optimization/results/PHASE6_ANALYSIS_REPORT.md"
    )
}

$summaryJson = $executionSummary | ConvertTo-Json -Depth 3
$summaryJson | Out-File -FilePath "$LogDir/execution_summary.json" -Encoding UTF8

Write-Log "Execution summary saved to $LogDir/execution_summary.json"

# Success Summary
Write-Log "================================================"
Write-Log "  PHASE 6 AUTONOMOUS EXECUTION COMPLETED!"
Write-Log "================================================"
Write-Log "Duration: $($totalDuration.ToString('hh\:mm\:ss'))"
Write-Log "Total runs: $rowCount"
Write-Log "Pareto frontier size: $frontierSize"
Write-Log "Top 5 parameter sets selected for Phase 7"
Write-Log "Sensitivity analysis completed"
Write-Log "Comprehensive analysis report generated"
Write-Log ""
Write-Log "Output files:"
foreach ($file in $executionSummary.output_files) {
    if (Test-Path $file) {
        Write-Log "  ✓ $file"
    } else {
        Write-Log "  ✗ $file (missing)"
    }
}
Write-Log ""
Write-Log "Next steps:"
Write-Log "  - Review PHASE6_ANALYSIS_REPORT.md for comprehensive analysis"
Write-Log "  - Review phase6_top_5_parameters.json for Phase 7 walk-forward validation"
Write-Log "  - Prepare for Phase 7 walk-forward validation"
Write-Log ""
Write-Log "Phase 6 autonomous execution completed successfully!"
Write-Log "Log file: $LogFile"
