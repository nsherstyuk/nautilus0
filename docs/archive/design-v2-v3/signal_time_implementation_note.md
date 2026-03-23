# Signal Generation Time Tracking Implementation

## Summary
Implemented signal generation time tracking to enable accurate hour/weekday analysis for entry-confirmed strategies.

## Changes Made

### 1. Strategy Modification (`ml_strategy_mtf_v2_entry_confirmed_adaptive.py`)
- Added `signal_generation_time` field to `PendingSignal` class (line 113)
- This tracks when the ML signal was first generated (15-minute bar timestamp)

### 2. Backtest Script Modification (`run_backtest_mtf_v2_entry_confirmed_adaptive.py`)
- Added `_build_trades_from_positions_with_signal_time()` function (lines 45-128)
- Extracts signal generation time from order tags
- Creates `signal_hour` and `signal_weekday` fields in trade records
- Falls back to execution time if signal time not available

### 3. Report Generation (`run_backtest_mtf_v2_full.py`)
- Added signal-based matrix generation (lines 515-540)
- Creates three new matrix files when signal data is available:
  - `hour_weekday_pnl_matrix_by_signal.csv`
  - `hour_weekday_trades_matrix_by_signal.csv`
  - `hour_weekday_winrate_matrix_by_signal.csv`

## CRITICAL: Strategy Order Tag Implementation Required

**The implementation is NOT complete yet.** The strategy needs to be modified to pass signal generation time through order tags when submitting bracket orders.

### Required Changes to Strategy

The strategy's order submission code needs to include signal generation time in the entry order tags:

```python
# When creating bracket orders, add signal_time to entry_tags:
signal_time_ns = self.pending_signal.signal_generation_time  # Already tracked
entry_tags = [f"{tag_prefix}", f"signal_time={signal_time_ns}"]

bracket = self.order_factory.bracket(
    instrument_id=self.instrument_id,
    order_side=order_side,
    quantity=size,
    sl_trigger_price=sl_price,
    tp_price=tp_price,
    entry_tags=entry_tags,  # Include signal_time tag
    sl_tags=[f"{tag_prefix}_SL"],
    tp_tags=[f"{tag_prefix}_TP"],
)
```

### Where to Make Changes

The adaptive strategy currently doesn't have a complete `_execute_signal` method implementation. It needs to:
1. Inherit or implement the full order submission logic from `ml_strategy_mtf_v2_entry_confirmed.py`
2. Modify the `entry_tags` parameter to include `signal_time={timestamp_ns}`
3. Ensure `self.pending_signal.signal_generation_time` is passed through

## Why This Matters

**Current matrices (execution-based):**
- Show P&L by trade execution time
- Misleading for hour exclusions because signals generated in excluded hours won't execute

**New matrices (signal-based):**
- Show P&L by signal generation time
- Accurate for determining which hours to exclude
- When you exclude hour X, you prevent signals from being generated at hour X

## Usage

After completing the strategy modification:

1. Run backtest with `python run_backtest_mtf_v2_entry_confirmed_adaptive.py`
2. Check for signal-based matrices in results folder
3. Use `*_by_signal.csv` matrices to identify profitable signal generation hours
4. Configure hour exclusions based on signal generation time, not execution time
5. Re-run backtest with exclusions - P&L should match estimated values

## Next Steps

1. Complete strategy modification to pass signal_time through order tags
2. Test with a short backtest run
3. Verify signal-based matrices are generated correctly
4. Re-analyze 2024 and 2025-2026 data with signal-based matrices
5. Update hour exclusion configuration based on signal generation analysis
