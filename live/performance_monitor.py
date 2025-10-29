"""Performance monitoring for live trading against Phase 6 benchmarks.

Purpose
-------
This module implements a real-time PerformanceMonitor which runs alongside the
live trading node and periodically samples portfolio state to track key
performance metrics. The monitor compares live performance to Phase 6 backtest
expectations and logs alerts when deviations exceed configured thresholds.

Integration
-----------
- Designed to run concurrently with the live trading node (non-intrusive)
- Polls portfolio/account state at a fixed interval (default: 60 seconds)
- Persists snapshots to a JSON file at logs/live/performance_metrics.json
- Includes a lightweight alerting mechanism using the configured logger

Tracked Metrics
---------------
- Cumulative realized PnL and current unrealized PnL
- Total trades, win/loss counts, win rate
- Rolling Sharpe ratio (derived from trade returns)
- Current and maximum drawdown from peak equity
- Rejected signals (if available via strategy/node hooks)

Alert Rules
-----------
- Win rate drops >10% below Phase 6 backtest win rate (min 10 trades)
- Rolling Sharpe ratio falls >20% below Phase 6 backtest Sharpe (min trades)
- Max drawdown exceeds Phase 6 max drawdown
- Trade frequency deviates by >50% from expected
- Consecutive losses exceed Phase 6 max by more than 2

Persistence
-----------
- Append-only JSON structure with a metadata header and snapshot array:
  {
    "metadata": { ... benchmark and session info ... },
    "snapshots": [ { ... snapshot ... }, ... ]
  }

Usage
-----
Typical usage from live/run_live.py (simplified):

    from live.performance_monitor import create_performance_monitor

    monitor = create_performance_monitor(node, live_config)
    # Schedule monitor.monitor_loop() in asyncio while node.run() executes

"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.phase6_config_loader import (
    Phase6ConfigLoader,
    Phase6PerformanceMetrics,
    Phase6Parameters,
)
from config.live_config import LiveConfig

# Type hints only; module can operate without NautilusTrader at import time.
try:  # pragma: no cover - typing conveniences
    from nautilus_trader.live.node import TradingNode  # type: ignore
    from nautilus_trader.model.identifiers import InstrumentId  # type: ignore
except Exception:  # pragma: no cover - allow import for docs/tests without runtime dep
    TradingNode = object  # type: ignore
    InstrumentId = object  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS_FILE = PROJECT_ROOT / "logs" / "live" / "performance_metrics.json"
DEFAULT_POLL_INTERVAL_SECONDS = 60.0

ALERT_WIN_RATE_DROP_THRESHOLD = 0.10  # 10%
ALERT_SHARPE_DROP_THRESHOLD = 0.20  # 20%
ALERT_TRADE_FREQUENCY_DEVIATION_THRESHOLD = 0.50  # 50%
ROLLING_SHARPE_MIN_TRADES = 10


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PerformanceSnapshot:
    """A single performance measurement snapshot suitable for JSON serialization."""

    timestamp: str
    elapsed_seconds: float
    cumulative_pnl: float
    unrealized_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    rolling_sharpe_ratio: float
    current_drawdown: float
    max_drawdown: float
    rejected_signals_count: int
    expected_pnl_so_far: float
    alerts: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "elapsed_seconds": self.elapsed_seconds,
            "cumulative_pnl": self.cumulative_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "rolling_sharpe_ratio": self.rolling_sharpe_ratio,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.max_drawdown,
            "rejected_signals_count": self.rejected_signals_count,
            "expected_pnl_so_far": self.expected_pnl_so_far,
            "alerts": list(self.alerts),
        }


@dataclass
class Phase6Benchmark:
    """Phase 6 benchmark expectations for live comparison."""

    rank: int
    run_id: int
    expected_sharpe_ratio: float
    expected_total_pnl: float
    expected_win_rate: float
    expected_trade_count: int
    expected_max_drawdown: float
    expected_avg_winner: float
    expected_avg_loser: float
    expected_expectancy: float
    expected_rejected_signals: int
    expected_consecutive_losses: int
    expected_period_days: Optional[float] = None

    @classmethod
    def from_phase6_metrics(
        cls, rank: int, run_id: int, metrics: Phase6PerformanceMetrics
    ) -> "Phase6Benchmark":
        return cls(
            rank=rank,
            run_id=run_id,
            expected_sharpe_ratio=float(metrics.sharpe_ratio or 0.0),
            expected_total_pnl=float(metrics.total_pnl or 0.0),
            expected_win_rate=float(metrics.win_rate or 0.0),
            expected_trade_count=int(metrics.trade_count or 0),
            expected_max_drawdown=float(metrics.max_drawdown or 0.0),
            expected_avg_winner=float(metrics.avg_winner or 0.0),
            expected_avg_loser=float(metrics.avg_loser or 0.0),
            expected_expectancy=float(metrics.expectancy or 0.0),
            expected_rejected_signals=int(metrics.rejected_signals_count or 0),
            expected_consecutive_losses=int(metrics.consecutive_losses or 0),
            expected_period_days=None,
        )


# ---------------------------------------------------------------------------
# Performance Monitor
# ---------------------------------------------------------------------------

class PerformanceMonitor:
    """Monitor live trading performance vs Phase 6 benchmarks.

    Parameters
    ----------
    trading_node : TradingNode
        Live trading node (provides portfolio access and caches).
    instrument_id : InstrumentId
        Target instrument identifier used to filter positions and PnL queries.
    benchmark : Phase6Benchmark
        Expected Phase 6 performance levels for comparison/alerts.
    metrics_file : Optional[pathlib.Path]
        Destination file for metrics persistence (append-only JSON). Defaults
        to logs/live/performance_metrics.json.
    poll_interval : float
        Sampling interval in seconds (default 60 seconds).
    """

    def __init__(
        self,
        trading_node: TradingNode,
        instrument_id: InstrumentId,
        benchmark: Phase6Benchmark,
        metrics_file: Optional[Path] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.trading_node = trading_node
        self.instrument_id = instrument_id
        self.benchmark = benchmark
        self.metrics_file = Path(metrics_file) if metrics_file is not None else DEFAULT_METRICS_FILE
        self.poll_interval = float(poll_interval)

        self._logger = logging.getLogger("live")
        self._start_time = datetime.now(timezone.utc)
        self._initial_balance: float = 0.0
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0
        self._running: bool = False

        # Trade tracking
        self._trade_history: List[Dict[str, Any]] = []  # {id, pnl, ts, is_win}
        self._seen_closed_position_ids: set[str] = set()
        self._last_persisted_trade_index: int = 0

    # ------------------------------
    # Internal helpers
    # ------------------------------

    def _initialize_metrics_file(self) -> None:
        """Create or validate the metrics file with metadata header."""
        try:
            self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover
            self._logger.warning("Failed creating metrics directory %s: %s", self.metrics_file.parent, exc)

        metadata = {
            "monitoring_start_time": self._start_time.isoformat(),
            "phase6_rank": self.benchmark.rank,
            "phase6_run_id": self.benchmark.run_id,
            "benchmark": {
                "rank": self.benchmark.rank,
                "run_id": self.benchmark.run_id,
                "expected_sharpe_ratio": self.benchmark.expected_sharpe_ratio,
                "expected_total_pnl": self.benchmark.expected_total_pnl,
                "expected_win_rate": self.benchmark.expected_win_rate,
                "expected_trade_count": self.benchmark.expected_trade_count,
                "expected_max_drawdown": self.benchmark.expected_max_drawdown,
                "expected_avg_winner": self.benchmark.expected_avg_winner,
                "expected_avg_loser": self.benchmark.expected_avg_loser,
                "expected_expectancy": self.benchmark.expected_expectancy,
                "expected_rejected_signals": self.benchmark.expected_rejected_signals,
                "expected_consecutive_losses": self.benchmark.expected_consecutive_losses,
                "expected_period_days": self.benchmark.expected_period_days,
            },
        }

        if not self.metrics_file.exists():
            payload = {"metadata": metadata, "snapshots": []}
            try:
                with self.metrics_file.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                self._logger.info(
                    "Performance metrics file initialized at %s", self.metrics_file.as_posix()
                )
            except Exception as exc:  # pragma: no cover
                self._logger.warning("Failed to initialize metrics file: %s", exc)
            return

        # If file exists, ensure it is valid JSON and contains required keys
        try:
            with self.metrics_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "metadata" not in data or "snapshots" not in data:
                raise ValueError("Invalid metrics file structure")
        except Exception as exc:  # pragma: no cover
            # Attempt to backup corrupt file and recreate
            try:
                backup = self.metrics_file.with_suffix(".corrupt.json")
                self.metrics_file.replace(backup)
                self._logger.warning("Corrupt metrics file moved to %s", backup.name)
            except Exception:
                pass
            payload = {"metadata": metadata, "snapshots": []}
            try:
                with self.metrics_file.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
            except Exception:
                pass

    def _to_float_like(self, obj: Any, default: float = 0.0) -> float:
        """Best-effort conversion for Money-like objects to float."""
        try:
            if obj is None:
                return default
            # Common Money patterns
            for attr in ("to_double", "as_double"):
                if hasattr(obj, attr):
                    method = getattr(obj, attr)
                    if callable(method):
                        return float(method())
            for attr in ("value", "amount"):
                if hasattr(obj, attr):
                    return float(getattr(obj, attr))
            return float(obj)
        except Exception:
            try:
                return float(obj)
            except Exception:
                return default

    def _get_portfolio_state(self) -> Tuple[float, float, int]:
        """Return realized PnL, unrealized PnL, and total closed trades for instrument.

        Returns a best-effort view with graceful fallbacks if certain accessors are
        unavailable in the running NautilusTrader version.
        """
        realized: float = 0.0
        unrealized: float = 0.0
        total_trades: int = 0

        try:
            portfolio = self.trading_node.portfolio

            # Attempt to set initial balance from account info (one-time)
            if self._initial_balance == 0.0:
                try:
                    # Prefer explicit override for account venue when instrument venue differs (e.g., IDEALPRO vs INTERACTIVE_BROKERS)
                    account_venue_name = (os.getenv("ACCOUNT_VENUE", "").strip() or "").upper()
                    instr_venue = getattr(self.instrument_id, "venue", None)
                    if not account_venue_name:
                        # Fall back to instrument venue name if present
                        try:
                            account_venue_name = (instr_venue.value if hasattr(instr_venue, "value") else str(instr_venue or "")).upper()
                        except Exception:
                            account_venue_name = ""

                    # IB default venue name for account context
                    if not account_venue_name:
                        account_venue_name = "INTERACTIVE_BROKERS"

                    # Resolve Venue type if available
                    try:
                        from nautilus_trader.model.identifiers import Venue as NautVenue  # type: ignore
                        resolved_venue = NautVenue(account_venue_name)
                    except Exception:
                        resolved_venue = account_venue_name  # type: ignore

                    account = None
                    if hasattr(portfolio, "account"):
                        try:
                            account = portfolio.account(resolved_venue)
                        except Exception:
                            # Fallback to IB venue when instrument venue (e.g., IDEALPRO) is not registered
                            try:
                                from nautilus_trader.model.identifiers import Venue as NautVenue  # type: ignore
                                account = portfolio.account(NautVenue("INTERACTIVE_BROKERS"))
                            except Exception:
                                account = None

                    if account is not None and hasattr(account, "balance_total"):
                        bal_obj = account.balance_total()
                        self._initial_balance = self._to_float_like(bal_obj, 0.0)
                except Exception:
                    self._initial_balance = 0.0

            # PnL accessors
            try:
                r = portfolio.realized_pnl(self.instrument_id)
                realized = self._to_float_like(r, 0.0)
            except Exception:
                realized = 0.0
            try:
                u = portfolio.unrealized_pnl(self.instrument_id)
                unrealized = self._to_float_like(u, 0.0)
            except Exception:
                unrealized = 0.0

            # Closed positions for trade count and trade history updates
            try:
                closed_positions = self.trading_node.cache.positions_closed(instrument_id=self.instrument_id)
                total_trades = len(closed_positions)
                # Update internal trade history (idempotent)
                for pos in closed_positions:
                    try:
                        pos_id = str(getattr(pos, "id", getattr(pos, "position_id", "")))
                        if not pos_id or pos_id in self._seen_closed_position_ids:
                            continue
                        pnl_obj = getattr(pos, "realized_pnl", 0.0)
                        pnl = self._to_float_like(pnl_obj, 0.0)
                        ts_ns = int(getattr(pos, "ts_closed", getattr(pos, "ts_event", 0)) or 0)
                        ts_iso = (
                            datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).isoformat()
                            if ts_ns
                            else datetime.now(timezone.utc).isoformat()
                        )
                        trade_return = 0.0
                        denom = max(self._initial_balance, 1.0)
                        try:
                            trade_return = float(pnl) / float(denom)
                        except Exception:
                            trade_return = 0.0
                        self._trade_history.append(
                            {
                                "id": pos_id,
                                "pnl": pnl,
                                "timestamp": ts_iso,
                                "is_win": pnl > 0.0,
                                "is_loss": pnl < 0.0,
                                "return": trade_return,
                            }
                        )
                        self._seen_closed_position_ids.add(pos_id)
                    except Exception:
                        continue
            except Exception:
                total_trades = len(self._seen_closed_position_ids)

        except Exception as exc:  # pragma: no cover
            self._logger.warning("Portfolio access failed: %s", exc)
            realized, unrealized, total_trades = 0.0, 0.0, len(self._seen_closed_position_ids)

        # Fallback initial balance from first equity if still unset
        try:
            if self._initial_balance == 0.0:
                equity_guess = realized + unrealized
                self._initial_balance = float(equity_guess)
                self._peak_equity = self._initial_balance
        except Exception:
            pass

        return realized, unrealized, total_trades

    def _calculate_trade_metrics(self) -> Tuple[int, int, float]:
        """Compute win/loss counts and win rate from tracked closed trades."""
        wins = sum(1 for t in self._trade_history if bool(t.get("is_win", False)))
        losses = sum(1 for t in self._trade_history if bool(t.get("is_loss", False)))
        total = wins + losses
        win_rate = float(wins) / float(total) if total > 0 else 0.0
        return wins, losses, win_rate

    def _calculate_rolling_sharpe(self) -> float:
        """Calculate rolling Sharpe ratio using trade returns.

        Mirrors the backtest computation style by using mean/std of trade returns
        across recently closed trades. Requires a minimum number of trades to
        mitigate instability with tiny samples.
        """
        if len(self._trade_history) < ROLLING_SHARPE_MIN_TRADES:
            return 0.0
        returns = [float(t.get("return", 0.0)) for t in self._trade_history[-200:]]  # cap window
        # Require at least 2 samples with variation
        if len(returns) < 2:
            return 0.0
        try:
            import math

            mean_return = sum(returns) / float(len(returns))
            variance = sum((r - mean_return) ** 2 for r in returns) / float(len(returns) - 1)
            std_return = math.sqrt(max(variance, 0.0))
            if std_return <= 0.0:
                return 0.0
            return mean_return / std_return
        except Exception:
            return 0.0

    def _calculate_drawdown(self, current_equity: float) -> Tuple[float, float]:
        """Update and return (current_drawdown, max_drawdown)."""
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
        current_drawdown = max(self._peak_equity - current_equity, 0.0)
        if current_drawdown > self._max_drawdown:
            self._max_drawdown = current_drawdown
        return current_drawdown, self._max_drawdown

    def _check_alerts(self, snapshot: PerformanceSnapshot) -> List[str]:
        """Evaluate performance deviations and return alert messages."""
        alerts: List[str] = []

        # Win Rate Alert
        try:
            if (
                snapshot.total_trades >= 10
                and snapshot.win_rate < (self.benchmark.expected_win_rate - ALERT_WIN_RATE_DROP_THRESHOLD)
            ):
                diff = (self.benchmark.expected_win_rate - snapshot.win_rate)
                alerts.append(
                    f"Win rate ({snapshot.win_rate:.1%}) is {diff:.1%} below backtest expectation ({self.benchmark.expected_win_rate:.1%})"
                )
        except Exception:
            pass

        # Sharpe Ratio Alert
        try:
            threshold = self.benchmark.expected_sharpe_ratio * (1.0 - ALERT_SHARPE_DROP_THRESHOLD)
            if (
                snapshot.total_trades >= ROLLING_SHARPE_MIN_TRADES
                and snapshot.rolling_sharpe_ratio < threshold
            ):
                base = max(self.benchmark.expected_sharpe_ratio, 1e-9)
                pct_drop = (base - snapshot.rolling_sharpe_ratio) / base
                alerts.append(
                    f"Sharpe ratio ({snapshot.rolling_sharpe_ratio:.3f}) is {pct_drop:.1%} below backtest expectation ({self.benchmark.expected_sharpe_ratio:.3f})"
                )
        except Exception:
            pass

        # Drawdown Alert
        try:
            if (
                self.benchmark.expected_max_drawdown > 0
                and snapshot.max_drawdown > self.benchmark.expected_max_drawdown
            ):
                alerts.append(
                    f"Max drawdown (${snapshot.max_drawdown:.2f}) exceeds backtest max (${self.benchmark.expected_max_drawdown:.2f})"
                )
        except Exception:
            pass

        # Trade Frequency Alert
        try:
            if self.benchmark.expected_trade_count > 0 and snapshot.elapsed_seconds > 0:
                # Expectation per day from benchmark; compare to actual frequency to date
                period_days = (
                    float(self.benchmark.expected_period_days)
                    if self.benchmark.expected_period_days is not None
                    else float(os.getenv("PHASE6_EXPECTED_PERIOD_DAYS", "365"))
                )
                try:
                    period_days = float(period_days)
                    if period_days <= 0:
                        period_days = 365.0
                except Exception:
                    period_days = 365.0
                expected_trades_per_day = self.benchmark.expected_trade_count / period_days
                actual_days = snapshot.elapsed_seconds / 86400.0
                expected_so_far = expected_trades_per_day * max(actual_days, 1e-6)
                if expected_so_far > 0:
                    deviation = abs(snapshot.total_trades - expected_so_far) / expected_so_far
                    if deviation > ALERT_TRADE_FREQUENCY_DEVIATION_THRESHOLD and snapshot.total_trades >= 5:
                        alerts.append(
                            f"Trade frequency deviates by {deviation:.0%} from expected (actual={snapshot.total_trades:.1f}, expected~{expected_so_far:.1f})"
                        )
        except Exception:
            pass

        # Expected PnL underperformance Alert (>20% below expected to date)
        try:
            if snapshot.expected_pnl_so_far != 0:
                shortfall = snapshot.expected_pnl_so_far - snapshot.cumulative_pnl
                if shortfall > abs(snapshot.expected_pnl_so_far) * 0.20:
                    pct = shortfall / (abs(snapshot.expected_pnl_so_far) + 1e-9)
                    alerts.append(
                        f"Cumulative PnL (${snapshot.cumulative_pnl:.2f}) is {pct:.0%} below expected-to-date (${snapshot.expected_pnl_so_far:.2f})"
                    )
        except Exception:
            pass

        # Consecutive Losses Alert
        try:
            consecutive_losses = 0
            for trade in reversed(self._trade_history):
                if trade.get("is_win", False):
                    break
                consecutive_losses += 1
            if consecutive_losses > (self.benchmark.expected_consecutive_losses + 2):
                alerts.append(
                    f"Consecutive losses streak {consecutive_losses} exceeds backtest max {self.benchmark.expected_consecutive_losses}"
                )
        except Exception:
            pass

        return alerts

    def _capture_snapshot(self) -> PerformanceSnapshot:
        """Capture a single snapshot from current portfolio state."""
        realized_pnl, unrealized_pnl, trade_count = self._get_portfolio_state()
        wins, losses, win_rate = self._calculate_trade_metrics()
        sharpe = self._calculate_rolling_sharpe()

        # Equity approximation: base equity plus realized + unrealized
        current_equity = self._initial_balance + realized_pnl + unrealized_pnl
        current_dd, max_dd = self._calculate_drawdown(current_equity)
        elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        # Expected PnL to date based on benchmark expectancy and number of trades so far
        expected_pnl_so_far = float(self.benchmark.expected_expectancy) * float(trade_count)

        snapshot = PerformanceSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=elapsed,
            cumulative_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_trades=trade_count,
            winning_trades=wins,
            losing_trades=losses,
            win_rate=win_rate,
            rolling_sharpe_ratio=sharpe,
            current_drawdown=current_dd,
            max_drawdown=max_dd,
            rejected_signals_count=0,
            expected_pnl_so_far=expected_pnl_so_far,
            alerts=[],
        )
        snapshot.alerts = self._check_alerts(snapshot)
        return snapshot

    def _persist_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        """Append snapshot to metrics file, handling IO errors gracefully."""
        try:
            with self.metrics_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("metrics file root must be an object")
            if "snapshots" not in data:
                data["snapshots"] = []
            snap_dict = snapshot.to_dict()
            # Include new trades since last persist to support richer reports
            new_trades = self._trade_history[self._last_persisted_trade_index :]
            if new_trades:
                # Persist minimal per-trade info
                snap_dict["trades"] = [
                    {"id": t.get("id"), "timestamp": t.get("timestamp"), "pnl": float(t.get("pnl", 0.0))}
                    for t in new_trades[-500:]  # cap to prevent oversized snapshots
                ]
            data["snapshots"].append(snap_dict)

            # Atomic write: write to temp file then replace
            tmp_path = self.metrics_file.with_name(self.metrics_file.name + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(self.metrics_file)
            # Advance trade index only after successful persist
            self._last_persisted_trade_index = len(self._trade_history)
        except Exception as exc:  # pragma: no cover
            self._logger.warning("Failed to persist performance snapshot: %s", exc)

    def _log_alerts(self, alerts: List[str]) -> None:
        if not alerts:
            return
        for msg in alerts:
            self._logger.warning("PERFORMANCE ALERT: %s", msg)
        self._logger.warning("Total performance alerts: %d", len(alerts))

    async def monitor_loop(self) -> None:
        """Run the performance monitoring loop until stopped."""
        self._logger.info(
            "Starting performance monitoring loop (interval=%.0fs, metrics=%s)...",
            self.poll_interval,
            self.metrics_file.as_posix(),
        )
        self._initialize_metrics_file()
        self._running = True
        try:
            while self._running:
                try:
                    snapshot = self._capture_snapshot()
                    self._persist_snapshot(snapshot)
                    self._logger.info(
                        "Performance snapshot: PnL=$%.2f, Trades=%d, Win Rate=%.1f%%, Sharpe=%.3f",
                        snapshot.cumulative_pnl,
                        snapshot.total_trades,
                        snapshot.win_rate * 100.0,
                        snapshot.rolling_sharpe_ratio,
                    )
                    if snapshot.alerts:
                        self._log_alerts(snapshot.alerts)
                except Exception as loop_exc:  # pragma: no cover
                    self._logger.warning("Performance monitor encountered error: %s", loop_exc)
                await asyncio.sleep(self.poll_interval)
        finally:
            self._logger.info("Performance monitoring stopped.")

    def start(self) -> None:
        """Mark the monitor as running. The loop is executed by monitor_loop()."""
        self._running = True
        self._logger.info("Starting performance monitor")

    def stop(self) -> None:
        """Request monitor loop to stop at next iteration."""
        self._running = False
        self._logger.info("Stopping performance monitor")


# ---------------------------------------------------------------------------
# Benchmark loading helpers
# ---------------------------------------------------------------------------

def _parameters_match_live(live: LiveConfig, params: Phase6Parameters) -> bool:
    """Compare live config fields to a Phase 6 parameter set (best-effort)."""
    try:
        return (
            int(live.fast_period) == int(params.fast_period)
            and int(live.slow_period) == int(params.slow_period)
            and float(live.crossover_threshold_pips) == float(params.crossover_threshold_pips)
            and int(live.stop_loss_pips) == int(params.stop_loss_pips)
            and int(live.take_profit_pips) == int(params.take_profit_pips)
            and int(live.trailing_stop_activation_pips) == int(params.trailing_stop_activation_pips)
            and int(live.trailing_stop_distance_pips) == int(params.trailing_stop_distance_pips)
            and bool(live.dmi_enabled) == bool(params.dmi_enabled)
            and int(live.dmi_period) == int(params.dmi_period)
            and bool(live.stoch_enabled) == bool(params.stoch_enabled)
            and int(live.stoch_period_k) == int(params.stoch_period_k)
            and int(live.stoch_period_d) == int(params.stoch_period_d)
            and int(live.stoch_bullish_threshold) == int(params.stoch_bullish_threshold)
            and int(live.stoch_bearish_threshold) == int(params.stoch_bearish_threshold)
        )
    except Exception:
        return False


def load_phase6_benchmark_from_env(live_config: LiveConfig) -> Phase6Benchmark:
    """Resolve the Phase 6 benchmark based on environment or parameter match.

    Resolution order:
    1) PHASE6_RANK env var
    2) PHASE6_RUN_ID env var
    3) Best parameter match between live_config and Phase 6 results
    4) Fallback to Rank 1
    """
    logger = logging.getLogger("live")

    loader = Phase6ConfigLoader()

    # Prefer explicit environment overrides
    rank_env = os.getenv("PHASE6_RANK")
    run_id_env = os.getenv("PHASE6_RUN_ID")

    result = None
    if rank_env:
        try:
            rank = int(float(rank_env))
            result = loader.get_by_rank(rank)
            if result is None:
                logger.warning("No Phase 6 result for PHASE6_RANK=%s; will attempt other methods.", rank_env)
        except Exception as exc:
            logger.warning("Invalid PHASE6_RANK=%s: %s", rank_env, exc)

    if result is None and run_id_env:
        try:
            run_id = int(float(run_id_env))
            result = loader.get_by_run_id(run_id)
            if result is None:
                logger.warning("No Phase 6 result for PHASE6_RUN_ID=%s; will attempt parameter matching.", run_id_env)
        except Exception as exc:
            logger.warning("Invalid PHASE6_RUN_ID=%s: %s", run_id_env, exc)

    # Attempt parameter match
    if result is None:
        try:
            for candidate in loader.results:
                if _parameters_match_live(live_config, candidate.parameters):
                    result = candidate
                    logger.info(
                        "Matched live configuration to Phase 6 run_id=%s (rank=%s)",
                        candidate.run_id,
                        candidate.rank,
                    )
                    break
        except Exception as exc:
            logger.warning("Failed to match live config to Phase 6 results: %s", exc)

    # Fallback to best
    if result is None:
        logger.warning("Falling back to Phase 6 rank 1 as benchmark (no explicit match found).")
        result = loader.get_best()

    benchmark = Phase6Benchmark.from_phase6_metrics(
        rank=result.rank, run_id=result.run_id, metrics=result.metrics
    )
    # Optional: expected period length in days (for trade frequency expectations)
    try:
        period_days_env = os.getenv("PHASE6_EXPECTED_PERIOD_DAYS")
        if period_days_env is not None and period_days_env.strip() != "":
            benchmark.expected_period_days = float(period_days_env)
    except Exception:
        benchmark.expected_period_days = benchmark.expected_period_days or None
    return benchmark


def create_performance_monitor(
    trading_node: TradingNode,
    live_config: LiveConfig,
    metrics_file: Optional[Path] = None,
    poll_interval: Optional[float] = None,
) -> PerformanceMonitor:
    """Factory to create a PerformanceMonitor for the provided node/config."""
    # Construct InstrumentId from symbol and venue, matching live runner format
    try:
        from nautilus_trader.model.identifiers import InstrumentId  # type: ignore

        instrument_id = InstrumentId.from_str(f"{live_config.symbol}.{live_config.venue}")
    except Exception:
        instrument_id = f"{live_config.symbol}.{live_config.venue}"  # type: ignore[assignment]

    benchmark = load_phase6_benchmark_from_env(live_config)
    # Derive default metrics path from live_config.log_dir when not explicitly provided
    resolved_metrics_path = Path(metrics_file) if metrics_file is not None else (Path(live_config.log_dir) / "performance_metrics.json")
    resolved_poll_interval = float(poll_interval) if poll_interval is not None else DEFAULT_POLL_INTERVAL_SECONDS
    monitor = PerformanceMonitor(
        trading_node=trading_node,
        instrument_id=instrument_id,  # type: ignore[arg-type]
        benchmark=benchmark,
        metrics_file=resolved_metrics_path,
        poll_interval=resolved_poll_interval,
    )
    return monitor


__all__ = [
    "PerformanceSnapshot",
    "Phase6Benchmark",
    "PerformanceMonitor",
    "load_phase6_benchmark_from_env",
    "create_performance_monitor",
]


