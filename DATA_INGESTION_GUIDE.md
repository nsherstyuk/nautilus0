# Data Ingestion Guide

## Configuration Status ✅

Your `.env` file is now configured for data ingestion with the following settings:

### Interactive Brokers Connection
```env
IB_HOST=127.0.0.1
IB_PORT=4002                    # TWS paper trading port (use 7497 for live)
IB_CLIENT_ID=1
IB_ACCOUNT_ID=                  # Optional - leave empty for default
IB_MARKET_DATA_TYPE=DELAYED_FROZEN  # Use DELAYED or LIVE if you have market data subscription
```

### Data Download Settings
```env
DATA_SYMBOLS=EUR/USD,GBP/USD,USD/CHF
DATA_START_DATE=2024-01-01
DATA_END_DATE=2025-10-30
```

## Before Running Ingestion

1. **Start TWS or IB Gateway**
   - Open TWS or IB Gateway application
   - Log in with your credentials
   - Ensure API connections are enabled in settings
   - Default ports:
     - TWS Paper: 4002
     - TWS Live: 7497
     - IB Gateway Paper: 4002
     - IB Gateway Live: 4001

2. **Verify Port Number**
   - Check your TWS/Gateway settings match `IB_PORT` in `.env`
   - Common ports: 4002 (paper), 7497 (live TWS), 4001 (live Gateway)

## Running Data Ingestion

```powershell
# Navigate to project root
cd C:\nautilus0

# Run the ingestion script
python data/ingest_historical.py
```

## What Gets Downloaded

For each symbol in `DATA_SYMBOLS`, the script downloads multiple timeframes:
- **1-minute bars**: Primary data for backtesting
- **2-minute bars**: For DMI trend filter
- **3-minute bars**: Alternative timeframe
- **5-minute bars**: Alternative timeframe
- **15-minute bars**: For Stochastic filter
- **Daily bars**: For long-term context

## Expected Results

### Output Location
- Parquet files: `data/historical/data/bar/EURUSD.IDEALPRO-{TIMEFRAME}-MID-EXTERNAL/*.parquet`
- CSV files: `data/historical/EUR-USD_EUR_USD_IDEALPRO_{TIMEFRAME}_MID_EXTERNAL.csv`
- Metadata: `data/historical/data/currency_pair/EURUSD.IDEALPRO/*.parquet`

### File Sizes (approximate for ~22 months)
- 1-minute: ~40 MB
- 2-minute: ~20 MB
- 3-minute: ~13 MB
- 5-minute: ~8 MB
- 15-minute: ~2.7 MB
- Daily: ~34 KB

### Total Time
- Per symbol: ~3-5 minutes (with IBKR pacing delays)
- 3 symbols: ~10-15 minutes total

## Troubleshooting

### Error: "Connection refused"
- TWS/Gateway is not running
- Check port number matches `.env`
- Verify API connections enabled in TWS settings

### Error: "Market data not subscribed"
- You need market data subscription for real-time data
- Use `IB_MARKET_DATA_TYPE=DELAYED_FROZEN` for free delayed data
- Historical data downloads work without subscription

### Error: "No data returned"
- Symbol format incorrect (use EUR/USD not EURUSD)
- Date range too far back (IBKR has limits)
- Market was closed on those dates

### Error: "Pacing violation"
- Script automatically handles pacing with delays
- If issue persists, increase delays in script config

## Next Steps After Ingestion

1. **Verify data loaded correctly**:
   ```powershell
   python check_data.py
   ```

2. **Run backtest with fresh data**:
   ```powershell
   python backtest/run_backtest.py
   ```

3. **Compare results**:
   - Fresh data may produce different results than Nov 13
   - IBKR can revise historical data (corrections, splits, etc.)
   - This is normal and expected

## Configuration Tips

### To change symbols:
```env
DATA_SYMBOLS=EUR/USD,GBP/USD,USD/JPY,AUD/USD
```

### To change date range:
```env
DATA_START_DATE=2023-01-01
DATA_END_DATE=2025-11-14
```

### To use live market data (requires subscription):
```env
IB_MARKET_DATA_TYPE=LIVE
```

### To connect to live TWS instead of paper:
```env
IB_PORT=7497
```

## Important Notes

1. **Data is not stored in git** - it's gitignored for good reason (large files)
2. **Re-ingestion will overwrite existing data** - no automatic backups
3. **IBKR rate limits apply** - script handles this automatically with delays
4. **Market data subscriptions** - you need an active subscription for real-time data, but historical data works without it
5. **Data revisions** - IBKR may revise historical data, so re-ingesting may produce different results than original downloads
