"""
research_imbalance_divergence.py
================================
Study: When price crosses a local high/low, does tick volume buy/sell imbalance
diverging from the breakout direction predict a reversal?

Local highs/lows detected as rolling-window pivot points.
Imbalance = buy_volume / (buy_volume + sell_volume) around the breakout bar.

Hypothesis: If price breaks above a local high but sell volume dominates
(buy_ratio < 0.5), a short-term reversal is more likely (and vice versa).

Uses 1-min XAUUSD bars with tick microstructure from Dukascopy data.
"""
import sys
import argparse
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")

# ---- Parameters to sweep ----
PIVOT_WINDOWS = [15, 30, 60]          # bars each side to define local high/low
IMBALANCE_WINDOWS = [1, 3, 5]         # bars after breakout to measure imbalance
FORWARD_HORIZONS = [5, 10, 15, 30, 60]  # bars forward to measure return
DIVERGENCE_THRESHOLD = 0.5            # buy_ratio threshold for divergence


def load_data(symbol):
    path = DATA_DIR / f"{symbol.lower()}_1m_tick.csv"
    print(f"Loading 1-min {symbol} data from {path}...")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    # Drop unnamed index column if present
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    # Strip timezone if present so all data is naive UTC
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  Loaded {len(df):,} bars from {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    # Drop bars with zero volume (weekends/gaps)
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    print(f"  After filtering zero-tick bars: {len(df):,}")
    return df


def detect_pivots(df, window):
    """
    Detect local highs and lows using rolling window.
    A local high at bar i means high[i] is the max of high[i-window : i+window+1].
    A local low at bar i means low[i] is the min of low[i-window : i+window+1].
    Returns arrays of pivot high prices and pivot low prices (NaN where not a pivot).
    """
    n = len(df)
    highs = df["high"].values
    lows = df["low"].values

    pivot_highs = np.full(n, np.nan)
    pivot_lows = np.full(n, np.nan)

    # Use rolling max/min for efficiency
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    # A bar is a pivot high if its high equals the rolling max
    mask_high = (highs == roll_max)
    pivot_highs[mask_high] = highs[mask_high]

    # A bar is a pivot low if its low equals the rolling min
    mask_low = (lows == roll_min)
    pivot_lows[mask_low] = lows[mask_low]

    return pivot_highs, pivot_lows


def find_breakouts(df, pivot_highs, pivot_lows):
    """
    For each bar, check if close crosses above the most recent pivot high
    or below the most recent pivot low.

    Returns a DataFrame of breakout events with columns:
      bar_idx, direction ('up'/'down'), pivot_price, breakout_price
    """
    n = len(df)
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    events = []
    last_pivot_high = np.nan
    last_pivot_low = np.nan
    broke_high = False
    broke_low = False

    for i in range(n):
        # Update latest pivot levels (only use pivots that are fully formed,
        # i.e., at least window bars old -- but we already used centered rolling)
        if not np.isnan(pivot_highs[i]):
            last_pivot_high = pivot_highs[i]
            broke_high = False  # reset on new pivot
        if not np.isnan(pivot_lows[i]):
            last_pivot_low = pivot_lows[i]
            broke_low = False  # reset on new pivot

        # Check breakout above last pivot high
        if not np.isnan(last_pivot_high) and not broke_high:
            if closes[i] > last_pivot_high:
                events.append({
                    "bar_idx": i,
                    "direction": "up",
                    "pivot_price": last_pivot_high,
                    "breakout_price": closes[i],
                })
                broke_high = True

        # Check breakout below last pivot low
        if not np.isnan(last_pivot_low) and not broke_low:
            if closes[i] < last_pivot_low:
                events.append({
                    "bar_idx": i,
                    "direction": "down",
                    "pivot_price": last_pivot_low,
                    "breakout_price": closes[i],
                })
                broke_low = True

    return pd.DataFrame(events)


def compute_imbalance_and_returns(df, breakouts, imb_window, fwd_horizons):
    """
    For each breakout event:
    - Compute buy_ratio in imb_window bars AFTER the breakout bar
    - Compute forward returns at each horizon
    - Flag divergence
    """
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values

    results = []
    for _, evt in breakouts.iterrows():
        idx = int(evt["bar_idx"])
        direction = evt["direction"]

        # Imbalance in window after breakout
        end = min(idx + imb_window + 1, n)
        if end <= idx + 1:
            continue
        window_buy = buy_vols[idx+1:end].sum()
        window_sell = sell_vols[idx+1:end].sum()
        total = window_buy + window_sell
        if total == 0:
            continue
        buy_ratio = window_buy / total

        # Divergence: broke up but sellers dominate, or broke down but buyers dominate
        if direction == "up":
            divergent = buy_ratio < DIVERGENCE_THRESHOLD
        else:
            divergent = buy_ratio > DIVERGENCE_THRESHOLD

        row = {
            "bar_idx": idx,
            "timestamp": df["timestamp"].iloc[idx],
            "direction": direction,
            "pivot_price": evt["pivot_price"],
            "breakout_price": evt["breakout_price"],
            "buy_ratio": buy_ratio,
            "imbalance_net": window_buy - window_sell,
            "divergent": divergent,
        }

        # Forward returns (in dollar terms for gold)
        for h in fwd_horizons:
            fwd_idx = idx + h
            if fwd_idx < n:
                fwd_ret = closes[fwd_idx] - closes[idx]
                # For "up" breakout, positive = continued up, negative = reversal
                # For "down" breakout, flip sign so positive = continued, negative = reversal
                if direction == "down":
                    fwd_ret = -fwd_ret
                row[f"fwd_{h}m"] = fwd_ret
            else:
                row[f"fwd_{h}m"] = np.nan

        results.append(row)

    return pd.DataFrame(results)


def analyze_results(results_df, pivot_window, imb_window):
    """Print analysis comparing divergent vs non-divergent breakouts."""
    if len(results_df) == 0:
        print("  No breakout events found.")
        return None

    fwd_cols = [c for c in results_df.columns if c.startswith("fwd_")]
    summary_rows = []

    for direction in ["up", "down"]:
        subset = results_df[results_df["direction"] == direction]
        if len(subset) == 0:
            continue

        div = subset[subset["divergent"] == True]
        nodiv = subset[subset["divergent"] == False]

        print(f"\n  --- {direction.upper()} breakouts (pivot_win={pivot_window}, imb_win={imb_window}) ---")
        print(f"  Total: {len(subset):,}  |  Divergent: {len(div):,} ({100*len(div)/len(subset):.1f}%)  |  Non-div: {len(nodiv):,}")

        for col in fwd_cols:
            horizon = col.replace("fwd_", "")
            div_mean = div[col].mean() if len(div) > 0 else np.nan
            nodiv_mean = nodiv[col].mean() if len(nodiv) > 0 else np.nan
            div_median = div[col].median() if len(div) > 0 else np.nan
            nodiv_median = nodiv[col].median() if len(nodiv) > 0 else np.nan

            # Reversal rate: how often does forward return go negative (against breakout)?
            div_rev_rate = (div[col] < 0).mean() if len(div) > 0 else np.nan
            nodiv_rev_rate = (nodiv[col] < 0).mean() if len(nodiv) > 0 else np.nan

            print(f"    {horizon:>5}:  Divergent mean=${div_mean:+.3f} med=${div_median:+.3f} rev_rate={div_rev_rate:.1%}"
                  f"  |  Non-div mean=${nodiv_mean:+.3f} med=${nodiv_median:+.3f} rev_rate={nodiv_rev_rate:.1%}"
                  f"  |  edge=${div_mean - nodiv_mean:+.3f}")

            summary_rows.append({
                "direction": direction,
                "pivot_window": pivot_window,
                "imb_window": imb_window,
                "horizon": horizon,
                "div_count": len(div),
                "nodiv_count": len(nodiv),
                "div_mean_fwd": div_mean,
                "nodiv_mean_fwd": nodiv_mean,
                "div_rev_rate": div_rev_rate,
                "nodiv_rev_rate": nodiv_rev_rate,
                "edge": div_mean - nodiv_mean,
            })

    return pd.DataFrame(summary_rows)


def analyze_imbalance_strength(results_df, pivot_window, imb_window):
    """
    Break divergent events into imbalance strength quintiles.
    Does STRONGER divergence predict bigger reversals?
    """
    fwd_cols = [c for c in results_df.columns if c.startswith("fwd_")]
    if len(fwd_cols) == 0:
        return

    print(f"\n  === Imbalance strength analysis (pivot={pivot_window}, imb={imb_window}) ===")
    for direction in ["up", "down"]:
        div = results_df[(results_df["direction"] == direction) & (results_df["divergent"] == True)]
        if len(div) < 20:
            continue

        # For up-breakouts: lower buy_ratio = stronger sell divergence
        # For down-breakouts: higher buy_ratio = stronger buy divergence
        if direction == "up":
            div = div.copy()
            div["div_strength"] = 1.0 - div["buy_ratio"]  # higher = more sell-heavy
        else:
            div = div.copy()
            div["div_strength"] = div["buy_ratio"]  # higher = more buy-heavy

        div["strength_q"] = pd.qcut(div["div_strength"], 3, labels=["weak", "medium", "strong"], duplicates="drop")

        print(f"\n  {direction.upper()} breakouts - divergence strength quintiles:")
        for q in ["weak", "medium", "strong"]:
            qdf = div[div["strength_q"] == q]
            if len(qdf) == 0:
                continue
            line = f"    {q:>8} (n={len(qdf):>5}): "
            for col in fwd_cols[:4]:  # just first 4 horizons
                h = col.replace("fwd_", "")
                line += f" {h}=${qdf[col].mean():+.3f}"
            print(line)


def oos_split(results_df):
    """Split into IS (2018-2022) and OOS (2023-2026)."""
    results_df = results_df.copy()
    results_df["year"] = results_df["timestamp"].dt.year
    is_df = results_df[results_df["year"] <= 2022]
    oos_df = results_df[results_df["year"] >= 2023]
    return is_df, oos_df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="XAUUSD", help="Symbol to analyze (default: XAUUSD)")
    args = parser.parse_args()
    symbol = args.symbol.upper()
    print(f"=== Imbalance Divergence Study: {symbol} ===")

    df = load_data(symbol)

    all_summaries = []

    for pw in PIVOT_WINDOWS:
        print(f"\n{'='*80}")
        print(f"Detecting pivots with window={pw} bars each side...")
        pivot_highs, pivot_lows = detect_pivots(df, pw)
        n_ph = np.sum(~np.isnan(pivot_highs))
        n_pl = np.sum(~np.isnan(pivot_lows))
        print(f"  Found {n_ph:,} pivot highs, {n_pl:,} pivot lows")

        print("Finding breakout events...")
        breakouts = find_breakouts(df, pivot_highs, pivot_lows)
        n_up = len(breakouts[breakouts["direction"] == "up"])
        n_down = len(breakouts[breakouts["direction"] == "down"])
        print(f"  Found {len(breakouts):,} breakouts ({n_up:,} up, {n_down:,} down)")

        for iw in IMBALANCE_WINDOWS:
            print(f"\n  Computing imbalance (window={iw} bars after breakout)...")
            results = compute_imbalance_and_returns(df, breakouts, iw, FORWARD_HORIZONS)

            if len(results) == 0:
                continue

            # Full sample
            print("\n  *** FULL SAMPLE ***")
            summary = analyze_results(results, pw, iw)
            if summary is not None:
                all_summaries.append(summary)

            analyze_imbalance_strength(results, pw, iw)

            # OOS split
            is_results, oos_results = oos_split(results)
            if len(oos_results) > 50:
                print(f"\n  *** OOS (2023-2026, n={len(oos_results):,}) ***")
                oos_summary = analyze_results(oos_results, pw, iw)

    # Final summary table
    if all_summaries:
        big = pd.concat(all_summaries, ignore_index=True)
        print(f"\n\n{'='*80}")
        print("SUMMARY: Best divergence edges across all configs")
        print("="*80)
        # Filter to 15min and 30min horizons for readability
        for horizon in ["15m", "30m", "60m"]:
            hdf = big[big["horizon"] == horizon].copy()
            if len(hdf) == 0:
                continue
            hdf = hdf.sort_values("edge", ascending=True)  # most negative edge = strongest reversal signal
            print(f"\n  Horizon: {horizon}")
            print(f"  {'dir':>5} {'pw':>4} {'iw':>4} {'div_n':>6} {'nodiv_n':>7} {'div_mean':>10} {'nodiv_mean':>11} {'div_rev%':>9} {'nodiv_rev%':>10} {'edge':>8}")
            for _, r in hdf.iterrows():
                print(f"  {r['direction']:>5} {r['pivot_window']:>4} {r['imb_window']:>4}"
                      f" {r['div_count']:>6} {r['nodiv_count']:>7}"
                      f" {r['div_mean_fwd']:>+10.3f} {r['nodiv_mean_fwd']:>+11.3f}"
                      f" {r['div_rev_rate']:>8.1%} {r['nodiv_rev_rate']:>9.1%}"
                      f" {r['edge']:>+8.3f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
