# SESSION HANDOVER — 2026-02-24 (Session 4, End of Day)

## EURUSD Trading System — Comprehensive Signal & Feature Audit

Read this file at the start of a new session to resume exactly where we left off.

---

## 1. EXECUTIVE SUMMARY

This session **exhaustively tested every signal and feature family** available for EURUSD direction prediction at 15-minute resolution. The verdict is unambiguous:

**EURUSD at the 15-minute timeframe is efficiently priced. No feature family we tested can predict direction with enough accuracy to overcome transaction costs.**

We also built a **replay-mode training pipeline** that computes HTF features exactly as the live system would see them (partial-hour bars), proving the train/serve skew issue is real and confirming the model has no genuine edge under any feature alignment mode.

### Results Summary

| Signal / Feature Family | Best AUC or WR | Edge vs Random | Verdict |
|---|---|---|---|
| v3 XGB on leaked batch features | AUC 0.756 | +25.6 pp | **FAKE — lookahead** |
| v3 XGB on clean features (label=right) | AUC 0.519 | +0.7 pp | **Zero edge** |
| v3 XGB on replay features (live-equiv) | AUC 0.519 | +0.6 pp | **Zero edge** |
| Session range breakouts (Asian→London) | WR 42.8% | +0.2 pp vs 42.6% random | **Zero edge** |
| Session range breakouts (London→NY) | WR 42.7% | +0.1 pp | **Zero edge** |
| 15 tick microstructure signal configs | WR 33.5-45.0% | -3.3 to -9.9 pp | **Zero edge** |
| Multi-horizon micro sweep (7 TP/SL) | WR ±1 pp of random | noise | **Zero edge** |
| XGBoost on 62 microstructure features | AUC 0.516 | +0.8 pp | **Zero edge** |
| Next-bar direction from vol_imbalance | 51.2% hit rate | +1.2 pp | **Zero edge** |

---

## 2. HTF BATCH vs LIVE ALIGNMENT — THE CRITICAL FINDING

### 2a. The Three Modes

The v3 model computes 1h/4h features via `_resample_ohlcv()` in `strategies/feature_engineering_v3.py`.
Using `label='left', closed='left'` (pandas default), three different behaviors emerge:

| Mode | What "1h_close" contains at 08:15 | Nature |
|---|---|---|
| **BATCH** (training) | 08:45 close (end-of-hour) | Lookahead — sees 3 bars into the future |
| **LIVE** (inference) | 08:15 close (current bar itself) | Degenerate — 1h_close == 15m_close always |
| **CLEAN** (label=right) | 08:00 close (previous hour end) | Correct — only past data |

### 2b. Quantified Impact

- **Live 1h_close == current 15m close for 100% of bars** (verified empirically)
- The "1h" feature in live carries **zero higher-timeframe information** — it's a copy of the current price
- For derived indicators (RSI, MACD, SMA): direction agreement between batch and live is 87-99%
- Magnitude error: 4-25% depending on feature
- The model was **never exposed to the live feature distribution during training**

### 2c. Replay Training Proof

Trained XGBoost under all three modes with purged walk-forward CV (176k samples, 4 folds):

| Mode | LONG AUC | SHORT AUC |
|---|---|---|
| BATCH (leaked) | **0.7562** | **0.7553** |
| CLEAN (label=right) | 0.5186 | 0.5147 |
| REPLAY (live-equiv) | 0.5192 | 0.5149 |

REPLAY ≈ CLEAN. The partial-hour perturbation adds no exploitable information.
The batch "edge" (AUC 0.756) is **100% from lookahead**.

---

## 3. WHAT WAS TESTED THIS SESSION (Path C)

### 3a. Session Range Breakouts (Step 1 of Path C)

**Script:** `trading_system_v4/scripts/session_breakout_signal.py`

- Asian range: 00:00-07:00 UTC → breakout at London open 07:00-10:00 UTC
- London range: 07:00-13:00 UTC → breakout at NY open 13:00-16:00 UTC
- Tested tight/wide range filters, yearly breakdown
- **Result:** London breakout WR=42.8%, NY breakout WR=42.7%, random WR=42.6%. **Zero edge.**

### 3b. Tick Microstructure as Direct Signal (Step 2 of Path C)

**Script:** `trading_system_v4/scripts/test_microstructure_edge.py`

- Tested 15 configurations: vol_imbalance z-score, buy_ratio extremes, velocity+imbalance combos, spread+imbalance, composite signals
- All 15 configs scored between -3.3 pp and -9.9 pp vs random
- **Result:** Zero edge across every configuration.

### 3c. Multi-Horizon Microstructure Sweep

**Script:** `trading_system_v4/scripts/test_microstructure_horizon.py`

- 7 TP/SL configurations (from tight 0.8/0.7 to wide 3.0/2.5 ATR)
- Momentum vs fade strategies
- Signal strength sweep (z-thresholds 1.0 to 3.0)
- Next-bar direction prediction (vol_imbalance z>2 → 51.2%, barely above 50%)
- Forward return correlations: r=0.0007 (1-bar) to r=0.006 (32-bar) — all negligible
- **Result:** Zero edge at any horizon.

### 3d. XGBoost on 62 Microstructure Features

**Script:** `trading_system_v4/scripts/test_microstructure_ml.py`

- 62 features from tick bars (raw + rolling aggregates + cross-features)
- Purged 5-fold time-series CV, 176k samples
- LONG AUC=0.5158, SHORT AUC=0.5156
- Top features were time-based (is_london, hour, dow), not microstructure
- **Result:** Zero predictive power in tick microstructure for EURUSD.

### 3e. HTF Batch/Live Alignment Investigation

**Scripts:**
- `trading_system_v4/scripts/_trace_htf_alignment.py` — initial pandas resampling trace
- `trading_system_v4/scripts/_quantify_htf_leak.py` — raw 1h close comparison across 3 modes
- `trading_system_v4/scripts/_htf_feature_diff.py` — derived feature comparison (RSI, MACD, etc.)

**Result:** Batch ≠ Live. See Section 2 above.

### 3f. Replay Mode Training

**Script:** `trading_system_v4/scripts/train_v3_replay.py`

- Efficient replay: pre-compute completed HTF bars + partial current-period bars
- Sliding window of 100 completed bars + 1 partial → compute indicators
- ~15 minutes for 176k bars (O(n × window) instead of O(n²))
- **Result:** AUC 0.519 — identical to clean. See Section 2c.

---

## 4. KEY DATA FILES

### Tick Bars (PRIMARY DATA SOURCE)
- **File:** `trading_system_v4/data/eurusd_1000t_bars.parquet`
- **Size:** 266,224 bars, 2015-01-01 to 2026-02-24
- **Columns:** timestamp, open, high, low, close, total_volume, tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread, buy_volume, sell_volume
- **Note:** Microstructure columns (tick_velocity, vol_imbalance, buy_ratio, avg_spread, max_spread) were tested exhaustively — zero predictive power for EURUSD direction

### 15-Minute Bars
- Resampled from tick bars: 176,783 bars
- Use `label='right', closed='right'` when resampling (the CLEAN way)

### Training Data
- `trading_system_v4/data/training_features.parquet` — 5m bars with 32 features
- `trading_system_v4/data/training_features_htf.parquet` — 5m + 15m + 1D HTF features (96 features)
- `trading_system_v4/data/training_labeled.parquet` — labeled 5m dataset
- `trading_system_v4/data/training_labeled_htf.parquet` — labeled 5m+HTF dataset

### Models (ALL invalidated for new work)
- `models/ml_model_mtf_v3_xgb.pkl` — production v3 (leaked features, fake edge)
- `models/ml_model_mtf_v3_xgb_leaked_backup.pkl` — backup of leaked model
- `trading_system_v4/model/hybrid_model_v4_eurusd_*.pkl` — v4 models (trained on NautilusTrader catalog data)

### Reports
- `trading_system_v4/HTF_ALIGNMENT_REPORT.md` — detailed HTF batch/live/clean comparison

---

## 5. CODEBASE STRUCTURE

### Feature Engineering
| File | What it does | Edge? |
|---|---|---|
| `strategies/feature_engineering_v3.py` | 50 features (40 15m + 10 HTF). Has WARNING on `_resample_ohlcv`. | **No** (AUC 0.51 clean) |
| `strategies/feature_engineering_v2_rf40.py` | v2 RF40 features | **No** |
| `trading_system_v4/features/feature_engineering.py` | v4 32 features per bar | **No** (AUC ~0.52) |

### Live Trading (Production — uses leaked model)
| File | Description |
|---|---|
| `strategies/ml_strategy_mtf_v2_entry_confirmed.py` | Live v3 HMTF strategy. Calls `latest_v3_row()` with bars from `bars_buffer_15m`. |
| `strategies/feature_engineering_v3.py` | `latest_v3_row()` → `compute_v3_features()` → `_resample_ohlcv()` (leaked) |

### Test Scripts Created This Session
| File | What it tests | Result |
|---|---|---|
| `scripts/session_breakout_signal.py` | Asian→London, London→NY breakouts | Zero edge |
| `scripts/test_microstructure_edge.py` | 15 microstructure signal configs | Zero edge |
| `scripts/test_microstructure_horizon.py` | Multi-horizon, momentum/fade, strength sweep | Zero edge |
| `scripts/test_microstructure_ml.py` | XGBoost on 62 micro features | AUC 0.516 |
| `scripts/_trace_htf_alignment.py` | Pandas resampling behavior trace | Batch ≠ Live proven |
| `scripts/_quantify_htf_leak.py` | Raw 1h close comparison (3 modes) | 100% bars differ |
| `scripts/_htf_feature_diff.py` | Derived feature diffs (RSI, MACD, etc.) | 87-99% direction agree |
| `scripts/train_v3_replay.py` | Replay-mode training (3-way comparison) | Replay AUC = Clean AUC ≈ 0.52 |

All scripts under `trading_system_v4/scripts/`.

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

## 8. WHAT HAS BEEN DEFINITIVELY RULED OUT

| Approach | Why it fails | Evidence |
|---|---|---|
| Standard 15m technicals (MACD, RSI, ADX, BBands, EMA, SMA, returns) | Zero predictive power | AUC=0.5149 with 157k samples |
| Multi-timeframe (1h, 4h) technical features | Only "worked" due to lookahead leak | Batch AUC 0.756 → Clean/Replay AUC 0.519 |
| Session range breakouts | WR identical to random | 42.8% vs 42.6% random across 10 years |
| Tick microstructure direct signals | Zero correlation with forward returns | r=0.0007 to r=0.006 |
| Tick microstructure as ML features | Top features are time-of-day, not micro | AUC 0.516 with 62 features |
| Tick velocity + volume imbalance combos | No predictive power at any threshold | 15 configs, 7 horizons tested |
| v3 model in live (train/serve skew) | Sees degenerate features (1h_close = current price) | 100% of bars affected |

---

## 9. POSSIBLE PATHS FORWARD

These are directions that have **NOT** been tested and might be fruitful:

### A. Different Instruments
- EURUSD may be the most efficient FX pair. Try: GBPJPY, AUDUSD, XAUUSD (gold), or index futures
- The tick bar infrastructure (`build_tick_bars.py`) already supports any instrument

### B. Different Timeframes
- Test 1h or 4h bars instead of 15m — slower signals may have structure
- Or ultra-short: tick-by-tick market making (very different paradigm)

### C. Different Target Formulations
- Instead of direction prediction, predict: volatility regimes, range (high-low), or time-to-move
- Volatility prediction is structurally easier than direction prediction

### D. Fundamental / Calendar Signals
- Economic data releases (NFP, CPI, ECB/Fed decisions) create structural moves
- Cross-asset flows (bond yields, equity risk-off)
- These require external data feeds not currently in the system

### E. Execution Alpha
- Use microstructure for better fills rather than directional prediction
- Optimal execution timing, spread compression detection
- Requires different infrastructure (not a prediction model)

### F. Ensemble of Weak Signals
- Combine many near-zero-edge signals, each from different feature families
- Requires careful correlation analysis to ensure independence
- Risk: if all signals are truly zero-edge, combining them produces zero-edge

---

## 10. SESSION HISTORY

| Session | Date | Key Work |
|---|---|---|
| 1 | 2026-02-23 AM | Built tick-bar download pipeline |
| 2 | 2026-02-23 PM | Built `build_tick_bars.py`, data collection |
| 3 | 2026-02-24 early | Audit: found HTF leak, all v3 edge fake. WR tests. Approved Path C. |
| 4 | 2026-02-24 this session | **Path C full implementation → all zero edge. HTF alignment investigation. Replay training. Comprehensive dead-end confirmation.** |

---

## 11. THINGS TO AVOID

1. **Do NOT use standard 15m technical indicators as ML features.** Proven zero edge (AUC 0.52, 176k samples, 4 CV folds).
2. **Do NOT use session range breakouts.** Proven identical to random (42.8% vs 42.6%).
3. **Do NOT use tick microstructure for EURUSD direction.** Proven zero edge (62 features, 176k samples).
4. **Do NOT use v3 leaked model/features for new work.** The batch leak (AUC 0.756) is fake.
5. **Do NOT change v2 behavior** unless explicitly asked (per copilot-instructions.md).
6. **Do NOT assume the live model "probably works."** The train/serve skew is proven — live features are from a distribution the model never saw.

---

## 12. FIRST ACTIONS FOR NEW SESSION

```
1. Read this handover file
2. Read .github/copilot-instructions.md for project rules
3. Decide which path from Section 9 to pursue
4. If trying a new instrument:
   python -m trading_system_v4.scripts.download_tick_data --symbol GBPJPY
   python -m trading_system_v4.scripts.build_tick_bars
5. If trying a different timeframe or target:
   Modify the labeling in add_labels.py or create a new labeler
6. If fundamentals: need to build a new data source integration
```
