# Live vs Backtest Parity: Root Cause Analysis & Action Plan
**Date:** February 21, 2026  
**Status:** Extended warmup showed NO improvement - fundamental computation path issues confirmed

---

## Executive Summary

**Current Parity:** 69.7% prediction agreement (20/66 bars disagree)  
**DMI+ Divergence:** Mean=5.67%, Max=10.6%  
**Root Cause:** Feature calculation path differences, NOT bar aggregation or warmup

**Key Finding:** Extended warmup from 2026-02-15 (vs 2026-02-17) had **ZERO** impact on parity, eliminating adaptive indicator convergence as the root cause. 30m OHLC bars are identical between live/replay, but DMI+ calculations diverge significantly.

---

## Confirmed NOT Root Causes (Already Eliminated)

1. ✅ **Timestamp bucketing** - Fixed via unified ts_event convention
2. ✅ **30m aggregation method** - Fixed via deterministic incremental bucketing
3. ✅ **MAMA/FAMA warmup convergence** - Tested with 5+ days warmup, no change
4. ✅ **Live process restart contamination** - Session filtering showed no improvement
5. ✅ **30m bar OHLC composition** - Verified identical timestamps and OHLC values

---

## Suspected Root Causes (Computational Path Differences)

### 1. **MAMA/FAMA Historical State Divergence**

**Hypothesis:** MAMA/FAMA adaptive indicators evolve differently in live vs backtest due to different historical bar sequences or double-delivery handling.

**Evidence:**
- DMI+ depends on MAMA/FAMA-derived features
- MAMA/FAMA are adaptive with memory (not stateless)
- Backtest double-delivers bars (NautilusTrader behavior)
- Live delivers each bar exactly once

**Mechanism:**
```python
# Current implementation
self.features_15m.loc[bar.ts_event, 'mama'] = mama_val
# If backtest delivers bar twice, does this overwrite with same value? Or recalculate?
```

**Tests to Run:**
1. Add before/after logging for bar delivery (log when bar enters `on_bar()`)
2. Count bar delivery: live=1x per bar, backtest=2x per bar?
3. Add MAMA/FAMA calculation logging to detect if double-delivery triggers recomputation
4. Export full `features_15m` DataFrame at comparison window start and diff live vs backtest

**Fix if Confirmed:**
- Make feature updates **idempotent** - detect duplicate bars and skip recalculation
- OR normalize backtest to deliver bars once (modify runner logic)

---

### 2. **DMI Calculation Input Feature Drift**

**Hypothesis:** DMI+ is calculated from 30m bars, but the input features (ATR, directional movement) may reference different historical windows in live vs backtest.

**Evidence:**
- DMI+ uses 14-period ADX calculation
- Every single 30m bar shows DMI+ divergence (no alignment even once)
- Mean divergence = 5.67% (systematic, not random)

**Mechanism:**
```python
# DMI+ calculation depends on:
# 1. True Range (TR) over last 14 bars
# 2. Directional Movement (+DM, -DM) over last 14 bars
# 3. Smoothing via ADX
#
# If the 14-bar lookback window differs by even 1 bar,
# DMI+ will diverge due to exponential smoothing
```

**Tests to Run:**
1. Add [DMI_DEBUG] logging:
   - Log +DM, -DM, TR for each 30m bar
   - Log the 14-bar window used for DMI calc
   - Compare live vs replay to find first divergence bar
2. Verify `features_30m` DataFrame has identical rows at comparison window start
3. Check if TA-Lib DMI/ADX maintains internal state (non-reentrant?)

**Fix if Confirmed:**
- Ensure DMI calc uses explicit DataFrame slicing (stateless)
- Avoid TA-Lib stateful functions if used
- Pre-compute DMI in batch (like offline retrain) and cache

---

### 3. **30m Feature DataFrame Construction Order**

**Hypothesis:** The order in which 15m→30m aggregation finalizes vs DMI calculation executes may differ between live and backtest.

**Evidence:**
- `_resample_to_30m()` now returns finalized dict when 30m boundary crosses
- DMI is calculated **after** 30m feature row is added to `features_30m`
- Quarter-hour edge case: when 15m bar close == 30m bar close, which executes first?

**Mechanism:**
```python
# Pseudocode timeline
# 15m bar at 09:30 arrives:
#   - Completes 30m bucket 09:00-09:30
#   - Adds 30m row to features_30m
#   - Calculates DMI on features_30m (including new row)
#
# BUT: does backtest add the 30m row before or after DMI calculation?
# Possible timing race if bar processing order varies
```

**Tests to Run:**
1. Add detailed execution order logging:
   ```python
   self.log.info(f"[EXEC_ORDER] Bar {ts} | Step: 30m_finalize")
   self.log.info(f"[EXEC_ORDER] Bar {ts} | Step: add_30m_row")
   self.log.info(f"[EXEC_ORDER] Bar {ts} | Step: calc_dmi")
   ```
2. Compare exec order logs for same 15m bars between live and backtest
3. Check if `on_bar()` double-delivery in backtest changes execution order

**Fix if Confirmed:**
- Enforce strict execution order: finalize_30m → update_features → calc_indicators
- Use explicit flags to prevent double-execution on backtest double-delivery

---

### 4. **NautilusTrader Backtest Bar Double-Delivery**

**Hypothesis:** NautilusTrader delivers each historical bar **twice** during backtest (confirmed behavior). This may cause features to be calculated twice with different intermediate states.

**Evidence:**
- Known NautilusTrader backtest behavior (bars delivered 2x)
- Live delivers each bar exactly once
- If feature calc is not idempotent, 2nd delivery can overwrite with different value

**Mechanism:**
```python
# Bar arrives first time:
on_bar(bar):
    mama, fama = calculate_mama_fama(bar)  # Uses current features_15m state
    self.features_15m.loc[bar.ts_event, 'mama'] = mama
    # ... more features calculated

# Bar arrives SECOND time (backtest only):
on_bar(bar):  # Same bar, different features_15m state now!
    mama, fama = calculate_mama_fama(bar)  # Different result due to state change
    self.features_15m.loc[bar.ts_event, 'mama'] = mama  # Overwrites!
```

**Tests to Run:**
1. Add delivery counter:
   ```python
   if bar.ts_event not in self._bar_delivery_count:
       self._bar_delivery_count[bar.ts_event] = 0
   self._bar_delivery_count[bar.ts_event] += 1
   if self._bar_delivery_count[bar.ts_event] > 1:
       self.log.warning(f"[DOUBLE_DELIVERY] {bar.ts_event} delivered {count} times")
   ```
2. Log feature values on first vs second delivery
3. Export `features_15m` after warmup and compare row-by-row with live

**Fix if Confirmed:**
```python
# Option 1: Skip second delivery
if bar.ts_event in self._processed_bars:
    return  # Already processed, skip
self._processed_bars.add(bar.ts_event)

# Option 2: Make calculations pure (no DataFrame mutation during calc)
features = calculate_all_features(bar, self.features_15m.copy())
self.features_15m.loc[bar.ts_event] = features  # Single atomic update
```

---

### 5. **TA-Lib Function State/Precision Differences**

**Hypothesis:** TA-Lib indicator functions (MAMA, FAMA, ADX, DMI) may have internal state or use different floating-point precision between calls.

**Evidence:**
- TA-Lib is C library with potential internal buffers
- Batch calculation (backtest) vs incremental (live) may differ
- Even small FP rounding differences compound over 14-bar windows

**Mechanism:**
```python
# TA-Lib MAMA is adaptive (memory-dependent)
mama, fama = talib.MAMA(close_prices, fastlimit=0.5, slowlimit=0.05)
# If close_prices array differs by even 1 ULP (unit last place),
# MAMA output can diverge significantly due to exponential weighting
```

**Tests to Run:**
1. Log raw inputs to TA-Lib functions:
   - Full `close_prices` array passed to MAMA
   - Full 30m OHLC arrays passed to DMI
2. Verify inputs are bitwise identical between live and backtest
3. Test TA-Lib determinism:
   ```python
   # Call twice with same input, verify same output
   result1 = talib.MAMA(close_arr, ...)
   result2 = talib.MAMA(close_arr, ...)
   assert np.allclose(result1, result2)
   ```

**Fix if Confirmed:**
- Replace TA-Lib with numba/numpy pure implementations (fully deterministic)
- OR cache TA-Lib inputs and verify them before each call
- OR pre-compute all indicators offline and load as static data

---

### 6. **Feature DataFrame Indexing/Sorting**

**Hypothesis:** Pandas DataFrame row ordering or index alignment issues cause features to be retrieved from wrong timestamps.

**Evidence:**
- `features_15m` and `features_30m` are indexed by timestamp
- If index is not sorted, `.loc[]` lookups may return wrong rows
- `.tail(N)` may return different rows if DataFrame is unsorted

**Mechanism:**
```python
# If features_15m is not sorted by index:
df_15m = self.features_15m.tail(30)  # Last 30 rows by insertion order
# Should be last 30 by timestamp order!
```

**Tests to Run:**
1. Add DataFrame validation after each update:
   ```python
   assert self.features_15m.index.is_monotonic_increasing
   assert self.features_30m.index.is_monotonic_increasing
   ```
2. Log DataFrame shape and index range after each bar
3. Export full DataFrame and verify row order matches timestamp order

**Fix if Confirmed:**
```python
# After each update, ensure sorted
self.features_15m = self.features_15m.sort_index()
self.features_30m = self.features_30m.sort_index()

# Or use explicit sort before windowing
df_15m = self.features_15m.sort_index().tail(30)
```

---

## Systematic Testing Plan

### Phase 1: Bar Delivery Audit (Week 1)

**Goal:** Confirm double-delivery behavior and quantify impact

**Actions:**
1. Add bar delivery counter to strategy:
   ```python
   self._bar_delivery_log = []
   def on_bar(self, bar):
       self._bar_delivery_log.append((bar.ts_event, 'entry'))
       # ... existing logic
   ```
2. Run 3-day backtest and analyze delivery counts
3. Run live for 1 day and compare delivery counts
4. **Expected Outcome:** Backtest=2x, Live=1x per bar

**Success Criteria:** Confirm double-delivery, quantify % of bars affected

---

### Phase 2: Feature State Snapshot Comparison (Week 2)

**Goal:** Identify exact bar where features first diverge

**Actions:**
1. Export `features_15m` and `features_30m` at comparison window start:
   ```python
   if bar.ts_event == datetime(2026, 2, 20, 5, 15, tzinfo=timezone.utc):
       self.features_15m.to_csv('features_15m_snapshot.csv')
       self.features_30m.to_csv('features_30m_snapshot.csv')
   ```
2. Run live and backtest with exports
3. Diff CSVs row-by-row and column-by-column
4. Find first diverging timestamp and feature column

**Success Criteria:** Pinpoint exact bar and feature where divergence starts

---

### Phase 3: Indicator Input Logging (Week 2)

**Goal:** Verify TA-Lib inputs are identical

**Actions:**
1. Add [INDICATOR_INPUT] logging:
   ```python
   def calculate_mama(self, close_prices):
       self.log.info(f"[INDICATOR_INPUT] MAMA input length={len(close_prices)} "
                     f"first={close_prices[0]} last={close_prices[-1]} "
                     f"hash={hash(tuple(close_prices))}")
       mama, fama = talib.MAMA(close_prices, ...)
       return mama, fama
   ```
2. Run backtest and capture input hashes
3. Run live and compare hashes for same timestamps
4. If hashes differ, log full array and diff

**Success Criteria:** Confirm if inputs match or identify first differing input

---

### Phase 4: Execution Order Tracing (Week 3)

**Goal:** Verify bar processing order is identical

**Actions:**
1. Add fine-grained execution tracing:
   ```python
   self._exec_trace = []
   def on_bar(self, bar):
       self._trace('on_bar_entry', bar.ts_event)
       # ... calculate features
       self._trace('features_calculated', bar.ts_event)
       # ... finalize 30m
       self._trace('30m_finalized', bar.ts_event)
       # ... calc DMI
       self._trace('dmi_calculated', bar.ts_event)
   ```
2. Export execution trace to log
3. Compare traces between live and backtest for same timestamp sequence

**Success Criteria:** Identify any out-of-order execution or missing steps

---

### Phase 5: Idempotency Implementation (Week 3-4)

**Goal:** Make bar processing idempotent (skip double-delivery)

**Actions:**
1. Add processed bar tracking:
   ```python
   if bar.ts_event in self._processed_bars:
       self.log.debug(f"[SKIP_DUPLICATE] Already processed {bar.ts_event}")
       return
   self._processed_bars.add(bar.ts_event)
   ```
2. Run backtest and verify each bar processed exactly once
3. Re-run parity comparison
4. **Expected Outcome:** 90%+ prediction agreement

**Success Criteria:** Parity improves to >90% after idempotency

---

### Phase 6: TA-Lib Replacement (If Needed, Week 5-6)

**Goal:** Replace TA-Lib with deterministic pure Python implementations

**Actions:**
1. Implement MAMA/FAMA in numba:
   ```python
   @numba.jit
   def mama_fama(close, fast=0.5, slow=0.05):
       # Pure implementation with explicit state
       ...
   ```
2. Implement DMI/ADX in numpy (stateless)
3. Run backtest with new implementations
4. Compare outputs with TA-Lib version (should be <0.01% diff)
5. Re-run parity comparison

**Success Criteria:** 95%+ prediction agreement with deterministic indicators

---

## Implementation Priority

### Critical Path (Must Fix)

1. **Bar Double-Delivery Idempotency** (Phase 5)
   - **Impact:** HIGH - likely primary cause
   - **Effort:** LOW - simple guard clause   
   - **Risk:** LOW - just skip duplicates

2. **Feature State Snapshot Diff** (Phase 2)
   - **Impact:** HIGH - diagnostic gold standard
   - **Effort:** LOW - just export CSVs
   - **Risk:** NONE - read-only

3. **Execution Order Tracing** (Phase 4)
   - **Impact:** MEDIUM - may reveal timing bugs
   - **Effort:** LOW - add logging
   - **Risk:** NONE - observability only

### Secondary Path (Nice to Have)

4. **TA-Lib Input Validation** (Phase 3)
   - **Impact:** MEDIUM - rules out input divergence
   - **Effort:** LOW - hash logging
   - **Risk:** NONE

5. **DataFrame Index Validation** (Phase 6 item 6)
   - **Impact:** LOW - unlikely but easy to check
   - **Effort:** VERY LOW - assert statements
   - **Risk:** NONE

6. **TA-Lib Replacement** (Phase 6)
   - **Impact:** HIGH - guaranteed determinism
   - **Effort:** HIGH - full reimplementation
   - **Risk:** MEDIUM - potential regression if not careful

---

## Success Metrics

| Metric | Baseline | Target | Stretch Goal |
|--------|----------|--------|--------------|
| Prediction Agreement % | 69.7% | 90% | 95% |
| Exact Match % | 0% | 50% | 75% |
| DMI+ Mean Abs Diff | 0.0567 | <0.01 | <0.001 |
| DMI+ Max Abs Diff | 0.1061 | <0.05 | <0.01 |

---

## Timeline Estimate

- **Phase 1-2:** Week 1 (Feb 21-28, 2026)
- **Phase 3-4:** Week 2 (Mar 1-7, 2026)
- **Phase 5:** Week 3 (Mar 8-14, 2026)
- **Phase 6 (if needed):** Week 4-5 (Mar 15-28, 2026)

**Total:** 4-5 weeks to 95% parity

---

## Next Immediate Actions (This Week)

1. ✅ Implement bar delivery counter (1 hour)
2. ✅ Add feature snapshot export at comparison window start (1 hour)
3. ✅ Run backtest with counters and exports (30 min)
4. ✅ Run live with counters and exports (let run overnight)
5. ✅ Analyze delivery counts and diff feature snapshots (2 hours)
6. ⏳ Implement idempotency guard if double-delivery confirmed (1 hour)
7. ⏳ Re-run parity comparison (30 min)

**Time Investment:** ~6 hours coding + overnight live run
**Expected Result:** Root cause identified and first fix deployed by week-end
