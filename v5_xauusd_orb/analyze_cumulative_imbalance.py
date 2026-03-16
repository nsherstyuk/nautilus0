"""
Analyze CUMULATIVE volume imbalance over N bars leading up to ORB breakout.

Hypothesis: Building buy/sell pressure over several bars before the breakout
is a stronger signal than the single entry bar's buy_ratio.

Approach:
  - For each trade day, find the breakout bar
  - Look back N bars (3, 5, 10) and compute cumulative imbalance metrics
  - Test whether pre-breakout pressure direction predicts trade outcome
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import datetime as dt
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_1m import load_1m_bars, Config, stats, print_stats


@dataclass
class EnrichedTrade:
    date: object
    direction: str
    pnl: float
    exit_type: str
    entry_tick_count: int
    entry_buy_ratio: float
    # Cumulative imbalance features
    cum_buy_ratio_3: float    # avg buy_ratio over 3 bars before entry
    cum_buy_ratio_5: float    # avg buy_ratio over 5 bars before entry
    cum_buy_ratio_10: float   # avg buy_ratio over 10 bars before entry
    cum_imbalance_3: float    # sum vol_imbalance over 3 bars
    cum_imbalance_5: float    # sum vol_imbalance over 5 bars
    cum_imbalance_10: float   # sum vol_imbalance over 10 bars
    pressure_agreement_3: bool  # does 3-bar pressure match direction?
    pressure_agreement_5: bool
    pressure_agreement_10: bool


def run_enriched_backtest(df: pd.DataFrame, cfg: Config) -> list[EnrichedTrade]:
    """Run backtest with cumulative imbalance lookback features."""
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

        bars = list(window.iterrows())
        n = len(bars)

        # Find breakout bar
        for i in range(n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            direction = None
            entry_px = None

            if bar['high'] >= rh:
                direction = 'LONG'
                entry_px = rh + hs if bar['open'] < rh else bar['open'] + hs
            elif bar['low'] <= rl:
                direction = 'SHORT'
                entry_px = rl - hs if bar['open'] > rl else bar['open'] - hs

            if direction is None:
                continue

            sl = rl if direction == 'LONG' else rh
            tp = tp_long if direction == 'LONG' else tp_short

            # Compute cumulative imbalance over lookback windows
            # Use ALL bars available up to (but not including) entry bar
            # This includes pre-trade-window bars from the full day
            entry_time = ts
            all_before = day_df[day_df.index < entry_time]

            cum_features = {}
            for lookback in [3, 5, 10]:
                recent = all_before.tail(lookback)
                if len(recent) >= max(lookback // 2, 1):
                    avg_br = recent['buy_ratio'].mean()
                    sum_imb = recent['vol_imbalance'].sum()
                else:
                    avg_br = 0.5
                    sum_imb = 0

                cum_features[f'cum_buy_ratio_{lookback}'] = avg_br
                cum_features[f'cum_imbalance_{lookback}'] = sum_imb

                # Pressure agreement: positive imbalance = buy pressure
                if direction == 'LONG':
                    cum_features[f'pressure_agreement_{lookback}'] = avg_br > 0.50
                else:
                    cum_features[f'pressure_agreement_{lookback}'] = avg_br < 0.50

            # Monitor trade outcome (simplified from backtest_1m._monitor)
            exit_px = None
            exit_type = 'EOD'

            for j in range(i + 1, n):
                ts_j, bar_j = bars[j]
                hs_j = bar_j['avg_spread'] / 2

                if direction == 'LONG':
                    if bar_j['low'] <= sl:
                        exit_px = sl - hs_j
                        exit_type = 'SL'
                        break
                    if bar_j['high'] >= tp:
                        exit_px = tp - hs_j
                        exit_type = 'TP'
                        break
                else:
                    if bar_j['high'] >= sl:
                        exit_px = sl + hs_j
                        exit_type = 'SL'
                        break
                    if bar_j['low'] <= tp:
                        exit_px = tp + hs_j
                        exit_type = 'TP'
                        break

            if exit_px is None:
                last_ts, last_bar = bars[-1]
                hs_last = last_bar['avg_spread'] / 2
                exit_px = last_bar['close'] - hs_last if direction == 'LONG' else last_bar['close'] + hs_last

            raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)

            trades.append(EnrichedTrade(
                date=day,
                direction=direction,
                pnl=round(raw_pnl, 3),
                exit_type=exit_type,
                entry_tick_count=int(bar.get('tick_count', 0)),
                entry_buy_ratio=round(bar.get('buy_ratio', 0.5), 4),
                **cum_features
            ))
            break  # one trade per day

    return trades


def enriched_stats(trades: list[EnrichedTrade], label: str = '') -> dict:
    """Same stats function adapted for EnrichedTrade."""
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


def print_estats(s: dict):
    if s['n'] == 0:
        print(f"  {s['label']:>35}: NO TRADES")
        return
    print(f"  {s['label']:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
          f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | "
          f"Mean ${s['mean']:>+7.2f} | Total ${s['total']:>+10.2f} | "
          f"DD ${s['max_dd']:>+9.2f} | MCL {s['mcl']:>2}")


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    oos_start = dt.date(2021, 1, 1)
    cfg = Config(entry_method='stop', time_exit_minutes=0)

    print("Running enriched backtest with cumulative imbalance features...")
    trades = run_enriched_backtest(df, cfg)
    oos = [t for t in trades if t.date >= oos_start]

    print(f"\nBaseline: {len(trades)} trades ({len(oos)} OOS)")
    print_estats(enriched_stats(trades, "ALL"))
    print_estats(enriched_stats(oos, "OOS"))

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Cumulative buy_ratio distribution
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  1. CUMULATIVE BUY RATIO DISTRIBUTION (avg over N bars before entry)")
    print("=" * 110)

    for lookback in [3, 5, 10]:
        field = f'cum_buy_ratio_{lookback}'
        longs = [getattr(t, field) for t in trades if t.direction == 'LONG']
        shorts = [getattr(t, field) for t in trades if t.direction == 'SHORT']
        print(f"\n  {lookback}-bar lookback:")
        print(f"    LONG:  mean={np.mean(longs):.4f}, median={np.median(longs):.4f}, "
              f"std={np.std(longs):.4f}")
        print(f"    SHORT: mean={np.mean(shorts):.4f}, median={np.median(shorts):.4f}, "
              f"std={np.std(shorts):.4f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Pressure agreement vs disagreement (3, 5, 10 bar)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  2. PRESSURE AGREEMENT vs DISAGREEMENT by lookback window")
    print("=" * 110)

    for lookback in [3, 5, 10]:
        field = f'pressure_agreement_{lookback}'
        agree = [t for t in trades if getattr(t, field)]
        disagree = [t for t in trades if not getattr(t, field)]
        agree_oos = [t for t in agree if t.date >= oos_start]
        disagree_oos = [t for t in disagree if t.date >= oos_start]

        print(f"\n  --- {lookback}-bar lookback ---")
        print_estats(enriched_stats(agree, f"{lookback}bar AGREES"))
        print_estats(enriched_stats(disagree, f"{lookback}bar DISAGREES"))
        print_estats(enriched_stats(agree_oos, f"{lookback}bar AGREES (OOS)"))
        print_estats(enriched_stats(disagree_oos, f"{lookback}bar DISAGREES (OOS)"))

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Threshold sweep on cumulative buy_ratio
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  3. THRESHOLD SWEEP: cumulative buy_ratio over 5 bars before entry")
    print("=" * 110)

    base_sh = enriched_stats(trades)['sharpe']

    print(f"\n  {'Thresh':>8} | {'N_pass':>6} | {'N_rej':>5} | {'Sh_pass':>7} | {'Sh_rej':>6} | "
          f"{'WR_pass':>7} | {'Total_pass':>10} | {'OOS_Sh':>6} | {'Better':>6}")
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*6}-+-{'-'*7}-+-{'-'*10}-+-{'-'*6}-+-{'-'*6}")

    for thresh in [0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.58, 0.60]:
        passed = [t for t in trades if
                  (t.direction == 'LONG' and t.cum_buy_ratio_5 > thresh) or
                  (t.direction == 'SHORT' and t.cum_buy_ratio_5 < (1.0 - thresh))]
        rejected = [t for t in trades if t not in passed]
        passed_oos = [t for t in passed if t.date >= oos_start]

        sp = enriched_stats(passed)
        sr = enriched_stats(rejected)
        sp_oos = enriched_stats(passed_oos)

        better = "YES" if sp['sharpe'] > base_sh else "no"
        print(f"  {thresh:>8.2f} | {sp['n']:>6} | {sr['n']:>5} | {sp['sharpe']:>7.2f} | "
              f"{sr['sharpe']:>6.2f} | {sp['wr']:>6.1f}% | "
              f"${sp['total']:>+9.2f} | {sp_oos['sharpe']:>6.2f} | {better:>6}")

    # Same for 10-bar lookback
    print(f"\n  --- Same sweep, 10-bar lookback ---")
    print(f"\n  {'Thresh':>8} | {'N_pass':>6} | {'N_rej':>5} | {'Sh_pass':>7} | {'Sh_rej':>6} | "
          f"{'WR_pass':>7} | {'Total_pass':>10} | {'OOS_Sh':>6} | {'Better':>6}")
    print(f"  {'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*6}-+-{'-'*7}-+-{'-'*10}-+-{'-'*6}-+-{'-'*6}")

    for thresh in [0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.58, 0.60]:
        passed = [t for t in trades if
                  (t.direction == 'LONG' and t.cum_buy_ratio_10 > thresh) or
                  (t.direction == 'SHORT' and t.cum_buy_ratio_10 < (1.0 - thresh))]
        rejected = [t for t in trades if t not in passed]
        passed_oos = [t for t in passed if t.date >= oos_start]

        sp = enriched_stats(passed)
        sr = enriched_stats(rejected)
        sp_oos = enriched_stats(passed_oos)

        better = "YES" if sp['sharpe'] > base_sh else "no"
        print(f"  {thresh:>8.2f} | {sp['n']:>6} | {sr['n']:>5} | {sp['sharpe']:>7.2f} | "
              f"{sr['sharpe']:>6.2f} | {sp['wr']:>6.1f}% | "
              f"${sp['total']:>+9.2f} | {sp_oos['sharpe']:>6.2f} | {better:>6}")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. Combined: velocity + cumulative imbalance
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  4. COMBINED: velocity (tick_count >= median) + cumulative imbalance")
    print("=" * 110)

    tc_med = np.median([t.entry_tick_count for t in trades])
    fast = [t for t in trades if t.entry_tick_count >= tc_med]

    print(f"\n  Velocity filter: tick_count >= {tc_med:.0f}")
    print_estats(enriched_stats(fast, "Velocity only"))
    print_estats(enriched_stats([t for t in fast if t.date >= oos_start], "Velocity only (OOS)"))

    for lookback in [5, 10]:
        field = f'cum_buy_ratio_{lookback}'
        for thresh in [0.50, 0.52, 0.54]:
            combined = [t for t in fast if
                        (t.direction == 'LONG' and getattr(t, field) > thresh) or
                        (t.direction == 'SHORT' and getattr(t, field) < (1.0 - thresh))]
            combined_oos = [t for t in combined if t.date >= oos_start]

            label = f"Vel+{lookback}bar>{thresh:.2f}"
            print_estats(enriched_stats(combined, label))
            print_estats(enriched_stats(combined_oos, f"{label} OOS"))

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Walk-forward: train cumulative imbalance threshold
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  5. WALK-FORWARD: Train 5-bar cumulative imbalance threshold on 3yr")
    print("=" * 110)

    by_year = {}
    for t in trades:
        by_year.setdefault(t.date.year, []).append(t)
    years = sorted(by_year.keys())

    print(f"\n  {'Test':>6} | {'Train':>12} | {'Thresh':>6} | {'N_all':>6} | {'N_filt':>6} | "
          f"{'Sh_all':>7} | {'Sh_filt':>7} | {'Sh_rej':>7} | {'Better?':>8}")

    wf_helps = 0
    wf_total = 0

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in trades if t.date.year in train_yrs]
        test_trades = [t for t in trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_trades) < 10:
            continue

        # Find optimal threshold on training data
        best_thresh = 0.50
        best_sh = enriched_stats(train_trades)['sharpe']
        for th in [0.50, 0.51, 0.52, 0.53, 0.54, 0.55]:
            filt = [t for t in train_trades if
                    (t.direction == 'LONG' and t.cum_buy_ratio_5 > th) or
                    (t.direction == 'SHORT' and t.cum_buy_ratio_5 < (1.0 - th))]
            if len(filt) >= 20:
                sh = enriched_stats(filt)['sharpe']
                if sh > best_sh:
                    best_sh = sh
                    best_thresh = th

        # Apply to test year
        test_filt = [t for t in test_trades if
                     (t.direction == 'LONG' and t.cum_buy_ratio_5 > best_thresh) or
                     (t.direction == 'SHORT' and t.cum_buy_ratio_5 < (1.0 - best_thresh))]
        test_rej = [t for t in test_trades if t not in test_filt]

        sh_all = enriched_stats(test_trades)['sharpe']
        sh_filt = enriched_stats(test_filt)['sharpe'] if len(test_filt) >= 5 else 0
        sh_rej = enriched_stats(test_rej)['sharpe'] if len(test_rej) >= 5 else 0

        wf_total += 1
        helps = sh_filt > sh_all
        if helps:
            wf_helps += 1

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {best_thresh:>6.2f} | "
              f"{len(test_trades):>6} | {len(test_filt):>6} | "
              f"{sh_all:>7.2f} | {sh_filt:>7.2f} | {sh_rej:>7.2f} | "
              f"{'YES' if helps else 'no':>8}")

    print(f"\n  Filter helps in {wf_helps}/{wf_total} years ({wf_helps/max(wf_total,1)*100:.0f}%)")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
