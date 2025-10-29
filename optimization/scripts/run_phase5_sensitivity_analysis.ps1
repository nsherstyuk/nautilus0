# Phase 5 Parameter Sensitivity Analysis Script
# 
# This script executes comprehensive parameter sensitivity analysis on Phase 5 results
# to identify the 4 most sensitive parameters for Phase 6 refinement.
#
# Prerequisites:
# - Phase 5 must be completed (phase5_filters_results.csv exists)
# - Python environment with required packages (pandas, numpy, scipy)
#
# Expected Outputs:
# - phase5_sensitivity_analysis.json (complete analysis data)
# - PHASE5_SENSITIVITY_REPORT.md (human-readable report)
# - phase5_correlation_matrix.csv (correlation data for spreadsheet analysis)
#
# Estimated Runtime: < 1 minute

param(
    [string]$CsvPath = "optimization/results/phase5_filters_results.csv",
    [string]$OutputDir = "optimization/results",
    [switch]$Verbose
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Color definitions for output
$ColorGreen = "Green"
$ColorRed = "Red"
$ColorYellow = "Yellow"
$ColorWhite = "White"

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

function Test-Prerequisites {
    Write-ColorOutput "Validating prerequisites..." $ColorYellow
    
    # Check if CSV file exists
    if (-not (Test-Path $CsvPath)) {
        Write-ColorOutput "ERROR: Phase 5 results file not found: $CsvPath" $ColorRed
        Write-ColorOutput "Please ensure Phase 5 has been completed successfully." $ColorRed
        exit 1
    }
    
    # Check if CSV file is not empty
    $csvFile = Get-Item $CsvPath
    if ($csvFile.Length -eq 0) {
        Write-ColorOutput "ERROR: Phase 5 results file is empty: $CsvPath" $ColorRed
        Write-ColorOutput "Please ensure Phase 5 has been completed successfully." $ColorRed
        exit 1
    }
    
    # Check if summary JSON exists (optional validation)
    $summaryPath = "optimization/results/phase5_filters_results_summary.json"
    if (-not (Test-Path $summaryPath)) {
        Write-ColorOutput "WARNING: Phase 5 summary file not found: $summaryPath" $ColorYellow
        Write-ColorOutput "Proceeding with analysis..." $ColorYellow
    }
    
    Write-ColorOutput "Prerequisites validated successfully." $ColorGreen
}

function Invoke-SensitivityAnalysis {
    Write-ColorOutput "Starting Phase 5 sensitivity analysis..." $ColorWhite
    
    # Build Python command
    $pythonCmd = "python optimization/tools/analyze_phase5_sensitivity.py --csv `"$CsvPath`" --output-dir `"$OutputDir`""
    
    if ($Verbose) {
        $pythonCmd += " --verbose"
    }
    
    Write-ColorOutput "Executing: $pythonCmd" $ColorWhite
    
    # Execute Python script
    try {
        $exitCode = 0
        Invoke-Expression $pythonCmd
        $exitCode = $LASTEXITCODE
    }
    catch {
        Write-ColorOutput "ERROR: Failed to execute Python script: $($_.Exception.Message)" $ColorRed
        exit 1
    }
    
    # Check exit code
    if ($exitCode -ne 0) {
        Write-ColorOutput "ERROR: Python script failed with exit code $exitCode" $ColorRed
        Write-ColorOutput "Troubleshooting suggestions:" $ColorYellow
        Write-ColorOutput "1. Ensure Python is installed and in PATH" $ColorYellow
        Write-ColorOutput "2. Install required packages: pip install pandas numpy scipy" $ColorYellow
        Write-ColorOutput "3. Check that the CSV file is valid and not corrupted" $ColorYellow
        Write-ColorOutput "4. Run with --verbose flag for detailed error information" $ColorYellow
        exit 1
    }
    
    Write-ColorOutput "Phase 5 sensitivity analysis completed successfully." $ColorGreen
}

function Test-OutputFiles {
    Write-ColorOutput "Validating output files..." $ColorYellow
    
    $expectedFiles = @(
        "$OutputDir/phase5_sensitivity_analysis.json",
        "$OutputDir/PHASE5_SENSITIVITY_REPORT.md",
        "$OutputDir/phase5_correlation_matrix.csv"
    )
    
    $allFilesExist = $true
    
    foreach ($file in $expectedFiles) {
        if (Test-Path $file) {
            $fileInfo = Get-Item $file
            Write-ColorOutput "[OK] $file ($($fileInfo.Length) bytes)" $ColorGreen
        }
        else {
            Write-ColorOutput "[MISSING] $file" $ColorRed
            $allFilesExist = $false
        }
    }
    
    if (-not $allFilesExist) {
        Write-ColorOutput "ERROR: Some expected output files are missing." $ColorRed
        Write-ColorOutput "Please check the Python script execution for errors." $ColorRed
        exit 1
    }
    
    Write-ColorOutput "All output files validated successfully." $ColorGreen
}

function Show-Summary {
    Write-ColorOutput "Reading analysis summary..." $ColorWhite
    
    $jsonPath = "$OutputDir/phase5_sensitivity_analysis.json"
    
    if (Test-Path $jsonPath) {
        try {
            $jsonContent = Get-Content $jsonPath -Raw | ConvertFrom-Json
            
            Write-ColorOutput ("`n" + ("=" * 60)) $ColorWhite
            Write-ColorOutput "PHASE 5 SENSITIVITY ANALYSIS SUMMARY" $ColorWhite
            Write-ColorOutput ("=" * 60) $ColorWhite
            
            Write-ColorOutput "Dataset Size: $($jsonContent.metadata.dataset_size) completed runs" $ColorWhite
            Write-ColorOutput "Best Sharpe Ratio: $($jsonContent.metadata.best_sharpe_ratio)" $ColorWhite
            Write-ColorOutput "Parameters Analyzed: $($jsonContent.metadata.parameters_analyzed)" $ColorWhite
            
            Write-ColorOutput "`nTop 4 Most Sensitive Parameters:" $ColorGreen
            foreach ($param in $jsonContent.top_4_sensitive_parameters) {
                Write-ColorOutput "  $($param.rank). $($param.parameter_name): $($param.sensitivity_score)" $ColorGreen
            }
            
            Write-ColorOutput "`nOutput Files:" $ColorWhite
            Write-ColorOutput "  - JSON: $OutputDir/phase5_sensitivity_analysis.json" $ColorWhite
            Write-ColorOutput "  - Report: $OutputDir/PHASE5_SENSITIVITY_REPORT.md" $ColorWhite
            Write-ColorOutput "  - CSV: $OutputDir/phase5_correlation_matrix.csv" $ColorWhite
            
            Write-ColorOutput ("=" * 60) $ColorWhite
        }
        catch {
            Write-ColorOutput "WARNING: Could not parse JSON summary: $($_.Exception.Message)" $ColorYellow
        }
    }
    else {
        Write-ColorOutput "WARNING: Could not find JSON summary file" $ColorYellow
    }
}

function Show-NextSteps {
    Write-ColorOutput "`nNext Steps:" $ColorYellow
    Write-ColorOutput "1. Review the sensitivity analysis report:" $ColorWhite
    Write-ColorOutput "   Get-Content `"$OutputDir/PHASE5_SENSITIVITY_REPORT.md`"" $ColorWhite
    Write-ColorOutput "`n2. Update Phase 6 configuration based on findings:" $ColorWhite
    Write-ColorOutput "   Edit optimization/configs/phase6_refinement.yaml" $ColorWhite
    Write-ColorOutput "   - Refine only the 4 most sensitive parameters" $ColorWhite
    Write-ColorOutput "   - Fix remaining 7 parameters at Phase 5 best values" $ColorWhite
    Write-ColorOutput "`n3. Run Phase 6 with updated configuration:" $ColorWhite
    Write-ColorOutput "   .\optimization\scripts\run_phase6.ps1" $ColorWhite
}

# Main execution
try {
    Write-ColorOutput "Phase 5 Parameter Sensitivity Analysis" $ColorGreen
    Write-ColorOutput "=====================================" $ColorGreen
    Write-ColorOutput "CSV Path: $CsvPath" $ColorWhite
    Write-ColorOutput "Output Dir: $OutputDir" $ColorWhite
    Write-ColorOutput "Verbose: $Verbose" $ColorWhite
    Write-ColorOutput "" $ColorWhite
    
    # Validate prerequisites
    Test-Prerequisites
    
    # Execute sensitivity analysis
    Invoke-SensitivityAnalysis
    
    # Validate output files
    Test-OutputFiles
    
    # Show summary
    Show-Summary
    
    # Show next steps
    Show-NextSteps
    
    Write-ColorOutput "`nPhase 5 sensitivity analysis completed successfully!" $ColorGreen
}
catch {
    Write-ColorOutput "`nERROR: Script execution failed: $($_.Exception.Message)" $ColorRed
    Write-ColorOutput "Please check the error details above and try again." $ColorRed
    exit 1
}