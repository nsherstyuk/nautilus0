# SESSION HANDOVER — 2026-02-25

## EURUSD / XAUUSD Trading System — Signal Audit Continuation

Read this file at the start of a new session to resume exactly where we left off.

---

## 1. EXECUTIVE SUMMARY

This session continued the signal audit started yesterday. Two additional approaches were tested and ruled out. The main productive output is **XAUUSD tick data now fully downloaded and ready for the 15m signal audit**.

### Results Added This Session

| Approach | Result | Verdict |
|---|---|---|
| Multi-pair FX daily momentum + carry | Sharpe 0.02, OOS -1.31%/yr, 6/15 win years | **Zero edge** |
| XAUUSD 1000-tick bars (2015–2026) | **415,511 bars downloaded** | **Ready for audit** |

### Cumulative Dead-Ends (all sessions)

| Approach | Result | Verdict |
|---|---|---|
| EURUSD 15m technical ML (v3 clean) | AUC 0.519 | Zero edge |
| EURUSD 15m microstructure (62 features) | AUC 0.516 | Zero edge |
| EURUSD session range breakouts | WR 42.8% vs 42.6% random | Zero edge |
| Multi-timeframe EURUSD (1h/4h HTF) | AUC 0.756 batch → 0.519 clean | Fake (lookahead) |
| Multi-pair FX daily momentum + carry | Sharpe 0.02 | Zero edge |

---

## 2. NEXT ACTION — XAUUSD SIGNAL AUDIT

### Data File
- **`trading_system_v4/data/xauusd_1000t_bars.parquet`**
- 415,511 rows, Jan 2015 → Feb 25, 2026
- Same schema as EURUSD: `timestamp, open, high, low, close, total_volume, tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread, buy_volume, sell_volume`
- 5 months had download errors (network timeouts) — coverage is ~95%+ and sufficient for analysis

### Pipeline to Run (same as EURUSD, but for XAUUSD)

```
Step 1: Resample to 15m bars
        label='right', closed='right'  (the CLEAN way — no lookahead)
        Expected: ~175,000 15m bars

Step 2: Feature engineering
        Same 32 features as EURUSD PLUS:
        - swing_proximity: distance from last confirmed local high/low (N bars back, no lookahead)
        - gold_session: flag for London+NY overlap (13:00-17:00 UTC) — gold's peak liquidity window

Step 3: Labeling
        TP = 1.5 × ATR(14), SL = 1.4 × ATR(14)  — same ratio as EURUSD
        NOTE: Gold ATR is in USD/oz (~$15-30), not pips. The labeling logic doesn't care — ATR-based
        LOOKAHEAD = 100 bars forward

Step 4: XGBoost walk-forward CV (4 folds, purged)
        Compare AUC vs EURUSD baseline of 0.519
        Hypothesis: if AUC > 0.54, worth investigating further

Step 5: Session breakout test
        Gold sessions: Asian (00:00-07:00 UTC), London (07:00-13:00 UTC), NY (13:00-22:00 UTC)
        Key window: London open breakout (07:00-10:00 UTC) — gold often makes its daily move here

Step 6: Microstructure ML test
        Same 62-feature XGBoost as EURUSD
        If top features are time-based (not microstructure), same conclusion as EURUSD
```

### Key Difference vs EURUSD Audit
- Gold is **trending** at daily timeframe (confirmed SR ~1.5 on BTC daily, gold similar)
- If 15m is also zero edge → go straight to **daily gold signal test**, not 1h/4h
- Daily gold trend-following is a documented institutional edge (CTAs run it)
- Spread cost in % terms is smaller for gold: ~$0.30/$2700 ≈ 0.01% vs EURUSD 0.1 pip = ~0.01% — comparable

---

## 3. WHAT WAS BUILT THIS SESSION

### Modified Files
- **`trading_system_v4/scripts/build_tick_bars.py`**
  - Added `--symbol` CLI argument (previously hardcoded to EURUSD)
  - Log file is now per-symbol: `build_tick_bars_{symbol.lower()}.log`
  - Output parquet is per-symbol: `{symbol.lower()}_1000t_bars.parquet`
  - Usage: `.venv\Scripts\python.exe -m trading_system_v4.scripts.build_tick_bars --symbol XAUUSD`

### New Data Files
- **`trading_system_v4/data/xauusd_1000t_bars.parquet`** — 415,511 XAUUSD tick bars
- **`trading_system_v4/data/fx_10pair_daily.parquet`** — 10 FX pair daily closes 2007-2025
- **`trading_system_v4/data/fx_momentum_carry_results.txt`** — FX backtest output

### tick_vault Supported Symbols (confirmed)
```
AUDUSD, BTCUSD, ETHUSD, EURUSD, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY, XAGUSD, XAUUSD
```

---

## 4. FX MOMENTUM + CARRY BACKTEST — FULL RESULTS

**Script:** `trading_system_v4/scripts/backtest_fx_momentum_carry.py`
**Universe:** EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF, USDJPY, EURJPY, GBPJPY, EURGBP
**Signal:** 50% cross-sectional momentum (63d) + 20% short momentum (21d) + 30% carry proxy (252d)
**Rebalance:** Weekly, long top 3, short bottom 3
**Costs:** 1.5 pip spread round-trip

```
Baseline: Sharpe=0.02, Ann Return=+0.23%, MaxDD=-27.6%, OOS Average=-1.31%/yr

Yearly breakdown (notable):
  2008: +25.2% (GFC — crisis creates huge FX moves, strategy worked)
  2013: +7.8%, 2014: +5.7%, 2016: +8.3%  (isolated good years)
  2017: -10.0%, 2019: -7.8%, 2021: -6.7%, 2025: -6.2%  (persistent losses)

Parameter sweep: No lookback/blend/sizing combination produces Sharpe > 0.1
At zero cost: Sharpe only 0.07 — the gross signal itself is nearly worthless
OOS win rate: 6/15 years (worse than coin flip)
```

**Conclusion:** FX cross-sectional momentum had edge in the 2000s. Post-2016 it is consistently negative. The strategy has been arbitraged away.

---

## 5. DISCUSSION ITEMS / STRATEGIC CONTEXT

### Why FX still exists but is hard to trade (resolved this session)
- FX is traded by: banks (market making, client flow), macro funds (fundamental), carry traders (hold for months), CTAs (trend-following at daily/weekly)
- What doesn't work: 15m direction prediction, cross-sectional weekly momentum (now proven)
- What might work: daily trend-following, fundamental/event-driven, actual carry (requires swap rate data)

### Swing Point Trading (discussed, not yet tested)
- Idea: detect local min/max, trade breakouts or fades
- Problem: confirmed local min/max requires lookahead (N+1 and N+2 bars must be higher)
- Equivalent to what we tested: Donchian breakouts (crypto daily), session range breakouts (EURUSD 15m)
- Decision: add `swing_proximity` as a *feature* in the XAUUSD audit rather than standalone strategy
- `swing_proximity` = distance from last confirmed N-bar high/low, computed with no lookahead

### If XAUUSD 15m Also Shows Zero Edge
Recommended sequence:
1. **Daily gold trend-following** — skip 1h/4h, go straight to daily to confirm edge exists
2. If edge at daily → work down to 1h to find highest-resolution timeframe that retains it
3. If daily also zero → consider: USDCAD (oil-correlated), AUDUSD (commodity-linked), or fundamentals approach

### ATR-Based Risk Management (from external review)
Reviewed a 5-point risk management spec for XAUUSD. Conclusion:
- ATR-based SL/sizing: ✅ Correct, already planned
- Spread guardrail (max spread threshold): ✅ Important, especially during NFP/FOMC
- News blackout / rollover filters: ⚠️ Test empirically, don't assume
- Partial close / trailing stop logic: ⚠️ Needs backtesting before committing
- Hard daily loss kill-switch: ✅ Standard practice
- **Overall: premature — no verified edge yet. Build risk management AFTER signal audit confirms edge.**

---

## 6. THINGS TO AVOID

1. **Do NOT use standard 15m technical indicators as ML features for EURUSD.** Proven zero edge.
2. **Do NOT use session range breakouts on EURUSD.** Proven identical to random.
3. **Do NOT use tick microstructure for EURUSD direction.** Proven zero edge.
4. **Do NOT use v3 leaked model/features for new work.** Batch AUC 0.756 is fake lookahead.
5. **Do NOT use multi-pair FX daily momentum+carry.** Proven Sharpe 0.02.
6. **Do NOT change v2 behavior** unless explicitly asked (per copilot-instructions.md).
7. **Do NOT design risk management before confirming signal edge** — it's premature.

---

## 7. FIRST ACTIONS FOR NEW SESSION

```
1. Read this file
2. Read .github/copilot-instructions.md
3. Verify XAUUSD data:
   .venv\Scripts\python.exe -c "import pandas as pd; df=pd.read_parquet('trading_system_v4/data/xauusd_1000t_bars.parquet'); print(df.shape, df.columns.tolist(), df.timestamp.min(), df.timestamp.max())"

4. Build XAUUSD signal audit script (new file):
   trading_system_v4/scripts/audit_xauusd_15m.py

   Sections:
   A. Resample tick bars → 15m (label='right', closed='right')
   B. Feature engineering (32 features + swing_proximity + gold_session flag)
   C. ATR-based labeling (TP=1.5x, SL=1.4x, lookahead=100 bars)
   D. XGBoost 4-fold purged CV → report LONG AUC, SHORT AUC
   E. Session breakout test (Asian→London, London→NY)
   F. Microstructure ML test (62 features)
   G. Summary verdict

5. Run it:
   .venv\Scripts\python.exe trading_system_v4\scripts\audit_xauusd_15m.py
```

---

## 8. ENVIRONMENT

```
Virtualenv: c:\nautilus0\.venv
Key packages: xgboost, scikit-learn, pandas, numpy, joblib, pyarrow, yfinance
Activate: .venv\Scripts\activate
```

---

## 9. SESSION HISTORY

| Session | Date | Key Work |
|---|---|---|
| 1 | 2026-02-23 AM | Built tick-bar download pipeline |
| 2 | 2026-02-23 PM | Built `build_tick_bars.py`, EURUSD data collection |
| 3 | 2026-02-24 early | Audit: found HTF leak, all v3 edge fake. WR tests. Approved Path C. |
| 4 | 2026-02-24 EOD | Path C full implementation → all zero edge. HTF alignment investigation. Replay training. |
| 5 | 2026-02-25 (this) | FX momentum+carry → zero edge. XAUUSD downloaded. build_tick_bars.py --symbol added. |
