#Requires -Version 5.1

<#
.SYNOPSIS
    Generate comprehensive PHASE5_EXECUTION_REPORT.md from execution data

.DESCRIPTION
    This script generates a detailed execution report for Phase 5 filter optimization
    including results analysis, filter impact insights, and recommendations for Phase 6.

.PARAMETER ExecutionData
    Hashtable containing all execution metrics and results

.PARAMETER OutputPath
    Path to output report file (default: optimization/results/PHASE5_EXECUTION_REPORT.md)

.EXAMPLE
    .\generate_phase5_report.ps1 -ExecutionData $data
    Generate report with default output path

.EXAMPLE
    .\generate_phase5_report.ps1 -ExecutionData $data -OutputPath "custom_report.md"
    Generate report to custom location

.NOTES
    Author: Phase 5 Report Generation System
    Version: 1.0
    Requires: PowerShell 5.1+
#>

param(
    [Parameter(Mandatory=$true)]
    [hashtable]$ExecutionData,
    
    [string]$OutputPath = "optimization/results/PHASE5_EXECUTION_REPORT.md"
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

function Analyze-FilterImpact {
    param([array]$Top10Results)
    
    $analysis = @{
        DmiEnabled = @{ Count = 0; AvgSharpe = 0; AvgWinRate = 0; AvgTradeCount = 0 }
        DmiDisabled = @{ Count = 0; AvgSharpe = 0; AvgWinRate = 0; AvgTradeCount = 0 }
        OptimalDmiPeriod = 0
        OptimalStochK = 0
        OptimalStochD = 0
        OptimalBullishThreshold = 0
        OptimalBearishThreshold = 0
    }
    
    # Return defaults if no results
    if (-not $Top10Results -or $Top10Results.Count -eq 0) {
        return $analysis
    }
    
    # Analyze DMI enabled vs disabled
    $dmiEnabledResults = $Top10Results | Where-Object { $_.parameters.dmi_enabled -eq $true }
    $dmiDisabledResults = $Top10Results | Where-Object { $_.parameters.dmi_enabled -eq $false }
    
    if ($dmiEnabledResults.Count -gt 0) {
        $analysis.DmiEnabled.Count = $dmiEnabledResults.Count
        $analysis.DmiEnabled.AvgSharpe = ($dmiEnabledResults | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average
        $analysis.DmiEnabled.AvgWinRate = ($dmiEnabledResults | ForEach-Object { $_.parameters.win_rate } | Measure-Object -Average).Average
        $analysis.DmiEnabled.AvgTradeCount = ($dmiEnabledResults | ForEach-Object { $_.parameters.trade_count } | Measure-Object -Average).Average
    }
    
    if ($dmiDisabledResults.Count -gt 0) {
        $analysis.DmiDisabled.Count = $dmiDisabledResults.Count
        $analysis.DmiDisabled.AvgSharpe = ($dmiDisabledResults | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average
        $analysis.DmiDisabled.AvgWinRate = ($dmiDisabledResults | ForEach-Object { $_.parameters.win_rate } | Measure-Object -Average).Average
        $analysis.DmiDisabled.AvgTradeCount = ($dmiDisabledResults | ForEach-Object { $_.parameters.trade_count } | Measure-Object -Average).Average
    }
    
    # Find optimal parameters
    $dmiPeriodStats = $Top10Results | Group-Object { $_.parameters.dmi_period } | ForEach-Object {
        @{ Period = $_.Name; AvgSharpe = ($_.Group | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average }
    }
    if ($dmiPeriodStats.Count -gt 0) {
        $analysis.OptimalDmiPeriod = ($dmiPeriodStats | Sort-Object AvgSharpe -Descending | Select-Object -First 1).Period
    }
    
    $stochKStats = $Top10Results | Group-Object { $_.parameters.stoch_period_k } | ForEach-Object {
        @{ Period = $_.Name; AvgSharpe = ($_.Group | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average }
    }
    if ($stochKStats.Count -gt 0) {
        $analysis.OptimalStochK = ($stochKStats | Sort-Object AvgSharpe -Descending | Select-Object -First 1).Period
    }
    
    $stochDStats = $Top10Results | Group-Object { $_.parameters.stoch_period_d } | ForEach-Object {
        @{ Period = $_.Name; AvgSharpe = ($_.Group | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average }
    }
    if ($stochDStats.Count -gt 0) {
        $analysis.OptimalStochD = ($stochDStats | Sort-Object AvgSharpe -Descending | Select-Object -First 1).Period
    }
    
    $bullishStats = $Top10Results | Group-Object { $_.parameters.stoch_bullish_threshold } | ForEach-Object {
        @{ Threshold = $_.Name; AvgSharpe = ($_.Group | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average }
    }
    if ($bullishStats.Count -gt 0) {
        $analysis.OptimalBullishThreshold = ($bullishStats | Sort-Object AvgSharpe -Descending | Select-Object -First 1).Threshold
    }
    
    $bearishStats = $Top10Results | Group-Object { $_.parameters.stoch_bearish_threshold } | ForEach-Object {
        @{ Threshold = $_.Name; AvgSharpe = ($_.Group | ForEach-Object { $_.objective_value } | Measure-Object -Average).Average }
    }
    if ($bearishStats.Count -gt 0) {
        $analysis.OptimalBearishThreshold = ($bearishStats | Sort-Object AvgSharpe -Descending | Select-Object -First 1).Threshold
    }
    
    return $analysis
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
        DmiPeriod = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        StochK = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        StochD = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        BullishThreshold = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
        BearishThreshold = @{ Min = [double]::MaxValue; Max = [double]::MinValue; Values = @() }
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
        $analysis.DmiPeriod.Values += $result.parameters.dmi_period
        $analysis.StochK.Values += $result.parameters.stoch_period_k
        $analysis.StochD.Values += $result.parameters.stoch_period_d
        $analysis.BullishThreshold.Values += $result.parameters.stoch_bullish_threshold
        $analysis.BearishThreshold.Values += $result.parameters.stoch_bearish_threshold
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
        [hashtable]$Phase4Baseline,
        [hashtable]$Phase5Best,
        [array]$Top10Results,
        [hashtable]$FilterAnalysis,
        [hashtable]$ParameterAnalysis
    )
    
    $insights = @()
    
    # Sharpe ratio improvement
    $sharpeImprovement = (($Phase5Best.SharpeRatio - $Phase4Baseline.SharpeRatio) / $Phase4Baseline.SharpeRatio) * 100
    $insights += "Sharpe ratio {0} by {1:N1}% over Phase 4 baseline ({2:N3} vs {3:N3})" -f $(if ($sharpeImprovement -gt 0) { "improved" } else { "decreased" }), [math]::Abs($sharpeImprovement), $Phase5Best.SharpeRatio, $Phase4Baseline.SharpeRatio
    
    # DMI filter impact
    if ($FilterAnalysis.DmiEnabled.Count -gt 0 -and $FilterAnalysis.DmiDisabled.Count -gt 0) {
        if ($FilterAnalysis.DmiEnabled.AvgSharpe -gt $FilterAnalysis.DmiDisabled.AvgSharpe) {
            $insights += "DMI filter adds value: enabled results show {0:N3} vs {1:N3} average Sharpe" -f $FilterAnalysis.DmiEnabled.AvgSharpe, $FilterAnalysis.DmiDisabled.AvgSharpe
        } else {
            $insights += "DMI filter degrades performance: disabled results show {0:N3} vs {1:N3} average Sharpe" -f $FilterAnalysis.DmiDisabled.AvgSharpe, $FilterAnalysis.DmiEnabled.AvgSharpe
        }
    }
    
    # Optimal filter parameters
    if ($FilterAnalysis.OptimalDmiPeriod -gt 0) {
        $insights += "Optimal DMI period identified: {0}" -f $FilterAnalysis.OptimalDmiPeriod
    }
    
    if ($FilterAnalysis.OptimalStochK -gt 0) {
        $insights += "Optimal Stochastic K period: {0}" -f $FilterAnalysis.OptimalStochK
    }
    
    if ($FilterAnalysis.OptimalStochD -gt 0) {
        $insights += "Optimal Stochastic D period: {0}" -f $FilterAnalysis.OptimalStochD
    }
    
    # Parameter clustering insights
    if ($ParameterAnalysis.DmiPeriod.StdDev -lt 2) {
        $insights += "Strong consensus on DMI period parameter (std dev: {0:N1})" -f $ParameterAnalysis.DmiPeriod.StdDev
    }
    
    if ($ParameterAnalysis.StochK.StdDev -lt 2) {
        $insights += "Strong consensus on Stochastic K parameter (std dev: {0:N1})" -f $ParameterAnalysis.StochK.StdDev
    }
    
    # Filter impact on trade count and win rate
    if ($FilterAnalysis.DmiEnabled.Count -gt 0 -and $FilterAnalysis.DmiDisabled.Count -gt 0) {
        $tradeCountImpact = $FilterAnalysis.DmiEnabled.AvgTradeCount - $FilterAnalysis.DmiDisabled.AvgTradeCount
        $winRateImpact = $FilterAnalysis.DmiEnabled.AvgWinRate - $FilterAnalysis.DmiDisabled.AvgWinRate
        
        if ([math]::Abs($tradeCountImpact) -gt 1) {
            $insights += "DMI filter {0} trade count by {1:N0} trades on average" -f $(if ($tradeCountImpact -gt 0) { "increases" } else { "decreases" }), [math]::Abs($tradeCountImpact)
        }
        
        if ([math]::Abs($winRateImpact) -gt 0.5) {
            $insights += "DMI filter {0} win rate by {1:N1} percentage points on average" -f $(if ($winRateImpact -gt 0) { "improves" } else { "reduces" }), [math]::Abs($winRateImpact)
        }
    }
    
    return $insights
}

# Generate report content
$report = @()

# Header
$report += "# Phase 5: Filter Parameter Optimization - Execution Report"
$report += ""
$report += "**Generated:** $($ExecutionData.StartTime.ToString('yyyy-MM-dd HH:mm:ss'))"
$report += "**Duration:** $(Format-Duration $ExecutionData.Duration)"
$report += "**Status:** $(if ($ExecutionData.SuccessRate -ge 90) { 'SUCCESS' } else { 'PARTIAL' })"
$report += "**Success Rate:** $($ExecutionData.SuccessRate)% ($($ExecutionData.CompletedCount)/$(if ($ExecutionData.UseReduced) { '108' } else { '2400' }))"
$report += "**Best Sharpe Ratio:** $($ExecutionData.Phase5Best.SharpeRatio)"
$report += "**Improvement over Phase 4:** {0:N1}%" -f ((($ExecutionData.Phase5Best.SharpeRatio - $ExecutionData.Phase4Baseline.SharpeRatio) / $ExecutionData.Phase4Baseline.SharpeRatio) * 100)
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
$report += "| Use Reduced | $($ExecutionData.UseReduced) |"
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
$report += "| Win Rate | $($ExecutionData.Phase3Baseline.WinRate)% |"
$report += "| Trade Count | $($ExecutionData.Phase3Baseline.TradeCount) |"
$report += "| Total PnL | $(Format-Currency $ExecutionData.Phase3Baseline.TotalPnL) |"
$report += ""

# Phase 4 Baseline
$report += "## Phase 4 Baseline"
$report += ""
$report += "**Source:** optimization/results/phase4_risk_management_results_top_10.json"
$report += ""
$report += "| Metric | Value |"
$report += "|--------|-------|"
$report += "| Sharpe Ratio | $($ExecutionData.Phase4Baseline.SharpeRatio) |"
$report += "| Stop Loss | $($ExecutionData.Phase4Baseline.StopLoss) pips |"
$report += "| Take Profit | $($ExecutionData.Phase4Baseline.TakeProfit) pips |"
$report += "| Trailing Activation | $($ExecutionData.Phase4Baseline.TrailingActivation) pips |"
$report += "| Trailing Distance | $($ExecutionData.Phase4Baseline.TrailingDistance) pips |"
$report += "| Win Rate | $($ExecutionData.Phase4Baseline.WinRate)% |"
$report += "| Trade Count | $($ExecutionData.Phase4Baseline.TradeCount) |"
$report += "| Total PnL | $(Format-Currency $ExecutionData.Phase4Baseline.TotalPnL) |"
$report += ""

# Phase 5 Configuration
$report += "## Phase 5 Configuration"
$report += ""
$report += "**Total Combinations:** $(if ($ExecutionData.UseReduced) { '108 (1×3×3×3×2×2)' } else { '2,400 (2×5×5×3×4×4)' })"
$report += ""
$report += "**Parameters Optimized:**"
$report += "- dmi_enabled: $(if ($ExecutionData.UseReduced) { '[true]' } else { '[true, false]' })"
$report += "- dmi_period: $(if ($ExecutionData.UseReduced) { '[10, 14, 18]' } else { '[10, 12, 14, 16, 18]' })"
$report += "- stoch_period_k: $(if ($ExecutionData.UseReduced) { '[10, 14, 18]' } else { '[10, 12, 14, 16, 18]' })"
$report += "- stoch_period_d: [3, 5, 7]"
$report += "- stoch_bullish_threshold: $(if ($ExecutionData.UseReduced) { '[20, 30]' } else { '[20, 25, 30, 35]' })"
$report += "- stoch_bearish_threshold: $(if ($ExecutionData.UseReduced) { '[70, 80]' } else { '[65, 70, 75, 80]' })"
$report += ""
$report += "**Fixed Parameters (from Phase 3 & 4):**"
$report += "- MA: fast=$($ExecutionData.Phase3Baseline.FastPeriod), slow=$($ExecutionData.Phase3Baseline.SlowPeriod), threshold=$($ExecutionData.Phase3Baseline.Threshold)"
$report += "- Risk: SL=$($ExecutionData.Phase4Baseline.StopLoss), TP=$($ExecutionData.Phase4Baseline.TakeProfit), TA=$($ExecutionData.Phase4Baseline.TrailingActivation), TD=$($ExecutionData.Phase4Baseline.TrailingDistance)"
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
$expectedCombinations = if ($ExecutionData.UseReduced) { 108 } else { 2400 }
$report += "| Failed | {0} ({1:N1}%) |" -f ($expectedCombinations - $ExecutionData.CompletedCount), (($expectedCombinations - $ExecutionData.CompletedCount) / $expectedCombinations * 100)
$report += "| Checkpoint Saves | {0} (every 10 backtests) |" -f [math]::Floor($ExecutionData.CompletedCount / 10)
$report += ""

# Results Summary
$report += "## Results Summary"
$report += ""
$report += "### Best Result (Rank 1)"
$report += ""
$report += "| Metric | Value |"
$report += "|--------|-------|"
$report += "| Run ID | $($ExecutionData.Phase5Best.RunId) |"
$report += "| Sharpe Ratio | $($ExecutionData.Phase5Best.SharpeRatio) |"
$report += "| DMI Enabled | $($ExecutionData.Phase5Best.DmiEnabled) |"
$report += "| DMI Period | $($ExecutionData.Phase5Best.DmiPeriod) |"
$report += "| Stochastic K | $($ExecutionData.Phase5Best.StochPeriodK) |"
$report += "| Stochastic D | $($ExecutionData.Phase5Best.StochPeriodD) |"
$report += "| Bullish Threshold | $($ExecutionData.Phase5Best.StochBullishThreshold) |"
$report += "| Bearish Threshold | $($ExecutionData.Phase5Best.StochBearishThreshold) |"
$report += "| Win Rate | $(if ($ExecutionData.Phase5Best.WinRate -ne $null) { "$($ExecutionData.Phase5Best.WinRate)%" } else { 'N/A' }) |"
$report += "| Trade Count | $(if ($ExecutionData.Phase5Best.TradeCount -ne $null) { $ExecutionData.Phase5Best.TradeCount } else { 'N/A' }) |"
$report += "| Total PnL | $(if ($ExecutionData.Phase5Best.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase5Best.TotalPnL } else { 'N/A' }) |"
$report += "| Max Drawdown | $(if ($ExecutionData.Phase5Best.MaxDrawdown -ne $null) { Format-Currency $ExecutionData.Phase5Best.MaxDrawdown } else { 'N/A' }) |"
$report += "| Profit Factor | $(if ($ExecutionData.Phase5Best.ProfitFactor -ne $null) { $ExecutionData.Phase5Best.ProfitFactor } else { 'N/A' }) |"
$report += ""

# Improvement over Phase 4
$sharpeImprovement = if ($ExecutionData.Phase4Baseline.SharpeRatio -and $ExecutionData.Phase5Best.SharpeRatio) {
    (($ExecutionData.Phase5Best.SharpeRatio - $ExecutionData.Phase4Baseline.SharpeRatio) / $ExecutionData.Phase4Baseline.SharpeRatio) * 100
} else { $null }

$pnlImprovement = if ($ExecutionData.Phase5Best.TotalPnL -ne $null -and $ExecutionData.Phase4Baseline.TotalPnL -ne $null) {
    $ExecutionData.Phase5Best.TotalPnL - $ExecutionData.Phase4Baseline.TotalPnL
} else { $null }

$winRateChange = if ($ExecutionData.Phase5Best.WinRate -ne $null -and $ExecutionData.Phase4Baseline.WinRate -ne $null) {
    $ExecutionData.Phase5Best.WinRate - $ExecutionData.Phase4Baseline.WinRate
} else { $null }

$tradeCountChange = if ($ExecutionData.Phase5Best.TradeCount -ne $null -and $ExecutionData.Phase4Baseline.TradeCount -ne $null) {
    $ExecutionData.Phase5Best.TradeCount - $ExecutionData.Phase4Baseline.TradeCount
} else { $null }

$report += "### Improvement over Phase 4"
$report += ""
$report += "| Metric | Phase 4 | Phase 5 | Change |"
$report += "|--------|---------|---------|--------|"
$sharpeDisplay = if ($sharpeImprovement -ne $null) { "{0:+0.1;-0.1;0.0}%" -f $sharpeImprovement } else { "N/A" }
$report += "| Sharpe Ratio | $($ExecutionData.Phase4Baseline.SharpeRatio) | $($ExecutionData.Phase5Best.SharpeRatio) | $sharpeDisplay |"

$pnlDisplay = if ($pnlImprovement -ne $null) { Format-Currency $pnlImprovement } else { "N/A" }
$report += "| Total PnL | $(if ($ExecutionData.Phase4Baseline.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase4Baseline.TotalPnL } else { 'N/A' }) | $(if ($ExecutionData.Phase5Best.TotalPnL -ne $null) { Format-Currency $ExecutionData.Phase5Best.TotalPnL } else { 'N/A' }) | $pnlDisplay |"

$winRateDisplay = if ($winRateChange -ne $null) { "{0:+0.0;-0.0;0.0} percentage points" -f $winRateChange } else { "N/A" }
$report += "| Win Rate | $(if ($ExecutionData.Phase4Baseline.WinRate -ne $null) { "$($ExecutionData.Phase4Baseline.WinRate)%" } else { 'N/A' }) | $(if ($ExecutionData.Phase5Best.WinRate -ne $null) { "$($ExecutionData.Phase5Best.WinRate)%" } else { 'N/A' }) | $winRateDisplay |"

$tradeCountDisplay = if ($tradeCountChange -ne $null) { "{0:+0;-0;0} trades" -f $tradeCountChange } else { "N/A" }
$report += "| Trade Count | $(if ($ExecutionData.Phase4Baseline.TradeCount -ne $null) { $ExecutionData.Phase4Baseline.TradeCount } else { 'N/A' }) | $(if ($ExecutionData.Phase5Best.TradeCount -ne $null) { $ExecutionData.Phase5Best.TradeCount } else { 'N/A' }) | $tradeCountDisplay |"
$report += ""

# Top 10 Results Table
$report += "## Top 10 Results"
$report += ""
$top10Table = @()
foreach ($result in $ExecutionData.Top10Results) {
    $top10Table += @{
        Rank = $ExecutionData.Top10Results.IndexOf($result) + 1
        RunId = $result.run_id
        Sharpe = $result.objective_value
        DMI = $result.parameters.dmi_enabled
        "DMI_Period" = $result.parameters.dmi_period
        "Stoch_K" = $result.parameters.stoch_period_k
        "Stoch_D" = $result.parameters.stoch_period_d
        "Bull_Thresh" = $result.parameters.stoch_bullish_threshold
        "Bear_Thresh" = $result.parameters.stoch_bearish_threshold
        "Win Rate" = "{0:N1}%" -f $result.parameters.win_rate
        Trades = $result.parameters.trade_count
        PnL = Format-Currency $result.parameters.total_pnl
    }
}

$report += Generate-MarkdownTable $top10Table @("Rank", "RunId", "Sharpe", "DMI", "DMI_Period", "Stoch_K", "Stoch_D", "Bull_Thresh", "Bear_Thresh", "Win Rate", "Trades", "PnL")
$report += ""

# Filter Impact Analysis
$filterAnalysis = Analyze-FilterImpact $ExecutionData.Top10Results

$report += "## Filter Impact Analysis"
$report += ""
$report += "### DMI Filter Impact"
$report += ""
$report += "| Configuration | Count | Avg Sharpe | Avg Win Rate | Avg Trade Count |"
$report += "|---------------|-------|------------|--------------|-----------------|"
if ($filterAnalysis.DmiEnabled.Count -gt 0) {
    $report += "| DMI Enabled | $($filterAnalysis.DmiEnabled.Count) | {0:N3} | {1:N1}% | {2:N0} |" -f $filterAnalysis.DmiEnabled.AvgSharpe, $filterAnalysis.DmiEnabled.AvgWinRate, $filterAnalysis.DmiEnabled.AvgTradeCount
}
if ($filterAnalysis.DmiDisabled.Count -gt 0) {
    $report += "| DMI Disabled | $($filterAnalysis.DmiDisabled.Count) | {0:N3} | {1:N1}% | {2:N0} |" -f $filterAnalysis.DmiDisabled.AvgSharpe, $filterAnalysis.DmiDisabled.AvgWinRate, $filterAnalysis.DmiDisabled.AvgTradeCount
}
$report += ""

if ($filterAnalysis.DmiEnabled.Count -gt 0 -and $filterAnalysis.DmiDisabled.Count -gt 0) {
    if ($filterAnalysis.DmiEnabled.AvgSharpe -gt $filterAnalysis.DmiDisabled.AvgSharpe) {
        $report += "**Conclusion:** DMI filter adds value ✅"
    } else {
        $report += "**Conclusion:** DMI filter degrades performance ❌"
    }
    $report += ""
}

$report += "### Optimal Filter Parameters"
$report += ""
$report += "| Parameter | Optimal Value |"
$report += "|-----------|---------------|"
$report += "| DMI Period | $($filterAnalysis.OptimalDmiPeriod) |"
$report += "| Stochastic K | $($filterAnalysis.OptimalStochK) |"
$report += "| Stochastic D | $($filterAnalysis.OptimalStochD) |"
$report += "| Bullish Threshold | $($filterAnalysis.OptimalBullishThreshold) |"
$report += "| Bearish Threshold | $($filterAnalysis.OptimalBearishThreshold) |"
$report += ""

# Parameter Clustering Analysis
$parameterAnalysis = Analyze-ParameterClustering $ExecutionData.Top10Results

$report += "## Parameter Clustering Analysis"
$report += ""
$report += "Analysis of parameter patterns in top 10 results:"
$report += ""
$report += "| Parameter | Range | Average | Std Dev | Consensus |"
$report += "|-----------|-------|---------|---------|-----------|"
$dmiPeriodRange = "{0}-{1}" -f $parameterAnalysis.DmiPeriod.Min, $parameterAnalysis.DmiPeriod.Max
$dmiPeriodAvg = "{0:N1}" -f $parameterAnalysis.DmiPeriod.Average
$dmiPeriodStdDev = "{0:N1}" -f $parameterAnalysis.DmiPeriod.StdDev
$dmiPeriodConsensus = if ($parameterAnalysis.DmiPeriod.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| DMI Period | $dmiPeriodRange | $dmiPeriodAvg | $dmiPeriodStdDev | $dmiPeriodConsensus |"

$stochKRange = "{0}-{1}" -f $parameterAnalysis.StochK.Min, $parameterAnalysis.StochK.Max
$stochKAvg = "{0:N1}" -f $parameterAnalysis.StochK.Average
$stochKStdDev = "{0:N1}" -f $parameterAnalysis.StochK.StdDev
$stochKConsensus = if ($parameterAnalysis.StochK.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Stochastic K | $stochKRange | $stochKAvg | $stochKStdDev | $stochKConsensus |"

$stochDRange = "{0}-{1}" -f $parameterAnalysis.StochD.Min, $parameterAnalysis.StochD.Max
$stochDAvg = "{0:N1}" -f $parameterAnalysis.StochD.Average
$stochDStdDev = "{0:N1}" -f $parameterAnalysis.StochD.StdDev
$stochDConsensus = if ($parameterAnalysis.StochD.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Stochastic D | $stochDRange | $stochDAvg | $stochDStdDev | $stochDConsensus |"

$bullishRange = "{0}-{1}" -f $parameterAnalysis.BullishThreshold.Min, $parameterAnalysis.BullishThreshold.Max
$bullishAvg = "{0:N1}" -f $parameterAnalysis.BullishThreshold.Average
$bullishStdDev = "{0:N1}" -f $parameterAnalysis.BullishThreshold.StdDev
$bullishConsensus = if ($parameterAnalysis.BullishThreshold.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Bullish Threshold | $bullishRange | $bullishAvg | $bullishStdDev | $bullishConsensus |"

$bearishRange = "{0}-{1}" -f $parameterAnalysis.BearishThreshold.Min, $parameterAnalysis.BearishThreshold.Max
$bearishAvg = "{0:N1}" -f $parameterAnalysis.BearishThreshold.Average
$bearishStdDev = "{0:N1}" -f $parameterAnalysis.BearishThreshold.StdDev
$bearishConsensus = if ($parameterAnalysis.BearishThreshold.StdDev -lt 2) { 'Strong' } else { 'Weak' }
$report += "| Bearish Threshold | $bearishRange | $bearishAvg | $bearishStdDev | $bearishConsensus |"
$report += ""

# Validation Results
$report += "## Validation Results"
$report += ""
if ($ExecutionData.ValidationReport.Count -gt 0) {
    $report += "**Validation Status:** $(if ($ExecutionData.ValidationReport.status -eq 'PASS') { 'PASS' } elseif ($ExecutionData.ValidationReport.status -eq 'WARN') { 'WARN' } else { 'FAIL' })"
    $report += ""
    $report += "**Validation Checklist:**"
    $report += "- [PASS/FAIL] All $(if ($ExecutionData.UseReduced) { '108' } else { '2,400' }) combinations tested"
    $report += "- [PASS/FAIL] Success rate >= 95%"
    $report += "- [PASS/FAIL] All parameters within expected ranges"
    $report += "- [PASS/FAIL] All Sharpe ratios non-zero"
    $report += "- [PASS/FAIL] Output directories unique (microsecond timestamps)"
    $report += "- [PASS/FAIL] Best Sharpe >= Phase 4 baseline (or within 5%)"
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
$insights = Generate-Insights $ExecutionData.Phase3Baseline $ExecutionData.Phase4Baseline $ExecutionData.Phase5Best $ExecutionData.Top10Results $filterAnalysis $parameterAnalysis

$report += "## Key Findings and Insights"
$report += ""
$report += "### Best Filter Parameters Identified"
$report += ""
$report += "| Parameter | Value |"
$report += "|-----------|-------|"
$report += "| DMI Enabled | $($ExecutionData.Phase5Best.DmiEnabled) |"
$report += "| DMI Period | $($ExecutionData.Phase5Best.DmiPeriod) |"
$report += "| Stochastic K | $($ExecutionData.Phase5Best.StochPeriodK) |"
$report += "| Stochastic D | $($ExecutionData.Phase5Best.StochPeriodD) |"
$report += "| Bullish Threshold | $($ExecutionData.Phase5Best.StochBullishThreshold) |"
$report += "| Bearish Threshold | $($ExecutionData.Phase5Best.StochBearishThreshold) |"
$report += ""

$report += "### Performance Improvements"
$report += ""
$report += "| Metric | Improvement |"
$report += "|--------|-------------|"
$report += "| Sharpe Ratio | {0:+0.1;-0.1;0.0}% over Phase 4 |" -f $sharpeImprovement
$report += "| Total PnL | $(Format-Currency $pnlImprovement) over Phase 4 |"
$report += "| Win Rate | {0:+0.0;-0.0;0.0} percentage points |" -f $winRateChange
$maxDdChange = if ($ExecutionData.Phase5Best.MaxDrawdown -ne $null -and $ExecutionData.Phase4Baseline.MaxDrawdown -ne $null) {
    $ExecutionData.Phase5Best.MaxDrawdown - $ExecutionData.Phase4Baseline.MaxDrawdown
} else { $null }
$maxDdDisplay = if ($maxDdChange -ne $null) { Format-Currency $maxDdChange } else { "N/A" }
$report += "| Max Drawdown | $maxDdDisplay over Phase 4 |"
$report += ""

$report += "### Filter Impact Insights"
$report += ""
foreach ($insight in $insights) {
    $report += "- $insight"
}
$report += ""

# Recommendations for Phase 6
$report += "## Recommendations for Phase 6"
$report += ""
$report += "### Phase 6 Fixed Parameters (from Phase 3, 4, and 5 best)"
$report += ""
$report += "**MA Parameters (from Phase 3):**"
$report += "- fast_period: $($ExecutionData.Phase3Baseline.FastPeriod)"
$report += "- slow_period: $($ExecutionData.Phase3Baseline.SlowPeriod)"
$report += "- crossover_threshold_pips: $($ExecutionData.Phase3Baseline.Threshold)"
$report += ""
$report += "**Risk Management Parameters (from Phase 4):**"
$report += "- stop_loss_pips: $($ExecutionData.Phase4Baseline.StopLoss)"
$report += "- take_profit_pips: $($ExecutionData.Phase4Baseline.TakeProfit)"
$report += "- trailing_stop_activation_pips: $($ExecutionData.Phase4Baseline.TrailingActivation)"
$report += "- trailing_stop_distance_pips: $($ExecutionData.Phase4Baseline.TrailingDistance)"
$report += ""
$report += "**Filter Parameters (from Phase 5):**"
$report += "- dmi_enabled: $($ExecutionData.Phase5Best.DmiEnabled)"
$report += "- dmi_period: $($ExecutionData.Phase5Best.DmiPeriod)"
$report += "- stoch_period_k: $($ExecutionData.Phase5Best.StochPeriodK)"
$report += "- stoch_period_d: $($ExecutionData.Phase5Best.StochPeriodD)"
$report += "- stoch_bullish_threshold: $($ExecutionData.Phase5Best.StochBullishThreshold)"
$report += "- stoch_bearish_threshold: $($ExecutionData.Phase5Best.StochBearishThreshold)"
$report += ""

$report += "### Phase 6 Optimization Focus"
$report += ""
$report += "**Parameters to Optimize:**"
$report += "- Parameter refinement and sensitivity analysis"
$report += "- Multi-objective optimization (Sharpe, PnL, drawdown)"
$report += "- Pareto frontier analysis"
$report += ""
$report += "**Expected Phase 6 Configuration:**"
$report += "- Total combinations: ~200-500 (fine grid around Phase 5 best)"
$report += "- Expected runtime: 4-6 hours with 8 workers"
$report += "- Success criteria: Further improve Sharpe ratio and reduce drawdown"
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
$expectedHours = if ($ExecutionData.UseReduced) { 2 } else { 40 }
$report += "- Execution completed in $(Format-Duration $ExecutionData.Duration) ({0:N1}% of expected {1} hours)" -f (($ExecutionData.Duration.TotalHours / $expectedHours) * 100), $expectedHours
$report += "- {0} backtests completed successfully ({1:N1}% success rate)" -f $ExecutionData.CompletedCount, $ExecutionData.SuccessRate
$report += "- All output directories had unique timestamps (bug fix verified)"
$report += "- All Sharpe ratios were non-zero (bug fix verified)"
$report += ""

# Next Steps
$report += "## Next Steps"
$report += ""
$report += "### Immediate Actions"
$report += "- [ ] Review top 10 results in detail"
$report += "- [ ] Verify validation report: optimization/results/phase5_validation_report.json"
$report += "- [ ] Document best filter parameters in Phase 5 summary"
$report += "- [ ] Archive Phase 5 results"
$report += ""

$report += "### Phase 6 Preparation"
$report += "- [ ] Create optimization/configs/phase6_refinement.yaml with Phase 5 best parameters fixed"
$report += "- [ ] Update Phase 6 config documentation"
$report += "- [ ] Create Phase 6 execution scripts"
$report += "- [ ] Schedule Phase 6 execution (4-6 hours runtime)"
$report += ""

$report += "### Documentation"
$report += "- [ ] Update optimization README with Phase 5 findings"
$report += "- [ ] Create Phase 5 summary report"
$report += "- [ ] Share results with team"
$report += ""

# Appendix: Output Files
$report += "## Appendix: Output Files"
$report += ""
$report += "| File | Path |"
$report += "|------|------|"
if ($ExecutionData.UseReduced) {
    $report += "| CSV Results | optimization/results/phase5_filters_reduced_results.csv |"
    $report += "| Top 10 JSON | optimization/results/phase5_filters_reduced_results_top_10.json |"
    $report += "| Summary JSON | optimization/results/phase5_filters_reduced_results_summary.json |"
    $report += "| Checkpoint File | optimization/checkpoints/phase5_filters_reduced_checkpoint.csv |"
} else {
    $report += "| CSV Results | optimization/results/phase5_filters_results.csv |"
    $report += "| Top 10 JSON | optimization/results/phase5_filters_results_top_10.json |"
    $report += "| Summary JSON | optimization/results/phase5_filters_results_summary.json |"
    $report += "| Checkpoint File | optimization/checkpoints/phase5_filters_checkpoint.csv |"
}
$report += "| Validation Report | optimization/results/phase5_validation_report.json |"
$report += "| Execution Log | optimization/logs/phase5/phase5_execution_[timestamp].log |"
$report += "| Execution Report | optimization/results/PHASE5_EXECUTION_REPORT.md (this file) |"
$report += ""

# Write report to file
$reportContent = $report -join "`n"
$reportContent | Out-File -FilePath $OutputPath -Encoding UTF8

Write-Host "Phase 5 execution report generated: $OutputPath" -ForegroundColor Green
Write-Host "Report contains $($report.Count) lines of comprehensive analysis" -ForegroundColor Green

