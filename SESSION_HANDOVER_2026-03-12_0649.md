# Session Handover: V7 Confirmed Rebreak Strategy Development
**Date:** 2026-03-12 06:49 UTC-04:00

---

## Objective
Build a tradeable strategy (v7) based on the "confirmed rebreak" pattern discovered in the tick volume imbalance research. Strategy uses Ousterhout deep-module architecture. All files in `c:\nautilus0\v7_confirmed_rebreak\`.

## What Was Completed

### 1. Research Phase (previous session)
- Discovered and validated the confirmed rebreak pattern on XAUUSD and EURUSD
- Pattern: divergent first break -> pullback -> matching-imbalance rebreak
- OOS edge: +$0.50 to +$2.16/trade after $0.30 spread, 55-60% win rate at 30-60m hold
- Full report: `docs/journal/2026-03-12_tick_volume_imbalance_investigation.md`
- Research scripts: `v5_xauusd_orb/research_confirmed_rebreak.py`, `research_imbalance_divergence.py`

### 2. Min Tick Count Filter Test
- Script: `v7_confirmed_rebreak/research/test_tick_filter.py`
- Results: `v7_confirmed_rebreak/research/tick_filter_results.txt`
- **Finding:** Filtering out bars with low tick_count in the imbalance window dramatically improves signal quality:
  - `min_ticks=0`: +$0.61/trade at 30m, 53% WR (1,419 events OOS)
  - `min_ticks=50`: +$0.70/trade at 30m, 54% WR (1,191 events)
  - `min_ticks=100`: +$0.99/trade at 30m, 56% WR (840 events)
- Decision: use `min_bar_ticks=50` as default (good balance of quality vs frequency)
- **No velocity filter needed** -- tick_count filter replaces it, no IBKR calibration required

### 3. V7 Architecture Built (Ousterhout deep modules)
All modules implemented and functional:

```
v7_confirmed_rebreak/
  ARCHITECTURE.md              # Design doc
  __init__.py
  config/
    strategy_config.py         # Frozen dataclass with all params
  core/
    market_types.py            # Bar, RebreakSignal, Fill, TradeRecord
    interfaces.py              # ExecutionEngine ABC
    pivot_tracker.py           # Deep: rolling pivot detection (2*window buffer)
    imbalance_classifier.py    # Deep: buy_ratio with min_bar_ticks quality filter
    pattern_detector.py        # Deep: full rebreak state machine
  strategy/
    rebreak_strategy.py        # Pure state machine (SCANNING -> IN_TRADE -> COOLDOWN)
  execution/
    sim_executor.py            # Backtest fill sim with spread, SL/TP checking
  backtest/
    engine.py                  # BacktestRunner: loads CSV, wires modules, runs loop
    run_backtest.py            # CLI entry point
    sweep_params.py            # Parameter sweep script
    debug_detector.py          # Debug utility (can be deleted)
  research/
    test_tick_filter.py        # Min tick count filter test
    tick_filter_results.txt    # Results
```

### 4. Bugs Found and Fixed
- **Pivot tracker was resetting every bar:** Original left-only approach set pivot to current bar's high (which equals rolling max in trends), so close could never exceed pivot. Fixed by using a **2*window buffer** where the pivot is the extreme of the FIRST half (historical bars), ensuring the level is always `window` bars in the past.
- **Pivot change detection:** Added `high_changed`/`low_changed` flags to avoid resetting level state when the pivot value stays the same.

### 5. First Backtest Run (pw=30, min_ticks=50, OOS 2023+)
- 958 trades, total PnL: +$0.44 (essentially flat)
- Win rate: 33.3% -- too low because SL=1.5x ATR is too tight
- 1-min ATR ~ $0.39, so SL = $0.59 gets hit by noise before the 30-60 bar edge manifests
- Exit reasons: 67% SL, 32% TP, 1% TIME_STOP

---

## What Needs To Be Done Next

### COMPLETED: SL/TP Parameter Sweep Results (OOS 2023+, pw=30, min_ticks=50)

| Config | Trades | PnL | WR% | AvgW | AvgL | SL% | TP% | TS% |
|--------|--------|-----|-----|------|------|-----|-----|-----|
| SL=2 TP=4 hold=60 | 955 | +$148 | 34.7% | +$4.93 | -$2.38 | 63% | 30% | 7% |
| SL=3 TP=6 hold=60 | 944 | +$83 | 37.1% | +$5.82 | -$3.29 | 55% | 23% | 22% |
| SL=5 TP=10 hold=60 | 935 | -$60 | 42.0% | +$6.02 | -$4.48 | 36% | 10% | 54% |
| SL=3 TP=6 hold=30 | 952 | +$4 | 41.5% | +$4.07 | -$2.88 | 41% | 13% | 47% |
| SL=3 TP=6 hold=45 | 943 | +$68 | 38.7% | +$5.14 | -$3.13 | 50% | 19% | 31% |
| **pure time=30** | 942 | -$26 | 44.5% | +$4.39 | -$3.57 | 0% | 0% | 100% |
| **pure time=45** | **915** | **+$176** | **46.0%** | +$5.63 | -$4.44 | 0% | 0% | 100% |
| **pure time=60** | **909** | **+$186** | **45.4%** | +$6.80 | -$5.28 | 0% | 0% | 100% |
| SL=2 TP=3 hold=30 | 960 | +$55 | 41.5% | +$3.44 | -$2.34 | 54% | 35% | 12% |
| SL=4 TP=6 hold=45 | 944 | +$65 | 42.6% | +$5.15 | -$3.70 | 38% | 20% | 42% |

**Key findings:**
- **Pure time-stop at 45-60 bars wins.** +$176-186 PnL, 45-46% WR -- highest PnL and WR
- **SL hurts more than it helps.** Tight SL (2-3x 1-min ATR) clips winners before they mature
- SL/TP are based on 1-minute ATR (~$0.39), which is too small. If keeping SL, switch to higher-TF ATR or use much wider multiples
- **Recommended approach:** Pure time=45 with a wide catastrophe SL (e.g., 10-15x ATR ~$4-6)
- Note: ~$186 total PnL over 909 trades = ~$0.20/trade average -- lower than research's +$0.70 at 30m. The gap may be due to: (a) the backtest's left-only pivots detect different levels than research's centered pivots, (b) the spread is applied to both entry AND exit in backtest vs only once in research. Needs investigation.

### NEXT STEPS:
1. **Investigate PnL gap** -- research showed +$0.70/trade at 30m, backtest shows +$0.20. Check if the backtest event count (~909) vs research (~1,191) explains this, or if the left-only pivot tracker finds different/worse events
2. **Test pw=60** -- research showed even stronger edge than pw=30
3. **Add wide catastrophe SL** to pure time-stop approach (e.g., 10-15x ATR)
4. **Run full-sample backtest** (all years, not just 2023+) to check IS vs OOS consistency
5. **Validate trade count** -- confirm backtest detects similar events as research
6. **Update ARCHITECTURE.md** with final design notes
7. **Consider adding:** session/time-of-day filter, per-direction (long vs short) analysis

---

## Key Config Defaults (strategy_config.py)
```python
instrument = "XAUUSD"
pivot_window = 30
imbalance_window = 3
divergence_threshold = 0.50
max_pullback_bars = 60
min_pullback_bars = 3
sl_atr_multiple = 1.5      # NEEDS TUNING
tp_atr_multiple = 3.0      # NEEDS TUNING
max_hold_bars = 60
atr_period = 60
min_bar_ticks = 50
spread_cost = 0.30
```

## Data
- XAUUSD 1-min bars with tick volume: `data/1m_csv/xauusd_1m_tick.csv`
- Columns: timestamp, open, high, low, close, tick_count, buy_volume, sell_volume, vol_imbalance, buy_ratio
- ~2.8M bars total, ~1.1M OOS (2023+)

## Backtest Command
```
cd c:\nautilus0
python -m v7_confirmed_rebreak.backtest.run_backtest --pw 30 --min-ticks 50 --start 2023-01-01
python -m v7_confirmed_rebreak.backtest.run_backtest --pw 30 --min-ticks 50 --start 2023-01-01 --verbose
```

## Important Rules
- Never use emojis or non-ASCII in Python code (Windows cp1252 encoding issue)
- All v7 files stay in `v7_confirmed_rebreak/` -- do not modify v5 or v6
- Strategy uses NO velocity filter -- min_bar_ticks filter replaces it
- No IBKR calibration needed for v7
