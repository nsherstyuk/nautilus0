# MTF V2 Trading System

## Active Code (December 2025)

This is the **MTF V2 Two-Position Bracket Strategy** for EUR/USD trading.

---

## Directory Structure

```
nautilus0/
├── .env.mtf_v2              # ⭐ ACTIVE CONFIG - V2 strategy settings
├── .env.mtf                 # V1 config (reference only)
├── .env                     # Base environment
│
├── config/                  # Configuration loaders
│   ├── mtf_v2_config.py     # ⭐ V2 config loader
│   ├── mtf_config.py        # V1 config loader
│   └── ibkr_config.py       # IBKR connection settings
│
├── strategies/              # Trading strategies
│   ├── ml_strategy_mtf_v2.py    # ⭐ ACTIVE V2 strategy
│   └── ml_strategy_mtf.py       # V1 strategy (reference)
│
├── live/                    # Live trading
│   ├── run_live_mtf_v2.py   # ⭐ Run V2 live trading
│   └── ib_bar_streamer.py   # Bar data via ib_insync
│
├── run_backtest_mtf_v2_full.py  # ⭐ V2 backtest with full reports
├── optimize_2pos_sim.py         # Grid optimization for 2-position strategy
├── phase0_download_data.py      # Historical data download
├── retrain_model.py             # ML model retraining
│
├── models/                  # ML models
│   └── ml_model_mtf.pkl     # ⭐ Active model
│
├── data/                    # Data storage
│   └── historical/          # Parquet data catalog
│
├── logs/                    # Log files
│   ├── live_mtf/            # Live trading logs
│   └── trader_logs/         # NautilusTrader logs
│
├── backtest_results/        # Backtest output directories
│
├── archive/                 # OLD FILES (not deleted, just organized)
│   ├── env_backups/         # Old .env files
│   ├── documentation/       # Old .md files
│   ├── scripts_old/         # Old Python scripts
│   ├── logs_old/            # Old log files
│   └── optimization_old/    # Old optimization scripts
│
└── patches/                 # IBKR adapter patches
```

---

## Data Ingestion from IBKR

### Configuration Variables (in `.env`)

| Variable | Purpose | Default | Example |
|----------|---------|---------|---------|
| `DATA_SYMBOLS` | Symbols to download | `SPY` | `EUR/USD` or `EUR/USD,GBP/USD` |
| `DATA_START_DATE` | Start of date range | Last 7 days | `2024-01-01` |
| `DATA_END_DATE` | End of date range | Today | `2025-12-04` |
| `CATALOG_PATH` | Output directory | `data/historical` | `data/historical` |
| `BACKTEST_VENUE` | Exchange for forex | `IDEALPRO` | `IDEALPRO` |
| `IB_HOST` | TWS/Gateway host | `127.0.0.1` | `127.0.0.1` |
| `IB_PORT` | TWS=7497, Gateway=4001 | `7497` | `7497` |
| `IB_CLIENT_ID` | Client identifier | `17` | `17` |

### Current `.env` Settings
```ini
# DATA INGESTION
DATA_SYMBOLS=EUR/USD
DATA_START_DATE=2024-01-01
DATA_END_DATE=2025-11-28

# IBKR CONNECTION
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=17

# OUTPUT
CATALOG_PATH=data/historical
BACKTEST_VENUE=IDEALPRO
```

### Important Notes
- **Client ID**: Ingestion script uses **client ID 99** internally to avoid conflicts with live trading
- **Chunking**: Large date ranges are automatically split into chunks (IBKR limit)
- **Timeframes**: Downloads 1m, 2m, 3m, 5m, 15m, and 1D bars

### Download Commands
```powershell
# Interactive download with status checks
python phase0_download_data.py

# Direct ingestion (requires TWS/Gateway running)
python data/ingest_historical.py
```

### Data Storage
| Type | Location | Purpose |
|------|----------|---------|
| Parquet | `data/historical/data/` | NautilusTrader catalog (fast) |
| CSV | `data/historical/*.csv` | Human-readable backup |

### Current Data Available
| Symbol | Timeframes | Date Range |
|--------|------------|------------|
| EUR/USD | 1m, 2m, 3m, 5m, 15m, 1D | 2021-12-29 to 2025-11-28 |
| GBP/USD | 1m, 2m, 3m, 5m, 15m, 1D | 2021-12-29 to 2025-11-28 |
| USD/CHF | 1m, 2m, 3m, 5m, 15m, 1D | 2021-12-29 to 2025-11-28 |

### Verify Data Coverage
```powershell
python data/verify_catalog.py
```

### Data Scripts Reference
| Script | Purpose |
|--------|---------|
| `data/ingest_historical.py` | Main ingestion from IBKR |
| `data/verify_catalog.py` | Check data coverage |
| `data/cleanup_catalog.py` | Remove/fix catalog data |
| `phase0_download_data.py` | Interactive download wizard |

---

## Quick Start

### 1. Historical Data Download
```powershell
python phase0_download_data.py
```

### 2. Run Backtest
```powershell
python run_backtest_mtf_v2_full.py
```
Output: `backtest_results/MTF_V2_YYYYMMDD_HHMMSS/`

### 3. Run Live Trading
```powershell
# Ensure IBKR TWS/Gateway is running on port 7497
python live/run_live_mtf_v2.py
```
Logs: `logs/live_mtf/`

---

## Configuration

### Active Config: `.env.mtf_v2`

| Setting | Value | Description |
|---------|-------|-------------|
| `MTF2_POS1_FRACTION` | 0.85 | Position 1 size (85%) |
| `MTF2_POS2_FRACTION` | 0.15 | Position 2 size (15%) |
| `MTF2_POS1_TP_ATR_MULT` | 0.6 | POS1 take profit |
| `MTF2_POS2_TP_ATR_MULT` | 1.5 | POS2 take profit |
| `MTF2_SL_ATR_MULT` | 1.4 | Stop loss (all) |
| `MTF2_TRAILING_DISTANCE_ATR_MULT` | 0.4 | Trailing stop |
| `MTF2_EXCLUDED_HOURS_MODE` | weekday | Per-weekday hour filtering |
| `MTF2_PREDICTION_THRESHOLD` | 0.55 | ML confidence threshold |

### Excluded Hours (Based on PnL Analysis)
```
Monday:    4,6,14,15,17,22
Tuesday:   3,5,11,16,17,18,19,20,21
Wednesday: 5
Thursday:  0,1,4,6,11,21,22
Friday:    1,5,6,8,11,14,18,22
Saturday:  ALL (market closed)
Sunday:    0-20 (no activity)
```

---

## Strategy Logic

### Two-Position Bracket (V2)

1. **Entry**: ML model predicts LONG/SHORT with confidence > 0.55
2. **Position 1 (85%)**: Quick win at 0.6x ATR, then closes
3. **Position 2 (15%)**: Extended target at 1.5x ATR
4. **After POS1 TP**: Move POS2 SL to breakeven, enable trailing
5. **Trailing Stop**: 0.4x ATR distance from current price

### Performance (Jan-Nov 2025 Backtest)
- **Total PnL**: $63,223 (with weekday exclusions)
- **Win Rate**: 67.8%
- **Trades**: 3,284

---

## Log Files

### Live Trading Logs (`logs/live_mtf/`)
| File | Description |
|------|-------------|
| `console_YYYYMMDD_HHMMSS.log` | Full console output (per run) |
| `strategy.log` | Strategy decisions |
| `orders.log` | Order events |
| `trades.log` | Trade executions |
| `errors.log` | Error logs |

### Backtest Output (`backtest_results/MTF_V2_*/`)
| File | Description |
|------|-------------|
| `summary.txt` | Performance summary |
| `trades.csv` | All trade details |
| `performance_by_hour.csv` | PnL by hour |
| `performance_by_weekday.csv` | PnL by weekday |
| `hour_weekday_pnl_matrix.csv` | Hour×Weekday PnL |
| `strategy_decisions.log` | Entry/exit decisions |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `.env.mtf_v2` | Active configuration |
| `config/mtf_v2_config.py` | Config loader with helpers |
| `strategies/ml_strategy_mtf_v2.py` | Trading strategy |
| `live/run_live_mtf_v2.py` | Live trading runner |
| `run_backtest_mtf_v2_full.py` | Backtest with reports |
| `models/ml_model_mtf.pkl` | ML prediction model |
| `optimize_2pos_sim.py` | Parameter optimization |

---

## Archive

All previous versions, old documentation, and unused scripts are in `archive/`.
Nothing was deleted - just organized.

### Archive Contents:
- `archive/env_backups/` - 30+ old .env files
- `archive/documentation/` - 100+ old .md files
- `archive/scripts_old/` - 150+ old Python scripts
- `archive/logs_old/` - Old log files
- `archive/optimization_old/` - Old optimization scripts

---

## Verification Commands

```powershell
# Verify config loads correctly
python -c "from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config; config = load_mtf_v2_config(); print_mtf_v2_config(config)"

# Quick backtest test
python run_backtest_mtf_v2_full.py

# Check IBKR connection
python -c "from ib_insync import IB; ib = IB(); ib.connect('127.0.0.1', 7497, clientId=99); print('Connected:', ib.isConnected()); ib.disconnect()"
```

---

*Last updated: December 4, 2025*
