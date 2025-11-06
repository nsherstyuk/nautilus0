"""
Quick guide for running data ingestion.
"""
from dotenv import load_dotenv
import os

load_dotenv()

print("=" * 70)
print("DATA INGESTION GUIDE")
print("=" * 70)
print()

print("Required Environment Variables:")
print("  - IB_HOST: IBKR host address (default: 127.0.0.1)")
print("  - IB_PORT: IBKR port (default: 7497 for TWS, 4001 for Gateway)")
print("  - IB_CLIENT_ID: Client identifier")
print("  - DATA_SYMBOLS: Comma-separated symbols (e.g., 'EUR/USD' or 'SPY')")
print("  - DATA_START_DATE: Start date in YYYY-MM-DD format")
print("  - DATA_END_DATE: End date in YYYY-MM-DD format")
print("  - CATALOG_PATH: Output directory (default: data/historical)")
print()

print("Current Configuration:")
print(f"  DATA_SYMBOLS: {os.getenv('DATA_SYMBOLS', 'NOT SET (default: SPY)')}")
print(f"  DATA_START_DATE: {os.getenv('DATA_START_DATE', 'NOT SET (default: 30 days ago)')}")
print(f"  DATA_END_DATE: {os.getenv('DATA_END_DATE', 'NOT SET (default: today)')}")
print(f"  CATALOG_PATH: {os.getenv('CATALOG_PATH', 'data/historical')}")
print()

print("Example Usage:")
print("  1. Set environment variables in .env file:")
print("     DATA_SYMBOLS=EUR/USD")
print("     DATA_START_DATE=2025-01-01")
print("     DATA_END_DATE=2025-07-31")
print()
print("  2. Ensure TWS or IB Gateway is running")
print()
print("  3. Run the ingestion script:")
print("     python data/ingest_historical.py")
print()
print("  4. Verify ingested data:")
print("     python data/verify_catalog.py")
print()

print("Note: For forex pairs, the script downloads:")
print("  - 1-minute bars (default)")
print("  - 2-minute bars (for DMI filter)")
print("  - 15-minute bars (for Stochastic filter)")
print("  - 1-day bars (for longer-term analysis)")
print()

