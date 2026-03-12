"""
V8 Confirmed Rebreak -- Live Trading Script

Connects to IBKR via ib_insync, streams 1-min bars, feeds them into
the LiveEngine which uses the SAME PatternDetector as backtest.

Bar sourcing:
  1. Seed rolling buffer with recent historical 1-min bars from IBKR
  2. Stream real-time updates via reqMktData
  3. Aggregate price updates into 1-min bars with buy/sell classification
     (uptick = buy, downtick = sell)

Usage:
  python -m v8_confirmed_rebreak.live.run_live --dry-run
  python -m v8_confirmed_rebreak.live.run_live --port 4002
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import signal as signal_mod
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from v8_confirmed_rebreak.live.live_config import LiveConfig
from v8_confirmed_rebreak.live.live_engine import LiveEngine, LiveBar


# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("v8_live")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    log.addHandler(sh)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fh = logging.FileHandler(str(log_dir / f"v8_live_{ts}.log"))
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)

    for lib in ("ib_insync.wrapper", "ib_insync.client", "ib_insync"):
        logging.getLogger(lib).setLevel(logging.CRITICAL)

    return log


# ── Trade CSV Logger ─────────────────────────────────────────────────────────

TRADE_FIELDS = [
    'timestamp', 'direction', 'entry_price', 'exit_price', 'sl_price',
    'pivot_price', 'quantity', 'pnl', 'exit_reason', 'buy_ratio',
    'gap', 'hold_bars',
]


def log_trade(trade: dict, path: Path):
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if is_new:
            writer.writeheader()
        row = {k: trade.get(k, '') for k in TRADE_FIELDS}
        writer.writerow(row)


# ── IBKR Connection ──────────────────────────────────────────────────────────

_IB_CRITICAL_ERRORS = {
    504: "Not connected",
    502: "Couldn't connect to TWS",
    1100: "Connectivity lost",
    2110: "TWS-server connection broken",
}
_IB_WARNING_CODES = {
    2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158,
    2119, 354, 300, 10168, 10167,
}


class IBKRConnection:
    """IBKR connection manager for V8 live trading."""

    def __init__(self, cfg: LiveConfig, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self.ib = None
        self._connected = False
        self._last_heartbeat = 0.0
        self.contract = None
        self.price_ticker = None

    @property
    def connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()

    def connect(self) -> bool:
        from ib_insync import IB
        for attempt in range(1, 4):
            try:
                if self.ib is not None:
                    try:
                        self.ib.disconnect()
                    except Exception:
                        pass

                self.ib = IB()
                self.ib.errorEvent += self._on_error
                self.ib.disconnectedEvent += self._on_disconnect
                self.ib.connect(self.cfg.ibkr_host, self.cfg.ibkr_port,
                                clientId=self.cfg.ibkr_client_id, timeout=20)

                if not self.ib.isConnected():
                    raise ConnectionError("isConnected=False after connect")

                self._connected = True
                self._last_heartbeat = time.time()
                self.log.info(f"Connected to IBKR {self.cfg.ibkr_host}:"
                              f"{self.cfg.ibkr_port}")
                return True

            except Exception as e:
                self.log.warning(f"Connect attempt {attempt}/3 failed: {e}")
                if attempt < 3:
                    time.sleep(5 * attempt)

        self.log.error("Failed to connect after 3 attempts")
        return False

    def ensure_connected(self) -> bool:
        if self.connected:
            now = time.time()
            if now - self._last_heartbeat > 30:
                try:
                    self.ib.reqCurrentTime()
                    self._last_heartbeat = now
                except Exception:
                    self._connected = False
            if self._connected:
                return True
        self.log.info("Reconnecting...")
        ok = self.connect()
        if ok:
            self._qualify_contract()
            self._start_price_stream()
        return ok

    def _qualify_contract(self):
        from ib_insync import Contract
        contract = Contract(
            symbol=self.cfg.symbol,
            secType=self.cfg.sec_type,
            exchange=self.cfg.exchange,
            currency=self.cfg.currency,
        )
        qualified = self.ib.qualifyContracts(contract)
        if qualified:
            self.contract = contract
            self.log.info(f"Contract qualified: {contract}")
        else:
            self.log.error(f"Failed to qualify {self.cfg.symbol}")

    def _start_price_stream(self):
        if self.contract is None:
            return
        self.ib.reqMarketDataType(3)
        self.price_ticker = self.ib.reqMktData(
            self.contract, '', snapshot=False, regulatorySnapshot=False)
        self.ib.sleep(2)
        self.log.info("Price stream started")

    def get_mid_price(self) -> Optional[float]:
        if self.price_ticker is None:
            return None
        bid, ask = self.price_ticker.bid, self.price_ticker.ask
        if (isinstance(bid, float) and not math.isnan(bid) and bid > 0
                and isinstance(ask, float) and not math.isnan(ask) and ask > 0):
            return (bid + ask) / 2
        if isinstance(self.price_ticker.close, float) and not math.isnan(self.price_ticker.close):
            return self.price_ticker.close
        return None

    def fetch_historical_bars(self, duration: str = "1 D",
                              bar_size: str = "1 min") -> pd.DataFrame:
        if not self.ensure_connected() or self.contract is None:
            return pd.DataFrame()
        try:
            bars = self.ib.reqHistoricalData(
                self.contract, endDateTime="",
                durationStr=duration, barSizeSetting=bar_size,
                whatToShow="MIDPOINT", useRTH=False, formatDate=2)
        except Exception as e:
            self.log.error(f"Historical data request failed: {e}")
            return pd.DataFrame()
        if not bars:
            self.log.warning("No historical bars returned")
            return pd.DataFrame()
        from ib_insync import util
        df = util.df(bars)
        self.log.info(f"Fetched {len(df)} historical bars")
        return df

    def submit_market_order(self, direction: str, quantity: float):
        from ib_insync import MarketOrder
        action = "BUY" if direction == "long" else "SELL"
        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(self.contract, order)
        self.log.info(f"ORDER SUBMITTED: {action} {quantity} @ MARKET")
        return trade

    def submit_stop_order(self, direction: str, quantity: float, stop_price: float):
        from ib_insync import StopOrder
        action = "SELL" if direction == "long" else "BUY"
        order = StopOrder(action, quantity, stop_price)
        trade = self.ib.placeOrder(self.contract, order)
        self.log.info(f"SL ORDER: {action} {quantity} @ {stop_price:.2f}")
        return trade

    def close_position(self, direction: str, quantity: float):
        action = "SELL" if direction == "long" else "BUY"
        from ib_insync import MarketOrder
        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(self.contract, order)
        self.log.info(f"CLOSE: {action} {quantity} @ MARKET")
        return trade

    def cancel_all_orders(self):
        open_orders = self.ib.openOrders()
        for order in open_orders:
            try:
                self.ib.cancelOrder(order)
            except Exception:
                pass

    def sleep(self, seconds: float):
        if self.connected:
            try:
                self.ib.sleep(seconds)
            except Exception:
                time.sleep(seconds)
        else:
            time.sleep(seconds)

    def disconnect(self):
        if self.price_ticker and self.ib:
            try:
                self.ib.cancelMktData(self.contract)
            except Exception:
                pass
        if self.ib:
            try:
                self.ib.disconnect()
            except Exception:
                pass

    def _on_disconnect(self):
        self._connected = False
        self.log.warning("IBKR disconnected")

    def _on_error(self, reqId, errorCode, errorString, contract):
        if errorCode in _IB_WARNING_CODES:
            return
        if errorCode in _IB_CRITICAL_ERRORS:
            self._connected = False
            self.log.error(f"IB critical {errorCode}: {errorString}")
        else:
            if errorCode not in (162,):
                self.log.warning(f"IB error {errorCode}: {errorString}")


# ── Real-time Bar Aggregator ────────────────────────────────────────────────

class BarAggregator:
    """Aggregates streaming price updates into 1-min bars.

    Uses price direction (uptick/downtick) as proxy for buy/sell classification.
    """

    def __init__(self, log: logging.Logger):
        self.log = log
        self.current_bar_start: Optional[datetime] = None
        self.bar_open = 0.0
        self.bar_high = 0.0
        self.bar_low = 0.0
        self.bar_close = 0.0
        self.bar_buy_vol = 0.0
        self.bar_sell_vol = 0.0
        self.bar_tick_count = 0
        self.last_price = 0.0

    def on_price(self, price: float, now: datetime) -> Optional[LiveBar]:
        """Process a price update. Returns completed LiveBar if minute boundary crossed."""
        bar_start = now.replace(second=0, microsecond=0)
        completed_bar = None

        if self.current_bar_start is not None and bar_start > self.current_bar_start:
            if self.bar_tick_count > 0:
                completed_bar = LiveBar(
                    timestamp=self.current_bar_start,
                    open=self.bar_open,
                    high=self.bar_high,
                    low=self.bar_low,
                    close=self.bar_close,
                    buy_volume=self.bar_buy_vol,
                    sell_volume=self.bar_sell_vol,
                    tick_count=self.bar_tick_count,
                )
            self.current_bar_start = bar_start
            self.bar_open = price
            self.bar_high = price
            self.bar_low = price
            self.bar_close = price
            self.bar_buy_vol = 0.0
            self.bar_sell_vol = 0.0
            self.bar_tick_count = 0

        elif self.current_bar_start is None:
            self.current_bar_start = bar_start
            self.bar_open = price
            self.bar_high = price
            self.bar_low = price
            self.bar_close = price

        self.bar_high = max(self.bar_high, price)
        self.bar_low = min(self.bar_low, price)
        self.bar_close = price
        self.bar_tick_count += 1

        if self.last_price > 0:
            if price > self.last_price:
                self.bar_buy_vol += 1
            elif price < self.last_price:
                self.bar_sell_vol += 1
            else:
                self.bar_buy_vol += 0.5
                self.bar_sell_vol += 0.5
        self.last_price = price

        return completed_bar


# ── Main Live Loop ──────────────────────────────────────────────────────────

class V8LiveTrader:
    """Main live trading orchestrator using V8 deep modules."""

    def __init__(self, live_cfg: LiveConfig, log: logging.Logger):
        self.live_cfg = live_cfg
        self.log = log

        self.conn = IBKRConnection(live_cfg, log)
        self.engine = LiveEngine(live_cfg, log)
        self.aggregator = BarAggregator(log)
        self.sl_order = None
        self._shutdown = False

        # State persistence
        self.state_dir = ROOT / "v8_confirmed_rebreak" / "live" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = ROOT / "v8_confirmed_rebreak" / "live" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.trade_log_path = self.log_dir / "trades.csv"

    def seed_buffer(self):
        """Load historical bars to seed the rolling buffer."""
        needed = 2 * self.live_cfg.pivot_window + 50
        hours_needed = max(needed // 60 + 1, 8)
        duration = f"{hours_needed * 3600} S"

        self.log.info(f"Seeding buffer with ~{needed} historical 1-min bars...")
        df = self.conn.fetch_historical_bars(duration=duration, bar_size="1 min")

        if df.empty:
            self.log.warning("No historical bars -- buffer starts empty")
            return 0

        count = 0
        for _, row in df.iterrows():
            ts = pd.Timestamp(row['date'])
            if ts.tzinfo is None:
                ts = ts.tz_localize('UTC')
            bar = LiveBar(
                timestamp=ts.to_pydatetime(),
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                buy_volume=row.get('volume', 0) / 2,
                sell_volume=row.get('volume', 0) / 2,
                tick_count=max(int(row.get('volume', 50)), 50),
            )
            self.engine.add_bar(bar)
            count += 1

        self.log.info(f"Buffer seeded with {count} bars "
                      f"(need {needed} for pivot computation)")
        return count

    def run(self):
        """Main trading loop."""
        def on_signal(sig, frame):
            self.log.info(f"Signal {sig} received -- shutting down")
            self._shutdown = True
        signal_mod.signal(signal_mod.SIGINT, on_signal)
        signal_mod.signal(signal_mod.SIGTERM, on_signal)

        if not self.conn.connect():
            self.log.error("Cannot connect to IBKR -- exiting")
            return

        self.conn._qualify_contract()
        if self.conn.contract is None:
            self.log.error("Cannot qualify contract -- exiting")
            self.conn.disconnect()
            return

        self.conn._start_price_stream()
        seeded = self.seed_buffer()
        self.log.info(f"Engine ready. Buffer: {len(self.engine.buffer)} bars. "
                      f"Dry-run: {self.live_cfg.dry_run}")

        poll_interval = 1.0
        last_bar_log = 0

        while not self._shutdown:
            if not self.conn.ensure_connected():
                self.log.error("Connection lost -- waiting 10s")
                time.sleep(10)
                continue

            price = self.conn.get_mid_price()
            if price is None:
                self.conn.sleep(poll_interval)
                continue

            now = datetime.now(timezone.utc)
            completed_bar = self.aggregator.on_price(price, now)

            if completed_bar is not None:
                self.engine.add_bar(completed_bar)

                # Safety check
                safety = self.engine.safety_check()
                if safety:
                    self.log.warning(f"SAFETY LIMIT: {safety}")
                    self.conn.sleep(poll_interval)
                    continue

                result = self.engine.on_bar()

                bars_in_buf = len(self.engine.buffer)
                if time.time() - last_bar_log > 300:
                    self.log.info(f"Buffer: {bars_in_buf} bars, "
                                  f"price={price:.2f}, "
                                  f"daily_trades={self.engine.daily_trades}")
                    last_bar_log = time.time()

                if result is not None:
                    self._handle_signal(result)

            self.conn.sleep(poll_interval)

        self.log.info("Shutting down...")
        self._cleanup()
        self.conn.disconnect()
        self.log.info("V8 live trader stopped.")

    def _handle_signal(self, result: dict):
        """Handle engine signal (entry or exit)."""
        action = result.get('action')

        if action == 'exit':
            self._handle_exit(result)
        elif action == 'enter':
            self._handle_entry(result)

    def _handle_entry(self, signal: dict):
        """Execute entry signal."""
        direction = signal['direction']
        self.log.info(f"SIGNAL: {direction.upper()} | "
                      f"pivot={signal['pivot_price']:.2f} "
                      f"buy_ratio={signal['buy_ratio']:.3f} "
                      f"gap={signal['gap']}")

        if self.live_cfg.dry_run:
            self.log.info("[DRY RUN] Would enter trade -- skipping order")
            return

        entry_trade = self.conn.submit_market_order(
            direction, self.live_cfg.quantity)
        self.conn.sleep(3)

        # Submit SL order
        sl_price = signal.get('sl_price', 0)
        if sl_price > 0:
            self.sl_order = self.conn.submit_stop_order(
                direction, self.live_cfg.quantity, sl_price)

    def _handle_exit(self, exit_info: dict):
        """Execute exit."""
        reason = exit_info.get('reason', 'UNKNOWN')
        direction = exit_info.get('direction', '')
        pnl = exit_info.get('pnl', 0)

        self.log.info(f"EXIT: reason={reason} dir={direction} PnL=${pnl:+.2f}")

        # Log trade to CSV
        log_row = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'direction': direction,
            'entry_price': f"{exit_info.get('entry_price', 0):.2f}",
            'exit_price': f"{exit_info.get('exit_price', 0):.2f}",
            'sl_price': f"{exit_info.get('sl_price', 0):.2f}" if 'sl_price' in exit_info else '',
            'pivot_price': f"{exit_info.get('pivot_price', 0):.2f}",
            'quantity': self.live_cfg.quantity,
            'pnl': f"{pnl:.2f}",
            'exit_reason': reason,
            'buy_ratio': f"{exit_info.get('buy_ratio', 0):.3f}",
            'gap': exit_info.get('gap', 0),
            'hold_bars': exit_info.get('hold_bars', 0),
        }
        log_trade(log_row, self.trade_log_path)

        if self.live_cfg.dry_run:
            self.log.info("[DRY RUN] Would close position -- skipping")
            return

        # Cancel SL order
        if self.sl_order:
            try:
                self.conn.ib.cancelOrder(self.sl_order.order)
            except Exception:
                pass
            self.sl_order = None

        # Only close at market if not SL (SL order handles itself)
        if reason != 'CATASTROPHE_SL':
            self.conn.close_position(direction, self.live_cfg.quantity)

    def _cleanup(self):
        """Clean up on shutdown."""
        if self.engine.in_trade:
            self.log.warning("Open trade at shutdown -- closing at market")
            if not self.live_cfg.dry_run:
                self.conn.close_position(
                    self.engine.trade_direction, self.live_cfg.quantity)
                if self.sl_order:
                    try:
                        self.conn.ib.cancelOrder(self.sl_order.order)
                    except Exception:
                        pass


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V8 Confirmed Rebreak -- Live")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run without submitting orders")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--client-id", type=int, default=99)
    parser.add_argument("--qty", type=float, default=1.0)
    parser.add_argument("--pw", type=int, default=60)
    parser.add_argument("--confirm", type=int, default=3)
    parser.add_argument("--max-hold", type=int, default=60)
    parser.add_argument("--sl", type=float, default=10.0)
    parser.add_argument("--min-ticks", type=int, default=50)
    args = parser.parse_args()

    live_cfg = LiveConfig(
        ibkr_host=args.host,
        ibkr_port=args.port,
        ibkr_client_id=args.client_id,
        symbol="XAUUSD",
        sec_type="CMDTY",
        exchange="SMART",
        currency="USD",
        quantity=args.qty,
        pivot_window=args.pw,
        confirm_bars=args.confirm,
        max_hold_bars=args.max_hold,
        sl_atr_multiple=args.sl,
        min_bar_ticks=args.min_ticks,
        dry_run=args.dry_run,
    )
    live_cfg.validate()

    log_dir = ROOT / "v8_confirmed_rebreak" / "live" / "logs"
    log = setup_logging(log_dir)

    log.info("=" * 60)
    log.info("V8 Confirmed Rebreak -- Live Trader")
    log.info(f"  Symbol:    {live_cfg.symbol}")
    log.info(f"  Dry-run:   {live_cfg.dry_run}")
    log.info(f"  Qty:       {live_cfg.quantity}")
    log.info(f"  PW={live_cfg.pivot_window} Confirm={live_cfg.confirm_bars} "
             f"Hold={live_cfg.max_hold_bars} SL={live_cfg.sl_atr_multiple}x")
    log.info("=" * 60)

    trader = V8LiveTrader(live_cfg, log)
    trader.run()


if __name__ == "__main__":
    main()
