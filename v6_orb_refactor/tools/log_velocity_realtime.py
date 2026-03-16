"""
Real-time velocity logger using IBKR market data events.
Captures every bid/ask update via pendingTickersEvent callback.
Works for all instruments including XAUUSD (no tick-by-tick API needed).
"""
import asyncio
import logging
import time
import csv
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ib_insync import IB, Contract


def create_contract(symbol: str) -> Contract:
    """Create IBKR contract."""
    if symbol == 'EURUSD':
        return Contract(symbol='EUR', secType='CASH', exchange='IDEALPRO', currency='USD')
    else:
        return Contract(symbol=symbol, secType='CMDTY', exchange='SMART', currency='USD')


class RealtimeVelocityLogger:
    """Captures every market data update via event callback for true velocity."""
    
    def __init__(self, instrument: str):
        self.instrument = instrument
        self.log_dir = Path('v6_velocity_logs')
        self.log_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = self.log_dir / f'velocity_realtime_{instrument}_{timestamp}.csv'
        log_file = self.log_dir / f'velocity_realtime_{instrument}_{timestamp}.log'
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('velocity_logger')
        
        # IBKR
        self.ib = IB()
        self.contract = create_contract(instrument)
        self.ticker = None
        
        # Tick buffer - stores timestamp of every bid/ask change
        self.tick_buffer = deque(maxlen=100000)
        self.total_ticks = 0
        self.last_bid = None
        self.last_ask = None
        
        # Current price
        self.current_bid = 0.0
        self.current_ask = 0.0
        
        # CSV and stats
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
        """Subscribe to market data with event callback."""
        self.logger.info(f"Subscribing to {self.instrument} market data...")
        
        # Request streaming market data
        self.ticker = self.ib.reqMktData(self.contract, '', False, False)
        
        # Register event callback - fires on EVERY market data update
        self.ib.pendingTickersEvent += self._on_ticker_update
        
        # Wait for initial data
        self.ib.sleep(3)
        
        if self.ticker.bid and self.ticker.bid > 0:
            self.logger.info(f"Market data active: Bid={self.ticker.bid:.2f} Ask={self.ticker.ask:.2f}")
        else:
            self.logger.warning("Waiting for market data...")
            
    def _on_ticker_update(self, tickers):
        """Called by ib_insync on EVERY market data update."""
        for ticker in tickers:
            # Only process our contract
            if ticker.contract and ticker.contract.symbol in (self.contract.symbol, 'XAUUSD'):
                bid = ticker.bid
                ask = ticker.ask
                
                # Skip invalid prices
                if not bid or not ask or bid <= 0 or ask <= 0:
                    continue
                    
                # Record every bid/ask change as a tick
                if bid != self.last_bid or ask != self.last_ask:
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    self.tick_buffer.append(now)
                    self.total_ticks += 1
                    self.last_bid = bid
                    self.last_ask = ask
                    self.current_bid = bid
                    self.current_ask = ask
    
    def get_velocity(self, lookback_minutes: int) -> float:
        """Calculate velocity from tick buffer."""
        if not self.tick_buffer:
            return 0.0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=lookback_minutes)
        count = sum(1 for t in self.tick_buffer if t >= cutoff)
        return count / lookback_minutes if lookback_minutes > 0 else 0.0
        
    def init_csv(self):
        """Initialize CSV."""
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'timestamp_utc', 'hour_utc', 'weekday',
                'bid', 'ask', 'mid',
                'velocity_1m', 'velocity_3m', 'velocity_5m', 'velocity_10m',
                'buffer_size', 'total_ticks'
            ])
        self.logger.info(f"CSV log: {self.csv_path}")
        
    def _reconnect(self):
        """Reconnect to IBKR after a disconnect."""
        max_retries = 60  # Try for up to 5 minutes (5s between attempts)
        for attempt in range(1, max_retries + 1):
            self.logger.info(f"Reconnect attempt {attempt}/{max_retries}...")
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
            except Exception:
                pass
            
            # Create fresh IB instance to avoid stale state
            self.ib = IB()
            time.sleep(5)
            
            if self.connect():
                self.subscribe()
                self.logger.info("Reconnected successfully, resuming logging")
                return True
        
        self.logger.error("Failed to reconnect after all retries")
        return False

    def _log_tick(self, last_print_time):
        """Write one CSV row and console line. Returns updated last_print_time."""
        if time.time() - last_print_time < 5:
            return last_print_time
        
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        vel_1m = self.get_velocity(1)
        vel_3m = self.get_velocity(3)
        vel_5m = self.get_velocity(5)
        vel_10m = self.get_velocity(10)
        buffer_size = len(self.tick_buffer)
        
        bid = self.current_bid
        ask = self.current_ask
        mid = (bid + ask) / 2 if bid > 0 else 0
        
        # Write CSV
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                now_utc.strftime('%Y-%m-%d %H:%M:%S'),
                now_utc.hour,
                now_utc.weekday(),
                f'{bid:.2f}' if bid > 0 else '',
                f'{ask:.2f}' if ask > 0 else '',
                f'{mid:.2f}' if mid > 0 else '',
                f'{vel_1m:.1f}',
                f'{vel_3m:.1f}',
                f'{vel_5m:.1f}',
                f'{vel_10m:.1f}',
                buffer_size,
                self.total_ticks
            ])
        
        self.records_logged += 1
        
        # Console output
        price_str = f"{bid:.2f}/{ask:.2f}" if bid > 0 else "N/A"
        
        vel_marker = ""
        if self.instrument == 'XAUUSD' and vel_3m >= 168:
            vel_marker = " ** ABOVE THRESHOLD **"
        elif self.instrument == 'EURUSD' and vel_3m >= 50:
            vel_marker = " ** ABOVE THRESHOLD **"
        
        print(f"[{now_utc.strftime('%H:%M:%S')}] Price: {price_str:>13s}  "
              f"Vel: 1m={vel_1m:>6.0f} 3m={vel_3m:>6.0f} 5m={vel_5m:>6.0f}  "
              f"Buffer: {buffer_size:>6,}  Total: {self.total_ticks:>8,}{vel_marker}")
        
        return time.time()

    def run(self):
        """Main logging loop with auto-reconnect."""
        if not self.connect():
            return
            
        self.subscribe()
        self.init_csv()
        
        print("\n" + "="*80)
        print(f"REAL-TIME VELOCITY LOGGER - {self.instrument}")
        print("="*80)
        print("Event-driven: captures every bid/ask update from IBKR")
        print(f"Log file: {self.csv_path}")
        print("Auto-reconnect: ON")
        print("Press Ctrl+C to stop")
        print("="*80 + "\n")
        
        last_print_time = time.time()
        
        try:
            while True:
                try:
                    # Let ib_insync process events
                    self.ib.sleep(0.25)
                    last_print_time = self._log_tick(last_print_time)
                    
                except (ConnectionError, OSError, asyncio.CancelledError) as e:
                    self.logger.warning(f"Connection lost: {e}")
                    if not self._reconnect():
                        self.logger.error("Giving up after failed reconnection")
                        break
                    last_print_time = time.time()
                
        except KeyboardInterrupt:
            print("\n" + "="*80)
            print("STOPPED")
            print("="*80)
            
            uptime = datetime.now() - self.start_time
            print(f"\nSession Stats:")
            print(f"  Uptime:        {str(uptime).split('.')[0]}")
            print(f"  Total ticks:   {self.total_ticks:,}")
            print(f"  Records:       {self.records_logged:,}")
            print(f"  Log file:      {self.csv_path}")
            
            if self.total_ticks > 0:
                avg_tpm = self.total_ticks / (uptime.total_seconds() / 60)
                print(f"  Avg velocity:  {avg_tpm:.1f} ticks/min")
            
            print("="*80)
            
        finally:
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
            except Exception:
                pass


def main():
    import sys
    print("="*80)
    print("REAL-TIME VELOCITY LOGGER (Event-Driven)")
    print("="*80)
    
    if len(sys.argv) > 1:
        instrument = sys.argv[1].strip().upper()
    else:
        instrument = input("Enter instrument (XAUUSD or EURUSD): ").strip().upper()
    
    if instrument not in ['XAUUSD', 'EURUSD']:
        print(f"Unknown instrument: {instrument}")
        return
        
    logger = RealtimeVelocityLogger(instrument)
    logger.run()


if __name__ == "__main__":
    main()
