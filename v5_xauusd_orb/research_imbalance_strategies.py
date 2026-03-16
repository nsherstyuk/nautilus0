"""
research_imbalance_strategies.py -- Explore two imbalance-driven strategies on XAUUSD 1-min data.

STRATEGY 1: LIQUIDITY GRAB FADE
  - Identify key levels: previous day high/low, round numbers ($50 increments)
  - When price pierces a level on DIVERGENT flow (buy_ratio opposes direction),
    fade the move (bet on reversal back inside)
  - Thesis: divergent flow at a key level = stop hunt / fake-out

STRATEGY 2: FLOW MOMENTUM
  - No price level needed
  - Enter when buy_ratio is extreme and sustained for N bars
  - Thesis: sustained directional flow = real conviction, ride the wave
  - Exit when flow reverts to neutral or time-based

Uses existing 1-min XAUUSD data with buy_volume, sell_volume, buy_ratio.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv'


def load_1m_bars(path=DATA_FILE):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


@dataclass
class Trade:
    date: object
    direction: str
    entry_price: float
    exit_price: float
    entry_time: object
    exit_time: object
    exit_type: str
    pnl: float
    hold_minutes: float
    entry_buy_ratio: float
    level_type: str = ''


def stats(trades: list[Trade], label: str = '') -> dict:
    if not trades:
        return {'label': label, 'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0,
                'mean': 0, 'total': 0, 'max_dd': 0, 'mcl': 0}
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
    }


def print_stats(s: dict):
    if s['n'] == 0:
        print(f"  {s['label']:>30}: NO TRADES")
        return
    print(f"  {s['label']:>30}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
          f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | "
          f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
          f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")


# =========================================================================
# STRATEGY 1: LIQUIDITY GRAB FADE
# =========================================================================

def get_prev_day_levels(df: pd.DataFrame) -> dict:
    """For each date, get previous day's high, low, close."""
    levels = {}
    dates = sorted(df['date'].unique())
    for i in range(1, len(dates)):
        prev = dates[i - 1]
        curr = dates[i]
        prev_data = df[df['date'] == prev]
        if len(prev_data) < 60:
            continue
        levels[curr] = {
            'prev_high': prev_data['high'].max(),
            'prev_low': prev_data['low'].min(),
            'prev_close': prev_data['close'].iloc[-1],
        }
    return levels


def get_round_levels(price: float, step: float = 50.0) -> list[float]:
    """Get round number levels near current price."""
    base = round(price / step) * step
    return [base - step, base, base + step]


def strategy_liquidity_fade(df: pd.DataFrame, cfg: dict) -> list[Trade]:
    """
    When price pierces a key level on divergent flow, fade it.

    Params in cfg:
      imb_window: bars to average buy_ratio over (default 3)
      div_threshold: how extreme divergence must be (default 0.40)
      sl_mult: SL in multiples of avg_spread (default 30)
      tp_mult: TP in multiples of avg_spread (default 20)
      max_hold: max bars to hold (default 60)
      trade_start: hour to start (default 8)
      trade_end: hour to stop (default 20)
      level_buffer: how far price must pierce level (default 0.5)
    """
    imb_window = cfg.get('imb_window', 3)
    div_threshold = cfg.get('div_threshold', 0.40)
    sl_mult = cfg.get('sl_mult', 30)
    tp_mult = cfg.get('tp_mult', 20)
    max_hold = cfg.get('max_hold', 60)
    trade_start = cfg.get('trade_start', 8)
    trade_end = cfg.get('trade_end', 20)
    level_buffer = cfg.get('level_buffer', 0.5)
    round_step = cfg.get('round_step', 50.0)

    prev_levels = get_prev_day_levels(df)
    trades = []

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5:
            continue

        window = day_df[(day_df['hour'] >= trade_start) & (day_df['hour'] < trade_end)]
        if len(window) < 30:
            continue

        bars = list(window.iterrows())
        n = len(bars)
        day_traded = False

        # Collect key levels for this day
        key_levels = []
        if day in prev_levels:
            lv = prev_levels[day]
            key_levels.append(('prev_high', lv['prev_high']))
            key_levels.append(('prev_low', lv['prev_low']))

        # Add round numbers near current price
        if n > 0:
            mid_price = bars[0][1]['close']
            for rl in get_round_levels(mid_price, round_step):
                key_levels.append(('round', rl))

        if not key_levels:
            continue

        for i in range(imb_window, n):
            if day_traded:
                break

            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            # Calculate rolling buy_ratio
            br_vals = [bars[j][1]['buy_ratio'] for j in range(i - imb_window, i + 1)]
            avg_br = np.mean(br_vals)

            for level_type, level in key_levels:
                # Check for upward pierce of level on DIVERGENT flow (sellers dominate)
                if bar['high'] >= level + level_buffer and bar['open'] < level:
                    if avg_br < div_threshold:  # sellers dominate = divergent on up-pierce
                        # FADE: go SHORT
                        entry_px = bar['close'] + hs
                        sl_px = entry_px + sl_mult * bar['avg_spread']
                        tp_px = entry_px - tp_mult * bar['avg_spread']

                        trade = _monitor_trade(bars, i + 1, n, 'SHORT', entry_px,
                                               sl_px, tp_px, max_hold, ts, day,
                                               avg_br, level_type)
                        if trade:
                            trades.append(trade)
                        day_traded = True
                        break

                # Check for downward pierce of level on DIVERGENT flow (buyers dominate)
                if bar['low'] <= level - level_buffer and bar['open'] > level:
                    if avg_br > (1 - div_threshold):  # buyers dominate = divergent on down-pierce
                        # FADE: go LONG
                        entry_px = bar['close'] - hs
                        sl_px = entry_px - sl_mult * bar['avg_spread']
                        tp_px = entry_px + tp_mult * bar['avg_spread']

                        trade = _monitor_trade(bars, i + 1, n, 'LONG', entry_px,
                                               sl_px, tp_px, max_hold, ts, day,
                                               avg_br, level_type)
                        if trade:
                            trades.append(trade)
                        day_traded = True
                        break

    return trades


# =========================================================================
# STRATEGY 2: FLOW MOMENTUM
# =========================================================================

def strategy_flow_momentum(df: pd.DataFrame, cfg: dict) -> list[Trade]:
    """
    Enter when buy_ratio is extreme and sustained for N bars.

    Params in cfg:
      streak_bars: how many consecutive bars must be extreme (default 5)
      long_threshold: buy_ratio above this = buy signal (default 0.60)
      short_threshold: buy_ratio below this = sell signal (default 0.40)
      sl_atr_mult: SL in ATR multiples (default 2.0)
      tp_atr_mult: TP in ATR multiples (default 3.0)
      max_hold: max bars (default 60)
      trade_start: hour (default 8)
      trade_end: hour (default 20)
      atr_window: bars for ATR calc (default 20)
      cooldown: bars after exit before re-entry (default 10)
    """
    streak_bars = cfg.get('streak_bars', 5)
    long_thr = cfg.get('long_threshold', 0.60)
    short_thr = cfg.get('short_threshold', 0.40)
    sl_atr = cfg.get('sl_atr_mult', 2.0)
    tp_atr = cfg.get('tp_atr_mult', 3.0)
    max_hold = cfg.get('max_hold', 60)
    trade_start = cfg.get('trade_start', 8)
    trade_end = cfg.get('trade_end', 20)
    atr_window = cfg.get('atr_window', 20)
    cooldown = cfg.get('cooldown', 10)

    trades = []

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5:
            continue

        window = day_df[(day_df['hour'] >= trade_start) & (day_df['hour'] < trade_end)]
        if len(window) < atr_window + streak_bars + 10:
            continue

        bars = list(window.iterrows())
        n = len(bars)

        # Precompute ATR
        ranges = [bars[j][1]['high'] - bars[j][1]['low'] for j in range(n)]

        last_exit_bar = -cooldown - 1
        day_trades = 0

        for i in range(max(atr_window, streak_bars), n):
            if day_trades >= 2:  # max 2 trades per day
                break
            if i - last_exit_bar < cooldown:
                continue

            # ATR
            atr = np.mean(ranges[i - atr_window:i])
            if atr <= 0:
                continue

            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            # Check for sustained extreme buy_ratio
            recent_brs = [bars[j][1]['buy_ratio'] for j in range(i - streak_bars + 1, i + 1)]

            # LONG: all recent bars have buy_ratio > threshold
            if all(br > long_thr for br in recent_brs):
                entry_px = bar['close'] + hs
                sl_px = entry_px - sl_atr * atr
                tp_px = entry_px + tp_atr * atr
                avg_br = np.mean(recent_brs)

                trade = _monitor_trade(bars, i + 1, n, 'LONG', entry_px,
                                       sl_px, tp_px, max_hold, ts, day,
                                       avg_br, 'flow_momentum')
                if trade:
                    trades.append(trade)
                    last_exit_bar = i + int(trade.hold_minutes)
                    day_trades += 1
                continue

            # SHORT: all recent bars have buy_ratio < threshold
            if all(br < short_thr for br in recent_brs):
                entry_px = bar['close'] - hs
                sl_px = entry_px + sl_atr * atr
                tp_px = entry_px - tp_atr * atr
                avg_br = np.mean(recent_brs)

                trade = _monitor_trade(bars, i + 1, n, 'SHORT', entry_px,
                                       sl_px, tp_px, max_hold, ts, day,
                                       avg_br, 'flow_momentum')
                if trade:
                    trades.append(trade)
                    last_exit_bar = i + int(trade.hold_minutes)
                    day_trades += 1

    return trades


def _monitor_trade(bars, start_idx, n, direction, entry_px, sl_px, tp_px,
                   max_hold, entry_ts, day, entry_br, level_type):
    """Monitor SL/TP/time exit."""
    exit_px = None
    exit_type = 'EOD'
    exit_ts = entry_ts

    for j in range(start_idx, min(start_idx + max_hold, n)):
        ts, bar = bars[j]
        hs = bar['avg_spread'] / 2

        if direction == 'LONG':
            if bar['low'] <= sl_px:
                exit_px = sl_px - hs
                exit_type = 'SL'
                exit_ts = ts
                break
            if bar['high'] >= tp_px:
                exit_px = tp_px - hs
                exit_type = 'TP'
                exit_ts = ts
                break
        else:
            if bar['high'] >= sl_px:
                exit_px = sl_px + hs
                exit_type = 'SL'
                exit_ts = ts
                break
            if bar['low'] <= tp_px:
                exit_px = tp_px + hs
                exit_type = 'TP'
                exit_ts = ts
                break

    # Time exit or EOD
    if exit_px is None:
        end_idx = min(start_idx + max_hold, n) - 1
        if end_idx >= start_idx:
            exit_ts, exit_bar = bars[end_idx]
            hs = exit_bar['avg_spread'] / 2
            exit_px = exit_bar['close'] - hs if direction == 'LONG' else exit_bar['close'] + hs
            exit_type = 'TIME' if end_idx < n - 1 else 'EOD'
        else:
            return None

    raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
    hold = (exit_ts - entry_ts).total_seconds() / 60

    return Trade(
        date=day,
        direction=direction,
        entry_price=round(entry_px, 3),
        exit_price=round(exit_px, 3),
        entry_time=entry_ts,
        exit_time=exit_ts,
        exit_type=exit_type,
        pnl=round(raw_pnl, 3),
        hold_minutes=round(hold, 1),
        entry_buy_ratio=round(entry_br, 4),
        level_type=level_type,
    )


# =========================================================================
# MAIN
# =========================================================================

def main():
    import datetime as dt
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = dt.date(2021, 1, 1)

    # =================================================================
    # STRATEGY 1: LIQUIDITY GRAB FADE -- parameter sweep
    # =================================================================
    print(f"\n{'='*120}")
    print("  STRATEGY 1: LIQUIDITY GRAB FADE")
    print("  (Pierce key level on divergent flow -> fade the move)")
    print("=" * 120)

    # Baseline with default params
    base_cfg = {'div_threshold': 0.40, 'imb_window': 3, 'sl_mult': 30,
                'tp_mult': 20, 'max_hold': 60}
    trades_1 = strategy_liquidity_fade(df, base_cfg)
    print(f"\n  Baseline config: div_thr=0.40, window=3, SL=30x, TP=20x, hold=60")
    print_stats(stats(trades_1, "LiqGrab (full)"))
    oos_1 = [t for t in trades_1 if t.date >= oos_start]
    print_stats(stats(oos_1, "LiqGrab (OOS)"))

    # Sweep divergence threshold
    print(f"\n  --- Divergence threshold sweep ---")
    print(f"  {'div_thr':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for div in [0.30, 0.35, 0.38, 0.40, 0.42, 0.45]:
        cfg = {**base_cfg, 'div_threshold': div}
        t = strategy_liquidity_fade(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {div:>8.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Sweep TP/SL ratio
    print(f"\n  --- TP/SL ratio sweep (div_thr=0.40) ---")
    print(f"  {'TP/SL':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for tp, sl in [(10, 30), (15, 30), (20, 30), (25, 30), (30, 30), (20, 20), (20, 40), (30, 20)]:
        cfg = {**base_cfg, 'tp_mult': tp, 'sl_mult': sl}
        t = strategy_liquidity_fade(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {tp}/{sl:>2} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Sweep hold time
    print(f"\n  --- Hold time sweep ---")
    print(f"  {'hold':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for hold in [15, 30, 45, 60, 90, 120]:
        cfg = {**base_cfg, 'max_hold': hold}
        t = strategy_liquidity_fade(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {hold:>6}m | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Level type breakdown
    if trades_1:
        print(f"\n  --- Level type breakdown ---")
        for lt in set(t.level_type for t in trades_1):
            subset = [t for t in trades_1 if t.level_type == lt]
            print_stats(stats(subset, lt))

    # Annual
    print(f"\n  --- Annual breakdown (best config) ---")
    by_year = {}
    for t in trades_1:
        by_year.setdefault(t.date.year, []).append(t)
    for yr in sorted(by_year):
        s = stats(by_year[yr], '')
        print(f"    {yr}: N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | Total ${s['total']:>+9.2f} | MCL {s['mcl']}")

    # =================================================================
    # STRATEGY 2: FLOW MOMENTUM -- parameter sweep
    # =================================================================
    print(f"\n{'='*120}")
    print("  STRATEGY 2: FLOW MOMENTUM")
    print("  (Sustained extreme buy_ratio -> ride the wave)")
    print("=" * 120)

    base_cfg2 = {'streak_bars': 5, 'long_threshold': 0.60, 'short_threshold': 0.40,
                 'sl_atr_mult': 2.0, 'tp_atr_mult': 3.0, 'max_hold': 60}
    trades_2 = strategy_flow_momentum(df, base_cfg2)
    print(f"\n  Baseline: streak=5, long_thr=0.60, short_thr=0.40, SL=2xATR, TP=3xATR, hold=60")
    print_stats(stats(trades_2, "FlowMom (full)"))
    oos_2 = [t for t in trades_2 if t.date >= oos_start]
    print_stats(stats(oos_2, "FlowMom (OOS)"))

    # Sweep threshold
    print(f"\n  --- Threshold sweep (symmetric: long=thr, short=1-thr) ---")
    print(f"  {'thr':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for thr in [0.55, 0.58, 0.60, 0.62, 0.65, 0.70]:
        cfg = {**base_cfg2, 'long_threshold': thr, 'short_threshold': 1 - thr}
        t = strategy_flow_momentum(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {thr:>8.2f} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Sweep streak
    print(f"\n  --- Streak bars sweep (thr=0.60) ---")
    print(f"  {'streak':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for streak in [3, 4, 5, 7, 10]:
        cfg = {**base_cfg2, 'streak_bars': streak}
        t = strategy_flow_momentum(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {streak:>8} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Sweep TP/SL ATR multiples
    print(f"\n  --- TP/SL ATR sweep ---")
    print(f"  {'TP/SL':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for tp_m, sl_m in [(1.5, 1.0), (2.0, 1.5), (2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (4.0, 2.0), (5.0, 2.0)]:
        cfg = {**base_cfg2, 'tp_atr_mult': tp_m, 'sl_atr_mult': sl_m}
        t = strategy_flow_momentum(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {tp_m}/{sl_m} | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Sweep hold time
    print(f"\n  --- Hold time sweep ---")
    print(f"  {'hold':>8} | {'N':>5} | {'Sh':>6} | {'WR':>5} | {'Mean':>8} | {'Total':>10} | {'N_OOS':>5} | {'Sh_OOS':>6}")
    for hold in [15, 30, 45, 60, 90, 120]:
        cfg = {**base_cfg2, 'max_hold': hold}
        t = strategy_flow_momentum(df, cfg)
        s = stats(t, '')
        t_oos = [x for x in t if x.date >= oos_start]
        so = stats(t_oos, '')
        print(f"  {hold:>6}m | {s['n']:>5} | {s['sharpe']:>6.2f} | {s['wr']:>4.1f}% | ${s['mean']:>+7.2f} | ${s['total']:>+9.2f} | {so['n']:>5} | {so['sharpe']:>6.2f}")

    # Direction breakdown
    if trades_2:
        print(f"\n  --- Direction breakdown ---")
        longs = [t for t in trades_2 if t.direction == 'LONG']
        shorts = [t for t in trades_2 if t.direction == 'SHORT']
        print_stats(stats(longs, "LONG"))
        print_stats(stats(shorts, "SHORT"))

    # Annual
    print(f"\n  --- Annual breakdown ---")
    by_year2 = {}
    for t in trades_2:
        by_year2.setdefault(t.date.year, []).append(t)
    for yr in sorted(by_year2):
        s = stats(by_year2[yr], '')
        print(f"    {yr}: N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | Total ${s['total']:>+9.2f} | MCL {s['mcl']}")

    # Exit type breakdown
    if trades_2:
        print(f"\n  --- Exit type breakdown ---")
        for et in set(t.exit_type for t in trades_2):
            subset = [t for t in trades_2 if t.exit_type == et]
            print_stats(stats(subset, et))

    print(f"\n{'='*120}")
    print("  DONE")
    print("=" * 120)


if __name__ == "__main__":
    main()
