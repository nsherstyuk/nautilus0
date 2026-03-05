"""
xauusd_orb_live.py -- Live XAUUSD Asian Range -> London Breakout

Automated execution via IBKR:
  1. At 06:00 UTC: computes Asian range (00:00-06:00 UTC high/low)
  2. At 08:00 UTC: places bracket orders (buy stop + sell stop) at range edges
  3. When one side fills: cancels the other, SL + TP are attached
  4. At 16:00 UTC: cancels any unfilled orders, closes any open position
  5. Logs everything

IBKR contract: XAUUSD CFD on SMART exchange
  - Minimum: 1 oz
  - Margin: ~5% (~$150 per oz at $3000)
  - Commission: ~$0.015 per oz (negligible)

Usage:
  # Dry run -- logs signals, does NOT place orders:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_live.py --dry-run

  # Live paper trading:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_live.py

  # Live paper, 10 oz position:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_live.py --qty 10

  # Custom IBKR port (live account):
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_live.py --port 4001 --qty 10

Environment:
  ORB_IB_HOST    IBKR host (default: 127.0.0.1)
  ORB_IB_PORT    IBKR port (default: 4002 = paper)
  ORB_CLIENT_ID  Client ID (default: 60)
  ORB_QTY        Position size in oz (default: 1)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "trading_system_v4" / "state"
LOG_DIR = ROOT / "trading_system_v4" / "logs"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("xauusd_orb")
log.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_sh.setLevel(logging.INFO)
log.addHandler(_sh)

_fh = logging.FileHandler(LOG_DIR / "xauusd_orb_live.log")
_fh.setFormatter(_fmt)
_fh.setLevel(logging.DEBUG)
log.addHandler(_fh)

# ── Trade log (CSV) ──────────────────────────────────────────────────────────
TRADE_LOG = LOG_DIR / "xauusd_orb_trades.csv"


def log_trade(trade: dict):
    """Append a trade record to the CSV log."""
    import csv
    is_new = not TRADE_LOG.exists()
    with open(TRADE_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'date', 'direction', 'entry', 'exit', 'sl', 'tp',
            'range_high', 'range_low', 'range_size', 'qty', 'pnl_per_oz',
            'pnl_total', 'result', 'hold_minutes'
        ])
        if is_new:
            writer.writeheader()
        writer.writerow(trade)


# ── Strategy Constants ────────────────────────────────────────────────────────
ASIAN_START_HOUR = 0     # UTC
ASIAN_END_HOUR = 6       # UTC
TRADE_START_HOUR = 8     # UTC -- place orders
TRADE_END_HOUR = 16      # UTC -- cancel/close everything
RR_RATIO = 2.0           # Reward:Risk


# ── State Machine ─────────────────────────────────────────────────────────────
class ORBState:
    """Persisted state for crash recovery."""
    
    IDLE = "IDLE"                  # Waiting for Asian range
    RANGE_COMPUTED = "RANGE_COMPUTED"  # Asian range known, waiting to place orders
    ORDERS_PLACED = "ORDERS_PLACED"   # Bracket orders live
    IN_TRADE = "IN_TRADE"             # One side filled, in position
    DONE_TODAY = "DONE_TODAY"          # Today's trade completed
    
    def __init__(self):
        self.state_file = STATE_DIR / "xauusd_orb_state.json"
        self.status = self.IDLE
        self.trade_date: Optional[str] = None
        self.range_high: float = 0
        self.range_low: float = 0
        self.range_size: float = 0
        self.direction: Optional[str] = None  # LONG or SHORT
        self.entry_price: float = 0
        self.sl_price: float = 0
        self.tp_price: float = 0
        self.entry_time: Optional[str] = None
        self.buy_order_id: int = 0
        self.sell_order_id: int = 0
        self.load()
    
    def load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
                log.debug(f"State loaded: {self.status} for {self.trade_date}")
            except Exception as e:
                log.warning(f"Failed to load state: {e}")
    
    def save(self):
        data = {
            'status': self.status,
            'trade_date': self.trade_date,
            'range_high': self.range_high,
            'range_low': self.range_low,
            'range_size': self.range_size,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'tp_price': self.tp_price,
            'entry_time': self.entry_time,
            'buy_order_id': self.buy_order_id,
            'sell_order_id': self.sell_order_id,
        }
        self.state_file.write_text(json.dumps(data, indent=2))
    
    def reset_for_new_day(self, today_str: str):
        self.status = self.IDLE
        self.trade_date = today_str
        self.range_high = 0
        self.range_low = 0
        self.range_size = 0
        self.direction = None
        self.entry_price = 0
        self.sl_price = 0
        self.tp_price = 0
        self.entry_time = None
        self.buy_order_id = 0
        self.sell_order_id = 0
        self.save()


# ── Gateway process management ────────────────────────────────────────────────

IBGW_EXE = Path(r"C:\Jts\ibgateway\1041\ibgateway.exe")


def is_gateway_running() -> bool:
    """Check if ibgateway process is alive."""
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ibgateway.exe"],
            capture_output=True, text=True, timeout=10
        )
        return "ibgateway.exe" in result.stdout
    except Exception:
        return False


def is_port_listening(port: int) -> bool:
    """Check if the API port is accepting connections.
    
    Uses netstat to avoid opening raw TCP connections to IBKR's API port,
    which leaves CLOSE_WAIT zombie sockets and exhausts Gateway's pool.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        target = f":{port}"
        for line in result.stdout.splitlines():
            if "LISTENING" in line and target in line:
                return True
        return False
    except Exception:
        return False


def start_gateway():
    """Launch IB Gateway if not already running.
    
    Note: Gateway still requires manual login on first start.
    Subsequent restarts within the same day use AutoRestart=1.
    """
    if is_gateway_running():
        log.info("IB Gateway already running")
        return True
    
    if not IBGW_EXE.exists():
        log.error(f"IB Gateway not found at {IBGW_EXE}")
        return False
    
    import subprocess
    log.info(f"Starting IB Gateway: {IBGW_EXE}")
    subprocess.Popen(
        [str(IBGW_EXE)],
        cwd=str(IBGW_EXE.parent),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    log.info("IB Gateway process launched (may need manual login on first start)")
    return True


# ── IBKR Connection Manager ──────────────────────────────────────────────────

class IBKRConnection:
    """Manages IBKR connection with auto-reconnect and Gateway health checks.
    
    Handles:
      - Initial connection with retry
      - Disconnect detection via ib_insync events
      - Automatic reconnect with exponential backoff
      - Gateway process liveness check before reconnect
      - Contract re-qualification after reconnect
    """
    
    MAX_RETRIES = 10
    BASE_BACKOFF = 5        # seconds
    MAX_BACKOFF = 300       # 5 minutes
    HEARTBEAT_INTERVAL = 30 # seconds
    GATEWAY_STARTUP_WAIT = 45  # seconds to wait for Gateway API after launch
    
    def __init__(self, host: str, port: int, client_id: int):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = None
        self.contract = None
        self._connected = False
        self._disconnect_count = 0
        self._last_heartbeat = 0.0
    
    @property
    def connected(self) -> bool:
        """True if ib_insync thinks we're connected."""
        return self.ib is not None and self.ib.isConnected()
    
    def connect(self) -> bool:
        """Connect to IBKR with retry. Returns True on success."""
        from ib_insync import IB
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            backoff = min(self.BASE_BACKOFF * (2 ** (attempt - 1)), self.MAX_BACKOFF)
            
            try:
                # Ensure Gateway is running
                if not is_gateway_running():
                    log.warning("Gateway not running -- attempting to start...")
                    start_gateway()
                    log.info(f"Waiting {self.GATEWAY_STARTUP_WAIT}s for Gateway to initialize...")
                    time.sleep(self.GATEWAY_STARTUP_WAIT)
                
                # Wait for API port
                if not is_port_listening(self.port):
                    log.warning(f"Port {self.port} not listening yet. "
                               f"Attempt {attempt}/{self.MAX_RETRIES}, "
                               f"retry in {backoff}s...")
                    time.sleep(backoff)
                    continue
                
                # Disconnect stale connection if any
                if self.ib is not None:
                    try:
                        self.ib.disconnect()
                    except Exception:
                        pass
                
                self.ib = IB()
                self.ib.connect(self.host, self.port, clientId=self.client_id,
                               timeout=20)
                
                # Register disconnect handler
                self.ib.disconnectedEvent += self._on_disconnect
                
                # Qualify contract
                self.contract = self._qualify_contract()
                
                self._connected = True
                self._last_heartbeat = time.time()
                log.info(f"Connected to IBKR at {self.host}:{self.port} "
                        f"(clientId={self.client_id})")
                return True
                
            except Exception as e:
                log.warning(f"Connection attempt {attempt}/{self.MAX_RETRIES} "
                           f"failed: {e}")
                if attempt < self.MAX_RETRIES:
                    log.info(f"Retrying in {backoff}s...")
                    time.sleep(backoff)
        
        log.error(f"Failed to connect after {self.MAX_RETRIES} attempts")
        return False
    
    def _qualify_contract(self):
        """Qualify the XAUUSD contract. Tries CFD, then Forex."""
        from ib_insync import Contract, Forex
        
        contract = Contract()
        contract.symbol = "XAUUSD"
        contract.secType = "CFD"
        contract.exchange = "SMART"
        contract.currency = "USD"
        
        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            log.info(f"Contract qualified (CFD): {contract}")
            return contract
        
        log.warning("Could not qualify XAUUSD CFD. Trying Forex XAUUSD...")
        contract = Forex("XAUUSD")
        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            log.info(f"Contract qualified (Forex): {contract}")
            return contract
        
        raise RuntimeError("Cannot qualify XAUUSD contract on IBKR. "
                         "Check market data subscriptions.")
    
    def _on_disconnect(self):
        """Called by ib_insync when connection drops."""
        self._connected = False
        self._disconnect_count += 1
        log.warning(f"IBKR disconnected (#{self._disconnect_count})")
    
    def ensure_connected(self) -> bool:
        """Check connection health; reconnect if needed. Returns True if connected."""
        # Fast path: still connected
        if self.connected:
            now = time.time()
            # Periodic heartbeat -- request current time from server
            if now - self._last_heartbeat > self.HEARTBEAT_INTERVAL:
                try:
                    self.ib.reqCurrentTime()
                    self._last_heartbeat = now
                except Exception:
                    log.warning("Heartbeat failed -- connection may be stale")
                    self._connected = False
            
            if self._connected:
                return True
        
        # Need to reconnect
        log.info("Connection lost -- attempting reconnect...")
        return self.connect()
    
    def sleep(self, seconds: float):
        """ib.sleep() wrapper that handles disconnection."""
        if self.connected:
            try:
                self.ib.sleep(seconds)
            except Exception:
                self._connected = False
                time.sleep(seconds)
        else:
            time.sleep(seconds)
    
    def disconnect(self):
        """Clean disconnect."""
        if self.ib is not None:
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self._connected = False


def get_current_price(conn: IBKRConnection) -> Optional[float]:
    """Get current mid price. Returns None on failure."""
    if not conn.ensure_connected():
        return None
    try:
        ticker = conn.ib.reqMktData(conn.contract, '', False, False)
        conn.sleep(2)
        
        mid = None
        if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
            mid = (ticker.bid + ticker.ask) / 2
        elif ticker.last and ticker.last > 0:
            mid = ticker.last
        
        conn.ib.cancelMktData(conn.contract)
        return mid
    except Exception as e:
        log.warning(f"get_current_price failed: {e}")
        return None


def get_asian_range_live(conn: IBKRConnection) -> dict:
    """
    Fetch the Asian range (00:00-06:00 UTC today) from IBKR historical bars.
    Uses 5-minute bars for the last 8 hours.
    """
    if not conn.ensure_connected():
        log.error("Not connected -- cannot fetch Asian range")
        return {}
    
    from ib_insync import util
    
    now_utc = datetime.now(tz=timezone.utc)
    
    try:
        bars = conn.ib.reqHistoricalData(
            conn.contract,
            endDateTime="",
            durationStr="8 hours",
            barSizeSetting="5 mins",
            whatToShow="MIDPOINT",
            useRTH=False,
            formatDate=2,  # UTC
        )
    except Exception as e:
        log.error(f"Historical data request failed: {e}")
        return {}
    
    if not bars:
        log.error("No historical bars received from IBKR")
        return {}
    
    df = util.df(bars)
    df['date_col'] = pd.to_datetime(df['date'])
    
    # Ensure UTC
    if df['date_col'].dt.tz is None:
        df['date_col'] = df['date_col'].dt.tz_localize('UTC')
    
    today = now_utc.date()
    df['bar_date'] = df['date_col'].dt.date
    df['bar_hour'] = df['date_col'].dt.hour
    
    # Filter to Asian session today (00:00-06:00 UTC)
    asian = df[(df['bar_date'] == today) & (df['bar_hour'] >= 0) & (df['bar_hour'] < 6)]
    
    if len(asian) < 3:
        log.warning(f"Only {len(asian)} Asian bars available (need ≥3)")
        return {}
    
    range_high = asian['high'].max()
    range_low = asian['low'].min()
    range_size = range_high - range_low
    
    if range_size <= 0:
        return {}
    
    log.info(f"Asian range: {range_low:.2f} - {range_high:.2f} "
             f"(size: {range_size:.2f}, {len(asian)} bars)")
    
    return {
        'range_high': range_high,
        'range_low': range_low,
        'range_size': range_size,
        'n_bars': len(asian),
    }


def place_bracket_orders(conn: IBKRConnection, state: ORBState, qty: int, dry_run: bool):
    """
    Place two bracket orders:
      1. Buy stop at range_high -> SL at range_low, TP at high + 2*range
      2. Sell stop at range_low -> SL at range_high, TP at low - 2*range
    
    One-cancels-all (OCA) group ensures only one fills.
    """
    from ib_insync import Order
    
    rh = state.range_high
    rl = state.range_low
    rs = state.range_size
    
    long_entry = round(rh, 2)
    long_sl = round(rl, 2)
    long_tp = round(rh + RR_RATIO * rs, 2)
    
    short_entry = round(rl, 2)
    short_sl = round(rh, 2)
    short_tp = round(rl - RR_RATIO * rs, 2)
    
    log.info(f"{'[DRY RUN] ' if dry_run else ''}"
             f"Placing bracket orders:")
    log.info(f"  LONG:  entry={long_entry}, SL={long_sl}, TP={long_tp}")
    log.info(f"  SHORT: entry={short_entry}, SL={short_sl}, TP={short_tp}")
    log.info(f"  Qty: {qty} oz, Risk/oz: ${rs:.2f}")
    
    if dry_run:
        state.status = ORBState.ORDERS_PLACED
        state.save()
        return
    
    if not conn.ensure_connected():
        log.error("Not connected -- cannot place orders")
        return
    
    oca_group = f"XAUUSD_ORB_{state.trade_date}"
    
    # ── Buy stop bracket ──
    buy_parent = Order()
    buy_parent.action = "BUY"
    buy_parent.orderType = "STP"
    buy_parent.totalQuantity = qty
    buy_parent.auxPrice = long_entry  # stop trigger price
    buy_parent.tif = "GTC"
    buy_parent.ocaGroup = oca_group
    buy_parent.ocaType = 1  # Cancel remaining on fill
    buy_parent.transmit = False
    
    buy_sl = Order()
    buy_sl.action = "SELL"
    buy_sl.orderType = "STP"
    buy_sl.totalQuantity = qty
    buy_sl.auxPrice = long_sl
    buy_sl.tif = "GTC"
    buy_sl.parentId = 0  # set after placement
    buy_sl.transmit = False
    
    buy_tp = Order()
    buy_tp.action = "SELL"
    buy_tp.orderType = "LMT"
    buy_tp.totalQuantity = qty
    buy_tp.lmtPrice = long_tp
    buy_tp.tif = "GTC"
    buy_tp.parentId = 0
    buy_tp.transmit = False
    
    # ── Sell stop bracket ──
    sell_parent = Order()
    sell_parent.action = "SELL"
    sell_parent.orderType = "STP"
    sell_parent.totalQuantity = qty
    sell_parent.auxPrice = short_entry
    sell_parent.tif = "GTC"
    sell_parent.ocaGroup = oca_group
    sell_parent.ocaType = 1
    sell_parent.transmit = False
    
    sell_sl = Order()
    sell_sl.action = "BUY"
    sell_sl.orderType = "STP"
    sell_sl.totalQuantity = qty
    sell_sl.auxPrice = short_sl
    sell_sl.tif = "GTC"
    sell_sl.parentId = 0
    sell_sl.transmit = False
    
    sell_tp = Order()
    sell_tp.action = "BUY"
    sell_tp.orderType = "LMT"
    sell_tp.totalQuantity = qty
    sell_tp.lmtPrice = short_tp
    sell_tp.tif = "GTC"
    sell_tp.parentId = 0
    sell_tp.transmit = True  # transmit all when last order placed
    
    try:
        # Place buy bracket
        buy_trade = conn.ib.placeOrder(conn.contract, buy_parent)
        conn.sleep(1)
        buy_parent_id = buy_trade.order.orderId
        
        buy_sl.parentId = buy_parent_id
        conn.ib.placeOrder(conn.contract, buy_sl)
        conn.sleep(0.5)
        
        buy_tp.parentId = buy_parent_id
        buy_tp.transmit = True
        conn.ib.placeOrder(conn.contract, buy_tp)
        conn.sleep(1)
        
        log.info(f"Buy bracket placed: parent orderId={buy_parent_id}")
        
        # Place sell bracket
        sell_trade = conn.ib.placeOrder(conn.contract, sell_parent)
        conn.sleep(1)
        sell_parent_id = sell_trade.order.orderId
        
        sell_sl.parentId = sell_parent_id
        conn.ib.placeOrder(conn.contract, sell_sl)
        conn.sleep(0.5)
        
        sell_tp.parentId = sell_parent_id
        sell_tp.transmit = True
        conn.ib.placeOrder(conn.contract, sell_tp)
        conn.sleep(1)
        
        log.info(f"Sell bracket placed: parent orderId={sell_parent_id}")
        
        state.buy_order_id = buy_parent_id
        state.sell_order_id = sell_parent_id
        state.status = ORBState.ORDERS_PLACED
        state.save()
        
    except Exception as e:
        log.error(f"Order placement failed: {e}")
        # Orders are server-side; on reconnect we can check status
        raise


def check_fills(conn: IBKRConnection, state: ORBState, dry_run: bool) -> bool:
    """Check if either bracket's parent order has filled. Returns True if filled."""
    if dry_run:
        return False
    
    if not conn.ensure_connected():
        return False
    
    try:
        conn.sleep(0)  # process events
        
        for trade in conn.ib.trades():
            order = trade.order
            if order.orderId == state.buy_order_id:
                if trade.orderStatus.status == 'Filled':
                    fill_price = trade.orderStatus.avgFillPrice
                    log.info(f"BUY filled at {fill_price}")
                    state.direction = "LONG"
                    state.entry_price = fill_price
                    state.sl_price = state.range_low
                    state.tp_price = round(state.range_high + RR_RATIO * state.range_size, 2)
                    state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                    state.status = ORBState.IN_TRADE
                    state.save()
                    return True
                    
            elif order.orderId == state.sell_order_id:
                if trade.orderStatus.status == 'Filled':
                    fill_price = trade.orderStatus.avgFillPrice
                    log.info(f"SELL filled at {fill_price}")
                    state.direction = "SHORT"
                    state.entry_price = fill_price
                    state.sl_price = state.range_high
                    state.tp_price = round(state.range_low - RR_RATIO * state.range_size, 2)
                    state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                    state.status = ORBState.IN_TRADE
                    state.save()
                    return True
    except Exception as e:
        log.warning(f"check_fills error: {e}")
    
    return False


def check_trade_exit(conn: IBKRConnection, state: ORBState, dry_run: bool) -> bool:
    """Check if SL or TP child orders have filled. Returns True if trade done."""
    if dry_run:
        return False
    
    if not conn.ensure_connected():
        return False
    
    try:
        conn.sleep(0)
        
        # Check if we still have a position
        positions = conn.ib.positions()
        has_position = any(
            p.contract.symbol == "XAUUSD" and abs(p.position) > 0
            for p in positions
        )
        
        if not has_position:
            # Position closed (SL or TP hit)
            log.info("Position closed (SL or TP filled)")
            return True
    except Exception as e:
        log.warning(f"check_trade_exit error: {e}")
    
    return False


def cancel_all_and_close(conn: IBKRConnection, state: ORBState, qty: int, dry_run: bool):
    """Cancel unfilled orders and close any open position (end of day)."""
    if dry_run:
        log.info("[DRY RUN] Would cancel all orders and close position")
        return
    
    if not conn.ensure_connected():
        log.error("Cannot cancel/close -- not connected")
        return
    
    try:
        # Cancel all open orders for this contract
        open_orders = conn.ib.openOrders()
        for order in open_orders:
            try:
                conn.ib.cancelOrder(order)
                conn.sleep(0.5)
            except Exception as e:
                log.warning(f"Cancel failed: {e}")
        
        conn.sleep(2)
        
        # Close any remaining position
        positions = conn.ib.positions()
        for pos in positions:
            if pos.contract.symbol == "XAUUSD" and abs(pos.position) > 0:
                close_action = "SELL" if pos.position > 0 else "BUY"
                close_qty = abs(pos.position)
                
                from ib_insync import MarketOrder
                close_order = MarketOrder(close_action, close_qty)
                trade = conn.ib.placeOrder(conn.contract, close_order)
                conn.sleep(3)
                
                fill_price = trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice else 0
                log.info(f"Closed position: {close_action} {close_qty} at {fill_price}")
    except Exception as e:
        log.error(f"cancel_all_and_close failed: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_loop(conn: IBKRConnection, state: ORBState, qty: int, dry_run: bool):
    """Main event loop -- runs until end of London session.
    
    Resilient to IBKR disconnections: each iteration checks
    connection health via conn.ensure_connected() before
    issuing any API call.
    """
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    
    # New day?
    if state.trade_date != today_str:
        log.info(f"New trading day: {today_str}")
        state.reset_for_new_day(today_str)
    
    # Skip weekends
    now = datetime.now(tz=timezone.utc)
    if now.weekday() >= 5:  # Sat=5, Sun=6
        log.info("Weekend -- no trading")
        return
    
    log.info(f"Starting ORB loop | state={state.status} | "
             f"date={state.trade_date} | qty={qty} oz | "
             f"dry_run={dry_run}")
    
    poll_interval = 10  # seconds between checks
    
    while True:
        now = datetime.now(tz=timezone.utc)
        hour = now.hour
        
        # ── Ensure connection is alive before each iteration ──
        if not conn.ensure_connected():
            log.warning("Connection unavailable -- sleeping 30s before retry")
            time.sleep(30)
            continue
        
        try:
            # ── State: IDLE -- waiting for Asian range to complete ──
            if state.status == ORBState.IDLE:
                if hour >= ASIAN_END_HOUR:
                    # Asian session over -- compute range
                    log.info("Computing Asian range from IBKR data...")
                    
                    range_data = get_asian_range_live(conn)
                    
                    if range_data:
                        state.range_high = range_data['range_high']
                        state.range_low = range_data['range_low']
                        state.range_size = range_data['range_size']
                        state.status = ORBState.RANGE_COMPUTED
                        state.save()
                        
                        log.info(f"Asian range computed: "
                                f"{state.range_low:.2f} - {state.range_high:.2f} "
                                f"(size: {state.range_size:.2f})")
                        
                        # Filter: skip very tight or very wide ranges
                        range_pct = state.range_size / state.range_high * 100
                        if range_pct < 0.05:
                            log.warning(f"Range too tight ({range_pct:.3f}%). Skipping today.")
                            state.status = ORBState.DONE_TODAY
                            state.save()
                        elif range_pct > 2.0:
                            log.warning(f"Range too wide ({range_pct:.2f}%). Skipping today.")
                            state.status = ORBState.DONE_TODAY
                            state.save()
                    else:
                        log.warning("Could not compute Asian range. Will retry...")
                        conn.sleep(60)
                        continue
                else:
                    log.debug(f"Waiting for Asian session to end ({hour}/6 UTC)")
            
            # ── State: RANGE_COMPUTED -- place orders at trade start ──
            elif state.status == ORBState.RANGE_COMPUTED:
                if hour >= TRADE_START_HOUR:
                    log.info("Trade window open -- placing bracket orders")
                    place_bracket_orders(conn, state, qty, dry_run)
                else:
                    log.debug(f"Waiting for trade window ({hour}/{TRADE_START_HOUR} UTC)")
            
            # ── State: ORDERS_PLACED -- monitor for fills ──
            elif state.status == ORBState.ORDERS_PLACED:
                if hour >= TRADE_END_HOUR:
                    log.info("Trade window closed. Cancelling unfilled orders.")
                    cancel_all_and_close(conn, state, qty, dry_run)
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    log.info("No fill today. Done.")
                    break
                
                filled = check_fills(conn, state, dry_run)
                if filled:
                    log.info(f"Entered {state.direction} at {state.entry_price:.2f}")
                    log.info(f"SL={state.sl_price:.2f}, TP={state.tp_price:.2f}")
                
                # Dry run: simulate by checking price
                if dry_run and not filled:
                    price = get_current_price(conn)
                    if price:
                        if price > state.range_high:
                            log.info(f"[DRY RUN] Price {price:.2f} > range high "
                                    f"{state.range_high:.2f} -> would go LONG")
                            state.direction = "LONG"
                            state.entry_price = state.range_high
                            state.sl_price = state.range_low
                            state.tp_price = round(state.range_high + RR_RATIO * state.range_size, 2)
                            state.entry_time = now.isoformat()
                            state.status = ORBState.IN_TRADE
                            state.save()
                        elif price < state.range_low:
                            log.info(f"[DRY RUN] Price {price:.2f} < range low "
                                    f"{state.range_low:.2f} -> would go SHORT")
                            state.direction = "SHORT"
                            state.entry_price = state.range_low
                            state.sl_price = state.range_high
                            state.tp_price = round(state.range_low - RR_RATIO * state.range_size, 2)
                            state.entry_time = now.isoformat()
                            state.status = ORBState.IN_TRADE
                            state.save()
            
            # ── State: IN_TRADE -- monitor SL/TP ──
            elif state.status == ORBState.IN_TRADE:
                if hour >= TRADE_END_HOUR:
                    log.info("Trade window closed while in position. Closing at market.")
                    cancel_all_and_close(conn, state, qty, dry_run)
                    
                    # Log the trade
                    price = get_current_price(conn) or state.entry_price
                    pnl_per_oz = (price - state.entry_price) if state.direction == "LONG" else (state.entry_price - price)
                    
                    log_trade({
                        'timestamp': now.isoformat(),
                        'date': state.trade_date,
                        'direction': state.direction,
                        'entry': state.entry_price,
                        'exit': price,
                        'sl': state.sl_price,
                        'tp': state.tp_price,
                        'range_high': state.range_high,
                        'range_low': state.range_low,
                        'range_size': state.range_size,
                        'qty': qty,
                        'pnl_per_oz': round(pnl_per_oz, 2),
                        'pnl_total': round(pnl_per_oz * qty, 2),
                        'result': 'TIME',
                        'hold_minutes': int((now - datetime.fromisoformat(state.entry_time)).total_seconds() / 60) if state.entry_time else 0,
                    })
                    
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    break
                
                done = check_trade_exit(conn, state, dry_run)
                
                if dry_run:
                    price = get_current_price(conn)
                    if price:
                        if state.direction == "LONG":
                            if price <= state.sl_price:
                                log.info(f"[DRY RUN] SL hit at {state.sl_price:.2f}")
                                done = True; result = 'SL'; exit_price = state.sl_price
                            elif price >= state.tp_price:
                                log.info(f"[DRY RUN] TP hit at {state.tp_price:.2f}")
                                done = True; result = 'TP'; exit_price = state.tp_price
                        else:
                            if price >= state.sl_price:
                                log.info(f"[DRY RUN] SL hit at {state.sl_price:.2f}")
                                done = True; result = 'SL'; exit_price = state.sl_price
                            elif price <= state.tp_price:
                                log.info(f"[DRY RUN] TP hit at {state.tp_price:.2f}")
                                done = True; result = 'TP'; exit_price = state.tp_price
                        
                        if not done:
                            unrealized = (price - state.entry_price) if state.direction == "LONG" else (state.entry_price - price)
                            log.debug(f"In {state.direction} | price={price:.2f} | "
                                     f"PnL/oz=${unrealized:+.2f} | "
                                     f"SL={state.sl_price:.2f} TP={state.tp_price:.2f}")
                
                if done:
                    # Determine result
                    if not dry_run:
                        price = get_current_price(conn) or state.entry_price
                        pnl_per_oz = (price - state.entry_price) if state.direction == "LONG" else (state.entry_price - price)
                        result = 'TP' if pnl_per_oz > 0 else 'SL'
                        exit_price = price
                    else:
                        if 'exit_price' not in dir():
                            exit_price = state.entry_price
                            result = 'UNKNOWN'
                        pnl_per_oz = (exit_price - state.entry_price) if state.direction == "LONG" else (state.entry_price - exit_price)
                    
                    log.info(f"Trade closed: {state.direction} {result} | "
                            f"Entry={state.entry_price:.2f} Exit={exit_price:.2f} | "
                            f"PnL/oz=${pnl_per_oz:+.2f} | Total=${pnl_per_oz*qty:+.2f}")
                    
                    log_trade({
                        'timestamp': now.isoformat(),
                        'date': state.trade_date,
                        'direction': state.direction,
                        'entry': state.entry_price,
                        'exit': exit_price,
                        'sl': state.sl_price,
                        'tp': state.tp_price,
                        'range_high': state.range_high,
                        'range_low': state.range_low,
                        'range_size': state.range_size,
                        'qty': qty,
                        'pnl_per_oz': round(pnl_per_oz, 2),
                        'pnl_total': round(pnl_per_oz * qty, 2),
                        'result': result,
                        'hold_minutes': int((now - datetime.fromisoformat(state.entry_time)).total_seconds() / 60) if state.entry_time else 0,
                    })
                    
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    break
            
            # ── State: DONE_TODAY ──
            elif state.status == ORBState.DONE_TODAY:
                log.info("Today's trading complete.")
                break
            
        except Exception as e:
            log.error(f"Error in loop: {e}", exc_info=True)
            time.sleep(30)
            continue
        
        conn.sleep(poll_interval)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="XAUUSD Asian Range -> London Breakout -- Live Execution"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log only, do not place orders")
    parser.add_argument("--qty", type=int,
                        default=int(os.environ.get("ORB_QTY", "1")),
                        help="Position size in oz (default: 1)")
    parser.add_argument("--host", type=str,
                        default=os.environ.get("ORB_IB_HOST", "127.0.0.1"),
                        help="IBKR host")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("ORB_IB_PORT", "4002")),
                        help="IBKR port (4002=paper, 4001=live)")
    parser.add_argument("--client-id", type=int,
                        default=int(os.environ.get("ORB_CLIENT_ID", "60")),
                        help="IBKR client ID")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  XAUUSD Asian Range -> London Breakout")
    print(f"  Mode: {'DRY RUN (no orders)' if args.dry_run else 'LIVE'}")
    print(f"  Qty: {args.qty} oz")
    print(f"  IBKR: {args.host}:{args.port} (clientId={args.client_id})")
    print("=" * 60)
    
    if not args.dry_run:
        print("\n  ⚠️  LIVE MODE -- real orders will be placed!")
        print("  Press Ctrl+C to abort.\n")
    
    state = ORBState()
    conn = IBKRConnection(args.host, args.port, args.client_id)
    
    if not conn.connect():
        log.error("Could not connect to IBKR after retries")
        log.info("Make sure IB Gateway is running and logged in")
        sys.exit(1)
    
    # Register clean shutdown
    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        if not args.dry_run:
            cancel_all_and_close(conn, state, args.qty, args.dry_run)
        conn.disconnect()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    try:
        run_loop(conn, state, args.qty, args.dry_run)
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        if not args.dry_run:
            log.info("Cleaning up...")
            cancel_all_and_close(conn, state, args.qty, args.dry_run)
        conn.disconnect()
        log.info("Disconnected from IBKR")


if __name__ == "__main__":
    main()
