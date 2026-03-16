"""
Simplified velocity logger using regular market data (not tick-by-tick).
Works better with IBKR paper accounts.
"""
import logging
import time
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import deque

from ib_insync import IB, Contract

def create_contract(symbol: str) -> Contract:
    """Create IBKR contract."""
    if symbol == 'EURUSD':
        return Contract(symbol='EUR', secType='CASH', exchange='IDEALPRO', currency='USD')
    else:
        return Contract(symbol=symbol, secType='CMDTY', exchange='SMART', currency='USD')


class SimpleVelocityLogger:
    """Logs velocity using regular market data updates."""
    
    def __init__(self, instrument: str):
        self.instrument = instrument
        self.log_dir = Path('v6_velocity_logs')
        self.log_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = self.log_dir / f'velocity_{instrument}_{timestamp}.csv'
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        )
        self.logger = logging.getLogger('velocity_logger')
        
        # Tick buffer (we'll treat each market data update as a "tick")
        self.tick_buffer = deque(maxlen=100000)
        
        # IBKR
        self.ib = IB()
        self.contract = create_contract(instrument)
        self.ticker = None
        
        self.records_logged = 0
        self.start_time = datetime.now()
        
    def connect(self):
        """Connect to IBKR."""
        self.logger.info("Connecting to IBKR...")
        
        ports = [4002, 7497, 4001, 7496]
        for port in ports:
            try:
                self.ib.connect('127.0.0.1', port, clientId=999)
                self.logger.info(f"Connected on port {port}")
                return True
            except:
                continue
        
        self.logger.error("Could not connect to IBKR")
        return False
        
    def subscribe(self):
        """Subscribe to market data."""
        self.logger.info(f"Subscribing to {self.instrument} market data...")
        
        # Use regular market data (updates every ~250ms when active)
        self.ticker = self.ib.reqMktData(self.contract, '', False, False)
        
        # Give it time to get initial data
        time.sleep(3)
        
        if self.ticker.bid and self.ticker.ask:
            self.logger.info(f"Market data received: Bid={self.ticker.bid:.2f} Ask={self.ticker.ask:.2f}")
        else:
            self.logger.warning("No market data yet (may be delayed or market closed)")
            
    def init_csv(self):
        """Initialize CSV."""
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'timestamp_utc', 'hour_utc', 'weekday',
                'bid', 'ask', 'last',
                'velocity_1m', 'velocity_3m', 'velocity_5m',
                'buffer_size'
            ])
        self.logger.info(f"CSV log: {self.csv_path}")
        
    def get_velocity(self, lookback_minutes: int) -> float:
        """Calculate velocity from buffer."""
        if not self.tick_buffer:
            return 0.0
            
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=lookback_minutes)
        count = sum(1 for t in self.tick_buffer if t['time'] >= cutoff)
        return count / lookback_minutes if lookback_minutes > 0 else 0.0
        
    def run(self):
        """Main loop."""
        if not self.connect():
            return
            
        self.subscribe()
        self.init_csv()
        
        print("\n" + "="*70)
        print(f"VELOCITY LOGGER - {self.instrument}")
        print("="*70)
        print("Logging every 5 seconds. Press Ctrl+C to stop")
        print("="*70 + "\n")
        
        last_bid = None
        last_ask = None
        
        try:
            while True:
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                
                # Update ticker to get latest data
                self.ib.sleep(0.1)
                
                # If bid/ask changed, treat as a "tick"
                if self.ticker.bid and self.ticker.ask:
                    if self.ticker.bid != last_bid or self.ticker.ask != last_ask:
                        self.tick_buffer.append({
                            'time': now_utc,
                            'bid': self.ticker.bid,
                            'ask': self.ticker.ask
                        })
                        last_bid = self.ticker.bid
                        last_ask = self.ticker.ask
                
                # Calculate velocity
                vel_1m = self.get_velocity(1)
                vel_3m = self.get_velocity(3)
                vel_5m = self.get_velocity(5)
                buffer_size = len(self.tick_buffer)
                
                # Log to CSV
                with open(self.csv_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        now_utc.strftime('%Y-%m-%d %H:%M:%S'),
                        now_utc.hour,
                        now_utc.weekday(),
                        f'{self.ticker.bid:.2f}' if self.ticker.bid else '',
                        f'{self.ticker.ask:.2f}' if self.ticker.ask else '',
                        f'{self.ticker.last:.2f}' if self.ticker.last else '',
                        f'{vel_1m:.1f}',
                        f'{vel_3m:.1f}',
                        f'{vel_5m:.1f}',
                        buffer_size
                    ])
                
                self.records_logged += 1
                
                # Print to console
                price_str = f"{self.ticker.bid:.2f}/{self.ticker.ask:.2f}" if self.ticker.bid else "N/A"
                print(f"[{now_utc.strftime('%H:%M:%S')}] Price: {price_str:>13s}  "
                      f"Vel: 1m={vel_1m:>5.0f} 3m={vel_3m:>5.0f} 5m={vel_5m:>5.0f}  "
                      f"Buffer: {buffer_size:>6,} updates")
                
                time.sleep(5)
                
        except KeyboardInterrupt:
            print("\n" + "="*70)
            print("STOPPED")
            print(f"Records logged: {self.records_logged:,}")
            print(f"Log file: {self.csv_path}")
            print("="*70)
            
        finally:
            self.ib.disconnect()


def main():
    print("="*70)
    print("SIMPLE VELOCITY LOGGER (Market Data Mode)")
    print("="*70)
    
    instrument = input("Enter instrument (XAUUSD or EURUSD): ").strip().upper()
    
    if instrument not in ['XAUUSD', 'EURUSD']:
        print(f"Unknown instrument: {instrument}")
        return
        
    logger = SimpleVelocityLogger(instrument)
    logger.run()


if __name__ == "__main__":
    main()
