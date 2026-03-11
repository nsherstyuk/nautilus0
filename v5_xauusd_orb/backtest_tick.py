"""
backtest_tick.py -- Honest ORB backtest engine using 1000-tick bars.

Key design principles:
1. NO look-ahead bias: decisions use only data available at that moment
2. Realistic fills:
   - Stop orders: triggered when bar touches level, filled at NEXT bar open + spread
   - Limit orders: triggered when bar touches level, filled at level (or better)
   - Market orders: filled at next bar open + spread
3. Real spread from data (avg_spread column), not assumed
4. Multiple entry strategies to compare

Data source: c:\\nautilus0\\trading_system_v4\\data\\xauusd_1000t_bars.csv
  - 415K bars, 2015-01-01 to 2026-02-25
  - Columns: timestamp, open, high, low, close, avg_spread, max_spread,
             vol_imbalance, buy_volume, sell_volume, tick_velocity, total_volume, buy_ratio
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TICK_DATA = ROOT / 'trading_system_v4' / 'data' / 'xauusd_1000t_bars.csv'


# ── Data Loading ──────────────────────────────────────────────────────────

def load_tick_bars(path: str | Path = TICK_DATA) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


# ── Order Types ───────────────────────────────────────────────────────────

@dataclass
class Order:
    """Represents a pending or filled order."""
    side: str           # 'BUY' or 'SELL'
    order_type: str     # 'STOP', 'LIMIT', 'MARKET'
    price: float        # trigger price for STOP/LIMIT, ignored for MARKET
    placed_at: pd.Timestamp = None


@dataclass
class Fill:
    """Represents a filled order."""
    side: str
    price: float        # actual fill price (including spread)
    time: pd.Timestamp
    bar_idx: int


@dataclass
class Trade:
    """A completed round-trip trade."""
    date: object
    direction: str      # 'LONG' or 'SHORT'
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_type: str     # 'stop_fill', 'limit_fill', 'market_fill'
    exit_type: str      # 'TP', 'SL', 'TIME_EXIT', 'EOD'
    range_high: float
    range_low: float
    range_size: float
    pnl: float          # raw P&L in price units
    spread_cost: float  # total spread paid (entry + exit)
    entry_spread: float # spread at entry
    exit_spread: float  # spread at exit
    hold_minutes: float
    # Extra features for analysis
    entry_hour: int = 0
    gap_from_level: float = 0  # how far from trigger level (0 = perfect fill)
    vol_imbalance_at_entry: float = 0
    buy_ratio_at_entry: float = 0
    tick_velocity_at_entry: float = 0


# ── Core Engine ───────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    # Range definition
    range_start: int = 0    # UTC hour
    range_end: int = 6      # UTC hour
    # Trade window
    trade_start: int = 8    # UTC hour to place orders
    trade_end: int = 16     # UTC hour to close everything
    # Strategy params
    rr_ratio: float = 2.0
    min_range_pct: float = 0.05
    max_range_pct: float = 2.0
    skip_weekdays: list = field(default_factory=lambda: [2])  # Wednesday
    # Exit rules
    time_exit_minutes: float = 60  # 0 = disabled
    # Entry method
    entry_method: str = 'stop'  # 'stop', 'limit_retest', 'confirm_close', 'market_at_cross'


def simulate_stop_entry(bar, level: float, side: str) -> bool:
    """Check if a stop order at `level` would be triggered by this bar."""
    if side == 'BUY':
        return bar['high'] >= level
    else:
        return bar['low'] <= level


def simulate_limit_entry(bar, level: float, side: str) -> bool:
    """Check if a limit order at `level` would be triggered by this bar."""
    if side == 'BUY':
        return bar['low'] <= level  # price comes down to our bid
    else:
        return bar['high'] >= level  # price comes up to our offer


def backtest_orb_tick(df: pd.DataFrame, cfg: BacktestConfig) -> list[Trade]:
    """
    Run the ORB backtest on tick-bar data.

    Entry methods:
    - 'stop': place buy stop at range_high, sell stop at range_low at trade_start.
              Fill at NEXT bar open when triggered. (Most realistic simulation of v5 live.)
    - 'limit_retest': wait for price to cross level, then place limit at level.
              Fill when price pulls back to the level. (Retest entry.)
    - 'confirm_close': wait for a bar to CLOSE above/below level.
              Enter at next bar open. (Confirmation entry.)
    - 'market_at_cross': enter at market when first bar crosses the level.
              Fill at that bar's close (simulating you see the cross and click buy.)
    """
    trades = []

    for day, day_df in df.groupby('date'):
        weekday = day_df['weekday'].iloc[0]
        if weekday >= 5:
            continue
        if weekday in cfg.skip_weekdays:
            continue

        # ── Compute Asian range ──
        asian = day_df[(day_df['hour'] >= cfg.range_start) & (day_df['hour'] < cfg.range_end)]
        if len(asian) < 5:  # need some bars
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

        # ── Trade window bars ──
        window = day_df[(day_df['hour'] >= cfg.trade_start) & (day_df['hour'] < cfg.trade_end)]
        if len(window) < 2:
            continue

        # ── Entry logic ──
        trade = _run_entry_and_trade(
            window, cfg, rh, rl, rs, tp_long, tp_short, day
        )
        if trade is not None:
            trades.append(trade)

    return trades


def _run_entry_and_trade(
    window: pd.DataFrame, cfg: BacktestConfig,
    rh: float, rl: float, rs: float,
    tp_long: float, tp_short: float, day
) -> Optional[Trade]:
    """Execute entry logic and simulate the trade."""

    bars = list(window.iterrows())
    n_bars = len(bars)

    if cfg.entry_method == 'stop':
        return _entry_stop(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day)
    elif cfg.entry_method == 'limit_retest':
        return _entry_limit_retest(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day)
    elif cfg.entry_method == 'confirm_close':
        return _entry_confirm_close(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day)
    elif cfg.entry_method == 'market_at_cross':
        return _entry_market_at_cross(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day)
    else:
        raise ValueError(f"Unknown entry_method: {cfg.entry_method}")


def _entry_stop(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day) -> Optional[Trade]:
    """
    Stop order entry: buy stop at range_high, sell stop at range_low.
    When triggered, fill at NEXT bar's open + half spread.
    """
    for i in range(n_bars - 1):
        ts, bar = bars[i]
        ts_next, bar_next = bars[i + 1]

        spread = bar['avg_spread']
        half_spread = spread / 2

        # Check if stop triggered
        direction = None
        if bar['high'] >= rh:
            direction = 'LONG'
        elif bar['low'] <= rl:
            direction = 'SHORT'

        if direction is None:
            continue

        # Fill at next bar's open + spread
        next_spread = bar_next['avg_spread']
        next_half = next_spread / 2

        if direction == 'LONG':
            # First bar where high >= rh: entry triggered
            # If open was already above rh, it's a gap-open
            if bar['open'] >= rh:
                entry_px = bar['open'] + half_spread  # gap: fill at current market
                gap = bar['open'] - rh
            else:
                entry_px = rh + half_spread  # stop: fill at level
                gap = 0
            sl_px = rl
            tp_px = tp_long
        else:
            if bar['open'] <= rl:
                entry_px = bar['open'] - half_spread
                gap = rl - bar['open']
            else:
                entry_px = rl - half_spread
                gap = 0
            sl_px = rh
            tp_px = tp_short

        # Simulate trade from entry
        return _monitor_trade(
            bars, i + 1, n_bars, cfg, direction, entry_px, sl_px, tp_px,
            ts, rh, rl, rs, day, 'stop_fill', gap, bar
        )

    return None


def _entry_limit_retest(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day) -> Optional[Trade]:
    """
    Retest entry: wait for level to be broken, then place limit order at the level.
    Fill when price returns to the level (support/resistance flip).
    """
    level_broken_long = False
    level_broken_short = False

    for i in range(n_bars - 1):
        ts, bar = bars[i]
        half_spread = bar['avg_spread'] / 2

        # Track if levels have been broken
        if bar['high'] >= rh:
            level_broken_long = True
        if bar['low'] <= rl:
            level_broken_short = True

        # If both broken, skip (ranging day)
        if level_broken_long and level_broken_short:
            return None

        # After break above rh, wait for pullback to rh (limit buy)
        if level_broken_long and not level_broken_short:
            if bar['low'] <= rh:  # price pulled back to the level
                entry_px = rh + half_spread  # fill at the level
                direction = 'LONG'
                return _monitor_trade(
                    bars, i + 1, n_bars, cfg, direction, entry_px, rl, tp_long,
                    ts, rh, rl, rs, day, 'limit_fill', 0, bar
                )

        # After break below rl, wait for pullback to rl (limit sell)
        if level_broken_short and not level_broken_long:
            if bar['high'] >= rl:
                entry_px = rl - half_spread
                direction = 'SHORT'
                return _monitor_trade(
                    bars, i + 1, n_bars, cfg, direction, entry_px, rh, tp_short,
                    ts, rh, rl, rs, day, 'limit_fill', 0, bar
                )

    return None


def _entry_confirm_close(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day) -> Optional[Trade]:
    """
    Confirmation entry: wait for a bar to CLOSE above/below the level.
    Enter at next bar's open. Avoids false breakouts (wick touches).
    """
    for i in range(n_bars - 1):
        ts, bar = bars[i]

        direction = None
        if bar['close'] > rh:
            direction = 'LONG'
        elif bar['close'] < rl:
            direction = 'SHORT'

        if direction is None:
            continue

        # Enter at next bar's open
        ts_next, bar_next = bars[i + 1]
        half_spread = bar_next['avg_spread'] / 2

        if direction == 'LONG':
            entry_px = bar_next['open'] + half_spread
            gap = entry_px - rh - half_spread  # how far past level
        else:
            entry_px = bar_next['open'] - half_spread
            gap = rl - entry_px - half_spread

        return _monitor_trade(
            bars, i + 1, n_bars, cfg, direction, entry_px,
            rl if direction == 'LONG' else rh,
            tp_long if direction == 'LONG' else tp_short,
            ts_next, rh, rl, rs, day, 'confirm_fill', max(0, gap), bar_next
        )

    return None


def _entry_market_at_cross(bars, n_bars, cfg, rh, rl, rs, tp_long, tp_short, day) -> Optional[Trade]:
    """
    Market entry at cross: when a bar's high/low first touches the level,
    enter at that bar's close (simulating: you see the breakout and act).
    """
    for i in range(n_bars - 1):
        ts, bar = bars[i]
        half_spread = bar['avg_spread'] / 2

        direction = None
        if bar['high'] >= rh:
            direction = 'LONG'
            entry_px = bar['close'] + half_spread
            gap = max(0, entry_px - rh - half_spread)
        elif bar['low'] <= rl:
            direction = 'SHORT'
            entry_px = bar['close'] - half_spread
            gap = max(0, rl - entry_px - half_spread)
        else:
            continue

        return _monitor_trade(
            bars, i + 1, n_bars, cfg, direction, entry_px,
            rl if direction == 'LONG' else rh,
            tp_long if direction == 'LONG' else tp_short,
            ts, rh, rl, rs, day, 'market_fill', gap, bar
        )

    return None


def _monitor_trade(
    bars, start_idx, n_bars, cfg, direction, entry_px, sl_px, tp_px,
    entry_ts, rh, rl, rs, day, entry_type, gap, entry_bar
) -> Trade:
    """Monitor an open trade: check SL, TP, time exit, EOD."""

    exit_px = None
    exit_type = 'EOD'
    exit_ts = entry_ts
    exit_spread = 0

    entry_time_dt = entry_ts

    for j in range(start_idx, n_bars):
        ts, bar = bars[j]
        half_spread = bar['avg_spread'] / 2

        # Time exit check
        if cfg.time_exit_minutes > 0:
            elapsed = (ts - entry_time_dt).total_seconds() / 60
            if elapsed >= cfg.time_exit_minutes:
                exit_px = bar['open'] - half_spread if direction == 'LONG' else bar['open'] + half_spread
                exit_type = 'TIME_EXIT'
                exit_ts = ts
                exit_spread = half_spread
                break

        # SL/TP check
        if direction == 'LONG':
            if bar['low'] <= sl_px:
                exit_px = sl_px - half_spread
                exit_type = 'SL'
                exit_ts = ts
                exit_spread = half_spread
                break
            if bar['high'] >= tp_px:
                exit_px = tp_px - half_spread  # TP is a limit sell, gets better fill
                exit_type = 'TP'
                exit_ts = ts
                exit_spread = half_spread
                break
        else:
            if bar['high'] >= sl_px:
                exit_px = sl_px + half_spread
                exit_type = 'SL'
                exit_ts = ts
                exit_spread = half_spread
                break
            if bar['low'] <= tp_px:
                exit_px = tp_px + half_spread
                exit_type = 'TP'
                exit_ts = ts
                exit_spread = half_spread
                break

    # EOD fallback
    if exit_px is None:
        last_ts, last_bar = bars[-1]
        half_spread = last_bar['avg_spread'] / 2
        exit_px = last_bar['close'] - half_spread if direction == 'LONG' else last_bar['close'] + half_spread
        exit_ts = last_ts
        exit_spread = half_spread

    # Calculate P&L
    raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)
    entry_spread = entry_bar['avg_spread'] / 2
    hold_min = (exit_ts - entry_time_dt).total_seconds() / 60

    return Trade(
        date=day,
        direction=direction,
        entry_price=round(entry_px, 2),
        exit_price=round(exit_px, 2),
        entry_time=entry_time_dt,
        exit_time=exit_ts,
        entry_type=entry_type,
        exit_type=exit_type,
        range_high=round(rh, 2),
        range_low=round(rl, 2),
        range_size=round(rs, 2),
        pnl=round(raw_pnl, 2),
        spread_cost=round(entry_spread + exit_spread, 3),
        entry_spread=round(entry_spread, 3),
        exit_spread=round(exit_spread, 3),
        hold_minutes=round(hold_min, 1),
        entry_hour=entry_time_dt.hour,
        gap_from_level=round(gap, 2),
        vol_imbalance_at_entry=entry_bar.get('vol_imbalance', 0),
        buy_ratio_at_entry=entry_bar.get('buy_ratio', 0.5),
        tick_velocity_at_entry=entry_bar.get('tick_velocity', 0),
    )


# ── Statistics ────────────────────────────────────────────────────────────

def compute_stats(trades: list[Trade], label: str = '') -> dict:
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
    total = pnl.sum()

    # Max consecutive losses
    streak = 0
    mcl = 0
    for v in pnl:
        if v < 0:
            streak += 1
            mcl = max(mcl, streak)
        else:
            streak = 0

    return {
        'label': label,
        'n': n,
        'sharpe': round(sharpe, 2),
        'pf': round(pf, 2),
        'wr': round(wr, 1),
        'mean': round(mean, 2),
        'total': round(total, 2),
        'max_dd': round(dd, 2),
        'mcl': mcl,
        'avg_spread_cost': round(pd.Series([t.spread_cost for t in trades]).mean(), 3),
    }


def print_stats(s: dict):
    if s['n'] == 0:
        print(f"  {s['label']}: NO TRADES")
        return
    print(f"  {s['label']:>25}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
          f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | "
          f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
          f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2} | "
          f"SpreadCost ${s['avg_spread_cost']:.3f}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    df = load_tick_bars()
    print(f"Loaded {len(df):,} tick bars ({df.index.min().date()} to {df.index.max().date()})")
    print(f"Days: {df['date'].nunique()}")

    oos_start = pd.Timestamp('2021-01-01').date()

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Compare entry methods (all with 60-min time exit, start=8)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  1. ENTRY METHOD COMPARISON (trade_start=8, time_exit=60min)")
    print("=" * 120)

    methods = ['stop', 'limit_retest', 'confirm_close', 'market_at_cross']
    for method in methods:
        cfg = BacktestConfig(entry_method=method, time_exit_minutes=60)
        trades = backtest_orb_tick(df, cfg)
        s = compute_stats(trades, method)
        print_stats(s)

        # OOS
        oos_trades = [t for t in trades if t.date >= oos_start]
        so = compute_stats(oos_trades, f"{method} (OOS)")
        print_stats(so)
        print()

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Compare entry methods WITHOUT time exit (raw edge)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  2. ENTRY METHOD COMPARISON (trade_start=8, NO time exit)")
    print("=" * 120)

    for method in methods:
        cfg = BacktestConfig(entry_method=method, time_exit_minutes=0)
        trades = backtest_orb_tick(df, cfg)
        s = compute_stats(trades, method)
        print_stats(s)

        oos_trades = [t for t in trades if t.date >= oos_start]
        so = compute_stats(oos_trades, f"{method} (OOS)")
        print_stats(so)
        print()

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Time exit sweep for each method
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  3. TIME EXIT SWEEP per entry method")
    print("=" * 120)

    for method in methods:
        print(f"\n  --- {method.upper()} ---")
        for te in [0, 15, 30, 45, 60, 90, 120]:
            cfg = BacktestConfig(entry_method=method, time_exit_minutes=te)
            trades = backtest_orb_tick(df, cfg)
            label = f"te={te}min" if te > 0 else "te=none"
            s = compute_stats(trades, label)
            oos_trades = [t for t in trades if t.date >= oos_start]
            so = compute_stats(oos_trades, "")
            print(f"    {label:>10}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
                  f"PF {s['pf']:>5.2f} | DD ${s['max_dd']:>+9.2f} | "
                  f"Total ${s['total']:>+10.2f} | OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Trade start sweep (how early should we watch?)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  4. TRADE START SWEEP (stop entry, 60min time exit)")
    print("=" * 120)

    for start in [6, 7, 8, 9, 10]:
        cfg = BacktestConfig(trade_start=start, entry_method='stop', time_exit_minutes=60)
        trades = backtest_orb_tick(df, cfg)
        s = compute_stats(trades, f"start={start}")
        oos_trades = [t for t in trades if t.date >= oos_start]
        so = compute_stats(oos_trades, "")

        gap_trades = [t for t in trades if t.gap_from_level > 0]
        gap_pct = len(gap_trades) / len(trades) * 100 if trades else 0

        print(f"    start={start}: N={s['n']:>5} | Gap%={gap_pct:>5.1f}% | "
              f"Sh {s['sharpe']:>6.2f} | PF {s['pf']:>5.2f} | "
              f"DD ${s['max_dd']:>+9.2f} | Total ${s['total']:>+10.2f} | "
              f"OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Volume/momentum filters on stop entry
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  5. VOLUME/MOMENTUM FILTERS (stop entry, start=8, 60min time exit)")
    print("=" * 120)

    cfg = BacktestConfig(entry_method='stop', time_exit_minutes=60)
    all_trades = backtest_orb_tick(df, cfg)

    # Filter by buy_ratio at entry (momentum confirmation)
    print(f"\n  Buy ratio filter (for LONG: want high; for SHORT: want low):")
    for threshold in [0.0, 0.45, 0.50, 0.55, 0.60]:
        filtered = [t for t in all_trades if (
            (t.direction == 'LONG' and t.buy_ratio_at_entry >= threshold) or
            (t.direction == 'SHORT' and t.buy_ratio_at_entry <= (1 - threshold))
        )]
        s = compute_stats(filtered, f"ratio>={threshold:.2f}")
        print(f"    ratio>={threshold:.2f}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
              f"PF {s['pf']:>5.2f} | Total ${s['total']:>+10.2f}")

    # Filter by tick velocity (high = fast market)
    print(f"\n  Tick velocity filter:")
    velocities = [t.tick_velocity_at_entry for t in all_trades]
    for pctile in [0, 25, 50, 75]:
        thresh = np.percentile(velocities, pctile)
        filtered = [t for t in all_trades if t.tick_velocity_at_entry >= thresh]
        s = compute_stats(filtered, f"vel>=P{pctile}")
        print(f"    vel>=P{pctile:>2} ({thresh:.2f}): N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
              f"PF {s['pf']:>5.2f} | Total ${s['total']:>+10.2f}")

    # Filter by gap size (skip large gaps)
    print(f"\n  Gap filter (skip trades where gap > X):")
    for max_gap in [0, 1, 2, 5, 10, 999]:
        filtered = [t for t in all_trades if t.gap_from_level <= max_gap]
        s = compute_stats(filtered, f"gap<=${max_gap}")
        label = f"gap<=${max_gap}" if max_gap < 999 else "all"
        print(f"    {label:>10}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
              f"PF {s['pf']:>5.2f} | Total ${s['total']:>+10.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. Annual breakdown for best configs
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*120}")
    print("  6. ANNUAL BREAKDOWN (best configs)")
    print("=" * 120)

    configs = [
        ('stop, te=60', BacktestConfig(entry_method='stop', time_exit_minutes=60)),
        ('limit_retest, te=60', BacktestConfig(entry_method='limit_retest', time_exit_minutes=60)),
        ('confirm_close, te=60', BacktestConfig(entry_method='confirm_close', time_exit_minutes=60)),
        ('stop, no te', BacktestConfig(entry_method='stop', time_exit_minutes=0)),
    ]

    for label, cfg in configs:
        trades = backtest_orb_tick(df, cfg)
        s = compute_stats(trades, label)
        print(f"\n  {label} (Sharpe={s['sharpe']}):")

        # Group by year
        by_year = {}
        for t in trades:
            yr = t.date.year
            if yr not in by_year:
                by_year[yr] = []
            by_year[yr].append(t)

        for yr in sorted(by_year):
            ys = compute_stats(by_year[yr], "")
            flag = " <<< LOSS" if ys['total'] < 0 else ""
            print(f"    {yr}: N={ys['n']:>4} | P&L ${ys['total']:>+9.2f} | "
                  f"Sh {ys['sharpe']:>6.2f} | DD ${ys['max_dd']:>+9.2f} | MCL {ys['mcl']}{flag}")

    print(f"\n{'='*120}")
    print("  DONE")
    print("=" * 120)


if __name__ == "__main__":
    main()
