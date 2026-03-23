# V7 Confirmed Rebreak -- Code Review & Architecture Critique

**Date:** 2026-03-12
**Reviewer:** Cascade (AI pair programmer)
**Scope:** All files in `v7_confirmed_rebreak/`
**Reference:** `ARCHITECTURE.md` (Ousterhout deep-module design), `SESSION_HANDOVER_2026-03-12_1136.md`

---

## 1. Executive Summary

The V7 codebase started with a clean Ousterhout deep-module architecture
(core/, strategy/, execution/) but then grew a parallel implementation
(engine_v2.py, live_engine.py) that **bypasses and duplicates** the deep
modules entirely. The result is two divergent codepaths for the same strategy
logic, violating the core architectural principles the project set out to follow.

**Verdict: The architecture is split. The "clean" half is unused in production.
The "production" half is a monolith.**

---

## 2. What Was Done Right

### 2.1 Original Core Modules (Grade: A)

The original `core/` package is genuinely well-designed:

- **`PivotTracker`** -- Deep module. Clean interface (`update(bar)`,
  `current_pivot_high`, `current_pivot_low`). Hides deque management,
  confirmation logic, change detection. 102 lines. Excellent.

- **`ImbalanceClassifier`** -- Deep module. Clean interface (`add_bar`,
  `get_buy_ratio`, `is_divergent`, `is_matching`). Hides quality filter,
  direction-aware classification. 96 lines. Excellent.

- **`PatternDetector`** -- Deep module. Single interface `process_bar(bar) ->
  List[RebreakSignal]`. Hides the full state machine (pending breaks,
  pending rebreaks, delayed imbalance assessment, pivot state). 335 lines
  of well-organized internal complexity. This is textbook Ousterhout.

- **`RebreakStrategy`** -- Pure state machine. No Pandas, no file I/O.
  Receives signals, issues commands to ExecutionEngine. 154 lines.

- **`SimExecutionEngine`** -- Implements ExecutionEngine ABC. Clean spread
  modeling, SL/TP checking. 138 lines.

- **`market_types.py`** -- Frozen dataclasses (Bar, RebreakSignal, Fill,
  TradeRecord). Immutable value objects. Clean.

- **`interfaces.py`** -- ABC for ExecutionEngine. Enables backtest/live
  polymorphism. 37 lines.

- **`strategy_config.py`** -- Frozen dataclass. No file paths, no broker
  settings. Pure strategy parameters. Clean.

### 2.2 Directory Layout

```
v7_confirmed_rebreak/
  config/          -- strategy parameters
  core/            -- deep modules (pivot, imbalance, pattern)
  strategy/        -- pure state machine
  execution/       -- sim executor (backtest fills)
  backtest/        -- runners, sweeps, walk-forward
  live/            -- IBKR connectivity, live engine
  research/        -- diagnostic scripts
```

This is clean and well-organized. Each directory has a clear responsibility.

### 2.3 Walk-Forward Validation

`walk_forward.py` is well-structured: loads data once, slices per window,
reports edge decay analysis, auto-runs multi-instrument test. The `WindowResult`
dataclass is a nice touch.

---

## 3. Critical Problems

### 3.1 TWO DIVERGENT IMPLEMENTATIONS (Severity: HIGH)

This is the central problem. The codebase has **two completely separate
implementations** of the same strategy logic:

**Path A (Original, Ousterhout-compliant):**
```
engine.py (BacktestRunner)
  -> PatternDetector.process_bar(bar)
  -> RebreakStrategy.on_bar(bar, detector, execution)
  -> SimExecutionEngine.process_bar(bar)
```

**Path B (Production, monolithic):**
```
engine_v2.py (BacktestEngineV2.run)
  -> Inline pattern detection in a 170-line for-loop
  -> Inline trade management
  -> Inline PnL computation
```

**Path C (Live, also monolithic):**
```
live_engine.py (LiveEngine.on_bar)
  -> RollingBuffer.compute_pivots (re-implemented)
  -> _detect_long_pattern / _detect_short_pattern (re-implemented)
  -> _check_exit (re-implemented)
```

The ARCHITECTURE.md promises:
> "Backtest/live parity by construction. The strategy code runs identically
> in both environments."

**This promise is broken.** There are now THREE separate implementations of
the pattern detection logic:
1. `PatternDetector` in `core/pattern_detector.py` (unused in production)
2. Inline in `engine_v2.py` lines 273-337 (used for backtest)
3. `_detect_long_pattern` / `_detect_short_pattern` in `live_engine.py`
   lines 284-402 (used for live)

If a bug is found in one, the other two must be manually synchronized.
This is the exact problem deep modules are designed to prevent.

### 3.2 DUPLICATE TYPE DEFINITIONS (Severity: MEDIUM)

The codebase defines `Bar` THREE TIMES:

1. `core/market_types.py:Bar` -- frozen dataclass, has `buy_ratio` property
2. `live/live_engine.py:Bar` -- mutable dataclass, different field order
3. (Implicit) `engine_v2.py` uses raw numpy arrays, no Bar objects at all

Similarly, `TradeRecord` is defined TWICE:
1. `core/market_types.py:TradeRecord` -- has `tp_price`, `buy_ratio_at_entry`
2. `backtest/engine_v2.py:TradeRecord` -- has `buy_ratio`, `gap` instead

These divergent types mean code cannot be shared between paths.

### 3.3 LIVE ENGINE BYPASSES ALL DEEP MODULES (Severity: HIGH)

`live_engine.py` does not use:
- `PivotTracker` -- reimplements pivot computation in `RollingBuffer.compute_pivots`
- `ImbalanceClassifier` -- reimplements buy_ratio in `_get_buy_ratio`
- `PatternDetector` -- reimplements the full state machine inline
- `ExecutionEngine` ABC -- no polymorphism, just raw dicts
- `RebreakStrategy` -- reimplements trade management inline

The live engine is a 522-line monolith that duplicates ~600 lines of
carefully-designed deep modules. It returns raw `dict` signals instead
of typed `RebreakSignal` objects.

### 3.4 LIVE CONFIG DUPLICATES STRATEGY CONFIG (Severity: MEDIUM)

`live_config.py` contains strategy parameters (`pivot_window`, `confirm_bars`,
`max_hold_bars`, `sl_atr_multiple`, `min_bar_ticks`, `spread_cost`) that
duplicate `strategy_config.py`. The `V7LiveTrader` creates a `StrategyConfig`
from `LiveConfig` values in `run_live.py:401-410`, which is error-prone --
any new parameter must be added in TWO places.

---

## 4. Medium Issues

### 4.1 Performance: get_arrays() Called Every Bar

`RollingBuffer.get_arrays()` creates 7 new numpy arrays from Python lists
on EVERY call to `on_bar()`. With 500 bars and 1-second polling, this is
~500 * 7 = 3,500 array allocations per bar. `compute_pivots()` then calls
`get_arrays()` again, doubling the allocations.

Fix: cache arrays and only rebuild when buffer changes, or maintain numpy
arrays incrementally.

### 4.2 Pivots Recomputed From Scratch Every Bar

`RollingBuffer.compute_pivots()` does a full `pd.Series.rolling().max()`
over 500 bars every single bar. In the backtest this is done once over the
full dataset. In live, it's done every 60 seconds. This is wasteful but
not catastrophic at 1-min resolution.

### 4.3 `import math` Inside Method Bodies

`imbalance_classifier.py` has `import math` inside three method bodies
(lines 64, 78, 89). Imports should be at module level.

### 4.4 `print()` Used Instead of Logger

`engine_v2.py` and `walk_forward.py` use `print()` for output instead of
the logging framework. The `run()` method prints progress directly. This
makes it impossible to suppress output when called programmatically (the
walk_forward script resorts to `contextlib.redirect_stdout` as a workaround).

### 4.5 Hardcoded Data Path

`DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")` is hardcoded in three files:
- `run_backtest.py:18`
- `run_backtest_v2.py:19`
- `walk_forward.py:31`

Should be in config or derived from project root.

### 4.6 No Tests

Zero unit tests. For a trading strategy where correctness is critical, this
is a significant gap. At minimum:
- `PivotTracker` should have tests for known pivot sequences
- `ImbalanceClassifier` should have tests for edge cases (zero volume, etc.)
- `PatternDetector` should have a synthetic bar sequence that triggers a signal
- Entry/exit PnL computation should be tested against manual calculation

### 4.7 Dead/Superseded Code Still Present

- `backtest/engine.py` (BacktestRunner using deep modules) is superseded by
  `engine_v2.py` but still present and importable
- `backtest/run_backtest.py` is superseded by `run_backtest_v2.py`
- `backtest/sweep_params.py` and `sweep_sl.py` reference the old engine
- Multiple research scripts in `research/` may be stale

This creates confusion about which code is "real".

---

## 5. Minor Issues

### 5.1 Spread Applied Inconsistently

- `engine_v2.py` applies spread at EXIT only (lines 222-224, 242-245)
- `live_engine.py` applies spread at both ENTRY and EXIT (lines 445-448, 487-490)
- `sim_executor.py` applies half-spread at entry AND half at exit (lines 34-37, 47-51)

This means backtest V2 and live will compute different PnLs for the same trade.

### 5.2 Signal Dict vs Typed Object

`engine_v2.py` uses tuples for signals (line 302):
```python
signal = ("long", eidx, closes[eidx], h_level, br, gap)
```

`live_engine.py` uses dicts (line 329):
```python
signal = {'direction': 'long', 'entry_idx': eidx, ...}
```

The original architecture uses `RebreakSignal` dataclass. Three representations
for the same concept.

### 5.3 Missing `hold_bars` in Trade Log

`run_live.py` TRADE_FIELDS includes `hold_bars` (line 85) but `_handle_exit`
never sets it in the log_row dict (lines 579-591).

### 5.4 SL Order Race Condition

In `run_live.py:_handle_exit`, if exit reason is 'SL', we skip closing the
position (line 607: `if reason != 'SL'`), assuming the SL stop order handles
it. But `_check_exit` in `live_engine.py` fires based on bar.high/low
touching the SL level -- the actual IBKR stop order might not have filled yet,
or might fill at a different price. There's no verification that the stop
order actually executed.

### 5.5 Buffer Seeding Buy/Sell Split

Historical bars from IBKR are MIDPOINT bars with no buy/sell volume split.
The seeding code (run_live.py:450-451) splits volume 50/50:
```python
buy_volume=row.get('volume', 0) / 2,
sell_volume=row.get('volume', 0) / 2,
```
This means the first ~imb_w bars after transition to real-time will have
contaminated buy_ratio values (mixing 50/50 historical with real uptick/downtick
data).

---

## 6. Architecture Scorecard

| Principle | Score | Notes |
|-----------|-------|-------|
| Deep modules, simple interfaces | **B-** | Core modules are excellent, but bypassed by production code |
| Strategy as pure state machine | **D** | Three separate implementations, none are "pure" |
| Backtest/live parity by construction | **F** | Three divergent codepaths, different spread logic |
| Information hiding | **B** | Core modules hide well; engine_v2 and live_engine expose everything |
| Single source of truth | **D** | Duplicate types, duplicate config, duplicate logic |
| Testability | **F** | Zero tests |
| No dead code | **C** | Superseded engine.py, old sweeps still present |

---

## 7. Recommended Fixes (Priority Order)

### P0: Unify Pattern Detection (eliminate divergence)

Either:
- **Option A:** Make `PatternDetector` work for both backtest and live by
  adding the delayed-processing mode (process bar at n-1-imb_w). Then both
  `engine_v2.py` and `live_engine.py` call `PatternDetector.process_bar()`.
- **Option B:** Accept engine_v2's inline loop for backtest speed, but make
  `live_engine.py` use `PatternDetector` + `RebreakStrategy` for live.
  Only one codebase to maintain for live trading correctness.

### P1: Unify Types

- Delete `live/live_engine.py:Bar` and use `core/market_types.py:Bar`
- Delete `backtest/engine_v2.py:TradeRecord` and use `core/market_types.py:TradeRecord`
  (add missing fields if needed)

### P1: Fix Spread Inconsistency

Choose one spread model and apply it consistently across engine_v2.py,
live_engine.py, and sim_executor.py.

### P2: Add Core Unit Tests

- Test `PivotTracker` with known sequences
- Test `PatternDetector` end-to-end with synthetic bars
- Test spread/PnL computation against manual calculation

### P2: Remove Dead Code

- Archive `backtest/engine.py`, `run_backtest.py`, `sweep_params.py`, `sweep_sl.py`
- Or clearly mark them as "V1 reference only"

### P3: Performance

- Cache numpy arrays in `RollingBuffer`
- Incremental pivot computation for live

---

## 8. Summary

**The good:** The original core modules (PivotTracker, ImbalanceClassifier,
PatternDetector, RebreakStrategy, SimExecutionEngine) are genuinely
well-designed deep modules with clean interfaces. The directory structure
is logical. The walk-forward validation is solid.

**The bad:** Production code (engine_v2.py for backtest, live_engine.py for
live) bypasses ALL of these modules and reimplements the same logic inline.
This creates three divergent codepaths, three sets of types, and three
places where bugs can hide. The ARCHITECTURE.md's promise of "backtest/live
parity by construction" is not met.

**The root cause:** engine_v2 was created to fix a PnL gap (centered vs
causal pivots). Rather than updating PivotTracker to support centered pivots,
a new monolithic engine was written. Then live_engine was written by porting
engine_v2's inline logic, creating a third copy.

**The fix:** Bring the deep modules up to date with engine_v2's proven logic,
then make both backtest and live call the deep modules. This restores the
architectural promise and eliminates the triple-maintenance burden.
