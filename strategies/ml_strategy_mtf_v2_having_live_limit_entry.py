from __future__ import annotations

from datetime import timedelta
import time
from typing import Optional

from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.objects import Price

from strategies import ml_strategy_mtf_v2 as base
from strategies import ml_strategy_mtf_v2_having_live as having


class MLSignalStrategyV2HavingLiveLimitEntryConfig(having.MLSignalStrategyV2HavingLiveConfig, kw_only=True):
    entry_limit_buffer_pips: float = 0.00010
    entry_timeout_sec: float = 60.0


class MLSignalStrategyV2HavingLiveLimitEntry(having.MLSignalStrategyV2HavingLive):
    def __init__(self, config: MLSignalStrategyV2HavingLiveLimitEntryConfig):
        super().__init__(config)
        self._entry_limit_buffer_pips = float(getattr(config, "entry_limit_buffer_pips", 0.00010))
        self._entry_timeout_sec = float(getattr(config, "entry_timeout_sec", 60.0))
        self._entry_submitted_wall_ts: dict[str, float] = {}

    def _reset_layers(self):
        super()._reset_layers()
        self._entry_submitted_wall_ts = {}

    def cancel_stale_entry_if_needed(self, now_wall_ts: Optional[float] = None) -> Optional[str]:
        if now_wall_ts is None:
            now_wall_ts = time.time()

        try:
            positions_open = list(self.cache.positions_open(instrument_id=self.instrument_id))
        except Exception:
            positions_open = []

        if positions_open:
            return None

        try:
            open_orders = list(self.cache.orders_open(instrument_id=self.instrument_id))
        except Exception:
            open_orders = []

        if not open_orders:
            return None

        timed_out_layers: list[str] = []
        for layer in self._layers.values():
            if layer.is_open or layer.is_closed or not layer.entry_order_id:
                continue

            try:
                if not self.cache.is_order_open(layer.entry_order_id):
                    continue
            except Exception:
                continue

            submitted_ts = self._entry_submitted_wall_ts.get(layer.name)
            if submitted_ts is None:
                self._entry_submitted_wall_ts[layer.name] = float(now_wall_ts)
                continue

            elapsed = float(now_wall_ts) - float(submitted_ts)
            if elapsed >= float(self._entry_timeout_sec):
                timed_out_layers.append(layer.name)

        if not timed_out_layers:
            return None

        try:
            self.cancel_all_orders(self.instrument_id)
        except Exception:
            pass

        try:
            self._reset_layers()
        except Exception:
            pass

        return f"ENTRY_TIMEOUT: layers={timed_out_layers} timeout_sec={self._entry_timeout_sec}"

    @staticmethod
    def _fx_pip_size_from_instrument_id(instrument_id) -> float:
        try:
            s = str(instrument_id)
            symbol = s.split(".", 1)[0]
            if "/" in symbol:
                quote = symbol.split("/", 1)[1].strip().upper()
            elif len(symbol) == 6:
                quote = symbol[3:].strip().upper()
            else:
                quote = ""
            if quote == "JPY":
                return 0.01
            return 0.0001
        except Exception:
            return 0.0001

    def _open_layer_position(
        self,
        layer: base.PositionLayer,
        order_side: OrderSide,
        entry_price: float,
        sl_price: float,
        atr: float,
    ):
        size_int = int(self.total_size * layer.size_fraction)
        if size_int == 0:
            layer.is_closed = True
            base._py_logger.info(f"[SKIP] {layer.name}: size=0, skipping (2-position mode)")
            return

        size = self._quantity_from_units(size_int)

        tp_distance = entry_price * atr * layer.tp_atr_mult
        if order_side == OrderSide.BUY:
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance

        pip_size = self._fx_pip_size_from_instrument_id(self.instrument_id)

        raw_buffer = float(self._entry_limit_buffer_pips)
        if raw_buffer >= 0.1:
            buffer_price = raw_buffer * float(pip_size)
        else:
            buffer_price = raw_buffer
        if order_side == OrderSide.BUY:
            entry_limit = entry_price + buffer_price
        else:
            entry_limit = entry_price - buffer_price

        tag_prefix = f"{self._order_id_tag}_{layer.name}"

        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=size,
            time_in_force=TimeInForce.GTD,
            expire_time=self.clock.utc_now() + timedelta(seconds=int(self._entry_timeout_sec)),
            entry_price=Price.from_str(f"{entry_limit:.5f}"),
            sl_trigger_price=Price.from_str(f"{sl_price:.5f}"),
            tp_price=Price.from_str(f"{tp_price:.5f}"),
            entry_order_type=OrderType.LIMIT,
            tp_post_only=False,
            entry_tags=[tag_prefix],
            sl_tags=[f"{tag_prefix}_SL"],
            tp_tags=[f"{tag_prefix}_TP"],
        )

        for order in bracket.orders:
            tags = []
            try:
                tags = [str(t) for t in (getattr(order, "tags", None) or [])]
            except Exception:
                tags = []

            try:
                if tag_prefix in tags:
                    layer.entry_order_id = order.client_order_id
                elif f"{tag_prefix}_SL" in tags:
                    layer.sl_order_id = order.client_order_id
                elif f"{tag_prefix}_TP" in tags:
                    layer.tp_order_id = order.client_order_id
            except Exception:
                continue

        if layer.entry_order_id:
            self._entry_submitted_wall_ts[layer.name] = time.time()

        direction = "LONG" if order_side == OrderSide.BUY else "SHORT"
        base._py_logger.info(
            f"[SUBMIT] {layer.name}: {direction} {size} units @ LIMIT {entry_limit:.5f} (mid={entry_price:.5f}, buf_pips={self._entry_limit_buffer_pips}), "
            f"SL={sl_price:.5f}, TP={tp_price:.5f} ({layer.tp_atr_mult}x ATR)"
        )

        self.submit_order_list(bracket)
        base._py_logger.info(f"[SUBMITTED] {layer.name} bracket order submitted to IBKR")
