# Session Handover  February 22, 2026 (Night)

## Project: trading_system_v4  Hybrid Modular Trading System

**Do NOT touch v2/v3 systems.** This is a new parallel implementation.

---

## Copy-Paste Prompt for Next Agent

```
I am continuing development of a new modular hybrid trading system at
c:\nautilus0\trading_system_v4\

Read this file first and use it as your full context:
  c:\nautilus0\SESSION_HANDOVER.md

Do NOT touch the existing v2/v3 system files.
Continue from the "Immediate Next Steps" section below.
Act autonomously, verify each step, critique your own work, and keep
changes minimal and modular.
```

---

## What Was Built This Session

### Modules Implemented

| Module | File | Status |
|---|---|---|
| Data adapter | `trading_system_v4/data/nautilus_adapter.py` | Working  mock stream |
| Feature engineering | `trading_system_v4/features/feature_engineering.py` | Working  35 features |
| Execution engine | `trading_system_v4/execution/execution_engine.py` | Working  stub broker |
| Risk manager | `trading_system_v4/risk/risk_manager.py` | Working  size + drawdown |
| Logger | `trading_system_v4/monitoring/logger.py` | Working  rotating files |
| Live runner | `trading_system_v4/scripts/run_live_hybrid.py` | Working  test mode validated |

### Test Command (Validated  exits 0)

```powershell
cd c:\nautilus0
python -m trading_system_v4.scripts.run_live_hybrid test
```

Expected output: bars received, 35 live features logged, exits cleanly.

---

## Folder Structure

```
trading_system_v4/
  config/          # config loaders (env-driven)
  data/
    nautilus_adapter.py   # live bar streaming + deduplication
  execution/
    execution_engine.py   # order routing, portfolio tracking
  features/
    feature_engineering.py  # 35-feature set (batch + live)
  model/           # (empty  model training not yet done)
  monitoring/
    logger.py      # RotatingFileHandler setup
  risk/
    risk_manager.py  # position size + drawdown checks
  scripts/
    run_live_hybrid.py  # main live runner
  README.md
```

---

## 35-Feature Set (Group Summary)

| Group | Features |
|---|---|
| Price action | body_ratio, close_position, upper_wick, lower_wick, bar_range_norm, open_gap |
| Momentum | return_1, return_5, return_12, return_24 |
| Volatility | atr_5, atr_14, atr_ratio, atr_norm, vol_5, vol_20, vol_ratio |
| Trend / EMA | ema_ratio_5_20, close_vs_ema20, close_vs_ema50, close_vs_ema200, ema20_slope |
| Oscillators | rsi_9, rsi_14 |
| Volume | volume_spike, log_volume |
| Session / time | hour_sin, hour_cos, dow_sin, dow_cos, is_london, is_ny, is_overlap |
| Regime | vol_regime |
| Pattern | range_position, return_max_10, return_min_10 |

Full implementation in `trading_system_v4/features/feature_engineering.py`:
- `add_features(df)`  batch mode (DataFrame in, DataFrame with 35 extra columns out)
- `FeatureEngineer(window=250)`  stateful live mode, call `add_bar(bar_dict)` per bar

---

## Key Implementation Details

### NautilusDataAdapter (data/nautilus_adapter.py)
- Deduplication cache: set of (timestamp, symbol)  prevents double-processing same bar
- Cache window: 100 entries (LRU-style eviction)
- IMPORTANT: `stream_loop()` is currently a **mock** (generates synthetic bars). Replace with real NautilusTrader API call for production.
- Thread-safe: uses daemon thread, `on_bar_callback` called on that thread

### FeatureEngineer (features/feature_engineering.py)
- Warm-up needed: returns empty dict for first ~200 bars (rolling windows)
- `add_bar()` returns `dict[str, float]`  filter out NaN values before passing to model
- Window buffer: 250 bars of OHLCV history kept in memory per instance

### ExecutionEngine (execution/execution_engine.py)
- `self.broker_api = None`  set this to real broker before going live
- Portfolio dict: `{symbol: {'position': float, 'avg_price': float}}`

### RiskManager (risk/risk_manager.py)
- `check_risk(portfolio, signal)` returns `bool`
- Checks: max position size (default 1.0), drawdown limit (default 10%)

### run_live_hybrid.py
- Run with `python -m trading_system_v4.scripts.run_live_hybrid` (not `python trading_system_v4/...`)
- `test` arg runs test mode (5 synthetic bars, then exit)
- Health-check thread logs heartbeat every 60s

---

## Immediate Next Steps (Priority Order)

### 1. Training Data Pipeline (HIGHEST PRIORITY)
- Script: `trading_system_v4/scripts/build_training_dataset.py`
- Load historical OHLCV parquet from `c:\nautilus0\data\historical\` (or catalog)
- Apply `add_features(df)` to get 35 features per row
- Output: `trading_system_v4/data/training_features.parquet`

### 2. Label Engineering
- Simulate SL/TP-aware labels (same logic as v3 retrain):
  - Label=1 if any forward bar HIGH >= close + ATR*1.4 within 60 bars
  - Label=0 if any forward bar LOW <= close - ATR*1.8 within 60 bars
  - Drop ambiguous rows
- Add labels as column `y` to training parquet

### 3. Train Model
- Script: `trading_system_v4/scripts/train_model.py`
- XGBoost or LightGBM on 35 features + label `y`
- Walk-forward CV (3 folds), target precision ~65%+
- Save to `trading_system_v4/model/hybrid_model_v1.pkl`

### 4. Probability Calibration
- Add isotonic regression calibration pass after training
- Save calibrator alongside model

### 5. Connect Real NautilusTrader Feed
- Replace mock `stream_loop()` in `nautilus_adapter.py` with real API
- Match IB streamer conventions: composite subscription key (symbol + bar_size + what_to_show + use_rth)

### 6. HTF Feature Injection
- Add 15m/30m features to each 5m bar row
- Requirement: no lookahead  use most recently *completed* 15m bar
- Separate `FeatureEngineer` instance per timeframe

### 7. Session/Hour Filter
- Skip inference during Asian session / low-liquidity hours
- Already have `is_london`, `is_ny`, `is_overlap` features  use at entry gate

### 8. End-to-End Live Test
- Run with real NautilusTrader feed + trained model
- Paper trade first (no real orders)
- Validate: prediction rate, feature coverage, deduplication working

---

## Known Gaps / Risks

| Issue | Severity | Notes |
|---|---|---|
| Mock data adapter | High | Must replace before any real trading |
| No trained model yet | High | Pipeline not built, model file missing |
| No historical data path confirmed | Medium | Check `c:\nautilus0\data\historical\` exists |
| HTF features missing | Medium | 5m model lacks multi-timeframe context |
| No order sizing logic | Medium | ExecutionEngine sends flat 1-lot  needs ATR-based sizing |
| No live P&L tracking | Low | Portfolio dict tracks position but no realized P&L |

---

## Do Not Touch

- `c:\nautilus0\strategies\`  v2/v3 live system
- `c:\nautilus0\models\`  v3 production model files
- `.env.mtf_v2`, `.env.mtf_v3`  live config
- Any file outside `trading_system_v4\` unless explicitly asked
