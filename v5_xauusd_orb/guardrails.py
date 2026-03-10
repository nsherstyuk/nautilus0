"""
guardrails.py -- Safety guardrails for live trading.

Provides:
  1. Daily loss limit   - halt trading if realized losses exceed threshold
  2. Max position check - prevent duplicate positions per instrument
  3. Orphan detection   - find/cancel stale orders/positions on startup
  4. Notifications      - email alerts on fill, error, startup, shutdown
  5. Graceful shutdown  - cancel all pending orders cleanly

Usage:
  Instantiated once in orb_multi_live.py main() and wired into the
  existing flow via check methods.
"""
from __future__ import annotations

import csv
import logging
import smtplib
import traceback
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from v5_xauusd_orb.config import Config, GuardrailsConfig


# ── Notifier ──────────────────────────────────────────────────────────────────

class Notifier:
    """Send email notifications for trading events."""

    def __init__(self, cfg: GuardrailsConfig, log: logging.Logger):
        self.cfg = cfg.notifications
        self.log = log
        self._enabled = self.cfg.enabled and bool(self.cfg.smtp_user)

    def send(self, subject: str, body: str, event_type: str = ""):
        """Send an email if notifications are enabled and event type is allowed."""
        if not self._enabled:
            return

        # Check event-specific toggle
        if event_type:
            toggle = getattr(self.cfg, f"notify_on_{event_type}", True)
            if not toggle:
                return

        try:
            msg = MIMEText(body, "plain")
            msg["Subject"] = f"[ORB Trading] {subject}"
            msg["From"] = self.cfg.from_addr or self.cfg.smtp_user
            msg["To"] = self.cfg.to_addr

            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port,
                              timeout=10) as server:
                server.starttls()
                server.login(self.cfg.smtp_user, self.cfg.smtp_password)
                server.send_message(msg)

            self.log.info(f"[NOTIFY] Email sent: {subject}")
        except Exception as e:
            self.log.warning(f"[NOTIFY] Email failed: {e}")


# ── Daily Loss Tracker ────────────────────────────────────────────────────────

class DailyLossTracker:
    """Track realized P&L for the current trading day."""

    def __init__(self, limit_usd: float, log: logging.Logger):
        self.limit = limit_usd
        self.log = log
        self._today: str = ""
        self._realized_pnl: float = 0.0
        self._halted: bool = False

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    def reset_for_new_day(self, today_str: str):
        self._today = today_str
        self._realized_pnl = 0.0
        self._halted = False

    def record_trade(self, pnl_total: float, instrument: str):
        """Record a completed trade's P&L. Returns True if loss limit hit."""
        self._realized_pnl += pnl_total
        self.log.info(f"[GUARDRAIL] Daily P&L after {instrument}: "
                      f"${self._realized_pnl:+.2f} "
                      f"(limit: -${self.limit:.2f})")

        if self.limit > 0 and self._realized_pnl <= -self.limit:
            self._halted = True
            self.log.warning(
                f"[GUARDRAIL] DAILY LOSS LIMIT HIT: ${self._realized_pnl:+.2f} "
                f"exceeds -${self.limit:.2f}. Halting new trades.")
            return True
        return False

    def load_from_trade_logs(self, log_dir: str, today_str: str):
        """Load today's realized P&L from existing trade CSV files."""
        self._today = today_str
        self._realized_pnl = 0.0
        self._halted = False

        log_path = Path(log_dir)
        for csv_file in log_path.glob("orb_*_trades.csv"):
            try:
                with open(csv_file) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get('date') == today_str:
                            pnl = float(row.get('pnl_total', 0))
                            self._realized_pnl += pnl
            except Exception:
                pass

        if self._realized_pnl != 0:
            self.log.info(f"[GUARDRAIL] Loaded today's P&L from logs: "
                          f"${self._realized_pnl:+.2f}")

        if self.limit > 0 and self._realized_pnl <= -self.limit:
            self._halted = True
            self.log.warning(
                f"[GUARDRAIL] DAILY LOSS LIMIT already exceeded on restart: "
                f"${self._realized_pnl:+.2f}")


# ── Position Guard ────────────────────────────────────────────────────────────

class PositionGuard:
    """Prevent duplicate positions and detect orphaned orders."""

    def __init__(self, cfg: GuardrailsConfig, log: logging.Logger):
        self.max_per_inst = cfg.max_positions_per_instrument
        self.cancel_orphaned = cfg.cancel_orphaned_orders
        self.close_orphaned = cfg.close_orphaned_positions
        self.log = log

    def check_max_positions(self, conn, inst_name: str) -> bool:
        """Return True if safe to trade (no duplicate positions detected).
        Return False if max positions exceeded."""
        if not conn.connected:
            return True  # can't check, allow by default

        contract = conn.contracts.get(inst_name)
        if contract is None:
            return True

        try:
            positions = conn.ib.positions()
            count = sum(
                1 for p in positions
                if p.contract.conId == contract.conId and abs(p.position) > 0
            )
            if count > self.max_per_inst:
                self.log.error(
                    f"[GUARDRAIL] {inst_name}: {count} positions detected "
                    f"(max={self.max_per_inst}). BLOCKING new orders.")
                return False
            if count > 0:
                self.log.debug(
                    f"[GUARDRAIL] {inst_name}: {count} existing position(s)")
        except Exception as e:
            self.log.warning(f"[GUARDRAIL] Position check failed: {e}")

        return True

    def scan_orphans(self, conn, active_managers: list) -> dict:
        """Scan for orphaned orders/positions not belonging to any active manager.

        Returns dict with 'orphaned_orders' and 'orphaned_positions' lists.
        """
        result = {'orphaned_orders': [], 'orphaned_positions': []}

        if not conn.connected:
            return result

        # Collect all known order IDs from active managers
        known_order_ids = set()
        known_con_ids = set()
        for mgr in active_managers:
            if mgr.state.buy_order_id:
                known_order_ids.add(mgr.state.buy_order_id)
            if mgr.state.sell_order_id:
                known_order_ids.add(mgr.state.sell_order_id)
            contract = conn.contracts.get(mgr.inst.name)
            if contract:
                known_con_ids.add(contract.conId)

        # Check for orphaned orders
        try:
            conn.ib.reqAllOpenOrders()
            conn.sleep(2)
            for trade in conn.ib.openTrades():
                oid = trade.order.orderId
                parent = trade.order.parentId
                if oid not in known_order_ids and parent not in known_order_ids:
                    result['orphaned_orders'].append(trade)
                    self.log.warning(
                        f"[GUARDRAIL] Orphaned order detected: "
                        f"id={oid} action={trade.order.action} "
                        f"type={trade.order.orderType} "
                        f"qty={trade.order.totalQuantity} "
                        f"contract={trade.contract.localSymbol}")
        except Exception as e:
            self.log.warning(f"[GUARDRAIL] Orphan order scan failed: {e}")

        # Check for orphaned positions
        try:
            for pos in conn.ib.positions():
                if abs(pos.position) > 0 and pos.contract.conId not in known_con_ids:
                    result['orphaned_positions'].append(pos)
                    self.log.warning(
                        f"[GUARDRAIL] Orphaned position detected: "
                        f"{pos.contract.localSymbol} "
                        f"qty={pos.position} avgCost={pos.avgCost:.2f}")
        except Exception as e:
            self.log.warning(f"[GUARDRAIL] Orphan position scan failed: {e}")

        return result

    def handle_orphans(self, conn, orphans: dict):
        """Cancel orphaned orders and optionally close orphaned positions."""
        for trade in orphans.get('orphaned_orders', []):
            if self.cancel_orphaned:
                try:
                    conn.ib.cancelOrder(trade.order)
                    conn.sleep(0.5)
                    self.log.info(
                        f"[GUARDRAIL] Cancelled orphaned order: "
                        f"id={trade.order.orderId}")
                except Exception as e:
                    self.log.error(
                        f"[GUARDRAIL] Failed to cancel orphan order "
                        f"{trade.order.orderId}: {e}")
            else:
                self.log.warning(
                    f"[GUARDRAIL] Orphaned order {trade.order.orderId} "
                    f"NOT cancelled (cancel_orphaned_orders=false)")

        for pos in orphans.get('orphaned_positions', []):
            if self.close_orphaned:
                try:
                    from ib_insync import MarketOrder
                    action = "SELL" if pos.position > 0 else "BUY"
                    order = MarketOrder(action, abs(pos.position))
                    conn.ib.placeOrder(pos.contract, order)
                    conn.sleep(3)
                    self.log.info(
                        f"[GUARDRAIL] Closed orphaned position: "
                        f"{pos.contract.localSymbol}")
                except Exception as e:
                    self.log.error(
                        f"[GUARDRAIL] Failed to close orphan position "
                        f"{pos.contract.localSymbol}: {e}")
            else:
                self.log.warning(
                    f"[GUARDRAIL] Orphaned position "
                    f"{pos.contract.localSymbol} NOT closed "
                    f"(close_orphaned_positions=false). "
                    f"Manual intervention required.")


# ── Graceful Shutdown ─────────────────────────────────────────────────────────

def graceful_shutdown(managers: list, conn, log: logging.Logger,
                      notifier: Notifier | None = None,
                      reason: str = "signal"):
    """Cancel all pending orders, close positions, disconnect cleanly."""
    log.info(f"[GUARDRAIL] Graceful shutdown initiated (reason: {reason})")

    for mgr in managers:
        try:
            state = mgr.state
            tag = mgr.tag

            if state.status == "ORDERS_PLACED":
                log.info(f"{tag} Cancelling pending orders...")
                mgr._cancel_and_close()
                state.status = "DONE_TODAY"
                state.save()

            elif state.status == "IN_TRADE":
                log.info(f"{tag} Closing open position...")
                mgr._cancel_and_close()
                # Record the forced exit via _record_exit (writes to trade CSV)
                now = datetime.now(tz=timezone.utc)
                price = conn.get_price(mgr.inst.name) if conn.connected else None
                if price and state.entry_price:
                    mgr._exit_fill_price = price
                    mgr._exit_fill_type = 'CLOSED'
                    mgr._record_exit(now, True)
                else:
                    state.status = "DONE_TODAY"
                    state.save()

        except Exception as e:
            log.error(f"{mgr.tag} Shutdown error: {e}")

    # Disconnect
    try:
        conn.disconnect()
        log.info("[GUARDRAIL] Disconnected from IBKR")
    except Exception:
        pass

    # Send notification
    if notifier:
        notifier.send(
            f"System Shutdown ({reason})",
            f"ORB trading system shut down.\n"
            f"Reason: {reason}\n"
            f"Time: {datetime.now(tz=timezone.utc).isoformat()}\n"
            f"Instruments: {', '.join(m.inst.name for m in managers)}",
            event_type="shutdown"
        )


# ── Composite Guardrails ─────────────────────────────────────────────────────

class Guardrails:
    """Unified guardrails interface. Created once, used throughout the session."""

    def __init__(self, cfg: Config, log: logging.Logger):
        gc = cfg.guardrails
        self.cfg = gc
        self.log = log

        self.notifier = Notifier(gc, log)
        self.loss_tracker = DailyLossTracker(gc.daily_loss_limit_usd, log)
        self.position_guard = PositionGuard(gc, log)

        log.info(f"[GUARDRAIL] Initialized: "
                 f"daily_loss_limit=${gc.daily_loss_limit_usd:.0f} | "
                 f"max_pos/inst={gc.max_positions_per_instrument} | "
                 f"cancel_orphans={gc.cancel_orphaned_orders} | "
                 f"notifications={'ON' if gc.notifications.enabled else 'OFF'}")

    def on_startup(self, conn, managers: list, today_str: str, log_dir: str):
        """Run all startup checks."""
        # Load today's P&L from trade logs
        self.loss_tracker.load_from_trade_logs(log_dir, today_str)

        # Scan for orphaned orders/positions
        orphans = self.position_guard.scan_orphans(conn, managers)
        n_orders = len(orphans['orphaned_orders'])
        n_positions = len(orphans['orphaned_positions'])

        if n_orders > 0 or n_positions > 0:
            self.log.warning(
                f"[GUARDRAIL] Startup scan: {n_orders} orphaned orders, "
                f"{n_positions} orphaned positions")
            self.position_guard.handle_orphans(conn, orphans)
        else:
            self.log.info("[GUARDRAIL] Startup scan: no orphans found")

        # Send startup notification
        self.notifier.send(
            "System Started",
            f"ORB trading system started.\n"
            f"Time: {datetime.now(tz=timezone.utc).isoformat()}\n"
            f"Instruments: {', '.join(m.inst.name for m in managers)}\n"
            f"Today's P&L so far: ${self.loss_tracker.realized_pnl:+.2f}\n"
            f"Daily loss limit: -${self.cfg.daily_loss_limit_usd:.2f}\n"
            f"Orphaned orders: {n_orders}, positions: {n_positions}",
            event_type="startup"
        )

    def on_new_day(self, today_str: str, log_dir: str):
        """Reset daily state."""
        self.loss_tracker.load_from_trade_logs(log_dir, today_str)

    def can_trade(self, conn, inst_name: str) -> bool:
        """Check all pre-trade guardrails. Returns True if safe to proceed."""
        # Daily loss limit
        if self.loss_tracker.halted:
            self.log.warning(
                f"[GUARDRAIL] {inst_name}: BLOCKED by daily loss limit "
                f"(${self.loss_tracker.realized_pnl:+.2f})")
            return False

        # Max position check
        if not self.position_guard.check_max_positions(conn, inst_name):
            return False

        return True

    def on_trade_closed(self, pnl_total: float, instrument: str,
                        direction: str, result: str, entry: float,
                        exit_price: float):
        """Called after a trade is recorded. Tracks P&L and sends notification."""
        limit_hit = self.loss_tracker.record_trade(pnl_total, instrument)

        # Notification
        self.notifier.send(
            f"{instrument} {direction} {result} ${pnl_total:+.2f}",
            f"Trade closed on {instrument}:\n"
            f"  Direction: {direction}\n"
            f"  Result:    {result}\n"
            f"  Entry:     {entry}\n"
            f"  Exit:      {exit_price}\n"
            f"  P&L:       ${pnl_total:+.2f}\n"
            f"  Daily P&L: ${self.loss_tracker.realized_pnl:+.2f}\n"
            f"  Time:      {datetime.now(tz=timezone.utc).isoformat()}",
            event_type="fill"
        )

        if limit_hit:
            self.notifier.send(
                "DAILY LOSS LIMIT HIT",
                f"Daily loss limit of -${self.cfg.daily_loss_limit_usd:.2f} "
                f"has been exceeded.\n"
                f"Realized P&L today: ${self.loss_tracker.realized_pnl:+.2f}\n"
                f"No new trades will be placed for the rest of the day.\n"
                f"Time: {datetime.now(tz=timezone.utc).isoformat()}",
                event_type="daily_loss_limit"
            )

    def on_error(self, error_msg: str, instrument: str = ""):
        """Send error notification."""
        self.notifier.send(
            f"ERROR {instrument}".strip(),
            f"Error in ORB trading system:\n"
            f"  Instrument: {instrument or 'N/A'}\n"
            f"  Error:      {error_msg}\n"
            f"  Time:       {datetime.now(tz=timezone.utc).isoformat()}",
            event_type="error"
        )
