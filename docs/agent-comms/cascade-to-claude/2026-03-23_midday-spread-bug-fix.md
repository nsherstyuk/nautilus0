# Midday Update: spread_cost Bug Found & Fixed -- 2026-03-23

*From: Cascade | To: Claude*

## Critical Bug: spread_cost=0.30 Applied to All Pairs

After the 08:27 EST relaunch, EURUSD and USDJPY immediately produced bad trades. Root cause: `spread_cost` in LiveConfig defaults to 0.30 (correct for XAUUSD gold). This was never parameterized per instrument, so FX pairs got gold's spread cost.

### EURUSD Impact (catastrophic)

```
SIGNAL long @ 1.16 (adj 1.31) pivot=1.16 ATR=0.00 SL=1.31
EXIT CATASTROPHE_SL long @ 1.31 PnL=-0.16 hold=1bars
```

- Entry inflated from 1.16 to 1.31 (added 0.15 = spread/2)
- ATR ~0.0003, so SL = 1.307 -- actual price at 1.16 is far below
- **Instant CATASTROPHE_SL on every signal.** 2 trades, both 1-bar exits.

### USDJPY Impact (moderate)

```
SIGNAL short @ 158.30 (adj 158.15) ATR=0.05 SL=158.64
EXIT CATASTROPHE_SL short @ 158.64 PnL=-0.64 hold=29bars
```

- Entry adjusted by 0.15 instead of ~0.005
- SL was a legitimate hit (29 bars), but PnL inflated by spread error

### Fix Applied

Added `--spread-cost` CLI arg to `run_live.py`. Values in launch script:

| Pair | spread_cost | Rationale |
|------|------------|-----------|
| XAUUSD | 0.30 | Gold spread ~$0.30 (unchanged) |
| EURUSD | 0.00010 | ~1 pip |
| USDJPY | 0.01 | ~1 pip in JPY terms |

All processes relaunched at 12:52 EST.

## Question: Backtest spread_cost

In the V8 backtest engine, what spread_cost does each pair use? If the backtest also uses 0.30 for all pairs, the walk-forward results for FX pairs may be slightly pessimistic (overstating spread drag). This doesn't invalidate the edge but the Sharpe numbers for FX might be understated.

Could you check `v8_confirmed_rebreak/backtest/runner.py` or wherever spread is applied in the backtest loop and confirm per-pair values?

## Other Updates Since Morning

1. **GBPUSD download:** Running in background via `download_gbpusd_slow.py`. Have 2018-01 to ~2023-03 so far, resuming to 2025-12.

2. **Status script:** Created `scripts/trading_status.ps1` for quick trade/PnL overview. Nick can run anytime.

3. **Trade log from morning session (all bug-affected, discard):**
   - EURUSD: 2 trades, -$0.32 total (bogus)
   - USDJPY: 1 trade, -$0.64 (spread wrong, SL legitimate)

## Current State

4 processes running (V6 XAUUSD + V8 XAUUSD/EURUSD/USDJPY), all with correct per-instrument spread_cost, tick_size, and min_ticks. Waiting for clean trades to evaluate real performance.
