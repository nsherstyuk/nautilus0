# Data Ingestion Runbook

## Overview

This runbook provides comprehensive guidance for data ingestion operations in the trading system. The system downloads historical market data from Interactive Brokers and stores it in Parquet format for use in backtesting and live trading.

### Key Components

- **`data/ingest_historical.py`** - Main ingestion script with CLI support
- **`data/verify_catalog.py`** - Catalog verification and overlap detection
- **`data/fix_parquet_intervals.py`** - Automated cleanup and re-ingestion
- **`data/cleanup_catalog.py`** - Manual catalog cleanup utilities

### Data Flow

```
IBKR API → ingest_historical.py → ParquetDataCatalog → Parquet Files
                ↓
         CSV Files (backup)
                ↓
         verify_catalog.py (validation)
```

## Quick Start

### Basic Ingestion

```bash
# Set environment variables
export DATA_SYMBOLS="EUR/USD"
export DATA_START_DATE="2024-01-01"
export DATA_END_DATE="2024-01-31"
export CATALOG_PATH="data/historical"

# Run ingestion
python data/ingest_historical.py
```

### With Force Clean

```bash
# Clean existing data and ingest fresh
python data/ingest_historical.py --force-clean
```

### Override Catalog Path

```bash
# Use custom output directory
python data/ingest_historical.py --catalog-path /custom/path
```

## Verification

### Check Catalog Contents

```bash
# Basic verification
python data/verify_catalog.py

# Check for interval overlaps
python data/verify_catalog.py --check-overlaps

# Get JSON output for programmatic use
python data/verify_catalog.py --json
```

### Interpreting Output

- **Bar counts**: Number of bars per instrument and timeframe
- **Date ranges**: Start and end timestamps for each dataset
- **Overlap warnings**: Indicates "Intervals are not disjoint" errors
- **Exit codes**: 0 = success, 3 = overlaps detected

## Troubleshooting

### Problem: "Intervals are not disjoint" Error

**Cause:** Overlapping time intervals in Parquet files from chunked downloads or multiple ingestion runs.

**Solutions:**

1. **Automated Fix (Recommended):**
   ```bash
   python data/fix_parquet_intervals.py --symbol EUR/USD
   ```
   - Validates → Cleans → Re-ingests → Validates
   - Complete fix with one command

2. **Force Clean on Ingestion:**
   ```bash
   python data/ingest_historical.py --force-clean
   ```
   - Cleans all data before fresh ingestion
   - Use when you want a clean slate

3. **Manual Cleanup:**
   ```bash
   # List all datasets
   python data/cleanup_catalog.py --list
   
   # Delete specific dataset
   python data/cleanup_catalog.py --delete --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL --execute
   
   # Delete all data
   python data/cleanup_catalog.py --delete-all --confirm --execute
   ```

### Problem: "Catalog dataset missing" Warning

**Cause:** Parquet write failed but CSV files were created.

**Solution:** Run cleanup and re-ingest:
```bash
python data/ingest_historical.py --force-clean
```

### Problem: No bars returned from catalog query

**Cause:** Bar type mismatch or missing -EXTERNAL suffix.

**Solution:** Check bar type naming conventions:
- Forex: `EUR/USD.IDEALPRO-1-MINUTE-MID-EXTERNAL`
- Stocks: `SPY.SMART-1-MINUTE-MID-EXTERNAL`

## Cleanup Workflows

### Approach 1: Automated Cleanup and Re-ingestion

**Command:** `python data/fix_parquet_intervals.py --symbol EUR/USD`

**Steps:**
1. Validates existing data for overlaps
2. Cleans problematic datasets
3. Re-ingests data for the symbol
4. Validates the result

**Use when:** You want a complete fix with one command.

### Approach 2: Force Clean During Ingestion

**Command:** `python data/ingest_historical.py --force-clean`

**Steps:**
1. Cleans all existing catalog data
2. Ingests fresh data

**Use when:** You want to ensure a fresh start every time.

### Approach 3: Manual Cleanup

**List datasets:**
```bash
python data/cleanup_catalog.py --list
```

**Delete specific dataset:**
```bash
python data/cleanup_catalog.py --delete --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL --execute
```

**Delete all data:**
```bash
python data/cleanup_catalog.py --delete-all --confirm --execute
```

**Use when:** You need fine-grained control over what gets deleted.

## Best Practices

1. **Always verify after ingestion:**
   ```bash
   python data/verify_catalog.py --check-overlaps
   ```

2. **Use `--force-clean` when re-ingesting the same date range:**
   ```bash
   python data/ingest_historical.py --force-clean
   ```

3. **Monitor disk space:** Cleanup frees significant space.

4. **Check logs for diagnostics:**
   ```bash
   tail -f logs/application.log
   ```

5. **Use debug logging for troubleshooting:**
   ```bash
   LOG_LEVEL=DEBUG python data/ingest_historical.py
   ```

## Command Reference

| Command | Description | Required Args | Example |
|---------|-------------|----------------|---------|
| `python data/ingest_historical.py` | Basic ingestion | Environment variables | `DATA_SYMBOLS="EUR/USD" python data/ingest_historical.py` |
| `python data/ingest_historical.py --force-clean` | Clean and ingest | Environment variables | `python data/ingest_historical.py --force-clean` |
| `python data/verify_catalog.py` | Verify catalog | None | `python data/verify_catalog.py` |
| `python data/verify_catalog.py --check-overlaps` | Check for overlaps | None | `python data/verify_catalog.py --check-overlaps` |
| `python data/fix_parquet_intervals.py --symbol EUR/USD` | Fix intervals | `--symbol` | `python data/fix_parquet_intervals.py --symbol EUR/USD` |
| `python data/cleanup_catalog.py --list` | List datasets | None | `python data/cleanup_catalog.py --list` |
| `python data/cleanup_catalog.py --delete-all --confirm --execute` | Delete all | `--confirm --execute` | `python data/cleanup_catalog.py --delete-all --confirm --execute` |

### Exit Codes

- **0**: Success
- **1**: General error
- **3**: Overlaps detected (verify_catalog.py)

## Advanced Topics

### Bar Deduplication

The system uses timestamp-based deduplication:
- Bars with identical timestamps are deduplicated
- Latest bar for each timestamp is kept
- Consolidation happens during Parquet write

### Parquet Consolidation

- Multiple CSV files are consolidated into single Parquet files
- Consolidation happens automatically during ingestion
- Failed consolidation results in CSV-only output

### Interval Overlap Detection

The system detects overlaps by:
1. Loading all Parquet files for an instrument/timeframe
2. Checking for overlapping time intervals
3. Reporting conflicts with specific file paths and timestamps

### Debug Logging

Enable detailed logging for troubleshooting:
```bash
LOG_LEVEL=DEBUG python data/ingest_historical.py
```

This shows:
- Bar deduplication details
- Consolidation progress
- Parquet write operations
- Error diagnostics

## Appendix

### File Locations

- **Data files:** `data/historical/` (or `CATALOG_PATH`)
- **Logs:** `logs/application.log`
- **CSV backups:** `data/historical/` (alongside Parquet files)

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATA_SYMBOLS` | Comma-separated symbols | "SPY" | Yes |
| `DATA_START_DATE` | Start date (YYYY-MM-DD) | 30 days ago | No |
| `DATA_END_DATE` | End date (YYYY-MM-DD) | Today | No |
| `CATALOG_PATH` | Output directory | "data/historical" | No |
| `IB_HOST` | IBKR host | - | Yes |
| `IB_PORT` | IBKR port | - | Yes |
| `IB_CLIENT_ID` | Client ID | - | Yes |

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "Intervals are not disjoint" | Overlapping time intervals | Use `--force-clean` or `fix_parquet_intervals.py` |
| "Catalog dataset missing" | Parquet write failed | Re-run ingestion with cleanup |
| "Cannot create catalog directory" | Permission issue | Check directory permissions |
| "No bars returned" | Bar type mismatch | Check instrument naming |

### Links

- [NautilusTrader Documentation](https://docs.nautilustrader.io/)
- [Interactive Brokers API](https://interactivebrokers.github.io/tws-api/)
- [Configuration Guide](config/env_variables.md)
- [Optimization Guide](optimization/README.md)
