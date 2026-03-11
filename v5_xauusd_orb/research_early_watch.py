"""
research_early_watch.py -- Test moving the order placement window earlier.

Current approach: Place stop orders at 8:00, miss 63% of crosses that happen 6-8.
Proposed: Place stop orders at 6:00 (or 7:00) to catch crosses as they happen.

The backtest simulates REALISTIC fills:
- Stop order placed at trade_start (e.g., 6:00)
- If price is already past the level → fill at market (open of that bar)
- If price crosses during the window → fill at the level (stop trigger)
- 60-min time exit from entry

This way, moving the window earlier means FEWER gap-opens and more level fills.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

RR = 2.0
SLIP = 0.15
SPREAD = 0.10
TIME_EXIT_BARS = 12  # 60 min in 5-min bars


def load_5m(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


def backtest_realistic(
    df: pd.DataFrame,
    trade_start: int = 8,
    trade_end: int = 16,
    range_start: int = 0,
    range_end: int = 6,
    time_exit_bars: int = 12,
) -> pd.DataFrame:
    """
    Backtest with REALISTIC fills:
    - At trade_start, check if price already past the level
    - If yes: fill at market (open of first bar) — NOT at level
    - If no: fill at level when it crosses (stop order behavior)
    """
    results = []

    for day, day_df in df.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5 or weekday == 2:
            continue

        asian = day_df[(day_df['hour'] >= range_start) & (day_df['hour'] < range_end)]
        if len(asian) < 36:
            continue

        rh = asian['high'].max()
        rl = asian['low'].min()
        rs = rh - rl
        if rs <= 0:
            continue
        mid = (rh + rl) / 2
        rpct = rs / mid * 100
        if rpct < 0.05 or rpct > 2.0:
            continue

        window = day_df[(day_df['hour'] >= trade_start) & (day_df['hour'] < trade_end)]
        if len(window) == 0:
            continue

        long_tp = rh + RR * rs
        short_tp = rl - RR * rs

        # Find entry
        direction = None
        entry_px = None
        entry_bar_i = None
        entry_type = None  # 'gap' or 'level'

        for i, (idx, bar) in enumerate(window.iterrows()):
            if i == 0:
                # First bar: check if price is ALREADY past the level
                # Gap-open long: open is above range_high
                if bar['open'] >= rh:
                    direction = 'LONG'
                    entry_px = bar['open'] + SLIP  # REALISTIC: fill at market open
                    entry_bar_i = i
                    entry_type = 'gap'
                    break
                # Gap-open short: open is below range_low
                if bar['open'] <= rl:
                    direction = 'SHORT'
                    entry_px = bar['open'] - SLIP  # REALISTIC: fill at market open
                    entry_bar_i = i
                    entry_type = 'gap'
                    break

            # Normal stop-order fill: price crosses level during the bar
            if bar['high'] >= rh and (direction is None):
                direction = 'LONG'
                entry_px = rh + SLIP  # Fill at stop level
                entry_bar_i = i
                entry_type = 'level'
                break
            if bar['low'] <= rl and (direction is None):
                direction = 'SHORT'
                entry_px = rl - SLIP  # Fill at stop level
                entry_bar_i = i
                entry_type = 'level'
                break

        if direction is None:
            continue

        sl_px = rl if direction == 'LONG' else rh
        tp_px = long_tp if direction == 'LONG' else short_tp

        # Monitor trade
        monitor = window.iloc[entry_bar_i + 1:]
        result = 'EOD'
        exit_px = None

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            if time_exit_bars is not None and j >= time_exit_bars:
                exit_px = bar['open']
                exit_px = exit_px - SLIP if direction == 'LONG' else exit_px + SLIP
                result = 'TIME_EXIT'
                break
            if direction == 'LONG':
                if bar['low'] <= sl_px:
                    exit_px = sl_px - SLIP
                    result = 'SL'
                    break
                if bar['high'] >= tp_px:
                    exit_px = tp_px
                    result = 'TP'
                    break
            else:
                if bar['high'] >= sl_px:
                    exit_px = sl_px + SLIP
                    result = 'SL'
                    break
                if bar['low'] <= tp_px:
                    exit_px = tp_px
                    result = 'TP'
                    break

        if exit_px is None:
            if len(monitor) > 0:
                exit_px = monitor['close'].iloc[-1]
                exit_px = exit_px - SLIP if direction == 'LONG' else exit_px + SLIP
            else:
                exit_px = entry_px

        raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
        pnl_usd = raw_pnl - SPREAD * 2

        entry_time = window.index[entry_bar_i]

        results.append({
            'date': day,
            'direction': direction,
            'result': result,
            'pnl_usd': round(pnl_usd, 2),
            'entry_type': entry_type,
            'entry_px': round(entry_px, 2),
            'range_high': round(rh, 2),
            'range_low': round(rl, 2),
            'range_size': round(rs, 2),
            'entry_hour': entry_time.hour,
            'entry_minute': entry_time.minute,
        })

    return pd.DataFrame(results)


def compute_stats(pnl: pd.Series) -> dict:
    if len(pnl) == 0:
        return {'n': 0, 'sharpe': 0, 'mean': 0, 'wr': 0, 'total': 0, 'pf': 0, 'max_dd': 0}
    n = len(pnl)
    mean = pnl.mean()
    std = pnl.std()
    sharpe = mean / std * np.sqrt(252) if std > 0 else 0
    wr = (pnl > 0).mean() * 100
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else float('inf')
    eq = pnl.cumsum()
    dd = (eq - eq.cummax()).min()
    return {'n': n, 'sharpe': round(sharpe, 2), 'mean': round(mean, 2),
            'wr': round(wr, 1), 'total': round(pnl.sum(), 2),
            'pf': round(pf, 2), 'max_dd': round(dd, 2)}


def max_consec_loss(pnl: pd.Series) -> int:
    streak = 0
    mx = 0
    for v in pnl:
        if v < 0:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 0
    return mx


def main():
    csv_path = str(ROOT / 'data' / '5m_csv' / 'xauusd_5m.csv')
    df = load_5m(csv_path)
    print(f"Loaded {len(df):,} 5-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = pd.Timestamp('2021-01-01').date()

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. MAIN SWEEP: Move order placement time from 6:00 to 10:00
    #    All with REALISTIC fills and 60-min time exit
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  1. ORDER PLACEMENT TIME SWEEP (realistic fills + 60min time exit)")
    print("     Range: 0-6 UTC. Orders placed at trade_start. trade_end=16.")
    print("=" * 100)

    print(f"\n  {'Start':>5} | {'N':>5} | {'Gap%':>5} | {'Lvl%':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'WR':>5} | {'MaxDD':>9} | {'MCL':>3} | {'Mean':>7} | "
          f"{'Total':>10} | {'OOS Sh':>6}")
    print(f"  {'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-"
          f"{'-'*9}-+-{'-'*3}-+-{'-'*7}-+-{'-'*10}-+-{'-'*6}")

    for start in range(6, 11):
        trades = backtest_realistic(df, trade_start=start, time_exit_bars=TIME_EXIT_BARS)
        if len(trades) == 0:
            continue

        oos = trades[trades['date'] >= oos_start]
        s = compute_stats(trades['pnl_usd'])
        so = compute_stats(oos['pnl_usd'])
        daily = trades.groupby('date')['pnl_usd'].sum()
        mcl = max_consec_loss(daily)

        gap_pct = (trades['entry_type'] == 'gap').mean() * 100
        lvl_pct = (trades['entry_type'] == 'level').mean() * 100

        marker = " << CURRENT" if start == 8 else ""
        print(f"  {start:>5} | {s['n']:>5} | {gap_pct:>4.1f}% | {lvl_pct:>4.1f}% | "
              f"{s['sharpe']:>7.2f} | {s['pf']:>5.2f} | {s['wr']:>4.1f}% | "
              f"${s['max_dd']:>+8.2f} | {mcl:>3} | ${s['mean']:>+6.2f} | "
              f"${s['total']:>+9.2f} | {so['sharpe']:>6.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. COMPARE: Old backtest (ideal fills) vs new realistic at each start
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  2. IDEAL vs REALISTIC FILLS side by side")
    print("=" * 100)

    from v5_xauusd_orb.research_5m import backtest_orb_5m, InstrumentConfig, compute_stats as cs5m

    base_cfg = InstrumentConfig(
        symbol='XAUUSD', data_file='data/5m_csv/xauusd_5m.csv', pip_size=0.01,
        spread_per_side=0.10, slippage=0.15, point_value=1.0, lot_label='1 oz',
        range_start=0, range_end=6, trade_start=8, trade_end=16,
        min_range_pct=0.05, max_range_pct=2.0,
    )

    print(f"\n  {'Start':>5} | {'Ideal Sh':>8} | {'Real Sh':>8} | {'Diff':>6} | "
          f"{'Ideal OOS':>9} | {'Real OOS':>9} | {'OOS Diff':>8}")
    print(f"  {'-'*5}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}-+-{'-'*9}-+-{'-'*9}-+-{'-'*8}")

    for start in range(6, 11):
        # Ideal (old backtest)
        cfg = InstrumentConfig(
            symbol='XAUUSD', data_file=base_cfg.data_file, pip_size=0.01,
            spread_per_side=0.10, slippage=0.15, point_value=1.0, lot_label='1 oz',
            range_start=0, range_end=6, trade_start=start, trade_end=16,
            min_range_pct=0.05, max_range_pct=2.0,
        )
        ideal = backtest_orb_5m(df, cfg, rr=2.0, be_bars_5m=None, time_exit_bars_5m=TIME_EXIT_BARS)
        si = cs5m(ideal)
        ideal_oos = backtest_orb_5m(df[df.index >= '2021-01-01'], cfg, rr=2.0, be_bars_5m=None, time_exit_bars_5m=TIME_EXIT_BARS)
        si_oos = cs5m(ideal_oos)

        # Realistic
        real = backtest_realistic(df, trade_start=start, time_exit_bars=TIME_EXIT_BARS)
        sr = compute_stats(real['pnl_usd'])
        real_oos = real[real['date'] >= oos_start]
        sr_oos = compute_stats(real_oos['pnl_usd'])

        marker = " << CURRENT" if start == 8 else ""
        print(f"  {start:>5} | {si['sharpe']:>8.2f} | {sr['sharpe']:>8.2f} | "
              f"{sr['sharpe']-si['sharpe']:>+5.2f} | "
              f"{si_oos['sharpe']:>9.2f} | {sr_oos['sharpe']:>9.2f} | "
              f"{sr_oos['sharpe']-si_oos['sharpe']:>+7.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DEEP DIVE: trade_start=6 — entry timing profile
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  3. ENTRY TIMING PROFILE: trade_start=6 (earliest possible)")
    print("=" * 100)

    t6 = backtest_realistic(df, trade_start=6, time_exit_bars=TIME_EXIT_BARS)
    print(f"\n  Entry hour distribution (trade_start=6):")
    for h in range(6, 16):
        subset = t6[t6['entry_hour'] == h]
        if len(subset) > 0:
            sh = compute_stats(subset['pnl_usd'])
            gap_n = (subset['entry_type'] == 'gap').sum()
            lvl_n = (subset['entry_type'] == 'level').sum()
            bar = '#' * max(1, int(len(subset) / len(t6) * 100))
            print(f"    {h:02d}:xx: N={len(subset):>4} (gap={gap_n:>3}, lvl={lvl_n:>3}) | "
                  f"Sh {sh['sharpe']:>5.2f} | WR {sh['wr']:.0f}% | ${sh['mean']:>+6.2f} | {bar}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. WHAT IF: Orders at 6:00, but SKIP gap-opens (only take level fills)?
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  4. FILTER: Place orders at X, but skip gap-opens (only level fills)")
    print("=" * 100)

    print(f"\n  {'Start':>5} | {'N (all)':>7} | {'N (lvl)':>7} | {'Sh all':>7} | {'Sh lvl':>7} | "
          f"{'OOS all':>7} | {'OOS lvl':>7}")
    print(f"  {'-'*5}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}")

    for start in range(6, 11):
        trades = backtest_realistic(df, trade_start=start, time_exit_bars=TIME_EXIT_BARS)
        lvl_only = trades[trades['entry_type'] == 'level']
        oos_all = trades[trades['date'] >= oos_start]
        oos_lvl = lvl_only[lvl_only['date'] >= oos_start]

        sa = compute_stats(trades['pnl_usd'])
        sl = compute_stats(lvl_only['pnl_usd'])
        soa = compute_stats(oos_all['pnl_usd'])
        sol = compute_stats(oos_lvl['pnl_usd'])

        marker = " << CURRENT" if start == 8 else ""
        print(f"  {start:>5} | {sa['n']:>7} | {sl['n']:>7} | {sa['sharpe']:>7.2f} | "
              f"{sl['sharpe']:>7.2f} | {soa['sharpe']:>7.2f} | {sol['sharpe']:>7.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. BEST COMBO: vary start + time exit with realistic fills
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  5. GRID: Trade start x Time exit (realistic fills)")
    print("=" * 100)

    print(f"\n  {'Start':>5} | {'TimeExit':>8} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | "
          f"{'MaxDD':>9} | {'Total':>10} | {'OOS Sh':>6}")
    print(f"  {'-'*5}-+-{'-'*8}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*9}-+-{'-'*10}-+-{'-'*6}")

    for start in [6, 7, 8]:
        for te_min in [30, 45, 60, 90, 120, None]:
            te_bars = te_min * 60 // 300 if te_min is not None else None  # convert min to 5m bars
            trades = backtest_realistic(df, trade_start=start, time_exit_bars=te_bars)
            if len(trades) == 0:
                continue
            oos = trades[trades['date'] >= oos_start]
            s = compute_stats(trades['pnl_usd'])
            so = compute_stats(oos['pnl_usd'])
            te_label = f"{te_min}min" if te_min else "none"
            marker = " << CUR" if start == 8 and te_min == 60 else ""
            print(f"  {start:>5} | {te_label:>8} | {s['n']:>5} | {s['sharpe']:>7.2f} | "
                  f"{s['pf']:>5.2f} | ${s['max_dd']:>+8.2f} | ${s['total']:>+9.2f} | "
                  f"{so['sharpe']:>6.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. ANNUAL BREAKDOWN for best realistic config
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("  6. ANNUAL BREAKDOWN: Best configs with realistic fills")
    print("=" * 100)

    for start, te_min in [(6, 60), (7, 60), (8, 60)]:
        te_bars = te_min * 60 // 300
        trades = backtest_realistic(df, trade_start=start, time_exit_bars=te_bars)
        daily = trades.groupby('date')['pnl_usd'].sum()
        port = pd.DataFrame({'pnl': daily})
        port.index = pd.to_datetime(port.index)
        s = compute_stats(trades['pnl_usd'])

        print(f"\n  Start={start}, TimeExit={te_min}min (N={s['n']}, Sharpe={s['sharpe']}):")
        for yr, g in port.groupby(port.index.year):
            yr_pnl = g['pnl'].sum()
            yr_sh = g['pnl'].mean() / g['pnl'].std() * np.sqrt(252) if g['pnl'].std() > 0 else 0
            yr_eq = g['pnl'].cumsum()
            yr_dd = (yr_eq - yr_eq.cummax()).min()
            yr_mcl = max_consec_loss(g['pnl'])
            flag = " <<< LOSS" if yr_pnl < 0 else ""
            print(f"    {yr}: P&L ${yr_pnl:>+8.2f} | Sh {yr_sh:>5.2f} | DD ${yr_dd:>+8.2f} | MCL {yr_mcl}{flag}")

    print(f"\n{'='*100}")
    print("  DONE")
    print("=" * 100)


if __name__ == "__main__":
    main()
