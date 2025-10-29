# Phase 6: Parameter Refinement and Sensitivity Analysis
# Automated Phase 6 execution for Windows with multi-objective Pareto analysis
# Selective refinement of most sensitive parameters from Phases 3-5 using Pareto optimization

param(
	[int]$Workers = 8,
	[switch]$NoArchive,
	[switch]$DryRun,
	[string]$Symbol,
	[string]$Venue,
	[string]$StartDate,
	[string]$EndDate,
	[string]$BarSpec,
	[string]$CatalogPath
)

# Script metadata
$ScriptName = "Phase 6: Parameter Refinement and Sensitivity Analysis"
$ScriptVersion = "1.0"
$ConfigFile = "optimization/configs/phase6_refinement.yaml"
$ExpectedRuntime = "4-6 hours"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  $ScriptName" -ForegroundColor Cyan
Write-Host "  Version: $ScriptVersion" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Usage information
if ($args -contains "-h" -or $args -contains "--help") {
	Write-Host "Usage: .\optimization\scripts\run_phase6.ps1 [-Workers <int>] [-NoArchive] [-DryRun] [-Symbol <str>] [-Venue <str>] [-StartDate <yyyy-MM-dd>] [-EndDate <yyyy-MM-dd>] [-BarSpec <str>] [-CatalogPath <path>]" -ForegroundColor Yellow
	Write-Host ""
	Write-Host "Parameters:" -ForegroundColor Yellow
	Write-Host "  -Workers <int>    Number of parallel workers (default: 8)" -ForegroundColor Yellow
	Write-Host "  -NoArchive       Skip archiving old results" -ForegroundColor Yellow
	Write-Host "  -DryRun          Show what would be executed without running" -ForegroundColor Yellow
	Write-Host "  -Symbol <str>     Override BACKTEST_SYMBOL (default/env fallback)" -ForegroundColor Yellow
	Write-Host "  -Venue <str>      Override BACKTEST_VENUE (default/env fallback)" -ForegroundColor Yellow
	Write-Host "  -StartDate <str>  Override BACKTEST_START_DATE yyyy-MM-dd (default/env fallback)" -ForegroundColor Yellow
	Write-Host "  -EndDate <str>    Override BACKTEST_END_DATE yyyy-MM-dd (default/env fallback)" -ForegroundColor Yellow
	Write-Host "  -BarSpec <str>    Override BACKTEST_BAR_SPEC (default/env fallback)" -ForegroundColor Yellow
	Write-Host "  -CatalogPath <p>  Override CATALOG_PATH (default/env fallback)" -ForegroundColor Yellow
	Write-Host ""
	Write-Host "Examples:" -ForegroundColor Yellow
	Write-Host "  .\optimization\scripts\run_phase6.ps1" -ForegroundColor Yellow
	Write-Host "  .\optimization\scripts\run_phase6.ps1 -Workers 12" -ForegroundColor Yellow
	Write-Host "  .\optimization\scripts\run_phase6.ps1 -Symbol EUR/USD -Venue IDEALPRO -StartDate 2025-01-01 -EndDate 2025-07-31 -BarSpec 15-MINUTE-MID-EXTERNAL -CatalogPath data/historical" -ForegroundColor Yellow
	Write-Host "  .\optimization\scripts\run_phase6.ps1 -DryRun" -ForegroundColor Yellow
	exit 0
}

# Environment Variable Setup
Write-Host "Setting up environment variables..." -ForegroundColor Green

# Resolve parameters -> env -> defaults
$resolvedSymbol = if ($PSBoundParameters.ContainsKey('Symbol') -and $Symbol) { $Symbol } elseif ($env:BACKTEST_SYMBOL -and $env:BACKTEST_SYMBOL.Trim().Length -gt 0) { $env:BACKTEST_SYMBOL } else { "EUR/USD" }
$resolvedVenue = if ($PSBoundParameters.ContainsKey('Venue') -and $Venue) { $Venue } elseif ($env:BACKTEST_VENUE -and $env:BACKTEST_VENUE.Trim().Length -gt 0) { $env:BACKTEST_VENUE } else { "IDEALPRO" }
$resolvedStart = if ($PSBoundParameters.ContainsKey('StartDate') -and $StartDate) { $StartDate } elseif ($env:BACKTEST_START_DATE -and $env:BACKTEST_START_DATE.Trim().Length -gt 0) { $env:BACKTEST_START_DATE } else { "2025-01-01" }
$resolvedEnd = if ($PSBoundParameters.ContainsKey('EndDate') -and $EndDate) { $EndDate } elseif ($env:BACKTEST_END_DATE -and $env:BACKTEST_END_DATE.Trim().Length -gt 0) { $env:BACKTEST_END_DATE } else { "2025-07-31" }
$resolvedBarSpec = if ($PSBoundParameters.ContainsKey('BarSpec') -and $BarSpec) { $BarSpec } elseif ($env:BACKTEST_BAR_SPEC -and $env:BACKTEST_BAR_SPEC.Trim().Length -gt 0) { $env:BACKTEST_BAR_SPEC } else { "15-MINUTE-MID-EXTERNAL" }
$resolvedCatalog = if ($PSBoundParameters.ContainsKey('CatalogPath') -and $CatalogPath) { $CatalogPath } elseif ($env:CATALOG_PATH -and $env:CATALOG_PATH.Trim().Length -gt 0) { $env:CATALOG_PATH } else { "data/historical" }

$env:BACKTEST_SYMBOL = $resolvedSymbol
$env:BACKTEST_VENUE = $resolvedVenue
$env:BACKTEST_START_DATE = $resolvedStart
$env:BACKTEST_END_DATE = $resolvedEnd
$env:BACKTEST_BAR_SPEC = $resolvedBarSpec
$env:CATALOG_PATH = $resolvedCatalog
$env:OUTPUT_DIR = "logs/backtest_results"

Write-Host "  BACKTEST_SYMBOL: $env:BACKTEST_SYMBOL" -ForegroundColor Gray
Write-Host "  BACKTEST_VENUE: $env:BACKTEST_VENUE" -ForegroundColor Gray
Write-Host "  BACKTEST_START_DATE: $env:BACKTEST_START_DATE" -ForegroundColor Gray
Write-Host "  BACKTEST_END_DATE: $env:BACKTEST_END_DATE" -ForegroundColor Gray
Write-Host "  BACKTEST_BAR_SPEC: $env:BACKTEST_BAR_SPEC" -ForegroundColor Gray
Write-Host "  CATALOG_PATH: $env:CATALOG_PATH" -ForegroundColor Gray
Write-Host "  OUTPUT_DIR: $env:OUTPUT_DIR" -ForegroundColor Gray
Write-Host ""

# Pre-flight Validation
Write-Host "Performing pre-flight validation..." -ForegroundColor Green

# Check Python availability
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  OK Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR Python not found or not in PATH" -ForegroundColor Red
    Write-Host "    Please install Python 3.8+ and ensure it is in your PATH" -ForegroundColor Red
    exit 1
}

# Verify Phase 6 config exists
if (-not (Test-Path $ConfigFile)) {
    Write-Host "  ERROR Phase 6 config not found: $ConfigFile" -ForegroundColor Red
    Write-Host "    Please ensure the configuration file exists" -ForegroundColor Red
    exit 1
}
Write-Host "  OK Phase 6 config found: $ConfigFile" -ForegroundColor Green

# Verify Phase 5 results exist
$phase5Results = "optimization/results/phase5_filters_results_top_10.json"
if (-not (Test-Path $phase5Results)) {
    Write-Host "  ERROR Phase 5 results not found: $phase5Results" -ForegroundColor Red
    Write-Host "    Phase 5 must be completed before running Phase 6" -ForegroundColor Red
    exit 1
}
Write-Host "  OK Phase 5 results found: $phase5Results" -ForegroundColor Green

# Verify catalog path exists
if (-not (Test-Path $env:CATALOG_PATH)) {
    Write-Host "  ERROR Catalog path not found: $env:CATALOG_PATH" -ForegroundColor Red
    Write-Host "    Please ensure the data catalog exists" -ForegroundColor Red
    exit 1
}
Write-Host "  OK Catalog path found: $env:CATALOG_PATH" -ForegroundColor Green

# Verify required instrument/bar subpaths exist and contain data
$symbolNoSlash = $env:BACKTEST_SYMBOL.Replace("/", "")
$instrumentId = "$symbolNoSlash.$($env:BACKTEST_VENUE)"
$barDir = Join-Path -Path $env:CATALOG_PATH -ChildPath ("data/bar/{0}-{1}" -f $instrumentId, $env:BACKTEST_BAR_SPEC)
$currencyPairDir = Join-Path -Path $env:CATALOG_PATH -ChildPath ("data/currency_pair/{0}" -f $instrumentId)

if (-not (Test-Path $barDir)) {
	Write-Host "  ERROR Required bar path not found: $barDir" -ForegroundColor Red
	Write-Host "    Ensure bar data exists for $instrumentId with spec $($env:BACKTEST_BAR_SPEC)" -ForegroundColor Red
	exit 1
}
$barParquets = Get-ChildItem -Path $barDir -Filter *.parquet -File -ErrorAction SilentlyContinue
if (-not $barParquets -or $barParquets.Count -eq 0) {
	Write-Host "  ERROR Bar path contains no .parquet files: $barDir" -ForegroundColor Red
	exit 1
}
Write-Host ("  OK Bar path ok: {0} ({1} parquet files)" -f $barDir, $barParquets.Count) -ForegroundColor Green

if (-not (Test-Path $currencyPairDir)) {
	Write-Host "  ERROR Required instrument path not found: $currencyPairDir" -ForegroundColor Red
	exit 1
}
$currencyPairFiles = Get-ChildItem -Path $currencyPairDir -File -ErrorAction SilentlyContinue
if (-not $currencyPairFiles -or $currencyPairFiles.Count -eq 0) {
	Write-Host "  ERROR Instrument path is empty: $currencyPairDir" -ForegroundColor Red
	exit 1
}
Write-Host "  OK Instrument path ok: $currencyPairDir" -ForegroundColor Green

# Scan for zero-byte parquet files in critical subpaths
$zeroByteFiles = @()
$zeroByteFiles += Get-ChildItem -Path $barDir -Filter *.parquet -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Length -eq 0 }
$zeroByteFiles += Get-ChildItem -Path $currencyPairDir -Filter *.parquet -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Length -eq 0 }
if ($zeroByteFiles.Count -gt 0) {
    Write-Host "  ERROR Zero-byte parquet files detected in catalog subpaths:" -ForegroundColor Red
	$zeroByteFiles | ForEach-Object { Write-Host "    - $($_.FullName)" -ForegroundColor Red }
	Write-Host "    Please repair the catalog (e.g., re-ingest or remove corrupt files) and retry." -ForegroundColor Red
	exit 1
}
Write-Host "  OK Catalog integrity check passed (no zero-byte parquet files)" -ForegroundColor Green

# Validate date range
$startDate = [DateTime]::ParseExact($env:BACKTEST_START_DATE, "yyyy-MM-dd", $null)
$endDate = [DateTime]::ParseExact($env:BACKTEST_END_DATE, "yyyy-MM-dd", $null)
if ($endDate -le $startDate) {
    Write-Host "  ERROR Invalid date range: End date must be after start date" -ForegroundColor Red
    exit 1
}
$duration = ($endDate - $startDate).TotalDays
Write-Host "  OK Date range valid: $duration days" -ForegroundColor Green

# Check required Python packages
Write-Host "  Checking required Python packages..." -ForegroundColor Gray
$requiredPackages = @("pandas", "yaml", "numpy", "scipy")
foreach ($package in $requiredPackages) {
    try {
        python -c "import $package" 2>$null
        Write-Host "    OK $package" -ForegroundColor Green
    } catch {
        Write-Host "    ERROR $package not found" -ForegroundColor Red
        Write-Host "      Please install: pip install $package" -ForegroundColor Red
        exit 1
    }
}

Write-Host "  OK All pre-flight checks passed" -ForegroundColor Green
Write-Host ""

# Archive Old Results
if (-not $NoArchive) {
    Write-Host "Archiving old Phase 6 results..." -ForegroundColor Green
    
    $archiveDir = ("optimization/results/archive/phase6_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
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

		$copyErrors = @()
		foreach ($file in $filesToArchive) {
			$fileName = Split-Path $file -Leaf
			$destination = Join-Path $archiveDir $fileName
			try {
				Copy-Item -Path $file -Destination $destination -ErrorAction Stop
			} catch {
                $copyErrors += ("Failed to copy {0} -> {1}: {2}" -f $file, $destination, $_.Exception.Message)
			}
		}

		if ($copyErrors.Count -gt 0) {
			Write-Host "  ERROR Archival aborted due to copy errors:" -ForegroundColor Red
			foreach ($err in $copyErrors) { Write-Host "    - $err" -ForegroundColor Red }
			Write-Host "    Originals have been left intact. Fix the issue and try again." -ForegroundColor Red
			try { Remove-Item -Path $archiveDir -Recurse -Force -ErrorAction Stop } catch { }
			exit 1
		}

		foreach ($file in $filesToArchive) {
			Remove-Item $file -Force
		}
        Write-Host "  OK Archived $($filesToArchive.Count) files to $archiveDir" -ForegroundColor Green
	} else {
        Write-Host "  OK No old Phase 6 files to archive" -ForegroundColor Green
	}
    Write-Host ""
}

# Display Execution Summary
Write-Host "Phase 6 Configuration:" -ForegroundColor Cyan
Write-Host "  Total combinations: 48 (selective refinement)" -ForegroundColor White
Write-Host "  Parameters being refined: stoch_period_d, stoch_bearish_threshold, stoch_period_k, stoch_bullish_threshold" -ForegroundColor White
Write-Host "  Fixed parameters: fast_period, slow_period, crossover_threshold_pips, stop_loss_pips, take_profit_pips, trailing_stop_activation_pips, trailing_stop_distance_pips, dmi_period" -ForegroundColor White
Write-Host "  Multi-objective optimization: sharpe_ratio, total_pnl, max_drawdown" -ForegroundColor White
Write-Host "  Workers: $Workers" -ForegroundColor White
Write-Host "  Expected runtime: $ExpectedRuntime" -ForegroundColor White
Write-Host ""

# Load Phase 5 baseline
Write-Host "Loading Phase 5 baseline..." -ForegroundColor Green
try {
    $phase5Data = Get-Content $phase5Results | ConvertFrom-Json
    $phase5Best = $phase5Data[0]
    # Read objective_value from Phase 5 top_10 JSON for the best Sharpe
    $phase5Sharpe = $phase5Best.objective_value
    # Access parameters via parameters.fast_period, etc.
    $params = $phase5Best.parameters
    Write-Host "  OK Phase 5 best Sharpe: $phase5Sharpe" -ForegroundColor Green
    Write-Host "  OK Phase 5 parameters: fast=$($params.fast_period), slow=$($params.slow_period), threshold=$($params.crossover_threshold_pips)" -ForegroundColor Green
} catch {
    Write-Host "  ERROR Could not load Phase 5 baseline" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Target: Maintain or improve Sharpe, generate robust Pareto frontier
Write-Host "Target: Maintain or improve Phase 5 Sharpe ($phase5Sharpe), generate robust Pareto frontier" -ForegroundColor Yellow
Write-Host ""

# Important: Highlight that this uses --pareto flag for multi-objective analysis
Write-Host "IMPORTANT: This execution uses --pareto flag for multi-objective analysis" -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN - Would execute the following command:" -ForegroundColor Yellow
    Write-Host ""
    $dryRunCmd = @(
        "python", "optimization/grid_search.py",
        "--config", "optimization/configs/phase6_refinement.yaml",
        "--objective", "sharpe_ratio",
        "--pareto", "sharpe_ratio", "total_pnl", "max_drawdown",
        "--workers", $Workers.ToString(),
        "--output", "optimization/results/phase6_refinement_results.csv",
        "--no-resume",
        "--verbose"
    ) -join " "
    Write-Host $dryRunCmd -ForegroundColor Gray
    Write-Host ""
    Write-Host "Analysis tools that would run:" -ForegroundColor Yellow
    Write-Host "  - python optimization/tools/analyze_parameter_sensitivity.py" -ForegroundColor Gray
    Write-Host "  - python optimization/tools/select_pareto_top5.py" -ForegroundColor Gray
    Write-Host "  - python optimization/tools/generate_phase6_analysis_report.py" -ForegroundColor Gray
    Write-Host ""
    Write-Host "DRY RUN COMPLETE" -ForegroundColor Yellow
    exit 0
}

# Execute Grid Search with Pareto Analysis
Write-Host "Executing Phase 6 parameter refinement with Pareto analysis..." -ForegroundColor Green
Write-Host ""

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

${cmdLine} = ($command -join " ")
Write-Host ("Command: {0}" -f $cmdLine) -ForegroundColor Gray
Write-Host ""

try {
    & $command[0] $command[1..($command.Length-1)]
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "  ERROR Grid search execution failed: $_" -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "Grid search completed in $duration" -ForegroundColor Green

if ($exitCode -ne 0) {
    Write-Host "  ERROR Grid search failed with exit code $exitCode" -ForegroundColor Red
    exit $exitCode
}

Write-Host "  OK Grid search completed successfully" -ForegroundColor Green
Write-Host ""

# Post-execution Validation
Write-Host "Validating Phase 6 results..." -ForegroundColor Green

# Verify output files exist
$requiredFiles = @(
    "optimization/results/phase6_refinement_results.csv",
    "optimization/results/phase6_refinement_results_top_10.json",
    "optimization/results/phase6_refinement_results_summary.json",
    "optimization/results/phase6_refinement_results_pareto_frontier.json"
)

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "  OK $file" -ForegroundColor Green
    } else {
        Write-Host "  ERROR $file not found" -ForegroundColor Red
        exit 1
    }
}

# Count CSV rows
try {
    $csvData = Import-Csv "optimization/results/phase6_refinement_results.csv"
    $rowCount = $csvData.Count
    Write-Host "  OK Results CSV contains $rowCount rows" -ForegroundColor Green
} catch {
    Write-Host "  ERROR Could not read results CSV" -ForegroundColor Red
    exit 1
}

# Load and display Pareto frontier size
try {
    $paretoData = Get-Content "optimization/results/phase6_refinement_results_pareto_frontier.json" | ConvertFrom-Json
    $frontierSize = $paretoData.frontier.Count
    Write-Host "  OK Pareto frontier contains $frontierSize non-dominated solutions" -ForegroundColor Green
} catch {
    Write-Host "  ERROR Could not read Pareto frontier JSON" -ForegroundColor Red
    exit 1
}

Write-Host "  OK All Phase 6 results validated" -ForegroundColor Green
Write-Host ""

# Run Analysis Tools
Write-Host "Running Phase 6 analysis tools..." -ForegroundColor Green

# Execute sensitivity analysis
Write-Host "  Running parameter sensitivity analysis..." -ForegroundColor Gray
try {
    python optimization/tools/analyze_parameter_sensitivity.py --csv optimization/results/phase6_refinement_results.csv --objectives sharpe_ratio total_pnl max_drawdown
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    ERROR Sensitivity analysis failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "    OK Sensitivity analysis completed" -ForegroundColor Green
} catch {
    Write-Host "    ERROR Sensitivity analysis failed: $_" -ForegroundColor Red
    exit 1
}

# Execute Pareto top 5 selection
Write-Host "  Running Pareto top 5 selection..." -ForegroundColor Gray
try {
    python optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json --output optimization/results/phase6_top_5_parameters.json
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    ERROR Pareto top 5 selection failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "    OK Pareto top 5 selection completed" -ForegroundColor Green
} catch {
    Write-Host "    ERROR Pareto top 5 selection failed: $_" -ForegroundColor Red
    exit 1
}

# Generate comprehensive analysis report
Write-Host "  Generating comprehensive analysis report..." -ForegroundColor Gray
try {
    python optimization/tools/generate_phase6_analysis_report.py --results-dir optimization/results --output optimization/results/PHASE6_ANALYSIS_REPORT.md
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    ERROR Report generation failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "    OK Comprehensive analysis report generated" -ForegroundColor Green
} catch {
    Write-Host "    ERROR Report generation failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "  OK All analysis tools completed successfully" -ForegroundColor Green
Write-Host ""

# Success Message and Next Steps
Write-Host "================================================" -ForegroundColor Green
Write-Host "  PHASE 6 COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""

# Show key findings
Write-Host "Key Findings:" -ForegroundColor Cyan
try {
    $top10Data = Get-Content "optimization/results/phase6_refinement_results_top_10.json" | ConvertFrom-Json
    $bestResult = $top10Data[0]
    Write-Host "  Best Sharpe ratio: $($bestResult.sharpe_ratio)" -ForegroundColor White
    Write-Host "  Best total PnL: $($bestResult.total_pnl)" -ForegroundColor White
    Write-Host "  Best max drawdown: $($bestResult.max_drawdown)" -ForegroundColor White
} catch {
    Write-Host "  Could not load best results" -ForegroundColor Yellow
}

Write-Host "  Pareto frontier size: $frontierSize non-dominated solutions" -ForegroundColor White
Write-Host "  Top 5 parameter sets selected for Phase 7" -ForegroundColor White
Write-Host "  Sensitivity analysis completed" -ForegroundColor White
Write-Host ""

# List output files
Write-Host "Output Files:" -ForegroundColor Cyan
Write-Host "  - optimization/results/phase6_refinement_results.csv" -ForegroundColor White
Write-Host "  - optimization/results/phase6_refinement_results_top_10.json" -ForegroundColor White
Write-Host "  - optimization/results/phase6_refinement_results_summary.json" -ForegroundColor White
Write-Host "  - optimization/results/phase6_refinement_results_pareto_frontier.json" -ForegroundColor White
Write-Host "  - optimization/results/phase6_sensitivity_analysis.json" -ForegroundColor White
Write-Host "  - optimization/results/phase6_top_5_parameters.json" -ForegroundColor White
Write-Host "  - optimization/results/PHASE6_ANALYSIS_REPORT.md" -ForegroundColor White
Write-Host ""

# Suggest next steps
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  - Review PHASE6_ANALYSIS_REPORT.md for comprehensive analysis" -ForegroundColor White
Write-Host "  - Review phase6_top_5_parameters.json for Phase 7 walk-forward validation" -ForegroundColor White
Write-Host "  - Prepare for Phase 7 walk-forward validation" -ForegroundColor White
Write-Host "  - Expected Phase 7 runtime: varies by walk-forward configuration" -ForegroundColor White
Write-Host ""

Write-Host "Phase 6 execution completed successfully!" -ForegroundColor Green
