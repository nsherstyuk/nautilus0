from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from live.hmtf_features import Atr, candle_body_wicks, make_default_soldier_indicators

logger = logging.getLogger("hmtf_engine")


class TradeState(Enum):
    IDLE = auto()
    HUNTING = auto()
    ACTIVE = auto()
    COOLDOWN = auto()


@dataclass(frozen=True)
class BarEvent:
    timeframe: str  # "15m" or "5m"
    end_time_utc: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass(frozen=True)
class MasterSignal:
    asof_15m_close: datetime
    confidence: float
    atr_15m: float


class TrainingRowLogger(Protocol):
    def log_row(self, row: Dict[str, Any]) -> None: ...


def get_dynamic_size(account_equity, atr_15m, current_price):
    risk_dollars = account_equity * 0.01  # 1% Risk ($42)
    sl_dist_price = atr_15m * 1.4
    # Units = Risk / SL Distance in price
    # For EUR/USD:
    units = int(risk_dollars / sl_dist_price)
    # Round to nearest micro-lot (1,000)
    size = max(round(units / 1000) * 1000, 1000)
    # Cap at 100k units as requested
    return min(size, 100000)


class FeatureStore:
    def __init__(self) -> None:
        self.last_master: Optional[MasterSignal] = None

    def update_master(self, signal: MasterSignal) -> None:
        self.last_master = signal


class SyncGate:
    """Prevents 5m processing when 15m update for same timestamp hasn't been applied."""

    def __init__(self, store: FeatureStore) -> None:
        self.store = store

    def can_process_5m(self, bar_5m_end: datetime) -> bool:
        if self.store.last_master is None:
            return False
        return self.store.last_master.asof_15m_close <= bar_5m_end


class TradingStateMachine:
    def __init__(self, cooldown_minutes: int) -> None:
        self.state: TradeState = TradeState.IDLE
        self.cooldown_until: Optional[datetime] = None
        self.cooldown_minutes = cooldown_minutes

    def maybe_transition_on_master(
        self,
        master: MasterSignal,
        threshold: float,
        now_utc: datetime,
        *,
        threshold_mode: str = "signed",
    ) -> None:
        if self.state == TradeState.COOLDOWN:
            if self.cooldown_until and now_utc >= self.cooldown_until:
                self.state = TradeState.IDLE
            else:
                return

        mode = (threshold_mode or "signed").strip().lower()
        if mode not in {"signed", "abs"}:
            logger.warning("Unknown threshold_mode=%r; defaulting to 'signed'", threshold_mode)
            mode = "signed"

        master_val = float(master.confidence)
        trigger_val = abs(master_val) if mode == "abs" else master_val

        if self.state == TradeState.IDLE and trigger_val > threshold:
            logger.info(
                "STATE IDLE -> HUNTING (master_conf=%.4f trigger=%.4f > %.4f mode=%s)",
                master_val,
                trigger_val,
                threshold,
                mode,
            )
            self.state = TradeState.HUNTING

        if self.state == TradeState.HUNTING and trigger_val <= threshold:
            logger.info(
                "STATE HUNTING -> IDLE (master_conf=%.4f trigger=%.4f <= %.4f mode=%s)",
                master_val,
                trigger_val,
                threshold,
                mode,
            )
            self.state = TradeState.IDLE

    def enter_cooldown(self, now_utc: datetime) -> None:
        self.state = TradeState.COOLDOWN
        self.cooldown_until = now_utc + timedelta(minutes=self.cooldown_minutes)


class MasterModel(Protocol):
    def predict(self, bar_15m: BarEvent, atr_15m: float) -> float: ...


class SoldierModel(Protocol):
    def predict(self, features: Dict[str, float]) -> float: ...


class DummyMasterModel:
    def predict(self, bar_15m: BarEvent, atr_15m: float) -> float:
        # Placeholder: returns neutral confidence.
        return 0.0


class DummySoldierModel:
    def predict(self, features: Dict[str, float]) -> float:
        # Placeholder: returns neutral score.
        return 0.0


class MultiTimeframeEngine:
    def __init__(
        self,
        store: FeatureStore,
        sync: SyncGate,
        sm: TradingStateMachine,
        master_model: MasterModel,
        soldier_model: SoldierModel,
        master_threshold: float,
        master_threshold_mode: str = "signed",
        dataset_logger: Optional[TrainingRowLogger] = None,
        on_soldier_evaluated: Optional[
            Callable[[BarEvent, MasterSignal, float, Dict[str, float]], None]
        ] = None,
    ) -> None:
        self.store = store
        self.sync = sync
        self.sm = sm
        self.master_model = master_model
        self.soldier_model = soldier_model
        self.master_threshold = master_threshold
        self.master_threshold_mode = master_threshold_mode
        self.dataset_logger = dataset_logger
        self.on_soldier_evaluated = on_soldier_evaluated

        self.last_soldier_score: Optional[float] = None
        self.last_soldier_features: Optional[Dict[str, float]] = None

        self._atr_15m = Atr(period=14)
        self._soldier_ind = make_default_soldier_indicators()

        self.last_5m: Optional[BarEvent] = None
        self.last_15m: Optional[BarEvent] = None

    def on_15m_close(self, bar: BarEvent) -> None:
        self.last_15m = bar
        atr_val = float(self._atr_15m.update(bar.h, bar.l, bar.c) or 0.0)
        conf = float(self.master_model.predict(bar, atr_val))
        signal = MasterSignal(asof_15m_close=bar.end_time_utc, confidence=conf, atr_15m=atr_val)
        self.store.update_master(signal)
        self.sm.maybe_transition_on_master(
            signal,
            threshold=self.master_threshold,
            now_utc=bar.end_time_utc,
            threshold_mode=self.master_threshold_mode,
        )
        logger.info("[MASTER 15m] close=%s conf=%.4f atr15=%.6f state=%s", bar.end_time_utc.isoformat(), conf, atr_val, self.sm.state.name)

    def on_5m_close(self, bar: BarEvent) -> None:
        self.last_5m = bar
        if not self.sync.can_process_5m(bar.end_time_utc):
            logger.info("[SOLDIER 5m] close=%s skipped (no master yet)", bar.end_time_utc.isoformat())
            return

        master = self.store.last_master
        assert master is not None

        # Enforce lagged feature rule
        if master.asof_15m_close > bar.end_time_utc:
            logger.warning("Lag violation: master_asof=%s > bar5=%s", master.asof_15m_close, bar.end_time_utc)
            return

        # Update 5m indicators
        rsi = float(self._soldier_ind.rsi.update(bar.c) or 50.0)
        macd, macd_sig, macd_hist = self._soldier_ind.macd.update(bar.c)
        bb_width = float(self._soldier_ind.bb_width.update(bar.c))
        body, upper, lower = candle_body_wicks(bar.o, bar.h, bar.l, bar.c)

        features: Dict[str, float] = {
            "macro_permission": float(master.confidence),
            "atr_15m": float(master.atr_15m),
            "rsi_5m": float(rsi),
            "macd_5m": float(macd),
            "macd_signal_5m": float(macd_sig),
            "macd_hist_5m": float(macd_hist),
            "bb_width_5m": float(bb_width),
            "body_5m": float(body),
            "upper_wick_5m": float(upper),
            "lower_wick_5m": float(lower),
        }

        score = float(self.soldier_model.predict(features))
        self.last_soldier_score = score
        self.last_soldier_features = features

        if self.on_soldier_evaluated is not None:
            try:
                self.on_soldier_evaluated(bar, master, score, features)
            except Exception:
                logger.exception("on_soldier_evaluated callback failed")

        if self.dataset_logger is not None:
            self.dataset_logger.log_row({
                "ts_5m_close": bar.end_time_utc.isoformat(),
                "ts_master_15m_close": master.asof_15m_close.isoformat(),
                "last_15m_prediction": float(master.confidence),
                "atr_15m": float(master.atr_15m),
                "open": bar.o,
                "high": bar.h,
                "low": bar.l,
                "close": bar.c,
                "volume": bar.v,
                **features,
            })

        logger.info(
            "[SOLDIER 5m] close=%s master_asof=%s master=%.4f score=%.4f state=%s",
            bar.end_time_utc.isoformat(),
            master.asof_15m_close.isoformat(),
            master.confidence,
            score,
            self.sm.state.name,
        )


class BarEventRouter:
    """Central ordering queue: if 15m and 5m share the same close timestamp, 15m is processed first."""

    def __init__(
        self,
        engine: MultiTimeframeEngine,
        *,
        max_hold_seconds: float = 10.0,
        time_basis: str = "wall_clock",
    ) -> None:
        self.engine = engine
        self.max_hold_seconds = float(max_hold_seconds)
        self.time_basis = str(time_basis).strip().lower()
        if self.time_basis not in {"wall_clock", "event_time"}:
            logger.warning("Unknown router time_basis=%r; defaulting to wall_clock", self.time_basis)
            self.time_basis = "wall_clock"
        self._queue: List[Tuple[datetime, int, BarEvent]] = []
        self._first_seen_5m: Dict[datetime, datetime] = {}
        self._now_utc: Optional[datetime] = None

    @staticmethod
    def _floor_to_15m(ts: datetime) -> datetime:
        # Preserve tzinfo and align to 15-minute boundaries.
        minute = ts.minute - (ts.minute % 15)
        return ts.replace(minute=minute, second=0, microsecond=0)

    def _can_dispatch_5m(self, bar: BarEvent) -> bool:
        """Only dispatch 5m once the expected 15m close for that quarter-hour is available.

        This prevents using a stale master at quarter-hour boundaries when the 5m close
        arrives before the 15m close event.
        """

        expected_master_close = self._floor_to_15m(bar.end_time_utc)
        master = self.engine.store.last_master
        if master is None:
            return False
        # We only consider the master usable if it is at least the expected close.
        if master.asof_15m_close < expected_master_close:
            return False
        # Also never allow lookahead.
        if master.asof_15m_close > bar.end_time_utc:
            return False
        return True

    def _hold_timed_out(self, bar_end: datetime, now_utc: datetime) -> bool:
        first = self._first_seen_5m.get(bar_end)
        if first is None:
            self._first_seen_5m[bar_end] = now_utc
            return False
        return (now_utc - first).total_seconds() >= self.max_hold_seconds

    def submit(self, bar: BarEvent) -> None:
        if self.time_basis == "event_time":
            if self._now_utc is None or bar.end_time_utc > self._now_utc:
                self._now_utc = bar.end_time_utc
        priority = 0 if bar.timeframe == "15m" else 1
        self._queue.append((bar.end_time_utc, priority, bar))
        self._drain()

    def _drain(self) -> None:
        self._queue.sort(key=lambda x: (x[0], x[1]))
        while self._queue:
            end_time, _priority, bar = self._queue[0]
            if bar.timeframe == "15m":
                self._queue.pop(0)
                self.engine.on_15m_close(bar)
                continue

            if bar.timeframe == "5m":
                now_utc = self._now_utc if self.time_basis == "event_time" else datetime.now(timezone.utc)
                if now_utc is None:
                    now_utc = datetime.now(timezone.utc)
                if self._can_dispatch_5m(bar):
                    self._queue.pop(0)
                    self._first_seen_5m.pop(end_time, None)
                    self.engine.on_5m_close(bar)
                    continue

                if self._hold_timed_out(end_time, now_utc):
                    # Fail-safe: allow processing (engine will still enforce no-lookahead).
                    self._queue.pop(0)
                    self._first_seen_5m.pop(end_time, None)
                    logger.warning(
                        "Router hold timeout (%.1fs): dispatching 5m close=%s with current master_asof=%s (expected=%s)",
                        self.max_hold_seconds,
                        bar.end_time_utc.isoformat(),
                        self.engine.store.last_master.asof_15m_close.isoformat() if self.engine.store.last_master else None,
                        self._floor_to_15m(bar.end_time_utc).isoformat(),
                    )
                    self.engine.on_5m_close(bar)
                    continue

                # Can't safely process earliest 5m yet; stop draining.
                return

            logger.warning("Unknown timeframe: %s", bar.timeframe)
            self._queue.pop(0)
