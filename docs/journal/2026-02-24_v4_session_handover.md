# SESSION HANDOVER — 2026-02-24

## EURUSD Trading System — Path C Implementation

Read this file at the start of a new session to resume exactly where we left off.

---

## 1. EXECUTIVE SUMMARY

We spent this session rigorously auditing the entire signal pipeline for the EURUSD trading system. **The key finding is that ALL existing ML edge was an artifact of a lookahead leak.** After fixing the leak, standard 15-minute technical indicators have zero predictive power (AUC=0.5149 with 157k samples — this is definitive).

The user has approved **Path C: Session-Range Breakout + Tick-Microstructure Quality Gating** as the next direction. **No code has been written for Path C yet.** Implementation should begin immediately.

---

## 2. CRITICAL FINDINGS FROM THIS SESSION

### 2a. HTF Lookahead Leak (the most important finding)

**Location:** `strategies/feature_engineering_v3.py` → `_resample_ohlcv()` method

**Bug:** Uses pandas defaults (`label='left', closed='left'`) when resampling 15m bars to 1h/4h. Combined with `.ffill()`, this causes future bars to leak into current features.

- 98.7% of bars affected
- Average 7.4 pips of future information leaked
- When fixed to `label='right', closed='right'`, ALL model edge disappears

**Current state:** Reverted to original (leaked) version with a WARNING comment added. Production still uses leaked model. A backup exists at `models/ml_model_mtf_v3_xgb_leaked_backup.pkl`.

### 2b. Signal Edge Test Results

| Signal Source | Edge vs Random | Verdict |
|---|---|---|
| Breakout (10-bar high/low + velocity) | -0.6 pp (32.9% vs 33.5% random) | **Zero edge** |
| v2 RF40 model | Never reaches confidence threshold | **Zero edge** |
| v3 XGB model (leaked features) | +19.1 pp at thr=0.70 | **Fake — all from leak** |
| v3 XGB model (clean features) | -3.8 pp | **Zero edge** |
| Clean retrained model (2024-2025) | -4.8 pp (CV accuracy 52.3%) | **Zero edge** |
| Clean retrained model (ALL 2015-2024) | +0.7 pp (AUC=0.5149) | **Zero edge** |

**Conclusion:** Standard 15m technicals (MACD, RSI, ADX, BBands, EMA, SMA, returns, etc.) are definitively non-predictive for EURUSD direction.

---

## 3. PATH C — WHAT TO BUILD NEXT

The user approved this approach. **Start implementing immediately.**

### Concept

1. **Base Signal: Session-Range Breakouts** — Structural FX phenomenon where London session open (07:00-09:00 UTC) breaks the Asian session range (00:00-07:00 UTC). This is well-documented in FX and has structural reasons (liquidity injection).

2. **Quality Gate: Tick-Microstructure Features** — Instead of predicting direction (which standard technicals can't do), predict *which breakouts are real vs fake* using information most participants don't have: tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread from the constituent 1000-tick bars.

3. **Meta-Labeling** — The ML model does NOT predict direction. It predicts whether a given session breakout will reach its TP (1.5 ATR) before its SL (1.4 ATR). This is a fundamentally different task from direction prediction.

### Implementation Plan (5 Steps)

**Step 1: Build session-range breakout signal generator** (START HERE)
- Work on 15m bars resampled from tick bars
- Define Asian session: 00:00-07:00 UTC (roughly 28 fifteen-minute bars)
- Compute Asian high/low range each day
- Signal fires when a London-session bar (07:00-09:00 UTC) closes above Asian high (LONG) or below Asian low (SHORT)
- Also consider: ATR expansion after compression, NY session (13:00-15:00 UTC) breakouts
- Output: DataFrame with columns [timestamp, direction, asian_high, asian_low, breakout_bar_close, atr_at_signal, ...]

**Step 2: Test base signal edge vs random** (GO/NO-GO GATE)
- Reuse `trading_system_v4/scripts/test_v2_signal_edge.py` framework
- Simulate TP=1.5 ATR, SL=1.4 ATR, SPREAD=0.0001, LOOKAHEAD=100 bars
- Compare session breakout WR vs random entry WR
- Break-even WR = 48.3% (for TP/SL ratio of 1.5/1.4)
- **If session breakouts don't beat random, STOP and reconsider**

**Step 3: Add tick-bar microstructure features**
- For each session breakout signal, look up the constituent tick bars (from `eurusd_1000t_bars.parquet`)
- Compute features at signal time from recent tick bars:
  - `tick_velocity` — ticks per second (institutional flow intensity)
  - `vol_imbalance` — buy vs sell volume asymmetry
  - `buy_ratio` — fraction of volume on bid side
  - `avg_spread` — market tightness
  - `max_spread` — liquidity gaps
  - Rolling aggregates: mean/std of above over last N tick bars
  - Asian range width in ATR multiples (compression indicator)
  - Time since session open (early breaks more reliable)

**Step 4: Meta-label and train**
- Reuse pipeline from `trading_system_v4/scripts/meta_labeling_v3_signal.py`
- Swap signal source to session breakouts
- Features = tick microstructure (NOT standard technicals)
- Target = binary TP hit (y_tp)
- Use purged time-series CV (already implemented in train script)
- XGBoost meta-classifier

**Step 5: Validate OOS**
- Ensure edge holds in true out-of-sample
- Check for any new leakage patterns
- Verify feature importance makes intuitive sense

---

## 4. KEY DATA FILES

### Tick Bars (PRIMARY DATA SOURCE)
- **File:** `trading_system_v4/data/eurusd_1000t_bars.parquet`
- **Size:** 266,224 bars, 2015-01-01 to 2026-02-24
- **Columns:** timestamp, open, high, low, close, total_volume, tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread
- **Note:** tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread are the microstructure features — these are the key differentiator for Path C

### 15-Minute Bars
- Resampled from tick bars: 176,783 bars
- Use `label='right', closed='right'` when resampling (the CLEAN way)

### Models (current production — leaked, do not use for new work)
- `models/ml_model_mtf_v3_xgb.pkl` — original production model (uses leaked features)
- `models/ml_model_mtf_v3_xgb_leaked_backup.pkl` — backup copy

### Meta-Labeled Datasets (INVALIDATED — do not use)
- `trading_system_v4/data/meta_labeled_v3_signal_thr65.parquet` — 100,281 rows, built on leaked signal

---

## 5. REUSABLE INFRASTRUCTURE (use these for Path C)

### `trading_system_v4/scripts/test_v2_signal_edge.py`
- Tests any signal's edge vs random baseline
- TP/SL simulation on 15m bars
- **Use for Step 2** — just need to feed it session breakout signals

### `trading_system_v4/scripts/meta_labeling_v3_signal.py`
- `_simulate()` function computes y_tp (TP/SL binary) and y_mfe (MFE in ATR multiples)
- Full meta-labeling pipeline
- **Use for Step 4** — swap signal source and features

### `trading_system_v4/scripts/train_meta_model_v3_signal.py`
- Purged time-series CV, OOF lift analysis, period decomposition
- XGBClassifier meta-model training
- **Use for Step 4** — swap features

### `trading_system_v4/scripts/retrain_v3_xgb_clean.py`
- Self-contained clean retrainer (confirmed clean features = no edge)
- Shows correct `label='right', closed='right'` resampling

---

## 6. SIMULATION CONSTANTS

```
TP = 1.5 × ATR(14)
SL = 1.4 × ATR(14)
SPREAD = 0.0001 (1 pip)
LOOKAHEAD = 100 bars (15m bars = 25 hours)
BREAK_EVEN_WR = 48.3%  (for this TP/SL ratio)
```

---

## 7. PYTHON ENVIRONMENT

```
Virtualenv: c:\nautilus0\.venv
Key packages: xgboost, scikit-learn, pandas, numpy, joblib, pyarrow
Activate:    .venv\Scripts\activate
```

---

## 8. KEY STRATEGIES & FEATURE ENGINEERING FILES

- `strategies/feature_engineering_v3.py` — v3 features (50 cols), HTF leak present with WARNING comment
- `strategies/feature_engineering_v2_rf40.py` — v2 RF40 features (proven zero edge)
- `strategies/feature_engineering_4h.py` — 4h features
- `retrain_model.py` — original v3 XGB trainer (uses NautilusTrader catalog)
- `strategies/ml_strategy_mtf_v3_hmtf.py` — v3 HMTF live strategy

---

## 9. THINGS TO AVOID

1. **Do NOT use standard 15m technical indicators as ML features.** AUC=0.5149 with 157k samples is definitive proof they have no edge for EURUSD direction.
2. **Do NOT use v3 leaked model/features for new work.** Keep them running in production (they're already there) but don't build on top of them.
3. **Do NOT change v2 behavior** unless explicitly asked (per copilot-instructions.md).
4. **Watch for new leakage patterns** — any feature computed from future bars, any label that peeks at future data.
5. **Break-even WR is 48.3%**, not 50%. A signal showing 50% WR has only +1.7 pp edge, barely meaningful.

---

## 10. WHY PATH C SHOULD WORK (rationale)

1. **Session breakouts have structural reasons** — London open injects massive liquidity into thin Asian markets. This creates directional impulses that are not random noise.

2. **Tick microstructure captures information asymmetry** — Most retail/institutional participants only see OHLCV. Tick velocity, volume imbalance, and spread dynamics reveal the *quality* of participation behind a price move.

3. **The ML task is different** — We're NOT asking "which direction will price go?" (proven impossible with technicals). We're asking "given a session breakout in direction X, will it follow through to 1.5 ATR?" This is a signal quality classification problem, which ML can plausibly solve.

4. **No HTF needed** — All features come from the same timeframe (tick bars aggregated to signal time). No resampling, no ffill, no lookahead risk from HTF alignment.

---

## 11. SESSION HISTORY (for context)

This session was Session #3 in a multi-day research arc:
- **Session 1 (2026-02-23 AM):** Built tick-bar download pipeline, started data collection
- **Session 2 (2026-02-23 PM):** Built build_tick_bars.py, started processing
- **Session 3 (2026-02-24, this session):**
  - Tested breakout signals → zero edge
  - Tested v2/v3 ML signals → v3 appeared +19 pp
  - Built meta-labeling pipeline on v3 signals → AUC=0.69 (looked great)
  - Audited for leaks → found HTF ffill lookahead in `_resample_ohlcv`
  - Confirmed leak explains 100% of v3 edge
  - Clean retrain on ALL data → AUC=0.5149 (zero edge)
  - Evaluated 4 paths forward → recommended Path C
  - User approved Path C
  - **Session ended before Path C implementation began**

---

## 12. FIRST ACTIONS FOR NEW SESSION

```
1. Read this handover file
2. Read .github/copilot-instructions.md for project rules
3. Verify tick bars exist:
   python -c "import pandas as pd; df=pd.read_parquet('trading_system_v4/data/eurusd_1000t_bars.parquet'); print(f'{len(df):,} bars, {df.timestamp.min()} to {df.timestamp.max()}')"
4. Create: trading_system_v4/scripts/session_breakout_signal.py
   - Build Asian range + London breakout signal generator
5. Create: trading_system_v4/scripts/test_session_breakout_edge.py
   - Test base signal edge vs random (GO/NO-GO gate)
6. If edge exists → proceed to Steps 3-5 from Section 3
```
