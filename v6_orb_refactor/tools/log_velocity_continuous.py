"""
Continuous velocity logger for IBKR tick data.
Logs to CSV for multi-day analysis. Includes reconnection logic.
"""
import logging
import time
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ib_insync import IB, Contract

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from v6_orb_refactor.live.live_context import LiveMarketContext


def create_contract(symbol: str, sec_type: str = 'CMDTY', exchange: str = 'SMART') -> Contract:
    """Create IBKR contract."""
    if symbol == 'EURUSD':
        contract = Contract(
            symbol='EUR',
            secType='CASH',
            exchange='IDEALPRO',
            currency='USD'
        )
    else:
        contract = Contract(
            symbol=symbol,
            secType=sec_type,
            exchange=exchange,
            currency='USD'
        )
    return contract


class VelocityLogger:
    """Logs IBKR tick velocity to CSV with reconnection logic."""
    
    def __init__(self, instrument: str, log_dir: str = 'v6_velocity_logs'):
        self.instrument = instrument
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create timestamped log file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = self.log_dir / f'velocity_{instrument}_{timestamp}.csv'
        
        # Setup logging
        log_file = self.log_dir / f'velocity_{instrument}_{timestamp}.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('velocity_logger')
        
        # IBKR connection
        self.ib = None
        self.context = None
        self.contract = create_contract(instrument)
        
        # Stats
        self.records_logged = 0
        self.reconnect_count = 0
        self.start_time = datetime.now()
        
    def connect(self):
        """Connect to IBKR with retry logic."""
        self.logger.info("Connecting to IBKR...")
        
        self.ib = IB()
        
        # Try TWS paper (7497), then live (7496), then Gateway paper (4002), then Gateway live (4001)
        ports = [7497, 7496, 4002, 4001]
        
        for port in ports:
            try:
                self.ib.connect('127.0.0.1', port, clientId=999)
                self.logger.info(f"Connected to IBKR on port {port}")
                return True
            except:
                continue
                
        self.logger.error("Could not connect to IBKR on any port")
        return False
        
    def reconnect(self):
        """Reconnect after disconnection."""
        self.logger.warning("Connection lost. Attempting reconnect...")
        self.reconnect_count += 1
        
        if self.context:
            try:
                self.context.disconnect()
            except:
                pass
                
        if self.ib:
            try:
                self.ib.disconnect()
            except:
                pass
                
        time.sleep(5)  # Wait before reconnect
        
        if self.connect():
            self.setup_context()
            self.logger.info(f"Reconnected successfully (reconnect #{self.reconnect_count})")
            return True
        else:
            self.logger.error("Reconnect failed")
            return False
            
    def setup_context(self):
        """Setup LiveMarketContext."""
        self.logger.info(f"Subscribing to {self.instrument} tick data...")
        
        self.context = LiveMarketContext(
            ib=self.ib,
            contract=self.contract,
            tick_buffer_minutes=10,
            on_tick_callback=None,
            logger=self.logger
        )
        
        # Give it time to accumulate initial ticks
        time.sleep(10)
        
    def init_csv(self):
        """Initialize CSV file with headers."""
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp',
                'timestamp_utc',
                'hour_utc',
                'weekday',
                'velocity_1m',
                'velocity_3m',
                'velocity_5m',
                'velocity_10m',
                'buffer_size',
                'buffer_duration_min'
            ])
        self.logger.info(f"CSV log created: {self.csv_path}")
        
    def log_velocity(self):
        """Log current velocity to CSV."""
        now_local = datetime.now()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        try:
            vel_1m = self.context.get_velocity(1, now_utc)
            vel_3m = self.context.get_velocity(3, now_utc)
            vel_5m = self.context.get_velocity(5, now_utc)
            vel_10m = self.context.get_velocity(10, now_utc)
            buffer_size = len(self.context.tick_buffer)
            
            # Calculate buffer duration
            if buffer_size > 0:
                oldest = min(t.timestamp for t in self.context.tick_buffer)
                newest = max(t.timestamp for t in self.context.tick_buffer)
                buffer_duration = (newest - oldest).total_seconds() / 60
            else:
                buffer_duration = 0
                
            # Write to CSV
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    now_local.strftime('%Y-%m-%d %H:%M:%S'),
                    now_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    now_utc.hour,
                    now_utc.weekday(),  # 0=Monday, 6=Sunday
                    f'{vel_1m:.1f}',
                    f'{vel_3m:.1f}',
                    f'{vel_5m:.1f}',
                    f'{vel_10m:.1f}',
                    buffer_size,
                    f'{buffer_duration:.1f}'
                ])
                
            self.records_logged += 1
            
            # Get current price from last tick
            current_price = "N/A"
            if len(self.context.tick_buffer) > 0:
                last_tick = list(self.context.tick_buffer)[-1]
                current_price = f"{last_tick.bid:.2f}/{last_tick.ask:.2f}"
            
            # Print to console every record (5 seconds)
            time_str = now_utc.strftime('%H:%M:%S')
            print(f"[{time_str}] Price: {current_price:>13s}  "
                  f"Velocity: 1m={vel_1m:>5.0f} 3m={vel_3m:>5.0f} 5m={vel_5m:>5.0f}  "
                  f"Buffer: {buffer_size:>6,} ticks")
            
            # Also log summary to file every minute
            if self.records_logged % 12 == 0:
                self.logger.info(
                    f"[{now_utc.strftime('%H:%M')}] "
                    f"Price={current_price} "
                    f"Vel: 1m={vel_1m:.0f} 3m={vel_3m:.0f} 5m={vel_5m:.0f} "
                    f"Buffer={buffer_size:,} Records={self.records_logged:,}"
                )
                
        except Exception as e:
            self.logger.error(f"Error logging velocity: {e}")
            
    def print_status(self):
        """Print status summary."""
        uptime = datetime.now() - self.start_time
        uptime_str = str(uptime).split('.')[0]  # Remove microseconds
        
        print("\n" + "="*70)
        print(f"VELOCITY LOGGER STATUS - {self.instrument}")
        print("="*70)
        print(f"Uptime:          {uptime_str}")
        print(f"Records logged:  {self.records_logged:,}")
        print(f"Reconnects:      {self.reconnect_count}")
        print(f"Log file:        {self.csv_path}")
        print(f"File size:       {self.csv_path.stat().st_size / 1024:.1f} KB")
        
        if self.context:
            print(f"Buffer size:     {len(self.context.tick_buffer):,} ticks")
        print("="*70 + "\n")
        
    def run(self, log_interval_seconds: int = 5):
        """Run continuous logging loop."""
        if not self.connect():
            return
            
        self.setup_context()
        self.init_csv()
        
        print("\n" + "="*70)
        print(f"VELOCITY LOGGER STARTED - {self.instrument}")
        print("="*70)
        print(f"Log file: {self.csv_path}")
        print(f"Logging every {log_interval_seconds} seconds")
        print("Press Ctrl+C to stop")
        print("="*70 + "\n")
        
        last_status_time = time.time()
        status_interval = 3600  # Print status every hour
        
        try:
            while True:
                # Check connection
                if not self.ib.isConnected():
                    if not self.reconnect():
                        self.logger.error("Failed to reconnect. Exiting.")
                        break
                        
                # Log velocity
                self.log_velocity()
                
                # Print status every hour
                if time.time() - last_status_time > status_interval:
                    self.print_status()
                    last_status_time = time.time()
                    
                time.sleep(log_interval_seconds)
                
        except KeyboardInterrupt:
            print("\n" + "="*70)
            print("STOPPING VELOCITY LOGGER")
            print("="*70)
            
        finally:
            self.print_status()
            
            if self.context:
                self.context.disconnect()
            if self.ib:
                self.ib.disconnect()
                
            self.logger.info("Disconnected from IBKR")
            self.logger.info(f"Final stats: {self.records_logged:,} records logged")


def main():
    print("="*70)
    print("CONTINUOUS IBKR VELOCITY LOGGER")
    print("="*70)
    
    instrument = input("Enter instrument (XAUUSD or EURUSD): ").strip().upper()
    
    if instrument not in ['XAUUSD', 'EURUSD']:
        print(f"Unknown instrument: {instrument}")
        return
        
    logger = VelocityLogger(instrument)
    logger.run(log_interval_seconds=5)


if __name__ == "__main__":
    main()
