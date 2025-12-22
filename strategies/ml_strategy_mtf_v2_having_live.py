from __future__ import annotations

import time
from typing import Optional

from strategies import ml_strategy_mtf_v2 as base


class MLSignalStrategyV2HavingLiveConfig(base.MLSignalStrategyV2Config, kw_only=True):
    protection_grace_sec: float = 15.0
    protection_require_open_orders: bool = False


class MLSignalStrategyV2HavingLive(base.MLSignalStrategyV2):
    def __init__(self, config: MLSignalStrategyV2HavingLiveConfig):
        super().__init__(config)
        self._protection_grace_sec = float(getattr(config, "protection_grace_sec", 15.0))
        self._protection_require_open_orders = bool(getattr(config, "protection_require_open_orders", True))
        self._entry_filled_wall_ts: dict[str, float] = {}

    def _reset_layers(self):
        super()._reset_layers()
        self._entry_filled_wall_ts = {}

    def on_order_filled(self, event):
        try:
            order_id = str(getattr(event, "client_order_id", ""))
            for layer_name, layer in self._layers.items():
                if layer.entry_order_id and order_id == str(layer.entry_order_id):
                    self._entry_filled_wall_ts.setdefault(layer_name, time.time())
        except Exception:
            pass

        return super().on_order_filled(event)

    def get_missing_protection_reason(self, now_wall_ts: Optional[float] = None) -> Optional[str]:
        if now_wall_ts is None:
            now_wall_ts = time.time()

        try:
            positions_open = list(self.cache.positions_open(instrument_id=self.instrument_id))
        except Exception:
            positions_open = []

        if not positions_open:
            return None

        open_layers = [l for l in self._layers.values() if l.is_open and not l.is_closed]
        if not open_layers:
            return "DESYNC: broker has open positions but strategy layers show none open"

        open_order_ids: set[str] = set()
        if self._protection_require_open_orders:
            try:
                open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
                for o in open_orders:
                    try:
                        open_order_ids.add(str(o.client_order_id))
                    except Exception:
                        continue
            except Exception:
                open_order_ids = set()

        for layer in open_layers:
            entry_ts = self._entry_filled_wall_ts.get(layer.name)
            if entry_ts is None:
                self._entry_filled_wall_ts[layer.name] = now_wall_ts
                continue

            elapsed = float(now_wall_ts) - float(entry_ts)
            if elapsed < float(self._protection_grace_sec):
                continue

            if not layer.sl_order_id or not layer.tp_order_id:
                return f"MISSING_CHILD_IDS: {layer.name} sl_id={layer.sl_order_id} tp_id={layer.tp_order_id}"

            if layer.venue_sl_id is None or layer.venue_tp_id is None:
                return f"NOT_ACCEPTED: {layer.name} venue_sl_id={layer.venue_sl_id} venue_tp_id={layer.venue_tp_id}"

            if self._protection_require_open_orders:
                if str(layer.sl_order_id) not in open_order_ids or str(layer.tp_order_id) not in open_order_ids:
                    return (
                        f"MISSING_OPEN_ORDERS: {layer.name} sl_open={str(layer.sl_order_id) in open_order_ids} "
                        f"tp_open={str(layer.tp_order_id) in open_order_ids}"
                    )

        return None
