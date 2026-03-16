"""
orb_multi_live.py -- Multi-instrument Asian Range -> Session Breakout (v5)

Trades XAUUSD (London breakout) and EURUSD (NY breakout) simultaneously
from a single process, sharing one IBKR connection.

Each instrument has its own:
  - Session times (Asian range window, trade window)
  - State machine (persisted to separate JSON files)
  - Contract, qty, BE offset, RR ratio
  - Trade log

Architecture:
  1 IBKRConnection (shared)
  N InstrumentManager (one per enabled instrument in config.yaml)
  1 main loop polling all managers each cycle

Usage:
  # Dry run (no orders):
  python -m v5_xauusd_orb.orb_multi_live --dry-run

  # Live paper trading:
  python -m v5_xauusd_orb.orb_multi_live

  # Only trade EURUSD:
  python -m v5_xauusd_orb.orb_multi_live --only EURUSD

  # Override port:
  python -m v5_xauusd_orb.orb_multi_live --port 4001
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import signal as signal_mod
import sys
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

import pandas as pd

from v5_xauusd_orb.config import load_config, Config, InstrumentConfig, ROOT
from v5_xauusd_orb.guardrails import Guardrails, graceful_shutdown


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(cfg: Config) -> logging.Logger:
    log = logging.getLogger("orb_multi")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    log.addHandler(sh)

    log_path = Path(cfg.paths.log_dir) / "orb_multi_live.log"
    fh = RotatingFileHandler(
        str(log_path), maxBytes=10_000_000, backupCount=5)
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)

    for _lib in ("ib_insync.wrapper", "ib_insync.client", "ib_insync"):
        logging.getLogger(_lib).setLevel(logging.CRITICAL)

    return log


# ── Trade CSV logger ──────────────────────────────────────────────────────────

TRADE_FIELDS = [
    'timestamp', 'date', 'instrument', 'direction', 'entry', 'exit',
    'sl', 'tp', 'range_high', 'range_low', 'range_size', 'qty',
    'pnl_per_unit', 'pnl_total', 'result', 'hold_minutes',
    'mfe', 'mae', 'account_mode',
]


def log_trade(trade: dict, trade_log_path: str):
    path = Path(trade_log_path)
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(trade)


# ── Velocity CSV logger ─────────────────────────────────────────────────────

VELOCITY_FIELDS = [
    'timestamp', 'date', 'instrument', 'hour', 'minute',
    'ticks_1min', 'ticks_2min', 'ticks_3min', 'ticks_4min', 'ticks_5min',
    'avg_4min', 'threshold', 'price', 'state',
]

# Log velocity from 06:00 to 10:00 UTC (covers pre-range-close through post-entry)
VELOCITY_LOG_START_HOUR = 6
VELOCITY_LOG_END_HOUR = 10


def log_velocity(row: dict, log_dir: str, inst_name: str):
    """Append one velocity sample to the instrument's velocity CSV."""
    path = Path(log_dir) / f"velocity_{inst_name.lower()}.csv"
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=VELOCITY_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# ── Per-instrument State ──────────────────────────────────────────────────────

class InstrumentState:
    """Persisted state for one instrument. Crash-recoverable."""

    IDLE = "IDLE"
    RANGE_COMPUTED = "RANGE_COMPUTED"
    ORDERS_PLACED = "ORDERS_PLACED"
    IN_TRADE = "IN_TRADE"
    DONE_TODAY = "DONE_TODAY"

    def __init__(self, state_dir: str, inst_name: str):
        self.state_file = Path(state_dir) / f"orb_{inst_name.lower()}_state.json"
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
        self.orders_placed_time: Optional[str] = None
        self.mfe: float = 0
        self.mae: float = 0
        self.buy_sl_order_id: int = 0
        self.buy_tp_order_id: int = 0
        self.sell_sl_order_id: int = 0
        self.sell_tp_order_id: int = 0
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
            'orders_placed_time': self.orders_placed_time,
            'mfe': self.mfe,
            'mae': self.mae,
            'buy_sl_order_id': self.buy_sl_order_id,
            'buy_tp_order_id': self.buy_tp_order_id,
            'sell_sl_order_id': self.sell_sl_order_id,
            'sell_tp_order_id': self.sell_tp_order_id,
        }
        # Atomic write: write to temp file then rename to prevent
        # corruption if the process crashes mid-write.
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.state_file)

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
        self.orders_placed_time = None
        self.mfe = 0
        self.mae = 0
        self.buy_sl_order_id = 0
        self.buy_tp_order_id = 0
        self.sell_sl_order_id = 0
        self.sell_tp_order_id = 0
        self.save()


# ── IBKR Connection (shared across instruments) ──────────────────────────────

_IB_CRITICAL_ERRORS = {
    504: "Not connected",
    502: "Couldn't connect to TWS",
    1100: "Connectivity between IBKR and TWS lost",
    2110: "Connectivity between TWS and server is broken",
    10182: "Failed to request live updates (disconnected)",
}
_IB_WARNING_CODES = {
    2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158,
    2119, 354, 300, 10168, 10167,
}


class SharedConnection:
    """Single IBKR connection shared by all instruments."""

    def __init__(self, cfg: Config, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self.host = cfg.ibkr.host
        self.port = cfg.ibkr.port
        self.client_id = cfg.ibkr.client_id
        self.ib = None
        self._connected = False
        self._disconnect_count = 0
        self._last_heartbeat = 0.0
        self._shutting_down = False
        # Per-instrument contracts and tickers
        self.contracts = {}       # inst_name -> Contract
        self.price_tickers = {}   # inst_name -> Ticker
        # Tick counter for velocity filter: inst_name -> deque of tick timestamps
        self._tick_timestamps = {}   # inst_name -> deque of float (unix timestamps)
        self._tick_subscriptions = {}  # inst_name -> subscription object
        self._tick_last_bid = {}     # inst_name -> last bid price (for change detection)
        self._tick_last_ask = {}     # inst_name -> last ask price (for change detection)
        self._velocity_handler_registered = False

    @property
    def connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()

    def connect(self) -> bool:
        from ib_insync import IB
        ic = self.cfg.ibkr

        for attempt in range(1, ic.max_retries + 1):
            backoff = min(ic.base_backoff_sec * (2 ** (attempt - 1)),
                          ic.max_backoff_sec)
            try:
                if self.ib is not None:
                    try:
                        self.ib.disconnect()
                    except Exception:
                        pass

                self.ib = IB()
                self.ib.errorEvent += self._on_ib_error
                self.ib.disconnectedEvent += self._on_disconnect
                self._velocity_handler_registered = False  # re-register after new IB instance

                self.ib.connect(self.host, self.port,
                                clientId=self.client_id,
                                timeout=ic.connect_timeout_sec)

                if not self.ib.isConnected():
                    raise ConnectionError("connect returned but isConnected=False")

                self._connected = True
                self._last_heartbeat = time.time()
                self.log.info(f"Connected to IBKR at {self.host}:{self.port} "
                              f"(clientId={self.client_id})")
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
        ok = self.connect()
        if ok:
            # Re-qualify contracts and restart tickers after reconnect
            self._requalify_all()
        return ok

    def sleep(self, seconds: float):
        if self.connected:
            try:
                self.ib.sleep(seconds)
            except Exception:
                self._connected = False
                time.sleep(seconds)
        else:
            time.sleep(seconds)

    def disconnect(self):
        self._shutting_down = True
        for name in list(self.price_tickers):
            self._stop_price_ticker(name)
        for name in list(self._tick_subscriptions):
            self.stop_tick_counter(name)
        if self.ib is not None:
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self._connected = False

    def qualify_contract(self, inst: InstrumentConfig) -> bool:
        """Qualify and store an IB contract for one instrument."""
        from ib_insync import Contract, Forex
        try:
            if inst.sec_type == "CASH":
                contract = Forex(inst.symbol + inst.currency)
                qualified = self.ib.qualifyContracts(contract)
                if not qualified:
                    # Try Forex pair directly
                    contract = Forex(inst.symbol, exchange=inst.exchange,
                                     currency=inst.currency)
                    qualified = self.ib.qualifyContracts(contract)
            else:
                contract = Contract(
                    symbol=inst.symbol, secType=inst.sec_type,
                    exchange=inst.exchange, currency=inst.currency)
                qualified = self.ib.qualifyContracts(contract)

            if qualified:
                self.contracts[inst.name] = contract
                self.log.info(f"[{inst.name}] Contract qualified: {contract}")
                self._start_price_ticker(inst.name)
                return True
            else:
                self.log.error(f"[{inst.name}] Could not qualify contract "
                               f"({inst.symbol} {inst.sec_type})")
                return False

        except Exception as e:
            self.log.error(f"[{inst.name}] Contract qualification failed: {e}")
            return False

    def get_price(self, inst_name: str) -> Optional[float]:
        """Get current price for an instrument from streaming ticker or hist."""
        if not self.ensure_connected():
            return None

        # 1) Streaming ticker
        t = self.price_tickers.get(inst_name)
        if t is not None:
            bid, ask = t.bid, t.ask
            if (isinstance(bid, float) and not math.isnan(bid) and bid > 0
                    and isinstance(ask, float) and not math.isnan(ask) and ask > 0):
                dec = self.cfg.instruments[inst_name].price_decimals
                return round((bid + ask) / 2, dec)
            if isinstance(t.close, float) and not math.isnan(t.close) and t.close > 0:
                return t.close

        # 2) Historical fallback
        contract = self.contracts.get(inst_name)
        if contract is None:
            return None
        try:
            bars = self.ib.reqHistoricalData(
                contract, endDateTime="",
                durationStr="3600 S", barSizeSetting="5 mins",
                whatToShow="MIDPOINT", useRTH=False, formatDate=2)
            if bars:
                return bars[-1].close
        except Exception:
            pass
        return None

    def get_asian_range(self, inst_name: str, inst: InstrumentConfig) -> dict:
        """Fetch Asian range for an instrument from historical bars."""
        if not self.ensure_connected():
            return {}

        contract = self.contracts.get(inst_name)
        if contract is None:
            return {}

        try:
            bars = self.ib.reqHistoricalData(
                contract, endDateTime="",
                durationStr="1 D", barSizeSetting="5 mins",
                whatToShow="MIDPOINT", useRTH=False, formatDate=2)
        except Exception as e:
            self.log.error(f"[{inst_name}] Historical data request failed: {e}")
            return {}

        if not bars:
            self.log.error(f"[{inst_name}] No historical bars received")
            return {}

        from ib_insync import util
        df = util.df(bars)
        df['date_col'] = pd.to_datetime(df['date'])
        if df['date_col'].dt.tz is None:
            df['date_col'] = df['date_col'].dt.tz_localize('UTC')

        today = datetime.now(tz=timezone.utc).date()
        df['bar_date'] = df['date_col'].dt.date
        df['bar_hour'] = df['date_col'].dt.hour

        asian = df[(df['bar_date'] == today)
                   & (df['bar_hour'] >= inst.asian_start_hour)
                   & (df['bar_hour'] < inst.asian_end_hour)]

        if len(asian) < 3:
            self.log.warning(f"[{inst_name}] Only {len(asian)} Asian bars (need >=3)")
            return {}

        rh = asian['high'].max()
        rl = asian['low'].min()
        rs = rh - rl
        if rs <= 0:
            return {}

        dec = inst.price_decimals
        self.log.info(f"[{inst_name}] Asian range: {rl:.{dec}f} - {rh:.{dec}f} "
                      f"(size: {rs:.{dec}f}, {len(asian)} bars)")
        return {'range_high': rh, 'range_low': rl, 'range_size': rs}

    # ── private ───────────────────────────────────────────────────

    def _start_price_ticker(self, inst_name: str):
        contract = self.contracts.get(inst_name)
        if contract is None:
            return
        try:
            self.ib.reqMarketDataType(3)
            ticker = self.ib.reqMktData(contract, '', snapshot=False,
                                        regulatorySnapshot=False)
            self.ib.sleep(2)
            self.price_tickers[inst_name] = ticker
            bid = ticker.bid
            if isinstance(bid, float) and not math.isnan(bid) and bid > 0:
                self.log.info(f"[{inst_name}] Price ticker started "
                              f"bid={bid} ask={ticker.ask}")
            else:
                self.log.warning(f"[{inst_name}] Price ticker started "
                                 f"but no data yet")
        except Exception as e:
            self.log.warning(f"[{inst_name}] Failed to start price ticker: {e}")

    def _stop_price_ticker(self, inst_name: str):
        ticker = self.price_tickers.pop(inst_name, None)
        if ticker is not None and self.ib is not None:
            try:
                self.ib.cancelMktData(ticker.contract)
            except Exception:
                pass

    def start_tick_counter(self, inst_name: str):
        """Enable velocity tick counting for an instrument.

        Uses the existing reqMktData price ticker + pendingTickersEvent
        to count bid/ask changes. Works for ALL instruments including
        XAUUSD CMDTY (reqTickByTickData is NOT supported for CMDTY).
        """
        contract = self.contracts.get(inst_name)
        if contract is None:
            return
        # Keep last 15 minutes of tick timestamps (generous buffer)
        self._tick_timestamps[inst_name] = deque(maxlen=100000)
        self._tick_last_bid[inst_name] = None
        self._tick_last_ask[inst_name] = None
        self._tick_subscriptions[inst_name] = True  # mark as active

        # Register ONE global handler for all instruments (idempotent)
        if not self._velocity_handler_registered:
            self.ib.pendingTickersEvent += self._on_velocity_tick
            self._velocity_handler_registered = True

        self.log.info(f"[{inst_name}] Tick counter started (reqMktData velocity)")

    def _on_velocity_tick(self, tickers):
        """Global pendingTickersEvent handler for velocity tick counting.

        Fires on every market data update from reqMktData. We check which
        instruments had bid/ask changes and record timestamps.
        """
        for ticker in tickers:
            if ticker.contract is None:
                continue
            # Match by conId against our known contracts
            for inst_name, contract in self.contracts.items():
                if (inst_name not in self._tick_subscriptions
                        or contract.conId != ticker.contract.conId):
                    continue
                bid = ticker.bid
                ask = ticker.ask
                # Skip invalid prices
                if (not isinstance(bid, (int, float)) or not isinstance(ask, (int, float))
                        or math.isnan(bid) or math.isnan(ask)
                        or bid <= 0 or ask <= 0):
                    continue
                # Only count if bid or ask actually changed
                if (bid != self._tick_last_bid.get(inst_name)
                        or ask != self._tick_last_ask.get(inst_name)):
                    self._tick_last_bid[inst_name] = bid
                    self._tick_last_ask[inst_name] = ask
                    ts_deque = self._tick_timestamps.get(inst_name)
                    if ts_deque is not None:
                        ts_deque.append(time.time())
                break  # found the matching instrument

    def stop_tick_counter(self, inst_name: str):
        """Stop velocity counting for an instrument."""
        self._tick_subscriptions.pop(inst_name, None)
        self._tick_timestamps.pop(inst_name, None)
        self._tick_last_bid.pop(inst_name, None)
        self._tick_last_ask.pop(inst_name, None)

    def get_tick_velocity(self, inst_name: str, lookback_minutes: int = 3) -> float:
        """Get average ticks per minute over the last N+1 minutes (entry bar + lookback).
        Returns 0 if no tick data available."""
        ts_deque = self._tick_timestamps.get(inst_name)
        if ts_deque is None or len(ts_deque) == 0:
            return 0.0
        now = time.time()
        window_sec = (lookback_minutes + 1) * 60  # +1 for the current/entry bar
        cutoff = now - window_sec
        # Count ticks in window
        count = sum(1 for ts in ts_deque if ts >= cutoff)
        minutes = window_sec / 60
        return count / minutes if minutes > 0 else 0.0

    def get_tick_counts_per_minute(self, inst_name: str, minutes: int = 5) -> list[int]:
        """Get tick counts for each of the last N completed minutes.
        Returns list of N ints, oldest first. Useful for detailed logging."""
        ts_deque = self._tick_timestamps.get(inst_name)
        if ts_deque is None or len(ts_deque) == 0:
            return [0] * minutes
        now = time.time()
        counts = []
        for m in range(minutes, 0, -1):
            lo = now - m * 60
            hi = now - (m - 1) * 60
            counts.append(sum(1 for ts in ts_deque if lo <= ts < hi))
        return counts

    def _requalify_all(self):
        """Re-qualify all contracts after reconnect."""
        for inst_name in list(self.contracts.keys()):
            inst = self.cfg.instruments.get(inst_name)
            if inst:
                self.qualify_contract(inst)
                # Restart tick counter if velocity filter is enabled
                if inst.velocity_filter_enabled:
                    self.start_tick_counter(inst_name)

    def _on_disconnect(self):
        self._connected = False
        self._disconnect_count += 1
        self.log.warning(f"IBKR disconnected (#{self._disconnect_count})")

    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        if errorCode in _IB_WARNING_CODES:
            self.log.debug(f"IB warning {errorCode}: {errorString}")
            return
        if errorCode in _IB_CRITICAL_ERRORS:
            self._connected = False
            self.log.error(f"IB critical error {errorCode}: "
                           f"{_IB_CRITICAL_ERRORS[errorCode]} - {errorString}")
        else:
            if errorCode not in (162,):
                self.log.warning(f"IB error {errorCode} (reqId={reqId}): "
                                 f"{errorString}")


# ── Instrument Manager ────────────────────────────────────────────────────────

class InstrumentManager:
    """Manages one instrument's ORB lifecycle within the shared connection."""

    def __init__(self, inst: InstrumentConfig, conn: SharedConnection,
                 state_dir: str, log: logging.Logger, dry_run: bool,
                 guardrails: Guardrails = None, account_mode: str = 'paper'):
        self.inst = inst
        self.conn = conn
        self.log = log
        self.dry_run = dry_run
        self.guardrails = guardrails
        self.account_mode = account_mode
        self.state = InstrumentState(state_dir, inst.name)
        self.tag = f"[{inst.name}]"
        self.dec = inst.price_decimals
        # Trade log path: per-instrument
        log_dir = Path(state_dir).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = str(log_dir)
        self.trade_log = str(log_dir / f"orb_{inst.name.lower()}_trades.csv")

    def verify_orders_on_startup(self):
        """Check if saved ORDERS_PLACED orders still exist at IBKR.
        If they were cancelled (e.g. by a previous shutdown), reset state
        to RANGE_COMPUTED so brackets get re-placed."""
        state = self.state
        if state.status != InstrumentState.ORDERS_PLACED:
            return
        if self.dry_run:
            return

        saved_ids = set()
        if state.buy_order_id:
            saved_ids.add(state.buy_order_id)
        if state.sell_order_id:
            saved_ids.add(state.sell_order_id)
        if not saved_ids:
            return

        # Query IBKR for open orders
        try:
            self.conn.ib.reqAllOpenOrders()
            self.conn.sleep(2)
            live_ids = {t.order.orderId for t in self.conn.ib.openTrades()}
            found = saved_ids & live_ids
            if not found:
                self.log.warning(
                    f"{self.tag} Saved orders {saved_ids} not found at IBKR "
                    f"-- resetting to RANGE_COMPUTED to re-place")
                state.buy_order_id = 0
                state.sell_order_id = 0
                state.orders_placed_time = None
                state.status = InstrumentState.RANGE_COMPUTED
                state.save()
            else:
                self.log.info(
                    f"{self.tag} Verified orders {found} still active at IBKR")
        except Exception as e:
            self.log.error(f"{self.tag} Order verification failed: {e}")

    def tick(self, now: datetime):
        """One iteration of the state machine. Called every poll_interval."""
        hour = now.hour
        state = self.state
        inst = self.inst

        # ── IDLE: wait for Asian range to close ──
        if state.status == InstrumentState.IDLE:
            if hour >= inst.asian_end_hour:
                self.log.info(f"{self.tag} Computing Asian range...")
                rng = self.conn.get_asian_range(inst.name, inst)
                if rng:
                    state.range_high = rng['range_high']
                    state.range_low = rng['range_low']
                    state.range_size = rng['range_size']
                    state.status = InstrumentState.RANGE_COMPUTED
                    state.save()

                    mid = (state.range_high + state.range_low) / 2
                    rng_pct = state.range_size / mid * 100 if mid > 0 else 0
                    if rng_pct < inst.min_range_pct:
                        self.log.warning(
                            f"{self.tag} Range too tight ({rng_pct:.3f}%). Skip.")
                        state.status = InstrumentState.DONE_TODAY
                        state.save()
                    elif rng_pct > inst.max_range_pct:
                        self.log.warning(
                            f"{self.tag} Range too wide ({rng_pct:.2f}%). Skip.")
                        state.status = InstrumentState.DONE_TODAY
                        state.save()
                else:
                    self.log.debug(f"{self.tag} Could not compute range yet")

        # ── RANGE_COMPUTED: place bracket orders when trade window opens ──
        elif state.status == InstrumentState.RANGE_COMPUTED:
            if hour >= inst.trade_start_hour:
                # Guardrail: check daily loss limit + max positions
                if self.guardrails and not self.guardrails.can_trade(
                        self.conn, inst.name):
                    self.log.warning(
                        f"{self.tag} GUARDRAIL blocked order placement")
                    state.status = InstrumentState.DONE_TODAY
                    state.save()
                    return

                # Velocity gate: Option A (Pre-fill monitoring)
                # Only place orders if market is currently active enough
                if inst.velocity_filter_enabled:
                    vel_ok, vel_val = self._check_velocity()
                    if not vel_ok:
                        # Log periodically but not every tick
                        now_ts = now.timestamp()
                        if not hasattr(self, '_last_vel_log') or now_ts - self._last_vel_log >= 60:
                            self.log.info(
                                f"{self.tag} Waiting for velocity: "
                                f"{vel_val:.0f} < threshold {inst.velocity_threshold} "
                                f"ticks/min")
                            self._last_vel_log = now_ts
                        return

                self.log.info(
                    f"{self.tag} Trade window & velocity check PASSED: "
                    f"hour={hour} >= trade_start={inst.trade_start_hour}")
                self._log_pre_placement(now)
                self._place_bracket_orders(now)

        # ── ORDERS_PLACED: wait for fill or window close ──
        elif state.status == InstrumentState.ORDERS_PLACED:
            # ── CRITICAL: Check fills FIRST, before any cancel logic ──
            # If IBKR filled our entry between ticks, we must detect it
            # before any cancel path can miss it and orphan the position.
            filled = self._check_fills()

            if not filled and hour >= inst.trade_end_hour:
                self.log.info(f"{self.tag} Trade window closed. Cancelling.")
                self._cancel_and_close()
                state.status = InstrumentState.DONE_TODAY
                state.save()
                self.log.info(f"{self.tag} No fill today. Done.")
                return

            # Max pending hours: cancel if orders haven't filled in time
            if (not filled and inst.max_pending_hours > 0
                    and state.orders_placed_time):
                elapsed = (now - datetime.fromisoformat(
                    state.orders_placed_time)).total_seconds()
                if elapsed >= inst.max_pending_hours * 3600:
                    hrs = inst.max_pending_hours
                    self.log.warning(
                        f"{self.tag} Orders pending > {hrs}h -- cancelling "
                        f"(max_pending_hours={hrs})")
                    self._cancel_and_close()
                    state.status = InstrumentState.DONE_TODAY
                    state.save()
                    return

            # Dynamic Velocity Gate: if velocity drops while orders are resting, pull them
            # Use 90% of threshold (hysteresis) to avoid rapid place/cancel cycling
            # when velocity fluctuates around the exact threshold boundary.
            # NOTE: This block only runs if no fill was detected above.
            if not filled and inst.velocity_filter_enabled:
                vel_ok, vel_val = self._check_velocity()
                cancel_threshold = inst.velocity_threshold * 0.9
                if vel_val < cancel_threshold:
                    self.log.warning(
                        f"{self.tag} Velocity dropped ({vel_val:.0f} < {cancel_threshold:.0f} "
                        f"[90% of {inst.velocity_threshold}]). "
                        f"Pulling resting orders to wait for activity.")
                    self._cancel_and_close()
                    # Revert to RANGE_COMPUTED so we keep watching
                    # Reset orders_placed_time so max_pending_hours timer restarts on re-place
                    state.status = InstrumentState.RANGE_COMPUTED
                    state.buy_order_id = 0
                    state.sell_order_id = 0
                    state.orders_placed_time = None
                    state.save()
                    return
            if filled:
                # Post-fill safety check: catch race condition fills during velocity drop
                if inst.velocity_filter_enabled:
                    vel_ok, vel_val = self._check_velocity()
                    per_min = self.conn.get_tick_counts_per_minute(inst.name, 5)
                    per_min_str = ','.join(str(c) for c in per_min)
                    
                    if not vel_ok:
                        self.log.warning(
                            f"{self.tag} RACE CONDITION: Filled during velocity drop! "
                            f"{state.direction} at {state.entry_price:.{self.dec}f} | "
                            f"velocity={vel_val:.0f} < threshold {inst.velocity_threshold} | "
                            f"per_min=[{per_min_str}] | Closing immediately.")
                        self._log_velocity_at_fill(now, vel_val, per_min, 'FILL_REJECT_RACE')
                        self._velocity_reject_close(now)
                        return
                    
                    # Velocity OK, accept fill
                    self._log_velocity_at_fill(now, vel_val, per_min, 'FILL_OK')
                    self.log.info(
                        f"{self.tag} Entered {state.direction} at "
                        f"{state.entry_price:.{self.dec}f} | "
                        f"SL={state.sl_price:.{self.dec}f} "
                        f"TP={state.tp_price:.{self.dec}f} | "
                        f"velocity={vel_val:.0f}/{inst.velocity_threshold} "
                        f"ticks/min (OK) | per_min=[{per_min_str}]")
                else:
                    # No velocity filter, just log fill
                    self.log.info(
                        f"{self.tag} Entered {state.direction} at "
                        f"{state.entry_price:.{self.dec}f} | "
                        f"SL={state.sl_price:.{self.dec}f} "
                        f"TP={state.tp_price:.{self.dec}f}")

            # Dry-run fill simulation
            if self.dry_run and not filled:
                was_placed = state.status == InstrumentState.ORDERS_PLACED
                self._dry_run_fill_check(now)
                # If dry-run just filled, apply velocity gate (same as live)
                if was_placed and state.status == InstrumentState.IN_TRADE:
                    if inst.velocity_filter_enabled:
                        vel_ok, vel_val = self._check_velocity()
                        per_min = self.conn.get_tick_counts_per_minute(inst.name, 5)
                        per_min_str = ','.join(str(c) for c in per_min)
                        
                        if not vel_ok:
                            self.log.warning(
                                f"{self.tag} [DRY RUN] VELOCITY REJECT: "
                                f"{state.direction} at {state.entry_price:.{self.dec}f} | "
                                f"velocity={vel_val:.0f} < threshold {inst.velocity_threshold} | "
                                f"per_min=[{per_min_str}]")
                            self._log_velocity_at_fill(now, vel_val, per_min, 'DRY_REJECT')
                            self._velocity_reject_close(now)
                            return
                        
                        self._log_velocity_at_fill(now, vel_val, per_min, 'DRY_OK')
                        self.log.info(
                            f"{self.tag} [DRY RUN] velocity={vel_val:.0f}/"
                            f"{inst.velocity_threshold} ticks/min (OK) | "
                            f"per_min=[{per_min_str}]")
                    else:
                        self.log.info(f"{self.tag} [DRY RUN] Fill accepted (no velocity filter)")

        # ── IN_TRADE: monitor SL/TP/BE/EOD/TIME_EXIT ──
        elif state.status == InstrumentState.IN_TRADE:
            if hour >= inst.trade_end_hour:
                self.log.info(f"{self.tag} Window closed in position. "
                              f"Closing at market.")
                self._eod_close(now)
                return

            # Time-based exit: close at market after N minutes in trade
            if (inst.time_exit_minutes > 0 and state.entry_time):
                elapsed_min = (now - datetime.fromisoformat(
                    state.entry_time)).total_seconds() / 60
                if elapsed_min >= inst.time_exit_minutes:
                    self.log.info(
                        f"{self.tag} Time exit triggered: "
                        f"{elapsed_min:.0f}min >= {inst.time_exit_minutes}min. "
                        f"Closing at market.")
                    self._time_exit_close(now)
                    return

            done = self._check_exit()

            # Update MFE / MAE (best favorable / worst adverse excursion)
            price = self.conn.get_price(self.inst.name)
            if price is not None and state.entry_price:
                if state.direction == "LONG":
                    favor = price - state.entry_price
                    adverse = state.entry_price - price
                else:
                    favor = state.entry_price - price
                    adverse = price - state.entry_price
                if favor > state.mfe:
                    state.mfe = round(favor, self.dec)
                if adverse > state.mae:
                    state.mae = round(adverse, self.dec)
                state.save()

            # Breakeven rule
            if not done and not state.be_applied and state.entry_time:
                elapsed = (now - datetime.fromisoformat(
                    state.entry_time)).total_seconds()
                if elapsed >= inst.be_hours * 3600:
                    self._apply_breakeven(now, price)

            # Dry-run exit simulation
            if self.dry_run and not done:
                done = self._dry_run_exit_check(now)

            if done:
                self._record_exit(now, done)

        # ── DONE_TODAY ──
        elif state.status == InstrumentState.DONE_TODAY:
            pass  # nothing to do

    def status_line(self, now: datetime) -> str:
        """One-line status string for periodic heartbeat."""
        state = self.state
        price = self.conn.get_price(self.inst.name)
        p_str = f"{price:.{self.dec}f}" if price else "n/a"

        if state.status == InstrumentState.IDLE:
            return f"{self.tag} IDLE | price={p_str}"

        elif state.status == InstrumentState.RANGE_COMPUTED:
            return (f"{self.tag} RANGE H={state.range_high:.{self.dec}f} "
                    f"L={state.range_low:.{self.dec}f} | "
                    f"price={p_str} | "
                    f"trade opens {self.inst.trade_start_hour}:00 UTC")

        elif state.status == InstrumentState.ORDERS_PLACED:
            vel = self.conn.get_tick_velocity(
                self.inst.name, self.inst.velocity_lookback_minutes)
            vel_str = (f" | vel={vel:.0f}/{self.inst.velocity_threshold}"
                       if self.inst.velocity_filter_enabled else "")
            return (f"{self.tag} WATCHING | price={p_str} | "
                    f"range H={state.range_high:.{self.dec}f} "
                    f"L={state.range_low:.{self.dec}f}{vel_str}")

        elif state.status == InstrumentState.IN_TRADE:
            if price:
                unreal = ((price - state.entry_price)
                          if state.direction == "LONG"
                          else (state.entry_price - price))
                be_str = ""
                if state.be_applied:
                    be_str = " | BE applied"
                elif state.entry_time:
                    elapsed = (now - datetime.fromisoformat(
                        state.entry_time)).total_seconds()
                    remain = max(0, self.inst.be_hours * 3600 - elapsed)
                    be_str = f" | BE in {int(remain)//60}m"
                return (f"{self.tag} {state.direction} | "
                        f"price={p_str} | "
                        f"entry={state.entry_price:.{self.dec}f} "
                        f"SL={state.sl_price:.{self.dec}f} "
                        f"TP={state.tp_price:.{self.dec}f} | "
                        f"PnL={unreal:+.{self.dec}f}{be_str}")
            return f"{self.tag} {state.direction} | price=n/a"

        else:
            return f"{self.tag} DONE"

    def reset_for_new_day(self, today_str: str):
        self.state.reset_for_new_day(today_str)

    # ── Private helpers ───────────────────────────────────────────

    def _check_velocity(self) -> tuple[bool, float]:
        """Check if current tick velocity passes the filter.
        Returns (passed: bool, velocity: float ticks/min)."""
        inst = self.inst
        if not inst.velocity_filter_enabled:
            return True, 0.0

        velocity = self.conn.get_tick_velocity(
            inst.name, inst.velocity_lookback_minutes)

        threshold = inst.velocity_threshold
        if threshold <= 0:
            # Adaptive threshold not implemented in live yet — use fixed
            self.log.warning(
                f"{self.tag} velocity_threshold=0 (adaptive) not supported "
                f"in live mode. Skipping velocity check.")
            return True, velocity

        passed = velocity >= threshold
        return passed, velocity

    def _velocity_reject_close(self, now: datetime):
        """Close position immediately after velocity rejection (Option B).
        Logs the rejection and marks day as done."""
        close_fill = self._cancel_and_close()
        state = self.state
        price = close_fill or self.conn.get_price(self.inst.name) or state.entry_price
        pnl = ((price - state.entry_price) if state.direction == "LONG"
               else (state.entry_price - price))
        pnl_total = round(pnl * self.inst.qty * self.inst.point_value, 2)
        self.log.info(
            f"{self.tag} VELOCITY REJECT: {state.direction} | "
            f"Entry={state.entry_price:.{self.dec}f} "
            f"Exit={price:.{self.dec}f} | "
            f"Spread cost=${pnl_total:+.2f}")
        log_trade({
            'timestamp': now.isoformat(),
            'date': state.trade_date,
            'instrument': self.inst.name,
            'direction': state.direction,
            'entry': state.entry_price,
            'exit': price,
            'sl': state.sl_price,
            'tp': state.tp_price,
            'range_high': state.range_high,
            'range_low': state.range_low,
            'range_size': state.range_size,
            'qty': self.inst.qty,
            'pnl_per_unit': round(pnl, self.dec),
            'pnl_total': pnl_total,
            'result': 'VELOCITY_REJECT',
            'hold_minutes': 0,
            'mfe': 0,
            'mae': 0,
            'account_mode': self.account_mode,
        }, self.trade_log)
        state.status = InstrumentState.DONE_TODAY
        state.save()
        if self.guardrails:
            self.guardrails.on_trade_closed(
                pnl_total, self.inst.name, state.direction,
                'VELOCITY_REJECT', state.entry_price, price)

    def _log_velocity_at_fill(self, now: datetime, avg_vel: float,
                               per_min: list[int], event: str):
        """Log a velocity CSV row at fill/rejection time for calibration analysis."""
        inst = self.inst
        price = self.conn.get_price(inst.name)
        log_velocity({
            'timestamp': now.isoformat(),
            'date': self.state.trade_date,
            'instrument': inst.name,
            'hour': now.hour,
            'minute': now.minute,
            'ticks_1min': per_min[-1] if per_min else 0,
            'ticks_2min': per_min[-2] if len(per_min) >= 2 else 0,
            'ticks_3min': per_min[-3] if len(per_min) >= 3 else 0,
            'ticks_4min': per_min[-4] if len(per_min) >= 4 else 0,
            'ticks_5min': per_min[-5] if len(per_min) >= 5 else 0,
            'avg_4min': round(avg_vel, 1),
            'threshold': inst.velocity_threshold,
            'price': round(price, inst.price_decimals) if price else '',
            'state': event,
        }, self.log_dir, inst.name)

    def _log_pre_placement(self, now: datetime):
        price = self.conn.get_price(self.inst.name)
        state = self.state
        if price is not None:
            if price > state.range_high:
                rel = "ABOVE range_high"
            elif price < state.range_low:
                rel = "BELOW range_low"
            else:
                rel = "INSIDE range"
            self.log.info(
                f"{self.tag} Pre-placement | price={price:.{self.dec}f} | "
                f"range {state.range_low:.{self.dec}f}-"
                f"{state.range_high:.{self.dec}f} | {rel}")
        self.log.info(f"{self.tag} Trade window open -- placing brackets")

    def _place_bracket_orders(self, now: datetime):
        from ib_insync import Order
        state = self.state
        inst = self.inst
        rr = inst.rr_ratio
        d = self.dec

        rh, rl, rs = state.range_high, state.range_low, state.range_size

        long_entry = round(rh, d)
        long_sl = round(rl, d)
        long_tp = round(rh + rr * rs, d)

        short_entry = round(rl, d)
        short_sl = round(rh, d)
        short_tp = round(rl - rr * rs, d)

        # ── Gap-open info (no skip) ──
        # If price already broke past a stop level, the stop order will fill
        # immediately at market. Backtest shows gap-open trades are among the
        # best (strong momentum signal), so we place the order anyway.
        price = self.conn.get_price(inst.name)
        if price is not None:
            if price >= long_entry:
                self.log.info(
                    f"{self.tag} Price {price:.{d}f} >= buy stop "
                    f"{long_entry:.{d}f} -- gap-open long "
                    f"(will fill at market)")
            if price <= short_entry:
                self.log.info(
                    f"{self.tag} Price {price:.{d}f} <= sell stop "
                    f"{short_entry:.{d}f} -- gap-open short "
                    f"(will fill at market)")

        self.log.info(f"{self.tag} LONG:  entry={long_entry} SL={long_sl} "
                      f"TP={long_tp}")
        self.log.info(f"{self.tag} SHORT: entry={short_entry} SL={short_sl} "
                      f"TP={short_tp}")
        self.log.info(f"{self.tag} Qty: {inst.qty}, RR={rr}")

        if self.dry_run:
            state.orders_placed_time = now.isoformat()
            state.status = InstrumentState.ORDERS_PLACED
            state.save()
            return

        if not self.conn.ensure_connected():
            self.log.error(f"{self.tag} Not connected -- cannot place orders")
            return

        contract = self.conn.contracts.get(inst.name)
        if contract is None:
            self.log.error(f"{self.tag} No contract available")
            return

        oca_group = f"ORB_{inst.name}_{state.trade_date}_{now.strftime('%H%M%S')}"
        trade_end_utc = now.replace(
            hour=inst.trade_end_hour, minute=0, second=0, microsecond=0)
        gtd_time = trade_end_utc.strftime("%Y%m%d %H:%M:%S %Z")

        try:
            # Buy stop bracket
            buy_parent = Order(
                action="BUY", orderType="STP", totalQuantity=inst.qty,
                auxPrice=long_entry, tif="GTD", goodTillDate=gtd_time,
                ocaGroup=oca_group, ocaType=1, transmit=False)
            buy_sl = Order(
                action="SELL", orderType="STP", totalQuantity=inst.qty,
                auxPrice=long_sl, tif="GTC", transmit=False)
            buy_tp = Order(
                action="SELL", orderType="LMT", totalQuantity=inst.qty,
                lmtPrice=long_tp, tif="GTC", transmit=False)

            buy_trade = self.conn.ib.placeOrder(contract, buy_parent)
            self.conn.sleep(1)
            buy_id = buy_trade.order.orderId

            buy_sl.parentId = buy_id
            buy_sl_trade = self.conn.ib.placeOrder(contract, buy_sl)
            self.conn.sleep(0.5)

            buy_tp.parentId = buy_id
            buy_tp.transmit = True
            buy_tp_trade = self.conn.ib.placeOrder(contract, buy_tp)
            self.conn.sleep(1)

            buy_sl_id = buy_sl_trade.order.orderId
            buy_tp_id = buy_tp_trade.order.orderId
            self.log.info(f"{self.tag} Buy bracket placed: id={buy_id}"
                          f" (SL={buy_sl_id}, TP={buy_tp_id})")

            # Sell stop bracket
            sell_parent = Order(
                action="SELL", orderType="STP", totalQuantity=inst.qty,
                auxPrice=short_entry, tif="GTD", goodTillDate=gtd_time,
                ocaGroup=oca_group, ocaType=1, transmit=False)
            sell_sl = Order(
                action="BUY", orderType="STP", totalQuantity=inst.qty,
                auxPrice=short_sl, tif="GTC", transmit=False)
            sell_tp = Order(
                action="BUY", orderType="LMT", totalQuantity=inst.qty,
                lmtPrice=short_tp, tif="GTC", transmit=True)

            sell_trade = self.conn.ib.placeOrder(contract, sell_parent)
            self.conn.sleep(1)
            sell_id = sell_trade.order.orderId

            sell_sl.parentId = sell_id
            sell_sl_trade = self.conn.ib.placeOrder(contract, sell_sl)
            self.conn.sleep(0.5)

            sell_tp.parentId = sell_id
            sell_tp.transmit = True
            sell_tp_trade = self.conn.ib.placeOrder(contract, sell_tp)
            self.conn.sleep(1)

            sell_sl_id = sell_sl_trade.order.orderId
            sell_tp_id = sell_tp_trade.order.orderId
            self.log.info(f"{self.tag} Sell bracket placed: id={sell_id}"
                          f" (SL={sell_sl_id}, TP={sell_tp_id})")

            state.buy_order_id = buy_id
            state.sell_order_id = sell_id
            state.buy_sl_order_id = buy_sl_id
            state.buy_tp_order_id = buy_tp_id
            state.sell_sl_order_id = sell_sl_id
            state.sell_tp_order_id = sell_tp_id
            state.orders_placed_time = now.isoformat()
            state.status = InstrumentState.ORDERS_PLACED
            state.save()

        except Exception as e:
            self.log.error(f"{self.tag} Order placement failed: {e}")

    def _check_fills(self) -> bool:
        if self.dry_run:
            return False
        if not self.conn.ensure_connected():
            return False
        state = self.state
        inst = self.inst
        rr = inst.rr_ratio
        try:
            self.conn.sleep(0)
            for trade in self.conn.ib.trades():
                oid = trade.order.orderId
                if (oid == state.buy_order_id
                        and trade.orderStatus.status == 'Filled'):
                    fill = trade.orderStatus.avgFillPrice
                    state.direction = "LONG"
                    state.entry_price = fill
                    state.sl_price = state.range_low
                    state.tp_price = round(
                        state.range_high + rr * state.range_size, self.dec)
                    state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                    state.status = InstrumentState.IN_TRADE
                    state.save()
                    return True
                elif (oid == state.sell_order_id
                      and trade.orderStatus.status == 'Filled'):
                    fill = trade.orderStatus.avgFillPrice
                    state.direction = "SHORT"
                    state.entry_price = fill
                    state.sl_price = state.range_high
                    state.tp_price = round(
                        state.range_low - rr * state.range_size, self.dec)
                    state.entry_time = datetime.now(tz=timezone.utc).isoformat()
                    state.status = InstrumentState.IN_TRADE
                    state.save()
                    return True
        except Exception as e:
            self.log.warning(f"{self.tag} check_fills error: {e}")
        return False

    def _check_exit(self) -> bool:
        if self.dry_run:
            return False
        if not self.conn.ensure_connected():
            return False
        state = self.state
        try:
            self.conn.sleep(0)

            # First, check if SL or TP child orders filled (gives us exact exit info)
            sl_oid = (state.buy_sl_order_id if state.direction == "LONG"
                      else state.sell_sl_order_id)
            tp_oid = (state.buy_tp_order_id if state.direction == "LONG"
                      else state.sell_tp_order_id)

            for trade in self.conn.ib.trades():
                oid = trade.order.orderId
                if oid == tp_oid and trade.orderStatus.status == 'Filled':
                    fill_px = trade.orderStatus.avgFillPrice
                    self._exit_fill_price = fill_px
                    self._exit_fill_type = 'TP'
                    self.log.info(
                        f"{self.tag} TP order {oid} filled at {fill_px:.{self.dec}f}")
                    return True
                if oid == sl_oid and trade.orderStatus.status == 'Filled':
                    fill_px = trade.orderStatus.avgFillPrice
                    self._exit_fill_price = fill_px
                    if state.be_applied:
                        self._exit_fill_type = 'BE'
                    else:
                        self._exit_fill_type = 'SL'
                    self.log.info(
                        f"{self.tag} {self._exit_fill_type} order {oid} filled "
                        f"at {fill_px:.{self.dec}f}")
                    return True

            # Fallback: check if position simply vanished (unknown reason)
            # Grace period: skip this check for 30s after entry to avoid
            # false positives from ib.positions() cache lag after fill.
            if state.entry_time:
                entry_dt = datetime.fromisoformat(state.entry_time)
                secs_in_trade = (datetime.now(tz=timezone.utc) - entry_dt).total_seconds()
                if secs_in_trade < 30:
                    return False

            positions = self.conn.ib.positions()
            contract = self.conn.contracts.get(self.inst.name)
            if contract is None:
                return False
            has_pos = any(
                p.contract.conId == contract.conId and abs(p.position) > 0
                for p in positions
            )
            if not has_pos:
                # Double-check with a fresh positions request
                self.conn.sleep(2)
                positions = self.conn.ib.positions()
                has_pos = any(
                    p.contract.conId == contract.conId and abs(p.position) > 0
                    for p in positions
                )
            if not has_pos:
                self._exit_fill_price = None
                self._exit_fill_type = 'CLOSED'
                self.log.warning(
                    f"{self.tag} Position vanished without detected SL/TP fill")
                return True

        except Exception as e:
            self.log.warning(f"{self.tag} check_exit error: {e}")
        return False

    def _dry_run_fill_check(self, now: datetime):
        price = self.conn.get_price(self.inst.name)
        state = self.state
        inst = self.inst
        if price is None:
            return
        rr = inst.rr_ratio
        if price > state.range_high:
            self.log.info(f"{self.tag} [DRY RUN] Price {price:.{self.dec}f} > "
                          f"high {state.range_high:.{self.dec}f} -> LONG")
            state.direction = "LONG"
            state.entry_price = state.range_high
            state.sl_price = state.range_low
            state.tp_price = round(
                state.range_high + rr * state.range_size, self.dec)
            state.entry_time = now.isoformat()
            state.status = InstrumentState.IN_TRADE
            state.save()
        elif price < state.range_low:
            self.log.info(f"{self.tag} [DRY RUN] Price {price:.{self.dec}f} < "
                          f"low {state.range_low:.{self.dec}f} -> SHORT")
            state.direction = "SHORT"
            state.entry_price = state.range_low
            state.sl_price = state.range_high
            state.tp_price = round(
                state.range_low - rr * state.range_size, self.dec)
            state.entry_time = now.isoformat()
            state.status = InstrumentState.IN_TRADE
            state.save()

    def _dry_run_exit_check(self, now: datetime) -> bool:
        price = self.conn.get_price(self.inst.name)
        state = self.state
        if price is None:
            return False
        if state.direction == "LONG":
            if price <= state.sl_price:
                self.log.info(f"{self.tag} [DRY RUN] SL hit "
                              f"at {state.sl_price:.{self.dec}f}")
                self._exit_result = 'SL'
                self._exit_price = state.sl_price
                return True
            if price >= state.tp_price:
                self.log.info(f"{self.tag} [DRY RUN] TP hit "
                              f"at {state.tp_price:.{self.dec}f}")
                self._exit_result = 'TP'
                self._exit_price = state.tp_price
                return True
        else:
            if price >= state.sl_price:
                self.log.info(f"{self.tag} [DRY RUN] SL hit "
                              f"at {state.sl_price:.{self.dec}f}")
                self._exit_result = 'SL'
                self._exit_price = state.sl_price
                return True
            if price <= state.tp_price:
                self.log.info(f"{self.tag} [DRY RUN] TP hit "
                              f"at {state.tp_price:.{self.dec}f}")
                self._exit_result = 'TP'
                self._exit_price = state.tp_price
                return True
        return False

    def _apply_breakeven(self, now: datetime, current_price=None):
        state = self.state
        inst = self.inst
        be_offset = inst.be_offset

        if state.direction == "LONG":
            new_sl = round(state.entry_price + be_offset, self.dec)
        else:
            new_sl = round(state.entry_price - be_offset, self.dec)

        # Guard: don't move SL to BE if price is already past it
        # (would create an untriggerable stop and lock in a loss)
        if current_price is not None:
            if state.direction == "LONG" and current_price < new_sl:
                self.log.info(
                    f"{self.tag} BE skipped: price {current_price:.{self.dec}f}"
                    f" < new_sl {new_sl:.{self.dec}f}, keeping original SL")
                return
            if state.direction == "SHORT" and current_price > new_sl:
                self.log.info(
                    f"{self.tag} BE skipped: price {current_price:.{self.dec}f}"
                    f" > new_sl {new_sl:.{self.dec}f}, keeping original SL")
                return

        if self.dry_run:
            self.log.info(
                f"{self.tag} [DRY RUN] BE rule: SL "
                f"{state.sl_price:.{self.dec}f} -> {new_sl:.{self.dec}f} "
                f"(entry {state.entry_price:.{self.dec}f} + "
                f"offset {be_offset})")
            state.sl_price = new_sl
            state.be_applied = True
            state.save()
            return

        if not self.conn.ensure_connected():
            return

        contract = self.conn.contracts.get(inst.name)
        if contract is None:
            return

        # Match by exact order ID to avoid modifying another instrument's SL
        target_sl_oid = (state.buy_sl_order_id if state.direction == "LONG"
                         else state.sell_sl_order_id)
        if not target_sl_oid:
            self.log.warning(f"{self.tag} BE: No SL order ID saved in state")
            return

        try:
            for trade in self.conn.ib.openTrades():
                if trade.order.orderId == target_sl_oid:
                    old_sl = trade.order.auxPrice
                    trade.order.auxPrice = new_sl
                    self.conn.ib.placeOrder(contract, trade.order)
                    self.conn.sleep(0.5)
                    state.sl_price = new_sl
                    state.be_applied = True
                    state.save()
                    self.log.info(
                        f"{self.tag} BE rule: SL order {target_sl_oid} "
                        f"{old_sl:.{self.dec}f} -> {new_sl:.{self.dec}f}")
                    return
            self.log.warning(
                f"{self.tag} BE: SL order {target_sl_oid} not found in open trades")
        except Exception as e:
            self.log.error(f"{self.tag} BE failed: {e}")

    def _cancel_and_close(self) -> Optional[float]:
        """Cancel all orders for this instrument and close any position.
        Returns the actual fill price if a position was closed, None otherwise."""
        if self.dry_run:
            self.log.info(f"{self.tag} [DRY RUN] Would cancel/close")
            return None
        if not self.conn.ensure_connected():
            return None
        contract = self.conn.contracts.get(self.inst.name)
        if contract is None:
            return None

        # Only cancel orders belonging to THIS instrument
        my_order_ids = set()
        if self.state.buy_order_id:
            my_order_ids.add(self.state.buy_order_id)
        if self.state.sell_order_id:
            my_order_ids.add(self.state.sell_order_id)

        try:
            for trade in self.conn.ib.openTrades():
                oid = trade.order.orderId
                parent = trade.order.parentId
                # Cancel if it's our parent order or a child of our parent
                if oid in my_order_ids or parent in my_order_ids:
                    try:
                        self.conn.ib.cancelOrder(trade.order)
                        self.conn.sleep(0.5)
                    except Exception:
                        pass
            self.conn.sleep(2)

            # Close any remaining position with verification
            actual_fill_price = None
            for pos in self.conn.ib.positions():
                if (pos.contract.conId == contract.conId
                        and abs(pos.position) > 0):
                    from ib_insync import MarketOrder
                    action = "SELL" if pos.position > 0 else "BUY"
                    close_order = MarketOrder(action, abs(pos.position))
                    close_trade = self.conn.ib.placeOrder(contract, close_order)
                    self.conn.sleep(3)

                    # Verify fill: check trade status
                    fill_verified = False
                    for attempt in range(3):
                        self.conn.sleep(0)  # pump events
                        if close_trade.orderStatus.status == 'Filled':
                            actual_fill_price = close_trade.orderStatus.avgFillPrice
                            self.log.info(
                                f"{self.tag} Position closed at market "
                                f"(fill price={actual_fill_price})")
                            fill_verified = True
                            break
                        # Also check if position is gone
                        self.conn.sleep(2)
                        still_open = any(
                            p.contract.conId == contract.conId
                            and abs(p.position) > 0
                            for p in self.conn.ib.positions()
                        )
                        if not still_open:
                            # Position gone but didn't catch fill price —
                            # use avgFillPrice if available, else streaming price
                            actual_fill_price = (
                                close_trade.orderStatus.avgFillPrice
                                or self.conn.get_price(self.inst.name))
                            self.log.info(
                                f"{self.tag} Position confirmed closed (attempt {attempt+1})"
                                f" fill_price={actual_fill_price}")
                            fill_verified = True
                            break
                        self.log.warning(
                            f"{self.tag} Close order not yet filled "
                            f"(attempt {attempt+1}/3, status={close_trade.orderStatus.status})")

                    if not fill_verified:
                        self.log.error(
                            f"{self.tag} CRITICAL: Position may still be open after "
                            f"close attempt! Manual check required. "
                            f"Close order status={close_trade.orderStatus.status}")
            return actual_fill_price
        except Exception as e:
            self.log.error(f"{self.tag} cancel_and_close failed: {e}")
            return None

    def _time_exit_close(self, now: datetime):
        """Time-based exit: cancel remaining orders, close position at market."""
        close_fill = self._cancel_and_close()
        state = self.state
        price = close_fill or self.conn.get_price(self.inst.name) or state.entry_price
        pnl = ((price - state.entry_price) if state.direction == "LONG"
               else (state.entry_price - price))
        # Final MFE/MAE update with closing price
        if state.entry_price:
            if state.direction == "LONG":
                favor = price - state.entry_price
                adverse = state.entry_price - price
            else:
                favor = state.entry_price - price
                adverse = price - state.entry_price
            if favor > state.mfe:
                state.mfe = round(favor, self.dec)
            if adverse > state.mae:
                state.mae = round(adverse, self.dec)
        pnl_total = round(pnl * self.inst.qty * self.inst.point_value, 2)
        hold_m = (int((now - datetime.fromisoformat(
            state.entry_time)).total_seconds() / 60)
            if state.entry_time else 0)
        self.log.info(
            f"{self.tag} Time exit: {state.direction} | "
            f"Entry={state.entry_price:.{self.dec}f} "
            f"Exit={price:.{self.dec}f} | "
            f"PnL={pnl:+.{self.dec}f}/unit | "
            f"Total=${pnl_total:+.2f} | Hold={hold_m}min")
        log_trade({
            'timestamp': now.isoformat(),
            'date': state.trade_date,
            'instrument': self.inst.name,
            'direction': state.direction,
            'entry': state.entry_price,
            'exit': price,
            'sl': state.sl_price,
            'tp': state.tp_price,
            'range_high': state.range_high,
            'range_low': state.range_low,
            'range_size': state.range_size,
            'qty': self.inst.qty,
            'pnl_per_unit': round(pnl, self.dec),
            'pnl_total': pnl_total,
            'result': 'TIME_EXIT',
            'hold_minutes': hold_m,
            'mfe': state.mfe,
            'mae': state.mae,
            'account_mode': self.account_mode,
        }, self.trade_log)
        state.status = InstrumentState.DONE_TODAY
        state.save()
        # Guardrail: track P&L
        if self.guardrails:
            self.guardrails.on_trade_closed(
                pnl_total, self.inst.name, state.direction,
                'TIME_EXIT', state.entry_price, price)

    def _eod_close(self, now: datetime):
        """End-of-day close: cancel orders, close position, log trade."""
        close_fill = self._cancel_and_close()
        state = self.state
        price = close_fill or self.conn.get_price(self.inst.name) or state.entry_price
        pnl = ((price - state.entry_price) if state.direction == "LONG"
               else (state.entry_price - price))
        # Final MFE/MAE update with closing price
        if state.entry_price:
            if state.direction == "LONG":
                favor = price - state.entry_price
                adverse = state.entry_price - price
            else:
                favor = state.entry_price - price
                adverse = price - state.entry_price
            if favor > state.mfe:
                state.mfe = round(favor, self.dec)
            if adverse > state.mae:
                state.mae = round(adverse, self.dec)
        pnl_total = round(pnl * self.inst.qty * self.inst.point_value, 2)
        hold_m = (int((now - datetime.fromisoformat(
            state.entry_time)).total_seconds() / 60)
            if state.entry_time else 0)
        log_trade({
            'timestamp': now.isoformat(),
            'date': state.trade_date,
            'instrument': self.inst.name,
            'direction': state.direction,
            'entry': state.entry_price,
            'exit': price,
            'sl': state.sl_price,
            'tp': state.tp_price,
            'range_high': state.range_high,
            'range_low': state.range_low,
            'range_size': state.range_size,
            'qty': self.inst.qty,
            'pnl_per_unit': round(pnl, self.dec),
            'pnl_total': pnl_total,
            'result': 'TIME',
            'hold_minutes': hold_m,
            'mfe': state.mfe,
            'mae': state.mae,
            'account_mode': self.account_mode,
        }, self.trade_log)
        state.status = InstrumentState.DONE_TODAY
        state.save()
        # Guardrail: track P&L
        if self.guardrails:
            self.guardrails.on_trade_closed(
                pnl_total, self.inst.name, state.direction,
                'TIME', state.entry_price, price)

    def _record_exit(self, now: datetime, done: bool):
        """Record a completed trade (SL/TP/BE exit)."""
        state = self.state
        if not self.dry_run:
            # Use actual fill info from _check_exit if available
            fill_px = getattr(self, '_exit_fill_price', None)
            fill_type = getattr(self, '_exit_fill_type', None)

            if fill_px is not None:
                # Got exact fill from IBKR order records
                exit_price = fill_px
                result = fill_type  # 'TP', 'SL', or 'BE'
            else:
                # Fallback: position vanished without detected order fill
                exit_price = self.conn.get_price(self.inst.name) or state.entry_price
                result = fill_type if fill_type else 'CLOSED'

            pnl = ((exit_price - state.entry_price) if state.direction == "LONG"
                   else (state.entry_price - exit_price))
        else:
            exit_price = getattr(self, '_exit_price', state.entry_price)
            result = getattr(self, '_exit_result', 'UNKNOWN')
            pnl = ((exit_price - state.entry_price)
                   if state.direction == "LONG"
                   else (state.entry_price - exit_price))

        hold_m = (int((now - datetime.fromisoformat(
            state.entry_time)).total_seconds() / 60)
            if state.entry_time else 0)

        pnl_total = round(pnl * self.inst.qty * self.inst.point_value, 2)
        self.log.info(
            f"{self.tag} Trade closed: {state.direction} {result} | "
            f"Entry={state.entry_price:.{self.dec}f} "
            f"Exit={exit_price:.{self.dec}f} | "
            f"PnL={pnl:+.{self.dec}f}/unit | "
            f"Total=${pnl_total:+.2f}")

        log_trade({
            'timestamp': now.isoformat(),
            'date': state.trade_date,
            'instrument': self.inst.name,
            'direction': state.direction,
            'entry': state.entry_price,
            'exit': exit_price,
            'sl': state.sl_price,
            'tp': state.tp_price,
            'range_high': state.range_high,
            'range_low': state.range_low,
            'range_size': state.range_size,
            'qty': self.inst.qty,
            'pnl_per_unit': round(pnl, self.dec),
            'pnl_total': pnl_total,
            'result': result,
            'hold_minutes': hold_m,
            'mfe': state.mfe,
            'mae': state.mae,
            'account_mode': self.account_mode,
        }, self.trade_log)

        state.status = InstrumentState.DONE_TODAY
        state.save()

        # Guardrail: track P&L + notify
        if self.guardrails:
            self.guardrails.on_trade_closed(
                pnl_total, self.inst.name, state.direction,
                result, state.entry_price, exit_price)

        # Clean up temp attributes
        self._exit_price = None
        self._exit_result = None
        self._exit_fill_price = None
        self._exit_fill_type = None


# ── Account Snapshot ──────────────────────────────────────────────────────────

def _snapshot_account(conn: SharedConnection, cfg: Config, log: logging.Logger):
    """Query IBKR account summary and write to JSON for the dashboard."""
    if not conn.connected:
        return
    try:
        summary = conn.ib.accountSummary()
        if not summary:
            return

        acct = {}
        for item in summary:
            acct[item.tag] = item.value

        snapshot = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "net_liquidation": acct.get("NetLiquidation", ""),
            "total_cash": acct.get("TotalCashValue", ""),
            "unrealized_pnl": acct.get("UnrealizedPnL", ""),
            "realized_pnl": acct.get("RealizedPnL", ""),
            "buying_power": acct.get("BuyingPower", ""),
            "maint_margin": acct.get("MaintMarginReq", ""),
            "currency": acct.get("Currency", "USD"),
        }

        snap_path = Path(cfg.paths.state_dir) / "account_snapshot.json"
        snap_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    except Exception as e:
        log.debug(f"Account snapshot failed: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_day(managers: list[InstrumentManager], conn: SharedConnection,
            cfg: Config, log: logging.Logger,
            guardrails: Guardrails = None):
    """Run one trading day for all instruments."""
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    poll = cfg.strategy.poll_interval

    # Reset state for any manager not yet on today's date
    for mgr in managers:
        if mgr.state.trade_date != today_str:
            log.info(f"{mgr.tag} New day: {today_str}")
            mgr.reset_for_new_day(today_str)

    # Skip configured weekdays per instrument (do this EARLY, before any logic)
    trade_date_dt = datetime.strptime(today_str, "%Y-%m-%d")
    trade_weekday = trade_date_dt.weekday()
    for mgr in managers:
        if trade_weekday in mgr.inst.skip_weekdays:
            day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][trade_weekday]
            log.info(f"{mgr.tag} {day_name} skipped (trade_date={today_str})")
            mgr.state.status = InstrumentState.DONE_TODAY
            mgr.state.save()

    # Guardrail: reset daily P&L tracker
    if guardrails:
        guardrails.on_new_day(today_str, cfg.paths.log_dir)

    # Verify any ORDERS_PLACED states still have live orders at IBKR
    for mgr in managers:
        mgr.verify_orders_on_startup()

    now = datetime.now(tz=timezone.utc)

    # Skip weekends (use trade_date, not wall-clock)
    if trade_date_dt.weekday() >= 5:
        log.info(f"Weekend ({today_str}) -- no trading")
        return

    log.info(f"Starting multi-ORB day | instruments: "
             f"{', '.join(m.inst.name for m in managers)} | "
             f"dry_run={managers[0].dry_run}")

    last_heartbeat = 0.0

    while True:
        now = datetime.now(tz=timezone.utc)

        if not conn.ensure_connected():
            log.warning("Connection unavailable -- sleeping 30s")
            time.sleep(30)
            continue

        # Run state machine for each instrument
        all_done = True
        for mgr in managers:
            inst = mgr.inst
            # Skip if already done (includes weekday skips set at startup)
            if mgr.state.status == InstrumentState.DONE_TODAY:
                continue

            try:
                mgr.tick(now)
            except Exception as e:
                log.error(f"{mgr.tag} Error in tick: {e}", exc_info=True)
                if guardrails:
                    guardrails.on_error(str(e), mgr.inst.name)

            if mgr.state.status != InstrumentState.DONE_TODAY:
                # Check if trade window has passed without action
                if (now.hour >= inst.trade_end_hour
                        and mgr.state.status in (InstrumentState.IDLE,
                                                  InstrumentState.RANGE_COMPUTED)):
                    log.info(f"{mgr.tag} Window closed, no trade taken")
                    mgr.state.status = InstrumentState.DONE_TODAY
                    mgr.state.save()
                else:
                    all_done = False

        # Periodic heartbeat (every 60s)
        now_ts = now.timestamp()
        if now_ts - last_heartbeat >= 60:
            last_heartbeat = now_ts
            for mgr in managers:
                if mgr.state.status != InstrumentState.DONE_TODAY:
                    log.info(f"[STATUS] {mgr.status_line(now)}")

            # Velocity logging: record tick counts every minute during 06:00-10:00 UTC
            if VELOCITY_LOG_START_HOUR <= now.hour < VELOCITY_LOG_END_HOUR:
                for mgr in managers:
                    inst = mgr.inst
                    if not inst.velocity_filter_enabled:
                        continue
                    per_min = conn.get_tick_counts_per_minute(inst.name, 5)
                    avg_4 = conn.get_tick_velocity(
                        inst.name, inst.velocity_lookback_minutes)
                    price = conn.get_price(inst.name)
                    log_velocity({
                        'timestamp': now.isoformat(),
                        'date': today_str,
                        'instrument': inst.name,
                        'hour': now.hour,
                        'minute': now.minute,
                        'ticks_1min': per_min[-1] if per_min else 0,
                        'ticks_2min': per_min[-2] if len(per_min) >= 2 else 0,
                        'ticks_3min': per_min[-3] if len(per_min) >= 3 else 0,
                        'ticks_4min': per_min[-4] if len(per_min) >= 4 else 0,
                        'ticks_5min': per_min[-5] if len(per_min) >= 5 else 0,
                        'avg_4min': round(avg_4, 1),
                        'threshold': inst.velocity_threshold,
                        'price': round(price, inst.price_decimals) if price else '',
                        'state': mgr.state.status,
                    }, cfg.paths.log_dir, inst.name)

            # Snapshot account balance to JSON for dashboard
            _snapshot_account(conn, cfg, log)

        if all_done:
            log.info("All instruments done for today.")
            break

        conn.sleep(poll)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Multi-instrument Asian Range -> Session Breakout (v5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log only, do not place orders")
    parser.add_argument("--port", type=int, default=None,
                        help="Override IBKR port")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to alternative config.yaml")
    parser.add_argument("--only", nargs='+', default=None,
                        help="Only trade these instruments (e.g. --only EURUSD)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.port is not None:
        cfg.ibkr.port = args.port

    log = setup_logging(cfg)

    # Determine which instruments to trade
    enabled = {}
    for name, inst in cfg.instruments.items():
        if not inst.enabled:
            continue
        if args.only and name not in [x.upper() for x in args.only]:
            continue
        enabled[name] = inst

    if not enabled:
        log.error("No instruments enabled. Check config.yaml or --only flag.")
        sys.exit(1)

    print("=" * 65)
    print("  Multi-Instrument ORB Session Breakout  (v5)")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  IBKR: {cfg.ibkr.host}:{cfg.ibkr.port} "
          f"(clientId={cfg.ibkr.client_id})")
    print(f"  Instruments:")
    for name, inst in enabled.items():
        te_str = f"TimeExit={inst.time_exit_minutes}min" if inst.time_exit_minutes > 0 else "TimeExit=off"
        vel_str = (f"VelFilter={inst.velocity_threshold}ticks/{inst.velocity_lookback_minutes+1}min"
                   if inst.velocity_filter_enabled else "VelFilter=off")
        print(f"    {name}: {inst.symbol} {inst.sec_type} | "
              f"range {inst.asian_start_hour}-{inst.asian_end_hour} -> "
              f"trade {inst.trade_start_hour}-{inst.trade_end_hour} UTC | "
              f"qty={inst.qty} | RR={inst.rr_ratio} | "
              f"BE={inst.be_hours}h +{inst.be_offset} | {te_str} | {vel_str}")
    print("=" * 65)

    if not args.dry_run:
        print("\n  WARNING: LIVE MODE -- real orders will be placed!")
        print("  Press Ctrl+C to abort.\n")

    # Initialize guardrails
    guards = Guardrails(cfg, log)

    conn = SharedConnection(cfg, log)
    if not conn.connect():
        log.error("Could not connect to IBKR after retries")
        sys.exit(1)

    # Qualify contracts for all instruments
    for name, inst in enabled.items():
        if not conn.qualify_contract(inst):
            log.error(f"Cannot qualify {name} -- removing from session")
            continue
        # Start tick counter for velocity filter
        if inst.velocity_filter_enabled:
            conn.start_tick_counter(name)

    # Create managers (with guardrails)
    account_mode = 'live' if cfg.ibkr.port == 4001 else 'paper'
    managers = []
    for name, inst in enabled.items():
        if name not in conn.contracts:
            continue
        mgr = InstrumentManager(inst, conn, cfg.paths.state_dir,
                                log, args.dry_run, guardrails=guards,
                                account_mode=account_mode)
        managers.append(mgr)

    if not managers:
        log.error("No instruments with valid contracts. Exiting.")
        conn.disconnect()
        sys.exit(1)

    log.info(f"Active instruments: "
             f"{', '.join(m.inst.name for m in managers)}")

    # Guardrail: startup scan (orphans, load today's P&L)
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    guards.on_startup(conn, managers, today_str, cfg.paths.log_dir)

    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        graceful_shutdown(managers, conn, log,
                          notifier=guards.notifier, reason="signal")
        sys.exit(0)

    signal_mod.signal(signal_mod.SIGINT, shutdown)
    signal_mod.signal(signal_mod.SIGTERM, shutdown)

    try:
        while True:
            run_day(managers, conn, cfg, log, guardrails=guards)

            # Sleep until next UTC midnight + 10 min
            now = datetime.now(tz=timezone.utc)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=10, second=0, microsecond=0)
            wait_sec = (next_midnight - now).total_seconds()
            log.info(f"Day complete. Sleeping {wait_sec/3600:.1f}h "
                     f"until {next_midnight.strftime('%Y-%m-%d %H:%M')} UTC")
            while wait_sec > 0:
                chunk = min(wait_sec, 60)
                time.sleep(chunk)
                wait_sec -= chunk

            new_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            log.info(f"Waking up for new trading day: {new_day}")
            for mgr in managers:
                mgr.reset_for_new_day(new_day)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        graceful_shutdown(managers, conn, log,
                          notifier=guards.notifier, reason="exit")


if __name__ == "__main__":
    main()
