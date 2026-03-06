"""
reconcile.py -- Live vs Backtest Parity Reconciliation

Parses the live trading log to extract what the system computed (range, planned
orders, actual fill, BE application, exit) and validates:

  1. MATH CHECK:  Given the range, were entry/SL/TP calculated correctly?
  2. FILL CHECK:  How far was the actual fill from the planned stop-entry?
  3. BE CHECK:    Was breakeven applied at the right time with correct offset?
  4. EXIT CHECK:  Did the trade exit correctly (TP/SL/TIME)?
  5. P&L CHECK:   Does the logged P&L match the expected math?

This approach works even when backtest historical data doesn't cover the live
trading period (e.g., parquet ends before live trades started).

Usage:
  python -m v5_xauusd_orb.reconcile              # all live trades
  python -m v5_xauusd_orb.reconcile --save        # also save CSV
  python -m v5_xauusd_orb.reconcile --date 2026-03-05  # single date
"""
from __future__ import annotations

import argparse
import re
import datetime as dt
from pathlib import Path

import pandas as pd
import yaml

from v5_xauusd_orb.config import ROOT


# ── Instrument config (from config.yaml) ─────────────────────────────────────

def load_instrument_configs() -> dict:
    """Load instrument parameters from config.yaml."""
    config_path = ROOT / 'v5_xauusd_orb' / 'config.yaml'
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    instruments = {}
    for name, ic in cfg.get('instruments', {}).items():
        if not ic.get('enabled', False):
            continue
        instruments[name] = {
            'range_start': ic.get('asian_start_hour', 0),
            'range_end': ic.get('asian_end_hour', 6),
            'trade_start': ic.get('trade_start_hour', 8),
            'trade_end': ic.get('trade_end_hour', 16),
            'rr': ic.get('rr_ratio', 2.0),
            'be_hours': ic.get('be_hours', 2),
            'be_offset': ic.get('be_offset', 0.0),
            'skip_weekdays': ic.get('skip_weekdays', []),
            'qty': ic.get('qty', 1),
            'decimals': ic.get('price_decimals', 2),
            'pip_label': ic.get('pip_label', '$'),
        }
    return instruments


# ── Log parsing ───────────────────────────────────────────────────────────────

def parse_log_events(log_path: str) -> list[dict]:
    """Parse the live log into structured events per instrument per day."""
    events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Extract timestamp
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if not ts_match:
                continue
            ts_str = ts_match.group(1)
            ts = dt.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            # Extract instrument tag
            tag_match = re.search(r'\[(\w+)\]', line)
            if not tag_match or tag_match.group(1) in ('STATUS', 'INFO', 'WARNING', 'ERROR'):
                # Check for instrument tag after STATUS
                tag_match2 = re.search(r'\[STATUS\]\s*\[(\w+)\]', line)
                if tag_match2:
                    inst = tag_match2.group(1)
                else:
                    continue
            else:
                inst = tag_match.group(1)

            # Range computed (from STATUS line)
            m = re.search(r'RANGE H=([\d.]+) L=([\d.]+)', line)
            if m:
                events.append({
                    'ts': ts, 'inst': inst, 'type': 'range',
                    'range_high': float(m.group(1)),
                    'range_low': float(m.group(2)),
                })
                continue

            # Planned bracket orders
            m = re.search(r'(LONG|SHORT):\s+entry=([\d.]+)\s+SL=([\d.]+)\s+TP=([\d.]+)', line)
            if m:
                events.append({
                    'ts': ts, 'inst': inst, 'type': 'planned_order',
                    'direction': m.group(1),
                    'planned_entry': float(m.group(2)),
                    'planned_sl': float(m.group(3)),
                    'planned_tp': float(m.group(4)),
                })
                continue

            # Actual fill
            m = re.search(r'Entered (LONG|SHORT) at ([\d.]+) \| SL=([\d.]+) TP=([\d.]+)', line)
            if m:
                events.append({
                    'ts': ts, 'inst': inst, 'type': 'fill',
                    'direction': m.group(1),
                    'fill_price': float(m.group(2)),
                    'fill_sl': float(m.group(3)),
                    'fill_tp': float(m.group(4)),
                })
                continue

            # BE applied
            m = re.search(r'BE rule: SL ([\d.]+) -> ([\d.]+)', line)
            if m:
                events.append({
                    'ts': ts, 'inst': inst, 'type': 'be_applied',
                    'old_sl': float(m.group(1)),
                    'new_sl': float(m.group(2)),
                })
                continue

            # Trade closed
            m = re.search(r'Trade closed: (LONG|SHORT) (TP|SL|BE|TIME) \| Entry=([\d.]+) Exit=([\d.]+) \| PnL=([+\-\d.]+)/unit \| Total=\$([+\-\d.]+)', line)
            if m:
                events.append({
                    'ts': ts, 'inst': inst, 'type': 'trade_closed',
                    'direction': m.group(1),
                    'result': m.group(2),
                    'entry': float(m.group(3)),
                    'exit': float(m.group(4)),
                    'pnl_per_unit': float(m.group(5)),
                    'pnl_total': float(m.group(6)),
                })
                continue

            # Window closed / EOD
            if 'Window closed in position' in line:
                events.append({'ts': ts, 'inst': inst, 'type': 'eod_close'})
            elif 'Position closed at market' in line:
                events.append({'ts': ts, 'inst': inst, 'type': 'market_close'})

    return events


def group_events_by_trade(events: list[dict]) -> list[dict]:
    """Group log events into trade records (one per instrument per day)."""
    trades = {}  # key = (date, instrument)

    for evt in events:
        trade_date = evt['ts'].date()
        key = (trade_date, evt['inst'])

        if key not in trades:
            trades[key] = {
                'date': trade_date,
                'instrument': evt['inst'],
                'range': None,
                'planned_orders': [],
                'fill': None,
                'be': None,
                'close': None,
                'eod': False,
            }

        t = trades[key]
        if evt['type'] == 'range':
            t['range'] = evt
        elif evt['type'] == 'planned_order':
            t['planned_orders'].append(evt)
        elif evt['type'] == 'fill':
            t['fill'] = evt
        elif evt['type'] == 'be_applied':
            t['be'] = evt
        elif evt['type'] == 'trade_closed':
            t['close'] = evt
        elif evt['type'] == 'eod_close':
            t['eod'] = True

    # Return trades that filled (even if close came via market close without summary)
    result = []
    for t in trades.values():
        if t['fill'] is None:
            continue
        if t['close'] is not None:
            result.append(t)
        elif t['eod']:
            # EOD market close without 'Trade closed:' log line
            # Construct close from CSV data (loaded later)
            t['close_from_csv'] = True
            result.append(t)
    return result


# ── Load live trade CSVs ─────────────────────────────────────────────────────

def load_live_trades() -> pd.DataFrame:
    logs_dir = ROOT / 'v5_xauusd_orb' / 'logs'
    frames = []
    for f in sorted(logs_dir.glob('orb_*_trades.csv')):
        df = pd.read_csv(f)
        if len(df) > 0:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined['date'] = pd.to_datetime(combined['date']).dt.date
    return combined


# ── Reconciliation checks ────────────────────────────────────────────────────

def check_trade(trade: dict, live_row: pd.Series | None, inst_cfg: dict) -> dict:
    """Run all parity checks on one trade."""
    dec = inst_cfg['decimals']
    rr = inst_cfg['rr']
    be_hours = inst_cfg['be_hours']
    be_offset = inst_cfg['be_offset']

    rng = trade['range']
    fill = trade['fill']
    close = trade['close']
    be = trade['be']

    # If no close log line but we have CSV data, reconstruct close
    if close is None and trade.get('close_from_csv') and live_row is not None:
        close = {
            'ts': dt.datetime.combine(trade['date'], dt.time(16, 0)),  # approximate
            'direction': fill['direction'],
            'result': live_row.get('result', 'TIME'),
            'entry': live_row['entry'],
            'exit': live_row['exit'],
            'pnl_per_unit': live_row['pnl_per_unit'],
            'pnl_total': live_row['pnl_total'],
        }
        # Use actual timestamp from CSV if available
        if pd.notna(live_row.get('timestamp')):
            close['ts'] = pd.to_datetime(live_row['timestamp']).to_pydatetime().replace(tzinfo=None)

    if close is None:
        return None

    checks = {
        'date': trade['date'],
        'instrument': trade['instrument'],
        'direction': fill['direction'],
    }

    # ── 1. RANGE CHECK ────────────────────────────────────────────────────────
    if rng:
        range_high = rng['range_high']
        range_low = rng['range_low']
        range_size = round(range_high - range_low, dec + 2)
        checks['range_high'] = range_high
        checks['range_low'] = range_low
        checks['range_size'] = range_size

        # Verify against live CSV if available
        if live_row is not None and pd.notna(live_row.get('range_high')):
            csv_rh = live_row['range_high']
            csv_rl = live_row['range_low']
            checks['csv_range_match'] = (abs(csv_rh - range_high) < 0.01 and
                                          abs(csv_rl - range_low) < 0.01)
        else:
            checks['csv_range_match'] = None
    else:
        range_high = range_low = range_size = None
        checks['range_high'] = checks['range_low'] = checks['range_size'] = None
        checks['csv_range_match'] = None

    # ── 2. MATH CHECK: planned orders correct? ────────────────────────────────
    planned = {p['direction']: p for p in trade['planned_orders']}
    math_errors = []

    if range_high is not None and range_low is not None:
        # Expected LONG: entry=range_high, SL=range_low, TP=range_high + rr*range_size
        if 'LONG' in planned:
            p = planned['LONG']
            exp_long_entry = range_high
            exp_long_sl = range_low
            exp_long_tp = round(range_high + rr * range_size, dec)
            # Live system places stop orders at range boundary (no pre-slippage)
            if abs(p['planned_entry'] - exp_long_entry) > 0.02:
                math_errors.append(f"LONG entry: planned={p['planned_entry']} expected={exp_long_entry}")
            if abs(p['planned_sl'] - exp_long_sl) > 0.02:
                math_errors.append(f"LONG SL: planned={p['planned_sl']} expected={exp_long_sl}")
            if abs(p['planned_tp'] - exp_long_tp) > 0.5:
                math_errors.append(f"LONG TP: planned={p['planned_tp']} expected={exp_long_tp}")

        if 'SHORT' in planned:
            p = planned['SHORT']
            exp_short_entry = range_low
            exp_short_sl = range_high
            exp_short_tp = round(range_low - rr * range_size, dec)
            if abs(p['planned_entry'] - exp_short_entry) > 0.02:
                math_errors.append(f"SHORT entry: planned={p['planned_entry']} expected={exp_short_entry}")
            if abs(p['planned_sl'] - exp_short_sl) > 0.02:
                math_errors.append(f"SHORT SL: planned={p['planned_sl']} expected={exp_short_sl}")
            if abs(p['planned_tp'] - exp_short_tp) > 0.5:
                math_errors.append(f"SHORT TP: planned={p['planned_tp']} expected={exp_short_tp}")

    checks['math_ok'] = len(math_errors) == 0
    checks['math_errors'] = '; '.join(math_errors) if math_errors else ''

    # ── 3. FILL CHECK: slippage ───────────────────────────────────────────────
    fill_dir = fill['direction']
    fill_px = fill['fill_price']
    if fill_dir in planned:
        planned_entry = planned[fill_dir]['planned_entry']
        slippage = abs(fill_px - planned_entry)
        checks['planned_entry'] = planned_entry
        checks['fill_price'] = fill_px
        checks['entry_slippage'] = round(slippage, dec + 2)
    else:
        checks['planned_entry'] = None
        checks['fill_price'] = fill_px
        checks['entry_slippage'] = None

    # ── 4. BE CHECK: timing and offset ────────────────────────────────────────
    if be:
        entry_time = fill['ts']
        be_time = be['ts']
        be_elapsed_min = (be_time - entry_time).total_seconds() / 60
        expected_be_min = be_hours * 60

        # Check timing (allow 1-minute tolerance for poll interval)
        be_timing_ok = abs(be_elapsed_min - expected_be_min) < 2

        # Check offset
        if fill_dir == 'LONG':
            expected_be_sl = fill_px + be_offset
        else:
            expected_be_sl = fill_px - be_offset
        be_offset_ok = abs(be['new_sl'] - expected_be_sl) < 0.02

        checks['be_applied'] = True
        checks['be_elapsed_min'] = round(be_elapsed_min, 1)
        checks['be_expected_min'] = expected_be_min
        checks['be_timing_ok'] = be_timing_ok
        checks['be_new_sl'] = be['new_sl']
        checks['be_expected_sl'] = round(expected_be_sl, dec)
        checks['be_offset_ok'] = be_offset_ok
    else:
        checks['be_applied'] = False
        # Was BE expected? If trade lasted > be_hours and wasn't closed
        if fill and close:
            hold_min = (close['ts'] - fill['ts']).total_seconds() / 60
            checks['be_expected'] = hold_min >= (be_hours * 60)
        else:
            checks['be_expected'] = None
        checks['be_elapsed_min'] = None
        checks['be_expected_min'] = be_hours * 60
        checks['be_timing_ok'] = None
        checks['be_new_sl'] = None
        checks['be_expected_sl'] = None
        checks['be_offset_ok'] = None

    # ── 5. EXIT CHECK ─────────────────────────────────────────────────────────
    result = close['result']
    exit_px = close['exit']
    checks['result'] = result
    checks['exit_price'] = exit_px

    # Verify result makes sense
    exit_errors = []
    if result == 'TP':
        # Exit should be near TP
        tp = fill['fill_tp']
        tp_diff = abs(exit_px - tp)
        # IBKR may fill limit orders with price improvement, especially on Gold
        if tp_diff > 3.0:
            exit_errors.append(f'TP exit far from target: exit={exit_px} tp={tp} diff={tp_diff}')
    elif result == 'SL':
        # Exit should be near SL (original or BE-adjusted)
        if be and be.get('new_sl'):
            expected_sl = be['new_sl']
        else:
            expected_sl = fill['fill_sl']
        sl_diff = abs(exit_px - expected_sl)
        if sl_diff > 2.0:
            exit_errors.append(f'SL exit far from stop: exit={exit_px} sl={expected_sl} diff={sl_diff}')

    checks['exit_ok'] = len(exit_errors) == 0
    checks['exit_errors'] = '; '.join(exit_errors) if exit_errors else ''

    # ── 6. P&L CHECK ──────────────────────────────────────────────────────────
    pnl_logged = close['pnl_per_unit']
    if fill_dir == 'LONG':
        pnl_expected = exit_px - fill_px
    else:
        pnl_expected = fill_px - exit_px

    pnl_diff = abs(pnl_logged - pnl_expected)
    checks['pnl_per_unit_logged'] = pnl_logged
    checks['pnl_per_unit_expected'] = round(pnl_expected, dec + 2)
    checks['pnl_ok'] = pnl_diff < 0.02
    checks['pnl_total'] = close['pnl_total']
    checks['hold_minutes'] = round((close['ts'] - fill['ts']).total_seconds() / 60, 1)

    # ── OVERALL GRADE ─────────────────────────────────────────────────────────
    all_ok = all([
        checks['math_ok'],
        checks['exit_ok'],
        checks.get('pnl_ok', True),
    ])
    be_ok = checks.get('be_timing_ok') is None or (checks['be_timing_ok'] and checks['be_offset_ok'])

    if all_ok and be_ok and (checks['entry_slippage'] or 0) < 1.0:
        checks['grade'] = 'EXCELLENT'
    elif all_ok and be_ok:
        checks['grade'] = 'GOOD'
    elif all_ok:
        checks['grade'] = 'OK'
    else:
        checks['grade'] = 'ISSUE'

    return checks


# ── Display ───────────────────────────────────────────────────────────────────

def print_report(results: list[dict], inst_configs: dict):
    """Pretty-print reconciliation report."""
    if not results:
        print("No trades to reconcile.")
        return

    GRADE_COLORS = {
        'EXCELLENT': '\033[92m',
        'GOOD': '\033[93m',
        'OK': '\033[93m',
        'ISSUE': '\033[91m',
    }
    RESET = '\033[0m'

    print()
    print("=" * 120)
    print("  LIVE TRADE PARITY RECONCILIATION")
    print("=" * 120)

    for r in results:
        cfg = inst_configs.get(r['instrument'], {})
        dec = cfg.get('decimals', 2)
        color = GRADE_COLORS.get(r['grade'], '')

        print(f"\n  {'─' * 116}")
        print(f"  {r['date']}  {r['instrument']}  {r['direction']}  "
              f"[{color}{r['grade']}{RESET}]"
              f"  (held {r['hold_minutes']:.0f} min)")
        print(f"  {'─' * 116}")

        # Range
        if r.get('range_high') is not None:
            print(f"  Range:       H={r['range_high']:.{dec}f}  "
                  f"L={r['range_low']:.{dec}f}  "
                  f"Size={r['range_size']:.{dec}f}")

        # Math check
        sym = '\033[92m[PASS]\033[0m' if r['math_ok'] else '\033[91m[FAIL]\033[0m'
        print(f"  Math:        {sym}  Order levels calculated from range")
        if r['math_errors']:
            print(f"               {r['math_errors']}")

        # Fill / slippage
        if r.get('planned_entry') is not None:
            slip_str = f"{r['entry_slippage']:.{dec}f}" if r['entry_slippage'] is not None else 'n/a'
            slip_warn = '  ⚠ HIGH' if r.get('entry_slippage', 0) > 1.0 else ''
            print(f"  Fill:        Planned={r['planned_entry']:.{dec}f}  "
                  f"Actual={r['fill_price']:.{dec}f}  "
                  f"Slippage={slip_str}{slip_warn}")

        # BE check
        if r['be_applied']:
            timing_sym = '\033[92m[PASS]\033[0m' if r['be_timing_ok'] else '\033[91m[FAIL]\033[0m'
            offset_sym = '\033[92m[PASS]\033[0m' if r['be_offset_ok'] else '\033[91m[FAIL]\033[0m'
            print(f"  BE Timing:   {timing_sym}  "
                  f"Applied at {r['be_elapsed_min']:.0f}min "
                  f"(expected {r['be_expected_min']:.0f}min)")
            print(f"  BE Offset:   {offset_sym}  "
                  f"New SL={r['be_new_sl']:.{dec}f}  "
                  f"Expected={r['be_expected_sl']:.{dec}f}")
        else:
            if r.get('be_expected'):
                print(f"  BE:          \033[93m[WARN]\033[0m  "
                      f"Not applied but trade held > {r['be_expected_min']:.0f}min")
            else:
                print(f"  BE:          Not triggered (trade ended before {r['be_expected_min']:.0f}min)")

        # Exit
        sym = '\033[92m[PASS]\033[0m' if r['exit_ok'] else '\033[91m[FAIL]\033[0m'
        print(f"  Exit:        {sym}  {r['result']}  "
              f"at {r['exit_price']:.{dec}f}")
        if r['exit_errors']:
            print(f"               {r['exit_errors']}")

        # P&L
        sym = '\033[92m[PASS]\033[0m' if r.get('pnl_ok', True) else '\033[91m[FAIL]\033[0m'
        print(f"  P&L:         {sym}  "
              f"Logged={r['pnl_per_unit_logged']:+.{dec}f}/unit  "
              f"Expected={r['pnl_per_unit_expected']:+.{dec}f}/unit  "
              f"Total=${r['pnl_total']:+.2f}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 120}")
    print("  SUMMARY")
    print(f"{'=' * 120}")

    n = len(results)
    grades = {}
    for r in results:
        grades[r['grade']] = grades.get(r['grade'], 0) + 1

    math_pass = sum(1 for r in results if r['math_ok'])
    exit_pass = sum(1 for r in results if r['exit_ok'])
    pnl_pass = sum(1 for r in results if r.get('pnl_ok', True))
    be_trades = [r for r in results if r['be_applied']]
    be_timing_pass = sum(1 for r in be_trades if r['be_timing_ok'])
    be_offset_pass = sum(1 for r in be_trades if r['be_offset_ok'])

    print(f"\n  Trades analyzed: {n}")
    print(f"  Math check:   {math_pass}/{n} pass")
    print(f"  Exit check:   {exit_pass}/{n} pass")
    print(f"  P&L check:    {pnl_pass}/{n} pass")
    if be_trades:
        print(f"  BE timing:    {be_timing_pass}/{len(be_trades)} pass")
        print(f"  BE offset:    {be_offset_pass}/{len(be_trades)} pass")

    print(f"\n  Grades:")
    for grade in ['EXCELLENT', 'GOOD', 'OK', 'ISSUE']:
        count = grades.get(grade, 0)
        if count > 0:
            color = GRADE_COLORS.get(grade, '')
            print(f"    {color}{grade}{RESET}: {count}")

    # Slippage stats
    slips = [r['entry_slippage'] for r in results if r.get('entry_slippage') is not None]
    if slips:
        print(f"\n  Entry slippage (stop order fill vs planned level):")
        print(f"    Mean: {sum(slips)/len(slips):.4f}")
        print(f"    Max:  {max(slips):.4f}")
        print(f"    Min:  {min(slips):.4f}")

    # Total P&L
    total_pnl = sum(r['pnl_total'] for r in results)
    wins = sum(1 for r in results if r['pnl_total'] > 0)
    losses = sum(1 for r in results if r['pnl_total'] < 0)
    print(f"\n  Live P&L:  ${total_pnl:+.2f}  ({wins}W / {losses}L = {wins/n*100:.0f}% WR)")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reconcile live trades — validate math, fills, BE, exits, P&L")
    parser.add_argument("--date", default=None,
                        help="Filter to specific date (YYYY-MM-DD)")
    parser.add_argument("--save", action="store_true",
                        help="Save reconciliation CSV")
    args = parser.parse_args()

    print("Live Trade Parity Reconciliation")
    print("=" * 50)

    # Load config
    inst_configs = load_instrument_configs()
    print(f"  Instruments: {', '.join(inst_configs.keys())}")

    # Load live trade CSVs
    live_trades = load_live_trades()
    if len(live_trades) == 0:
        print("  No live trades found.")
        return
    print(f"  Live trades: {len(live_trades)}")

    # Parse log
    log_path = ROOT / 'v5_xauusd_orb' / 'logs' / 'orb_multi_live.log'
    if not log_path.exists():
        print(f"  Log not found: {log_path}")
        return

    events = parse_log_events(str(log_path))
    print(f"  Log events parsed: {len(events)}")

    log_trades = group_events_by_trade(events)
    print(f"  Log trades found: {len(log_trades)}")

    # Filter by date if specified
    if args.date:
        target = dt.date.fromisoformat(args.date)
        log_trades = [t for t in log_trades if t['date'] == target]

    # Run checks on each trade
    results = []
    for lt in sorted(log_trades, key=lambda x: (x['date'], x['instrument'])):
        inst = lt['instrument']
        if inst not in inst_configs:
            continue

        # Find matching CSV row for cross-validation
        csv_match = None
        if len(live_trades) > 0:
            mask = (live_trades['date'] == lt['date']) & (live_trades['instrument'] == inst)
            matches = live_trades[mask]
            if len(matches) > 0:
                csv_match = matches.iloc[0]

        result = check_trade(lt, csv_match, inst_configs[inst])
        if result is not None:
            results.append(result)

    # Display
    print_report(results, inst_configs)

    # Save CSV
    if args.save:
        out_path = ROOT / 'v5_xauusd_orb' / 'logs' / 'reconciliation.csv'
        df = pd.DataFrame(results)
        df.to_csv(out_path, index=False)
        print(f"  Saved to {out_path}")


if __name__ == "__main__":
    main()
