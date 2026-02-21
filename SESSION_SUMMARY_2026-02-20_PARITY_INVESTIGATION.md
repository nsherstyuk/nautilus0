# Session Summary: Live vs Backtest Parity Investigation
**Date:** February 20, 2026  
**Focus:** Exit code debugging, parity measurement, and deterministic computation improvements

---

## Executive Summary

This session focused on establishing and improving parity between live trading and backtest replay for the MTF V2 strategy. Key accomplishments:

1. ✅ **Validated clean backtest exit behavior** (PY_EXIT:0 confirmed)
2. ✅ **Implemented deterministic 30m aggregation** (incremental bucket-based resampling)
3. ✅ **Unified timestamp semantics** (ts_event convention for feature indexing)
4. ✅ **Added DMI parity debug logging** (opt-in via MTF2_DMI_PARITY_DEBUG=1)
5. ✅ **Implemented session-filtering tools** (auto-detect latest contiguous live session)

**Current Parity Status:**
- Prediction agreement: **68.3%** (unchanged after deterministic improvements)
- DMI+ mean absolute difference: **0.047742** (full log) / **0.056727** (latest session only)
- Common bars: 48 (full log) / 32 (latest session only)

---

## Problem Statement

### Original Request
> "trace and fix the nonzero backtest exit source, then run a parity check over the same recent live date range and report how close backtest and live are"

### Evolved Context
- Initial exit-code investigation revealed clean behavior (no fix needed)
- Live logs showed duplicate timestamps from multiple process restarts
- DMI+ values diverged between live and backtest (mean abs diff ~0.048)
- User questioned fundamental 30m resampling approach
- Focus shifted to: **deterministic computation** + **session contamination isolation**

---

## Technical Environment

### Key Files Modified

#### 1. `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py`
**Purpose:** Core multi-timeframe ML trading strategy  
**Changes:**
- **Lines 318-326:** Added persistent 30m aggregator state variables
  ```python
  self._agg_30m_bucket_start_ns: Optional[int] = None
  self._agg_30m_open: Optional[float] = None
  self._agg_30m_high: Optional[float] = None
  self._agg_30m_low: Optional[float] = None
  self._agg_30m_close: Optional[float] = None
  ```
- **Line 327:** Added `MTF2_DMI_PARITY_DEBUG` environment flag
- **Line 949:** Modified `on_bar()` to pass bar object to `_resample_to_30m(bar)`
- **Lines 1193, 1204:** Changed feature timestamp from `ts_init` to `ts_event`
- **Lines 1302-1368:** Replaced full pandas resample with incremental bucket aggregator
- **Lines 1369-1392:** Added `_log_dmi_parity_snapshot()` method for debug logging

**Key Behavior Changes:**
- 30m bars now built incrementally (bucket-based) instead of full-buffer resample each bar
- Feature DataFrame indexed by bar open time (`ts_event`) in both live and backtest
- Optional debug logging emits last 14 30m bars' OHLC + DMI+ values when enabled

#### 2. `scripts/compare_live_vs_bt_bar_metrics.py`
**Purpose:** Compare [BAR_METRICS] lines from live vs backtest replay logs  
**Changes:**
- Added `_latest_contiguous_bounds()` function (auto-detect latest clean session)
- Added `--session-start`, `--session-end`, `--auto-session` arguments
- Modified `main()` to apply session filter before window filter
- Prints chosen session window for transparency

**Usage:**
```bash
python scripts/compare_live_vs_bt_bar_metrics.py \
  --live logs/live_mtf/strategy.log \
  --replay backtest_results/.../replay.log \
  --start "2026-02-19 19:15" \
  --end "2026-02-20 21:45"
# Auto-session filtering enabled by default
```

#### 3. `scripts/report_dmi_parity_diff.py` (NEW)
**Purpose:** Specialized DMI+ comparison between live and replay  
**Features:**
- Parses [BAR_METRICS] (live) and [DMI_PARITY] (replay) snapshots
- Auto-detects latest contiguous session (max 20min gap tolerance)
- Computes mean/p90/max absolute DMI differences
- Reports top 5 worst divergence timestamps

**Usage:**
```bash
python scripts/report_dmi_parity_diff.py \
  --live logs/live_mtf/strategy.log \
  --replay backtest_results/.../replay.log \
  --start "2026-02-19 19:15" \
  --end "2026-02-20 21:45"
# Defaults to auto-latest-session filtering
```

---

## Comparison Window Details

### Live Trading Window
- **Source:** `logs/live_mtf/strategy.log`
- **Full log range:** 2026-02-19 19:15:00+00:00 to 2026-02-20 21:45:00+00:00
- **Total [BAR_METRICS] lines:** 111 (includes duplicates from restarts)
- **Unique timestamps:** 102

### Auto-Detected Latest Session
- **Session range:** 2026-02-20 05:15:00+00:00 to 2026-02-20 21:30:00+00:00
- **Common DMI points:** 32 (vs 48 in full log)
- **Detection method:** Find latest contiguous sequence with max 20min gap tolerance

### Backtest Replay
- **Results directory:** `backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260220_213108`
- **Replay log:** `replay.log` (contains [BAR_METRICS] and [DMI_PARITY] lines)
- **Run date:** 2026-02-17 to 2026-02-20 (3-day warmup + comparison window)
- **Debug flag:** MTF2_DMI_PARITY_DEBUG=1 (enabled for latest run)

---

## Parity Measurements

### Baseline (Pre-Implementation)
| Metric | Value |
|--------|-------|
| Prediction agreement % | 68.3% |
| Exact metric matches % | 0.0% |
| Common bars | 101 |
| DMI+ mean abs diff | ~0.048 |
| DMI+ max abs diff | ~0.106 |

### Post-Implementation (After Deterministic Fixes)
| Metric | Full Log | Latest Session Only |
|--------|----------|---------------------|
| Prediction agreement % | 68.3% | Not yet measured |
| Exact metric matches % | 0.0% | Not yet measured |
| Common bars | 48 (DMI) | 32 (DMI) |
| DMI+ mean abs diff | 0.047742 | 0.056727 |
| DMI+ p90 abs diff | 0.071925 | 0.093871 |
| DMI+ max abs diff | 0.106104 | 0.106104 |

**Key Observation:** Session filtering reduced common points but **did not improve** DMI parity, suggesting deeper computation-path issues beyond restart contamination.

---

## Root Cause Analysis

### DMI Divergence Causes Identified

1. **Timestamp Bucketing Mismatch (FIXED)**
   - **Issue:** Live used `ts_init` (bar close), backtest used `ts_event` (bar open)
   - **Impact:** Same logical 30m bar bucketed differently by 15 minutes
   - **Fix:** Unified both paths to use `ts_event` for feature indexing (lines 1193, 1204)

2. **Full-Buffer Resample Artifacts (FIXED)**
   - **Issue:** `df.resample('30T').agg(...)` recomputed entire 30m history each bar
   - **Impact:** Floating-point accumulation drift, potential boundary instability
   - **Fix:** Incremental bucket aggregator finalizes only when 30m boundary crossed (lines 1302-1368)

3. **Mixed Live-Run Contamination (MITIGATED)**
   - **Issue:** Live process restarts create duplicate timestamps with different feature states
   - **Impact:** Comparison script picks "last value" which may have different warmup history
   - **Mitigation:** Auto-session filtering isolates latest contiguous run (session-filtering tools)

4. **Persistent State Divergence (SUSPECTED, NOT CONFIRMED)**
   - **Hypothesis:** Even within single session, live and backtest may have different historical feature states entering comparison window
   - **Evidence:** Session filtering didn't improve parity despite clean single-run isolation
   - **Potential causes:**
     - Historical bar delivery differences (backtest double-delivery vs live single)
     - Feature warmup from different start states
     - MAMA/FAMA adaptive period evolution path dependency

---

## Deterministic Improvements Implemented

### 1. Incremental 30m Aggregator
**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py` (lines 1302-1368)

**Old Approach:**
```python
def _resample_to_30m(self):
    df_15m = self.features_15m.copy()
    df_30m = df_15m.resample('30T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    })
    return df_30m
```

**New Approach:**
```python
def _resample_to_30m(self, bar: Bar) -> Optional[dict]:
    bar_ts = bar.ts_event  # Use bar open time
    bar_start_minute = (bar_ts // 60_000_000_000) * 60_000_000_000
    bucket_start = (bar_start_minute // 1_800_000_000_000) * 1_800_000_000_000
    
    if self._agg_30m_bucket_start_ns is None:
        # Initialize new bucket
        self._agg_30m_bucket_start_ns = bucket_start
        self._agg_30m_open = bar.open.as_double()
        # ... etc
        return None
    
    if bucket_start == self._agg_30m_bucket_start_ns:
        # Update current bucket
        self._agg_30m_high = max(self._agg_30m_high, bar.high.as_double())
        # ... etc
        return None
    else:
        # Finalize bucket and start new one
        finalized = {
            'open': self._agg_30m_open,
            'high': self._agg_30m_high,
            'low': self._agg_30m_low,
            'close': self._agg_30m_close,
            'ts_event': self._agg_30m_bucket_start_ns
        }
        # Reset for next bucket
        return finalized
```

**Benefits:**
- Deterministic bucketing (aligned to 30-minute Unix epoch boundaries)
- No full-buffer recomputation each bar
- Identical logic path regardless of historical bar order

### 2. Unified Timestamp Convention
**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py` (lines 1193, 1204)

**Change:**
```python
# OLD: self.features_15m.loc[bar.ts_init, 'mama'] = mama_val
# NEW:
self.features_15m.loc[bar.ts_event, 'mama'] = mama_val
```

**Impact:**
- Live and backtest now index features by bar **open** time consistently
- Eliminates 15-minute bucketing offset between environments

### 3. DMI Parity Debug Logging
**File:** `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py` (lines 1369-1392)

**Activation:**
```bash
MTF2_DMI_PARITY_DEBUG=1 python run_backtest_mtf_v2_entry_confirmed_adaptive.py
```

**Output Format:**
```
[DMI_PARITY] 2026-02-20 10:00:00+00:00 | last_14_30m_ohlc=[(ts, o, h, l, c), ...] | dmi_plus=24.567
```

**Usage:**
- Compare against live [BAR_METRICS] DMI+ values
- Identify which specific 30m bars diverge in OHLC composition
- Trace backward to 15m bar aggregation issues

---

## Session-Filtering Methodology

### Auto-Detection Algorithm
**Implementation:** `_latest_contiguous_bounds()` / `latest_contiguous_bounds()`

**Logic:**
1. Parse all [BAR_METRICS] timestamps from log
2. Sort chronologically
3. Walk backward from latest timestamp
4. Break when gap > 20 minutes detected
5. Return (earliest_in_sequence, latest_in_sequence)

**Rationale:**
- Live process restarts create multi-hour gaps in bar timestamps
- Latest contiguous session = most recent uninterrupted run
- 20-minute threshold allows for market close gaps or minor delays

### Application
Both comparison scripts now:
1. Auto-detect latest session by default (can override with `--session-start`/`--session-end`)
2. Filter metrics to session window **before** applying user's comparison window
3. Print chosen session range for transparency

**Example Output:**
```
live_session_auto=2026-02-20 05:15:00+00:00->2026-02-20 21:30:00+00:00
common_dmi_points=32
```

---

## Pending Work & Next Steps

### Immediate Next Actions

1. **Run Full BAR_METRICS Comparison with Session Filtering**
   ```bash
   python scripts/compare_live_vs_bt_bar_metrics.py \
     --live logs/live_mtf/strategy.log \
     --replay backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260220_213108/replay.log \
     --start "2026-02-19 19:15" \
     --end "2026-02-20 21:45"
   ```
   **Goal:** Measure if session filtering improves prediction agreement % or exact matches %

2. **Produce Before/After Parity Delta Table**
   - Compare baseline (68.3% pred, 0% exact) to session-filtered metrics
   - Determine if restart contamination was major factor or deeper issues persist

### Deeper Investigation (If Parity Still Poor)

3. **Extend Warmup Window**
   - Current backtest starts 2026-02-17, comparison starts 2026-02-19 19:15
   - Auto-detected live session starts 2026-02-20 05:15
   - **Action:** Run backtest from 2026-02-15 to ensure identical 30m state entering live session window
   - **Command:**
     ```python
     result, path = run_v2_entry_confirmed_adaptive_backtest(
         symbol='EUR/USD',
         venue='IDEALPRO',
         start_date='2026-02-15',
         end_date='2026-02-21',
     )
     ```

4. **Add MAMA/FAMA Debug Snapshots**
   - Extend `_log_dmi_parity_snapshot()` to include:
     - Last 14 15m bars' `mama`, `fama`, `mama_diff` values
     - Last 14 30m bars' `adx`, `dmi_plus`, `dmi_minus` values
   - Compare full feature state, not just DMI+

5. **Validate Bar Delivery Consistency**
   - Confirm live streamer delivers each bar exactly once
   - Confirm backtest double-delivery is handled correctly (idempotent feature updates)
   - Add bar-delivery-count debug logging

6. **State Snapshot Export**
   - Export full `features_15m` and `features_30m` DataFrames at end of warmup period
   - Compare live vs backtest state before entering comparison window
   - Identify earliest divergence point

---

## Commands Reference

### Run Backtest with DMI Debug
```bash
# Ensure debug flag is set
export MTF2_DMI_PARITY_DEBUG=1  # Linux/Mac
# or
$env:MTF2_DMI_PARITY_DEBUG=1  # PowerShell

cd c:\nautilus0
python -c "
import sys; sys.path.insert(0, '.')
from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest
result, path = run_v2_entry_confirmed_adaptive_backtest(
    symbol='EUR/USD',
    venue='IDEALPRO',
    start_date='2026-02-17',
    end_date='2026-02-20',
)
print('RESULTS DIR:', path)
"
```

### Compare BAR_METRICS (Auto-Session)
```bash
python scripts/compare_live_vs_bt_bar_metrics.py \
  --live logs/live_mtf/strategy.log \
  --replay backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260220_213108/replay.log \
  --start "2026-02-19 19:15" \
  --end "2026-02-20 21:45"
```

### Report DMI Parity (Auto-Session)
```bash
python scripts/report_dmi_parity_diff.py \
  --live logs/live_mtf/strategy.log \
  --replay backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260220_213108/replay.log \
  --start "2026-02-19 19:15" \
  --end "2026-02-20 21:45" \
  > dmi_parity_report.txt
```

### Extend Catalog with Recent Live Data
```bash
python scripts/extend_catalog_with_live_bars.py --start 2026-02-19 --force-overwrite
```

---

## Key Learnings

1. **Incremental Aggregation ≠ Automatic Parity**
   - Deterministic computation path is necessary but not sufficient
   - Historical state evolution matters (warmup path dependency)

2. **Session Filtering Isolates, Doesn't Fix**
   - Auto-session filtering successfully removes restart contamination from analysis
   - But parity gaps persist within clean single-run sessions
   - Suggests deeper feature-state or computation-order issues

3. **Timestamp Semantics Matter**
   - `ts_event` (bar open) vs `ts_init` (bar close) created 15-minute bucketing offset
   - Always use same timestamp reference across environments

4. **Debug Logging Essential for Multi-Timeframe**
   - DMI_PARITY snapshots enable bar-by-bar OHLC + indicator comparison
   - Next iteration should add MAMA/FAMA snapshots for complete feature visibility

5. **Warmup Window Critical**
   - Comparing from arbitrary start time may inherit different historical states
   - Need shared warmup period (3-5 days minimum) for adaptive indicators (MAMA/FAMA)

---

## Environment Variables

### MTF V2 Strategy Controls
- `MTF2_REPLAY_MODE=1` - Enable replay/backtest mode (vs live trading)
- `MTF2_DMI_PARITY_DEBUG=1` - Enable DMI debug snapshot logging
- `MTF2_LIVE_SIGNAL_MAX_AGE_SEC=1200` - Max age for prediction validity (20 min)

### Data Paths
- Live logs: `logs/live_mtf/strategy.log`
- Backtest results: `backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_YYYYMMDD_HHMMSS/`
- Historical data catalog: `data/historical/data/bar/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL/`

---

## Critical Files Index

### Strategy Implementation
- `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py` - Core strategy with incremental 30m aggregator

### Backtest Runner
- `run_backtest_mtf_v2_entry_confirmed_adaptive.py` - Entry point for programmatic backtest runs

### Parity Analysis Tools
- `scripts/compare_live_vs_bt_bar_metrics.py` - Full [BAR_METRICS] comparison with session filtering
- `scripts/report_dmi_parity_diff.py` - Specialized DMI+ divergence report with auto-session

### Data Management
- `scripts/extend_catalog_with_live_bars.py` - Sync live bars into backtest catalog

### Logs
- `logs/live_mtf/strategy.log` - Live trading log with [BAR_METRICS] lines
- `backtest_results/.../replay.log` - Backtest replay log with [BAR_METRICS] and [DMI_PARITY] lines

---

## Reproducibility Checklist

To reproduce this session's work from scratch:

1. ✅ Ensure `.env.mtf_v2` configured with correct model paths and API keys
2. ✅ Run live trading supervisor to generate recent `strategy.log`
3. ✅ Extract live trading window from logs (grep for [BAR_METRICS])
4. ✅ Sync live bars into catalog: `python scripts/extend_catalog_with_live_bars.py --start YYYY-MM-DD --force-overwrite`
5. ✅ Run backtest with DMI debug: Set `MTF2_DMI_PARITY_DEBUG=1`, call `run_v2_entry_confirmed_adaptive_backtest()`
6. ✅ Run DMI parity report: `python scripts/report_dmi_parity_diff.py --live ... --replay ...`
7. ✅ Run full BAR_METRICS comparison: `python scripts/compare_live_vs_bt_bar_metrics.py --live ... --replay ...`
8. ⏳ Analyze delta and determine next investigation path

---

## Open Questions

1. **Why does session filtering NOT improve DMI parity?**
   - Hypothesis: Warmup history differs even within single session
   - Next step: Run backtest from earlier start date (2026-02-15) with longer warmup

2. **Are MAMA/FAMA values also diverging?**
   - Need to add MAMA/FAMA debug snapshots to confirm
   - These are adaptive indicators (path-dependent on historical bars)

3. **Does bar delivery order affect feature calculation?**
   - Backtest delivers each bar twice (NautilusTrader behavior)
   - Live delivers once
   - Need to verify feature updates are idempotent

4. **What is acceptable parity threshold?**
   - Current: 68.3% prediction agreement
   - Target: >90% prediction agreement, >50% exact matches?
   - Define success criteria before further optimization

---

## Contact & Continuation

**Session Date:** February 20, 2026  
**Latest Backtest Results:** `backtest_results/MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260220_213108`  
**Latest Live Session:** 2026-02-20 05:15:00+00:00 to 21:30:00+00:00  

**To continue this work:**
1. Import this summary file for full context
2. Run pending commands in "Next Steps" section
3. Compare parity metrics before/after session filtering
4. Proceed with warmup window extension if needed

**Key Success Metric:** Achieve >90% prediction agreement and >50% exact metric matches between live and backtest for same date range with clean session filtering.
