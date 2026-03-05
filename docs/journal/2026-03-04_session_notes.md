# Session Notes — Live vs Backtest Parity Investigation

_Last updated: 2026-02-20_

---

## What was fixed this session

### 1. `_resample_to_30m()` — `ts_event` bug (ROOT CAUSE of DMI divergence)

**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py`, line ~1300

**Bug:** Used `b.ts_init` (bar close time in live) as the pandas resample bucket key.
In live, `ts_init` = bar close (+15 min offset from bar open). In backtest, `ts_init == ts_event` = bar open.
This shifted every 15m bar into the wrong 30m bucket in live, producing different DMI values.

**Fix:** Changed to `b.ts_event` (bar open time, consistent in both live and backtest).

**Verified:** Simulated DMI diff dropped from ±0.05–0.15 to < 0.002 across all Feb 20 bars.

**Impact:** Live `dmi_plus` was 0.27–0.38 vs backtest 0.19–0.26 → 7/11 predictions flipped.
After fix, prediction agreement is expected to be ~100% (matches simulation).

---

### 2. `scripts/compare_live_vs_bt_bar_metrics.py` — two bugs fixed

- `--live` default was `live_trading.log` (BAR_METRICS not there) → changed to `strategy.log`
- Added `--live-bar-shift-min=-15` (default): shifts live `ts_init`-stamped BAR_METRICS lines
  back 15 min so they align with replay `ts_event`-stamped lines before comparison.

**Usage after fix:**
```
python scripts/compare_live_vs_bt_bar_metrics.py \
    --live    logs/live_mtf/strategy.log \
    --replay  backtest_results/<run_dir>/replay.log \
    --start   "2026-02-20 19:00" \
    --end     "2026-02-20 22:00"
```

---

## Investigation findings (disproven as root causes)

| Hypothesis | Result |
|---|---|
| `extend_catalog_with_live_bars.py` resampling bug | Disproven — reads native IB OHLC directly |
| Catalog OHLC values differ from live CSV | Disproven — 289 bars, 0 mismatches |
| Feb 16 05:00–21:45 gap (68 bars in live only) | Not causal — doesn't shift the last-50 30m window |
| `live_trading.log` has BAR_METRICS | False — BAR_METRICS go to `strategy.log` |

---

## Still pending / next actions

### A. Validate fix in production
- Restart live strategy (with `ts_event` fix deployed)
- After next trading session, run compare script and confirm pred agreement > 90%

### B. Backtest exit-code-1 when 0 trades
- `run_backtest_mtf_v2_entry_confirmed_adaptive.py` exits with code 1 when no trades occur
  (post-processing crashes on empty `positions_df`)
- Fix: wrap post-processing in try/except, exit 0 on empty results

### C. Dedup guard logs before check
- In `on_bar()`, the BAR_METRICS log line fires before the duplicate timestamp guard
- Move the log line to after the guard so deduped bars don't produce spurious log entries

### D. Asymmetric thresholds (lower priority)
- `prediction_threshold` applies equally to long and short — consider separate thresholds
  if live trade balance is skewed

---

## Key facts for next session

- BAR_METRICS are in `logs/live_mtf/strategy.log`, NOT `live_trading.log`
- Live `bar_time` in strategy.log = `ts_init` = bar close time (offset +15 min from bar open)
- Backtest replay.log `bar_time` = `ts_event` = bar open time
- Catalog parquet prices: `int64 / 1e9` (fixed_size_binary[8], little-endian)
- Live bar CSVs: `logs/live_mtf/live_bars/YYYY-MM-DD/EUR_USD_15_mins_MIDPOINT_rth0.csv`
  - `time_utc` = bar open time = ts_event
  - `is_warmup` = 1/0 integer (not bool)
  - Warmup bars are duplicated across restarts (same bar delivered 8-9x)
- `bars_buffer_15m` maxlen=3400, `bars_buffer_30m` maxlen=50
- DMI is `dmp_30m` = column index 1 of `ta.adx(length=14)` / 100
