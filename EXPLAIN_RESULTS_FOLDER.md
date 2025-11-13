# How Results Folder is Determined

## Two Types of Results Folders

### 1. Backtest Results Folder (Created by `run_backtest.py`)

**Location:** `backtest/run_backtest.py` lines 1187-1189

```python
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
safe_symbol = cfg.symbol.replace('/', '-')
output_dir = Path(cfg.output_dir) / f"{safe_symbol}_{timestamp}"
```

**Components:**
- **Base directory**: `cfg.output_dir` (default: `"logs/backtest_results"` from `BacktestConfig`)
- **Symbol**: From `BACKTEST_SYMBOL` env var (e.g., `"EUR/USD"` → `"EUR-USD"`)
- **Timestamp**: Current time when backtest runs (`YYYYMMDD_HHMMSS` format)

**Example:** `logs/backtest_results/EUR-USD_20251112_175738`

**Configuration:**
- Can be changed via `BACKTEST_OUTPUT_DIR` env var
- Default: `"logs/backtest_results"` (from `config/backtest_config.py` line 31)

### 2. Optimization Script Summary (Created by `quick_trailing_optimization.py`)

**Location:** `quick_trailing_optimization.py` line 173

```python
output_file = Path("logs") / f"trailing_stop_quick_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
```

**Components:**
- **Base directory**: `"logs"` (hardcoded)
- **Filename**: `trailing_stop_quick_results_{timestamp}.json`
- **Timestamp**: Current time when script runs

**Example:** `logs/trailing_stop_quick_results_20251112_175914.json`

### How Optimization Script Finds Backtest Results

**Location:** `quick_trailing_optimization.py` lines 67-73

```python
results_dir = Path("logs/backtest_results")
folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime, reverse=True)
latest_folder = folders[0]
```

**Logic:**
1. Looks in `logs/backtest_results` directory
2. Finds all folders matching pattern `EUR-USD_*`
3. Sorts by modification time (newest first)
4. Picks the first (latest) folder

**Note:** This assumes symbol is `EUR/USD`. For other symbols, the pattern would be different.

## Summary

| Item | Location | Determined By |
|------|----------|---------------|
| **Backtest results folder** | `logs/backtest_results/{SYMBOL}_{TIMESTAMP}` | Symbol from env + timestamp when backtest runs |
| **Base directory** | `logs/backtest_results` | `BACKTEST_OUTPUT_DIR` env var (default: `"logs/backtest_results"`) |
| **Optimization summary** | `logs/trailing_stop_quick_results_{TIMESTAMP}.json` | Hardcoded `"logs"` directory + timestamp |

## To Change Results Folder Location

1. **Change base directory for backtests:**
   ```bash
   BACKTEST_OUTPUT_DIR=my_custom_path/logs/backtest_results
   ```

2. **Change optimization summary location:**
   Edit `quick_trailing_optimization.py` line 173:
   ```python
   output_file = Path("my_custom_path") / f"trailing_stop_quick_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
   ```

