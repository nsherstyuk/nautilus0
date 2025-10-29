# Phase 5 Parameter Sensitivity Analysis Report

## Executive Summary

**Analysis Date:** 2025-10-24T09:05:43.798313
**Dataset Size:** 2387 completed runs
**Best Sharpe Ratio:** 0.4779
**Parameters Analyzed:** 12

## Top 4 Most Sensitive Parameters

| Rank | Parameter | Sensitivity Score | Pearson Corr | Spearman Corr | Variance Contrib | Stability |
|------|-----------|------------------|--------------|---------------|------------------|----------|
| 1 | stoch_period_d | 0.392 | -0.491 | -0.486 | 0.244 | high |
| 2 | stoch_bearish_threshold | 0.354 | 0.452 | 0.444 | 0.208 | high |
| 3 | stoch_period_k | 0.102 | -0.088 | -0.062 | 0.124 | high |
| 4 | stoch_bullish_threshold | 0.090 | 0.128 | 0.124 | 0.033 | high |

## All Parameters Correlation Analysis

| Parameter | Pearson Corr | Pearson P-Value | Spearman Corr | Spearman P-Value |
|-----------|--------------|-----------------|---------------|------------------|
| stoch_period_d | -0.491 | 0.0000 | -0.486 | 0.0000 |
| stoch_bearish_threshold | 0.452 | 0.0000 | 0.444 | 0.0000 |
| stoch_bullish_threshold | 0.128 | 0.0000 | 0.124 | 0.0000 |
| stoch_period_k | -0.088 | 0.0000 | -0.062 | 0.0026 |
| dmi_period | -0.078 | 0.0001 | -0.058 | 0.0043 |
| fast_period | 0.000 | 1.0000 | 0.000 | 1.0000 |
| slow_period | 0.000 | 1.0000 | 0.000 | 1.0000 |
| crossover_threshold_pips | 0.000 | 1.0000 | 0.000 | 1.0000 |
| stop_loss_pips | 0.000 | 1.0000 | 0.000 | 1.0000 |
| take_profit_pips | 0.000 | 1.0000 | 0.000 | 1.0000 |
| trailing_stop_activation_pips | 0.000 | 1.0000 | 0.000 | 1.0000 |
| trailing_stop_distance_pips | 0.000 | 1.0000 | 0.000 | 1.0000 |

> Note: Correlation is not defined for parameters with zero variance across analyzed rows. These constant features are shown with numeric placeholders (0.0, p=1.0): fast_period, slow_period, stop_loss_pips, take_profit_pips, trailing_stop_activation_pips, trailing_stop_distance_pips.

## Variance Contribution Analysis

| Parameter | Variance Contribution |
|-----------|----------------------|
| stoch_period_d | 0.244 |
| stoch_bearish_threshold | 0.208 |
| stoch_period_k | 0.124 |
| stoch_bullish_threshold | 0.033 |
| dmi_period | 0.019 |
| fast_period | 0.000 |
| slow_period | 0.000 |
| crossover_threshold_pips | 0.000 |
| stop_loss_pips | 0.000 |
| take_profit_pips | 0.000 |
| trailing_stop_activation_pips | 0.000 |
| trailing_stop_distance_pips | 0.000 |

## Parameter Stability Analysis (Top 10 Results)

| Parameter | Mean | Std Dev | CV | Stability | Min | Max |
|-----------|------|---------|----|-----------|-----|-----|
| fast_period | 42.00 | 0.00 | 0.000 | high | 42.00 | 42.00 |
| slow_period | 270.00 | 0.00 | 0.000 | high | 270.00 | 270.00 |
| crossover_threshold_pips | 0.35 | 0.00 | 0.000 | high | 0.35 | 0.35 |
| stop_loss_pips | 35.00 | 0.00 | 0.000 | high | 35.00 | 35.00 |
| take_profit_pips | 50.00 | 0.00 | 0.000 | high | 50.00 | 50.00 |
| trailing_stop_activation_pips | 22.00 | 0.00 | 0.000 | high | 22.00 | 22.00 |
| trailing_stop_distance_pips | 12.00 | 0.00 | 0.000 | high | 12.00 | 12.00 |
| dmi_period | 12.60 | 2.84 | 0.225 | medium | 10.00 | 18.00 |
| stoch_period_k | 18.00 | 0.00 | 0.000 | high | 18.00 | 18.00 |
| stoch_period_d | 3.00 | 0.00 | 0.000 | high | 3.00 | 3.00 |
| stoch_bullish_threshold | 32.00 | 2.58 | 0.081 | high | 30.00 | 35.00 |
| stoch_bearish_threshold | 65.00 | 0.00 | 0.000 | high | 65.00 | 65.00 |

## Boolean Parameter Analysis (dmi_enabled)

**True Values:** Mean=0.381, Std=0.054
**False Values:** Mean=0.390, Std=0.049
**Statistical Test:** mann_whitney_u
**P-value:** 0.0001
**Effect Size (Cohen's d):** -0.172
**Conclusion:** Minimal impact on Sharpe ratio

## Recommendations for Phase 6

1. Refine 4 most sensitive parameters: stoch_period_d, stoch_bearish_threshold, stoch_period_k, stoch_bullish_threshold
2. Fix 8 remaining parameters at Phase 5 best values
3. Expected Phase 6 combinations: 200-300 (vs 5.9M current)
4. Expected runtime reduction: 4-6 hours (vs 20-40 hours current)
5. Use ±10% ranges around Phase 5 best values for top 4 parameters

## Next Steps

1. Review the top 4 sensitive parameters identified above
2. Update `optimization/configs/phase6_refinement.yaml` to refine only these 4 parameters
3. Fix the remaining 8 parameters at their Phase 5 best values
4. Run Phase 6 with the updated configuration

