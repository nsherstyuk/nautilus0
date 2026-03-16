"""
Standalone velocity monitor for IBKR tick data.
No trading - just connects and displays real-time tick velocity.
"""
import logging
import time
from datetime import datetime, timedelta

from ib_insync import IB, Contract

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from v6_orb_refactor.live.live_context import LiveMarketContext


def create_contract(symbol: str, sec_type: str = 'CMDTY', exchange: str = 'SMART') -> Contract:
    """Create IBKR contract."""
    return Contract(
        symbol=symbol,
        secType=sec_type,
        exchange=exchange,
        currency='USD'
    )


def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger('velocity_monitor')
    
    print("="*70)
    print("IBKR VELOCITY MONITOR")
    print("="*70)
    
    # Get instrument from user
    instrument = input("Enter instrument (XAUUSD or EURUSD): ").strip().upper()
    
    if instrument == 'XAUUSD':
        contract = create_contract('XAUUSD', 'CMDTY', 'SMART')
    elif instrument == 'EURUSD':
        contract = create_contract('EUR', 'CASH', 'IDEALPRO')
        contract.currency = 'USD'
    else:
        print(f"Unknown instrument: {instrument}")
        return
    
    # Connect to IBKR
    logger.info("Connecting to IBKR...")
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=999)  # TWS paper/live
    except:
        try:
            ib.connect('127.0.0.1', 4002, clientId=999)  # IB Gateway paper
        except:
            logger.error("Could not connect to IBKR. Make sure TWS/Gateway is running.")
            return
    
    logger.info(f"Connected. Subscribing to {instrument} tick data...")
    
    # Create LiveMarketContext (no callbacks needed for monitoring)
    context = LiveMarketContext(
        ib=ib,
        contract=contract,
        tick_buffer_minutes=10,
        on_tick_callback=None,  # No callback needed
        logger=logger
    )
    
    # Give it time to accumulate ticks
    logger.info("Accumulating tick data for 10 seconds...")
    time.sleep(10)
    
    print("\n" + "="*70)
    print(f"MONITORING {instrument} VELOCITY (Ctrl+C to stop)")
    print("="*70)
    print(f"{'Time':<10} {'1-min':>8} {'3-min':>8} {'5-min':>8} {'Buffer Size':>12}")
    print("-"*70)
    
    try:
        while True:
            now = datetime.utcnow()
            
            # Calculate velocity for different lookbacks
            vel_1m = context.get_velocity(1, now)
            vel_3m = context.get_velocity(3, now)
            vel_5m = context.get_velocity(5, now)
            buffer_size = len(context.tick_buffer)
            
            time_str = now.strftime('%H:%M:%S')
            print(f"{time_str:<10} {vel_1m:>8.1f} {vel_3m:>8.1f} {vel_5m:>8.1f} {buffer_size:>12,} ticks")
            
            time.sleep(5)  # Update every 5 seconds
            
    except KeyboardInterrupt:
        print("\n" + "="*70)
        print("Monitoring stopped")
        print("="*70)
        
        # Show final stats
        now = datetime.utcnow()
        print(f"\nFinal Stats:")
        print(f"  Buffer size: {len(context.tick_buffer):,} ticks")
        print(f"  3-min velocity: {context.get_velocity(3, now):.1f} ticks/min")
        
        if len(context.tick_buffer) > 0:
            oldest = min(t.timestamp for t in context.tick_buffer)
            newest = max(t.timestamp for t in context.tick_buffer)
            duration = (newest - oldest).total_seconds() / 60
            print(f"  Data coverage: {duration:.1f} minutes")
        
        context.disconnect()
        ib.disconnect()
        print("\nDisconnected from IBKR")


if __name__ == "__main__":
    main()
