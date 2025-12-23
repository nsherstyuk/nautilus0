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
    return max(round(units / 1000) * 1000, 1000)


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

    def maybe_transition_on_master(self, master: MasterSignal, threshold: float, now_utc: datetime) -> None:
        if self.state == TradeState.COOLDOWN:
            if self.cooldown_until and now_utc >= self.cooldown_until:
                self.state = TradeState.IDLE
            else:
                return

        if self.state == TradeState.IDLE and master.confidence > threshold:
            logger.info("STATE IDLE -> HUNTING (master_conf=%.4f > %.4f)", master.confidence, threshold)
            self.state = TradeState.HUNTING

        if self.state == TradeState.HUNTING and master.confidence <= threshold:
            logger.info("STATE HUNTING -> IDLE (master_conf=%.4f <= %.4f)", master.confidence, threshold)
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
        dataset_logger: Optional[TrainingRowLogger] = None,
    ) -> None:
        self.store = store
        self.sync = sync
        self.sm = sm
        self.master_model = master_model
        self.soldier_model = soldier_model
        self.master_threshold = master_threshold
        self.dataset_logger = dataset_logger

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
        self.sm.maybe_transition_on_master(signal, threshold=self.master_threshold, now_utc=bar.end_time_utc)
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

    def __init__(self, engine: MultiTimeframeEngine) -> None:
        self.engine = engine
        self._queue: List[Tuple[datetime, int, BarEvent]] = []

    def submit(self, bar: BarEvent) -> None:
        priority = 0 if bar.timeframe == "15m" else 1
        self._queue.append((bar.end_time_utc, priority, bar))
        self._drain()

    def _drain(self) -> None:
        self._queue.sort(key=lambda x: (x[0], x[1]))
        while self._queue:
            _, _, bar = self._queue.pop(0)
            if bar.timeframe == "15m":
                self.engine.on_15m_close(bar)
            elif bar.timeframe == "5m":
                self.engine.on_5m_close(bar)
            else:
                logger.warning("Unknown timeframe: %s", bar.timeframe)
