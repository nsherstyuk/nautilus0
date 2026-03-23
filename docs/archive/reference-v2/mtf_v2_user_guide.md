# MTF V2 User Guide

This guide is the single source of truth for operating the **MTF V2** trading system in this repository:

- Live trading (IBKR + NautilusTrader)
- Backtesting (standard + dynamic sizing)
- Data ingestion (IBKR historical → Parquet catalog + CSV backups)
- ML model retraining
- Parameter grid optimization (simulation-based + YAML-driven)

> This repo is intended to contain **MTF V2 only**. Legacy strategy tooling may still exist in the workspace, but this guide documents **only the supported MTF V2 workflow**.

---

## 1) Quick Start (Most Common Commands)

### 1.1 Data ingestion (download / refresh history)

- Start TWS / IB Gateway first.
- Ensure `.env` is configured.

```powershell
python phase0_download_data.py
```

Or run ingestion directly:

```powershell
python data/ingest_historical.py
```

Verify catalog coverage:

```powershell
python data/verify_catalog.py
```

### 1.2 Backtest (MTF V2)

Standard backtest:

```powershell
python run_backtest_mtf_v2_full.py
```

Dynamic sizing backtest:

```powershell
python run_backtest_mtf_v2_full_dynamic_sizing.py
```

### 1.3 Live trading (MTF V2)

- Start TWS / IB Gateway first.
- Ensure `.env.mtf_v2` is configured (paper trading recommended).

```powershell
python live/run_live_mtf_v2.py
```

### 1.4 Retrain model (MTF features)

```powershell
python research/train_model_mtf.py
```

### 1.5 Grid optimization (simulation-based)

Quick run:

```powershell
python optimize_2pos_sim.py --quick --start 2024-01-01 --end 2024-10-31
```

Full run:

```powershell
python optimize_2pos_sim.py --start 2024-01-01 --end 2024-10-31
```

### 1.6 Grid optimization (YAML-driven, MTF V2)

This uses the repository’s YAML grid search framework to run the MTF V2 sweep runner.

```powershell
python optimization\grid_search.py --config optimization\configs\mtf_v2_smoke.yaml --no-resume --verbose
```

---

## 2) Repository Layout (MTF V2)

### 2.1 Entry points

- `live/run_live_mtf_v2.py`
- `run_backtest_mtf_v2_full.py`
- `run_backtest_mtf_v2_full_dynamic_sizing.py`
- `phase0_download_data.py`
- `data/ingest_historical.py`
- `research/train_model_mtf.py`
- `optimize_2pos_sim.py`

### 2.2 Core modules

- `strategies/ml_strategy_mtf_v2.py` (live strategy)
- `config/mtf_v2_config.py` (loads `.env.mtf_v2`)
- `config/ibkr_config.py` (loads `.env`)
- `patches/` (IB connection patch used by live runner)

### 2.3 Data storage

- Parquet catalog root: `data/historical/data/`
- CSV backups: `data/historical/*.csv`

> Large data is typically gitignored. Keep the directory structure, but don’t commit the bulk data.

---

## 3) Environment Files

This repo intentionally uses **two** environment files:

### 3.1 `.env` (data ingestion + generic IBKR)

Used by:
- `data/ingest_historical.py`
- `phase0_download_data.py`
- `config/ibkr_config.py`

Typical variables:
- `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`, `IB_ACCOUNT_ID`, `IB_MARKET_DATA_TYPE`
- `DATA_SYMBOLS`, `DATA_START_DATE`, `DATA_END_DATE`
- `CATALOG_PATH` (if applicable)

### 3.2 `.env.mtf_v2` (MTF V2 live + backtest)

Used by:
- `config/mtf_v2_config.py`
- `live/run_live_mtf_v2.py`
- `run_backtest_mtf_v2_full.py`
- `run_backtest_mtf_v2_full_dynamic_sizing.py`

Key variables:
- IBKR connection for V2: `MTF2_IBKR_HOST`, `MTF2_IBKR_PORT`, `MTF2_IBKR_CLIENT_ID`, `MTF2_IBKR_ACCOUNT`
- Trading instrument / bar type: `MTF2_INSTRUMENT`, `MTF2_BAR_TYPE`
- Model: `MTF2_MODEL_PATH`
- Strategy params: `MTF2_TOTAL_POSITION_SIZE`, `MTF2_POS1_FRACTION`, `MTF2_POS2_FRACTION`, `MTF2_SL_ATR_MULT`, `MTF2_POS1_TP_ATR_MULT`, ...
- Time filters: `MTF2_CONFIG_TIMEZONE`, `MTF2_EXCLUDED_HOURS_MODE`, `MTF2_EXCLUDED_HOURS_*`
- Backtest window: `MTF2_BACKTEST_START`, `MTF2_BACKTEST_END`, `MTF2_INITIAL_BALANCE`

### 3.3 Recommended workflow: keep multiple env variants

For safety and repeatability, keep personal copies outside git, e.g.:

- `.env.mtf_v2.paper`
- `.env.mtf_v2.live`
- `.env.mtf_v2.backtest`

Then copy the one you want into `.env.mtf_v2` before running.

---

## 4) Data Ingestion (IBKR → Parquet + CSV)

### 4.1 Prerequisites

- TWS / IB Gateway is running
- API enabled (socket clients)
- Host/port/client id match `.env`

### 4.2 Run ingestion

Preferred (guided):

```powershell
python phase0_download_data.py
```

Direct:

```powershell
python data/ingest_historical.py
```

### 4.3 What you should see

Outputs:
- Parquet: `data/historical/data/bar/<BAR_TYPE>/*.parquet`
- CSV: `data/historical/*.csv`

### 4.4 Verify catalog

```powershell
python data/verify_catalog.py
```

If you have catalog overlaps/corruption:

```powershell
python data/cleanup_catalog.py
```

---

## 5) Backtesting (MTF V2)

### 5.1 Standard backtest

```powershell
python run_backtest_mtf_v2_full.py
```

Typical outputs:
- `backtest_results/` (reports / CSV / plots, depending on the script)
- `logs/` (if logging is enabled in the run)

### 5.2 Dynamic sizing backtest

```powershell
python run_backtest_mtf_v2_full_dynamic_sizing.py
```

Dynamic sizing is controlled via `.env.mtf_v2` variables prefixed with `BT_`.

Common controls:
- `BT_DYNAMIC_SIZING_ENABLED`
- `BT_STARTING_EQUITY_USD`
- `BT_TARGET_MARGIN_USAGE`
- `BT_RISK_PER_TRADE_PCT`
- `BT_MIN_LOTS`, `BT_MAX_LOTS`

---

## 6) Live Trading (MTF V2)

### 6.1 Prerequisites

- Paper trading account recommended first
- TWS / IB Gateway running
- `.env.mtf_v2` configured
- Model file exists: `models/ml_model_mtf.pkl` (or whatever `MTF2_MODEL_PATH` points to)

### 6.2 Run

```powershell
python live/run_live_mtf_v2.py
```

### 6.3 Logs

Live runner configures logging via `config/logging.live.yaml` and writes into:

- `logs/live_mtf/`
  - `live_trading.log`
  - `strategy.log`
  - `orders.log`
  - `trades.log`
  - `errors.log`
  - `console_<timestamp>.log`

### 6.4 Important configuration consistency checks

If you are running **two-position mode** (POS1 + POS2):
- Ensure `MTF2_POS1_FRACTION + MTF2_POS2_FRACTION == 1.0`
- Ensure `MTF2_MAX_POSITIONS >= 2` (otherwise the strategy may refuse the second position)

---

## 7) ML Model (How it plugs into V2)

### 7.1 Strategy side

`strategies/ml_strategy_mtf_v2.py`:
- Loads a model from `model_path` (joblib)
- Computes a **fixed 10-feature vector** and calls:
  - `model.predict(...)`
  - `model.predict_proba(...)`

Because feature ordering matters, **training must match the strategy’s feature computation**.

### 7.2 Supported retraining script

Use:

```powershell
python research/train_model_mtf.py
```

It:
- Loads Parquet bars from `data/historical`
- Builds 15m + 30m features
- Trains a model and writes:
  - `models/ml_model_mtf.pkl`
  - `models/feature_names_mtf.txt`

### 7.3 Walk-forward / rolling training (optional, recommended)

```powershell
python research/train_model_mtf_rolling.py
```

Outputs multiple models under:
- `models/rolling/`

### 7.4 Recommended retrain workflow

1) Ingest newest data
2) Retrain model
3) Backtest using the new model
4) If performance is acceptable, deploy to live
5) Keep a backup of the previous model file

---

## 8) Parameter Optimization (Grid Runs)

This repo supports two optimization styles:

### 8.1 Simulation-based grid optimization (MTF V2 compatible)

`optimize_2pos_sim.py`:
- Loads Parquet 15m bars
- Computes the same MTF features
- Uses the trained ML model to generate predictions
- Simulates a 2-position bracket-style lifecycle
- Sweeps a parameter grid (splits / TP / SL / trailing distance)

Quick mode:

```powershell
python optimize_2pos_sim.py --quick --start 2024-01-01 --end 2024-10-31
```

Full mode:

```powershell
python optimize_2pos_sim.py --start 2024-01-01 --end 2024-10-31
```

Notes:
- This is a fast optimizer intended for **parameter exploration**.
- The final candidate settings should be validated via your full backtest script.

### 8.2 YAML-driven grid search framework (MTF V2)

There is an `optimization/grid_search.py` framework with YAML configs under `optimization/configs/`.

MTF V2 is supported via:
- `system: mtf_v2`
- runner: `backtest/run_backtest_mtf_v2_sweep.py`

This is the recommended approach when you want:
- A machine-readable results table (CSV) for ranking
- Automatic checkpoint/resume
- One output directory per run containing artifacts for audit/debug

#### 8.2.1 Minimal smoke test config

A ready-to-run 2-combo config is included:
- `optimization/configs/mtf_v2_smoke.yaml`

Run it from the repo root:

```powershell
python optimization\grid_search.py --config optimization\configs\mtf_v2_smoke.yaml --no-resume --verbose
```

#### 8.2.2 Configuration structure

The YAML grid search has three main sections:

```yaml
system:
  name: mtf_v2
  runner: backtest/run_backtest_mtf_v2_sweep.py

optimization:
  objective: sharpe_ratio
  workers: 1

parameters:
  prediction_threshold:
    values: [0.55, 0.70]

fixed:
  backtest_start: "2025-01-01"
  backtest_end: "2025-03-01"
  initial_balance: 50000
```

Notes:
- `parameters` defines the sweep grid.
- `fixed` defines constants applied to every run.
- Parameters are injected into the runner via environment variables (prefixed `MTF2_`).

#### 8.2.3 Required setup

- Parquet catalog exists at `data/historical` (or set `CATALOG_PATH`).
- Model file exists at `models/ml_model_mtf.pkl` (or set `MTF2_MODEL_PATH` in `.env.mtf_v2`).
- `.env.mtf_v2` should define the instrument and bar type (especially `MTF2_BAR_TYPE`).

#### 8.2.4 Outputs to inspect

Grid search summary outputs:
- `optimization/results/<name>_results.csv`
- `optimization/results/<name>_results_top_10.json`
- `optimization/results/<name>_results_summary.json`

Per-run artifacts (one directory per run under `backtest_results/`):
- `performance_stats.json`
- `positions.csv`
- `trades.csv`
- `strategy_decisions.log`

---

## 9) Troubleshooting

### 9.1 Ingestion: “connection refused”
- TWS/IBG not running
- Port mismatch
- API not enabled

### 9.2 Backtest: “no data found for bar_type”
- Parquet catalog missing that bar type
- Wrong `MTF2_BAR_TYPE` (must match catalog naming)

### 9.3 Live: strategy starts but no trades
- `MTF2_PREDICTION_THRESHOLD` too high
- Hour filters exclude everything
- ATR outside `MTF2_MIN_ATR` / `MTF2_MAX_ATR`

---

## 10) Safety / Operations Notes

- Prefer paper trading until stable.
- Keep model backups and keep a record of which model was deployed.
- Keep logs for each run (at least: `strategy.log`, `orders.log`, `trades.log`, `errors.log`).
