"""
research_rebreak_filter.py -- Can entry-bar order flow predict ORB trade outcomes?

Tests whether the V8 "re-break imbalance" concept has value in ORB context.

Checks:
1. Entry bar direction (close > open = bullish) alignment with trade direction
2. Entry bar buy_ratio alignment with trade direction
3. Post-entry buy_ratio (bars 1-3 after entry) alignment
4. Re-break pattern: first break -> pullback -> re-break, does it filter losers?

Uses existing backtest_1m infrastructure + 1-min XAUUSD data with buy/sell volumes.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from dataclasses import dataclass

# Reuse existing backtest engine
from .backtest_1m import load_1m_bars, backtest, Config, Trade, stats, print_stats

ROOT = Path(__file__).resolve().parents[1]


def main():
    import datetime as dt

    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = dt.date(2021, 1, 1)

    # Run baseline backtest (stop entry, no time exit, velocity unfiltered)
    cfg = Config(entry_method='stop', time_exit_minutes=0)
    all_trades = backtest(df, cfg)
    print(f"Total trades: {len(all_trades)}")
    print_stats(stats(all_trades, "ALL"))
    oos_trades = [t for t in all_trades if t.date >= oos_start]
    print_stats(stats(oos_trades, "ALL OOS"))

    # =====================================================================
    # TEST 1: Entry bar direction alignment
    # Is a bullish entry bar on a LONG trade better than a bearish one?
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 1: ENTRY BAR DIRECTION vs TRADE OUTCOME")
    print("  (Does the close-vs-open of the entry bar predict if the trade wins?)")
    print("=" * 110)

    # We need entry bar close vs open, which isn't stored in Trade directly.
    # Re-derive from the 1-min data using entry_time.
    aligned = []
    opposed = []
    aligned_oos = []
    opposed_oos = []

    for t in all_trades:
        # Look up the entry bar in the dataframe
        try:
            entry_bar = df.loc[t.entry_time]
            bar_bullish = entry_bar['close'] > entry_bar['open']
        except (KeyError, TypeError):
            continue

        if t.direction == 'LONG':
            is_aligned = bar_bullish
        else:
            is_aligned = not bar_bullish

        if is_aligned:
            aligned.append(t)
            if t.date >= oos_start:
                aligned_oos.append(t)
        else:
            opposed.append(t)
            if t.date >= oos_start:
                opposed_oos.append(t)

    print(f"\n  Bar direction ALIGNED with trade direction (bullish bar + LONG, bearish bar + SHORT):")
    print_stats(stats(aligned, "Aligned (full)"))
    print_stats(stats(aligned_oos, "Aligned (OOS)"))
    print(f"\n  Bar direction OPPOSED to trade direction:")
    print_stats(stats(opposed, "Opposed (full)"))
    print_stats(stats(opposed_oos, "Opposed (OOS)"))

    # =====================================================================
    # TEST 2: Entry bar buy_ratio alignment
    # LONG + buy_ratio > 0.5 = matching (buyers dominate on long entry)
    # SHORT + buy_ratio < 0.5 = matching (sellers dominate on short entry)
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 2: ENTRY BAR BUY_RATIO ALIGNMENT vs TRADE OUTCOME")
    print("  (Do buyers dominate on LONG entries that win? Sellers on SHORT winners?)")
    print("=" * 110)

    matching = []
    divergent = []
    matching_oos = []
    divergent_oos = []

    for t in all_trades:
        br = t.entry_buy_ratio
        if br == 0 or np.isnan(br):
            continue
        if t.direction == 'LONG':
            is_match = br > 0.5
        else:
            is_match = br < 0.5

        if is_match:
            matching.append(t)
            if t.date >= oos_start:
                matching_oos.append(t)
        else:
            divergent.append(t)
            if t.date >= oos_start:
                divergent_oos.append(t)

    print(f"\n  Buy_ratio MATCHING trade direction (buyers on LONG, sellers on SHORT):")
    print_stats(stats(matching, "Matching (full)"))
    print_stats(stats(matching_oos, "Matching (OOS)"))
    print(f"\n  Buy_ratio DIVERGENT from trade direction:")
    print_stats(stats(divergent, "Divergent (full)"))
    print_stats(stats(divergent_oos, "Divergent (OOS)"))

    # =====================================================================
    # TEST 3: Buy_ratio quintile analysis on entry bar
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 3: ENTRY BUY_RATIO QUINTILES (for LONG and SHORT separately)")
    print("=" * 110)

    for direction in ['LONG', 'SHORT']:
        dir_trades = [t for t in all_trades if t.direction == direction and t.entry_buy_ratio > 0]
        if not dir_trades:
            continue
        brs = np.array([t.entry_buy_ratio for t in dir_trades])
        edges = np.percentile(brs, [0, 20, 40, 60, 80, 100])

        print(f"\n  {direction} trades (N={len(dir_trades)}):")
        labels = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
        for qi in range(5):
            lo, hi = edges[qi], edges[qi + 1]
            subset = [t for t, b in zip(dir_trades, brs) if lo <= b < (hi if qi < 4 else hi + 0.01)]
            s = stats(subset, labels[qi])
            br_label = "most selling" if qi == 0 else ("most buying" if qi == 4 else "")
            print(f"    {labels[qi]} br={lo:.3f}-{hi:.3f} {br_label:>14}: "
                  f"N={s['n']:>4} | Sh {s['sharpe']:>6.2f} | WR {s['wr']:>5.1f}% | "
                  f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+9.2f}")

    # =====================================================================
    # TEST 4: Post-entry buy_ratio (bars 1-3 after entry)
    # Does flow AFTER entry predict outcome?
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 4: POST-ENTRY BUY_RATIO (avg of bars 1-3 after entry)")
    print("  (Does order flow right after entry predict if the trade wins?)")
    print("=" * 110)

    post_matching = []
    post_divergent = []
    post_matching_oos = []
    post_divergent_oos = []
    post_brs_win = []
    post_brs_lose = []

    for t in all_trades:
        try:
            idx = df.index.get_loc(t.entry_time)
        except (KeyError, TypeError):
            continue

        # Get bars 1, 2, 3 after entry
        post_bars = df.iloc[idx+1:idx+4]
        if len(post_bars) < 3:
            continue

        post_br = post_bars['buy_ratio'].mean()
        if np.isnan(post_br):
            continue

        if t.direction == 'LONG':
            is_match = post_br > 0.5
        else:
            is_match = post_br < 0.5

        if t.pnl > 0:
            post_brs_win.append(post_br if t.direction == 'LONG' else 1 - post_br)
        else:
            post_brs_lose.append(post_br if t.direction == 'LONG' else 1 - post_br)

        if is_match:
            post_matching.append(t)
            if t.date >= oos_start:
                post_matching_oos.append(t)
        else:
            post_divergent.append(t)
            if t.date >= oos_start:
                post_divergent_oos.append(t)

    print(f"\n  Post-entry flow MATCHING:")
    print_stats(stats(post_matching, "Post-match (full)"))
    print_stats(stats(post_matching_oos, "Post-match (OOS)"))
    print(f"\n  Post-entry flow DIVERGENT:")
    print_stats(stats(post_divergent, "Post-div (full)"))
    print_stats(stats(post_divergent_oos, "Post-div (OOS)"))

    if post_brs_win and post_brs_lose:
        print(f"\n  Direction-normalized post-entry buy_ratio:")
        print(f"    Winners: mean={np.mean(post_brs_win):.4f} (>0.5 = flow supports trade)")
        print(f"    Losers:  mean={np.mean(post_brs_lose):.4f}")

    # =====================================================================
    # TEST 5: Simple re-break pattern
    # Does requiring break -> pullback -> re-break filter losers?
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 5: RE-BREAK PATTERN (break -> pullback -> re-break)")
    print("  (Skip first touch; only enter if price breaks, pulls back, re-breaks)")
    print("=" * 110)

    rebreak_trades = _backtest_rebreak(df, cfg)
    print(f"\n  Re-break trades: {len(rebreak_trades)}")
    print_stats(stats(rebreak_trades, "Rebreak (full)"))
    rb_oos = [t for t in rebreak_trades if t.date >= oos_start]
    print_stats(stats(rb_oos, "Rebreak (OOS)"))
    print(f"\n  Comparison to standard stop entry:")
    print_stats(stats(all_trades, "Stop (full)"))
    print_stats(stats(oos_trades, "Stop (OOS)"))

    # =====================================================================
    # TEST 6: Combined: Re-break + matching flow
    # =====================================================================
    print(f"\n{'='*110}")
    print("  TEST 6: RE-BREAK + MATCHING FLOW (V8-style confirmation)")
    print("  (Re-break entry AND buy_ratio must align with direction)")
    print("=" * 110)

    rb_match = [t for t in rebreak_trades if _has_matching_flow(t)]
    rb_div = [t for t in rebreak_trades if not _has_matching_flow(t)]
    print(f"\n  Re-break + matching flow:")
    print_stats(stats(rb_match, "RB+match (full)"))
    rb_match_oos = [t for t in rb_match if t.date >= oos_start]
    print_stats(stats(rb_match_oos, "RB+match (OOS)"))
    print(f"\n  Re-break + divergent flow:")
    print_stats(stats(rb_div, "RB+div (full)"))
    rb_div_oos = [t for t in rb_div if t.date >= oos_start]
    print_stats(stats(rb_div_oos, "RB+div (OOS)"))

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


def _has_matching_flow(t: Trade) -> bool:
    """Check if entry bar buy_ratio aligns with trade direction."""
    br = t.entry_buy_ratio
    if br == 0 or np.isnan(br):
        return True  # no data, assume matching
    if t.direction == 'LONG':
        return br > 0.5
    else:
        return br < 0.5


def _backtest_rebreak(df: pd.DataFrame, cfg: Config) -> list[Trade]:
    """
    Re-break entry: instead of entering on first touch of range level,
    require: first break -> pullback inside range -> second break.
    """
    from .backtest_1m import _monitor
    import datetime as dt

    trades = []

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5 or wd in cfg.skip_weekdays:
            continue

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

        window = day_df[(day_df['hour'] >= cfg.trade_start) & (day_df['hour'] < cfg.trade_end)]
        if len(window) < 5:
            continue

        bars = list(window.iterrows())
        n = len(bars)

        # State machine: track first break and pullback per side
        broke_high = False
        pullback_high = False
        broke_low = False
        pullback_low = False

        for i in range(n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            # Track high-side breakout state
            if not broke_high:
                if bar['high'] >= rh:
                    broke_high = True
            elif not pullback_high:
                if bar['close'] < rh:  # pulled back below level
                    pullback_high = True
            else:
                # Waiting for re-break of high
                if bar['high'] >= rh:
                    # RE-BREAK! Enter long
                    if bar['open'] >= rh:
                        entry_px = bar['open'] + hs
                    else:
                        entry_px = rh + hs
                    sl = rl
                    tp = tp_long

                    trade = _monitor(bars, i + 1, n, cfg, 'LONG', entry_px, sl, tp,
                                     ts, rh, rl, rs, day, 'rebreak', 0, bar)
                    if trade is not None:
                        trades.append(trade)
                    break

            # Track low-side breakout state
            if not broke_low:
                if bar['low'] <= rl:
                    broke_low = True
            elif not pullback_low:
                if bar['close'] > rl:  # pulled back above level
                    pullback_low = True
            else:
                # Waiting for re-break of low
                if bar['low'] <= rl:
                    # RE-BREAK! Enter short
                    if bar['open'] <= rl:
                        entry_px = bar['open'] - hs
                    else:
                        entry_px = rl - hs
                    sl = rh
                    tp = tp_short

                    trade = _monitor(bars, i + 1, n, cfg, 'SHORT', entry_px, sl, tp,
                                     ts, rh, rl, rs, day, 'rebreak', 0, bar)
                    if trade is not None:
                        trades.append(trade)
                    break

            # If both sides have broken out (chopped through both levels), skip day
            if broke_high and broke_low:
                break

    return trades


if __name__ == "__main__":
    main()
