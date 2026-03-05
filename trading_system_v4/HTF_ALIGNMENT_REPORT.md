# HTF Alignment Investigation Report
**Date:** 2026-02-24  
**Scope:** Batch vs Live HTF feature alignment in v3 model  
**Verdict:** Train/serve skew confirmed. Model has no genuine edge.

---

## 1. Background

The v3 XGBoost model uses 50 features: 40 from 15m bars + 10 from higher-timeframe (1h/4h) bars.
The HTF features are computed by `_resample_ohlcv()` in `feature_engineering_v3.py`, which uses
pandas defaults `label='left', closed='left'` when resampling 15m → 1h/4h.

A previous audit found this creates **lookahead** in batch processing. This investigation
determines whether the batch "leak" accidentally reproduces what happens in live trading.

---

## 2. The Three Modes

### 2.1 BATCH (label=left) — Production Training

- 1h bar labeled at `08:00` covers `[08:00, 09:00)` = bars at 08:00, 08:15, 08:30, 08:45
- The bar's `close` = the 08:45 close (3 bars in the FUTURE from position 0)
- After `ffill`: ALL 15m bars at 08:00-08:45 receive this end-of-hour close as `1h_close`
- **This is LOOKAHEAD.** At 08:00 the model knows where the hour will close.

### 2.2 LIVE (label=left) — Production Inference

- Same label/closed settings, but only bars received so far exist
- 1h bar labeled at `08:00` at time 08:15 only contains `{08:00, 08:15}`
- The bar's `close` = the 08:15 close (the CURRENT 15m bar's own close)
- Result: **1h_close == current 15m close for 100% of bars** (verified on 200-bar sample)
- The "1h" feature carries NO higher-timeframe information — it's degenerate.

### 2.3 CLEAN (label=right, closed=right) — No Lookahead

- 1h bar labeled at `08:00` covers `(07:00, 08:00]` = completed previous hour
- The bar's `close` = the 08:00 close (truly past data, no leak)
- This is the CORRECT alignment for leak-free backtesting.

---

## 3. Key Finding: BATCH ≠ LIVE

| Metric | Value |
|--------|-------|
| Live 1h_close == current 15m close | **100% of bars** |
| Batch vs Live mean difference | **8.39 pips** |
| Batch vs Clean mean difference | **15.08 pips** |
| Bars where batch ≠ live | **135 / 200 (67.5%)** |

### Hour-Position Analysis

| Position | Batch=Live | Batch≠Live | Live=Clean |
|----------|-----------|-----------|-----------|
| Pos 0 (first bar) | 1 | 53 | 54 |
| Pos 1 | 1 | 48 | 0 |
| Pos 2 | 17 | 34 | 0 |
| Pos 3 (last bar) | 46 | 0 | 0 |

- **Position 0:** Maximum leak. Batch sees end-of-hour close. Live sees current bar close (= clean).
- **Position 3:** No leak. Hour is complete, all modes converge.
- **Positions 1-2:** Partial leak. Batch has full hour; live has partial hour.

---

## 4. Impact on Derived HTF Features

The model doesn't consume raw 1h_close directly. It uses derived indicators (RSI, MACD, SMA, returns)
computed on the 1h series. Since these indicators smooth over many periods (14-26), the impact of
one wrong bar is diluted.

### 4.1 Relative Error by Feature

| Feature | Rel Error (%) | Match (%) |
|---------|--------------|-----------|
| price_to_sma20_1h | 0.0 | 35.2 |
| rsi_1h | 3.9 | 35.2 |
| rsi_4h | 4.1 | 9.0 |
| trend_alignment | 5.1 | 96.2 |
| di_diff_1h | 7.5 | 45.0 |
| macd_diff_1h | 9.2 | 35.2 |
| macd_diff_4h | 10.0 | 9.0 |
| returns_1h_4 | 23.7 | 35.2 |
| returns_4h_4 | 24.6 | 9.0 |
| price_to_sma20_4h | 0.1 | 9.0 |

### 4.2 Direction Agreement (Most Important for Trading Decisions)

| Feature | Overall (%) | Pos 0 (%) | Pos 3 (%) |
|---------|------------|----------|----------|
| macd_diff_1h | 97.8 | 96.3 | 100.0 |
| di_diff_1h | 97.2 | 94.8 | 100.0 |
| trend_alignment | 98.6 | 97.8 | 100.0 |
| macd_diff_4h | 98.4 | 98.5 | 98.3 |
| returns_1h_4 | 91.6 | 87.3 | 100.0 |
| returns_4h_4 | 88.6 | 87.3 | 90.5 |

**Interpretation:** The DIRECTION of HTF features agrees 87-99% between batch and live.
The model's "trend is bullish/bearish" decisions are mostly consistent.
However, MAGNITUDES differ by 4-25%, and the model's parameters were optimized for
the batch distribution (with lookahead), not the live distribution.

---

## 5. The Full Evidence Chain

| Test | Result | Edge |
|------|--------|------|
| v3 model on batch features (leaked) | AUC ~0.56-0.58 | ~+19 pp (FAKE — from lookahead) |
| v3 model retrained on clean features (label=right) | AUC = 0.5149 (157k samples) | **Zero edge** |
| Session range breakout (Asian→London, London→NY) | 42.8% WR vs 42.6% random | **Zero edge** |
| 15 tick microstructure signal configs | All -3.3 to -9.9 pp vs random | **Zero edge** |
| Multi-horizon micro sweep (7 TP/SL, momentum/fade) | All within ±1 pp of random | **Zero edge** |
| Next-bar direction from vol_imbalance z>2 | 51.2% hit rate (barely above 50%) | **Zero edge** |
| XGBoost on 62 microstructure features | AUC = 0.5158 | **Zero edge** |

---

## 6. Conclusion

### 6.1 The batch leak does NOT match live behavior.

In batch training, the model sees **complete future hour closes** as HTF features.
In live inference, the model sees **current 15m bar's own close** as the "1h close"
(a completely degenerate feature). These are fundamentally different distributions.

### 6.2 The model has no genuine predictive edge.

The apparent edge (AUC ~0.56-0.58) was entirely an artifact of the HTF lookahead.
When corrected:
- Clean HTF features → AUC 0.5149 (no edge)
- Microstructure features → AUC 0.5158 (no edge)
- Session breakout signals → WR identical to random (no edge)

**EURUSD at the 15-minute timeframe appears to be efficiently priced.**
No feature family we tested — technical indicators, session structures, tick
microstructure, or multi-timeframe analysis — can predict the direction of
price movement with enough accuracy to overcome transaction costs.

### 6.3 The live model has a train/serve skew.

The model consumes features in live that differ from what it was trained on:
- Direction agreement: 87-99% (moderate consistency)
- Magnitude error: 4-25% (significant for some features)
- The model was NEVER exposed to the live feature distribution during training

The model's live performance is **unpredictable** — it may appear to work
over short periods by chance, but has no systematic edge.

---

## 7. Possible Paths Forward

1. **Accept EURUSD 15m is efficient.** Focus resources elsewhere.
2. **Try different instruments/timeframes.** Other FX pairs or commodities may have structure.
3. **Try different target formulations.** Predict volatility, regime, or range instead of direction.
4. **Fundamental signals.** Economic data releases, central bank communication, cross-asset flows.
5. **Execution alpha.** Use microstructure for better fills rather than directional prediction.

---

## Scripts Created During This Investigation

- `trading_system_v4/scripts/_trace_htf_alignment.py` — Initial trace of pandas resampling behavior
- `trading_system_v4/scripts/_quantify_htf_leak.py` — Raw 1h close comparison across 3 modes
- `trading_system_v4/scripts/_htf_feature_diff.py` — Derived feature comparison (RSI, MACD, etc.)
