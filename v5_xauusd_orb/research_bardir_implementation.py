"""
research_bardir_implementation.py -- Compare two ways to implement the
"entry bar direction" filter in live ORB trading:

Approach A: CONFIRM-CLOSE ENTRY
  Wait for the 1-min bar to CLOSE beyond the range level.
  Enter on the NEXT bar's open. This guarantees a bullish close for LONG
  (bearish for SHORT) by definition.
  Trade-off: delayed entry (up to 1 min), worse fill price.

Approach B: POST-FILL GATE
  Enter immediately on stop trigger (current behavior).
  At the END of the entry bar, check close-vs-open.
  If OPPOSED (bearish bar on LONG, bullish bar on SHORT) → exit at close.
  If ALIGNED → hold the trade normally.
  Trade-off: take the spread hit on scratched trades, but get better fills
  on the good ones.

Both approaches are tested with walk-forward validation.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from .backtest_1m import load_1m_bars, backtest, Config, Trade, stats, print_stats, _monitor

ROOT = Path(__file__).resolve().parents[1]


def main():
    df = load_1m_bars()
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    cfg = Config(entry_method='stop', time_exit_minutes=0)

    # =====================================================================
    # BASELINE: Standard stop entry (current behavior)
    # =====================================================================
    baseline_trades = backtest(df, cfg)
    print(f"\nBaseline (stop entry): {len(baseline_trades)} trades")
    print_stats(stats(baseline_trades, "Baseline"))

    # =====================================================================
    # APPROACH A: Confirm-close entry
    # Already implemented in backtest_1m.py as 'confirm_close'
    # =====================================================================
    print(f"\n{'='*120}")
    print("  APPROACH A: CONFIRM-CLOSE ENTRY")
    print("  (Wait for bar CLOSE beyond level, enter next bar open)")
    print("=" * 120)

    cfg_cc = Config(entry_method='confirm_close', time_exit_minutes=0)
    cc_trades = backtest(df, cfg_cc)
    print(f"\n  Confirm-close trades: {len(cc_trades)}")
    print_stats(stats(cc_trades, "ConfirmClose (full)"))

    import datetime as dt
    oos_start = dt.date(2021, 1, 1)
    cc_oos = [t for t in cc_trades if t.date >= oos_start]
    print_stats(stats(cc_oos, "ConfirmClose (OOS)"))

    base_oos = [t for t in baseline_trades if t.date >= oos_start]
    print(f"\n  vs Baseline:")
    print_stats(stats(base_oos, "Baseline (OOS)"))

    # Annual breakdown
    print(f"\n  Annual comparison (Confirm-close vs Baseline):")
    print(f"  {'Year':>6} | {'N_base':>6} | {'N_cc':>6} | {'Sh_base':>7} | {'Sh_cc':>7} | "
          f"{'Mean_base':>9} | {'Mean_cc':>9} | {'Tot_base':>10} | {'Tot_cc':>10} | {'CC better?':>10}")

    by_year_base = {}
    for t in baseline_trades:
        by_year_base.setdefault(t.date.year, []).append(t)
    by_year_cc = {}
    for t in cc_trades:
        by_year_cc.setdefault(t.date.year, []).append(t)

    years = sorted(set(list(by_year_base.keys()) + list(by_year_cc.keys())))
    cc_wins = 0
    cc_total = 0

    for yr in years:
        sb = stats(by_year_base.get(yr, []), '')
        sc = stats(by_year_cc.get(yr, []), '')
        better = sc['sharpe'] > sb['sharpe'] if sc['n'] > 0 and sb['n'] > 0 else False
        cc_total += 1
        if better:
            cc_wins += 1
        print(f"  {yr:>6} | {sb['n']:>6} | {sc['n']:>6} | {sb['sharpe']:>7.2f} | {sc['sharpe']:>7.2f} | "
              f"${sb['mean']:>+8.2f} | ${sc['mean']:>+8.2f} | ${sb['total']:>+9.2f} | ${sc['total']:>+9.2f} | "
              f"{'YES' if better else 'no':>10}")

    print(f"\n  CC better in {cc_wins}/{cc_total} years ({cc_wins/max(cc_total,1)*100:.0f}%)")

    # =====================================================================
    # APPROACH B: Post-fill gate
    # Enter on stop. At end of entry bar, if bar direction is opposed,
    # exit at bar close. Otherwise hold normally.
    # =====================================================================
    print(f"\n{'='*120}")
    print("  APPROACH B: POST-FILL GATE")
    print("  (Enter on stop, exit at entry bar close if bar direction is opposed)")
    print("=" * 120)

    pfg_trades = _backtest_postfill_gate(df, cfg)
    print(f"\n  Post-fill gate trades: {len(pfg_trades)}")
    print_stats(stats(pfg_trades, "PostFillGate (full)"))

    pfg_oos = [t for t in pfg_trades if t.date >= oos_start]
    print_stats(stats(pfg_oos, "PostFillGate (OOS)"))

    # Count how many were scratched
    scratched = [t for t in pfg_trades if t.exit_type == 'BAR_DIR_EXIT']
    held = [t for t in pfg_trades if t.exit_type != 'BAR_DIR_EXIT']
    print(f"\n  Scratched (opposed bar): {len(scratched)} trades")
    print_stats(stats(scratched, "Scratched"))
    print(f"  Held (aligned bar): {len(held)} trades")
    print_stats(stats(held, "Held"))

    scratched_oos = [t for t in scratched if t.date >= oos_start]
    held_oos = [t for t in held if t.date >= oos_start]
    print(f"\n  OOS scratched: {len(scratched_oos)}")
    print_stats(stats(scratched_oos, "Scratched OOS"))
    print(f"  OOS held: {len(held_oos)}")
    print_stats(stats(held_oos, "Held OOS"))

    # Annual breakdown
    print(f"\n  Annual comparison (Post-fill gate vs Baseline):")
    print(f"  {'Year':>6} | {'N_base':>6} | {'N_pfg':>6} | {'N_scr':>6} | {'Sh_base':>7} | {'Sh_pfg':>7} | "
          f"{'Mean_base':>9} | {'Mean_pfg':>9} | {'Tot_base':>10} | {'Tot_pfg':>10} | {'PFG better?':>11}")

    by_year_pfg = {}
    for t in pfg_trades:
        by_year_pfg.setdefault(t.date.year, []).append(t)
    by_year_scr = {}
    for t in scratched:
        by_year_scr.setdefault(t.date.year, []).append(t)

    pfg_wins = 0
    pfg_total = 0

    for yr in years:
        sb = stats(by_year_base.get(yr, []), '')
        sp = stats(by_year_pfg.get(yr, []), '')
        n_scr = len(by_year_scr.get(yr, []))
        better = sp['sharpe'] > sb['sharpe'] if sp['n'] > 0 and sb['n'] > 0 else False
        pfg_total += 1
        if better:
            pfg_wins += 1
        print(f"  {yr:>6} | {sb['n']:>6} | {sp['n']:>6} | {n_scr:>6} | {sb['sharpe']:>7.2f} | {sp['sharpe']:>7.2f} | "
              f"${sb['mean']:>+8.2f} | ${sp['mean']:>+8.2f} | ${sb['total']:>+9.2f} | ${sp['total']:>+9.2f} | "
              f"{'YES' if better else 'no':>11}")

    print(f"\n  PFG better in {pfg_wins}/{pfg_total} years ({pfg_wins/max(pfg_total,1)*100:.0f}%)")

    # =====================================================================
    # HEAD-TO-HEAD comparison
    # =====================================================================
    print(f"\n{'='*120}")
    print("  HEAD-TO-HEAD COMPARISON")
    print("=" * 120)

    sb = stats(baseline_trades, "Baseline")
    sc = stats(cc_trades, "ConfirmClose")
    sp = stats(pfg_trades, "PostFillGate")

    sb_oos = stats(base_oos, "Baseline OOS")
    sc_oos = stats(cc_oos, "ConfirmClose OOS")
    sp_oos = stats(pfg_oos, "PostFillGate OOS")

    print(f"\n  {'Metric':>15} | {'Baseline':>12} | {'ConfirmClose':>12} | {'PostFillGate':>12}")
    print(f"  {'-'*15}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}")
    print(f"  {'N (full)':>15} | {sb['n']:>12} | {sc['n']:>12} | {sp['n']:>12}")
    print(f"  {'N (OOS)':>15} | {sb_oos['n']:>12} | {sc_oos['n']:>12} | {sp_oos['n']:>12}")
    print(f"  {'Sharpe (full)':>15} | {sb['sharpe']:>12.2f} | {sc['sharpe']:>12.2f} | {sp['sharpe']:>12.2f}")
    print(f"  {'Sharpe (OOS)':>15} | {sb_oos['sharpe']:>12.2f} | {sc_oos['sharpe']:>12.2f} | {sp_oos['sharpe']:>12.2f}")
    print(f"  {'PF (full)':>15} | {sb['pf']:>12.2f} | {sc['pf']:>12.2f} | {sp['pf']:>12.2f}")
    print(f"  {'PF (OOS)':>15} | {sb_oos['pf']:>12.2f} | {sc_oos['pf']:>12.2f} | {sp_oos['pf']:>12.2f}")
    print(f"  {'WR (full)':>15} | {sb['wr']:>11.1f}% | {sc['wr']:>11.1f}% | {sp['wr']:>11.1f}%")
    print(f"  {'WR (OOS)':>15} | {sb_oos['wr']:>11.1f}% | {sc_oos['wr']:>11.1f}% | {sp_oos['wr']:>11.1f}%")
    print(f"  {'Mean (full)':>15} | ${sb['mean']:>+11.2f} | ${sc['mean']:>+11.2f} | ${sp['mean']:>+11.2f}")
    print(f"  {'Mean (OOS)':>15} | ${sb_oos['mean']:>+11.2f} | ${sc_oos['mean']:>+11.2f} | ${sp_oos['mean']:>+11.2f}")
    print(f"  {'Total (full)':>15} | ${sb['total']:>+11.2f} | ${sc['total']:>+11.2f} | ${sp['total']:>+11.2f}")
    print(f"  {'Total (OOS)':>15} | ${sb_oos['total']:>+11.2f} | ${sc_oos['total']:>+11.2f} | ${sp_oos['total']:>+11.2f}")
    print(f"  {'MaxDD (full)':>15} | ${sb['max_dd']:>+11.2f} | ${sc['max_dd']:>+11.2f} | ${sp['max_dd']:>+11.2f}")
    print(f"  {'MaxDD (OOS)':>15} | ${sb_oos['max_dd']:>+11.2f} | ${sc_oos['max_dd']:>+11.2f} | ${sp_oos['max_dd']:>+11.2f}")
    print(f"  {'MCL (full)':>15} | {sb['mcl']:>12} | {sc['mcl']:>12} | {sp['mcl']:>12}")
    print(f"  {'MCL (OOS)':>15} | {sb_oos['mcl']:>12} | {sc_oos['mcl']:>12} | {sp_oos['mcl']:>12}")

    # =====================================================================
    # APPROACH B + Velocity: combined filter
    # =====================================================================
    print(f"\n{'='*120}")
    print("  COMBINED: POST-FILL GATE + VELOCITY FILTER (walk-forward)")
    print("=" * 120)

    print(f"\n  {'Test':>6} | {'Train':>12} | {'Vel_thr':>7} | "
          f"{'N_base':>6} | {'N_vel':>6} | {'N_pfg':>6} | {'N_vel+pfg':>9} | "
          f"{'Sh_base':>7} | {'Sh_vel':>7} | {'Sh_pfg':>7} | {'Sh_combo':>8}")

    for test_yr in years:
        train_yrs = [y for y in years if y < test_yr][-3:]
        if len(train_yrs) < 2:
            continue

        train_trades = [t for t in baseline_trades if t.date.year in train_yrs]
        test_base = [t for t in baseline_trades if t.date.year == test_yr]
        test_pfg = [t for t in pfg_trades if t.date.year == test_yr]
        if len(train_trades) < 20 or len(test_base) < 10:
            continue

        vel_thr = np.median([t.entry_tick_count for t in train_trades])

        test_vel = [t for t in test_base if t.entry_tick_count >= vel_thr]
        test_pfg_held = [t for t in test_pfg if t.exit_type != 'BAR_DIR_EXIT']
        test_vel_pfg = [t for t in test_pfg_held if t.entry_tick_count >= vel_thr]

        s_base = stats(test_base, '')
        s_vel = stats(test_vel, '')
        s_pfg = stats(test_pfg, '')
        s_combo = stats(test_vel_pfg, '')

        print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {vel_thr:>7.0f} | "
              f"{s_base['n']:>6} | {s_vel['n']:>6} | {s_pfg['n']:>6} | {s_combo['n']:>9} | "
              f"{s_base['sharpe']:>7.2f} | {s_vel['sharpe']:>7.2f} | {s_pfg['sharpe']:>7.2f} | {s_combo['sharpe']:>8.2f}")

    # =====================================================================
    # Scratch cost analysis for Approach B
    # =====================================================================
    print(f"\n{'='*120}")
    print("  SCRATCH COST ANALYSIS (Approach B)")
    print("  What is the typical P&L of scratched trades?")
    print("=" * 120)

    if scratched:
        scr_pnls = [t.pnl for t in scratched]
        print(f"\n  Scratched trade P&L distribution:")
        print(f"    N = {len(scr_pnls)}")
        print(f"    Mean = ${np.mean(scr_pnls):+.2f}")
        print(f"    Median = ${np.median(scr_pnls):+.2f}")
        print(f"    Std = ${np.std(scr_pnls):.2f}")
        print(f"    Min = ${np.min(scr_pnls):+.2f}")
        print(f"    Max = ${np.max(scr_pnls):+.2f}")
        print(f"    % negative = {sum(1 for p in scr_pnls if p < 0)/len(scr_pnls)*100:.1f}%")

        # What would have happened if we held these trades?
        # Compare: scratched exit P&L vs what the full trade would have given
        # The scratched trades were also run in baseline (same day), find them
        scr_dates = set(t.date for t in scratched)
        base_on_scr_dates = [t for t in baseline_trades if t.date in scr_dates]
        print(f"\n  Baseline outcomes on same days as scratched trades:")
        print(f"    N = {len(base_on_scr_dates)}")
        if base_on_scr_dates:
            base_scr_pnls = [t.pnl for t in base_on_scr_dates]
            print(f"    Mean = ${np.mean(base_scr_pnls):+.2f}")
            print(f"    Total = ${sum(base_scr_pnls):+.2f}")
            print(f"    If held: ${sum(base_scr_pnls):+.2f}, scratched early: ${sum(scr_pnls):+.2f}")
            print(f"    Saved by scratching: ${sum(base_scr_pnls) - sum(scr_pnls):+.2f} "
                  f"({'SAVED' if sum(base_scr_pnls) < sum(scr_pnls) else 'LOST'} money by scratching)")

    print(f"\n{'='*120}")
    print("  DONE")
    print("=" * 120)


def _backtest_postfill_gate(df: pd.DataFrame, cfg: Config) -> list[Trade]:
    """
    Post-fill gate: enter on stop (like normal), but at the end of the
    entry bar, check if bar direction aligns with trade direction.
    If opposed, exit at bar close. If aligned, hold normally.
    """
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

        for i in range(n):
            ts, bar = bars[i]
            hs = bar['avg_spread'] / 2

            direction = None
            entry_px = None

            if bar['high'] >= rh:
                direction = 'LONG'
                if bar['open'] >= rh:
                    entry_px = bar['open'] + hs
                    etype = 'stop_gap'
                else:
                    entry_px = rh + hs
                    etype = 'stop_at_level'
            elif bar['low'] <= rl:
                direction = 'SHORT'
                if bar['open'] <= rl:
                    entry_px = bar['open'] - hs
                    etype = 'stop_gap'
                else:
                    entry_px = rl - hs
                    etype = 'stop_at_level'

            if direction is None:
                continue

            # CHECK: entry bar direction
            bar_bullish = bar['close'] > bar['open']
            if direction == 'LONG':
                is_aligned = bar_bullish
            else:
                is_aligned = not bar_bullish

            if not is_aligned:
                # OPPOSED: exit at entry bar close
                if direction == 'LONG':
                    exit_px = bar['close'] - hs
                else:
                    exit_px = bar['close'] + hs

                raw_pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)

                trades.append(Trade(
                    date=day,
                    direction=direction,
                    entry_price=round(entry_px, 3),
                    exit_price=round(exit_px, 3),
                    entry_time=ts,
                    exit_time=ts,
                    entry_type=etype,
                    exit_type='BAR_DIR_EXIT',
                    range_high=round(rh, 3),
                    range_low=round(rl, 3),
                    range_size=round(rs, 3),
                    pnl=round(raw_pnl, 3),
                    spread_cost=round(hs * 2, 4),
                    hold_minutes=0,
                    entry_tick_count=int(bar.get('tick_count', 0)),
                    entry_avg_spread=round(bar.get('avg_spread', 0), 4),
                    entry_buy_ratio=round(bar.get('buy_ratio', 0.5), 4),
                    entry_vol_imbalance=bar.get('vol_imbalance', 0),
                    gap_from_level=0,
                ))
                break  # done for this day

            # ALIGNED: hold normally via _monitor
            sl = rl if direction == 'LONG' else rh
            tp = tp_long if direction == 'LONG' else tp_short

            trade = _monitor(bars, i + 1, n, cfg, direction, entry_px, sl, tp,
                             ts, rh, rl, rs, day, etype, 0, bar)
            if trade is not None:
                trades.append(trade)
            break  # done for this day

    return trades


if __name__ == "__main__":
    main()
