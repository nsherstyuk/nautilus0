"""
orb_live.py -- Live XAUUSD Asian Range -> London Breakout  (v5)

All parameters come from config.yaml.

Usage:
  # Dry run (no orders):
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_live --dry-run

  # Live paper trading:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_live

  # Override qty from command line:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_live --qty 10

  # Use a different config file:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_live --config my_config.yaml
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Optional

# Allow nested event loops -- required for ib_insync reconnection
# (same pattern as live/ib_bar_streamer.py which works reliably)
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

import pandas as pd

from v5_xauusd_orb.config import load_config, Config, ROOT


# ── Logging setup (deferred until config is loaded) ──────────────────────────

def setup_logging(cfg: Config) -> logging.Logger:
    log = logging.getLogger("xauusd_orb")
    if log.handlers:
        return log  # already set up
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    log.addHandler(sh)

    fh = logging.FileHandler(cfg.paths.live_log)
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)

    # Silence ib_insync's own console prints (e.g. raw "Error 162" lines).
    # Our _on_ib_error handler already filters and re-logs what matters.
    for _lib in ("ib_insync.wrapper", "ib_insync.client", "ib_insync"):
        logging.getLogger(_lib).setLevel(logging.CRITICAL)

    return log


# ── Trade CSV logger ─────────────────────────────────────────────────────────

TRADE_FIELDS = [
    'timestamp', 'date', 'direction', 'entry', 'exit', 'sl', 'tp',
    'range_high', 'range_low', 'range_size', 'qty', 'pnl_per_oz',
    'pnl_total', 'result', 'hold_minutes',
]


def log_trade(trade: dict, trade_log_path: str):
    """Append a trade record to the CSV log."""
    path = Path(trade_log_path)
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(trade)


# ── State Machine ─────────────────────────────────────────────────────────────

class ORBState:
    """Persisted state for crash recovery."""

    IDLE = "IDLE"
    RANGE_COMPUTED = "RANGE_COMPUTED"
    ORDERS_PLACED = "ORDERS_PLACED"
    IN_TRADE = "IN_TRADE"
    DONE_TODAY = "DONE_TODAY"

    def __init__(self, state_dir: str):
        self.state_file = Path(state_dir) / "xauusd_orb_state.json"
        self.status = self.IDLE
        self.trade_date: Optional[str] = None
        self.range_high: float = 0
        self.range_low: float = 0
        self.range_size: float = 0
        self.direction: Optional[str] = None
        self.entry_price: float = 0
        self.sl_price: float = 0
        self.tp_price: float = 0
        self.entry_time: Optional[str] = None
        self.buy_order_id: int = 0
        self.sell_order_id: int = 0
        self.be_applied: bool = False
        self.load()

    def load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
            except Exception:
                pass

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
            'be_applied': self.be_applied,
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
        self.be_applied = False
        self.save()


# ── IBKR Connection Manager ──────────────────────────────────────────────────
#
# Modeled on live/ib_bar_streamer.py IBBarStreamer which is battle-tested in
# the MTF v2 live system.  Key differences from the original v5 code:
#
#   1. nest_asyncio.apply() at module top for reliable ib_insync reconnection.
#   2. NO port probing (is_port_listening) -- raw TCP connections to the IBKR
#      API port leave CLOSE_WAIT zombie sockets that exhaust IB Gateway's
#      connection pool.  Instead, just try to connect and catch exceptions.
#   3. ib.errorEvent handler for disconnect detection (like IBBarStreamer).
#   4. Exponential backoff reconnect capped at max_backoff_sec.
# ──────────────────────────────────────────────────────────────────────────────

# Critical IB error codes that indicate a broken connection
_IB_CRITICAL_ERRORS = {
    504:   "Not connected",
    502:   "Couldn't connect to TWS",
    1100:  "Connectivity between IBKR and TWS lost",
    2110:  "Connectivity between TWS and server is broken",
    10182: "Failed to request live updates (disconnected)",
}
# Harmless warnings we ignore
_IB_WARNING_CODES = {
    2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158,
    2119,   # market data farm connecting
    354,    # market data not subscribed (paper account -- we use historical fallback)
    300,    # Can't find EId (orphaned ticker after failed reqMktData)
    10168,  # delayed data not enabled -- we get data via streaming type-3 anyway
    10167,  # delayed data farmConnection (Gateway)
}


class IBKRConnection:
    """IBKR connection with auto-reconnect.

    Follows the same connect / error-handler / reconnect pattern used by
    ``live.ib_bar_streamer.IBBarStreamer`` which runs 24/5 in production.
    """

    def __init__(self, cfg: Config, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self.host = cfg.ibkr.host
        self.port = cfg.ibkr.port
        self.client_id = cfg.ibkr.client_id
        self.ib = None
        self.contract = None
        self._connected = False
        self._disconnect_count = 0
        self._last_heartbeat = 0.0
        self._shutting_down = False
        self._price_ticker = None  # persistent streaming ticker for price

    # ── public interface ──────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()

    def connect(self) -> bool:
        """Connect to IB Gateway with retry + exponential backoff.

        Does NOT probe the port first -- just attempts the real ib_insync
        connect and lets the exception decide the retry.
        """
        from ib_insync import IB
        ic = self.cfg.ibkr

        for attempt in range(1, ic.max_retries + 1):
            backoff = min(ic.base_backoff_sec * (2 ** (attempt - 1)),
                          ic.max_backoff_sec)
            try:
                # Clean up any previous IB instance
                if self.ib is not None:
                    try:
                        self.ib.disconnect()
                    except Exception:
                        pass

                self.ib = IB()
                self.ib.errorEvent += self._on_ib_error
                self.ib.disconnectedEvent += self._on_disconnect

                self.ib.connect(self.host, self.port,
                                clientId=self.client_id,
                                timeout=ic.connect_timeout_sec)

                if not self.ib.isConnected():
                    raise ConnectionError("connect returned but isConnected=False")

                # Qualify contract
                self.contract = self._qualify_contract()
                self._connected = True
                self._last_heartbeat = time.time()
                self.log.info(f"Connected to IBKR at {self.host}:{self.port} "
                              f"(clientId={self.client_id})")

                # Start persistent streaming price ticker (delayed type-3).
                # snapshot=False is required: snapshot mode returns nan for
                # delayed CFD data on paper accounts, while streaming works.
                self._start_price_ticker()

                return True

            except Exception as e:
                self.log.warning(f"Connect attempt {attempt}/{ic.max_retries} "
                                 f"failed: {e}")
                if attempt < ic.max_retries:
                    self.log.info(f"Retrying in {backoff}s...")
                    time.sleep(backoff)

        self.log.error(f"Failed to connect after {ic.max_retries} attempts")
        return False

    def ensure_connected(self) -> bool:
        """Verify connection is alive; reconnect if needed."""
        if self._shutting_down:
            return False
        if self.connected:
            now = time.time()
            if now - self._last_heartbeat > self.cfg.ibkr.heartbeat_interval_sec:
                try:
                    self.ib.reqCurrentTime()
                    self._last_heartbeat = now
                except Exception:
                    self.log.warning("Heartbeat failed")
                    self._connected = False
            if self._connected:
                return True

        self.log.info("Connection lost -- reconnecting...")
        return self.connect()

    def sleep(self, seconds: float):
        """ib.sleep() wrapper -- falls back to time.sleep on disconnect."""
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
        self._shutting_down = True  # prevent reconnect loop on shutdown
        self._stop_price_ticker()
        if self.ib is not None:
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self._connected = False

    # ── private helpers ───────────────────────────────────────────────────

    def _start_price_ticker(self):
        """Start a persistent streaming market data subscription.

        Uses delayed data (type 3) in streaming mode (snapshot=False).
        TWS paper accounts support delayed streaming for CFDs even without
        a live market-data subscription.  Snapshot mode returns nan for CFDs
        on paper, but streaming mode works -- this is the same data channel
        that powers TWS charts.
        """
        try:
            self.ib.reqMarketDataType(3)  # delayed
            self._price_ticker = self.ib.reqMktData(
                self.contract, '', snapshot=False, regulatorySnapshot=False)
            self.ib.sleep(2)  # give initial data time to arrive
            bid = self._price_ticker.bid
            ask = self._price_ticker.ask
            import math
            if isinstance(bid, float) and not math.isnan(bid) and bid > 0:
                self.log.info(f"Price ticker started (delayed streaming) "
                              f"bid={bid:.2f} ask={ask:.2f}")
            else:
                self.log.warning("Price ticker started but no data yet "
                                 "(will retry on next read)")
        except Exception as e:
            self.log.warning(f"Failed to start price ticker: {e}")
            self._price_ticker = None

    def _stop_price_ticker(self):
        """Cancel the persistent price ticker."""
        if self._price_ticker is not None and self.ib is not None:
            try:
                self.ib.cancelMktData(self._price_ticker.contract)
            except Exception:
                pass
            self._price_ticker = None

    def _qualify_contract(self):
        from ib_insync import Contract, Forex
        ic = self.cfg.ibkr

        contract = Contract()
        contract.symbol = ic.symbol
        contract.secType = ic.sec_type
        contract.exchange = ic.exchange
        contract.currency = ic.currency

        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            self.log.info(f"Contract qualified ({ic.sec_type}): {contract}")
            return contract

        self.log.warning(f"Could not qualify {ic.symbol} {ic.sec_type}. "
                         f"Trying Forex...")
        contract = Forex(ic.symbol)
        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            self.log.info(f"Contract qualified (Forex): {contract}")
            return contract

        raise RuntimeError(f"Cannot qualify {ic.symbol} contract on IBKR.")

    def _on_disconnect(self):
        """Called by ib_insync when connection drops."""
        self._connected = False
        self._disconnect_count += 1
        self.log.warning(f"IBKR disconnected (#{self._disconnect_count})")

    def _on_ib_error(self, reqId: int, errorCode: int,
                     errorString: str, contract):
        """Handle IB errors -- detect critical disconnects.

        Mirrors live/ib_bar_streamer.py error handling.
        """
        if errorCode in _IB_WARNING_CODES:
            self.log.debug(f"IB warning {errorCode}: {errorString}")
            return
        if errorCode in _IB_CRITICAL_ERRORS:
            self._connected = False
            self.log.error(f"IB critical error {errorCode}: "
                           f"{_IB_CRITICAL_ERRORS[errorCode]} - {errorString}")
        else:
            if errorCode not in (162,):  # 162 = historical data cancelled
                self.log.warning(f"IB error {errorCode} (reqId={reqId}): "
                                 f"{errorString}")


# ── Price helpers ─────────────────────────────────────────────────────────────

def get_current_price(conn: IBKRConnection) -> Optional[float]:
    """Return current price from the persistent streaming ticker.

    Priority:
      1. Persistent delayed-streaming ticker (type 3, snapshot=False).
         This uses the same data channel as TWS charts.
      2. 5-min historical MIDPOINT bars (HMDS fallback).
      3. Daily historical MIDPOINT bar (last resort).
    """
    import math
    if not conn.ensure_connected():
        return None

    # 1) Read from persistent streaming ticker
    t = conn._price_ticker
    if t is not None:
        bid, ask = t.bid, t.ask
        if (isinstance(bid, float) and not math.isnan(bid) and bid > 0
                and isinstance(ask, float) and not math.isnan(ask) and ask > 0):
            return round((bid + ask) / 2, 2)
        # ticker exists but no bid/ask yet -- check close
        if isinstance(t.close, float) and not math.isnan(t.close) and t.close > 0:
            return t.close

    # 2) 5-min historical MIDPOINT (uses HMDS -- works for CFDs on paper)
    try:
        bars = conn.ib.reqHistoricalData(
            conn.contract, endDateTime="",
            durationStr="3600 S", barSizeSetting="5 mins",
            whatToShow="MIDPOINT", useRTH=False, formatDate=2,
        )
        if bars:
            return bars[-1].close
    except Exception:
        pass

    # 3) Daily fallback — least preferred, but better than n/a
    try:
        bars = conn.ib.reqHistoricalData(
            conn.contract, endDateTime="",
            durationStr="2 D", barSizeSetting="1 day",
            whatToShow="MIDPOINT", useRTH=False, formatDate=2,
        )
        if bars:
            return bars[-1].close
    except Exception as e:
        conn.log.debug(f"get_current_price daily fallback failed: {e}")
    return None


def get_asian_range_live(conn: IBKRConnection, cfg: Config) -> dict:
    """Fetch Asian range from IBKR historical bars."""
    if not conn.ensure_connected():
        conn.log.error("Not connected -- cannot fetch Asian range")
        return {}
    from ib_insync import util

    now_utc = datetime.now(tz=timezone.utc)
    try:
        bars = conn.ib.reqHistoricalData(
            conn.contract, endDateTime="",
            durationStr="1 D", barSizeSetting="5 mins",
            whatToShow="MIDPOINT", useRTH=False, formatDate=2,
        )
    except Exception as e:
        conn.log.error(f"Historical data request failed: {e}")
        return {}

    if not bars:
        conn.log.error("No historical bars received")
        return {}

    df = util.df(bars)
    df['date_col'] = pd.to_datetime(df['date'])
    if df['date_col'].dt.tz is None:
        df['date_col'] = df['date_col'].dt.tz_localize('UTC')

    today = now_utc.date()
    df['bar_date'] = df['date_col'].dt.date
    df['bar_hour'] = df['date_col'].dt.hour

    asian = df[(df['bar_date'] == today)
               & (df['bar_hour'] >= cfg.strategy.asian_start_hour)
               & (df['bar_hour'] < cfg.strategy.asian_end_hour)]

    if len(asian) < 3:
        conn.log.warning(f"Only {len(asian)} Asian bars (need >=3)")
        return {}

    range_high = asian['high'].max()
    range_low = asian['low'].min()
    range_size = range_high - range_low
    if range_size <= 0:
        return {}

    conn.log.info(f"Asian range: {range_low:.2f} - {range_high:.2f} "
                  f"(size: {range_size:.2f}, {len(asian)} bars)")
    return {
        'range_high': range_high,
        'range_low': range_low,
        'range_size': range_size,
        'n_bars': len(asian),
    }


# ── Order placement ──────────────────────────────────────────────────────────

def place_bracket_orders(conn: IBKRConnection, state: ORBState,
                         cfg: Config, qty: int, dry_run: bool):
    from ib_insync import Order

    rh = state.range_high
    rl = state.range_low
    rs = state.range_size
    rr = cfg.strategy.rr_ratio

    long_entry = round(rh, 2)
    long_sl = round(rl, 2)
    long_tp = round(rh + rr * rs, 2)

    short_entry = round(rl, 2)
    short_sl = round(rh, 2)
    short_tp = round(rl - rr * rs, 2)

    conn.log.info(f"{'[DRY RUN] ' if dry_run else ''}"
                  f"Placing bracket orders (RR={rr}):")
    conn.log.info(f"  LONG:  entry={long_entry}, SL={long_sl}, TP={long_tp}")
    conn.log.info(f"  SHORT: entry={short_entry}, SL={short_sl}, TP={short_tp}")
    conn.log.info(f"  Qty: {qty} oz, Risk/oz: ${rs:.2f}")

    if dry_run:
        state.status = ORBState.ORDERS_PLACED
        state.save()
        return

    if not conn.ensure_connected():
        conn.log.error("Not connected -- cannot place orders")
        return

    oca_group = f"XAUUSD_ORB_{state.trade_date}"

    # GTD = auto-cancel at trade window close (failsafe if script crashes)
    trade_end_utc = datetime.now(tz=timezone.utc).replace(
        hour=cfg.strategy.trade_end_hour, minute=0, second=0, microsecond=0)
    gtd_time = trade_end_utc.strftime("%Y%m%d %H:%M:%S %Z")
    conn.log.info(f"  GTD expiry: {gtd_time}")

    # Buy stop bracket
    buy_parent = Order(action="BUY", orderType="STP", totalQuantity=qty,
                       auxPrice=long_entry, tif="GTD",
                       goodTillDate=gtd_time,
                       ocaGroup=oca_group, ocaType=1, transmit=False)
    buy_sl = Order(action="SELL", orderType="STP", totalQuantity=qty,
                   auxPrice=long_sl, tif="GTC", transmit=False)
    buy_tp = Order(action="SELL", orderType="LMT", totalQuantity=qty,
                   lmtPrice=long_tp, tif="GTC", transmit=False)

    # Sell stop bracket
    sell_parent = Order(action="SELL", orderType="STP", totalQuantity=qty,
                        auxPrice=short_entry, tif="GTD",
                        goodTillDate=gtd_time,
                        ocaGroup=oca_group, ocaType=1, transmit=False)
    sell_sl = Order(action="BUY", orderType="STP", totalQuantity=qty,
                    auxPrice=short_sl, tif="GTC", transmit=False)
    sell_tp = Order(action="BUY", orderType="LMT", totalQuantity=qty,
                    lmtPrice=short_tp, tif="GTC", transmit=True)

    try:
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

        conn.log.info(f"Buy bracket placed: orderId={buy_parent_id}")

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

        conn.log.info(f"Sell bracket placed: orderId={sell_parent_id}")

        state.buy_order_id = buy_parent_id
        state.sell_order_id = sell_parent_id
        state.status = ORBState.ORDERS_PLACED
        state.save()

    except Exception as e:
        conn.log.error(f"Order placement failed: {e}")
        raise


# ── Fill / exit checks ───────────────────────────────────────────────────────

def check_fills(conn: IBKRConnection, state: ORBState,
                cfg: Config, dry_run: bool) -> bool:
    if dry_run:
        return False
    if not conn.ensure_connected():
        return False
    rr = cfg.strategy.rr_ratio
    try:
        conn.sleep(0)
        for trade in conn.ib.trades():
            oid = trade.order.orderId
            if oid == state.buy_order_id and trade.orderStatus.status == 'Filled':
                fill = trade.orderStatus.avgFillPrice
                conn.log.info(f"BUY filled at {fill}")
                state.direction = "LONG"
                state.entry_price = fill
                state.sl_price = state.range_low
                state.tp_price = round(state.range_high + rr * state.range_size, 2)
                state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                state.status = ORBState.IN_TRADE
                state.save()
                return True
            elif oid == state.sell_order_id and trade.orderStatus.status == 'Filled':
                fill = trade.orderStatus.avgFillPrice
                conn.log.info(f"SELL filled at {fill}")
                state.direction = "SHORT"
                state.entry_price = fill
                state.sl_price = state.range_high
                state.tp_price = round(state.range_low - rr * state.range_size, 2)
                state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                state.status = ORBState.IN_TRADE
                state.save()
                return True
    except Exception as e:
        conn.log.warning(f"check_fills error: {e}")
    return False


def check_trade_exit(conn: IBKRConnection, state: ORBState,
                     dry_run: bool) -> bool:
    if dry_run:
        return False
    if not conn.ensure_connected():
        return False
    try:
        conn.sleep(0)
        positions = conn.ib.positions()
        has_position = any(
            p.contract.symbol == conn.cfg.ibkr.symbol and abs(p.position) > 0
            for p in positions
        )
        if not has_position:
            conn.log.info("Position closed (SL or TP filled)")
            return True
    except Exception as e:
        conn.log.warning(f"check_trade_exit error: {e}")
    return False


def cancel_all_and_close(conn: IBKRConnection, state: ORBState,
                         qty: int, dry_run: bool):
    if dry_run:
        conn.log.info("[DRY RUN] Would cancel all orders and close position")
        return
    if not conn.ensure_connected():
        conn.log.error("Cannot cancel/close -- not connected")
        return
    try:
        open_orders = conn.ib.openOrders()
        for order in open_orders:
            try:
                conn.ib.cancelOrder(order)
                conn.sleep(0.5)
            except Exception as e:
                conn.log.warning(f"Cancel failed: {e}")
        conn.sleep(2)

        positions = conn.ib.positions()
        for pos in positions:
            if (pos.contract.symbol == conn.cfg.ibkr.symbol
                    and abs(pos.position) > 0):
                close_action = "SELL" if pos.position > 0 else "BUY"
                close_qty = abs(pos.position)
                from ib_insync import MarketOrder
                close_order = MarketOrder(close_action, close_qty)
                trade = conn.ib.placeOrder(conn.contract, close_order)
                conn.sleep(3)
                fill = trade.orderStatus.avgFillPrice or 0
                conn.log.info(f"Closed: {close_action} {close_qty} at {fill}")
    except Exception as e:
        conn.log.error(f"cancel_all_and_close failed: {e}")


# ── Breakeven Stop Helper ────────────────────────────────────────────────────

def apply_breakeven_stop(conn: IBKRConnection, state: ORBState,
                         dry_run: bool, log: logging.Logger,
                         be_offset: float = 2.0):
    """Move the active SL order to entry + offset after be_hours elapsed.

    For live trading, scans open orders for the SL child order
    (SELL STP for LONG, BUY STP for SHORT) and modifies its auxPrice
    to state.entry_price + be_offset (LONG) or - be_offset (SHORT).
    For dry-run, only updates state.sl_price.
    """
    if state.direction == "LONG":
        new_sl = state.entry_price + be_offset
    else:
        new_sl = state.entry_price - be_offset

    if dry_run:
        log.info(f"[DRY RUN] BE rule: SL moved to {new_sl:.2f} "
                 f"(entry {state.entry_price:.2f} + offset {be_offset}) "
                 f"(was {state.sl_price:.2f})")
        state.sl_price = new_sl
        state.be_applied = True
        state.save()
        return

    if not conn.ensure_connected():
        log.warning("BE rule: not connected -- will retry next poll")
        return

    sl_action = "SELL" if state.direction == "LONG" else "BUY"
    try:
        for order in conn.ib.openOrders():
            if order.action == sl_action and order.orderType == "STP":
                old_sl = order.auxPrice
                order.auxPrice = new_sl
                conn.ib.placeOrder(conn.contract, order)  # modify in-place
                conn.sleep(0.5)
                state.sl_price = new_sl
                state.be_applied = True
                state.save()
                log.info(f"BE rule triggered: SL moved "
                         f"{old_sl:.2f} -> {new_sl:.2f} "
                         f"(entry {state.entry_price:.2f} + offset {be_offset})")
                return
        log.warning("1h BE rule: SL order not found in open orders")
    except Exception as e:
        log.error(f"apply_breakeven_stop failed: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_loop(conn: IBKRConnection, state: ORBState,
             cfg: Config, qty: int, dry_run: bool):
    log = conn.log
    strat = cfg.strategy
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    if state.trade_date != today_str:
        log.info(f"New trading day: {today_str}")
        state.reset_for_new_day(today_str)

    now = datetime.now(tz=timezone.utc)

    # Skip weekends
    if now.weekday() >= 5:
        log.info("Weekend -- no trading")
        return

    # Skip configured weekdays
    if now.weekday() in strat.skip_weekdays:
        day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][now.weekday()]
        log.info(f"{day_name} is in skip_weekdays -- no trading today")
        return

    # Guard: if the trade window is already closed, skip today
    if now.hour >= strat.trade_end_hour and state.status in (
            ORBState.IDLE, ORBState.RANGE_COMPUTED):
        log.info(f"Trade window already closed (UTC hour={now.hour} >= "
                 f"{strat.trade_end_hour}). Skipping today.")
        state.status = ORBState.DONE_TODAY
        state.save()
        return

    log.info(f"Starting ORB loop | state={state.status} | "
             f"date={state.trade_date} | qty={qty} oz | dry_run={dry_run}")

    _last_heartbeat: float = 0.0   # epoch seconds of last status log

    while True:
        now = datetime.now(tz=timezone.utc)
        hour = now.hour

        if not conn.ensure_connected():
            log.warning("Connection unavailable -- sleeping 30s")
            time.sleep(30)
            continue

        try:
            # ── Periodic status heartbeat (every 60 s) ──
            _now_ts = now.timestamp()
            if _now_ts - _last_heartbeat >= 60:
                _last_heartbeat = _now_ts
                _price = get_current_price(conn)
                _price_str = f"{_price:.2f}" if _price else "n/a"

                if state.status == ORBState.IDLE:
                    # Time until Asian range closes (06:00 UTC) and gets computed
                    _range_close = now.replace(
                        hour=strat.asian_end_hour, minute=0,
                        second=0, microsecond=0)
                    if now.hour < strat.asian_start_hour:
                        _secs = int((_range_close - now).total_seconds())
                        _eta = f"Asian range closes in {_secs//3600}h {(_secs%3600)//60}m"
                    elif now.hour < strat.asian_end_hour:
                        _secs = int((_range_close - now).total_seconds())
                        _eta = (f"collecting Asian range | "
                                f"closes in {_secs//3600}h {(_secs%3600)//60}m")
                    else:
                        _eta = "Asian range ready -- computing"
                    log.info(f"[STATUS] IDLE | price={_price_str} | {_eta}")

                elif state.status == ORBState.RANGE_COMPUTED:
                    _trade_open = now.replace(
                        hour=strat.trade_start_hour, minute=0,
                        second=0, microsecond=0)
                    if now >= _trade_open:
                        _eta = "trade window open"
                    else:
                        _secs = int((_trade_open - now).total_seconds())
                        _eta = f"trade opens in {_secs//3600}h {(_secs%3600)//60}m"
                    log.info(f"[STATUS] RANGE H={state.range_high:.2f} "
                             f"L={state.range_low:.2f} | "
                             f"price={_price_str} | {_eta}")

                elif state.status == ORBState.ORDERS_PLACED:
                    _trade_close = now.replace(
                        hour=strat.trade_end_hour, minute=0,
                        second=0, microsecond=0)
                    _secs_left = max(0, int(
                        (_trade_close - now).total_seconds()))
                    log.info(f"[STATUS] WATCHING | price={_price_str} | "
                             f"range H={state.range_high:.2f} "
                             f"L={state.range_low:.2f} | "
                             f"window closes in "
                             f"{_secs_left//3600}h {(_secs_left%3600)//60}m")

                elif state.status == ORBState.IN_TRADE and _price:
                    _unreal = ((_price - state.entry_price)
                               if state.direction == "LONG"
                               else (state.entry_price - _price))
                    _hold_m = (int((now - datetime.fromisoformat(
                                   state.entry_time)).total_seconds() / 60)
                               if state.entry_time else 0)
                    _be_in = ""
                    if not state.be_applied and state.entry_time:
                        _elapsed = (now - datetime.fromisoformat(
                            state.entry_time)).total_seconds()
                        _be_secs = max(0, strat.be_hours * 3600 - int(_elapsed))
                        _be_in = (f" | BE in {_be_secs//60}m"
                                  if _be_secs > 0 else " | BE applied")
                    else:
                        _be_in = " | BE applied" if state.be_applied else ""
                    log.info(f"[STATUS] {state.direction} | "
                             f"price={_price_str} | "
                             f"entry={state.entry_price:.2f} "
                             f"SL={state.sl_price:.2f} "
                             f"TP={state.tp_price:.2f} | "
                             f"PnL/oz=${_unreal:+.2f} "
                             f"(${_unreal * qty:+.2f} total) | "
                             f"held {_hold_m}m{_be_in}")

            # ── IDLE: wait for Asian range ──
            if state.status == ORBState.IDLE:
                if hour >= strat.asian_end_hour:
                    log.info("Computing Asian range from IBKR data...")
                    rng = get_asian_range_live(conn, cfg)
                    if rng:
                        state.range_high = rng['range_high']
                        state.range_low = rng['range_low']
                        state.range_size = rng['range_size']
                        state.status = ORBState.RANGE_COMPUTED
                        state.save()

                        rng_pct = state.range_size / state.range_high * 100
                        if rng_pct < strat.min_range_pct:
                            log.warning(f"Range too tight ({rng_pct:.3f}%). "
                                        f"Skipping.")
                            state.status = ORBState.DONE_TODAY
                            state.save()
                        elif rng_pct > strat.max_range_pct:
                            log.warning(f"Range too wide ({rng_pct:.2f}%). "
                                        f"Skipping.")
                            state.status = ORBState.DONE_TODAY
                            state.save()
                    else:
                        log.warning("Could not compute Asian range. Retrying...")
                        conn.sleep(60)
                        continue

            # ── RANGE_COMPUTED: place orders ──
            elif state.status == ORBState.RANGE_COMPUTED:
                if hour >= strat.trade_start_hour:
                    current_price = get_current_price(conn)
                    if current_price is not None:
                        if current_price > state.range_high:
                            relation = "ABOVE range_high"
                        elif current_price < state.range_low:
                            relation = "BELOW range_low"
                        else:
                            relation = "INSIDE Asian range"
                        log.info(
                            f"Pre-placement check | price={current_price:.2f} | "
                            f"range_low={state.range_low:.2f} | "
                            f"range_high={state.range_high:.2f} | {relation}"
                        )
                    else:
                        log.info(
                            f"Pre-placement check | price=n/a | "
                            f"range_low={state.range_low:.2f} | "
                            f"range_high={state.range_high:.2f}"
                        )
                    log.info("Trade window open -- placing bracket orders")
                    place_bracket_orders(conn, state, cfg, qty, dry_run)

            # ── ORDERS_PLACED: monitor fills ──
            elif state.status == ORBState.ORDERS_PLACED:
                if hour >= strat.trade_end_hour:
                    log.info("Trade window closed. Cancelling.")
                    cancel_all_and_close(conn, state, qty, dry_run)
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    log.info("No fill today. Done.")
                    break

                filled = check_fills(conn, state, cfg, dry_run)
                if filled:
                    log.info(f"Entered {state.direction} at "
                             f"{state.entry_price:.2f}")
                    log.info(f"SL={state.sl_price:.2f}, "
                             f"TP={state.tp_price:.2f}")

                # Dry-run simulation
                if dry_run and not filled:
                    price = get_current_price(conn)
                    if price:
                        rr = strat.rr_ratio
                        if price > state.range_high:
                            log.info(f"[DRY RUN] Price {price:.2f} > high "
                                     f"{state.range_high:.2f} -> LONG")
                            state.direction = "LONG"
                            state.entry_price = state.range_high
                            state.sl_price = state.range_low
                            state.tp_price = round(
                                state.range_high + rr * state.range_size, 2)
                            state.entry_time = now.isoformat()
                            state.status = ORBState.IN_TRADE
                            state.save()
                        elif price < state.range_low:
                            log.info(f"[DRY RUN] Price {price:.2f} < low "
                                     f"{state.range_low:.2f} -> SHORT")
                            state.direction = "SHORT"
                            state.entry_price = state.range_low
                            state.sl_price = state.range_high
                            state.tp_price = round(
                                state.range_low - rr * state.range_size, 2)
                            state.entry_time = now.isoformat()
                            state.status = ORBState.IN_TRADE
                            state.save()

            # ── IN_TRADE: monitor SL/TP ──
            elif state.status == ORBState.IN_TRADE:
                if hour >= strat.trade_end_hour:
                    log.info("Trade window closed while in position. "
                             "Closing at market.")
                    cancel_all_and_close(conn, state, qty, dry_run)

                    price = get_current_price(conn) or state.entry_price
                    pnl = ((price - state.entry_price)
                           if state.direction == "LONG"
                           else (state.entry_price - price))
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
                        'pnl_per_oz': round(pnl, 2),
                        'pnl_total': round(pnl * qty, 2),
                        'result': 'TIME',
                        'hold_minutes': (
                            int((now - datetime.fromisoformat(
                                state.entry_time)).total_seconds() / 60)
                            if state.entry_time else 0),
                    }, cfg.paths.trade_log)
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    break

                done = check_trade_exit(conn, state, dry_run)

                # ── Breakeven stop rule ──
                if not done and not state.be_applied and state.entry_time:
                    elapsed_secs = (
                        now - datetime.fromisoformat(state.entry_time)
                    ).total_seconds()
                    if elapsed_secs >= strat.be_hours * 3600:
                        apply_breakeven_stop(conn, state, dry_run, log,
                                             be_offset=strat.be_offset_usd)

                if dry_run:
                    price = get_current_price(conn)
                    if price:
                        if state.direction == "LONG":
                            if price <= state.sl_price:
                                log.info(f"[DRY RUN] SL hit at "
                                         f"{state.sl_price:.2f}")
                                done = True
                                result = 'SL'
                                exit_price = state.sl_price
                            elif price >= state.tp_price:
                                log.info(f"[DRY RUN] TP hit at "
                                         f"{state.tp_price:.2f}")
                                done = True
                                result = 'TP'
                                exit_price = state.tp_price
                        else:
                            if price >= state.sl_price:
                                log.info(f"[DRY RUN] SL hit at "
                                         f"{state.sl_price:.2f}")
                                done = True
                                result = 'SL'
                                exit_price = state.sl_price
                            elif price <= state.tp_price:
                                log.info(f"[DRY RUN] TP hit at "
                                         f"{state.tp_price:.2f}")
                                done = True
                                result = 'TP'
                                exit_price = state.tp_price

                        if not done:
                            unrealized = (
                                (price - state.entry_price)
                                if state.direction == "LONG"
                                else (state.entry_price - price))
                            log.debug(f"In {state.direction} | "
                                      f"price={price:.2f} | "
                                      f"PnL/oz=${unrealized:+.2f}")

                if done:
                    if not dry_run:
                        price = get_current_price(conn) or state.entry_price
                        pnl = ((price - state.entry_price)
                               if state.direction == "LONG"
                               else (state.entry_price - price))
                        result = 'TP' if pnl > 0 else 'SL'
                        exit_price = price
                    else:
                        if 'exit_price' not in dir():
                            exit_price = state.entry_price
                            result = 'UNKNOWN'
                        pnl = ((exit_price - state.entry_price)
                               if state.direction == "LONG"
                               else (state.entry_price - exit_price))

                    log.info(f"Trade closed: {state.direction} {result} | "
                             f"Entry={state.entry_price:.2f} "
                             f"Exit={exit_price:.2f} | "
                             f"PnL/oz=${pnl:+.2f} | "
                             f"Total=${pnl * qty:+.2f}")

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
                        'pnl_per_oz': round(pnl, 2),
                        'pnl_total': round(pnl * qty, 2),
                        'result': result,
                        'hold_minutes': (
                            int((now - datetime.fromisoformat(
                                state.entry_time)).total_seconds() / 60)
                            if state.entry_time else 0),
                    }, cfg.paths.trade_log)
                    state.status = ORBState.DONE_TODAY
                    state.save()
                    break

            # ── DONE_TODAY ──
            elif state.status == ORBState.DONE_TODAY:
                log.info("Today's trading complete.")
                break

        except Exception as e:
            log.error(f"Error in loop: {e}", exc_info=True)
            time.sleep(30)
            continue

        conn.sleep(strat.poll_interval)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="XAUUSD Asian Range -> London Breakout (v5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log only, do not place orders")
    parser.add_argument("--qty", type=int, default=None,
                        help="Override position size in oz")
    parser.add_argument("--port", type=int, default=None,
                        help="Override IBKR port")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to alternative config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # CLI overrides
    if args.qty is not None:
        cfg.position.qty = args.qty
    if args.port is not None:
        cfg.ibkr.port = args.port

    qty = cfg.position.qty
    log = setup_logging(cfg)

    print("=" * 60)
    print("  XAUUSD Asian Range -> London Breakout  (v5)")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Qty:  {qty} oz")
    print(f"  RR:   {cfg.strategy.rr_ratio}")
    print(f"  Skip: {cfg.strategy.skip_weekdays}")
    print(f"  IBKR: {cfg.ibkr.host}:{cfg.ibkr.port} "
          f"(clientId={cfg.ibkr.client_id})")
    print(f"  Config: {args.config or 'config.yaml (default)'}")
    print("=" * 60)

    if not args.dry_run:
        print("\n  WARNING: LIVE MODE -- real orders will be placed!")
        print("  Press Ctrl+C to abort.\n")

    state = ORBState(cfg.paths.state_dir)
    conn = IBKRConnection(cfg, log)

    if not conn.connect():
        log.error("Could not connect to IBKR after retries")
        log.info("Make sure IB Gateway is running and logged in")
        sys.exit(1)

    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        if not args.dry_run:
            cancel_all_and_close(conn, state, qty, args.dry_run)
        conn.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            run_loop(conn, state, cfg, qty, args.dry_run)

            # Sleep until next UTC midnight + 10 min buffer, then start
            # a new trading day automatically.
            now = datetime.now(tz=timezone.utc)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=10, second=0, microsecond=0)
            wait_sec = (next_midnight - now).total_seconds()
            log.info(f"Day complete. Sleeping {wait_sec/3600:.1f}h until "
                     f"{next_midnight.strftime('%Y-%m-%d %H:%M')} UTC")
            # Sleep in short chunks so Ctrl+C is responsive
            while wait_sec > 0:
                chunk = min(wait_sec, 60)
                time.sleep(chunk)
                wait_sec -= chunk

            # Reset state for the new day
            new_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            log.info(f"Waking up for new trading day: {new_day}")
            state.reset_for_new_day(new_day)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        if not args.dry_run:
            log.info("Cleaning up...")
            cancel_all_and_close(conn, state, qty, args.dry_run)
        conn.disconnect()
        log.info("Disconnected from IBKR")


if __name__ == "__main__":
    main()
