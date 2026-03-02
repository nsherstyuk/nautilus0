#!/usr/bin/env python3
"""
ORB Multi-Instrument Status Report
Generates a static HTML dashboard from trade CSVs, state files,
and optionally live IBKR account data.

Usage:
    python -m v5_xauusd_orb.status_report           # offline (CSV + state only)
    python -m v5_xauusd_orb.status_report --live     # also query IBKR for account info
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"
OUTPUT_FILE = BASE_DIR / "status.html"

TRADE_CSV_FILES = {
    "XAUUSD": LOG_DIR / "orb_xauusd_trades.csv",
    "EURUSD": LOG_DIR / "orb_eurusd_trades.csv",
}
STATE_FILES = {
    "XAUUSD": STATE_DIR / "orb_xauusd_state.json",
    "EURUSD": STATE_DIR / "orb_eurusd_state.json",
}

# ── Data Loading ──────────────────────────────────────────────────────────────

def load_trades(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    trades = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ("entry", "exit", "sl", "tp", "range_high", "range_low",
                        "range_size", "pnl_per_unit", "pnl_total"):
                if key in row and row[key]:
                    try:
                        row[key] = float(row[key])
                    except ValueError:
                        pass
            for key in ("qty", "hold_minutes"):
                if key in row and row[key]:
                    try:
                        row[key] = int(float(row[key]))
                    except ValueError:
                        pass
            trades.append(row)
    return trades


def load_state(state_path: Path) -> Optional[dict]:
    if not state_path.exists():
        return None
    with open(state_path, "r") as f:
        return json.load(f)


def load_ibkr_account(port: int = 4002, client_id: int = 61) -> Optional[dict]:
    """Try to connect to IBKR and get account summary. Returns None on failure."""
    try:
        from ib_insync import IB
        ib = IB()
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=10)
        summary = ib.accountSummary()
        positions = ib.positions()
        orders = ib.openOrders()

        acct = {}
        for item in summary:
            acct[item.tag] = item.value

        pos_list = []
        for p in positions:
            pos_list.append({
                "symbol": p.contract.localSymbol or p.contract.symbol,
                "qty": float(p.position),
                "avg_cost": float(p.avgCost),
                "value": float(p.position) * float(p.avgCost),
            })

        order_list = []
        for o in orders:
            order_list.append({
                "id": o.orderId,
                "action": o.action,
                "type": o.orderType,
                "qty": float(o.totalQuantity),
                "price": o.auxPrice if o.orderType == "STP" else o.lmtPrice,
                "tif": o.tif,
            })

        ib.disconnect()
        return {"account": acct, "positions": pos_list, "orders": order_list}
    except Exception as e:
        print(f"  Could not connect to IBKR: {e}")
        return None


# ── Stats Calculation ─────────────────────────────────────────────────────────

def compute_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_pnl": 0, "avg_pnl": 0, "avg_win": 0, "avg_loss": 0,
            "best": 0, "worst": 0, "avg_hold_min": 0,
        }
    pnls = [t.get("pnl_total", 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    hold_mins = [t.get("hold_minutes", 0) for t in trades if t.get("hold_minutes")]

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "total_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "best": max(pnls) if pnls else 0,
        "worst": min(pnls) if pnls else 0,
        "avg_hold_min": sum(hold_mins) / len(hold_mins) if hold_mins else 0,
    }


# ── HTML Generation ───────────────────────────────────────────────────────────

def pnl_color(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: #22c55e;"
        elif val < 0:
            return "color: #ef4444;"
    return ""


def fmt_pnl(val, prefix="$"):
    if isinstance(val, (int, float)):
        sign = "+" if val >= 0 else ""
        return f"{sign}{prefix}{val:,.2f}"
    return str(val)


def generate_html(all_trades: dict[str, list[dict]],
                  states: dict[str, Optional[dict]],
                  ibkr_data: Optional[dict],
                  stats_by_inst: dict[str, dict],
                  combined_stats: dict) -> str:

    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Account section
    acct_html = ""
    if ibkr_data and ibkr_data.get("account"):
        a = ibkr_data["account"]
        nlv = a.get("NetLiquidation", "N/A")
        cash = a.get("TotalCashValue", "N/A")
        margin = a.get("MaintMarginReq", "N/A")
        upnl = a.get("UnrealizedPnL", "N/A")
        rpnl = a.get("RealizedPnL", "N/A")
        acct_html = f"""
        <div class="card">
            <h2>IBKR Account</h2>
            <div class="grid-4">
                <div class="stat-box">
                    <div class="stat-label">Net Liquidation</div>
                    <div class="stat-value">${nlv}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Cash Balance</div>
                    <div class="stat-value">${cash}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Margin Used</div>
                    <div class="stat-value">${margin}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Unrealized P&L</div>
                    <div class="stat-value">${upnl}</div>
                </div>
            </div>
        </div>
        """

        # Open positions
        if ibkr_data.get("positions"):
            pos_rows = ""
            for p in ibkr_data["positions"]:
                pos_rows += f"""
                <tr>
                    <td>{p['symbol']}</td>
                    <td>{p['qty']:g}</td>
                    <td>{p['avg_cost']:.5f}</td>
                </tr>"""
            acct_html += f"""
            <div class="card">
                <h2>Open Positions</h2>
                <table>
                    <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead>
                    <tbody>{pos_rows}</tbody>
                </table>
            </div>"""

        # Open orders
        if ibkr_data.get("orders"):
            ord_rows = ""
            for o in ibkr_data["orders"]:
                ord_rows += f"""
                <tr>
                    <td>{o['id']}</td>
                    <td>{o['action']}</td>
                    <td>{o['type']}</td>
                    <td>{o['qty']:g}</td>
                    <td>{o['price']}</td>
                    <td>{o['tif']}</td>
                </tr>"""
            acct_html += f"""
            <div class="card">
                <h2>Open Orders</h2>
                <table>
                    <thead><tr><th>ID</th><th>Action</th><th>Type</th><th>Qty</th><th>Price</th><th>TIF</th></tr></thead>
                    <tbody>{ord_rows}</tbody>
                </table>
            </div>"""
    else:
        acct_html = """
        <div class="card muted">
            <h2>IBKR Account</h2>
            <p>Not connected. Run with <code>--live</code> to fetch account data.</p>
        </div>"""

    # Current state per instrument
    state_cards = ""
    for inst_name, st in states.items():
        if st is None:
            status = "No state file"
            detail = ""
        else:
            status = st.get("status", "UNKNOWN")
            detail_parts = [f"Date: {st.get('trade_date', 'N/A')}"]
            if st.get("range_high"):
                detail_parts.append(
                    f"Range: {st['range_low']:.5g} - {st['range_high']:.5g} "
                    f"(size: {st.get('range_size', 0):.5g})")
            if st.get("direction"):
                detail_parts.append(
                    f"{st['direction']} @ {st.get('entry_price', 0):.5g} | "
                    f"SL={st.get('sl_price', 0):.5g} TP={st.get('tp_price', 0):.5g}")
            if st.get("be_applied"):
                detail_parts.append("BE applied")
            detail = " | ".join(detail_parts)

        status_class = "status-idle"
        if status == "IN_TRADE":
            status_class = "status-active"
        elif status == "DONE_TODAY":
            status_class = "status-done"
        elif status == "ORDERS_PLACED":
            status_class = "status-watching"

        state_cards += f"""
        <div class="card">
            <div class="inst-header">
                <h3>{inst_name}</h3>
                <span class="status-badge {status_class}">{status}</span>
            </div>
            <p class="state-detail">{detail}</p>
        </div>"""

    # Combined stats
    c = combined_stats
    combined_pnl_style = pnl_color(c["total_pnl"])
    stats_html = f"""
    <div class="card">
        <h2>Overall Performance</h2>
        <div class="grid-4">
            <div class="stat-box">
                <div class="stat-label">Total P&L</div>
                <div class="stat-value" style="{combined_pnl_style}">{fmt_pnl(c['total_pnl'])}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Trades</div>
                <div class="stat-value">{c['count']}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">{c['win_rate']:.1f}%</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Avg Hold</div>
                <div class="stat-value">{c['avg_hold_min']:.0f} min</div>
            </div>
        </div>
        <div class="grid-4" style="margin-top: 12px;">
            <div class="stat-box">
                <div class="stat-label">Avg Win</div>
                <div class="stat-value" style="color:#22c55e;">{fmt_pnl(c['avg_win'])}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Avg Loss</div>
                <div class="stat-value" style="color:#ef4444;">{fmt_pnl(c['avg_loss'])}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Best</div>
                <div class="stat-value" style="color:#22c55e;">{fmt_pnl(c['best'])}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Worst</div>
                <div class="stat-value" style="color:#ef4444;">{fmt_pnl(c['worst'])}</div>
            </div>
        </div>
    </div>"""

    # Per-instrument stats
    for inst_name, s in stats_by_inst.items():
        if s["count"] == 0:
            continue
        pstyle = pnl_color(s["total_pnl"])
        stats_html += f"""
    <div class="card">
        <h3>{inst_name} -- {s['count']} trades | Win rate: {s['win_rate']:.1f}% | P&L: <span style="{pstyle}">{fmt_pnl(s['total_pnl'])}</span></h3>
    </div>"""

    # Trade history table
    all_sorted = []
    for inst_name, trades in all_trades.items():
        for t in trades:
            t["_inst"] = inst_name
            all_sorted.append(t)
    all_sorted.sort(key=lambda t: t.get("timestamp", ""), reverse=True)

    trade_rows = ""
    running_pnl = sum(t.get("pnl_total", 0) for t in all_sorted)
    # Build rows in chronological order for running PnL
    chrono = list(reversed(all_sorted))
    rpnl_map = {}
    rp = 0.0
    for t in chrono:
        rp += t.get("pnl_total", 0)
        rpnl_map[t.get("timestamp", "")] = rp

    for t in all_sorted:
        pnl_val = t.get("pnl_total", 0)
        pstyle = pnl_color(pnl_val)
        rp_val = rpnl_map.get(t.get("timestamp", ""), 0)
        rp_style = pnl_color(rp_val)
        result = t.get("result", "")
        result_class = "result-tp" if result == "TP" else "result-sl" if result == "SL" else ""

        date_str = t.get("date", "")
        ts = t.get("timestamp", "")
        time_str = ""
        if ts and "T" in ts:
            try:
                time_str = ts.split("T")[1][:8]
            except Exception:
                pass

        trade_rows += f"""
        <tr>
            <td>{date_str}</td>
            <td>{time_str}</td>
            <td><span class="inst-tag">{t.get('_inst', '')}</span></td>
            <td>{t.get('direction', '')}</td>
            <td>{t.get('entry', '')}</td>
            <td>{t.get('exit', '')}</td>
            <td>{t.get('sl', '')}</td>
            <td>{t.get('tp', '')}</td>
            <td><span class="{result_class}">{result}</span></td>
            <td>{t.get('hold_minutes', '')}m</td>
            <td style="{pstyle}">{fmt_pnl(pnl_val)}</td>
            <td style="{rp_style}">{fmt_pnl(rp_val)}</td>
        </tr>"""

    if not trade_rows:
        trade_rows = '<tr><td colspan="12" class="muted">No trades yet</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORB Multi-Instrument Dashboard</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0f172a; color: #e2e8f0; padding: 20px;
        max-width: 1400px; margin: 0 auto;
    }}
    h1 {{ color: #f8fafc; margin-bottom: 4px; font-size: 1.5rem; }}
    h2 {{ color: #94a3b8; font-size: 1.1rem; margin-bottom: 12px; }}
    h3 {{ color: #cbd5e1; font-size: 0.95rem; margin-bottom: 8px; }}
    .header {{
        display: flex; justify-content: space-between; align-items: baseline;
        border-bottom: 1px solid #1e293b; padding-bottom: 12px; margin-bottom: 20px;
    }}
    .header-time {{ color: #64748b; font-size: 0.85rem; }}
    .card {{
        background: #1e293b; border-radius: 8px; padding: 16px;
        margin-bottom: 16px; border: 1px solid #334155;
    }}
    .card.muted p {{ color: #64748b; }}
    .grid-4 {{
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    }}
    .stat-box {{
        background: #0f172a; border-radius: 6px; padding: 12px; text-align: center;
    }}
    .stat-label {{ color: #64748b; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    .stat-value {{ color: #f1f5f9; font-size: 1.3rem; font-weight: 600; margin-top: 4px; }}
    .inst-header {{ display: flex; justify-content: space-between; align-items: center; }}
    .status-badge {{
        padding: 3px 10px; border-radius: 12px; font-size: 0.75rem;
        font-weight: 600; text-transform: uppercase;
    }}
    .status-idle {{ background: #334155; color: #94a3b8; }}
    .status-active {{ background: #1e3a5f; color: #60a5fa; }}
    .status-watching {{ background: #3b2f1e; color: #fbbf24; }}
    .status-done {{ background: #14532d; color: #4ade80; }}
    .state-detail {{ color: #64748b; font-size: 0.85rem; margin-top: 6px; }}
    table {{
        width: 100%; border-collapse: collapse; font-size: 0.85rem;
    }}
    th {{
        text-align: left; padding: 8px 10px; border-bottom: 2px solid #334155;
        color: #64748b; font-weight: 600; text-transform: uppercase;
        font-size: 0.7rem; letter-spacing: 0.05em;
    }}
    td {{ padding: 7px 10px; border-bottom: 1px solid #1e293b; }}
    tr:hover {{ background: #1a2744; }}
    .inst-tag {{
        background: #334155; padding: 2px 6px; border-radius: 4px;
        font-size: 0.75rem; font-weight: 600;
    }}
    .result-tp {{ color: #4ade80; font-weight: 600; }}
    .result-sl {{ color: #f87171; font-weight: 600; }}
    code {{
        background: #334155; padding: 2px 6px; border-radius: 4px;
        font-size: 0.8rem;
    }}
    @media (max-width: 768px) {{
        .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
    }}
</style>
</head>
<body>
    <div class="header">
        <div>
            <h1>ORB Multi-Instrument Dashboard</h1>
            <p style="color: #64748b; font-size: 0.85rem;">Asian Range Breakout Strategy -- Live Trading</p>
        </div>
        <div class="header-time">Updated: {now_str}</div>
    </div>

    {acct_html}

    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 16px;">
        {state_cards}
    </div>

    {stats_html}

    <div class="card">
        <h2>Trade History</h2>
        <table>
            <thead>
                <tr>
                    <th>Date</th><th>Time (UTC)</th><th>Instrument</th>
                    <th>Dir</th><th>Entry</th><th>Exit</th>
                    <th>SL</th><th>TP</th><th>Result</th>
                    <th>Hold</th><th>P&L</th><th>Cumul.</th>
                </tr>
            </thead>
            <tbody>
                {trade_rows}
            </tbody>
        </table>
    </div>

    <p style="color: #475569; font-size: 0.75rem; text-align: center; margin-top: 20px;">
        Generated by status_report.py | Data from v5_xauusd_orb trade logs
    </p>
</body>
</html>"""

    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate ORB trading status dashboard")
    parser.add_argument("--live", action="store_true",
                        help="Connect to IBKR for live account data")
    parser.add_argument("--port", type=int, default=4002,
                        help="IBKR Gateway port (default: 4002)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not auto-open the HTML in browser")
    args = parser.parse_args()

    print("ORB Status Report Generator")
    print("=" * 40)

    # Load trades
    all_trades = {}
    for inst_name, csv_path in TRADE_CSV_FILES.items():
        trades = load_trades(csv_path)
        all_trades[inst_name] = trades
        print(f"  {inst_name}: {len(trades)} trades loaded")

    # Load states
    states = {}
    for inst_name, state_path in STATE_FILES.items():
        st = load_state(state_path)
        states[inst_name] = st
        if st:
            print(f"  {inst_name} state: {st.get('status', 'N/A')} ({st.get('trade_date', '')})")

    # IBKR account (optional)
    ibkr_data = None
    if args.live:
        print("  Connecting to IBKR...")
        ibkr_data = load_ibkr_account(port=args.port)
        if ibkr_data:
            nlv = ibkr_data["account"].get("NetLiquidation", "?")
            print(f"  Account NLV: ${nlv}")

    # Compute stats
    stats_by_inst = {}
    all_combined = []
    for inst_name, trades in all_trades.items():
        stats_by_inst[inst_name] = compute_stats(trades)
        all_combined.extend(trades)
    combined_stats = compute_stats(all_combined)

    # Generate HTML
    html = generate_html(all_trades, states, ibkr_data,
                         stats_by_inst, combined_stats)

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\n  Dashboard written to: {OUTPUT_FILE}")
    print(f"  Total P&L: {fmt_pnl(combined_stats['total_pnl'])}")
    print(f"  Trades: {combined_stats['count']} "
          f"(W:{combined_stats['wins']} L:{combined_stats['losses']} "
          f"WR:{combined_stats['win_rate']:.0f}%)")

    if not args.no_open:
        webbrowser.open(str(OUTPUT_FILE))
        print("  Opened in browser.")


if __name__ == "__main__":
    main()
