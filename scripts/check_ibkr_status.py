"""
IBKR Account & Trade Status Checker
Connects to IBKR and shows:
  - Account summary (cash, margin, P&L)
  - Current positions
  - Open orders
  - Today's executions (fills)
  - Recent completed orders

Usage:
  python scripts/check_ibkr_status.py              # default port 4002, clientId 50
  python scripts/check_ibkr_status.py --port 7497  # TWS paper
  python scripts/check_ibkr_status.py --days 3     # show last 3 days of trades
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from ib_insync import IB, util

# Suppress ib_insync info logging
import logging
logging.getLogger('ib_insync').setLevel(logging.WARNING)


def connect(host: str, port: int, client_id: int) -> IB:
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10)
    return ib


def print_section(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print('=' * 70)


def show_account(ib: IB):
    print_section("ACCOUNT SUMMARY")
    tags = [
        'NetLiquidation', 'TotalCashValue', 'GrossPositionValue',
        'MaintMarginReq', 'AvailableFunds', 'BuyingPower',
        'UnrealizedPnL', 'RealizedPnL',
    ]
    summary = ib.accountSummary()
    shown = set()
    for item in summary:
        if item.tag in tags and item.tag not in shown:
            val = item.value
            try:
                val = f"${float(val):,.2f}"
            except (ValueError, TypeError):
                pass
            print(f"  {item.tag:<25s} {val}")
            shown.add(item.tag)
    # Show any remaining important tags
    for item in summary:
        if item.tag not in shown and item.tag in ('AccountType', 'Cushion'):
            print(f"  {item.tag:<25s} {item.value}")
            shown.add(item.tag)


def show_positions(ib: IB):
    print_section("CURRENT POSITIONS")
    positions = ib.positions()
    if not positions:
        print("  No open positions")
        return
    for pos in positions:
        c = pos.contract
        pnl = pos.avgCost * pos.position  # approximate cost basis
        print(f"  {c.symbol:<10s} {c.secType:<6s} qty={pos.position:>8.2f}  "
              f"avgCost={pos.avgCost:>10.2f}  value={pnl:>12.2f}")


def show_open_orders(ib: IB):
    print_section("OPEN ORDERS")
    orders = ib.openOrders()
    if not orders:
        print("  No open orders")
        return
    trades = ib.openTrades()
    for trade in trades:
        o = trade.order
        c = trade.contract
        status = trade.orderStatus.status
        print(f"  {c.symbol:<10s} {o.action:<5s} {o.totalQuantity:>8.2f}  "
              f"type={o.orderType:<5s} lmt={o.lmtPrice or '-':<10s}  "
              f"aux={o.auxPrice or '-':<10s} status={status}")


def show_executions(ib: IB, days: int = 1):
    print_section(f"EXECUTIONS (last {days} day{'s' if days > 1 else ''})")
    # Request execution reports
    fills = ib.fills()
    if not fills:
        # Try requesting explicitly
        from ib_insync import ExecutionFilter
        filt = ExecutionFilter()
        trades = ib.reqExecutions(filt)
        ib.sleep(2)
        fills = ib.fills()

    if not fills:
        print("  No executions found")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for fill in fills:
        exec_time = fill.execution.time
        if hasattr(exec_time, 'replace'):
            # Make timezone-aware if needed
            if exec_time.tzinfo is None:
                exec_time = exec_time.replace(tzinfo=timezone.utc)
        if exec_time >= cutoff:
            recent.append(fill)

    if not recent:
        print(f"  No executions in the last {days} day(s)")
        return

    # Sort by time
    recent.sort(key=lambda f: f.execution.time)

    print(f"  {'Time (UTC)':<22s} {'Symbol':<10s} {'Side':<6s} {'Qty':>8s}  "
          f"{'Price':>10s}  {'PnL':>10s}  {'Commission':>10s}")
    print(f"  {'-'*22} {'-'*10} {'-'*6} {'-'*8}  {'-'*10}  {'-'*10}  {'-'*10}")

    for fill in recent:
        e = fill.execution
        c = fill.contract
        comm = fill.commissionReport
        pnl_str = ""
        comm_str = ""
        if comm and comm.realizedPNL != 1.7976931348623157e+308:  # IB's "no value" sentinel
            pnl_str = f"${comm.realizedPNL:>9.2f}"
        if comm and comm.commission != 1.7976931348623157e+308:
            comm_str = f"${comm.commission:>9.2f}"

        time_str = e.time.strftime('%Y-%m-%d %H:%M:%S') if hasattr(e.time, 'strftime') else str(e.time)
        print(f"  {time_str:<22s} {c.symbol:<10s} {e.side:<6s} {e.shares:>8.2f}  "
              f"${e.price:>9.2f}  {pnl_str:>10s}  {comm_str:>10s}")


def show_completed_orders(ib: IB):
    print_section("COMPLETED ORDERS (today)")
    try:
        completed = ib.reqCompletedOrders(apiOnly=False)
        ib.sleep(2)
    except Exception:
        completed = []

    if not completed:
        print("  No completed orders found")
        return

    # Show last 20
    for trade in completed[-20:]:
        o = trade.order
        c = trade.contract
        status = trade.orderStatus.status
        fill_price = trade.orderStatus.avgFillPrice
        print(f"  {c.symbol:<10s} {o.action:<5s} {o.totalQuantity:>8.2f}  "
              f"type={o.orderType:<5s} fill={fill_price:>10.2f}  status={status}")


def show_pnl(ib: IB):
    """Request real-time PnL for the account."""
    print_section("DAILY P&L")
    account = ib.managedAccounts()[0] if ib.managedAccounts() else ''
    if not account:
        print("  Could not determine account ID")
        return

    pnl = ib.reqPnL(account)
    ib.sleep(2)

    if pnl:
        daily = pnl.dailyPnL if pnl.dailyPnL and pnl.dailyPnL != 1.7976931348623157e+308 else 0
        unrealized = pnl.unrealizedPnL if pnl.unrealizedPnL and pnl.unrealizedPnL != 1.7976931348623157e+308 else 0
        realized = pnl.realizedPnL if pnl.realizedPnL and pnl.realizedPnL != 1.7976931348623157e+308 else 0
        print(f"  Daily P&L:      ${daily:>12,.2f}")
        print(f"  Unrealized:     ${unrealized:>12,.2f}")
        print(f"  Realized:       ${realized:>12,.2f}")
        ib.cancelPnL(pnl.account)
    else:
        print("  PnL data not available")


def main():
    parser = argparse.ArgumentParser(description='IBKR Account & Trade Status Checker')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=4002, help='4002=GW paper, 7497=TWS paper')
    parser.add_argument('--client-id', type=int, default=50, help='clientId (avoid conflicts with strategies)')
    parser.add_argument('--days', type=int, default=1, help='How many days of execution history')
    args = parser.parse_args()

    print(f"Connecting to IBKR at {args.host}:{args.port} (clientId={args.client_id})...")
    try:
        ib = connect(args.host, args.port, args.client_id)
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        sys.exit(1)

    print(f"Connected. Account: {ib.managedAccounts()}")
    print(f"Server time: {ib.reqCurrentTime()}")

    try:
        show_account(ib)
        show_pnl(ib)
        show_positions(ib)
        show_open_orders(ib)
        show_executions(ib, days=args.days)
        show_completed_orders(ib)
    finally:
        ib.disconnect()
        print(f"\n{'=' * 70}")
        print("  Disconnected.")
        print('=' * 70)


if __name__ == '__main__':
    main()
