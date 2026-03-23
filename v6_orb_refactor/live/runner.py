"""LiveRunner - Orchestrates live execution of the ORB strategy.

Responsibilities: polling loop, state persistence, daily reset, range
calculation, trade CSV logging, guardrails, signal handling, heartbeat.
"""
import csv
import json
import logging
import signal as signal_mod
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..config.config import StrategyConfig, LiveConfig
from ..core.market_event import Fill, Tick, RangeInfo
from ..strategy.orb_strategy import ORBStrategy, StrategyState


class LiveRunner:
    """
    Orchestrates the live execution loop.
    Connects strategy, market context, and execution engine.
    Handles state persistence, trade logging, and guardrails transparently.
    """

    def __init__(self, strategy: ORBStrategy, context, execution,
                 connection, config: LiveConfig,
                 guardrails=None,
                 logger: Optional[logging.Logger] = None):
        self.strategy = strategy
        self.context = context
        self.execution = execution
        self.conn = connection
        self.cfg = config
        self.scfg = config.strategy
        self.guardrails = guardrails
        self.logger = logger or logging.getLogger(__name__)

        # Paths
        self.state_file = Path(config.paths.state_dir) / (
            f"orb_{self.scfg.instrument.lower()}_state.json")
        self.trade_log_path = Path(config.paths.trade_log)

        # Ensure state dir exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Track current day
        self.current_date: Optional[str] = None

        # MFE/MAE tracking
        self._mfe: float = 0.0
        self._mae: float = 0.0

        # Heartbeat timing
        self._last_heartbeat: float = 0.0

        # Account mode for trade logging
        self._account_mode = 'live' if config.ibkr.port == 4001 else 'paper'

    # ── Main loop ────────────────────────────────────────────────────

    def start(self):
        """Main entry point. Runs the daily loop until shutdown."""
        self.logger.info("LiveRunner starting")
        self._load_state()
        self._install_signal_handlers()

        try:
            while True:
                self._run_day()

                # Sleep until next UTC midnight + 10 min
                now = datetime.now(tz=timezone.utc)
                next_midnight = (now + timedelta(days=1)).replace(
                    hour=0, minute=10, second=0, microsecond=0)
                wait_sec = (next_midnight - now).total_seconds()
                self.logger.info(
                    f"Day complete. Sleeping {wait_sec/3600:.1f}h "
                    f"until {next_midnight.strftime('%Y-%m-%d %H:%M')} UTC")
                while wait_sec > 0:
                    chunk = min(wait_sec, 60)
                    time.sleep(chunk)
                    wait_sec -= chunk

                new_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
                self.logger.info(f"Waking up for new trading day: {new_day}")

        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
        finally:
            self._cleanup("exit")

    def _run_day(self):
        """Run one trading day."""
        now = datetime.now(tz=timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        # Daily reset
        if today_str != self.current_date:
            self._reset_daily_state(today_str)

        # Skip weekends
        trade_dt = datetime.strptime(today_str, "%Y-%m-%d")
        if trade_dt.weekday() >= 5:
            self.logger.info(f"Weekend ({today_str}) -- no trading")
            return

        # Skip configured weekdays
        if trade_dt.weekday() in self.scfg.skip_weekdays:
            day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][trade_dt.weekday()]
            self.logger.info(f"{day_name} skipped ({today_str})")
            self.strategy.state = StrategyState.DONE_TODAY
            self._save_state()
            return

        # Check if daily loss limit breached
        if self.guardrails and self.guardrails.is_breached:
            self.logger.error("Daily loss limit breached — no trading today")
            self.strategy.state = StrategyState.DONE_TODAY
            self._save_state()
            return

        # On restart: if DONE_TODAY but still in trade window and gap
        # metrics not yet computed (fresh context), re-evaluate the day.
        if (self.strategy.state == StrategyState.DONE_TODAY
                and now.hour < self.scfg.trade_end_hour
                and self.context._current_gap_metrics is None
                and self.context.daily_range is None):
            self.logger.info(
                "Overriding stale DONE_TODAY — still in trade window, "
                "re-evaluating with fresh context")
            self.strategy.state = StrategyState.IDLE

        self.logger.info(
            f"Starting ORB day | {self.scfg.instrument} | "
            f"dry_run={self.cfg.dry_run}")

        # Main polling loop for the day
        while self.strategy.state != StrategyState.DONE_TODAY:
            now = datetime.now(tz=timezone.utc)

            if not self.conn.ensure_connected():
                self.logger.warning("Connection unavailable — sleeping 30s")
                time.sleep(30)
                continue

            try:
                self._tick(now)
            except Exception as e:
                self.logger.error(f"Error in tick: {e}", exc_info=True)
                if self.guardrails:
                    self.guardrails.on_error(str(e), self.scfg.instrument)

            # Check if trade window has passed without action
            if (now.hour >= self.scfg.trade_end_hour
                    and self.strategy.state in (
                        StrategyState.IDLE, StrategyState.RANGE_READY)):
                self.logger.info("Window closed, no trade taken")
                self.strategy.state = StrategyState.DONE_TODAY
                self._save_state()

            # Heartbeat
            self._heartbeat(now)

            self.conn.sleep(self.cfg.poll_interval)

        self.logger.info("Done for today")

    def _tick(self, now: datetime):
        """One iteration of the polling loop."""
        # Calculate range at range_end_hour
        if (now.hour >= self.scfg.range_end_hour
                and self.strategy.state == StrategyState.IDLE
                and self.context.daily_range is None):
            self._calculate_and_set_range(now)

        # Calculate gap metrics after gap period completes (gap_end_hour)
        # Must be AFTER range is set but BEFORE trade window opens
        if (self.scfg.gap_filter_enabled
                and now.hour >= self.scfg.gap_end_hour
                and self.context.daily_range is not None
                and self.context._current_gap_metrics is None):
            self._calculate_and_inject_gap_metrics(
                now, self.context.daily_range)

        # Check fills from execution engine
        if self.execution.check_fills():
            self._save_state()

        # Create synthetic tick from streaming data
        tick = self._get_current_tick(now)
        if tick:
            # Update MFE/MAE if in trade
            if self.strategy.state == StrategyState.IN_TRADE:
                self._update_mfe_mae(tick)

            # Feed tick to strategy
            self.strategy.on_tick(tick, self.context, self.execution)
            self._save_state()

    # ── Range calculation ────────────────────────────────────────────

    def _calculate_and_set_range(self, now: datetime):
        """Calculate Asian range and set it in the market context."""
        self.logger.info(
            f"Calculating Asian range "
            f"({self.scfg.range_start_hour}-{self.scfg.range_end_hour} UTC)")

        rng = self.context.calculate_daily_range(
            self.scfg.range_start_hour, self.scfg.range_end_hour)

        if rng:
            self.context.set_daily_range(rng, now)
        else:
            self.logger.warning("Failed to calculate Asian range")

    def _calculate_and_inject_gap_metrics(self, now: datetime,
                                          daily_range: RangeInfo):
        """Fetch gap period bars from IBKR and inject metrics into context."""
        cfg = self.scfg
        if not cfg.gap_filter_enabled:
            return

        overnight_range = daily_range.size if daily_range else 0.0
        gap_vol, gap_range = self.context.calculate_gap_metrics_from_ibkr(
            cfg.gap_start_hour, cfg.gap_end_hour, overnight_range)

        self.context.inject_gap_data(
            now.date(), gap_vol, gap_range,
            cfg.gap_vol_percentile, cfg.gap_range_percentile,
            cfg.gap_rolling_days)

    # ── Tick construction ────────────────────────────────────────────

    def _get_current_tick(self, now: datetime) -> Optional[Tick]:
        """Create a Tick from current streaming data."""
        if self.context._last_bid and self.context._last_ask:
            return Tick(
                timestamp=now,
                bid=self.context._last_bid,
                ask=self.context._last_ask,
            )
        return None

    # ── Fill callback ────────────────────────────────────────────────

    def on_fill(self, fill: Fill):
        """Callback from execution engine when a fill occurs."""
        self.logger.info(
            f"Fill: {fill.reason} {fill.direction} @ {fill.price}")

        # Forward to strategy
        self.strategy.on_fill(fill, self.context, self.execution)

        # Log trade CSV on exit fills
        if fill.reason in ("SL", "TP", "BE", "MARKET", "CLOSED",
                           "TIME_EXIT"):
            self._log_trade(fill)

        # Guardrails P&L tracking on exit fills
        if (self.guardrails
                and fill.reason in ("SL", "TP", "BE", "MARKET", "CLOSED",
                                    "TIME_EXIT")):
            pnl = self._calc_trade_pnl(fill.price)
            pnl_total = round(
                pnl * self.scfg.qty * self.scfg.point_value, 2)
            self.guardrails.on_trade_closed(
                pnl_total, self.scfg.instrument,
                self.strategy.direction or "?", fill.reason,
                self.strategy.entry_price, fill.price)

        # Reset MFE/MAE on entry
        if fill.reason == "ENTRY":
            self._mfe = 0.0
            self._mae = 0.0

        self._save_state()

    def _calc_trade_pnl(self, exit_price: float) -> float:
        s = self.strategy
        if s.direction == "LONG":
            return exit_price - s.entry_price
        else:
            return s.entry_price - exit_price

    # ── MFE/MAE tracking ────────────────────────────────────────────

    def _update_mfe_mae(self, tick: Tick):
        s = self.strategy
        if not s.entry_price or not s.direction:
            return
        price = tick.mid
        if s.direction == "LONG":
            favor = price - s.entry_price
            adverse = s.entry_price - price
        else:
            favor = s.entry_price - price
            adverse = price - s.entry_price
        if favor > self._mfe:
            self._mfe = round(favor, self.scfg.price_decimals)
        if adverse > self._mae:
            self._mae = round(adverse, self.scfg.price_decimals)

    # ── Trade CSV logging ────────────────────────────────────────────

    def _log_trade(self, fill: Fill):
        """Append a trade record to CSV."""
        s = self.strategy
        d = self.scfg.price_decimals
        pnl = self._calc_trade_pnl(fill.price)
        pnl_total = round(pnl * self.scfg.qty * self.scfg.point_value, 2)
        hold_m = 0
        if s.entry_time:
            hold_m = int((fill.timestamp - s.entry_time).total_seconds() / 60)

        row = {
            'timestamp': fill.timestamp.isoformat(),
            'date': self.current_date,
            'instrument': self.scfg.instrument,
            'direction': s.direction,
            'entry': s.entry_price,
            'exit': fill.price,
            'sl': s.sl_price,
            'tp': s.tp_price,
            'range_high': s.range.high if s.range else '',
            'range_low': s.range.low if s.range else '',
            'range_size': s.range.size if s.range else '',
            'qty': self.scfg.qty,
            'pnl_per_unit': round(pnl, d),
            'pnl_total': pnl_total,
            'result': fill.reason,
            'hold_minutes': hold_m,
            'mfe': self._mfe,
            'mae': self._mae,
            'account_mode': self._account_mode,
        }

        try:
            path = self.trade_log_path
            write_header = not path.exists()
            with open(path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
            self.logger.info(
                f"Trade logged: {s.direction} {fill.reason} "
                f"PnL=${pnl_total:+.2f}")
        except Exception as e:
            self.logger.error(f"Trade log failed: {e}")

    # ── Heartbeat ────────────────────────────────────────────────────

    def _heartbeat(self, now: datetime):
        """Periodic status logging + velocity CSV + account snapshot."""
        now_ts = now.timestamp()
        if now_ts - self._last_heartbeat < 60:
            return
        self._last_heartbeat = now_ts

        # Status line
        s = self.strategy
        vel = self.context.get_velocity(
            self.scfg.velocity_lookback_minutes, now)
        price = self.context.get_current_price(now)
        price_str = f"{price:.{self.scfg.price_decimals}f}" if price else "N/A"
        self.logger.info(
            f"[STATUS] {self.scfg.instrument} | state={s.state.value} | "
            f"price={price_str} | vel={vel:.0f}")

        # Heartbeat check connection
        self.conn.heartbeat()

    # ── Daily reset ──────────────────────────────────────────────────

    def _reset_daily_state(self, today_str: str):
        """Reset everything for a new trading day."""
        self.logger.info(f"New trading day: {today_str}")
        self.current_date = today_str

        # Cancel any lingering orders from previous day
        if self.strategy.state in (
                StrategyState.ORDERS_PLACED, StrategyState.IN_TRADE):
            self.logger.info("Canceling previous day's orders/position")
            self.execution.cancel_orb_brackets()
            if self.execution.has_position():
                self.execution.close_at_market()

        # Reset strategy
        self.strategy.reset_for_new_day()

        # Reset execution engine trade date
        self.execution.set_trade_date(today_str)

        # Clear daily range and gap metrics cache
        self.context.daily_range = None
        self.context.daily_range_date = None
        self.context._current_gap_metrics = None
        self.context._gap_metrics_date = None

        # Reset MFE/MAE
        self._mfe = 0.0
        self._mae = 0.0

        # Guardrails
        if self.guardrails:
            self.guardrails.on_new_day(today_str)

        self._save_state()

    # ── State Persistence ────────────────────────────────────────────

    def _save_state(self):
        """Save strategy + executor state to JSON (atomic write)."""
        try:
            snapshot = self.strategy.get_state_snapshot()
            snapshot["current_date"] = self.current_date
            snapshot["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
            snapshot["mfe"] = self._mfe
            snapshot["mae"] = self._mae
            snapshot["order_ids"] = self.execution.get_order_ids()

            tmp = self.state_file.with_suffix('.tmp')
            tmp.write_text(
                json.dumps(snapshot, indent=2, default=str),
                encoding='utf-8')
            tmp.replace(self.state_file)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    def _load_state(self):
        """Load strategy + executor state from JSON."""
        if not self.state_file.exists():
            self.logger.info("No saved state found, starting fresh")
            return

        try:
            data = json.loads(self.state_file.read_text(encoding='utf-8'))
            self.current_date = data.get("current_date")
            self.strategy.restore_state(data)
            self._mfe = data.get("mfe", 0.0)
            self._mae = data.get("mae", 0.0)

            order_ids = data.get("order_ids")
            if order_ids:
                self.execution.restore_order_ids(order_ids)

            self.logger.info(
                f"State restored: {self.strategy.state.value}, "
                f"date={self.current_date}")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            self.logger.info("Starting fresh due to state load failure")

    # ── Signal handling ──────────────────────────────────────────────

    def _install_signal_handlers(self):
        """Install SIGINT/SIGTERM handlers for graceful shutdown."""
        def handler(signum, frame):
            self.logger.info(f"Signal {signum} received, shutting down")
            self._cleanup("signal")
            sys.exit(0)

        signal_mod.signal(signal_mod.SIGINT, handler)
        signal_mod.signal(signal_mod.SIGTERM, handler)

    # ── Cleanup ──────────────────────────────────────────────────────

    def _cleanup(self, reason: str = "exit"):
        """Graceful shutdown: cancel orders, save state, disconnect."""
        self.logger.info(f"LiveRunner cleanup ({reason})")

        # Cancel resting orders
        if self.strategy.state == StrategyState.ORDERS_PLACED:
            self.execution.cancel_orb_brackets()

        # Guardrails shutdown
        if self.guardrails and self.conn.contract:
            self.guardrails.graceful_shutdown(
                self.conn.ib, self.conn.contract,
                self.scfg.instrument, reason)

        # Save final state
        self._save_state()

        # Disconnect market data
        try:
            self.context.disconnect()
        except Exception:
            pass

        # Disconnect IBKR
        self.conn.disconnect()
