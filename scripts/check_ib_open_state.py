#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from ib_insync import IB


def _load_env() -> None:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / ".env.mtf_v2", override=True)


def _is_stop_order(order_type: str) -> bool:
    order_type = (order_type or "").upper()
    return "STP" in order_type


def _is_take_profit_order(order_type: str) -> bool:
    order_type = (order_type or "").upper()
    return "LMT" in order_type


def main() -> int:
    _load_env()

    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_TRADING_PORT", os.getenv("IB_PORT", "4002")))
    client_id = int(os.getenv("IB_CHECK_CLIENT_ID", "97"))

    ib = IB()
    print(f"Connecting to IB {host}:{port} client_id={client_id}")
    ib.connect(host, port, clientId=client_id, timeout=10)

    try:
        ib.reqAllOpenOrders()
        ib.sleep(1.5)
        open_trades = ib.openTrades()
        open_orders = [t.order for t in open_trades]

        ib.reqPositions()
        ib.sleep(1.0)
        positions = [p for p in ib.positions() if float(p.position) != 0.0]

        print("\n=== OPEN POSITIONS ===")
        if not positions:
            print("None")
        for p in positions:
            contract = p.contract
            symbol = f"{contract.symbol}/{contract.currency}"
            side = "LONG" if p.position > 0 else "SHORT"
            print(f"- {symbol} qty={p.position} side={side} avgCost={p.avgCost}")

        print("\n=== OPEN ORDERS ===")
        if not open_trades:
            print("None")
        for t in open_trades:
            c = t.contract
            o = t.order
            s = t.orderStatus
            symbol = f"{c.symbol}/{c.currency}"
            print(
                f"- {symbol} orderId={o.orderId} permId={o.permId} status={s.status} "
                f"action={o.action} type={o.orderType} qty={o.totalQuantity} "
                f"lmt={o.lmtPrice} stp={o.auxPrice} parentId={o.parentId} ref={o.orderRef}"
            )

        print("\n=== PROTECTION CHECK BY POSITION ===")
        if not positions:
            print("No positions -> SL/TP not required")
        for p in positions:
            contract = p.contract
            symbol = contract.symbol
            currency = contract.currency
            expected_action = "SELL" if p.position > 0 else "BUY"

            related = [
                o for o in open_orders
                if getattr(getattr(o, "contract", None), "symbol", None) is None
            ]
            # open_orders above are plain Order objects; map from trades instead
            related_trades = [
                t for t in open_trades
                if t.contract.symbol == symbol and t.contract.currency == currency and t.order.action == expected_action
            ]

            sl_orders = [t for t in related_trades if _is_stop_order(t.order.orderType)]
            tp_orders = [t for t in related_trades if _is_take_profit_order(t.order.orderType)]

            sl_ok = len(sl_orders) > 0
            tp_ok = len(tp_orders) > 0

            print(
                f"- {symbol}/{currency} expectedProtectAction={expected_action} "
                f"SL={'YES' if sl_ok else 'NO'} TP={'YES' if tp_ok else 'NO'} "
                f"(sl_count={len(sl_orders)} tp_count={len(tp_orders)})"
            )

        return 0
    finally:
        ib.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
