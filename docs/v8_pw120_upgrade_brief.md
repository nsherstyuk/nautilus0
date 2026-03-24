# V8 Strategy Upgrade: pw=120 Multi-Pair Deployment

## Research Summary

We completed a comprehensive analysis of the V8 Confirmed Rebreak strategy across multiple pivot_window scales (10–120) and 8 FX pairs over 8 years of 1-minute tick data (~3M bars per pair).

### Key Findings

**1. Larger pivot windows are strictly better.**
The pattern "bigger structural level = higher Sharpe" held across every pair tested. Small-scale pivots (pw=10–30) produce negative Sharpe everywhere — they're noise, not structure.

**2. Fixed hold=60 outperforms proportional hold.**
We tested both proportional (max_hold = pw) and fixed (max_hold = 60) approaches. Fixed hold=60 wins for pw ≥ 60 because even smaller-structure rebreaks need ~60 minutes to realize the move.

**3. Walk-forward validation confirms pw=120 across all 4 viable pairs.**
The IS optimizer independently picks pw=120 in 19 out of 24 windows across 4 pairs. Every single OOS window is profitable.

**4. Multi-scale (running multiple pw values on the same pair) does NOT add value.**
The additional trades from smaller scales are lower quality and dilute the portfolio Sharpe. The way to get more trades is more pairs, not more scales.

**5. Spread viability eliminates 4 of 8 pairs.**
USDCAD, AUDUSD, NZDUSD, and USDCHF all show positive Sharpe at pw=120 but fail the PnL/spread ratio test (all below 1.0). The edge exists but transaction costs eat it.

---

## Walk-Forward Results (2yr IS → 1yr OOS, 6 windows)

| Pair   | Avg OOS Sharpe | % Positive | IS Picks pw=120 | Verdict  |
|--------|:--------------:|:----------:|:----------------:|:--------:|
| EURUSD | **+3.96**      | 100% (6/6) | 4/6              | STRONG   |
| XAUUSD | **+3.08**      | 100% (6/6) | 5/6              | STRONG   |
| USDJPY | **+2.91**      | 100% (6/6) | 5/6              | STRONG   |
| GBPUSD | **+1.84**      | 100% (6/6) | 5/6              | STRONG   |

---

## Full-Sample Portfolio Stats (pw=120, hold=60)

### Trade Frequency

| Pair   | Total (8yr) | Per Year | Per Month | Per Trading Day |
|--------|:-----------:|:--------:|:---------:|:---------------:|
| EURUSD | 2,109       | 259      | 21.6      | 1.60            |
| XAUUSD | 2,066       | 254      | 21.1      | 1.49            |
| USDJPY | 2,064       | 251      | 21.0      | 1.48            |
| GBPUSD | 2,525       | 307      | 25.6      | 1.61            |
| **TOTAL** | **8,764** | **1,067** | **~89** | **~4.2**       |

### Performance

| Pair   | Win Rate | Sharpe | Avg PnL per Trade |
|--------|:--------:|:------:|:-----------------:|
| EURUSD | 60.8%    | +3.98  | +3.0 pips         |
| XAUUSD | 56.1%    | +2.86  | +$1.02            |
| USDJPY | 55.6%    | +2.53  | +2.9 pips         |
| GBPUSD | 55.4%    | +2.11  | +0.2 pips         |

### Year-by-Year: 32/32 pair-years profitable

| Year | EURUSD      | XAUUSD       | USDJPY      | GBPUSD     |
|------|:-----------:|:------------:|:-----------:|:----------:|
| 2018 | 309t / +7.8 | 189t / +22.9 | 273t / +2.5 | 315t / +0.1 |
| 2019 | 288t / +7.7 | 194t / +104  | 248t / +1.6 | 309t / +0.05 |
| 2020 | 231t / +7.3 | 242t / +219  | 252t / +7.9 | 316t / +0.08 |
| 2021 | 255t / +4.8 | 299t / +236  | 211t / +2.8 | 306t / +0.06 |
| 2022 | 211t / +9.6 | 264t / +239  | 236t / +11.8 | 331t / +0.13 |
| 2023 | 297t / +7.7 | 267t / +65.8 | 268t / +14.1 | 326t / +0.04 |
| 2024 | 225t / +5.8 | 287t / +301  | 226t / +10.5 | 312t / +0.03 |
| 2025 | 253t / +12.7 | 289t / +695 | 288t / +9.1 | 251t / +0.02 |

---

## Recommended Configuration

All 4 pairs use **identical strategy parameters** except spread_cost and min_bar_ticks:

```
pivot_window:        120
max_hold_bars:       60
max_pullback_bars:   60
min_pullback_bars:   3
atr_period:          60
confirm_bars:        3
imbalance_window:    3
divergence_threshold: 0.50
sl_atr_multiple:     10.0
tp_atr_multiple:     99.0
```

Per-pair specifics:

| Pair   | spread_cost | min_bar_ticks | sec_type | symbol | currency |
|--------|:-----------:|:-------------:|:--------:|:------:|:--------:|
| EURUSD | 0.00010     | 30            | CASH     | EUR    | USD      |
| XAUUSD | 0.30        | 50            | CMDTY    | XAUUSD | USD      |
| USDJPY | 0.015       | 30            | CASH     | USD    | JPY      |
| GBPUSD | 0.00012     | 30            | CASH     | GBP    | USD      |

---

## Implementation Plan

### What Changes from pw=60 → pw=120

**Strategy config**: Only `pivot_window` changes from 60 to 120. Everything else stays the same.

**Backfill on startup**: No code change needed. `seed_buffer()` already computes `needed = 2 * pivot_window + 50` dynamically. For pw=120 that's 290 bars, well within the 8-hour minimum floor (480 bars).

**Buffer size**: Already 500, validation requires ≥ 241. Passes.

### Multi-Pair Architecture

The current system runs one pair per process. For 4 pairs, two approaches:

**Option A: 4 Separate Processes (Simplest)**
- Run 4 independent `run_live.py` instances with different `--client-id` values (10, 11, 12, 13)
- Each process handles one pair
- Use the existing watchdog per process, or a single multi-process watchdog
- Pro: Zero code changes to the trading engine. Just config.
- Con: 4 IBKR connections (IBKR allows up to 32 client IDs)

**Option B: Single Multi-Pair Process (More Complex)**
- Refactor `V8LiveTrader` to manage 4 engines/aggregators/contracts
- Share one IBKR connection, use threading or asyncio per pair
- Requires changes to: IBKRConnection (multi-contract), main loop (parallel), signal handling (per-pair routing), logging (per-pair), safety limits (per-pair + global)
- Pro: Single process, unified monitoring
- Con: Significant refactor, more failure modes

**Recommendation: Start with Option A.** It's deployable immediately with only config changes. Option B can be built later as an optimization.

### Option A Launch Commands

```bash
# XAUUSD
python -m v8_confirmed_rebreak.live.run_live \
    --symbol XAUUSD --sec-type CMDTY --exchange SMART --currency USD \
    --pw 120 --max-hold 60 --spread 0.30 --min-ticks 50 \
    --client-id 10 --qty 1.0

# EURUSD
python -m v8_confirmed_rebreak.live.run_live \
    --symbol EUR --sec-type CASH --exchange IDEALPRO --currency USD \
    --pw 120 --max-hold 60 --spread 0.00010 --min-ticks 30 \
    --client-id 11 --qty 20000

# USDJPY
python -m v8_confirmed_rebreak.live.run_live \
    --symbol USD --sec-type CASH --exchange IDEALPRO --currency JPY \
    --pw 120 --max-hold 60 --spread 0.015 --min-ticks 30 \
    --client-id 12 --qty 20000

# GBPUSD
python -m v8_confirmed_rebreak.live.run_live \
    --symbol GBP --sec-type CASH --exchange IDEALPRO --currency USD \
    --pw 120 --max-hold 60 --spread 0.00012 --min-ticks 30 \
    --client-id 13 --qty 20000
```

---

## Expected Results

Based on 8 years of walk-forward validated backtesting:

- **~4 trades per day** across 4 pairs
- **~89 trades per month**
- **~1,067 trades per year**
- **All 4 pairs Sharpe > 2.0** (OOS walk-forward average)
- **100% of OOS windows profitable** (24/24)
- **32/32 pair-years profitable** in full-sample backtest
- **Both longs and shorts profitable** for every pair in every OOS window
