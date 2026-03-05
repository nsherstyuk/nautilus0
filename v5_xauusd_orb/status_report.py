#!/usr/bin/env python3
"""
ORB Multi-Instrument Status Report
Generates a static HTML dashboard from trade CSVs, state files,
live log events, and optionally live IBKR account data.

Usage:
    python -m v5_xauusd_orb.status_report           # offline (CSV + state only)
    python -m v5_xauusd_orb.status_report --live     # also query IBKR for account info
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"
LIVE_LOG = LOG_DIR / "orb_multi_live.log"
OUTPUT_FILE = BASE_DIR / "status.html"

TRADE_CSV_FILES = {
    "XAUUSD": LOG_DIR / "orb_xauusd_trades.csv",
    "EURUSD": LOG_DIR / "orb_eurusd_trades.csv",
}
STATE_FILES = {
    "XAUUSD": STATE_DIR / "orb_xauusd_state.json",
    "EURUSD": STATE_DIR / "orb_eurusd_state.json",
}
ACCOUNT_SNAPSHOT = STATE_DIR / "account_snapshot.json"
CONFIG_FILE = BASE_DIR / "config.yaml"


# ── Config Loading ────────────────────────────────────────────────────────────

def load_instrument_configs() -> dict:
    """Load instrument configs from config.yaml for session times, BE params, etc."""
    try:
        import yaml
        with open(CONFIG_FILE, "r") as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("instruments", {})
    except Exception:
        return {}


# ── Log Helpers ───────────────────────────────────────────────────────────────

def get_last_prices_from_log(log_path: Path) -> dict:
    """Parse the last STATUS lines from the log to get current prices per instrument.
    Returns {instrument_name: {price, pnl, timestamp}}."""
    result = {}
    if not log_path.exists():
        return result
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 8KB to find recent status lines
            f.seek(max(0, size - 8192))
            data = f.read().decode("utf-8", errors="replace")
        for line in reversed(data.strip().split("\n")):
            line = line.strip()
            if "[STATUS]" not in line:
                continue
            # Parse: "2026-03-05 10:57:23  INFO     [STATUS] [XAUUSD] SHORT | price=5094.06 | ..."
            import re
            m = re.match(
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}).*\[STATUS\]\s+\[(\w+)\].*price=([\d.]+).*PnL=([+-]?[\d.]+)',
                line)
            if m:
                ts_str, inst, price, pnl = m.groups()
                if inst not in result:  # keep only the latest per instrument
                    result[inst] = {
                        "price": float(price),
                        "pnl": float(pnl),
                        "timestamp": ts_str,
                    }
            # Also handle non-IN_TRADE status lines (WATCHING, RANGE)
            m2 = re.match(
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}).*\[STATUS\]\s+\[(\w+)\].*price=([\d.]+)',
                line)
            if m2:
                ts_str, inst, price = m2.groups()
                if inst not in result:
                    result[inst] = {
                        "price": float(price),
                        "pnl": None,
                        "timestamp": ts_str,
                    }
            # Stop once we have data for all expected instruments
            if len(result) >= 2:
                break
    except Exception:
        pass
    return result


def get_process_health(log_path: Path) -> dict:
    """Check if the live process appears to be running based on last log timestamp.
    Returns {last_log_time: str, age_seconds: float, alive: bool}."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2048))
            data = f.read().decode("utf-8", errors="replace")
        for line in reversed(data.strip().split("\n")):
            line = line.strip()
            if line and len(line) > 19:
                ts_str = line[:19]
                try:
                    log_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    # Log timestamps appear to be in local time
                    now_local = datetime.now()
                    age = (now_local - log_dt).total_seconds()
                    return {
                        "last_log_time": ts_str,
                        "age_seconds": age,
                        "alive": age < 120,  # consider dead if >2min stale
                    }
                except ValueError:
                    continue
    except Exception:
        pass
    return {"last_log_time": "unknown", "age_seconds": 999999, "alive": False}


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


# ── Log Parsing ──────────────────────────────────────────────────────────────

def parse_log_events(log_path: Path, date_str: str = None) -> list[dict]:
    """Parse the live log for significant events.

    Returns list of dicts with keys: time, level, instrument, event, detail, category.
    If date_str is given (e.g. '2026-03-03'), only returns events from that date.
    """
    if not log_path.exists():
        return []

    # Patterns that indicate significant events (not STATUS lines)
    EVENT_PATTERNS = [
        (r'\[([A-Z]+)\]\s+Asian range computed', 'range', 'Asian range computed'),
        (r'\[([A-Z]+)\]\s+Pre-placement \| (.+)', 'check', 'Pre-placement check'),
        (r'\[([A-Z]+)\]\s+Trade window open', 'window', 'Trade window opened'),
        (r'\[([A-Z]+)\]\s+Price .+ SKIPPING (.+)', 'skip', 'Side skipped (stale price)'),
        (r'\[([A-Z]+)\]\s+LONG:\s+(.+)', 'order', 'Long levels set'),
        (r'\[([A-Z]+)\]\s+SHORT:\s+(.+)', 'order', 'Short levels set'),
        (r'\[([A-Z]+)\]\s+Buy bracket placed: id=(\d+)', 'fill', 'Buy bracket placed'),
        (r'\[([A-Z]+)\]\s+Sell bracket placed: id=(\d+)', 'fill', 'Sell bracket placed'),
        (r'\[([A-Z]+)\]\s+Position closed', 'close', 'Position closed'),
        (r'\[([A-Z]+)\]\s+Trade closed: (.+)', 'result', 'Trade closed'),
        (r'\[([A-Z]+)\]\s+Breakeven stop applied', 'be', 'Breakeven stop applied'),
        (r'\[([A-Z]+)\]\s+EOD close', 'eod', 'End-of-day close'),
        (r'\[([A-Z]+)\]\s+Day skipped', 'skip', 'Day skipped'),
        (r'\[([A-Z]+)\]\s+Both sides stale', 'skip', 'Both sides stale -- no trade'),
        (r'Shutting down', 'system', 'System shutdown'),
        (r'Connected to IB', 'system', 'Connected to IBKR'),
        (r'IB error (\d+).+: (.+)', 'error', 'IBKR error'),
        (r'Connect attempt .+ failed', 'error', 'Connection retry'),
    ]

    events = []
    # Log format: "2026-03-03 06:29:05  INFO     [XAUUSD] ..."
    line_re = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\w+)\s+(.*)')

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            m = line_re.match(line)
            if not m:
                continue

            log_date, log_time, level, message = m.groups()

            # Filter to requested date
            if date_str and log_date != date_str:
                continue

            # Skip STATUS lines (periodic updates) and noisy IB info codes
            if '[STATUS]' in message:
                continue
            # Skip harmless IB reconnect/farm/order-canceled messages
            if re.search(r'IB error (202|1100|1102|2104|2106|2108|2158)\b', message):
                continue

            for pattern, category, event_name in EVENT_PATTERNS:
                pm = re.search(pattern, message)
                if pm:
                    instrument = pm.group(1) if pm.lastindex and pm.group(1).isalpha() and len(pm.group(1)) <= 6 else ''
                    detail = pm.group(pm.lastindex) if pm.lastindex and pm.lastindex > 1 else ''

                    # Build clean detail text (strip redundant [INST] prefix)
                    if category == 'skip' and 'SKIPPING' in message:
                        # e.g. "Price 1.16 <= sell stop 1.17 -- SKIPPING short side (...)"
                        skip_m = re.search(r'Price\s+([\d.]+)\s*<=?\s*(buy|sell)\s+stop\s+([\d.]+)\s*--\s*SKIPPING\s+(.+)', message)
                        if skip_m:
                            full_detail = f"price {skip_m.group(1)} already past {skip_m.group(2)} stop {skip_m.group(3)} — {skip_m.group(4)}"
                        else:
                            full_detail = detail
                    elif category == 'result':
                        full_detail = detail
                    elif category == 'check':
                        full_detail = detail
                    elif category == 'order':
                        # Strip "[INST] LONG: " prefix, keep just the levels
                        order_m = re.search(r'entry=([\d.]+)\s+SL=([\d.]+)\s+TP=([\d.]+)', message)
                        if order_m:
                            full_detail = f"entry={order_m.group(1)} SL={order_m.group(2)} TP={order_m.group(3)}"
                            if '[SKIPPED]' in message:
                                full_detail += " [SKIPPED]"
                        else:
                            full_detail = detail
                    elif category == 'fill':
                        full_detail = f"order #{detail}" if detail.isdigit() else detail
                    elif category == 'error':
                        # Clean up IB error messages
                        err_m = re.search(r'IB error (\d+).*?: (.+)', message)
                        if err_m:
                            code = err_m.group(1)
                            msg = err_m.group(2).strip()
                            # Skip noisy reconnect messages
                            if code in ('1102', '1100', '2104', '2106', '2158'):
                                full_detail = f"[{code}] {msg}"
                            else:
                                full_detail = f"[{code}] {msg}"
                        else:
                            full_detail = message
                    else:
                        full_detail = ''

                    events.append({
                        'date': log_date,
                        'time': log_time,
                        'level': level,
                        'instrument': instrument,
                        'event': event_name,
                        'detail': full_detail,
                        'category': category,
                    })
                    break  # First match wins

    return events


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

EVENT_ICONS = {
    'range':  '&#x1F4CA;',   # chart
    'check':  '&#x1F50D;',   # magnifier
    'window': '&#x1F514;',   # bell
    'skip':   '&#x26A0;',    # warning
    'order':  '&#x1F4DD;',   # memo
    'fill':   '&#x2705;',    # check
    'close':  '&#x1F6D1;',   # stop
    'result': '&#x1F3AF;',   # target
    'be':     '&#x1F6E1;',   # shield
    'eod':    '&#x1F319;',   # moon
    'system': '&#x2699;',    # gear
    'error':  '&#x274C;',    # X
}


def pnl_color(val, dim_positive=False):
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: #6ee7a0;" if dim_positive else "color: #22c55e;"
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
                  combined_stats: dict,
                  today_events: list[dict] = None,
                  all_events: list[dict] = None,
                  account_snapshot: Optional[dict] = None,
                  instrument_configs: dict = None,
                  last_prices: dict = None,
                  process_health: dict = None) -> str:

    now_utc = datetime.now(tz=timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    instrument_configs = instrument_configs or {}
    last_prices = last_prices or {}
    process_health = process_health or {}

    # Process health banner
    health_html = ""
    if process_health:
        alive = process_health.get("alive", False)
        last_log = process_health.get("last_log_time", "unknown")
        age_sec = process_health.get("age_seconds", 0)
        if age_sec < 60:
            age_label = f"{int(age_sec)}s ago"
        elif age_sec < 3600:
            age_label = f"{int(age_sec // 60)}m ago"
        else:
            age_label = f"{int(age_sec // 3600)}h {int((age_sec % 3600) // 60)}m ago"

        if alive:
            health_html = f"""
            <div style="background:#14532d;border:1px solid #22c55e;border-radius:8px;padding:10px 16px;
                        margin-bottom:16px;display:flex;align-items:center;gap:10px;">
                <span style="font-size:1.2rem;">&#x25CF;</span>
                <span style="color:#4ade80;font-weight:600;">Process ALIVE</span>
                <span style="color:#64748b;font-size:0.85rem;">Last log: {last_log} ({age_label})</span>
            </div>"""
        else:
            health_html = f"""
            <div style="background:#4a1d1d;border:1px solid #ef4444;border-radius:8px;padding:10px 16px;
                        margin-bottom:16px;display:flex;align-items:center;gap:10px;">
                <span style="font-size:1.2rem;">&#x25CF;</span>
                <span style="color:#ef4444;font-weight:600;">Process DOWN</span>
                <span style="color:#fca5a5;font-size:0.85rem;">Last log: {last_log} ({age_label})
                -- EOD close and BE rules WILL NOT FIRE</span>
            </div>"""

    # Account section -- prefer snapshot from live process, fallback to --live query
    acct_html = ""

    # Merge sources: snapshot file (auto-updated) + live query (on-demand)
    acct_vals = {}
    snap_time = ""
    if account_snapshot:
        acct_vals = {
            "NetLiquidation": account_snapshot.get("net_liquidation", ""),
            "TotalCashValue": account_snapshot.get("total_cash", ""),
            "UnrealizedPnL": account_snapshot.get("unrealized_pnl", ""),
            "RealizedPnL": account_snapshot.get("realized_pnl", ""),
            "BuyingPower": account_snapshot.get("buying_power", ""),
            "MaintMarginReq": account_snapshot.get("maint_margin", ""),
        }
        ts = account_snapshot.get("timestamp", "")
        if ts:
            try:
                snap_dt = datetime.fromisoformat(ts)
                snap_time = snap_dt.strftime("%H:%M UTC")
            except Exception:
                snap_time = ts[:19]

    if ibkr_data and ibkr_data.get("account"):
        # Live query overrides snapshot values
        for k, v in ibkr_data["account"].items():
            acct_vals[k] = v
        snap_time = "live"

    if acct_vals:
        nlv = acct_vals.get("NetLiquidation", "N/A")
        cash = acct_vals.get("TotalCashValue", "N/A")
        margin = acct_vals.get("MaintMarginReq", "N/A")
        upnl = acct_vals.get("UnrealizedPnL", "N/A")
        buying = acct_vals.get("BuyingPower", "N/A")

        # Format unrealized P&L with color
        upnl_style = ""
        try:
            upnl_f = float(upnl)
            upnl_style = pnl_color(upnl_f)
            upnl_display = f"${upnl_f:,.2f}"
        except (ValueError, TypeError):
            upnl_display = f"${upnl}" if upnl != "N/A" else "N/A"

        # Staleness check
        snap_age_sec = 0
        stale_warning = ""
        if account_snapshot and account_snapshot.get("timestamp"):
            try:
                snap_dt = datetime.fromisoformat(account_snapshot["timestamp"])
                snap_age_sec = (now_utc - snap_dt).total_seconds()
                if snap_age_sec > 300:  # >5 minutes
                    mins = int(snap_age_sec // 60)
                    stale_warning = (
                        f'<span style="color:#fbbf24;font-size:0.75rem;margin-left:8px;">'
                        f'STALE -- {mins}m old</span>')
            except Exception:
                pass

        source_label = f'<span style="color:#64748b;font-size:0.75rem;margin-left:8px;">({snap_time})</span>' if snap_time else ''

        acct_html = f"""
        <div class="card">
            <h2>IBKR Account {source_label}{stale_warning}</h2>
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
                    <div class="stat-label">Buying Power</div>
                    <div class="stat-value">${buying}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Unrealized P&L</div>
                    <div class="stat-value" style="{upnl_style}">{upnl_display}</div>
                </div>
            </div>
        </div>
        """

        # Open positions (only from --live)
        if ibkr_data and ibkr_data.get("positions"):
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

        # Open orders (only from --live)
        if ibkr_data and ibkr_data.get("orders"):
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
            <p>No account data. The live process will update this automatically, or run with <code>--live</code>.</p>
        </div>"""

    # Current state per instrument -- rich cards
    state_cards = ""
    for inst_name, st in states.items():
        if st is None:
            status = "No state file"
            detail_html = '<p class="state-detail">No state file found</p>'
        else:
            status = st.get("status", "UNKNOWN")
            inst_cfg = instrument_configs.get(inst_name, {})
            price_data = last_prices.get(inst_name, {})
            dec = inst_cfg.get("price_decimals", 2)
            pip_label = inst_cfg.get("pip_label", "$")
            trade_end_hour = inst_cfg.get("trade_end_hour", 16)
            be_hours = inst_cfg.get("be_hours", 2)

            # Build rich detail rows
            rows = []
            rows.append(f'<div class="detail-row"><span class="detail-label">Date</span><span>{st.get("trade_date", "N/A")}</span></div>')

            if st.get("range_high"):
                rh = st["range_high"]
                rl = st["range_low"]
                rs = st.get("range_size", 0)
                rows.append(f'<div class="detail-row"><span class="detail-label">Asian Range</span><span>{rl:.5g} &mdash; {rh:.5g} (size: {rs:.5g})</span></div>')

            if st.get("direction"):
                d = st["direction"]
                ep = st.get("entry_price", 0)
                sl = st.get("sl_price", 0)
                tp = st.get("tp_price", 0)
                dir_class = "dir-long" if d == "LONG" else "dir-short"
                rows.append(f'<div class="detail-row"><span class="detail-label">Position</span><span class="{dir_class}">{d}</span> @ {ep:.5g}</div>')
                rows.append(f'<div class="detail-row"><span class="detail-label">SL / TP</span><span style="color:#f87171">{sl:.5g}</span> / <span style="color:#4ade80">{tp:.5g}</span></div>')

            if st.get("be_applied"):
                rows.append('<div class="detail-row"><span class="detail-label">Breakeven</span><span class="badge-be">BE APPLIED</span></div>')

            # ── Enhanced IN_TRADE panel ──────────────────────────────────
            if status == "IN_TRADE" and st.get("direction"):
                d = st["direction"]
                ep = st.get("entry_price", 0)
                sl = st.get("sl_price", 0)
                tp = st.get("tp_price", 0)
                be_applied = st.get("be_applied", False)
                entry_time_str = st.get("entry_time", "")
                cur_price = price_data.get("price")
                cur_pnl = price_data.get("pnl")
                price_ts = price_data.get("timestamp", "")

                # Distances
                if d == "LONG":
                    dist_to_tp = tp - ep if tp else 0
                    dist_to_sl = ep - sl if sl else 0
                    price_to_tp = (tp - cur_price) if (cur_price and tp) else None
                    price_to_sl = (cur_price - sl) if (cur_price and sl) else None
                else:
                    dist_to_tp = ep - tp if tp else 0
                    dist_to_sl = sl - ep if sl else 0
                    price_to_tp = (cur_price - tp) if (cur_price and tp) else None
                    price_to_sl = (sl - cur_price) if (cur_price and sl) else None

                total_range = dist_to_tp + dist_to_sl  # SL-to-TP total distance

                # Time calculations
                elapsed_sec = 0
                if entry_time_str:
                    try:
                        entry_dt = datetime.fromisoformat(entry_time_str)
                        elapsed_sec = (now_utc - entry_dt).total_seconds()
                    except Exception:
                        pass

                eod_dt = now_utc.replace(hour=trade_end_hour, minute=0, second=0, microsecond=0)
                time_to_eod = max(0, (eod_dt - now_utc).total_seconds())
                total_window = 0
                if entry_time_str:
                    try:
                        entry_dt = datetime.fromisoformat(entry_time_str)
                        total_window = max(1, (eod_dt - entry_dt).total_seconds())
                    except Exception:
                        total_window = trade_end_hour * 3600

                time_pct = min(100, elapsed_sec / total_window * 100) if total_window > 0 else 0

                def fmt_dur(s):
                    s = max(0, s)
                    h, m = int(s // 3600), int((s % 3600) // 60)
                    return f"{h}h {m}m" if h else f"{m}m"

                # ── Live price + P&L row ──
                if cur_price is not None:
                    pnl_style = pnl_color(cur_pnl) if cur_pnl is not None else ""
                    pnl_str = f'{cur_pnl:+.{dec}f} {pip_label}' if cur_pnl is not None else ""
                    rows.append(
                        f'<div class="detail-row" style="margin-top:8px;">'
                        f'<span class="detail-label">Live Price</span>'
                        f'<span style="font-size:1.1rem;font-weight:600;">{cur_price:.{dec}f}</span>'
                        f'<span style="{pnl_style};font-weight:600;margin-left:12px;">P&L: {pnl_str}</span>'
                        f'<span style="color:#475569;font-size:0.75rem;margin-left:8px;">(from log {price_ts})</span>'
                        f'</div>')

                # ── Visual price ladder ──
                # Shows SL --- entry --- price --- TP with a position indicator
                if cur_price is not None and total_range > 0:
                    # Normalize positions: 0 = SL level, 1 = TP level
                    if d == "LONG":
                        entry_pos = dist_to_sl / total_range * 100
                        price_pos = (cur_price - sl) / total_range * 100 if sl else 50
                    else:
                        entry_pos = dist_to_sl / total_range * 100
                        price_pos = (sl - cur_price) / total_range * 100 if sl else 50

                    price_pos = max(0, min(100, price_pos))
                    entry_pos = max(0, min(100, entry_pos))

                    # Colors for profit zone
                    if d == "LONG":
                        profit_zone = cur_price > ep
                    else:
                        profit_zone = cur_price < ep
                    bar_color = "#22c55e" if profit_zone else "#ef4444"

                    ladder_html = f"""
                    <div style="margin:12px 0 8px 0;">
                        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#64748b;margin-bottom:4px;">
                            <span style="color:#f87171;">SL {sl:.{dec}f}</span>
                            <span>Entry {ep:.{dec}f}</span>
                            <span style="color:#4ade80;">TP {tp:.{dec}f}</span>
                        </div>
                        <div style="position:relative;height:24px;background:#1e293b;border-radius:4px;border:1px solid #334155;overflow:hidden;">
                            <!-- Filled bar from SL to current price -->
                            <div style="position:absolute;left:0;top:0;bottom:0;width:{price_pos:.1f}%;
                                        background:{bar_color};opacity:0.3;border-radius:4px 0 0 4px;"></div>
                            <!-- Entry marker -->
                            <div style="position:absolute;left:{entry_pos:.1f}%;top:0;bottom:0;width:2px;
                                        background:#94a3b8;" title="Entry {ep:.{dec}f}"></div>
                            <!-- Current price marker -->
                            <div style="position:absolute;left:{price_pos:.1f}%;top:-2px;bottom:-2px;width:4px;
                                        background:{bar_color};border-radius:2px;box-shadow:0 0 6px {bar_color};"
                                 title="Current {cur_price:.{dec}f}"></div>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:#475569;margin-top:2px;">
                            <span>{pip_label}{price_to_sl:.{dec}f} to SL</span>
                            <span>{pip_label}{price_to_tp:.{dec}f} to TP</span>
                        </div>
                    </div>"""
                    rows.append(ladder_html)

                # ── Time progress bar ──
                time_bar_color = "#60a5fa" if time_to_eod > 1800 else "#fbbf24" if time_to_eod > 600 else "#ef4444"
                rows.append(f"""
                <div style="margin:8px 0;">
                    <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#64748b;margin-bottom:3px;">
                        <span>Time in trade: {fmt_dur(elapsed_sec)}</span>
                        <span>EOD close: {trade_end_hour}:00 UTC ({fmt_dur(time_to_eod)} left)</span>
                    </div>
                    <div style="height:8px;background:#0f172a;border-radius:4px;overflow:hidden;">
                        <div style="height:100%;width:{time_pct:.1f}%;background:{time_bar_color};border-radius:4px;
                                    transition:width 0.3s;"></div>
                    </div>
                </div>""")

                # ── BE progress bar ──
                if not be_applied:
                    be_total = be_hours * 3600
                    be_pct = min(100, elapsed_sec / be_total * 100) if be_total > 0 else 100
                    be_remain = max(0, be_total - elapsed_sec)
                    rows.append(f"""
                    <div style="margin:4px 0 8px 0;">
                        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#64748b;margin-bottom:3px;">
                            <span>Breakeven timer</span>
                            <span>{fmt_dur(be_remain)} until SL moves to entry</span>
                        </div>
                        <div style="height:8px;background:#0f172a;border-radius:4px;overflow:hidden;">
                            <div style="height:100%;width:{be_pct:.1f}%;background:#a78bfa;border-radius:4px;"></div>
                        </div>
                    </div>""")

                # ── WHY STILL OPEN? panel ──
                why_items = []

                # TP check
                if price_to_tp is not None:
                    tp_pct = (1 - price_to_tp / dist_to_tp) * 100 if dist_to_tp > 0 else 0
                    why_items.append(
                        f'<div style="display:flex;gap:8px;align-items:center;padding:4px 0;">'
                        f'<span style="color:#475569;font-size:1rem;">&#x2610;</span>'
                        f'<span>TP not hit</span>'
                        f'<span style="color:#64748b;font-size:0.8rem;">'
                        f'&mdash; {pip_label}{price_to_tp:.{dec}f} away ({tp_pct:.0f}% of the way)</span></div>')
                else:
                    why_items.append(
                        f'<div style="display:flex;gap:8px;align-items:center;padding:4px 0;">'
                        f'<span style="color:#475569;">&#x2610;</span>'
                        f'<span>TP not hit</span></div>')

                # SL check
                if price_to_sl is not None:
                    sl_label = "BE stop" if be_applied else "SL"
                    why_items.append(
                        f'<div style="display:flex;gap:8px;align-items:center;padding:4px 0;">'
                        f'<span style="color:#475569;font-size:1rem;">&#x2610;</span>'
                        f'<span>{sl_label} not hit</span>'
                        f'<span style="color:#64748b;font-size:0.8rem;">'
                        f'&mdash; {pip_label}{price_to_sl:.{dec}f} cushion</span></div>')

                # EOD check
                why_items.append(
                    f'<div style="display:flex;gap:8px;align-items:center;padding:4px 0;">'
                    f'<span style="color:#475569;font-size:1rem;">&#x2610;</span>'
                    f'<span>EOD close pending</span>'
                    f'<span style="color:#64748b;font-size:0.8rem;">'
                    f'&mdash; {fmt_dur(time_to_eod)} until {trade_end_hour}:00 UTC</span></div>')

                why_html = ''.join(why_items)
                rows.append(f"""
                <div style="margin:12px 0 8px 0;background:#0f172a;border:1px solid #334155;border-radius:6px;padding:10px 14px;">
                    <div style="color:#fbbf24;font-weight:600;font-size:0.85rem;margin-bottom:6px;">
                        Why is this position still open?
                    </div>
                    <div style="font-size:0.85rem;color:#cbd5e1;">
                        {why_html}
                    </div>
                </div>""")

            # Show order info with pending/filled status
            buy_id = st.get("buy_order_id", 0)
            sell_id = st.get("sell_order_id", 0)
            if buy_id or sell_id:
                is_pending = status == "ORDERS_PLACED"
                is_filled = status in ("IN_TRADE", "DONE_TODAY") and st.get("direction")
                order_parts = []
                if buy_id:
                    if is_filled and st.get("direction") == "LONG":
                        order_parts.append(f'<span class="badge-be">Buy #{buy_id} FILLED</span>')
                    elif is_pending:
                        order_parts.append(f'<span class="badge-pending">Buy #{buy_id} PENDING</span>')
                    else:
                        order_parts.append(f'Buy #{buy_id}')
                else:
                    order_parts.append('<span class="badge-skip">Buy SKIPPED</span>')
                if sell_id:
                    if is_filled and st.get("direction") == "SHORT":
                        order_parts.append(f'<span class="badge-be">Sell #{sell_id} FILLED</span>')
                    elif is_pending:
                        order_parts.append(f'<span class="badge-pending">Sell #{sell_id} PENDING</span>')
                    else:
                        order_parts.append(f'Sell #{sell_id}')
                else:
                    order_parts.append('<span class="badge-skip">Sell SKIPPED</span>')
                rows.append(f'<div class="detail-row"><span class="detail-label">Orders</span><span>{" | ".join(order_parts)}</span></div>')

            # Show today's events for this instrument
            inst_events = [e for e in (today_events or []) if e.get('instrument') == inst_name]
            if inst_events:
                evt_items = ""
                for ev in inst_events:
                    icon = EVENT_ICONS.get(ev['category'], '&bull;')
                    lvl_class = 'evt-warn' if ev['level'] == 'WARNING' else 'evt-info'
                    evt_items += f'<div class="evt-line {lvl_class}"><span class="evt-time">{ev["time"]}</span> {icon} {ev["event"]}'
                    if ev.get('detail'):
                        evt_items += f' <span class="evt-detail">&mdash; {ev["detail"]}</span>'
                    evt_items += '</div>'
                rows.append(f'<div class="detail-row evt-section"><span class="detail-label">Today</span><div class="evt-list">{evt_items}</div></div>')

            detail_html = ''.join(rows)

        status_class = "status-idle"
        if status == "IN_TRADE":
            status_class = "status-active"
        elif status == "DONE_TODAY":
            status_class = "status-done"
        elif status == "ORDERS_PLACED":
            status_class = "status-watching"
        elif status == "RANGE_COMPUTED":
            status_class = "status-range"

        state_cards += f"""
        <div class="card inst-card">
            <div class="inst-header">
                <h3>{inst_name}</h3>
                <span class="status-badge {status_class}">{status.replace('_', ' ')}</span>
            </div>
            <div class="inst-detail">
                {detail_html}
            </div>
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
                <div class="stat-value" style="{pnl_color(c['worst'], dim_positive=True)}">{fmt_pnl(c['worst'])}</div>
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

    # Activity timeline
    activity_html = ""
    if today_events:
        activity_rows = ""
        for ev in today_events:
            icon = EVENT_ICONS.get(ev['category'], '&bull;')
            inst = ev.get('instrument', '')
            inst_tag = f'<span class="inst-tag">{inst}</span>' if inst else '<span class="inst-tag" style="background:#334155;color:#64748b">SYS</span>'

            msg_class = ''
            if ev['category'] == 'skip':
                msg_class = 'skip'
            elif ev['category'] == 'error':
                msg_class = 'warn'
            elif ev['category'] in ('result', 'close', 'fill'):
                msg_class = 'good'

            detail_text = ''
            if ev['category'] in ('skip', 'result', 'check', 'error', 'order'):
                detail_text = f' &mdash; <span class="evt-detail">{ev["detail"]}</span>'

            activity_rows += f"""
            <div class="activity-line">
                <span class="activity-time">{ev['time']}</span>
                <span class="activity-inst">{inst_tag}</span>
                <span class="activity-msg {msg_class}">{icon} {ev['event']}{detail_text}</span>
            </div>"""

        activity_html = f"""
        <div class="card activity-card">
            <h2>Today's Activity</h2>
            {activity_rows}
        </div>"""
    else:
        activity_html = """
        <div class="card">
            <h2>Today's Activity</h2>
            <p style="color: #64748b;">No events yet today.</p>
        </div>"""

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
    .status-active {{ background: #1e3a5f; color: #60a5fa; animation: pulse 2s infinite; }}
    .status-watching {{ background: #3b2f1e; color: #fbbf24; }}
    .status-done {{ background: #14532d; color: #4ade80; }}
    .status-range {{ background: #2d2b4e; color: #a78bfa; }}
    @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
    .state-detail {{ color: #64748b; font-size: 0.85rem; margin-top: 6px; }}
    .inst-card {{ min-height: 120px; }}
    .inst-detail {{ margin-top: 10px; }}
    .detail-row {{ display: flex; gap: 8px; align-items: baseline; padding: 3px 0; font-size: 0.85rem; color: #cbd5e1; }}
    .detail-label {{ color: #64748b; min-width: 80px; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; flex-shrink: 0; }}
    .dir-long {{ color: #4ade80; font-weight: 600; }}
    .dir-short {{ color: #f87171; font-weight: 600; }}
    .badge-be {{ background: #1e3a5f; color: #60a5fa; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
    .badge-skip {{ background: #4a1d1d; color: #fca5a5; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
    .badge-pending {{ background: #3b2f1e; color: #fbbf24; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; animation: pulse 2s infinite; }}
    .evt-section {{ align-items: flex-start; }}
    .evt-list {{ display: flex; flex-direction: column; gap: 2px; }}
    .evt-line {{ font-size: 0.8rem; color: #94a3b8; }}
    .evt-line.evt-warn {{ color: #fbbf24; }}
    .evt-time {{ color: #475569; font-family: monospace; font-size: 0.75rem; margin-right: 4px; }}
    .evt-detail {{ color: #64748b; font-style: italic; }}
    .activity-card {{ }}
    .activity-line {{ display: flex; gap: 8px; padding: 4px 0; font-size: 0.82rem; border-bottom: 1px solid #1e293b; }}
    .activity-line:last-child {{ border-bottom: none; }}
    .activity-time {{ color: #475569; font-family: monospace; font-size: 0.78rem; min-width: 65px; }}
    .activity-inst {{ min-width: 60px; }}
    .activity-msg {{ color: #cbd5e1; }}
    .activity-msg.warn {{ color: #fbbf24; }}
    .activity-msg.skip {{ color: #fca5a5; }}
    .activity-msg.good {{ color: #4ade80; }}
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

    {health_html}

    {acct_html}

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; margin-bottom: 16px;">
        {state_cards}
    </div>

    {activity_html}

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

    # Account snapshot (auto-written by live process)
    account_snapshot = None
    if ACCOUNT_SNAPSHOT.exists():
        try:
            account_snapshot = json.loads(ACCOUNT_SNAPSHOT.read_text(encoding="utf-8"))
            nlv = account_snapshot.get("net_liquidation", "?")
            ts = account_snapshot.get("timestamp", "")[:19]
            print(f"  Account snapshot: NLV=${nlv} (as of {ts})")
        except Exception as e:
            print(f"  Account snapshot unreadable: {e}")

    # IBKR account (optional, overrides snapshot)
    ibkr_data = None
    if args.live:
        print("  Connecting to IBKR...")
        ibkr_data = load_ibkr_account(port=args.port)
        if ibkr_data:
            nlv = ibkr_data["account"].get("NetLiquidation", "?")
            print(f"  Account NLV (live): ${nlv}")

    # Load instrument configs (for session times, BE params, decimals)
    instrument_configs = load_instrument_configs()
    if instrument_configs:
        print(f"  Instrument configs: {', '.join(instrument_configs.keys())}")

    # Get last prices from log (for live price display)
    last_prices = get_last_prices_from_log(LIVE_LOG)
    for inst, pdata in last_prices.items():
        p = pdata.get("price", "?")
        ts = pdata.get("timestamp", "?")
        print(f"  {inst} last price: {p} ({ts})")

    # Process health check
    proc_health = get_process_health(LIVE_LOG)
    alive_str = "ALIVE" if proc_health.get("alive") else "DOWN"
    print(f"  Process: {alive_str} (last log: {proc_health.get('last_log_time', '?')})")

    # Parse log events
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    today_events = parse_log_events(LIVE_LOG, date_str=today_str)
    all_events = parse_log_events(LIVE_LOG)
    print(f"  Log events: {len(today_events)} today, {len(all_events)} total")

    # Compute stats
    stats_by_inst = {}
    all_combined = []
    for inst_name, trades in all_trades.items():
        stats_by_inst[inst_name] = compute_stats(trades)
        all_combined.extend(trades)
    combined_stats = compute_stats(all_combined)

    # Generate HTML
    html = generate_html(all_trades, states, ibkr_data,
                         stats_by_inst, combined_stats,
                         today_events=today_events,
                         all_events=all_events,
                         account_snapshot=account_snapshot,
                         instrument_configs=instrument_configs,
                         last_prices=last_prices,
                         process_health=proc_health)

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
