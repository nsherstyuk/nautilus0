# Logging-Driven Strategy Improvement Plan (ML Version)

## Objective
Systematically identify and eliminate "toxic" trade conditions where the ML model consistently fails. We will capture the exact feature state at entry and correlate it with trade PnL to find rules like "Don't trust the model when MAMA Diff is negative and Volatility is low."

## Phase 1: Lock in Baseline
*   **Status:** User is currently running `run_backtest_mtf_v2_replay.py` with fixed data.
*   **Action:** Analyze the standard reports (`performance_stats.json`, `trades.csv`) from this run to establish the baseline PnL and Win Rate.

## Phase 2: Instrumentation (The "Black Box" Recorder)
**Goal:** Modify `MLSignalStrategyV2` to record a "feature snapshot" for every trade.

1.  **Target File:** `strategies/ml_strategy_mtf_v2.py`
2.  **Implement `_capture_trade_features` Logic:**
    *   In `_execute_entry`, capture the latest values of the 10 ML features:
        *   `log_ret` (15m)
        *   `mama_diff` (15m)
        *   `dmp_30m`, `dmn_30m`
        *   `stoch_k_30m`, `stoch_d_30m`
        *   `wma_diff_30m`
        *   `atr` (15m)
        *   `hour`, `day_of_week`
    *   **PLUS** Raw context features:
        *   `current_atr` (value)
        *   `prediction_score` (raw probability)
3.  **Log Trade Outcomes:**
    *   Match entry features with realized PnL when the position closes.
    *   Save to `logs/backtest_results/<run_id>/ml_trade_features.csv`.

## Phase 3: Data Mining & Analysis
**Goal:** Find specific feature combinations that predict failure.

1.  **Generate Data:** Run the instrumented backtest.
2.  **Analyze (`analyze_ml_failures.py`):**
    *   **Confidence vs PnL:** Does higher model confidence actually correlate with higher PnL?
    *   **Regime Analysis:** Are there specific "MAMA Diff" or "Stoch" ranges where the model is essentially guessing (50% WR)?
    *   **Time Decay:** Does PnL degrade significantly after X bars in a trade (Stall detection tuning)?

## Phase 4: Execution & Refinement
**Goal:** Filter the model's bad calls.

1.  **Implement Filters:**
    *   Add "Meta-Filters" to `MLSignalStrategyV2Config`.
    *   Example: `if self.prediction_score > 0.6 but self.wma_diff < 0: REJECT`
2.  **Verify:** Re-run backtest and confirm higher Sharpe/PnL.
