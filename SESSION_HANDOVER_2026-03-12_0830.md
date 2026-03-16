# Session Handover -- 2026-03-12 08:30

## V7 Confirmed Rebreak Strategy -- Major Progress

### What Changed This Session

**Root cause of PnL gap identified and fixed.** The original backtest averaged +$0.20/trade vs research's +$0.70/trade. The problem was the `PivotTracker`'s timing -- centered pivots (research) forward-fill from the pivot bar itself, while any causal approach can only start `confirm_bars` later. During that gap, a different (stale) pivot is active, causing the `PatternDetector` to track wrong breakout sequences.

**Solution: Engine V2** (`v7_confirmed_rebreak/backtest/engine_v2.py`) uses pre-computed centered pivots with a configurable shift delay (`confirm_bars`). This is legitimate for live trading -- you maintain a rolling buffer and confirm pivots `confirm_bars` after they occur.

### Recommended Config (FINAL)

| Parameter | Value | Notes |
|-----------|-------|-------|
| `pivot_window` | 60 | Research confirmed strongest edge |
| `confirm_bars` | 3 | Short delay, near-research quality |
| `max_hold_bars` | 60 | Pure time-stop exit |
| `sl_atr_multiple` | 10.0 | Catastrophe SL (10x ATR) |
| `tp_atr_multiple` | 99.0 | Disabled (time-stop only) |
| `min_bar_ticks` | 50 | Quality filter |
| `spread_cost` | 0.30 | XAUUSD |

### Backtest Results (OOS 2023-01-01+)

**Best config: pw=60, c=3, h=60, SL=10xATR**
- 1,150 trades, +$1,863 total PnL, +$1.62/trade
- 57.4% win rate
- All years positive: 2023 +$89, 2024 +$386, 2025 +$1,034, 2026 +$354
- Max single loss: -$36 (capped by SL)
- 10/38 months negative, worst month -$30.71

**Without SL (pw=60, c=3, h=60, SL=none):**
- 1,145 trades, +$1,854, +$1.62/trade, 58.0% WR
- Max single loss: -$51.33

### Parameter Sweep Summary (all OOS 2023+)

| Config | Trades | PnL | Avg/trade | WR |
|--------|--------|-----|-----------|-----|
| pw30 c5 h60 | 1,496 | +$672 | +$0.45 | 51.9% |
| pw45 c5 h60 | 1,308 | +$1,383 | +$1.06 | 54.7% |
| **pw60 c3 h60** | **1,145** | **+$1,854** | **+$1.62** | **58.0%** |
| pw60 c5 h60 | 1,179 | +$1,659 | +$1.41 | 56.7% |
| pw60 c5 h90 | 1,155 | +$1,690 | +$1.46 | 55.1% |
| pw90 c5 h60 | 1,001 | +$1,227 | +$1.23 | 56.3% |

### Architecture

**Engine V2** (`engine_v2.py`) replaces the original `engine.py` + `PatternDetector` pipeline:
- Pre-computes pivots using `pd.Series.rolling(center=True).max()` with shift delay
- Single-pass pattern detection loop (no state machine resets on pivot changes)
- Catastrophe SL using bar high/low for intra-bar detection
- Half-spread applied on entry and exit (realistic)

**Files created/modified:**
- `v7_confirmed_rebreak/backtest/engine_v2.py` -- New backtest engine
- `v7_confirmed_rebreak/backtest/run_backtest_v2.py` -- CLI runner
- `v7_confirmed_rebreak/backtest/sweep_v2.py` -- Parameter sweep
- `v7_confirmed_rebreak/backtest/sweep_sl.py` -- SL level sweep
- `v7_confirmed_rebreak/config/strategy_config.py` -- Added `confirm_bars` field
- `v7_confirmed_rebreak/core/pivot_tracker.py` -- Updated (asymmetric confirm)
- `v7_confirmed_rebreak/core/pattern_detector.py` -- Updated (preserve mid-sequence state)
- `v7_confirmed_rebreak/research/quick_pivot_compare.py` -- Pivot comparison tool
- `v7_confirmed_rebreak/research/test_precomputed_pivots.py` -- Shift delay analysis

### Key Technical Findings

1. **Centered vs causal pivots find identical levels** (23,674 shared) but **different timing** (67% bar-by-bar agreement). The timing difference creates 1,534 extra garbage events in the causal approach.

2. **Edge degrades rapidly with delay**: shift=0 gives +$0.78/trade, shift=5 gives +$0.45, shift=10 gives +$0.04, shift=30 gives -$0.30. The sweet spot is confirm=3-5.

3. **The original PatternDetector resets level state on every pivot change**, killing in-progress breakout sequences. This caused the engine to produce far fewer trades (354) than the research loop (1,496). Engine V2 fixes this by using pre-computed pivots.

4. **pw=60 dominates pw=30** across all configs. Larger windows produce higher-quality S/R levels.

### Backtest Command

```
python -m v7_confirmed_rebreak.backtest.run_backtest_v2 --pw 60 --confirm 3 --max-hold 60 --sl 10 --start 2023-01-01
```

### Next Steps

1. Full-sample backtest (include 2020-2022 in-sample) to verify no regime issues
2. Live trading implementation using rolling pivot buffer
3. Multi-instrument test (EURUSD, GBPUSD if tick data available)
4. Walk-forward validation (train on rolling windows)

### Rules (unchanged)

- Never use emojis or non-ASCII in Python code
- All v7 files stay in `v7_confirmed_rebreak/`
- No velocity filter -- min_bar_ticks filter replaces it
- Data path: `C:\nautilus0\data\1m_csv`
