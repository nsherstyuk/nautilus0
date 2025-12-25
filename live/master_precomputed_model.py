from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from live.hmtf_engine import BarEvent, MasterModel


@dataclass(frozen=True)
class PrecomputedMasterModel(MasterModel):
    """Master model backed by a precomputed mapping (replay/backtest).

    This avoids re-implementing the full v2 feature recipe in the live engine.
    """

    predictions_by_close: Dict[datetime, float]

    def predict(self, bar_15m: BarEvent, atr_15m: float) -> float:  # noqa: ARG002
        return float(self.predictions_by_close.get(bar_15m.end_time_utc, 0.0))
