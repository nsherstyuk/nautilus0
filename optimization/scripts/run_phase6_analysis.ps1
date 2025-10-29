#Requires -Version 5.1

<#
.SYNOPSIS
    Phase 6 Analysis Orchestration Script

.DESCRIPTION
    Orchestrates the execution of all three Phase 6 analysis tools in sequence:
    1. Parameter sensitivity analysis
    2. Pareto frontier top 5 selection
    3. Comprehensive analysis report generation

    This script automates the post-execution analysis workflow for Phase 6,
    generating 6 output files required for Phase 7 preparation.

.PARAMETER ResultsDir
    Directory containing Phase 6 results (default: optimization/results)

.PARAMETER Verbose
    Enable verbose logging for analysis tools

.PARAMETER ContinueOnError
    Continue execution if individual tools fail

.EXAMPLE
    .\run_phase6_analysis.ps1
    Run Phase 6 analysis with default settings

.EXAMPLE
    .\run_phase6_analysis.ps1 -Verbose -ContinueOnError
    Run Phase 6 analysis with verbose logging and error tolerance

.NOTES
    Prerequisites: Phase 6 grid search must be completed
    Expected Outputs: 6 files (sensitivity analysis, Pareto selection, comprehensive report)
    Estimated Runtime: < 5 minutes
#>

param(
    [string]$ResultsDir = "optimization/results",
    [switch]$Verbose,
    [switch]$ContinueOnError
)

# Color definitions for console output
$ColorGreen = "Green"
$ColorRed = "Red"
$ColorYellow = "Yellow"
$ColorCyan = "Cyan"
$ColorWhite = "White"

# Helper function to write colored output
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = $ColorWhite
    )
    Write-Host $Message -ForegroundColor $Color
}

# Helper function to write step headers
function Write-StepHeader {
    param(
        [int]$StepNumber,
        [string]$StepName
    )
    Write-ColorOutput "`n" $ColorCyan
    Write-ColorOutput "=" * 60 $ColorCyan
    Write-ColorOutput "Step $StepNumber/3: $StepName" $ColorCyan
    Write-ColorOutput "=" * 60 $ColorCyan
    Write-ColorOutput ""
}

# Helper function to test file existence
function Test-FileExists {
    param(
        [string]$Path,
        [string]$Description
    )
    
    if (-not (Test-Path $Path)) {
        Write-ColorOutput "ERROR: $Description not found at: $Path" $ColorRed
        return $false
    }
    
    if ((Get-Item $Path).Length -eq 0) {
        Write-ColorOutput "ERROR: $Description is empty at: $Path" $ColorRed
        return $false
    }
    
    return $true
}

# Validate prerequisites function
function Validate-Prerequisites {
    Write-ColorOutput "Validating Phase 6 execution prerequisites..." $ColorCyan
    
    $prerequisites = @(
        @{ Path = "$ResultsDir/phase6_refinement_results.csv"; Description = "Phase 6 results CSV" },
        @{ Path = "$ResultsDir/phase6_refinement_results_pareto_frontier.json"; Description = "Pareto frontier JSON" },
        @{ Path = "$ResultsDir/phase6_refinement_results_top_10.json"; Description = "Top 10 results JSON" },
        @{ Path = "$ResultsDir/phase6_refinement_results_summary.json"; Description = "Summary JSON" }
    )
    
    $allValid = $true
    foreach ($prereq in $prerequisites) {
        if (-not (Test-FileExists $prereq.Path $prereq.Description)) {
            $allValid = $false
        }
    }
    
    if (-not $allValid) {
        Write-ColorOutput "`nPrerequisites validation failed!" $ColorRed
        Write-ColorOutput "Please run Phase 6 grid search first using: .\run_phase6.ps1" $ColorYellow
        Write-ColorOutput "Then verify all result files are generated before running analysis." $ColorYellow
        return $false
    }
    
    Write-ColorOutput "All prerequisites validated successfully!" $ColorGreen
    return $true
}

# Execute parameter sensitivity analysis
function Invoke-SensitivityAnalysis {
    Write-StepHeader 1 "Parameter Sensitivity Analysis"
    
    $command = "python optimization/tools/analyze_parameter_sensitivity.py --csv `"$ResultsDir/phase6_refinement_results.csv`" --objectives sharpe_ratio total_pnl max_drawdown --output-dir `"$ResultsDir`""
    
    if ($Verbose) {
        $command += " --verbose"
    }
    
    Write-ColorOutput "Analyzing parameter correlations..." $ColorCyan
    Write-ColorOutput "Calculating variance contributions..." $ColorCyan
    Write-ColorOutput "Generating sensitivity report..." $ColorCyan
    Write-ColorOutput ""
    
    try {
        Invoke-Expression $command
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            # Verify outputs
            $outputs = @(
                "$ResultsDir/phase6_sensitivity_analysis.json",
                "$ResultsDir/phase6_sensitivity_summary.md",
                "$ResultsDir/phase6_correlation_matrix.csv"
            )
            
            $allOutputsExist = $true
            foreach ($output in $outputs) {
                if (-not (Test-Path $output)) {
                    Write-ColorOutput "WARNING: Expected output not found: $output" $ColorYellow
                    $allOutputsExist = $false
                }
            }
            
            if ($allOutputsExist) {
                Write-ColorOutput "Sensitivity analysis completed successfully!" $ColorGreen
                Write-ColorOutput "Generated files:" $ColorGreen
                foreach ($output in $outputs) {
                    Write-ColorOutput "  - $output" $ColorGreen
                }
            } else {
                Write-ColorOutput "Sensitivity analysis completed with warnings - some outputs missing" $ColorYellow
            }
        } else {
            Write-ColorOutput "Sensitivity analysis failed with exit code: $exitCode" $ColorRed
            Write-ColorOutput "Check the error messages above for troubleshooting guidance." $ColorYellow
        }
        
        return $exitCode
    }
    catch {
        Write-ColorOutput "Error executing sensitivity analysis: $($_.Exception.Message)" $ColorRed
        return 1
    }
}

# Execute Pareto frontier top 5 selection
function Invoke-ParetoTop5Selection {
    Write-StepHeader 2 "Pareto Frontier Top 5 Selection"
    
    $command = "python optimization/tools/select_pareto_top5.py --pareto-json `"$ResultsDir/phase6_refinement_results_pareto_frontier.json`" --output `"$ResultsDir/phase6_top_5_parameters.json`" --n 5"
    
    if ($Verbose) {
        $command += " --verbose"
    }
    
    Write-ColorOutput "Loading Pareto frontier..." $ColorCyan
    Write-ColorOutput "Normalizing objectives..." $ColorCyan
    Write-ColorOutput "Selecting diverse parameter sets..." $ColorCyan
    Write-ColorOutput "Exporting for Phase 7..." $ColorCyan
    Write-ColorOutput ""
    
    try {
        Invoke-Expression $command
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            # Verify outputs
            $outputs = @(
                "$ResultsDir/phase6_top_5_parameters.json",
                "$ResultsDir/phase6_pareto_selection_report.md"
            )
            
            $allOutputsExist = $true
            foreach ($output in $outputs) {
                if (-not (Test-Path $output)) {
                    Write-ColorOutput "WARNING: Expected output not found: $output" $ColorYellow
                    $allOutputsExist = $false
                }
            }
            
            if ($allOutputsExist) {
                Write-ColorOutput "Pareto top 5 selection completed successfully!" $ColorGreen
                Write-ColorOutput "Generated files:" $ColorGreen
                foreach ($output in $outputs) {
                    Write-ColorOutput "  - $output" $ColorGreen
                }
            } else {
                Write-ColorOutput "Pareto selection completed with warnings - some outputs missing" $ColorYellow
            }
        } else {
            Write-ColorOutput "Pareto top 5 selection failed with exit code: $exitCode" $ColorRed
            Write-ColorOutput "Check the error messages above for troubleshooting guidance." $ColorYellow
        }
        
        return $exitCode
    }
    catch {
        Write-ColorOutput "Error executing Pareto selection: $($_.Exception.Message)" $ColorRed
        return 1
    }
}

# Execute comprehensive report generation
function Invoke-ComprehensiveReport {
    Write-StepHeader 3 "Comprehensive Analysis Report"
    
    $command = "python optimization/tools/generate_phase6_analysis_report.py --results-dir `"$ResultsDir`" --output `"$ResultsDir/PHASE6_ANALYSIS_REPORT.md`""
    
    if ($Verbose) {
        $command += " --verbose"
    }
    
    Write-ColorOutput "Loading Phase 6 artifacts..." $ColorCyan
    Write-ColorOutput "Generating executive summary..." $ColorCyan
    Write-ColorOutput "Generating sensitivity section..." $ColorCyan
    Write-ColorOutput "Generating Pareto section..." $ColorCyan
    Write-ColorOutput "Generating recommendations..." $ColorCyan
    Write-ColorOutput ""
    
    try {
        Invoke-Expression $command
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            # Verify output
            if (Test-Path "$ResultsDir/PHASE6_ANALYSIS_REPORT.md") {
                Write-ColorOutput "Comprehensive report generation completed successfully!" $ColorGreen
                Write-ColorOutput "Generated file: $ResultsDir/PHASE6_ANALYSIS_REPORT.md" $ColorGreen
            } else {
                Write-ColorOutput "WARNING: Expected output not found: $ResultsDir/PHASE6_ANALYSIS_REPORT.md" $ColorYellow
            }
        } else {
            Write-ColorOutput "Comprehensive report generation failed with exit code: $exitCode" $ColorRed
            Write-ColorOutput "Check the error messages above for troubleshooting guidance." $ColorYellow
        }
        
        return $exitCode
    }
    catch {
        Write-ColorOutput "Error executing comprehensive report generation: $($_.Exception.Message)" $ColorRed
        return 1
    }
}

# Show analysis summary
function Show-AnalysisSummary {
    Write-ColorOutput "`n" $ColorCyan
    Write-ColorOutput "=" * 60 $ColorCyan
    Write-ColorOutput "Phase 6 Analysis Complete" $ColorCyan
    Write-ColorOutput "=" * 60 $ColorCyan
    
    $expectedFiles = @(
        "phase6_sensitivity_analysis.json",
        "phase6_sensitivity_summary.md", 
        "phase6_correlation_matrix.csv",
        "phase6_top_5_parameters.json",
        "phase6_pareto_selection_report.md",
        "PHASE6_ANALYSIS_REPORT.md"
    )
    
    $generatedFiles = @()
    foreach ($file in $expectedFiles) {
        $fullPath = "$ResultsDir/$file"
        if (Test-Path $fullPath) {
            $size = (Get-Item $fullPath).Length
            $sizeKB = [math]::Round($size / 1KB, 2)
            $generatedFiles += "$file ($sizeKB KB)"
        }
    }
    
    Write-ColorOutput "Generated Files ($($generatedFiles.Count)/$($expectedFiles.Count)):" $ColorGreen
    foreach ($file in $generatedFiles) {
        Write-ColorOutput "  ✓ $file" $ColorGreen
    }
    
    $missingFiles = $expectedFiles | Where-Object { -not (Test-Path "$ResultsDir/$_") }
    if ($missingFiles.Count -gt 0) {
        Write-ColorOutput "`nMissing Files:" $ColorYellow
        foreach ($file in $missingFiles) {
            Write-ColorOutput "  ✗ $file" $ColorYellow
        }
    }
}

# Show next steps
function Show-NextSteps {
    Write-ColorOutput "`nNext Steps:" $ColorCyan
    Write-ColorOutput "1. Review comprehensive report:" $ColorWhite
    Write-ColorOutput "   Get-Content `"$ResultsDir/PHASE6_ANALYSIS_REPORT.md`"" $ColorYellow
    Write-ColorOutput ""
    Write-ColorOutput "2. Review top 5 parameter sets:" $ColorWhite
    Write-ColorOutput "   Get-Content `"$ResultsDir/phase6_top_5_parameters.json`" | ConvertFrom-Json" $ColorYellow
    Write-ColorOutput ""
    Write-ColorOutput "3. Run validation:" $ColorWhite
    Write-ColorOutput "   python optimization/scripts/validate_phase6_results.py --verbose" $ColorYellow
    Write-ColorOutput ""
    Write-ColorOutput "4. Phase 7 preparation:" $ColorWhite
    Write-ColorOutput "   Top 5 parameter sets are ready for Phase 7 walk-forward validation" $ColorGreen
}

# Main execution
try {
    Write-ColorOutput "Phase 6 Analysis Orchestration Script" $ColorCyan
    Write-ColorOutput "=====================================" $ColorCyan
    Write-ColorOutput "Results Directory: $ResultsDir" $ColorWhite
    Write-ColorOutput "Verbose Mode: $Verbose" $ColorWhite
    Write-ColorOutput "Continue On Error: $ContinueOnError" $ColorWhite
    Write-ColorOutput ""
    
    $startTime = Get-Date
    
    # Validate prerequisites
    if (-not (Validate-Prerequisites)) {
        exit 1
    }
    
    # Execute sensitivity analysis
    $sensitivityExitCode = Invoke-SensitivityAnalysis
    if ($sensitivityExitCode -ne 0 -and -not $ContinueOnError) {
        Write-ColorOutput "Sensitivity analysis failed. Use -ContinueOnError to proceed anyway." $ColorRed
        exit 2
    }
    
    # Execute Pareto top 5 selection
    $paretoExitCode = Invoke-ParetoTop5Selection
    if ($paretoExitCode -ne 0 -and -not $ContinueOnError) {
        Write-ColorOutput "Pareto selection failed. Use -ContinueOnError to proceed anyway." $ColorRed
        exit 3
    }
    
    # Execute comprehensive report generation
    $reportExitCode = Invoke-ComprehensiveReport
    if ($reportExitCode -ne 0) {
        Write-ColorOutput "Comprehensive report generation failed. This is critical for Phase 7." $ColorRed
        exit 4
    }
    
    $endTime = Get-Date
    $duration = $endTime - $startTime
    
    Show-AnalysisSummary
    Show-NextSteps
    
    Write-ColorOutput "`nTotal execution time: $($duration.TotalMinutes.ToString('F2')) minutes" $ColorCyan
    Write-ColorOutput "Phase 6 analysis completed successfully!" $ColorGreen
    
    exit 0
}
catch {
    Write-ColorOutput "`nUnexpected error: $($_.Exception.Message)" $ColorRed
    Write-ColorOutput "Please check the error details and try again." $ColorYellow
    exit 1
}
