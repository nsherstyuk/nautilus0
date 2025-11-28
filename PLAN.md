# Implementation Plan: ML Strategy Integration

## 1. Analysis & Findings

### Custom Architecture Analysis
*   **Custom IBKR Connector:** Located in `patches/ib_connection_patch.py`. It monkey-patches `InteractiveBrokersClientConnectionMixin` to override connection methods (`_connect`, `_connect_socket`, etc.). This ensures stability or handles specific connection quirks without modifying the core library code.
*   **Custom Data Loader:** `data/ingest_historical.py` wraps the standard `HistoricInteractiveBrokersClient` but adds custom bar specification handling and chunking logic.
*   **Partial Position Closing:** Implemented in `strategies/moving_average_crossover.py` (approx. line 1670). It uses `self.cfg.partial_close_enabled` to trigger a partial close on the first trailing stop activation. This logic is tightly coupled with the `MovingAverageCrossover` strategy.

### Critique: M5 Bar Support
*   **Status:** **SUPPORTED**.
*   **Evidence:** `data/ingest_historical.py` explicitly handles `5-MINUTE` and `5-MIN` in `_calculate_chunk_size_days` (lines 149-150) and `create_bar_specification`.

### Safety Check: Custom OrderFactory
*   **Observation:** The existing strategy uses `self.order_factory.market()` and `self.order_factory.bracket()`. These appear to be standard NautilusTrader methods.
*   **Gotchas:**
    *   **Patched Connection:** The IBKR connection is patched at runtime (`patches/ib_connection_patch.py`). This must be applied in the ML strategy's runner if live trading is intended (though the brief focuses on Backtest/Research first).
    *   **No Custom Factory Methods Found:** I did not find unique method names (e.g., `custom_order(...)`) on `order_factory`. If they exist, they might be dynamically injected or I missed a specific mixin. However, the usage in `MovingAverageCrossover` suggests standard `bracket` orders are the primary mechanism for entry + SL/TP.
    *   **Execution Logic:** The "Partial Close" logic is manual (calculating fraction and submitting a new market order), not a built-in `OrderFactory` method.

## 2. Implementation Steps

### Phase 1: Research & Data (Offline)
*   **Goal:** Create training data and model.
*   **Action 1:** Create `research/train_model.py`.
    *   **Data Loading:** Use `data/historical/` parquet files (ensure M5 data is ingested).
    *   **Feature Engineering:** Implement:
        *   Log Returns
        *   RSI(14), MACD, Stoch(14,3,3), ADX(14), ATR(14) using `pandas-ta`.
    *   **Labeling:** Implement Dynamic Triple Barrier Method (Entry +/- 1.5 * ATR).
    *   **Training:** Train Random Forest Classifier.
    *   **Export:** Save model to `models/strategy_model.joblib`.

### Phase 2: Strategy Implementation ("The Brain")
*   **Goal:** Create the live/backtest strategy class.
*   **Action 2:** Create `strategies/ml_strategy.py`.
    *   **Class:** `MLSignalStrategy(Strategy)`.
    *   **Config:** Define `MLSignalStrategyConfig`.
    *   **Components:**
        *   `on_start`: Load `models/strategy_model.joblib`.
        *   `on_bar`:
            *   Maintain a rolling buffer of bars (enough for indicator lookback).
            *   Re-calculate features **exactly** as in Phase 1.
            *   Call `model.predict()`.
    *   **Execution:**
        *   Use `self.order_factory.market()` or `bracket()` based on signal.
        *   *Decision Point:* Do we port the "Partial Close" logic? (Brief implies "Analyze... against requirements", but requirements only say "If Signal 1/-1, send Order"). I will implement basic execution first, keeping the structure open for partial close if needed later.

### Phase 3: Backtesting (Verification)
*   **Goal:** Verify the strategy using the custom data format.
*   **Action 3:** Modify `backtest/run_backtest.py` (or create `backtest/run_ml_backtest.py`).
    *   Load `MLSignalStrategy`.
    *   Ensure `BacktestDataConfig` uses the correct M5 bar spec from `data/ingest_historical.py`.
    *   Wire up the `BacktestEngine`.
    *   **Analysis:** Output Total PnL, Win Rate, Trade Count.

## 3. Risks & Considerations
*   **Feature Parity:** The biggest risk is `pandas-ta` in research vs. incremental calculation in `on_bar`. We must ensure the calculations are identical.
*   **Lookback Buffer:** The strategy needs enough history to calculate valid indicators (e.g., EMA-150 needs 150+ bars). We must handle the "warmup" period correctly.
*   **Custom Logic Porting:** If the ML strategy requires the advanced features of the existing `MovingAverageCrossover` (Regime Detection, Adaptive Stops, Partial Close), these will need to be refactored out of the massive `MovingAverageCrossover` class into reusable components or duplicated. For this MVP, I will stick to the Brief's core requirements.
