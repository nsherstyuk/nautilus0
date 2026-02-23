# Session Handover — February 22, 2026 (Late Night)

## Project: trading_system_v4 — Hybrid Modular Trading System

**Do NOT touch v2/v3 systems.** This is a new parallel implementation.

---

## Copy-Paste Prompt for Next Agent

```
I am continuing development of a new modular hybrid trading system at
c:\nautilus0\trading_system_v4\

Read this file first and use it as your full context:
  c:\nautilus0\SESSION_HANDOVER_2026-02-22.md

Do NOT touch the existing v2/v3 system files.
Continue from the "Immediate Next Steps" section below.
Act autonomously, verify each step, critique your own work, and keep
changes minimal and modular.
```

---

## Overall Project Goal

Build a complete ML-driven trading system that:
1. Ingests historical OHLCV data from the NautilusTrader Parquet catalog
2. Engineers 32 clean, non-redundant features per bar
3. Labels data using forward SL/TP simulation (same logic as v3)
4. Trains an XGBoost/LightGBM model with walk-forward CV + isotonic calibration
5. Runs live on a real NautilusTrader feed (replacing the mock adapter)
6. Executes paper trades first; then live IBKR orders via `ExecutionEngine`
7. Supports HTF (15m) feature injection with strict no-lookahead guarantee

---

## What Was Built in Previous Sessions

| Module | File | Status |
|---|---|---|
| Data adapter | `trading_system_v4/data/nautilus_adapter.py` | Working — mock stream |
| Feature engineering | `trading_system_v4/features/feature_engineering.py` | **Overhauled this session** |
| Execution engine | `trading_system_v4/execution/execution_engine.py` | Working — stub broker |
| Risk manager | `trading_system_v4/risk/risk_manager.py` | Working — size + drawdown |
| Logger | `trading_system_v4/monitoring/logger.py` | Working — rotating files |
| Live runner | `trading_system_v4/scripts/run_live_hybrid.py` | Working — test mode validated |
| Training pipeline | `trading_system_v4/scripts/build_training_dataset.py` | **Built + fixed this session** |

---

## What Was Done This Session

### 1. Training Data Pipeline (`build_training_dataset.py`) — built from scratch

**What it does:**
- Recursively finds all Parquet files under `data/historical/data/bar/`
- Filters to a single bar size (default `5-MINUTE`, configurable via `sys.argv[1]`)
- Decodes NautilusTrader binary-encoded price columns (`struct.unpack('<q', raw)[0] / 1e9`)
- Processes **each symbol independently** before concatenation — prevents cross-symbol contamination of `return_1`, `open_gap`, ATR, EMA etc.
- Derives UTC `timestamp` from `ts_init` (nanoseconds)
- Handles FX zero-volume gracefully
- Calls `add_features(df)` to attach the 32-feature set
- Reports NaN coverage; outputs a single `training_features.parquet`

**Run command:**
```powershell
cd c:\nautilus0
python -m trading_system_v4.scripts.build_training_dataset          # default: 5-MINUTE
python -m trading_system_v4.scripts.build_training_dataset 15-MINUTE
```

**Output:** `trading_system_v4/data/training_features.parquet`
- 624,171 rows × 42 columns
- Symbols: EURUSD.IDEALPRO, GBPUSD.IDEALPRO, USDCHF.IDEALPRO
- Date range: 2022-12-27 → 2026-02-19

**Bugs fixed in the process:**
| Bug | Fix |
|---|---|
| `pd.to_numeric(bytes)` → all NaN (100% broken prices) | `struct.unpack('<q', raw)[0] / 1e9` decoder |
| No `timestamp` column → session features silently skipped | Derived from `ts_init` nanoseconds |
| All bar sizes mixed (1m/3m/5m/15m/1d in one DataFrame) | Filter by `bar_size` before loading |
| Cross-symbol row contamination | Per-symbol loop before `add_features()` |
| FX volume = 0 → `volume_spike = inf` | Volume substitution removed; volume features dropped |
| `pct_change()` FutureWarning | Added `fill_method=None` |

---

### 2. Feature Engineering (`feature_engineering.py`) — major overhaul

**Before this session:** 37 features, 2 constant, 6 highly redundant pairs.

**After this session:** **32 features, zero constant, highest correlation = 0.93.**

#### Removed features (7 total):
| Feature | Reason |
|---|---|
| `volume_spike` | Constant = 1.0 for all FX bars (zero variance) |
| `log_volume` | Constant = 0.693 for all FX bars (zero variance) |
| `ema20_slope` | r = 0.990 with `ema_ratio_5_20` — duplicate |
| `rsi_9` | r = 0.972 with `rsi_14` — duplicate |
| `atr_5` (in df) | Not dimensionless; kept as local var for computing `atr_ratio` |
| `atr_14` (in df) | Not dimensionless; kept as local var for computing `atr_norm` |
| `open_gap` | 75th pct = 0 on continuous 5m FX; near-zero variance |

#### Added features (2 total):
| Feature | Description |
|---|---|
| `adx_14` | Wilder ADX(14) normalised to [0, 1]. Trend _strength_ independent of direction. Mean 0.24, max 0.82. |
| `is_session_open` | 1.0 when consecutive bar timestamp gap > 2 hours (weekend/holiday re-open). 455 hits / 624k rows. |

#### Other fixes:
- `_atr_series` now uses Wilder's `ewm(com=period-1)` — was inconsistently using `ewm(span=period)` while `_rsi_series` already used Wilder's
- Added `_adx_series` helper using Wilder's smoothing throughout
- Removed FX-specific volume substitution logic (volume features gone entirely)
- `FeatureEngineer` class improvements:
  - `is_ready` property: `True` when `bars_loaded >= WARMUP_BARS (200)`
  - `bars_loaded` property: explicit count
  - `add_bar()` returns `{}` during warm-up instead of computing on insufficient data
  - `_NON_FEATURE_COLS` frozenset: centralised exclusion list
  - `np.floating` / `np.integer` added to type check in `_compute_features`

#### Final 32-feature set:
```
Price action : body_ratio, close_position, upper_wick, lower_wick, bar_range_norm
Momentum     : return_1, return_5, return_12, return_24
Volatility   : atr_ratio, atr_norm, vol_5, vol_20, vol_ratio
Trend/EMA    : ema_ratio_5_20, close_vs_ema20, close_vs_ema50, close_vs_ema200
Oscillators  : rsi_14, adx_14
Session/time : hour_sin, hour_cos, dow_sin, dow_cos, is_london, is_ny, is_overlap, is_session_open
Regime       : vol_regime, range_position
Pattern      : return_max_10, return_min_10
```

---

## Current Folder Structure

```
trading_system_v4/
  config/                    # env-driven config loaders
  data/
    nautilus_adapter.py      # live bar streaming + deduplication (mock stream)
    training_features.parquet  ← GENERATED: 624k rows, 32 features, 3 symbols
  execution/
    execution_engine.py      # order routing, portfolio tracking (stub broker)
  features/
    feature_engineering.py   # 32-feature set — batch add_features() + live FeatureEngineer
  model/                     # EMPTY — model training not yet done
  monitoring/
    logger.py                # RotatingFileHandler setup
  risk/
    risk_manager.py          # position size + drawdown checks
  scripts/
    build_training_dataset.py  # ← BUILT THIS SESSION
    run_live_hybrid.py         # main live runner
    run_pipeline.py
  README.md
```

---

## Historical Data Available

Located at `c:\nautilus0\data\historical\data\bar\`:

| Symbol | Bar sizes available | Coverage |
|---|---|---|
| EURUSD.IDEALPRO | 1m, 2m, 3m, 5m, 15m, 1d | Dec 2023 → Feb 2026 |
| GBPUSD.IDEALPRO | 1m, 2m, 3m, 5m, 15m, 1d | Dec 2022 → Feb 2026 |
| USDCHF.IDEALPRO | 1m, 2m, 3m, 5m, 15m, 1d | Dec 2022 → Feb 2026 |

Top-level CSVs in `data/historical/` are mirors from the ingestion script — safe to use for inspection.
NautilusTrader Parquet format: prices stored as little-endian int64 × 1e9; decoded by `build_training_dataset.py`.

---

## Immediate Next Steps (Priority Order)

### 1. Label Engineering — HIGHEST PRIORITY
**Script to create:** `trading_system_v4/scripts/add_labels.py`

- Load `trading_system_v4/data/training_features.parquet`
- Process **per symbol** to prevent cross-symbol label leakage
- For each row at index `i`:
  - `atr = atr_norm * close` (reconstruct absolute ATR from `atr_norm`)
  - `tp_level = close + atr * 1.4`
  - `sl_level = close - atr * 1.8`
  - Scan forward bars `i+1 … i+60`:
    - `Label = 1` if any `high >= tp_level` is hit first
    - `Label = 0` if any `low <= sl_level` is hit first
    - `Drop row` if neither is hit within 60 bars (ambiguous)
- Add column `y` to DataFrame
- Output: `trading_system_v4/data/training_labeled.parquet`
- Report: label balance (target ~30–50% positives), rows kept vs dropped

### 2. Train Model
**Script to create:** `trading_system_v4/scripts/train_model.py`

- Load `training_labeled.parquet`
- Feature columns = the 32 listed above (exclude `timestamp`, `symbol`, `bar_size`, OHLCV, `y`)
- Walk-forward cross-validation: 3 folds, each fold = one year of data
  - Fold 1: train 2023, test 2024
  - Fold 2: train 2023–2024, test 2025
  - Fold 3: train 2023–2025, test 2026 YTD
- Model: XGBoost (`XGBClassifier`) or LightGBM (`LGBMClassifier`)
  - Target metric: precision@0.6 threshold ≥ 65%; also report recall, F1, ROC-AUC
  - Use `scale_pos_weight` for class imbalance
- After final training: isotonic regression calibration (`sklearn.calibration.CalibratedClassifierCV`)
- Save:
  - `trading_system_v4/model/hybrid_model_v1.pkl` — trained model
  - `trading_system_v4/model/calibrator_v1.pkl` — isotonic calibrator
  - `trading_system_v4/model/feature_list_v1.json` — ordered feature names (must match at inference)

### 3. Connect Model to Live Runner
- Load model + calibrator in `run_live_hybrid.py`
- On each new bar: call `fe.add_bar(bar)` → if `fe.is_ready` → `model.predict_proba(features)` → calibrate → threshold at 0.60
- Add session/hour gate: skip inference if `is_london == 0 and is_ny == 0` (Asian session)
- Log: timestamp, symbol, raw_prob, calibrated_prob, signal (1/0/skip)

### 4. HTF Feature Injection (15m)
- Separate `FeatureEngineer` instance for 15m bars
- On each 5m bar: inject the most recently *completed* 15m bar's features as prefix `htf_*`
- No-lookahead rule: 5m bar at T uses the 15m bar that closed at or before T
- Prefix all 15m features with `htf_` to avoid name collision
- This will expand the feature vector from 32 → ~60 features; retrain model after adding

### 5. Replace Mock Data Adapter
- `trading_system_v4/data/nautilus_adapter.py`: replace `stream_loop()` mock with real NautilusTrader API
- Match composite subscription key convention: `(symbol, bar_size, what_to_show, use_rth)`
- Update reconnect / health-check logic
- Test against live IB feed (paper trading account)

### 6. Order Execution Wiring
- `ExecutionEngine.broker_api` is currently `None`
- Wire to real IBKR broker via `ib_insync` or NautilusTrader execution client
- ATR-based position sizing: `size = risk_per_trade / (atr * sl_multiplier)`
- Add realized P&L tracking to portfolio dict

### 7. End-to-End Paper Trade Test
- Run with real NautilusTrader feed + trained model
- Paper trade only (no real orders)
- Validate: prediction rate, feature coverage, dedup working, no lookahead

---

## Known Gaps / Risks

| Issue | Severity | Notes |
|---|---|---|
| No trained model | Critical | Pipeline built; labeling + training still needed |
| Mock data adapter | High | Must replace before any real trading |
| HTF features missing | Medium | 5m model lacks multi-timeframe context — add after first model trains |
| No order sizing logic | Medium | ExecutionEngine sends flat 1-lot |
| No live P&L tracking | Low | Portfolio dict tracks position, not realized P&L |
| Label balance unknown | Medium | Run `add_labels.py` to verify; if <20% positives, revisit ATR multipliers |
| atr_norm vs atr columns | Low | Labels use `atr_norm * close` to reconstruct ATR — verify this is correct at label time |

---

## Key Technical Conventions

### NautilusTrader Parquet Decoding
```python
import struct
price = struct.unpack('<q', bytes_value)[0] / 1e9  # little-endian int64 / 1e9
timestamp = pd.to_datetime(ts_init_nanoseconds, unit='ns', utc=True)
```

### Label Engineering Rule (from v3, copy exactly)
```python
tp_level = close + atr * 1.4   # TP multiplier
sl_level = close - atr * 1.8   # SL multiplier
lookahead_bars = 60             # ~5 hours on 5m
```

### Feature Engineering Entry Points
```python
# Batch (offline):
from trading_system_v4.features.feature_engineering import add_features
df_with_features = add_features(df)   # df must have open/high/low/close/timestamp per symbol

# Live (stateful):
from trading_system_v4.features.feature_engineering import FeatureEngineer
fe = FeatureEngineer(window=250)
features = fe.add_bar(bar_dict)   # returns {} until fe.is_ready (200 bars)
```

### Test Commands (all validated exit 0)
```powershell
cd c:\nautilus0

# Test live runner (mock stream, 5 bars, exits cleanly):
python -m trading_system_v4.scripts.run_live_hybrid test

# Rebuild training dataset (5-MINUTE bars):
python -m trading_system_v4.scripts.build_training_dataset

# Rebuild for a different bar size:
python -m trading_system_v4.scripts.build_training_dataset 15-MINUTE
```

---

## Do Not Touch

- `c:\nautilus0\strategies\` — v2/v3 live system
- `c:\nautilus0\models\` — v3 production model files
- `.env.mtf_v2`, `.env.mtf_v3` — live config
- Any file outside `trading_system_v4\` unless explicitly asked
