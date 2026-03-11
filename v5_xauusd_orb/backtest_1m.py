"""
backtest_1m.py -- Honest ORB backtest engine using 1-minute bars from Dukascopy ticks.

Every bar is exactly 1 minute, so:
  - tick_count = ticks per minute (velocity)
  - No bar-duration ambiguity (unlike 1000-tick bars)
  - Entry/exit precision: within 1 minute
  - Real spread, volume, imbalance from raw tick data

Data: c:/nautilus0/data/1m_csv/xauusd_1m_tick.csv
  Columns: timestamp, open, high, low, close, tick_count, avg_spread, max_spread,
           vol_imbalance, buy_volume, sell_volume, total_volume, buy_ratio
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'


# ── Data Loading ──────────────────────────────────────────────────────────

def load_1m_bars(path: str | Path = DATA_FILE) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


# ── Trade Result ──────────────────────────────────────────────────────────

@dataclass
class Trade:
    date: object
    direction: str
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_type: str     # 'stop_at_level', 'stop_gap', 'limit_fill', 'confirm_fill'
    exit_type: str      # 'TP', 'SL', 'TIME_EXIT', 'EOD'
    range_high: float
    range_low: float
    range_size: float
    pnl: float
    spread_cost: float
    hold_minutes: float
    # Microstructure at entry
    entry_tick_count: int = 0
    entry_avg_spread: float = 0
    entry_buy_ratio: float = 0.5
    entry_vol_imbalance: float = 0
    gap_from_level: float = 0


# ── Config ────────────────────────────────────────────────────────────────

@dataclass
class Config:
    range_start: int = 0
    range_end: int = 6
    trade_start: int = 8
    trade_end: int = 16
    rr_ratio: float = 2.0
    min_range_pct: float = 0.05
    max_range_pct: float = 2.0
    skip_weekdays: list = field(default_factory=lambda: [2])  # Wednesday
    time_exit_minutes: float = 0  # 0 = disabled
    entry_method: str = 'stop'  # 'stop', 'limit_retest', 'confirm_close'


# ── Core Engine ───────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, cfg: Config) -> list[Trade]:
    trades = []

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5 or wd in cfg.skip_weekdays:
            continue

        # Asian range
        asian = day_df[(day_df['hour'] >= cfg.range_start) & (day_df['hour'] < cfg.range_end)]
        if len(asian) < 10:
            continue

        rh = asian['high'].max()
        rl = asian['low'].min()
        rs = rh - rl
        if rs <= 0:
            continue
        mid = (rh + rl) / 2
        rpct = rs / mid * 100
        if rpct < cfg.min_range_pct or rpct > cfg.max_range_pct:
            continue

        tp_long = rh + cfg.rr_ratio * rs
        tp_short = rl - cfg.rr_ratio * rs

        # Trade window
        window = day_df[(day_df['hour'] >= cfg.trade_start) & (day_df['hour'] < cfg.trade_end)]
        if len(window) < 5:
            continue

        trade = _run_day(window, cfg, rh, rl, rs, tp_long, tp_short, day)
        if trade is not None:
            trades.append(trade)

    return trades


def _run_day(window, cfg, rh, rl, rs, tp_long, tp_short, day) -> Optional[Trade]:
    bars = list(window.iterrows())
    n = len(bars)

    if cfg.entry_method == 'stop':
        return _entry_stop(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day)
    elif cfg.entry_method == 'limit_retest':
        return _entry_limit_retest(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day)
    elif cfg.entry_method == 'confirm_close':
        return _entry_confirm_close(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day)
    else:
        raise ValueError(f"Unknown entry_method: {cfg.entry_method}")


def _entry_stop(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day):
    """
    Stop order at range_high (buy) and range_low (sell).
    Fill logic:
      - If bar's high >= rh and bar's open < rh: level fill (stop triggered within bar)
      - If bar's open >= rh: gap fill at open (price already past level)
    Spread applied to fill price.
    """
    for i in range(n):
        ts, bar = bars[i]
        hs = bar['avg_spread'] / 2

        direction = None
        entry_px = None
        gap = 0

        # Check long trigger
        if bar['high'] >= rh:
            direction = 'LONG'
            if bar['open'] >= rh:
                entry_px = bar['open'] + hs
                gap = bar['open'] - rh
                etype = 'stop_gap'
            else:
                entry_px = rh + hs
                gap = 0
                etype = 'stop_at_level'
        elif bar['low'] <= rl:
            direction = 'SHORT'
            if bar['open'] <= rl:
                entry_px = bar['open'] - hs
                gap = rl - bar['open']
                etype = 'stop_gap'
            else:
                entry_px = rl - hs
                gap = 0
                etype = 'stop_at_level'

        if direction is None:
            continue

        sl = rl if direction == 'LONG' else rh
        tp = tp_long if direction == 'LONG' else tp_short

        return _monitor(bars, i + 1, n, cfg, direction, entry_px, sl, tp,
                        ts, rh, rl, rs, day, etype, gap, bar)

    return None


def _entry_limit_retest(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day):
    """Wait for breakout, then enter on pullback to the level."""
    broken_long = False
    broken_short = False

    for i in range(n):
        ts, bar = bars[i]
        hs = bar['avg_spread'] / 2

        if bar['high'] >= rh:
            broken_long = True
        if bar['low'] <= rl:
            broken_short = True

        if broken_long and broken_short:
            return None

        if broken_long and not broken_short:
            if bar['low'] <= rh:  # pullback to level
                entry_px = rh + hs
                return _monitor(bars, i + 1, n, cfg, 'LONG', entry_px, rl, tp_long,
                                ts, rh, rl, rs, day, 'limit_fill', 0, bar)

        if broken_short and not broken_long:
            if bar['high'] >= rl:
                entry_px = rl - hs
                return _monitor(bars, i + 1, n, cfg, 'SHORT', entry_px, rh, tp_short,
                                ts, rh, rl, rs, day, 'limit_fill', 0, bar)

    return None


def _entry_confirm_close(bars, n, cfg, rh, rl, rs, tp_long, tp_short, day):
    """Wait for bar CLOSE above/below level, enter next bar open."""
    for i in range(n - 1):
        ts, bar = bars[i]

        direction = None
        if bar['close'] > rh:
            direction = 'LONG'
        elif bar['close'] < rl:
            direction = 'SHORT'

        if direction is None:
            continue

        ts_next, bar_next = bars[i + 1]
        hs = bar_next['avg_spread'] / 2

        if direction == 'LONG':
            entry_px = bar_next['open'] + hs
            gap = max(0, entry_px - rh - hs)
        else:
            entry_px = bar_next['open'] - hs
            gap = max(0, rl - entry_px - hs)

        sl = rl if direction == 'LONG' else rh
        tp = tp_long if direction == 'LONG' else tp_short

        return _monitor(bars, i + 1, n, cfg, direction, entry_px, sl, tp,
                        ts_next, rh, rl, rs, day, 'confirm_fill', gap, bar_next)

    return None


def _monitor(bars, start_idx, n, cfg, direction, entry_px, sl, tp,
             entry_ts, rh, rl, rs, day, etype, gap, entry_bar):
    """Monitor open trade: SL, TP, time exit, EOD."""

    exit_px = None
    exit_type = 'EOD'
    exit_ts = entry_ts
    exit_spread = 0

    for j in range(start_idx, n):
        ts, bar = bars[j]
        hs = bar['avg_spread'] / 2

        # Time exit
        if cfg.time_exit_minutes > 0:
            elapsed = (ts - entry_ts).total_seconds() / 60
            if elapsed >= cfg.time_exit_minutes:
                if direction == 'LONG':
                    exit_px = bar['open'] - hs
                else:
                    exit_px = bar['open'] + hs
                exit_type = 'TIME_EXIT'
                exit_ts = ts
                exit_spread = hs
                break

        # SL / TP
        if direction == 'LONG':
            if bar['low'] <= sl:
                exit_px = sl - hs
                exit_type = 'SL'
                exit_ts = ts
                exit_spread = hs
                break
            if bar['high'] >= tp:
                exit_px = tp - hs
                exit_type = 'TP'
                exit_ts = ts
                exit_spread = hs
                break
        else:
            if bar['high'] >= sl:
                exit_px = sl + hs
                exit_type = 'SL'
                exit_ts = ts
                exit_spread = hs
                break
            if bar['low'] <= tp:
                exit_px = tp + hs
                exit_type = 'TP'
                exit_ts = ts
                exit_spread = hs
                break

    # EOD
    if exit_px is None:
        last_ts, last_bar = bars[-1]
        hs = last_bar['avg_spread'] / 2
        exit_px = last_bar['close'] - hs if direction == 'LONG' else last_bar['close'] + hs
        exit_ts = last_ts
        exit_spread = hs

    raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
    entry_hs = entry_bar['avg_spread'] / 2
    hold = (exit_ts - entry_ts).total_seconds() / 60

    return Trade(
        date=day,
        direction=direction,
        entry_price=round(entry_px, 3),
        exit_price=round(exit_px, 3),
        entry_time=entry_ts,
        exit_time=exit_ts,
        entry_type=etype,
        exit_type=exit_type,
        range_high=round(rh, 3),
        range_low=round(rl, 3),
        range_size=round(rs, 3),
        pnl=round(raw_pnl, 3),
        spread_cost=round(entry_hs + exit_spread, 4),
        hold_minutes=round(hold, 1),
        entry_tick_count=int(entry_bar.get('tick_count', 0)),
        entry_avg_spread=round(entry_bar.get('avg_spread', 0), 4),
        entry_buy_ratio=round(entry_bar.get('buy_ratio', 0.5), 4),
        entry_vol_imbalance=entry_bar.get('vol_imbalance', 0),
        gap_from_level=round(gap, 3),
    )


# ── Statistics ────────────────────────────────────────────────────────────

def stats(trades: list[Trade], label: str = '') -> dict:
    if not trades:
        return {'label': label, 'n': 0}
    pnl = pd.Series([t.pnl for t in trades])
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
    streak = 0; mcl = 0
    for v in pnl:
        if v < 0:
            streak += 1; mcl = max(mcl, streak)
        else:
            streak = 0
    return {
        'label': label, 'n': n, 'sharpe': round(sharpe, 2),
        'pf': round(pf, 2), 'wr': round(wr, 1),
        'mean': round(mean, 2), 'total': round(pnl.sum(), 2),
        'max_dd': round(dd, 2), 'mcl': mcl,
        'avg_spread': round(pd.Series([t.spread_cost for t in trades]).mean(), 4),
    }


def print_stats(s: dict):
    if s['n'] == 0:
        print(f"  {s['label']}: NO TRADES")
        return
    print(f"  {s['label']:>30}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
          f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | "
          f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
          f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    import datetime as dt
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")
    print(f"Days: {df['date'].nunique()}, Months with data: {len(set(d.month for d in pd.to_datetime(df.index).to_pydatetime()))}")

    oos_start = dt.date(2021, 1, 1)

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Entry method comparison
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  1. ENTRY METHOD COMPARISON (no time exit)")
    print("=" * 110)

    for method in ['stop', 'limit_retest', 'confirm_close']:
        cfg = Config(entry_method=method, time_exit_minutes=0)
        trades = backtest(df, cfg)
        s = stats(trades, method)
        print_stats(s)
        oos = [t for t in trades if t.date >= oos_start]
        so = stats(oos, f"{method} (OOS)")
        print_stats(so)
        print()

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Time exit sweep (stop entry)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. TIME EXIT SWEEP (stop entry)")
    print("=" * 110)

    for te in [0, 15, 30, 45, 60, 90, 120, 180]:
        cfg = Config(entry_method='stop', time_exit_minutes=te)
        trades = backtest(df, cfg)
        s = stats(trades, f"te={te}" if te > 0 else "none")
        oos = [t for t in trades if t.date >= oos_start]
        so = stats(oos, "")
        label = f"te={te}min" if te > 0 else "te=none"
        print(f"  {label:>10}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
              f"DD ${s['max_dd']:>+9.2f} | Total ${s['total']:>+10.2f} | OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Velocity filter (tick_count per 1-min bar)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. TICK COUNT (VELOCITY) FILTER — stop entry, no time exit")
    print("=" * 110)

    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)

    tcs = [t.entry_tick_count for t in all_trades]
    print(f"\n  Tick count stats: mean={np.mean(tcs):.0f}, median={np.median(tcs):.0f}, "
          f"P25={np.percentile(tcs,25):.0f}, P75={np.percentile(tcs,75):.0f}")

    # Quintile analysis
    tc_arr = np.array(tcs)
    quintile_edges = np.percentile(tc_arr, [0, 20, 40, 60, 80, 100])
    labels = ['Q1_slow', 'Q2', 'Q3', 'Q4', 'Q5_fast']

    print(f"\n  {'Quintile':>10} | {'TcRange':>15} | {'N':>5} | {'Sharpe':>7} | {'PF':>5} | "
          f"{'WR':>5} | {'Mean':>7} | {'Total':>10}")
    print(f"  {'-'*10}-+-{'-'*15}-+-{'-'*5}-+-{'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*7}-+-{'-'*10}")

    for qi in range(5):
        lo, hi = quintile_edges[qi], quintile_edges[qi + 1]
        subset = [t for t in all_trades if lo <= t.entry_tick_count < (hi if qi < 4 else hi + 1)]
        s = stats(subset, labels[qi])
        print(f"  {labels[qi]:>10} | {lo:>6.0f} - {hi:>6.0f} | {s['n']:>5} | {s['sharpe']:>7.2f} | "
              f"{s['pf']:>5.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+6.2f} | ${s['total']:>+9.2f}")

    # OOS quintiles
    print(f"\n  OOS (2021+) quintiles:")
    oos_trades = [t for t in all_trades if t.date >= oos_start]
    oos_tcs = np.array([t.entry_tick_count for t in oos_trades])
    oos_edges = np.percentile(oos_tcs, [0, 20, 40, 60, 80, 100])

    for qi in range(5):
        lo, hi = oos_edges[qi], oos_edges[qi + 1]
        subset = [t for t in oos_trades if lo <= t.entry_tick_count < (hi if qi < 4 else hi + 1)]
        s = stats(subset, labels[qi])
        print(f"  {labels[qi]:>10} | {lo:>6.0f} - {hi:>6.0f} | {s['n']:>5} | {s['sharpe']:>7.2f} | "
              f"{s['pf']:>5.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+6.2f} | ${s['total']:>+9.2f}")

    # Fast half vs slow half (the critical test)
    tc_med = np.median(tc_arr)
    fast = [t for t in all_trades if t.entry_tick_count >= tc_med]
    slow = [t for t in all_trades if t.entry_tick_count < tc_med]
    sf = stats(fast, "Fast (>=median)")
    ss = stats(slow, "Slow (<median)")
    print(f"\n  Median tick_count = {tc_med:.0f}")
    print_stats(sf)
    print_stats(ss)

    # OOS fast/slow
    fast_oos = [t for t in oos_trades if t.entry_tick_count >= tc_med]
    slow_oos = [t for t in oos_trades if t.entry_tick_count < tc_med]
    print_stats(stats(fast_oos, "Fast OOS"))
    print_stats(stats(slow_oos, "Slow OOS"))

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Gap analysis
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  4. GAP ANALYSIS (stop entry, no time exit)")
    print("=" * 110)

    level_fills = [t for t in all_trades if t.gap_from_level <= 0.01]
    gap_fills = [t for t in all_trades if t.gap_from_level > 0.01]

    print(f"\n  Level fills (gap<=0.01): N={len(level_fills)}")
    print_stats(stats(level_fills, "Level fills"))
    print(f"  Gap fills (gap>0.01): N={len(gap_fills)}")
    print_stats(stats(gap_fills, "Gap fills"))

    if gap_fills:
        gaps = [t.gap_from_level for t in gap_fills]
        print(f"\n  Gap size: mean=${np.mean(gaps):.2f}, median=${np.median(gaps):.2f}, "
              f"P90=${np.percentile(gaps,90):.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Annual breakdown (stop, no time exit)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  5. ANNUAL BREAKDOWN (stop entry, no time exit)")
    print("=" * 110)

    by_year = {}
    for t in all_trades:
        yr = t.date.year
        by_year.setdefault(yr, []).append(t)

    for yr in sorted(by_year):
        s = stats(by_year[yr], "")
        flag = " <<< LOSS" if s['total'] < 0 else ""
        print(f"    {yr}: N={s['n']:>4} | P&L ${s['total']:>+9.2f} | "
              f"Sh {s['sharpe']:>6.2f} | DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']}{flag}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. Walk-forward velocity test
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  6. WALK-FORWARD: Train velocity threshold on 3yr, test on next")
    print("=" * 110)

    years = sorted(by_year.keys())
    filter_helps = 0
    total_tests = 0

    print(f"\n  {'Test':>6} | {'Train':>12} | {'Thresh':>6} | {'N_all':>6} | {'N_filt':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'Sh_rej':>7} | {'Better?':>8}")

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue
        train_trades = [t for t in all_trades if t.date.year in train_yrs]
        test_trades = [t for t in all_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        thresh = np.median([t.entry_tick_count for t in train_trades])
        fast_test = [t for t in test_trades if t.entry_tick_count >= thresh]
        slow_test = [t for t in test_trades if t.entry_tick_count < thresh]

        sh_all = stats(test_trades)['sharpe']
        sh_fast = stats(fast_test)['sharpe'] if len(fast_test) >= 5 else 0
        sh_slow = stats(slow_test)['sharpe'] if len(slow_test) >= 5 else 0

        total_tests += 1
        helps = sh_fast > sh_all
        if helps:
            filter_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {thresh:>6.0f} | "
              f"{len(test_trades):>6} | {len(fast_test):>6} | "
              f"{sh_all:>7.2f} | {sh_fast:>7.2f} | {sh_slow:>7.2f} | "
              f"{'YES' if helps else 'no':>8}")

    print(f"\n  Filter helps in {filter_helps}/{total_tests} years ({filter_helps/max(total_tests,1)*100:.0f}%)")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
