"""
"""
from __future__ import annotations
import json
import logging
import pathlib
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("order_manager")

dataclass
class OrderRecord:
    local_id: str
    strategy_id: str
    instrument_id: str
    side: str
    quantity: float
    price: Optional[float]
    status: str = "NEW"
    ib_order_id: Optional[int] = None

class OrderManager:
    def __init__(self, persistence_dir: str = "var/orders"):
        self.persistence_dir = pathlib.Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self._in_memory: Dict[str, OrderRecord] = {}

    def _persist(self, rec: OrderRecord) -> None:
        path = self.persistence_dir / f"{rec.local_id}.json"
        try:
            path.write_text(json.dumps(rec.__dict__), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist order %s", rec.local_id)

    def new_order(self, strategy_id: str, instrument_id: str, side: str, quantity: float, price: Optional[float] = None) -> OrderRecord:
        local_id = str(uuid.uuid4())
        rec = OrderRecord(local_id=local_id, strategy_id=strategy_id, instrument_id=instrument_id, side=side, quantity=quantity, price=price)
        self._in_memory[local_id] = rec
        self._persist(rec)
        logger.info("Created new order local_id=%s strategy=%s instrument=%s side=%s qty=%s price=%s", local_id, strategy_id, instrument_id, side, quantity, price)
        return rec

    def mark_sent(self, local_id: str, ib_order_id: int) -> None:
        rec = self._in_memory.get(local_id)
        if not rec:
            logger.warning("Attempt to mark_sent for unknown local_id=%s", local_id)
            return
        rec.status = "SENT"
        rec.ib_order_id = ib_order_id
        self._persist(rec)

    def update_status(self, local_id: str, status: str, extra: Optional[dict] = None) -> None:
        rec = self._in_memory.get(local_id)
        if not rec:
            logger.warning("Update status for unknown local_id=%s", local_id)
            return
        rec.status = status
        self._persist(rec)
        logger.info("Order %s status updated to %s extra=%s", local_id, status, extra)