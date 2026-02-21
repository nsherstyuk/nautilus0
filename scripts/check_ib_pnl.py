#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from ib_insync import IB


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / '.env', override=False)
    load_dotenv(root / '.env.mtf_v2', override=True)

    host = os.getenv('IB_HOST', '127.0.0.1')
    port = int(os.getenv('IB_TRADING_PORT', os.getenv('IB_PORT', '4002')))
    client_id = int(os.getenv('IB_CHECK_CLIENT_ID', '98'))

    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10)
    try:
        account_values = ib.accountSummary()
        wanted = {'NetLiquidation', 'RealizedPnL', 'UnrealizedPnL', 'TotalCashValue', 'AvailableFunds'}
        rows = [v for v in account_values if v.tag in wanted]

        print(f'Connected to {host}:{port} (client {client_id})')
        if not rows:
            print('No account summary rows returned for requested PnL tags.')
            return 0

        print('--- Account Summary ---')
        for v in rows:
            print(f'{v.tag}={v.value} {v.currency}')
        return 0
    finally:
        ib.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
