"""
research_5m.py -- XAUUSD backtest on 5-minute bars (no resample to 1h).

Key difference from research_no_be.py:
- Uses raw 5-min bars for trade monitoring (12 bars per hour instead of 1)
- Entry fills happen on the exact 5-min bar that crosses the level
- BE/time-exit triggers are counted in 5-min bars (12 bars = 1 hour)
- This is MUCH closer to what the live script experiences with stop orders

Usage:
  python -m v5_xauusd_orb.research_5m
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class InstrumentConfig:
    symbol: str
    data_file: str
    pip_size: float
    spread_per_side: float
    slippage: float
    point_value: float
    lot_label: str
    range_start: int
    range_end: int
    trade_start: int
    trade_end: int
    min_range_pct: float = 0.01
    max_range_pct: float = 2.0
    skip_weekdays: list = None

    def __post_init__(self):
        if self.skip_weekdays is None:
            self.skip_weekdays = [2]


XAUUSD = InstrumentConfig(
    symbol='XAUUSD',
    data_file='data/5m_csv/xauusd_5m.csv',
    pip_size=0.01,
    spread_per_side=0.10,
    slippage=0.15,
    point_value=1.0,
    lot_label='1 oz',
    range_start=0, range_end=6,
    trade_start=8, trade_end=16,
    min_range_pct=0.05, max_range_pct=2.0,
)


def load_5m(csv_path: str) -> pd.DataFrame:
    """Load raw 5-min bars, no resampling."""
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


def backtest_orb_5m(
    df: pd.DataFrame,
    inst: InstrumentConfig,
    rr: float = 2.0,
    be_bars_5m: int | None = None,
    be_offset: float = 0.0,
    time_exit_bars_5m: int | None = None,
    qty: int = 1,
) -> pd.DataFrame:
    """
    ORB backtest on 5-minute bars.

    Parameters:
    - be_bars_5m: number of 5-min bars before BE triggers (12 = 1h, 24 = 2h, None = disabled)
    - time_exit_bars_5m: close at market after N 5-min bars (12 = 1h, None = disabled)
    """
    results = []
    spread = inst.spread_per_side
    slip = inst.slippage

    for day, day_df in df.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5:
            continue
        if weekday in inst.skip_weekdays:
            continue

        # Range session (hourly filter on 5-min bars)
        asian = day_df[(day_df['hour'] >= inst.range_start) &
                       (day_df['hour'] < inst.range_end)]
        if len(asian) < 36:  # at least 3 hours of 5-min bars (36 bars)
            continue

        range_high = asian['high'].max()
        range_low = asian['low'].min()
        range_size = range_high - range_low
        if range_size <= 0:
            continue

        mid_price = (range_high + range_low) / 2
        range_pct = range_size / mid_price * 100
        if range_pct < inst.min_range_pct or range_pct > inst.max_range_pct:
            continue

        # Trade window (5-min bars)
        window = day_df[(day_df['hour'] >= inst.trade_start) &
                        (day_df['hour'] < inst.trade_end)]
        if len(window) == 0:
            continue

        # Entry levels
        long_entry = range_high + slip
        long_sl = range_low
        long_tp = range_high + rr * range_size

        short_entry = range_low - slip
        short_sl = range_high
        short_tp = range_low - rr * range_size

        # Find entry on 5-min bars
        direction = None
        entry_px = None
        entry_bar_i = None

        for i, (idx, bar) in enumerate(window.iterrows()):
            if bar['high'] >= range_high:
                direction, entry_px, entry_bar_i = 'LONG', long_entry, i
                sl_px, tp_px = long_sl, long_tp
                break
            if bar['low'] <= range_low:
                direction, entry_px, entry_bar_i = 'SHORT', short_entry, i
                sl_px, tp_px = short_sl, short_tp
                break

        if direction is None:
            continue

        # Monitor trade on 5-min bars
        monitor = window.iloc[entry_bar_i + 1:]
        current_sl = sl_px
        be_triggered = False
        result = 'EOD'
        exit_px = None
        hold_bars = len(monitor)
        entry_time = window.index[entry_bar_i]

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            # Time-based exit
            if time_exit_bars_5m is not None and j >= time_exit_bars_5m:
                exit_px = bar['open']
                if direction == 'LONG':
                    exit_px -= slip
                else:
                    exit_px += slip
                result = 'TIME_EXIT'
                hold_bars = j + 1
                break

            # BE trigger
            if not be_triggered and be_bars_5m is not None and j >= be_bars_5m:
                be_triggered = True
                if direction == 'LONG':
                    current_sl = entry_px + be_offset
                else:
                    current_sl = entry_px - be_offset

            # Check SL / TP
            if direction == 'LONG':
                sl_hit = bar['low'] <= current_sl
                tp_hit = bar['high'] >= tp_px
            else:
                sl_hit = bar['high'] >= current_sl
                tp_hit = bar['low'] <= tp_px

            if sl_hit:
                if direction == 'LONG':
                    exit_px = current_sl - slip
                else:
                    exit_px = current_sl + slip
                result = 'BE' if be_triggered else 'SL'
                hold_bars = j + 1
                break

            if tp_hit:
                exit_px = tp_px
                result = 'TP'
                hold_bars = j + 1
                break

        if exit_px is None:
            if len(monitor) > 0:
                exit_px = monitor['close'].iloc[-1]
                if direction == 'LONG':
                    exit_px -= slip
                else:
                    exit_px += slip
            else:
                exit_px = entry_px

        if direction == 'LONG':
            raw_pnl = (exit_px - entry_px)
        else:
            raw_pnl = (entry_px - exit_px)

        pnl_price = raw_pnl - (spread * 2)
        pnl_usd = pnl_price * inst.point_value * qty

        results.append({
            'date': day,
            'direction': direction,
            'result': result,
            'entry': round(entry_px, 6),
            'exit': round(exit_px, 6),
            'sl': round(sl_px, 6),
            'tp': round(tp_px, 6),
            'range_size': round(range_size, 6),
            'pnl_price': round(pnl_price, 6),
            'pnl_usd': round(pnl_usd, 2),
            'hold_bars': hold_bars,
            'entry_time': entry_time,
        })

    return pd.DataFrame(results)


def compute_stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {'trades': 0, 'sharpe': 0, 'pf': 0, 'max_dd': 0, 'TP%': 0, 'SL%': 0, 'BE%': 0, 'total_pnl': 0}
    n = len(df)
    tp_n = (df['result'] == 'TP').sum()
    sl_n = (df['result'] == 'SL').sum()
    be_n = (df['result'] == 'BE').sum()

    eq = df['pnl_usd'].cumsum()
    dd = (eq - eq.cummax()).min()
    sharpe = (df['pnl_usd'].mean() / df['pnl_usd'].std() * np.sqrt(252)
              if df['pnl_usd'].std() > 0 else 0)

    gp = df.loc[df['pnl_usd'] > 0, 'pnl_usd'].sum()
    gl = df.loc[df['pnl_usd'] < 0, 'pnl_usd'].abs().sum()
    pf = gp / gl if gl > 0 else float('inf')

    return {
        'trades': n,
        'TP%': round(tp_n / n * 100, 1),
        'SL%': round(sl_n / n * 100, 1),
        'BE%': round(be_n / n * 100, 1),
        'total_pnl': round(df['pnl_usd'].sum(), 2),
        'sharpe': round(sharpe, 2),
        'pf': round(pf, 2),
        'max_dd': round(dd, 2),
    }


def max_consec_loss(daily_pnl: pd.Series) -> int:
    streak = 0
    max_streak = 0
    for v in daily_pnl:
        if v < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def main():
    print("=" * 95)
    print("  XAUUSD 5-MINUTE BAR BACKTEST")
    print("  (12x finer resolution than 1h — closer to live stop-order fills)")
    print("=" * 95)

    df = load_5m(str(ROOT / XAUUSD.data_file))
    print(f"  Loaded {len(df):,} 5-min bars ({df.index.min().date()} to {df.index.max().date()})")

    is_end = pd.Timestamp('2020-12-31', tz='UTC')
    oos_start = pd.Timestamp('2021-01-01', tz='UTC')

    # ═══════════════════════════════════════════════════════════════════════
    # 1. BASELINE: 5m no-BE vs 1h no-BE comparison
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  1. BASELINE COMPARISON: 5m bars vs 1h bars (no-BE)")
    print("=" * 95)

    # 5m
    trades_5m = backtest_orb_5m(df, XAUUSD, rr=2.0, be_bars_5m=None)
    s5 = compute_stats(trades_5m)
    d5 = trades_5m.groupby('date')['pnl_usd'].sum()
    mcl5 = max_consec_loss(d5)

    is5 = compute_stats(backtest_orb_5m(df.loc[:is_end], XAUUSD, rr=2.0, be_bars_5m=None))
    oos5 = compute_stats(backtest_orb_5m(df.loc[oos_start:], XAUUSD, rr=2.0, be_bars_5m=None))

    # 1h (resample)
    from v5_xauusd_orb.research_no_be import (
        load_ohlcv_csv, backtest_orb as backtest_1h, compute_stats as stats_1h,
        max_consec_loss as mcl_1h, INSTRUMENTS
    )
    ohlcv_1h = load_ohlcv_csv(str(ROOT / XAUUSD.data_file))
    trades_1h = backtest_1h(ohlcv_1h, INSTRUMENTS['XAUUSD'], rr=2.0, be_bars=None)
    s1 = stats_1h(trades_1h)
    d1 = trades_1h.groupby('date')['pnl_usd'].sum()
    mcl1 = mcl_1h(d1)
    is1 = stats_1h(backtest_1h(ohlcv_1h.loc[:is_end], INSTRUMENTS['XAUUSD'], rr=2.0, be_bars=None))
    oos1 = stats_1h(backtest_1h(ohlcv_1h.loc[oos_start:], INSTRUMENTS['XAUUSD'], rr=2.0, be_bars=None))

    print(f"\n  {'Resolution':>12} | {'Trades':>6} | {'TP%':>5} | {'SL%':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'MaxDD':>10} | {'MCL':>3} | {'IS Sh':>5} | {'OOS Sh':>6} | {'Total P&L':>11}")
    print(f"  {'-'*12}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*10}-+-"
          f"{'-'*3}-+-{'-'*5}-+-{'-'*6}-+-{'-'*11}")
    print(f"  {'1h bars':>12} | {s1['trades']:>6} | {s1['TP%']:>4.1f}% | {s1['SL%']:>4.1f}% | "
          f"{s1['sharpe']:>7.2f} | {s1['pf']:>5.2f} | ${s1['max_dd']:>+9,.2f} | "
          f"{mcl1:>3} | {is1['sharpe']:>5.2f} | {oos1['sharpe']:>6.2f} | ${s1['total_pnl']:>+10,.2f}")
    print(f"  {'5m bars':>12} | {s5['trades']:>6} | {s5['TP%']:>4.1f}% | {s5['SL%']:>4.1f}% | "
          f"{s5['sharpe']:>7.2f} | {s5['pf']:>5.2f} | ${s5['max_dd']:>+9,.2f} | "
          f"{mcl5:>3} | {is5['sharpe']:>5.2f} | {oos5['sharpe']:>6.2f} | ${s5['total_pnl']:>+10,.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. TRADE START SWEEP (5m bars)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  2. TRADE START SWEEP (5m bars, trade_end=16)")
    print("=" * 95)

    print(f"\n  {'Start':>5} | {'Trades':>6} | {'TP%':>5} | {'SL%':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'MaxDD':>10} | {'MCL':>3} | {'IS Sh':>5} | {'OOS Sh':>6}")
    print(f"  {'-'*5}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*10}-+-"
          f"{'-'*3}-+-{'-'*5}-+-{'-'*6}")

    for start in range(6, 13):
        cfg = InstrumentConfig(
            symbol='XAUUSD', data_file=XAUUSD.data_file, pip_size=0.01,
            spread_per_side=0.10, slippage=0.15, point_value=1.0, lot_label='1 oz',
            range_start=0, range_end=6, trade_start=start, trade_end=16,
            min_range_pct=0.05, max_range_pct=2.0,
        )
        trades = backtest_orb_5m(df, cfg, rr=2.0, be_bars_5m=None)
        s = compute_stats(trades)
        daily = trades.groupby('date')['pnl_usd'].sum()
        mcl = max_consec_loss(daily)
        is_s = compute_stats(backtest_orb_5m(df.loc[:is_end], cfg, rr=2.0, be_bars_5m=None))
        oos_s = compute_stats(backtest_orb_5m(df.loc[oos_start:], cfg, rr=2.0, be_bars_5m=None))
        marker = " << CURRENT" if start == 8 else ""
        print(f"  {start:>5} | {s['trades']:>6} | {s['TP%']:>4.1f}% | {s['SL%']:>4.1f}% | "
              f"{s['sharpe']:>7.2f} | {s['pf']:>5.2f} | ${s['max_dd']:>+9,.2f} | "
              f"{mcl:>3} | {is_s['sharpe']:>5.2f} | {oos_s['sharpe']:>6.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. TRADE END SWEEP (5m bars)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  3. TRADE END SWEEP (5m bars, trade_start=8)")
    print("=" * 95)

    print(f"\n  {'End':>5} | {'Trades':>6} | {'TP%':>5} | {'SL%':>5} | {'EOD%':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'MaxDD':>10} | {'MCL':>3} | {'OOS Sh':>6}")
    print(f"  {'-'*5}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*10}-+-"
          f"{'-'*3}-+-{'-'*6}")

    for end in range(10, 21):
        cfg = InstrumentConfig(
            symbol='XAUUSD', data_file=XAUUSD.data_file, pip_size=0.01,
            spread_per_side=0.10, slippage=0.15, point_value=1.0, lot_label='1 oz',
            range_start=0, range_end=6, trade_start=8, trade_end=end,
            min_range_pct=0.05, max_range_pct=2.0,
        )
        trades = backtest_orb_5m(df, cfg, rr=2.0, be_bars_5m=None)
        s = compute_stats(trades)
        if s['trades'] == 0:
            continue
        daily = trades.groupby('date')['pnl_usd'].sum()
        mcl = max_consec_loss(daily)
        eod_pct = round((trades['result'] == 'EOD').sum() / s['trades'] * 100, 1)
        oos_s = compute_stats(backtest_orb_5m(df.loc[oos_start:], cfg, rr=2.0, be_bars_5m=None))
        marker = " << CURRENT" if end == 16 else ""
        print(f"  {end:>5} | {s['trades']:>6} | {s['TP%']:>4.1f}% | {s['SL%']:>4.1f}% | "
              f"{eod_pct:>4.1f}% | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"${s['max_dd']:>+9,.2f} | {mcl:>3} | {oos_s['sharpe']:>6.2f}{marker}")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. TIME EXIT SWEEP (5m bars — 1h = 12 bars, 2h = 24, etc.)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  4. TIME EXIT SWEEP (5m bars, no-BE)")
    print("=" * 95)

    print(f"\n  {'Exit':>8} | {'Trades':>6} | {'TP%':>5} | {'SL%':>5} | {'TIME%':>5} | {'Sharpe':>7} | "
          f"{'PF':>5} | {'MaxDD':>10} | {'MCL':>3} | {'OOS Sh':>6}")
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*10}-+-"
          f"{'-'*3}-+-{'-'*6}")

    for minutes in [15, 30, 45, 60, 90, 120, 180, 240, None]:
        bars_5m = minutes // 5 if minutes is not None else None
        trades = backtest_orb_5m(df, XAUUSD, rr=2.0, be_bars_5m=None, time_exit_bars_5m=bars_5m)
        s = compute_stats(trades)
        if s['trades'] == 0:
            continue
        te_pct = round((trades['result'] == 'TIME_EXIT').sum() / s['trades'] * 100, 1)
        daily = trades.groupby('date')['pnl_usd'].sum()
        mcl = max_consec_loss(daily)
        oos_s = compute_stats(backtest_orb_5m(df.loc[oos_start:], XAUUSD, rr=2.0, be_bars_5m=None, time_exit_bars_5m=bars_5m))
        label = f"{minutes}min" if minutes is not None else "none"
        print(f"  {label:>8} | {s['trades']:>6} | {s['TP%']:>4.1f}% | {s['SL%']:>4.1f}% | "
              f"{te_pct:>4.1f}% | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
              f"${s['max_dd']:>+9,.2f} | {mcl:>3} | {oos_s['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. ENTRY TIMING ANALYSIS (5m bars — where exactly do entries happen?)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  5. ENTRY TIMING (5m bars — exact minute of entry)")
    print("=" * 95)

    trades_5m = backtest_orb_5m(df, XAUUSD, rr=2.0, be_bars_5m=None)
    trades_5m['entry_hour'] = pd.to_datetime(trades_5m['entry_time']).dt.hour
    trades_5m['entry_minute'] = pd.to_datetime(trades_5m['entry_time']).dt.minute

    print(f"\n  Entry hour distribution:")
    for h in range(8, 16):
        subset = trades_5m[trades_5m['entry_hour'] == h]
        n = len(subset)
        pct = n / len(trades_5m) * 100
        if n > 0:
            sub_sh = subset.pnl_usd.mean() / subset.pnl_usd.std() * np.sqrt(252) if subset.pnl_usd.std() > 0 else 0
            wr = (subset.pnl_usd > 0).mean() * 100
            bar = '#' * int(pct)
            print(f"    {h:02d}:xx UTC: {n:>4} ({pct:>5.1f}%) | "
                  f"Mean ${subset.pnl_usd.mean():>+6.2f} | Sh {sub_sh:>5.2f} | WR {wr:.0f}% | {bar}")

    # First 30 minutes breakdown
    print(f"\n  First hour breakdown (5-min slots):")
    first_hour = trades_5m[trades_5m['entry_hour'] == 8]
    for m in range(0, 60, 5):
        subset = first_hour[first_hour['entry_minute'] == m]
        n = len(subset)
        if n >= 5:
            sub_sh = subset.pnl_usd.mean() / subset.pnl_usd.std() * np.sqrt(252) if subset.pnl_usd.std() > 0 else 0
            print(f"    08:{m:02d}: N={n:>4} | Mean ${subset.pnl_usd.mean():>+6.2f} | Sh {sub_sh:.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. OOS VALIDATION (5m bars, current config)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*95}")
    print("  6. OOS VALIDATION + ANNUAL BREAKDOWN (5m bars, no-BE)")
    print("=" * 95)

    is_trades = backtest_orb_5m(df.loc[:is_end], XAUUSD, rr=2.0, be_bars_5m=None)
    oos_trades = backtest_orb_5m(df.loc[oos_start:], XAUUSD, rr=2.0, be_bars_5m=None)
    is_s = compute_stats(is_trades)
    oos_s = compute_stats(oos_trades)

    print(f"\n  IS  (2015-2020): Sharpe {is_s['sharpe']} | PF {is_s['pf']} | Trades {is_s['trades']}")
    print(f"  OOS (2021-2026): Sharpe {oos_s['sharpe']} | PF {oos_s['pf']} | Trades {oos_s['trades']}")

    trades_all = backtest_orb_5m(df, XAUUSD, rr=2.0, be_bars_5m=None)
    daily = trades_all.groupby('date')['pnl_usd'].sum()
    port_df = pd.DataFrame({'pnl': daily})
    port_df.index = pd.to_datetime(port_df.index)

    print(f"\n  Annual:")
    for yr, g in port_df.groupby(port_df.index.year):
        yr_pnl = g['pnl'].sum()
        yr_sh = g['pnl'].mean() / g['pnl'].std() * np.sqrt(252) if g['pnl'].std() > 0 else 0
        yr_eq = g['pnl'].cumsum()
        yr_dd = (yr_eq - yr_eq.cummax()).min()
        yr_mcl = max_consec_loss(g['pnl'])
        flag = " <<< LOSS" if yr_pnl < 0 else ""
        print(f"    {yr}: P&L ${yr_pnl:>+10,.2f} | Sh {yr_sh:>5.2f} | DD ${yr_dd:>+9,.2f} | MCL {yr_mcl}{flag}")

    print(f"\n{'='*95}")
    print("  DONE")
    print("=" * 95)


if __name__ == "__main__":
    main()
