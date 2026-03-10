"""
research_no_be.py -- Critical research while Claude is unavailable.

Answers three questions:
1. Portfolio-level MaxConsecLoss with no-BE (4-pair: XAUUSD, EURUSD, USDJPY, AUDUSD)
2. Option C: time-based exit (close at market after N hours) as BE alternative
3. No-BE OOS validation (IS: 2015-2020, OOS: 2021-2026)

Uses 5-minute CSV data resampled to 1h, same engine logic as backtest_multi_fx.py.

Usage:
  python -m v5_xauusd_orb.research_no_be
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


# ── Instrument definitions ────────────────────────────────────────────────────

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


INSTRUMENTS = {
    'XAUUSD': InstrumentConfig(
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
    ),
    'EURUSD': InstrumentConfig(
        symbol='EURUSD',
        data_file='data/5m_csv/eurusd_5m.csv',
        pip_size=0.0001,
        spread_per_side=0.00003,
        slippage=0.00005,
        point_value=100000.0,
        lot_label='100k units',
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
    'USDJPY': InstrumentConfig(
        symbol='USDJPY',
        data_file='data/5m_csv/usdjpy_5m.csv',
        pip_size=0.01,
        spread_per_side=0.005,
        slippage=0.008,
        point_value=1000.0,
        lot_label='100k units',
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
    'AUDUSD': InstrumentConfig(
        symbol='AUDUSD',
        data_file='data/5m_csv/audusd_5m.csv',
        pip_size=0.0001,
        spread_per_side=0.00003,
        slippage=0.00005,
        point_value=100000.0,
        lot_label='100k units',
        range_start=0, range_end=6,
        trade_start=7, trade_end=16,
        min_range_pct=0.01, max_range_pct=2.0,
    ),
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_ohlcv_csv(csv_path: str) -> pd.DataFrame:
    """Load 5m CSV and resample to 1h OHLCV."""
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    ohlcv = pd.DataFrame({
        'open':  df['open'].resample('1h').first(),
        'high':  df['high'].resample('1h').max(),
        'low':   df['low'].resample('1h').min(),
        'close': df['close'].resample('1h').last(),
    }).dropna()
    return ohlcv


# ── Core backtest (identical to backtest_multi_fx.py) ─────────────────────────

def backtest_orb(
    ohlcv: pd.DataFrame,
    inst: InstrumentConfig,
    rr: float = 2.0,
    be_bars: int | None = None,
    be_offset: float = 0.0,
    max_entry_hour: int | None = None,   # Option C: max hour for entry (None = full window)
    time_exit_bars: int | None = None,   # Option C: close at market after N bars in trade
    qty: int = 1,
) -> pd.DataFrame:
    results = []
    ohlcv = ohlcv.copy()
    ohlcv['date'] = ohlcv.index.date
    ohlcv['hour'] = ohlcv.index.hour
    ohlcv['weekday'] = pd.to_datetime(ohlcv['date']).dt.weekday

    spread = inst.spread_per_side
    slip = inst.slippage

    for day, day_df in ohlcv.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5:
            continue
        if weekday in inst.skip_weekdays:
            continue

        asian = day_df[(day_df['hour'] >= inst.range_start) &
                       (day_df['hour'] < inst.range_end)]
        if len(asian) < 3:
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

        window = day_df[(day_df['hour'] >= inst.trade_start) &
                        (day_df['hour'] < inst.trade_end)]
        if len(window) == 0:
            continue

        long_entry = range_high + slip
        long_sl = range_low
        long_tp = range_high + rr * range_size

        short_entry = range_low - slip
        short_sl = range_high
        short_tp = range_low - rr * range_size

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

        monitor = window.iloc[entry_bar_i + 1:]
        current_sl = sl_px
        be_triggered = False
        result = 'EOD'
        exit_px = None
        hold_bars = len(monitor)

        for j, (idx, bar) in enumerate(monitor.iterrows()):
            # Time-based exit (Option C)
            if time_exit_bars is not None and j >= time_exit_bars:
                exit_px = bar['open']  # exit at market (open of next bar)
                if direction == 'LONG':
                    exit_px -= slip
                else:
                    exit_px += slip
                result = 'TIME_EXIT'
                hold_bars = j + 1
                break

            # BE trigger
            if not be_triggered and be_bars is not None and j >= be_bars:
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
        })

    return pd.DataFrame(results)


# ── Stats helpers ─────────────────────────────────────────────────────────────

def compute_stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {'trades': 0}
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
    """Max consecutive days with negative P&L."""
    streak = 0
    max_streak = 0
    for v in daily_pnl:
        if v < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ── Main research ─────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  RESEARCH: No-BE Analysis for 4-Pair Portfolio")
    print("  XAUUSD + EURUSD + USDJPY + AUDUSD")
    print("=" * 80)

    # Load all data
    data = {}
    for sym, inst in INSTRUMENTS.items():
        path = ROOT / inst.data_file
        print(f"Loading {sym}...", end=' ', flush=True)
        ohlcv = load_ohlcv_csv(str(path))
        print(f"{len(ohlcv):,} 1h bars ({ohlcv.index.min().date()} to {ohlcv.index.max().date()})")
        data[sym] = ohlcv

    # ═══════════════════════════════════════════════════════════════════════════
    # QUESTION 1: No-BE portfolio stats + MaxConsecLoss
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  Q1: No-BE Baselines + Portfolio MaxConsecLoss (2015-2026)")
    print("=" * 80)

    no_be_trades = {}
    for sym, inst in INSTRUMENTS.items():
        trades = backtest_orb(data[sym], inst, rr=2.0, be_bars=None, be_offset=0.0)
        no_be_trades[sym] = trades
        s = compute_stats(trades)
        daily = trades.groupby('date')['pnl_usd'].sum()
        mcl = max_consec_loss(daily)
        print(f"  {sym:8s}: {s['trades']:>5} trades | Sharpe {s['sharpe']:>5.2f} | "
              f"PF {s['pf']:>5.2f} | MaxDD ${s['max_dd']:>+10,.2f} | "
              f"MaxConsecLoss(days) {mcl}")

    # Portfolio-level
    daily_pnls = {}
    for sym, trades in no_be_trades.items():
        if len(trades) > 0:
            daily_pnls[sym] = trades.groupby('date')['pnl_usd'].sum()

    combined = pd.DataFrame(daily_pnls).fillna(0)
    portfolio_daily = combined.sum(axis=1)
    port_total = portfolio_daily.sum()
    port_sharpe = (portfolio_daily.mean() / portfolio_daily.std() * np.sqrt(252)
                   if portfolio_daily.std() > 0 else 0)
    eq = portfolio_daily.cumsum()
    port_dd = (eq - eq.cummax()).min()
    gp = portfolio_daily[portfolio_daily > 0].sum()
    gl = portfolio_daily[portfolio_daily < 0].abs().sum()
    port_pf = gp / gl if gl > 0 else float('inf')
    port_mcl = max_consec_loss(portfolio_daily)

    # Also compute max consecutive loss in terms of trades (across all instruments)
    all_trades_sorted = pd.concat(
        [t.assign(symbol=sym) for sym, t in no_be_trades.items()]
    ).sort_values('date')
    trade_mcl = 0
    streak = 0
    for _, row in all_trades_sorted.iterrows():
        if row['pnl_usd'] < 0:
            streak += 1
            trade_mcl = max(trade_mcl, streak)
        else:
            streak = 0

    print(f"\n  PORTFOLIO (4-pair combined):")
    print(f"    Total P&L:       ${port_total:+,.2f}")
    print(f"    Sharpe:          {port_sharpe:.2f}")
    print(f"    Profit Factor:   {port_pf:.2f}")
    print(f"    Max Drawdown:    ${port_dd:+,.2f}")
    print(f"    MaxConsecLoss (losing days):  {port_mcl}")
    print(f"    MaxConsecLoss (losing trades): {trade_mcl}")
    print(f"    Trading days:    {len(portfolio_daily)}")

    # Show worst losing streaks
    print(f"\n  Worst losing streaks (portfolio daily P&L):")
    streaks = []
    current_start = None
    current_sum = 0
    current_len = 0
    for date, pnl in portfolio_daily.items():
        if pnl < 0:
            if current_start is None:
                current_start = date
            current_sum += pnl
            current_len += 1
        else:
            if current_len >= 3:
                streaks.append((current_start, current_len, current_sum))
            current_start = None
            current_sum = 0
            current_len = 0
    if current_len >= 3:
        streaks.append((current_start, current_len, current_sum))
    streaks.sort(key=lambda x: x[2])  # sort by total loss
    for start, length, total in streaks[:10]:
        print(f"    {start}: {length} days, ${total:+,.2f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # QUESTION 2: Option C -- time-based exit sweeps
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  Q2: Option C — Time-Based Exit (close at market after N hours)")
    print("=" * 80)

    time_exit_hours = [1, 2, 3, 4, 5, 6, None]  # None = no time exit (pure SL/TP/EOD)

    for sym, inst in INSTRUMENTS.items():
        print(f"\n  {sym}:")
        print(f"  {'Hours':>6} | {'Trades':>6} | {'TP%':>5} | {'SL%':>5} | "
              f"{'TIME%':>5} | {'Sharpe':>7} | {'PF':>5} | {'MaxDD':>11} | {'MCL':>3}")
        print(f"  {'-'*6}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-"
              f"{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*11}-+-{'-'*3}")

        for hours in time_exit_hours:
            bars = hours if hours is not None else None
            trades = backtest_orb(
                data[sym], inst, rr=2.0,
                be_bars=None, be_offset=0.0,
                time_exit_bars=bars,
            )
            s = compute_stats(trades)
            if s['trades'] == 0:
                continue
            te_n = (trades['result'] == 'TIME_EXIT').sum()
            te_pct = round(te_n / s['trades'] * 100, 1)
            daily = trades.groupby('date')['pnl_usd'].sum()
            mcl = max_consec_loss(daily)
            label = f"{hours}h" if hours is not None else "none"
            print(f"  {label:>6} | {s['trades']:>6} | {s['TP%']:>4.1f}% | {s['SL%']:>4.1f}% | "
                  f"{te_pct:>4.1f}% | {s['sharpe']:>7.2f} | {s['pf']:>5.2f} | "
                  f"${s['max_dd']:>+10,.2f} | {mcl:>3}")

    # Portfolio-level Option C comparison
    print(f"\n  PORTFOLIO Option C Comparison:")
    print(f"  {'Hours':>6} | {'Sharpe':>7} | {'PF':>5} | {'MaxDD':>11} | {'MCL_days':>8} | {'MCL_trades':>10}")
    print(f"  {'-'*6}-+-{'-'*7}-+-{'-'*5}-+-{'-'*11}-+-{'-'*8}-+-{'-'*10}")

    for hours in time_exit_hours:
        bars = hours if hours is not None else None
        port_daily_pnls = {}
        all_tr = []
        for sym, inst in INSTRUMENTS.items():
            trades = backtest_orb(
                data[sym], inst, rr=2.0,
                be_bars=None, be_offset=0.0,
                time_exit_bars=bars,
            )
            if len(trades) > 0:
                port_daily_pnls[sym] = trades.groupby('date')['pnl_usd'].sum()
                all_tr.append(trades.assign(symbol=sym))

        comb = pd.DataFrame(port_daily_pnls).fillna(0)
        pdaily = comb.sum(axis=1)
        sh = (pdaily.mean() / pdaily.std() * np.sqrt(252) if pdaily.std() > 0 else 0)
        eq_ = pdaily.cumsum()
        dd_ = (eq_ - eq_.cummax()).min()
        gp_ = pdaily[pdaily > 0].sum()
        gl_ = pdaily[pdaily < 0].abs().sum()
        pf_ = gp_ / gl_ if gl_ > 0 else float('inf')
        mcl_days = max_consec_loss(pdaily)

        all_sorted = pd.concat(all_tr).sort_values('date')
        mcl_tr = 0
        st = 0
        for _, r in all_sorted.iterrows():
            if r['pnl_usd'] < 0:
                st += 1
                mcl_tr = max(mcl_tr, st)
            else:
                st = 0

        label = f"{hours}h" if hours is not None else "none"
        print(f"  {label:>6} | {sh:>7.2f} | {pf_:>5.2f} | ${dd_:>+10,.2f} | {mcl_days:>8} | {mcl_tr:>10}")

    # ═══════════════════════════════════════════════════════════════════════════
    # QUESTION 3: No-BE OOS Validation (IS: 2015-2020, OOS: 2021-2026)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  Q3: No-BE Out-of-Sample Validation")
    print("  IS: 2015-01-01 to 2020-12-31 | OOS: 2021-01-01 to 2026-12-31")
    print("=" * 80)

    is_end = pd.Timestamp('2020-12-31', tz='UTC')
    oos_start = pd.Timestamp('2021-01-01', tz='UTC')

    print(f"\n  {'Pair':>8} | {'IS Sharpe':>9} | {'OOS Sharpe':>10} | "
          f"{'IS PF':>5} | {'OOS PF':>6} | {'IS MCL':>6} | {'OOS MCL':>7} | Verdict")
    print(f"  {'-'*8}-+-{'-'*9}-+-{'-'*10}-+-{'-'*5}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*12}")

    is_daily_all = {}
    oos_daily_all = {}

    for sym, inst in INSTRUMENTS.items():
        ohlcv = data[sym]
        is_data = ohlcv.loc[:is_end]
        oos_data = ohlcv.loc[oos_start:]

        is_trades = backtest_orb(is_data, inst, rr=2.0, be_bars=None, be_offset=0.0)
        oos_trades = backtest_orb(oos_data, inst, rr=2.0, be_bars=None, be_offset=0.0)

        is_s = compute_stats(is_trades)
        oos_s = compute_stats(oos_trades)

        is_daily = is_trades.groupby('date')['pnl_usd'].sum() if len(is_trades) > 0 else pd.Series(dtype=float)
        oos_daily = oos_trades.groupby('date')['pnl_usd'].sum() if len(oos_trades) > 0 else pd.Series(dtype=float)

        is_mcl = max_consec_loss(is_daily)
        oos_mcl = max_consec_loss(oos_daily)

        is_daily_all[sym] = is_daily
        oos_daily_all[sym] = oos_daily

        verdict = "PASS" if oos_s['sharpe'] > 0 else "FAIL"
        if oos_s['sharpe'] > is_s['sharpe']:
            verdict += " (OOS > IS)"

        print(f"  {sym:>8} | {is_s['sharpe']:>9.2f} | {oos_s['sharpe']:>10.2f} | "
              f"{is_s['pf']:>5.2f} | {oos_s['pf']:>6.2f} | {is_mcl:>6} | {oos_mcl:>7} | {verdict}")

    # Portfolio OOS
    is_comb = pd.DataFrame(is_daily_all).fillna(0)
    oos_comb = pd.DataFrame(oos_daily_all).fillna(0)
    is_pdaily = is_comb.sum(axis=1)
    oos_pdaily = oos_comb.sum(axis=1)

    is_sh = (is_pdaily.mean() / is_pdaily.std() * np.sqrt(252) if is_pdaily.std() > 0 else 0)
    oos_sh = (oos_pdaily.mean() / oos_pdaily.std() * np.sqrt(252) if oos_pdaily.std() > 0 else 0)
    is_gp = is_pdaily[is_pdaily > 0].sum()
    is_gl = is_pdaily[is_pdaily < 0].abs().sum()
    is_pf = is_gp / is_gl if is_gl > 0 else float('inf')
    oos_gp = oos_pdaily[oos_pdaily > 0].sum()
    oos_gl = oos_pdaily[oos_pdaily < 0].abs().sum()
    oos_pf = oos_gp / oos_gl if oos_gl > 0 else float('inf')
    is_mcl_p = max_consec_loss(is_pdaily)
    oos_mcl_p = max_consec_loss(oos_pdaily)

    print(f"\n  {'PORT':>8} | {is_sh:>9.2f} | {oos_sh:>10.2f} | "
          f"{is_pf:>5.2f} | {oos_pf:>6.2f} | {is_mcl_p:>6} | {oos_mcl_p:>7} | "
          f"{'PASS (OOS > IS)' if oos_sh > is_sh else 'PASS' if oos_sh > 0 else 'FAIL'}")

    # Annual breakdown for portfolio no-BE
    print(f"\n  Portfolio Annual Breakdown (No-BE):")
    print(f"  {'Year':>6} | {'P&L':>12} | {'Sharpe':>7} | {'MaxDD':>11} | {'MCL':>3}")
    print(f"  {'-'*6}-+-{'-'*12}-+-{'-'*7}-+-{'-'*11}-+-{'-'*3}")

    all_no_be = pd.concat(
        [t.assign(symbol=sym) for sym, t in no_be_trades.items()]
    )
    all_no_be['year'] = pd.to_datetime(all_no_be['date']).dt.year
    port_no_be_daily = pd.DataFrame({
        sym: t.groupby('date')['pnl_usd'].sum()
        for sym, t in no_be_trades.items() if len(t) > 0
    }).fillna(0).sum(axis=1)
    port_no_be_daily = port_no_be_daily.sort_index()

    # Group by year
    port_df = pd.DataFrame({'pnl': port_no_be_daily})
    port_df.index = pd.to_datetime(port_df.index)
    for yr, g in port_df.groupby(port_df.index.year):
        yr_pnl = g['pnl'].sum()
        yr_sh = (g['pnl'].mean() / g['pnl'].std() * np.sqrt(252) if g['pnl'].std() > 0 else 0)
        yr_eq = g['pnl'].cumsum()
        yr_dd = (yr_eq - yr_eq.cummax()).min()
        yr_mcl = max_consec_loss(g['pnl'])
        print(f"  {yr:>6} | ${yr_pnl:>+11,.2f} | {yr_sh:>7.2f} | ${yr_dd:>+10,.2f} | {yr_mcl:>3}")

    print("\n" + "=" * 80)
    print("  RESEARCH COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
