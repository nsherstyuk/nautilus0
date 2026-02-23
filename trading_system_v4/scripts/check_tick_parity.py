"""
check_tick_parity.py — Broker Tick Parity Analysis

Compares the tick density of Dukascopy (our training data) vs IBKR (our live execution data).
Because IBKR conflates quotes (e.g., 250ms snapshots for standard feeds), 1,000 ticks on 
Dukascopy might equal 300 ticks on IBKR. 

If we train on 1,000-Tick Bars from Dukascopy, we must execute on N-Tick Bars on IBKR 
where N = 1000 * (IBKR_Ticks / Dukascopy_Ticks).

Usage:
  python -m trading_system_v4.scripts.check_tick_parity
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Forex, util
from tick_vault import download_range, read_tick_data

# ── Configuration ─────────────────────────────────────────────────────────────
SYMBOL = "EURUSD"
# Pick a recent, highly active day (e.g., a Tuesday or Wednesday)
# IBKR historical ticks are only available for the last 6 months.
TARGET_DATE = datetime(2026, 2, 18, tzinfo=timezone.utc) 

def get_ibkr_ticks(target_date: datetime) -> int:
    """
    Connects to IBKR and downloads exactly 1 hour of tick data during the 
    London/NY overlap (14:00 - 15:00 UTC) to measure peak tick density.
    """
    # Use util.startLoop() for ib_insync in an existing asyncio loop
    util.startLoop()
    ib = IB()
    try:
        # Connect to TWS/Gateway (adjust port if using Gateway: 4001/4002)
        ib.connect('127.0.0.1', 4002, clientId=99)
    except Exception as e:
        print(f"[ERROR] Could not connect to IBKR: {e}")
        print("Please ensure TWS or IB Gateway is running and API is enabled.")
        return -1

    contract = Forex(SYMBOL)
    ib.qualifyContracts(contract)

    # We sample 1 hour of the most active time of day (14:00 to 15:00 UTC)
    start_time = target_date.replace(hour=14, minute=0, second=0)
    end_time = target_date.replace(hour=15, minute=0, second=0)
    
    print(f"Fetching IBKR ticks for {SYMBOL} from {start_time} to {end_time}...")
    
    all_ticks = []
    current_end = end_time
    
    # IBKR limits historical ticks to 1000 per request. We must paginate backwards.
    while current_end > start_time:
        try:
            # Format datetime for IBKR (YYYYMMDD HH:MM:SS UTC)
            end_str = current_end.strftime('%Y%m%d %H:%M:%S UTC')
            
            ticks = ib.reqHistoricalTicks(
                contract,
                startDateTime='',
                endDateTime=end_str,
                numberOfTicks=1000,
                whatToShow='BID_ASK',
                useRth=False,
                ignoreSize=False
            )
            
            if not ticks:
                print(f"  [WARN] IBKR returned empty tick list for end_time: {end_str}")
                break
                
            all_ticks.extend(ticks)
            
            # The oldest tick in this batch becomes the end_time for the next request
            oldest_tick_time = ticks[0].time
            print(f"  Fetched {len(ticks)} ticks. Oldest tick: {oldest_tick_time}")
            
            # If we haven't moved backwards (e.g., exactly 1000 ticks in 1 millisecond), break to avoid infinite loop
            if oldest_tick_time >= current_end:
                break
                
            current_end = oldest_tick_time
            
            # Respect IBKR pacing (max 60 requests / 10 mins)
            ib.sleep(1) 
            
        except Exception as e:
            print(f"  [WARN] IBKR Pagination Error: {e}")
            break

    ib.disconnect()
    
    # Filter out ticks that fell before our exact start_time due to the 1000-tick chunking
    valid_ticks = [t for t in all_ticks if t.time >= start_time]
    
    print(f"  -> IBKR returned {len(valid_ticks):,} ticks for the 1-hour window.")
    return len(valid_ticks)


async def get_dukascopy_ticks(target_date: datetime) -> int:
    """
    Downloads the exact same 1-hour window from Dukascopy using tick-vault.
    """
    # tick-vault expects naive datetimes for its API, but they represent UTC
    start_time = target_date.replace(hour=14, minute=0, second=0, tzinfo=None)
    end_time = target_date.replace(hour=15, minute=0, second=0, tzinfo=None)
    
    print(f"Fetching Dukascopy ticks for {SYMBOL} from {start_time} to {end_time}...")
    
    await download_range(symbol=SYMBOL, start=start_time, end=end_time)
    df = read_tick_data(symbol=SYMBOL, start=start_time, end=end_time)
    
    if df is None or df.empty:
        print("  [ERROR] Dukascopy returned 0 ticks.")
        return -1
        
    print(f"  -> Dukascopy returned {len(df):,} ticks for the 1-hour window.")
    return len(df)


async def main():
    print("=" * 60)
    print("BROKER TICK PARITY ANALYSIS")
    print("=" * 60)
    
    # 1. Get Dukascopy Ticks
    duka_count = await get_dukascopy_ticks(TARGET_DATE)
    
    # 2. Get IBKR Ticks
    ibkr_count = get_ibkr_ticks(TARGET_DATE)
    
    if duka_count <= 0 or ibkr_count <= 0:
        print("\n[ABORT] Could not fetch data from both sources.")
        return
        
    # 3. Calculate Parity Ratio
    ratio = ibkr_count / duka_count
    
    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"  Dukascopy Ticks (1 Hour): {duka_count:,}")
    print(f"  IBKR Ticks (1 Hour):      {ibkr_count:,}")
    print(f"  Tick Compression Ratio:   {ratio:.4f} (IBKR has {ratio*100:.1f}% of Dukascopy's ticks)")
    
    # 4. Recommendation
    target_training_bar = 1000
    live_execution_bar = int(target_training_bar * ratio)
    
    print("\nRECOMMENDATION:")
    print(f"  If you train your ML model on {target_training_bar}-Tick Bars from Dukascopy,")
    print(f"  you MUST execute live using {live_execution_bar}-Tick Bars on IBKR.")
    print("  Otherwise, the volatility and momentum features will be severely distorted.")
    print("=" * 60)

if __name__ == "__main__":
    import os
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
