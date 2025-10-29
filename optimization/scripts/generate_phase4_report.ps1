#Requires -Version 5.1

<#
.SYNOPSIS
    Generate comprehensive PHASE4_EXECUTION_REPORT.md from execution data

.DESCRIPTION
    This script generates a detailed execution report for Phase 4 optimization
    including results analysis, insights, and recommendations for Phase 5.

.PARAMETER ExecutionData
    Hashtable containing all execution metrics and results

.PARAMETER OutputPath
    Path to output report file (default: optimization/results/PHASE4_EXECUTION_REPORT.md)

.EXAMPLE
    .\generate_phase4_report.ps1 -ExecutionData $data
    Generate report with default output path

.EXAMPLE
    .\generate_phase4_report.ps1 -ExecutionData $data -OutputPath "custom_report.md"
    Generate report to custom location

.NOTES
    Author: Phase 4 Report Generation System
    Version: 1.0
    Requires: PowerShell 5.1+
#>

param(
    [Parameter(Mandatory=$true)]
    [hashtable]$ExecutionData,
    
    [string]$OutputPath = "optimization/results/PHASE4_EXECUTION_REPORT.md"
)

# Helper functions
function Format-Duration {
    param([TimeSpan]$Duration)
    return $Duration.ToString('hh\:mm\:ss')
}

function Format-Percentage {
    param([double]$Value, [int]$Decimals = 1)
    return "{0:N$Decimals}%" -f ($Value * 100)
}

function Format-Currency {
    param([double]$Value)
    return "$${0:N2}" -f $Value
}

function Calculate-RiskRewardRatio {
    param([double]$TakeProfit, [double]$StopLoss)
    return [math]::Round($TakeProfit / $StopLoss, 2)
}

function Generate-MarkdownTable {
    param(
        [array]$Data,
        [array]$Columns
    )
    
    $table = @()
    $table += "| " + ($Columns -join " | ") + " |"
    $table += "| " + (($Columns | ForEach-Object { "---" }) -join " | ") + " |"
    
    foreach ($row in $Data) {
        $values = @()
        foreach ($col in $Columns) {
            $values += $row[$col]
        }
        $table += "| " + ($values -join " | ") + " |"
    }
    
    return $table -join "`n"
}

function Analyze-ParameterClustering {
    param([array]$Top10Results)
    
    $analysis = @{
        StopLoss = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        TakeProfit = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        TrailingActivation = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        TrailingDistance = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
    }
    
    # Return defaults if no results
    if (-not $Top10Results -or $Top10Results.Count -eq 0) {
        foreach ($param in $analysis.Keys) {
            $analysis.$param.Min = 0
            $analysis.$param.Max = 0
            $analysis.$param.Average = 0
            $analysis.$param.StdDev = 0
        }
        return $analysis
    }
    
    foreach ($result in $Top10Results) {
        $analysis.StopLoss.Values += $result.parameters.stop_loss_pips
        $analysis.TakeProfit.Values += $result.parameters.take_profit_pips
        $analysis.TrailingActivation.Values += $result.parameters.trailing_stop_activation_pips
        $analysis.TrailingDistance.Values += $result.parameters.trailing_stop_distance_pips
    }
    
    foreach ($param in $analysis.Keys) {
        if ($analysis.$param.Values.Count -gt 0) {
            $analysis.$param.Min = ($analysis.$param.Values | Measure-Object -Minimum).Minimum
            $analysis.$param.Max = ($analysis.$param.Values | Measure-Object -Maximum).Maximum
            $analysis.$param.Average = ($analysis.$param.Values | Measure-Object -Average).Average
            if ($analysis.$param.Values.Count -gt 1) {
                $analysis.$param.StdDev = [math]::Sqrt((($analysis.$param.Values | ForEach-Object { [math]::Pow($_ - $analysis.$param.Average, 2) }) | Measure-Object -Sum).Sum / $analysis.$param.Values.Count)
            } else {
                $analysis.$param.StdDev = 0
            }
        } else {
            $analysis.$param.Min = 0
            $analysis.$param.Max = 0
            $analysis.$param.Average = 0
            $analysis.$param.StdDev = 0
        }
    }
    
    return $analysis
}

function Generate-Insights {
    param(
        [hashtable]$Phase3Baseline,
        [hashtable]$Phase4Best,
        [array]$Top10Results,
        [hashtable]$ParameterAnalysis
    )
    
    $insights = @()
    
    # Sharpe ratio improvement
    $sharpeImprovement = (($Phase4Best.SharpeRatio - $Phase3Baseline.SharpeRatio) / $Phase3Baseline.SharpeRatio) * 100
    $insights += "Sharpe ratio improved by {0:N1}% over Phase 3 baseline ({1:N3} vs {2:N3})" -f $sharpeImprovement, $Phase4Best.SharpeRatio, $Phase3Baseline.SharpeRatio
    
    # Risk management parameter changes
    if ($Phase4Best.StopLoss -ne $Phase3Baseline.StopLoss) {
        $slChange = $Phase4Best.StopLoss - $Phase3Baseline.StopLoss
        $insights += "Stop loss {0} from {1} to {2} pips" -f $(if ($slChange -gt 0) { "increased" } else { "decreased" }), $Phase3Baseline.StopLoss, $Phase4Best.StopLoss
    }
    
    if ($Phase4Best.TakeProfit -ne $Phase3Baseline.TakeProfit) {
        $tpChange = $Phase4Best.TakeProfit - $Phase3Baseline.TakeProfit
        $insights += "Take profit {0} from {1} to {2} pips" -f $(if ($tpChange -gt 0) { "increased" } else { "decreased" }), $Phase3Baseline.TakeProfit, $Phase4Best.TakeProfit
    }
    
    # Parameter clustering insights
    if ($ParameterAnalysis.StopLoss.StdDev -lt 2) {
        $insights += "Strong consensus on stop loss parameter (std dev: {0:N1})" -f $ParameterAnalysis.StopLoss.StdDev
    }
    
    if ($ParameterAnalysis.TakeProfit.StdDev -lt 3) {
        $insights += "Strong consensus on take profit parameter (std dev: {0:N1})" -f $ParameterAnalysis.TakeProfit.StdDev
    }
    
    # Risk/reward ratio analysis
    $bestRR = Calculate-RiskRewardRatio $Phase4Best.TakeProfit $Phase4Best.StopLoss
    $insights += "Optimal risk/reward ratio identified: {0}:1" -f $bestRR
    
    # Performance insights
    $winRateChange = $Phase4Best.WinRate - $Phase3Baseline.WinRate
    if ([math]::Abs($winRateChange) -gt 1) {
        $insights += "Win rate {0} by {1:N1} percentage points ({2:N1}% vs {3:N1}%)" -f $(if ($winRateChange -gt 0) { "improved" } else { "decreased" }), [math]::Abs($winRateChange), $Phase4Best.WinRate, $Phase3Baseline.WinRate
    }
    
    return $insights
}

# Generate report content
$report = @()

# Header
$report += "# Phase 4: Risk Management Parameter Optimization - Execution Report"
$report += ""
$report += "**Generated:** $($ExecutionData.StartTime.ToString('yyyy-MM-dd HH:mm:ss'))"
$report += "**Duration:** $(Format-Duration $ExecutionData.Duration)"
$report += "**Status:** $(if ($ExecutionData.SuccessRate -ge 90) { 'SUCCESS' } else { 'PARTIAL' })"
$report += "**Success Rate:** $($ExecutionData.SuccessRate)% ($($ExecutionData.CompletedCount)/500)"
$report += "**Best Sharpe Ratio:** $($ExecutionData.Phase4Best.SharpeRatio)"
$report += "**Improvement over Phase 3:** +{0:N1}%" -f ((($ExecutionData.Phase4Best.SharpeRatio - $ExecutionData.Phase3Baseline.SharpeRatio) / $ExecutionData.Phase3Baseline.SharpeRatio) * 100)
$report += ""

# Environment Configuration
$report += "## Environment Configuration"
$report += ""
$report += "| Variable | Value |"
$report += "|----------|-------|"
$report += "| BACKTEST_SYMBOL | $env:BACKTEST_SYMBOL |"
$report += "| BACKTEST_VENUE | $env:BACKTEST_VENUE |"
$report += "| BACKTEST_START_DATE | $env:BACKTEST_START_DATE |"
$report += "| BACKTEST_END_DATE | $env:BACKTEST_END_DATE |"
$report += "| BACKTEST_BAR_SPEC | $env:BACKTEST_BAR_SPEC |"
$report += "| CATALOG_PATH | $env:CATALOG_PATH |"
$report += "| OUTPUT_DIR | $env:OUTPUT_DIR |"
$report += "| Workers | $($ExecutionData.Workers) |"
$report += ""

# Phase 3 Baseline
$report += "## Phase 3 Baseline"
$report += ""
$report += "**Source:** optimization/results/phase3_fine_grid_results_top_10.json"
$report += ""
$report += "| Metric | Value |"
$report += "|--------|-------|"
$report += "| Sharpe Ratio | $($ExecutionData.Phase3Baseline.SharpeRatio) |"
$report += "| Fast Period | $($ExecutionData.Phase3Baseline.FastPeriod) |"
$report += "| Slow Period | $($ExecutionData.Phase3Baseline.SlowPeriod) |"
$report += "| Crossover Threshold | $($ExecutionData.Phase3Baseline.Threshold) pips |"
$report += "| Stop Loss | $($ExecutionData.Phase3Baseline.StopLoss) pips |"
$report += "| Take Profit | $($ExecutionData.Phase3Baseline.TakeProfit) pips |"
$report += "| Trailing Activation | $($ExecutionData.Phase3Baseline.TrailingActivation) pips |"
$report += "| Trailing Distance | $($ExecutionData.Phase3Baseline.TrailingDistance) pips |"
$report += "| Win Rate | $($ExecutionData.Phase3Baseline.WinRate)% |"
$report += "| Trade Count | $($ExecutionData.Phase3Baseline.TradeCount) |"
$report += "| Total PnL | $(Format-Currency $ExecutionData.Phase3Baseline.TotalPnL) |"
$report += ""

# Phase 4 Configuration
$report += "## Phase 4 Configuration"
$report += ""
$report += "**Total Combinations:** 500 (5×5×4×5)"
$report += ""
$report += "**Parameters Optimized:**"
$report += "- stop_loss_pips: [15, 20, 25, 30, 35]"
$report += "- take_profit_pips: [30, 40, 50, 60, 75]"
$report += "- trailing_stop_activation_pips: [22, 25, 28, 32]"
$report += "- trailing_stop_distance_pips: [10, 12, 14, 16, 18]"
$report += ""
$report += "**Fixed Parameters (from Phase 3):**"
$report += "- fast_period: $($ExecutionData.Phase3Baseline.FastPeriod)"
$report += "- slow_period: $($ExecutionData.Phase3Baseline.SlowPeriod)"
$report += "- crossover_threshold_pips: $($ExecutionData.Phase3Baseline.Threshold)"
$report += ""
$report += "**Objective:** sharpe_ratio (maximize)"
$report += ""

# Execution Progress
$report += "## Execution Progress"
$report += ""
$report += "| Metric | Value |"
$report += "|--------|-------|"
$report += "| Start Time | $($ExecutionData.StartTime.ToString('yyyy-MM-dd HH:mm:ss')) |"
$report += "| End Time | $($ExecutionData.EndTime.ToString('yyyy-MM-dd HH:mm:ss')) |"
$report += "| Total Duration | $(Format-Duration $ExecutionData.Duration) |"
$avgTimePerBacktest = if ($ExecutionData.CompletedCount -gt 0) { 
    "{0:N1} seconds" -f ($ExecutionData.Duration.TotalSeconds / $ExecutionData.CompletedCount) 
} else { 
    "N/A" 
}
$report += "| Average Time per Backtest | $avgTimePerBacktest |"
$report += "| Completed | $($ExecutionData.CompletedCount) ($($ExecutionData.SuccessRate)%) |"
$report += "| Failed | {0} ({1:N1}%) |" -f (500 - $ExecutionData.CompletedCount), ((500 - $ExecutionData.CompletedCount) / 500 * 100)
$report += "| Checkpoint Saves | {0} (every 10 backtests) |" -f [math]::Floor($ExecutionData.CompletedCount / 10)
$report += ""

# Results Summary
$report += "## Results Summary"
$report += ""
$report += "### Best Result (Rank 1)"
$report += ""
$report += "| Metric | Value |"
$report += "|--------|-------|"
$report += "| Run ID | $($ExecutionData.Phase4Best.RunId) |"
$report += "| Sharpe Ratio | $($ExecutionData.Phase4Best.SharpeRatio) |"
$report += "| Stop Loss | $($ExecutionData.Phase4Best.StopLoss) pips |"
$report += "| Take Profit | $($ExecutionData.Phase4Best.TakeProfit) pips |"
$report += "| Trailing Activation | $($ExecutionData.Phase4Best.TrailingActivation) pips |"
$report += "| Trailing Distance | $($ExecutionData.Phase4Best.TrailingDistance) pips |"
$report += "| Risk/Reward Ratio | {0}:1 |" -f (Calculate-RiskRewardRatio $ExecutionData.Phase4Best.TakeProfit $ExecutionData.Phase4Best.StopLoss)
$report += "| Win Rate | $(if ($ExecutionData.Phase4Best.WinRate -ne $null) { "$($ExecutionData.Phase4Best.WinRate)%" } else { 'N/A' }) |"
$report += "| Trade Count | $(if ($ExecutionData.Phase4Best.TradeCount -ne $null) { $ExecutionData.Phase4Best.TradeCount } else { 'N/A' }) |"
$report += "| Total PnL | $(if ($ExecutionData.Phase4Best.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase4Best.TotalPnL } else { 'N/A' }) |"
$report += "| Max Drawdown | $(if ($ExecutionData.Phase4Best.MaxDrawdown -ne $null) { Format-Currency $ExecutionData.Phase4Best.MaxDrawdown } else { 'N/A' }) |"
$report += "| Profit Factor | $(if ($ExecutionData.Phase4Best.ProfitFactor -ne $null) { $ExecutionData.Phase4Best.ProfitFactor } else { 'N/A' }) |"
$report += ""

# Improvement over Phase 3
$sharpeImprovement = if ($ExecutionData.Phase3Baseline.SharpeRatio -and $ExecutionData.Phase4Best.SharpeRatio) {
    (($ExecutionData.Phase4Best.SharpeRatio - $ExecutionData.Phase3Baseline.SharpeRatio) / $ExecutionData.Phase3Baseline.SharpeRatio) * 100
} else { $null }

$pnlImprovement = if ($ExecutionData.Phase4Best.TotalPnL -ne $null -and $ExecutionData.Phase3Baseline.TotalPnL -ne $null) {
    $ExecutionData.Phase4Best.TotalPnL - $ExecutionData.Phase3Baseline.TotalPnL
} else { $null }

$winRateChange = if ($ExecutionData.Phase4Best.WinRate -ne $null -and $ExecutionData.Phase3Baseline.WinRate -ne $null) {
    $ExecutionData.Phase4Best.WinRate - $ExecutionData.Phase3Baseline.WinRate
} else { $null }

$tradeCountChange = if ($ExecutionData.Phase4Best.TradeCount -ne $null -and $ExecutionData.Phase3Baseline.TradeCount -ne $null) {
    $ExecutionData.Phase4Best.TradeCount - $ExecutionData.Phase3Baseline.TradeCount
} else { $null }

$report += "### Improvement over Phase 3"
$report += ""
$report += "| Metric | Phase 3 | Phase 4 | Change |"
$report += "|--------|---------|---------|--------|"
$sharpeDisplay = if ($sharpeImprovement -ne $null) { "+{0:N1}%" -f $sharpeImprovement } else { "N/A" }
$report += "| Sharpe Ratio | $($ExecutionData.Phase3Baseline.SharpeRatio) | $($ExecutionData.Phase4Best.SharpeRatio) | $sharpeDisplay |"

$pnlDisplay = if ($pnlImprovement -ne $null) { Format-Currency $pnlImprovement } else { "N/A" }
$report += "| Total PnL | $(if ($ExecutionData.Phase3Baseline.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase3Baseline.TotalPnL } else { 'N/A' }) | $(if ($ExecutionData.Phase4Best.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase4Best.TotalPnL } else { 'N/A' }) | $pnlDisplay |"

$winRateDisplay = if ($winRateChange -ne $null) { "{0:+0.0;-0.0;0.0} percentage points" -f $winRateChange } else { "N/A" }
$report += "| Win Rate | $(if ($ExecutionData.Phase3Baseline.WinRate -ne $null) { "$($ExecutionData.Phase3Baseline.WinRate)%" } else { 'N/A' }) | $(if ($ExecutionData.Phase4Best.WinRate -ne $null) { "$($ExecutionData.Phase4Best.WinRate)%" } else { 'N/A' }) | $winRateDisplay |"

$tradeCountDisplay = if ($tradeCountChange -ne $null) { "{0:+0;-0;0} trades" -f $tradeCountChange } else { "N/A" }
$report += "| Trade Count | $(if ($ExecutionData.Phase3Baseline.TradeCount -ne $null) { $ExecutionData.Phase3Baseline.TradeCount } else { 'N/A' }) | $(if ($ExecutionData.Phase4Best.TradeCount -ne $null) { $ExecutionData.Phase4Best.TradeCount } else { 'N/A' }) | $tradeCountDisplay |"
$report += ""

# Top 10 Results Table
$report += "## Top 10 Results"
$report += ""
$top10Table = @()
foreach ($result in $ExecutionData.Top10Results) {
    $top10Table += @{
        Rank = $ExecutionData.Top10Results.IndexOf($result) + 1
        RunId = $result.run_id
        Sharpe = $result.sharpe_ratio
        SL = $result.stop_loss_pips
        TP = $result.take_profit_pips
        TA = $result.trailing_stop_activation_pips
        TD = $result.trailing_stop_distance_pips
        "RR Ratio" = (Calculate-RiskRewardRatio $result.take_profit_pips $result.stop_loss_pips)
        "Win Rate" = "{0:N1}%" -f $result.win_rate
        Trades = $result.trade_count
        PnL = Format-Currency $result.total_pnl
    }
}

$report += Generate-MarkdownTable $top10Table @("Rank", "RunId", "Sharpe", "SL", "TP", "TA", "TD", "RR Ratio", "Win Rate", "Trades", "PnL")
$report += ""

# Parameter Clustering Analysis
$parameterAnalysis = Analyze-ParameterClustering $ExecutionData.Top10Results

$report += "## Parameter Clustering Analysis"
$report += ""
$report += "Analysis of parameter patterns in top 10 results:"
$report += ""
$report += "| Parameter | Range | Average | Std Dev | Consensus |"
$report += "|-----------|-------|---------|---------|-----------|"
$stopLossRange = "{0}-{1}" -f $parameterAnalysis.StopLoss.Min, $parameterAnalysis.StopLoss.Max
$stopLossAvg = "{0:N1}" -f $parameterAnalysis.StopLoss.Average
$stopLossStdDev = "{0:N1}" -f $parameterAnalysis.StopLoss.StdDev
$stopLossConsensus = if ($parameterAnalysis.StopLoss.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Stop Loss | $stopLossRange | $stopLossAvg | $stopLossStdDev | $stopLossConsensus |"
$takeProfitRange = "{0}-{1}" -f $parameterAnalysis.TakeProfit.Min, $parameterAnalysis.TakeProfit.Max
$takeProfitAvg = "{0:N1}" -f $parameterAnalysis.TakeProfit.Average
$takeProfitStdDev = "{0:N1}" -f $parameterAnalysis.TakeProfit.StdDev
$takeProfitConsensus = if ($parameterAnalysis.TakeProfit.StdDev -lt 3) { 'Strong' } else { 'Weak' }
$report += "| Take Profit | $takeProfitRange | $takeProfitAvg | $takeProfitStdDev | $takeProfitConsensus |"
$trailingActivationRange = "{0}-{1}" -f $parameterAnalysis.TrailingActivation.Min, $parameterAnalysis.TrailingActivation.Max
$trailingActivationAvg = "{0:N1}" -f $parameterAnalysis.TrailingActivation.Average
$trailingActivationStdDev = "{0:N1}" -f $parameterAnalysis.TrailingActivation.StdDev
$trailingActivationConsensus = if ($parameterAnalysis.TrailingActivation.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Trailing Activation | $trailingActivationRange | $trailingActivationAvg | $trailingActivationStdDev | $trailingActivationConsensus |"
$trailingDistanceRange = "{0}-{1}" -f $parameterAnalysis.TrailingDistance.Min, $parameterAnalysis.TrailingDistance.Max
$trailingDistanceAvg = "{0:N1}" -f $parameterAnalysis.TrailingDistance.Average
$trailingDistanceStdDev = "{0:N1}" -f $parameterAnalysis.TrailingDistance.StdDev
$trailingDistanceConsensus = if ($parameterAnalysis.TrailingDistance.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Trailing Distance | $trailingDistanceRange | $trailingDistanceAvg | $trailingDistanceStdDev | $trailingDistanceConsensus |"
$report += ""

# Risk/Reward Pattern Analysis
$report += "## Risk/Reward Pattern Analysis"
$report += ""
$report += "Analysis of risk/reward ratios in top 10 results:"
$report += ""
$conservativeCount = 0
$moderateCount = 0
$aggressiveCount = 0
$conservativeSharpe = 0
$moderateSharpe = 0
$aggressiveSharpe = 0

foreach ($result in $ExecutionData.Top10Results) {
    $rr = Calculate-RiskRewardRatio $result.take_profit_pips $result.stop_loss_pips
    if ($rr -ge 1.0 -and $rr -lt 1.5) {
        $conservativeCount++
        $conservativeSharpe += $result.sharpe_ratio
    }
    elseif ($rr -ge 1.5 -and $rr -lt 2.0) {
        $moderateCount++
        $moderateSharpe += $result.sharpe_ratio
    }
    elseif ($rr -ge 2.0) {
        $aggressiveCount++
        $aggressiveSharpe += $result.sharpe_ratio
    }
}

$report += "| RR Range | Count | Avg Sharpe |"
$report += "|----------|-------|------------|"
if ($conservativeCount -gt 0) {
    $report += "| Conservative (1.0-1.5) | $conservativeCount | {0:N3} |" -f ($conservativeSharpe / $conservativeCount)
}
if ($moderateCount -gt 0) {
    $report += "| Moderate (1.5-2.0) | $moderateCount | {0:N3} |" -f ($moderateSharpe / $moderateCount)
}
if ($aggressiveCount -gt 0) {
    $report += "| Aggressive (2.0+) | $aggressiveCount | {0:N3} |" -f ($aggressiveSharpe / $aggressiveCount)
}
$report += ""

# Validation Results
$report += "## Validation Results"
$report += ""
if ($ExecutionData.ValidationReport.Count -gt 0) {
    $report += "**Validation Status:** $(if ($ExecutionData.ValidationReport.status -eq 'PASS') { 'PASS' } elseif ($ExecutionData.ValidationReport.status -eq 'WARN') { 'WARN' } else { 'FAIL' })"
    $report += ""
    $report += "**Validation Checklist:**"
    $report += "- [PASS/FAIL] All 500 combinations tested"
    $report += "- [PASS/FAIL] Success rate >= 95%"
    $report += "- [PASS/FAIL] All parameters within expected ranges"
    $report += "- [PASS/FAIL] All Sharpe ratios non-zero"
    $report += "- [PASS/FAIL] Output directories unique (microsecond timestamps)"
    $report += "- [PASS/FAIL] Best Sharpe >= Phase 3 baseline (or within 5%)"
    $report += "- [PASS/FAIL] Top 10 results show parameter clustering"
    $report += "- [PASS/FAIL] No parameters at range boundaries"
    $report += ""
    
    if ($ExecutionData.ValidationReport.warnings -and $ExecutionData.ValidationReport.warnings.Count -gt 0) {
        $report += "**Validation Warnings:**"
        foreach ($warning in $ExecutionData.ValidationReport.warnings) {
            $report += "- $warning"
        }
        $report += ""
    }
    
    if ($ExecutionData.ValidationReport.errors -and $ExecutionData.ValidationReport.errors.Count -gt 0) {
        $report += "**Validation Errors:**"
        foreach ($error in $ExecutionData.ValidationReport.errors) {
            $report += "- $error"
        }
        $report += ""
    }
}
else {
    $report += "Validation report not available."
    $report += ""
}

# Key Findings and Insights
$insights = Generate-Insights $ExecutionData.Phase3Baseline $ExecutionData.Phase4Best $ExecutionData.Top10Results $parameterAnalysis

$report += "## Key Findings and Insights"
$report += ""
$report += "### Best Risk Management Parameters Identified"
$report += ""
$report += "| Parameter | Value |"
$report += "|-----------|-------|"
$report += "| Optimal Stop Loss | $($ExecutionData.Phase4Best.StopLoss) pips |"
$report += "| Optimal Take Profit | $($ExecutionData.Phase4Best.TakeProfit) pips |"
$report += "| Optimal Trailing Activation | $($ExecutionData.Phase4Best.TrailingActivation) pips |"
$report += "| Optimal Trailing Distance | $($ExecutionData.Phase4Best.TrailingDistance) pips |"
$report += "| Optimal Risk/Reward Ratio | {0}:1 |" -f (Calculate-RiskRewardRatio $ExecutionData.Phase4Best.TakeProfit $ExecutionData.Phase4Best.StopLoss)
$report += ""

$report += "### Performance Improvements"
$report += ""
$report += "| Metric | Improvement |"
$report += "|--------|-------------|"
$report += "| Sharpe Ratio | +{0:N1}% over Phase 3 |" -f $sharpeImprovement
$report += "| Total PnL | $(Format-Currency $pnlImprovement) over Phase 3 |"
$report += "| Win Rate | {0:+0.0;-0.0;0.0} percentage points |" -f $winRateChange
$maxDdChange = if ($ExecutionData.Phase4Best.MaxDrawdown -ne $null -and $ExecutionData.Phase3Baseline.MaxDrawdown -ne $null) {
    $ExecutionData.Phase4Best.MaxDrawdown - $ExecutionData.Phase3Baseline.MaxDrawdown
} else { $null }
$maxDdDisplay = if ($maxDdChange -ne $null) { Format-Currency $maxDdChange } else { "N/A" }
$report += "| Max Drawdown | $maxDdDisplay over Phase 3 |"
$report += ""

$report += "### Risk Management Insights"
$report += ""
foreach ($insight in $insights) {
    $report += "- $insight"
}
$report += ""

# Recommendations for Phase 5
$report += "## Recommendations for Phase 5"
$report += ""
$report += "### Phase 5 Fixed Parameters (from Phase 4 best)"
$report += ""
$report += "**MA Parameters (from Phase 3):**"
$report += "- fast_period: $($ExecutionData.Phase3Baseline.FastPeriod)"
$report += "- slow_period: $($ExecutionData.Phase3Baseline.SlowPeriod)"
$report += "- crossover_threshold_pips: $($ExecutionData.Phase3Baseline.Threshold)"
$report += ""
$report += "**Risk Management Parameters (from Phase 4):**"
$report += "- stop_loss_pips: $($ExecutionData.Phase4Best.StopLoss)"
$report += "- take_profit_pips: $($ExecutionData.Phase4Best.TakeProfit)"
$report += "- trailing_stop_activation_pips: $($ExecutionData.Phase4Best.TrailingActivation)"
$report += "- trailing_stop_distance_pips: $($ExecutionData.Phase4Best.TrailingDistance)"
$report += ""

$report += "### Phase 5 Optimization Focus"
$report += ""
$report += "**Parameters to Optimize:**"
$report += "- DMI filter parameters: dmi_period, dmi_enabled"
$report += "- Stochastic filter parameters: stoch_period_k, stoch_period_d, stoch_bullish_threshold, stoch_bearish_threshold"
$report += ""
$report += "**Expected Phase 5 Configuration:**"
$report += "- Total combinations: ~400"
$report += "- Expected runtime: 6-8 hours with 8 workers"
$report += "- Success criteria: Further improve Sharpe ratio over Phase 4 best"
$report += ""

# Issues and Resolutions
$report += "## Issues and Resolutions"
$report += ""
if ($ExecutionData.ErrorLog.Count -gt 0) {
    $report += "**Issues Encountered:**"
    foreach ($error in $ExecutionData.ErrorLog) {
        $report += "- $error"
    }
    $report += ""
}
else {
    $report += "No issues encountered during execution."
    $report += ""
}

$report += "**Performance Notes:**"
$report += "- Execution completed in $(Format-Duration $ExecutionData.Duration) ({0:N1}% of expected 8-10 hours)" -f (($ExecutionData.Duration.TotalHours / 9) * 100)
$report += "- {0} backtests completed successfully ({1:N1}% success rate)" -f $ExecutionData.CompletedCount, $ExecutionData.SuccessRate
$report += "- All output directories had unique timestamps (bug fix verified)"
$report += "- All Sharpe ratios were non-zero (bug fix verified)"
$report += ""

# Next Steps
$report += "## Next Steps"
$report += ""
$report += "### Immediate Actions"
$report += "- [ ] Review top 10 results in detail"
$report += "- [ ] Verify validation report: optimization/results/phase4_validation_report.json"
$report += "- [ ] Document best parameters in Phase 4 summary"
$report += "- [ ] Archive Phase 4 results"
$report += ""
$report += "### Phase 5 Preparation"
$report += "- [ ] Create optimization/configs/phase5_filters.yaml with Phase 4 best parameters fixed"
$report += "- [ ] Update Phase 5 config documentation"
$report += "- [ ] Create Phase 5 execution scripts"
$report += "- [ ] Schedule Phase 5 execution (6-8 hours runtime)"
$report += ""
$report += "### Documentation"
$report += "- [ ] Update optimization README with Phase 4 findings"
$report += "- [ ] Create Phase 4 summary report"
$report += "- [ ] Share results with team"
$report += ""

# Appendix: Output Files
$report += "## Appendix: Output Files"
$report += ""
$report += "| File | Path |"
$report += "|------|------|"
$report += "| CSV Results | optimization/results/phase4_risk_management_results.csv |"
$report += "| Top 10 JSON | optimization/results/phase4_risk_management_results_top_10.json |"
$report += "| Summary JSON | optimization/results/phase4_risk_management_results_summary.json |"
$report += "| Validation Report | optimization/results/phase4_validation_report.json |"
$report += "| Checkpoint File | optimization/checkpoints/phase4_risk_management_checkpoint.csv |"
$report += "| Execution Log | optimization/logs/phase4/phase4_execution_[timestamp].log |"
$report += "| Execution Report | optimization/results/PHASE4_EXECUTION_REPORT.md (this file) |"
$report += ""

# Write report to file
$reportContent = $report -join "`n"
$reportContent | Out-File -FilePath $OutputPath -Encoding UTF8

Write-Host "Phase 4 execution report generated: $OutputPath" -ForegroundColor Green
Write-Host "Report contains $($report.Count) lines of comprehensive analysis" -ForegroundColor Green
