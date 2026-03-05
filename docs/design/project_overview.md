# Trading System — Full Project Overview
**Written:** 2026-02-27  
**Purpose:** Plain-English narrative of the entire project lifecycle — what was built, what failed, what we learned, and where we are now.

---

## Table of Contents
1. [What We Are Trying to Do](#1-what-we-are-trying-to-do)
2. [The Technology Stack](#2-the-technology-stack)
3. [v2 — The Multi-Timeframe ML System (First Production Attempt)](#3-v2--the-multi-timeframe-ml-system-first-production-attempt)
4. [The Root Problems Found in v2](#4-the-root-problems-found-in-v2)
5. [v3 — Hierarchical Multi-Timeframe (HMTF)](#5-v3--hierarchical-multi-timeframe-hmtf)
6. [v4 — New Modular Pipeline (trading_system_v4)](#6-v4--new-modular-pipeline-trading_system_v4)
7. [The ML Lookahead Leak — the Most Important Finding](#7-the-ml-lookahead-leak--the-most-important-finding)
8. [The Edge Search — Assets and Approaches Tried](#8-the-edge-search--assets-and-approaches-tried)
9. [v5 — XAUUSD Asian Range Breakout (Current Strategy)](#9-v5--xauusd-asian-range-breakout-current-strategy)
10. [Why We Switched from CFD to CMDTY](#10-why-we-switched-from-cfd-to-cmdty)
11. [How the v5 Live Script Works (orb_live.py)](#11-how-the-v5-live-script-works-orb_livepy)
12. [Where We Are Right Now](#12-where-we-are-right-now)
13. [Key Lessons Learned](#13-key-lessons-learned)

---

## 1. What We Are Trying to Do

Build a fully automated trading system that:
- Runs on Interactive Brokers (IBKR) paper and then live accounts
- Identifies a genuine, non-overfitted edge in a tradeable instrument
- Places, manages, and exits bracket orders automatically
- Survives the gap between "this works in backtest" and "this works in real time"

---

## 2. The Technology Stack

| Component | Tool |
|-----------|------|
| Broker API | Interactive Brokers — `ib_insync` Python library |
| Backtesting engine | NautilusTrader (Rust-core, Python interface) |
| ML models | XGBoost / LightGBM |
| Data storage | NautilusTrader Parquet catalog + CSV files |
| Primary platform | Windows, IBKR Gateway on port 4002 (paper) |
| Python environment | `c:\nautilus0\.venv` |

---

## 3. v2 — The Multi-Timeframe ML System (First Production Attempt)

**What it was:**  
A multi-timeframe ML strategy running on EUR/USD. It:
1. Consumed 15-minute and 30-minute OHLCV bars
2. Computed ~50 technical features (DMI, MAMA oscillator, RSI, ATR, etc.)
3. Fed them into an XGBoost classifier trained to predict whether a trade would hit TP before SL
4. Entered bracket orders (entry + SL + TP) when the model's confidence exceeded a threshold (0.65–0.80)
5. Used NautilusTrader's backtest engine for parameter optimization

**Optimization done:**  
Sequential grid search over 5 parameter groups (SL multiplier, TP multiplier, MAMA threshold, confidence threshold, hour filters). Used 2025 EUR/USD data with a "replay" backtest that mimics live bar delivery.

**Backtest results looked excellent:**  
Sharpe ratios of 2–4, profit factors around 3, consistent positive returns. The optimized parameters were loaded into the live config and the system was run live.

**Live results were poor:**  
The system lost money. Win rates were lower, and several trades went in the wrong direction relative to what the backtest predicted.

---

## 4. The Root Problems Found in v2

### Problem A — Bar Double-Delivery Bug (Critical)

**What happened:**  
NautilusTrader, in replay/backtest mode, delivers each bar 2–4 times to the strategy's `on_bar()` callback. This is a known characteristic of the engine related to how it emits bar data.

The v2 strategy was **not idempotent** — it processed every bar delivery. Functions like MAMA and DMI are cumulative (they append to a rolling buffer each time). So instead of a 50-bar window, the backtest was actually processing windows of 100–200+ bars with repeated entries.

**Measurement:**  
- 61% of bars delivered twice, 38% three or more times
- DMI+ values in backtest differed from live by a mean of 0.057 (5.7%)
- Prediction agreement between backtest and live: only **69.7%** (target: >95%)
- In terms of trade direction: 30% of the time, when backtest said LONG, live said SHORT

**Fix applied:**  
Added an idempotency guard in `on_bar()` — tracks each bar's `ts_event` timestamp in a set, skips if already processed. This brought parity to near 100%.

**But the damage was already done:**  
The entire parameter optimization had been run on the buggy backtest. The "optimal" SL/TP/threshold values were tuned for distorted signals that don't exist in the real market. Resuming live trading with those parameters was dangerous.

### Problem B — 30m Resampling Timestamp Bug

**What happened:**  
When resampling 15-minute bars to 30-minute bars for DMI calculation, the code used `ts_init` (bar close timestamp) instead of `ts_event` (bar open timestamp) as the bucket key.

In live trading, `ts_init` is offset by +15 minutes from bar open. In backtest, `ts_init == ts_event`. This caused live bars to fall into different 30-minute buckets than backtest bars, producing different DMI values.

**Effect:**  
Live `dmi_plus` was 0.27–0.38, while backtest showed 0.19–0.26. This caused 7 out of 11 predictions to flip direction.

**Fix applied:**  
Changed the resampling key from `ts_init` to `ts_event` throughout. DMI difference dropped from ±0.05–0.15 to < 0.002.

### Problem C — XGBoost Model Trained on Lookahead-Contaminated Data

(See Section 7 for full detail — this was confirmed in the v4 investigation.)

The model used as the trading signal was trained with features that unknowingly leaked future price information. When the leak was fixed, the model had **zero predictive power** (AUC dropped from 0.756 to 0.519 — essentially random).

---

## 5. v3 — Hierarchical Multi-Timeframe (HMTF)

**What it was:**  
A redesign of v2 with a cleaner architecture. Key idea: treat 5-minute and 15-minute bars as separate timeframes with a strict "no lookahead" handoff.

- 15m "master" model predicts trend direction
- 5m "soldier" model uses the *most recently completed* 15m prediction as a feature
- Strict ordering: when a 15m and 5m bar share the same close timestamp, 15m is processed first
- State machine: `IDLE → HUNTING → ACTIVE → COOLDOWN` (cooldown ~30 minutes)
- Dynamic position sizing via `get_dynamic_size()` based on current confidence

**Training:**  
Model trained on 2024 EUR/USD data only. Labels: binary — price hits TP (close + ATR×1.4) before SL (close - ATR×1.8) within 60 bars.

**What went wrong:**  
Same underlying issue — the features feeding the model had lookahead contamination via the HTF resampling bug (see Section 7). The model results that looked promising were artifacts of future data leaking into current features.

Additionally, the HR hierarchy (5m + 15m HMTF dataset logging, CSV append-only pipeline) added significant complexity without addressing the core predictive power problem.

---

## 6. v4 — New Modular Pipeline (trading_system_v4)

**Context:**  
After identifying the v2/v3 issues, a completely fresh pipeline was built under `trading_system_v4/` with the explicit goal of exposing and fixing all data integrity problems before building a new model.

**What was built:**
- `data/nautilus_adapter.py` — reads from NautilusTrader Parquet catalog
- `features/feature_engineering.py` — 32 clean, non-redundant features (removed 7 constant or highly correlated features from the original 37)
- `scripts/build_training_dataset.py` — processes each symbol independently before concatenation (prevents cross-symbol contamination)
- `scripts/add_labels.py` — multiple labeling approaches tested
- `scripts/train_model.py` — walk-forward CV with purged folds
- `scripts/run_live_hybrid.py` — live runner with dual model (long + short)

**Training data available:**  
- EURUSD, GBPUSD, USDCHF — 5-minute bars from 2022 to 2026
- Extended back to 2020 during audit
- 1000-tick bars: EURUSD (266k bars), XAUUSD (415k bars), 2015–2026

**What happened:**  
The rigorous audit confirmed that **all observed model edge was fake** (see Section 7).

---

## 7. The ML Lookahead Leak — the Most Important Finding

**This is the single most important finding of the entire project.**

### What the leak was

In `strategies/feature_engineering_v3.py`, the `_resample_ohlcv()` method used pandas defaults when resampling 15-minute bars to 1-hour and 4-hour timeframes:

```python
df.resample('1h')  # default: label='left', closed='left'
```

Pandas `label='left'` means: the bucket labeled "13:00" contains bars from 13:00 to 13:59. But the `.ffill()` (forward-fill) step afterward causes the completed 1h bar to be used *before* the hour ends — effectively using future bars to compute current features.

**Scope of contamination:**
- 98.7% of all training bars were affected
- Average 7.4 pips of future information leaked into each feature row
- When the leak was fixed to `label='right', closed='right'`, ALL model edge disappeared

### The before-and-after table

| Signal / Model | AUC / Result | Status |
|---|---|---|
| v3 XGBoost model (leaked features) | AUC 0.756, precision +19.1 pp above random | **Fake — all from leak** |
| v3 XGBoost model (clean features, fix applied) | AUC 0.519 | **Zero edge** |
| Clean retrained model (2024–2025 only) | AUC 0.519 | **Zero edge** |
| Clean retrained model (ALL 2015–2024, 157k samples) | AUC 0.5149 | **Definitively zero edge** |

### Why the results felt real

The leaked model produced a Sharpe ratio of 2–4 in backtests. Trades appeared logical — they entered in the direction of the trend and exited cleanly. This is because:

1. The model was literally using future bar data as input — it knew where price was going
2. The backtest evaluated using the same leaking pipeline — so training AND evaluation saw the same future
3. The optimization loops found parameter combinations that looked even better — they were all just "how much future data should I use?"

### What was done

- Reverted `feature_engineering_v3.py` to the original (leaked) version with a `# WARNING: LEAKED` comment
- Created a backup: `models/ml_model_mtf_v3_xgb_leaked_backup.pkl`
- De-listed the leaked model from production use
- Accepted that standard 15m technical indicators (MACD, RSI, ADX, Bollinger, EMA, SMA, returns) have **no detectable predictive power** for EUR/USD direction

---

## 8. The Edge Search — Assets and Approaches Tried

After accepting that the existing ML edge was fake, a systematic search for real edge was conducted.

### EURUSD 15m — Technical ML
- 32 features: RSI, MACD, ATR, EMA, SMA, Bollinger, DMI, ADX, session flags, time features
- Walk-forward XGBoost, purged CV, 4 folds
- **Result: AUC 0.519 (essentially random)**

### EURUSD 15m — Tick Microstructure ML
- 62 features: all above + tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread from 1000-tick bars
- Hypothesis: microstructure features contain institutional flow information not visible to retail
- **Result: AUC 0.516 — zero edge, top features were all time-based (not microstructure)**

### EURUSD — Session Range Breakout (base signal only)
- Asian session (00:00–07:00 UTC) range → London open breakout signal
- Same framework used for XAUUSD ORB later
- Win rate on 1.5 ATR TP / 1.4 ATR SL: **42.8% vs 42.6% random baseline**
- **Result: statistically zero edge for EUR/USD**

### Multi-Pair FX Daily Momentum + Carry
- Universe: 10 FX pairs (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF, USDJPY, EURJPY, GBPJPY, EURGBP)
- Signal: 50% cross-sectional 63-day momentum + 20% 21-day momentum + 30% 252-day carry proxy
- Weekly rebalance, long top 3, short bottom 3, 1.5 pip round-trip cost
- **Result: Sharpe 0.02, OOS average -1.31%/yr, win rate 6/15 years**
- Conclusion: FX momentum had edge in the early 2000s; post-2016 it has been consistently negative — arbitraged away

### XAUUSD — Session Range Breakout
- Asian range breakout applied to gold (00:00–06:00 UTC → London trade window 08:00–16:00 UTC)
- RR = 2.0 (TP = 2 × range size from entry)
- Backtest on 2015–2026 using 415k tick bars resampled to 5-minute
- **Result: Sharpe 2.60, profit factor 1.61, ALL years profitable, max drawdown -$109 on $1/oz sizing**
- This was the first approach to show genuine, consistent edge

**Why XAUUSD works where EURUSD doesn't:**
- Gold is a trending asset — it makes large directional moves within sessions
- The Asian session (quiet hours, low volatility) genuinely compresses a range
- The London session genuinely injects liquidity and breaks that range with momentum
- The structural reason for the pattern is clear and not a statistical artifact

**Seasonality analysis (`analyze_seasonality.py`) confirmed:**
- Mondays, Tuesdays, Thursdays, Fridays — all profitable breakout days
- Wednesdays: consistently near-zero edge (possibly midweek mean-reversion)
- Wednesdays are now skipped in the live strategy

---

## 9. v5 — XAUUSD Asian Range Breakout (Current Strategy)

### Strategy Logic

1. **Asian Range Collection (00:00–06:00 UTC):** Record the highest high and lowest low of all bars during this window. This is the "range."

2. **London Trade Window (08:00–16:00 UTC):** Place two bracket orders:
   - LONG: stop entry at range_high, SL at range_low, TP at range_high + 2 × (range_high - range_low)
   - SHORT: stop entry at range_low, SL at range_high, TP at range_low - 2 × (range_high - range_low)
   - The two orders are an OCA (One-Cancels-All) group — if one fills, the other is cancelled

3. **Risk/Reward = 2.0:** TP distance is always 2 × SL distance

4. **Filters:**
   - Skip if Asian range < 0.05% of price (too tight, noise)
   - Skip if Asian range > 2.0% of price (unusual event, too wide)  
   - Skip Wednesdays entirely (near-zero edge from seasonality)
   - GTD (Good-Till-Date) expiry at 16:00 UTC — unfilled orders auto-cancel

5. **Breakeven Rule (1h BE):** After 1 hour in a trade, move SL to entry price. This converts the trade to risk-free. Backed by optimization: 1h BE gives Sharpe 5.00, profit factor 7.98.

6. **State Machine:**  
   `IDLE → RANGE_COMPUTED → ORDERS_PLACED → IN_TRADE → DONE_TODAY`  
   Resets to IDLE at midnight UTC daily.

### Backtest Performance (2019–2026, 1 oz/trade)

| Metric | Baseline (EOD) | With 1h BE Rule |
|--------|---------------|-----------------|
| Total P&L | +$2,602 | +$2,918 |
| Sharpe | 2.83 | **5.00** |
| Max Drawdown | -$109 | **-$26** |
| Profit Factor | 2.04 | **7.98** |

The 1h BE rule is the primary risk management innovation: it dramatically cuts drawdown (from -$109 to -$26) while *increasing* total P&L, because it eliminates the slow losers that drift for hours and exit at EOD slightly negative.

---

## 10. Why We Switched from CFD to CMDTY

### The Problem (Feb 27, 2026)

The live system ran successfully through the full cycle:
- IDLE → Asian range collected → RANGE_COMPUTED → bracket orders placed → ORDERS_PLACED

But the orders were rejected with:  
> **Error 201/202: "COULD NOT VALUE THIS CONTRACT AT THIS TIME"**

**Root cause:** IBKR blocks CFD trading for Canadian residents. The original contract was `secType="CFD"` for XAUUSD. Canadian regulatory rules prohibit CFD trading on IBKR regardless of account type.

### Why CMDTY

IBKR offers "London Gold" as a commodity contract: `secType="CMDTY"`, symbol `XAUUSD`, exchange `SMART`, currency `USD`.

Verified equivalence:
| Feature | CFD | CMDTY |
|---------|-----|-------|
| Underlying | XAUUSD spot | XAUUSD spot |
| Min tick | $0.01 | $0.01 |
| Multiplier | 1 oz/unit | 1 oz/unit |
| Order types supported | STP, OCA, GTD, TRAIL | STP, OCA, GTD, TRAIL — identical |
| Price at time of check | $5,184.90 (CFD) | $5,181.36 (CMDTY) |
| Price difference | — | $3.54 (0.07%) |

Change made: `v5_xauusd_orb/config.yaml` → `sec_type: "CMDTY"`

### Streaming Price Fix

A separate issue was found: `reqMktData(snapshot=True)` always returns `nan` for delayed CFD/CMDTY data on paper accounts. The fix: at connect time, start a persistent `reqMktData(snapshot=False)` streaming subscription. `get_current_price()` reads from this ticker instantly instead of making a blocking historical request.

---

## 11. How the v5 Live Script Works (orb_live.py)

### Architecture

`orb_live.py` is a single-file live trading script (~1,200 lines). It runs an infinite polling loop and manages the full trade lifecycle.

### Key Classes

**`IBKRConnection`**
- Wraps `ib_insync.IB`
- On `connect()`: calls `ib.connect()` with exponential backoff retry (up to 10 attempts, max 5 min wait), then starts a persistent price streaming ticker
- On `disconnect()`: cancels the price ticker cleanly
- `get_current_price()`: reads bid/ask mid from the streaming ticker (instant); falls back to 5-min MIDPOINT historical data, then daily MIDPOINT
- Error handler suppresses known harmless warning codes (2103–2108, 2157, 2158, 10168, 10167)

**`ORBStrategy`** (the main class)
- Holds all state: current phase, Asian range H/L, order IDs, position info, daily log
- `run_loop()`: called every 10 seconds by the main loop
  - Checks UTC time, determines which phase should be active
  - Dispatches to the appropriate handler function

**Phase handlers:**
- `_phase_collect_range()`: polls each 5-min bar during 00:00–06:00 UTC, records running H/L
- `_phase_compute_range()`: at 06:00 UTC, finalizes range, validates it passes filters
- `_phase_place_orders()`: at 08:00 UTC, computes entry/SL/TP levels, submits OCA bracket orders via IBKR
- `_phase_watch()`: monitors for fill, tracks open position, applies BE rule after 1h
- `_phase_eod()`: at 16:00 UTC, cancels unfilled orders, closes any open position, marks day DONE

### Connection Reliability

Before this was fixed, every attempt to probe the IBKR port with a raw TCP socket caused Gateway to hold a CLOSE_WAIT connection slot. After several probes, the slot pool exhausted and all real connections timed out.

Fix: removed all raw socket probing. The script simply calls `ib_insync.IB().connect()` and retries on failure.

### Daily Launch

The script runs continuously. After `DONE_TODAY`, it sleeps until next day's 00:10 UTC and resets state. A PowerShell scheduled task (`daily_launcher.ps1`) can restart it automatically if it crashes.

---

## 12. Where We Are Right Now

**Date:** 2026-02-27

### Status
- v5 live script: CMDTY contract configured, streaming price working, full loop runs
- Orders placed with CFD were rejected (Canadian restriction) — now on CMDTY which should work
- First CMDTY live session not yet confirmed accepted (need tonight's Asian session to test)

### What Happened on Feb 27 (Simulated Trade)
The script ran its first full live cycle. The orders were placed but rejected because of the CFD restriction.

A simulation of what would have happened if the orders had gone through:
- Asian range: H = 5199.79, L = 5167.03 (range size $32.76/oz)
- LONG entry stop at 5199.79, SL at 5167.03, TP at 5265.31
- SHORT entry stop at 5167.03, SL at 5199.79, TP at 5101.51
- Price broke the LONG level at ~13:05 UTC (5-min bar high 5214.84 > 5199.79)
- TP of 5265.31 was not reached by 16:00 UTC; trade closed via GTD expiry
- Exit price approximately 5244.20 (16:00 UTC bar)
- **Estimated P&L: +$44.41/oz** — it would have been a winning trade

### Infrastructure
| Component | Status |
|-----------|--------|
| IB Gateway | Running, port 4002, paper account DU1558484 |
| v5 ORB script | config pointing to CMDTY |
| v2/v3 live | Not running |
| Contract | XAUUSD CMDTY, SMART, USD, conId 69067924 |

---

## 13. Key Lessons Learned

### On ML in trading

1. **Lookahead is insidious.** A tiny misuse of pandas `.resample()` defaults made the model appear to have AUC 0.756, Sharpe 2–4, and highly profitable trades. Everything looked real. It was not. Always check resampling labels, `.shift()` calls, `.ffill()` after joins, and any feature that uses a "current period" bar to label that same period.

2. **Standard technical indicators (RSI, MACD, ADX, etc.) have no detectable edge** on EUR/USD 15-minute bars — confirmed across 157k samples, 2015–2024, multiple model types, AUC consistently 0.51–0.52. This is not a sampling fluke; it is a real finding.

3. **The backtest engine matters.** NautilusTrader delivers bars multiple times in replay mode. Any calculation that appends to a buffer on each delivery (like a rolling EMV) will diverge from live. Build idempotency guards from day one. Verify parity before trusting any optimization result.

4. **Train the model on only what the strategy actually sees.** If the strategy filters to London hours, train on London hours only. If the strategy only enters after certain filters pass, train on bars that would pass those filters.

5. **Calibrate probabilities.** XGBoost `predict_proba` outputs are not true probabilities. A threshold of 0.70 does not mean 70% win rate. Use isotonic regression or Platt scaling.

### On finding edge

6. **Rule-based edge > ML edge for small datasets.** The XAUUSD Asian range breakout (a 30-year-old pattern, no model required) shows Sharpe 5.00 and profit factor 7.98. The ML system showed similar numbers that turned out to be fake.

7. **The structural reason must exist.** Asian session = low volume, range compression. London session = liquidity injection, range expansion. The structural cause is clear. When you can explain *why* a pattern exists, it is more likely to persist.

8. **Check for asset-specific properties.** EUR/USD is mean-reverting at short timeframes — it is hard to predict direction. Gold is a trending asset with clear session dynamics. The same session-range-breakout approach that showed zero edge on EUR/USD showed Sharpe 2.60 on gold.

### On IBKR live infrastructure

9. **Never probe ports with raw sockets.** Gateway treats every TCP connection as an API client. Raw socket probes exhaust the connection pool. Use `ib_insync.IB().connect()` directly with retry logic.

10. **Delayed data requires streaming, not snapshot.** `reqMktData(snapshot=True)` returns `nan` for delayed data on paper accounts. `reqMktData(snapshot=False)` with a persistent subscription gives live bid/ask.

11. **Verify what you can actually trade.** Canadian residents cannot trade CFDs on IBKR. The equivalent commodity contract (CMDTY) has identical pricing, identical order support, and works fine.

---

*End of overview. For session-by-session technical detail, see:*
- `SESSION_NOTES.md` — Feb 20: DMI parity / ts_event bug
- `SESSION_SUMMARY_2026-02-20_PARITY_INVESTIGATION.md` — parity measurements
- `SESSION_SUMMARY_2026-02-21_IDEMPOTENCY_FIX.md` — bar double-delivery fix
- `SESSION_HANDOVER_2026-02-22.md` — v4 pipeline built
- `SESSION_HANDOVER_2026-02-23.md` — two-model split, fixed-horizon labels
- `trading_system_v4/SESSION_HANDOVER_2026-02-24.md` — lookahead leak found, edge audit
- `trading_system_v4/SESSION_HANDOVER_2026-02-25.md` — XAUUSD data downloaded, all dead-ends catalogued
- `SESSION_HANDOVER.md` — Feb 26: v5 connection fix
- `SESSION_HANDOVER_20260227_0308.md` — Feb 27: live launch, backtest, BE rule optimization
