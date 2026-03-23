"""
Guardrails - Safety limits for live trading.

Ported from V5 with clean interface. Handles:
- Daily loss limit tracking
- Orphaned order/position detection and cleanup on startup
- Graceful shutdown (cancel orders, close positions)
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Guardrails:
    """
    Deep module: Hides daily P&L tracking, orphan detection, and
    shutdown procedures. Runner calls simple methods; internals are hidden.
    """

    def __init__(self, daily_loss_limit_usd: float = 50.0,
                 max_positions: int = 1,
                 cancel_orphaned_orders: bool = True,
                 close_orphaned_positions: bool = True,
                 logger: Optional[logging.Logger] = None):
        self.daily_loss_limit = daily_loss_limit_usd
        self.max_positions = max_positions
        self.cancel_orphaned_orders = cancel_orphaned_orders
        self.close_orphaned_positions = close_orphaned_positions
        self.logger = logger or logging.getLogger(__name__)

        self._daily_pnl: float = 0.0
        self._trade_count: int = 0
        self._today: str = ""
        self._breached: bool = False

    # ── Daily lifecycle ──────────────────────────────────────────────

    def on_new_day(self, date_str: str):
        """Reset daily P&L tracker for a new trading day."""
        self._today = date_str
        self._daily_pnl = 0.0
        self._trade_count = 0
        self._breached = False
        self.logger.info(
            f"Guardrails reset for {date_str} | "
            f"daily_loss_limit=${self.daily_loss_limit:.2f}")

    def on_trade_closed(self, pnl_usd: float, instrument: str,
                        direction: str, result: str,
                        entry_price: float, exit_price: float):
        """Record a closed trade and check daily loss limit."""
        self._daily_pnl += pnl_usd
        self._trade_count += 1
        self.logger.info(
            f"Guardrail P&L update: {instrument} {direction} {result} "
            f"${pnl_usd:+.2f} | Daily total: ${self._daily_pnl:+.2f} "
            f"({self._trade_count} trades)")

        if self._daily_pnl <= -self.daily_loss_limit:
            self._breached = True
            self.logger.error(
                f"DAILY LOSS LIMIT BREACHED: ${self._daily_pnl:.2f} "
                f"<= -${self.daily_loss_limit:.2f}")

    @property
    def is_breached(self) -> bool:
        return self._breached

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    # ── Startup scan ─────────────────────────────────────────────────

    def on_startup(self, ib, contract, instrument_name: str):
        """Scan for orphaned orders/positions on startup and clean up."""
        if not ib.isConnected():
            return

        # Check for orphaned orders
        if self.cancel_orphaned_orders:
            self._scan_orphaned_orders(ib, contract, instrument_name)

        # Check for orphaned positions
        if self.close_orphaned_positions:
            self._scan_orphaned_positions(ib, contract, instrument_name)

    def _scan_orphaned_orders(self, ib, contract, instrument_name: str):
        """Cancel any orders for our contract that exist on startup."""
        try:
            cancelled = 0
            for trade in ib.openTrades():
                if (hasattr(trade.contract, 'conId')
                        and trade.contract.conId == contract.conId):
                    try:
                        ib.cancelOrder(trade.order)
                        cancelled += 1
                        ib.sleep(0.3)
                    except Exception:
                        pass
            if cancelled:
                self.logger.warning(
                    f"Startup: cancelled {cancelled} orphaned orders "
                    f"for {instrument_name}")
            else:
                self.logger.info(
                    f"Startup: no orphaned orders for {instrument_name}")
        except Exception as e:
            self.logger.error(f"Orphaned order scan failed: {e}")

    def _scan_orphaned_positions(self, ib, contract, instrument_name: str):
        """Detect orphaned positions (position without matching state)."""
        try:
            for pos in ib.positions():
                if (pos.contract.conId == contract.conId
                        and abs(pos.position) > 0):
                    self.logger.warning(
                        f"Startup: ORPHANED POSITION detected for "
                        f"{instrument_name}: {pos.position} units @ "
                        f"avgCost={pos.avgCost}")
                    # Log but don't auto-close — let operator decide
                    # To auto-close, uncomment:
                    # self._close_orphaned_position(ib, contract, pos)
                    return
            self.logger.info(
                f"Startup: no orphaned positions for {instrument_name}")
        except Exception as e:
            self.logger.error(f"Orphaned position scan failed: {e}")

    # ── Graceful shutdown ────────────────────────────────────────────

    def graceful_shutdown(self, ib, contract, instrument_name: str,
                          reason: str = "shutdown"):
        """Cancel all orders and optionally close position."""
        self.logger.info(
            f"Graceful shutdown ({reason}) for {instrument_name}")
        if not ib.isConnected():
            return

        # Cancel all orders for this contract
        try:
            cancelled = 0
            for trade in ib.openTrades():
                if (hasattr(trade.contract, 'conId')
                        and trade.contract.conId == contract.conId):
                    try:
                        ib.cancelOrder(trade.order)
                        cancelled += 1
                        ib.sleep(0.3)
                    except Exception:
                        pass
            if cancelled:
                self.logger.info(
                    f"Shutdown: cancelled {cancelled} orders "
                    f"for {instrument_name}")
        except Exception as e:
            self.logger.error(f"Shutdown order cancel failed: {e}")

    # ── Error handling ───────────────────────────────────────────────

    def on_error(self, error_msg: str, instrument: str = ""):
        """Log errors for monitoring."""
        self.logger.error(
            f"Guardrail error [{instrument}]: {error_msg}")
