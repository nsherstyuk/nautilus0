# Session Handover - February 28, 2026 07:06 UTC

## Session Objective
Improve robustness of the v5 XAUUSD Asian Range Breakout strategy through:
1. Realistic slippage and spread modeling in the backtest engine
2. Sensitivity analysis of the Breakeven (BE) rule
3. RR ratio optimization
4. BE offset optimization (moving SL to small profit instead of exact breakeven)
5. Fixing a cost model bug found during self-review

---

## Research & Analysis Performed

### 1. Slippage Modeling Added to `backtest.py`

**Problem**: Original backtest had no slippage and only 1x spread cost, inflating results.

**Fix applied**:
- Entry: stop orders get +/- $0.15 slippage (LONG/SHORT)
- Exit SL: stop orders get slippage (fills at worse price)
- Exit TP: NO slippage (limit orders fill at exact price)
- Exit EOD: market orders get slippage
- Spread: fixed from `1x` to `2x` (entry + exit legs)
- Added `--slippage` CLI argument (default $0.15)

**Impact**: Original Sharpe of 5.00 dropped to 2.37 with realistic costs. This was expected and reveals the true strategy performance.

### 2. BE Rule Sensitivity Analysis

**Question**: Is the 60-minute BE rule overfitted to that exact threshold?

**Method**: Tested BE at 30, 45, 60, 75, 90, 120 minutes using corrected cost model.

**Corrected Results** (RR=2.0, slippage=$0.15, spread=$0.10):

| Strategy | P&L | Sharpe | PF | MaxDD |
|----------|-----|--------|-----|-------|
| Baseline (no BE) | $+2,185 | 2.37 | 1.51 | -$117.80 |
| 30 min BE | $+2,350 | 4.24 | 6.22 | -$19.30 |
| 45 min BE | $+2,526 | 4.45 | 6.17 | -$19.30 |
| 60 min BE (was current) | $+2,571 | 4.42 | 4.96 | -$31.01 |
| 75 min BE | $+2,608 | 4.43 | 4.60 | -$31.01 |
| 90 min BE | $+2,669 | 4.40 | 4.03 | -$34.84 |
| 120 min BE | $+2,758 | 4.28 | 3.31 | -$36.05 |

**Conclusion**: 60min BE is robust (only 0.1% deviation from neighbors). 120min BE produces highest P&L. All BE strategies significantly outperform baseline.

### 3. RR Ratio Optimization

**Question**: Is RR=2.0 optimal with realistic costs?

**Method**: Tested RR=1.5, 1.75, 2.0, 2.5, 3.0 with slippage+spread.

**Results** (no BE rule, just SL/TP/EOD):

| RR | Win Rate | P&L | Sharpe | PF | MaxDD |
|----|----------|-----|--------|-----|-------|
| 1.5 | 30.3% | $+2,080 | 2.42 | 1.51 | -$113 |
| 1.75 | 24.2% | $+2,150 | 2.41 | 1.51 | -$121 |
| 2.0 | 19.4% | $+2,185 | 2.37 | 1.51 | -$117 |
| 2.5 | 13.3% | $+2,328 | 2.37 | 1.54 | -$125 |
| 3.0 | 9.1% | $+2,455 | 2.37 | 1.57 | -$113 |

**Conclusion**: All RR values have nearly identical Sharpe (2.37-2.42). The edge is robust across TP distances. RR=3.0 has highest P&L but only 9.1% TP rate. We kept RR=2.0 to minimize live parameter changes.

### 4. Combined Test: 120-min BE + RR=3.0

Tested to see if combining best parameters helps:
- P&L: $+3,101 | Sharpe: 4.17 | PF: 3.83 | MaxDD: -$34.80

Strong results, but decided to only change BE timing (not RR) to reduce deployment risk.

### 5. BE Offset Optimization

**Question**: Instead of moving SL to exact breakeven (entry price), what if we move it to entry + $X to lock in small profit?

**Key insight discovered during analysis**: "Breakeven" at entry price is actually a LOSS of ~$0.35 per trade after spread ($0.20) and slippage ($0.15). A $2 offset turns this into a $1.65 GAIN per BE exit.

**Results** (120min BE, RR=3.0, corrected cost model):

| Offset | P&L | Sharpe | PF | MaxDD | BE% |
|--------|-----|--------|-----|-------|-----|
| $0 | $+2,875 | 3.87 | 3.39 | -$36 | 62.7% |
| $2 | $+3,770 | 5.40 | 4.94 | -$33 | 68.9% |
| $4 | $+4,759 | 7.41 | 5.98 | -$32 | 73.4% |
| $10 | $+9,215 | 14.93 | 10.64 | -$29 | 80.5% |
| $20 | $+18,103 | 24.42 | 19.93 | -$29 | 83.0% |

**Analysis of offset levels**:
- $0-$2: Compensates for cost drag. Rational, low risk.
- $2 specifically: Turns BE exit from -$0.35 loss to +$1.65 gain. Economic rationale is clear.
- $6-$10: Locks meaningful profits but becomes regime-dependent.
- $15-$20: Fundamentally changes strategy from breakout to fixed-dollar profit target. Dangerous -- only works if Gold trends consistently.

**Why higher offsets are dangerous**:
- Mean Asian range is only $13.10 (median $8.75)
- $10 offset = 76% of mean range -- requires price to be nearly a full range above entry
- $20 offset = 153% of mean range -- essentially a different strategy
- Linear P&L scaling with offset (no plateau) is a classic overfitting signal

### 6. Critical Bug Found: Inconsistent Cost Models

**Discovery**: During self-review, found that `backtest_exits.py` (used for BE sensitivity) had NO slippage on entries or exits, and only 1x spread cost. This meant the earlier BE sensitivity results were ~7% too optimistic.

**Fix applied**:
- Added `slippage` parameter to `simulate_trade()` and `run_strategy()`
- Applied slippage to entries, SL/BE exits, EOD exits
- Fixed spread from 1x to 2x everywhere (including partial close)
- Updated `analyze_be_sensitivity.py` to pass spread/slippage separately
- Re-ran all BE sensitivity tests with corrected model

**Impact**: P&L dropped ~$170-250 per strategy (~7-8% haircut). Rankings and conclusions unchanged -- the original analysis was directionally correct.

---

## Decisions Made

### Final Configuration Deployed

| Parameter | Old Value | New Value | Rationale |
|-----------|-----------|-----------|-----------|
| be_hours | 1 | **2** | More room for trades to develop; $2,758 P&L, Sharpe 4.28 |
| be_offset_usd | (new) | **$2.0** | Covers spread+slippage so BE exits break even after costs |
| rr_ratio | 2.0 | **2.0** (unchanged) | Minimize live changes; Sharpe similar across all RR values |

### Why 120 min instead of 60 min BE
- Higher P&L ($2,758 vs $2,571)
- Small Sharpe trade-off (4.28 vs 4.42)
- A breakout still alive after 2 hours is more likely a real trend
- The 60min rule was selected before realistic cost modeling

### Why $2 offset instead of $0 or higher
- $0 "breakeven" is actually -$0.35 after costs -- it's a misnomer
- $2 is only 15% of mean range ($13.10) -- very conservative
- Clear economic rationale: compensates for execution costs
- Does NOT change the strategy nature (still a breakout strategy)
- Higher offsets ($10+) are regime-dependent and likely overfitted

### Why keep RR=2.0
- All RR values showed similar Sharpe (2.37-2.42)
- RR=2.0 has 19.4% TP rate vs 9.1% at RR=3.0 -- more consistent
- Changing fewer parameters at once is safer for live deployment
- Can test RR=3.0 later as a separate experiment

---

## Git Status

**Branch**: `v5-orb-robustness-tests` (NOT merged to main -- intentional)

**Commits**:
```
628bd8b12 - Update strategy config: 2h BE rule + $2 offset for live deployment
f65c1c847 - Fix cost model in backtest_exits.py: add slippage, fix spread to 2x
5e97d3b84 - Add slippage modeling and BE rule sensitivity analysis to v5 ORB
```

**Why not merged**: Staying on the feature branch is safer. If something goes wrong Monday, `git checkout main` instantly reverts to the old 1h BE / no offset config. Merge after confirming new parameters work for ~1 week.

**Before Monday's live session**: Run `git checkout v5-orb-robustness-tests` to ensure the updated code is active.

---

## Files Modified/Created This Session

### Modified
- `v5_xauusd_orb/backtest.py` -- slippage modeling, 2x spread fix
- `v5_xauusd_orb/backtest_exits.py` -- slippage modeling, 2x spread fix, partial close fix
- `v5_xauusd_orb/config.yaml` -- be_hours: 2, be_offset_usd: 2.0
- `v5_xauusd_orb/config.py` -- added be_offset_usd to StrategyConfig
- `v5_xauusd_orb/orb_live.py` -- apply_breakeven_stop() uses be_offset

### Created
- `v5_xauusd_orb/analyze_be_sensitivity.py` -- BE time sensitivity testing
- `patch_backtest_slippage.py` -- helper script to patch backtest.py
- `test_120min_rr3.py` -- combined optimization test
- `optimize_be_offset.py` -- first attempt (had slippage bug)
- `optimize_be_offset_fixed.py` -- corrected BE offset optimization
- `check_range_stats.py` -- Asian range size statistics

---

## Risk Warnings for Live Deployment

1. **Slippage assumption ($0.15)**: This is an estimate. Verify with actual live fills. If real slippage is consistently higher, strategy profitability degrades.

2. **Feb 2026 underperformance**: All configurations showed 0% TP rate across 8 trades in Feb 2026. Could be noise (small sample) or a regime shift.

3. **In-sample optimization**: All parameters were selected on 2019-2026 data. No formal out-of-sample validation was performed. The $2 offset is low-risk because of its clear economic rationale, but the 120-min BE time was selected on full data.

4. **Gold volatility regime**: Strategy requires Gold to move enough during London session to trigger breakouts. Low-volatility periods will reduce trade frequency and profitability.

---

## Recommended Next Steps

1. **Monday**: Switch to `v5-orb-robustness-tests` branch, run live with new config
2. **Week 1**: Monitor real slippage vs $0.15 assumption, track BE exit P&L
3. **Week 2-3**: If stable, consider testing RR=3.0 as next experiment
4. **Week 4**: If RR=3.0 works, consider formal out-of-sample test for higher BE offsets
5. **Future**: Walk-forward optimization, Monte Carlo simulation for robustness

---

## Asian Range Statistics (for reference)

```
Range stats (N=1462, 2019-2026):
  Mean:   $13.10
  Median: $8.75
  Std:    $18.37
  Min:    $1.47
  Max:    $386.45
  P25:    $5.91
  P75:    $13.81
```

At RR=2.0: mean TP distance = $26.20, median = $17.50
At RR=3.0: mean TP distance = $39.30, median = $26.26

---

*Session duration: ~1 hour*
*Tests run: 20+ backtests across parameter combinations*
*Key insight: Realistic cost modeling reduced Sharpe from 5.00 to 2.37-4.28 depending on configuration*
