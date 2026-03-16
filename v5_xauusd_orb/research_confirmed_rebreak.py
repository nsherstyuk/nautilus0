"""
research_confirmed_rebreak.py
==============================
Study: After a divergent breakout (price crosses local high/low but imbalance
opposes direction), price pulls back, then re-crosses the same level with
imbalance NOW matching the direction. Does this "confirmed rebreak" predict
stronger continuation than a normal breakout?

Pattern sequence:
1. First breakout of pivot level - with DIVERGENT imbalance
2. Price pulls back below/above the pivot level
3. Second breakout of SAME level - with MATCHING imbalance
4. Measure forward returns from the second breakout

Comparison groups:
A) "Confirmed rebreak" (divergent first, matching second)
B) "Clean first break" (matching imbalance on first break, no pullback)
C) "All rebreaks" (any second break after pullback, regardless of imbalance)
"""
import sys
import argparse
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")

PIVOT_WINDOWS = [15, 30, 60]
IMB_WINDOW = 3                    # bars after breakout to measure imbalance
FORWARD_HORIZONS = [5, 10, 15, 30, 60]
DIVERGENCE_THRESHOLD = 0.5
MAX_PULLBACK_BARS = 60            # max bars between first break and rebreak
MIN_PULLBACK_BARS = 3             # min bars for pullback to form
SPREAD_COST = 0.30                # $ round-trip spread cost for XAUUSD
EURUSD_SPREAD = 0.00010           # 1 pip round-trip for EURUSD


def load_data(symbol):
    path = DATA_DIR / f"{symbol.lower()}_1m_tick.csv"
    print(f"Loading 1-min {symbol} data from {path}...")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  Loaded {len(df):,} bars  {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    print(f"  After filtering zero-tick: {len(df):,}")
    return df


def detect_pivots(df, window):
    n = len(df)
    highs = df["high"].values
    lows = df["low"].values
    pivot_highs = np.full(n, np.nan)
    pivot_lows = np.full(n, np.nan)
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values
    pivot_highs[highs == roll_max] = highs[highs == roll_max]
    pivot_lows[lows == roll_min] = lows[lows == roll_min]
    return pivot_highs, pivot_lows


def get_buy_ratio(buy_vols, sell_vols, start, end):
    bv = buy_vols[start:end].sum()
    sv = sell_vols[start:end].sum()
    total = bv + sv
    if total == 0:
        return np.nan
    return bv / total


def find_rebreak_events(df, pivot_highs, pivot_lows, pw, spread=0):
    """
    Scan for the full pattern:
    1) First breakout with divergent imbalance
    2) Pullback (price returns through the pivot level)
    3) Second breakout of same level - classify imbalance as matching or not

    Also collect "clean first breaks" (matching imbalance, no prior divergent break).
    """
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values

    events = []

    last_pivot_high = np.nan
    last_pivot_low = np.nan

    # State tracking per level
    # For highs
    h_first_break_idx = -1
    h_first_was_divergent = False
    h_broke = False
    h_pulled_back = False

    # For lows
    l_first_break_idx = -1
    l_first_was_divergent = False
    l_broke = False
    l_pulled_back = False

    for i in range(n):
        # Update pivots - reset state on new pivot
        if not np.isnan(pivot_highs[i]):
            last_pivot_high = pivot_highs[i]
            h_broke = False
            h_pulled_back = False
            h_first_break_idx = -1
            h_first_was_divergent = False

        if not np.isnan(pivot_lows[i]):
            last_pivot_low = pivot_lows[i]
            l_broke = False
            l_pulled_back = False
            l_first_break_idx = -1
            l_first_was_divergent = False

        # --- UP direction (pivot high) ---
        if not np.isnan(last_pivot_high):
            if not h_broke:
                # First break attempt
                if closes[i] > last_pivot_high:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio(buy_vols, sell_vols, i+1, end_imb)
                        if not np.isnan(br):
                            divergent = br < DIVERGENCE_THRESHOLD
                            h_broke = True
                            h_first_break_idx = i
                            h_first_was_divergent = divergent

                            if not divergent:
                                # Clean first break with matching imbalance
                                evt = _build_event(df, closes, buy_vols, sell_vols,
                                    i, "up", last_pivot_high, br, "clean_first", n, spread)
                                if evt:
                                    events.append(evt)

            elif not h_pulled_back:
                # Waiting for pullback (price back below pivot)
                if closes[i] <= last_pivot_high:
                    h_pulled_back = True

            else:
                # Had first break + pullback, looking for rebreak
                gap = i - h_first_break_idx
                if gap > MAX_PULLBACK_BARS:
                    # Too long, give up on this sequence
                    h_broke = False
                    h_pulled_back = False
                    h_first_break_idx = -1
                    continue

                if gap >= MIN_PULLBACK_BARS and closes[i] > last_pivot_high:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio(buy_vols, sell_vols, i+1, end_imb)
                        if not np.isnan(br):
                            matching = br >= DIVERGENCE_THRESHOLD
                            if h_first_was_divergent and matching:
                                label = "confirmed_rebreak"
                            elif h_first_was_divergent and not matching:
                                label = "divergent_rebreak"
                            elif not h_first_was_divergent and matching:
                                label = "matching_rebreak"
                            else:
                                label = "double_divergent"

                            evt = _build_event(df, closes, buy_vols, sell_vols,
                                i, "up", last_pivot_high, br, label, n, spread)
                            if evt:
                                evt["bars_since_first"] = gap
                                events.append(evt)
                            # Done with this level
                            h_pulled_back = False
                            h_broke = False

        # --- DOWN direction (pivot low) ---
        if not np.isnan(last_pivot_low):
            if not l_broke:
                if closes[i] < last_pivot_low:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio(buy_vols, sell_vols, i+1, end_imb)
                        if not np.isnan(br):
                            divergent = br > DIVERGENCE_THRESHOLD
                            l_broke = True
                            l_first_break_idx = i
                            l_first_was_divergent = divergent

                            if not divergent:
                                evt = _build_event(df, closes, buy_vols, sell_vols,
                                    i, "down", last_pivot_low, br, "clean_first", n, spread)
                                if evt:
                                    events.append(evt)

            elif not l_pulled_back:
                if closes[i] >= last_pivot_low:
                    l_pulled_back = True

            else:
                gap = i - l_first_break_idx
                if gap > MAX_PULLBACK_BARS:
                    l_broke = False
                    l_pulled_back = False
                    l_first_break_idx = -1
                    continue

                if gap >= MIN_PULLBACK_BARS and closes[i] < last_pivot_low:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio(buy_vols, sell_vols, i+1, end_imb)
                        if not np.isnan(br):
                            matching = br <= DIVERGENCE_THRESHOLD
                            if l_first_was_divergent and matching:
                                label = "confirmed_rebreak"
                            elif l_first_was_divergent and not matching:
                                label = "divergent_rebreak"
                            elif not l_first_was_divergent and matching:
                                label = "matching_rebreak"
                            else:
                                label = "double_divergent"

                            evt = _build_event(df, closes, buy_vols, sell_vols,
                                i, "down", last_pivot_low, br, label, n, spread)
                            if evt:
                                evt["bars_since_first"] = gap
                                events.append(evt)
                            l_pulled_back = False
                            l_broke = False

    return pd.DataFrame(events)


def _build_event(df, closes, buy_vols, sell_vols, idx, direction, pivot_price, buy_ratio, label, n, spread=0):
    # Entry point: idx + IMB_WINDOW (when we know the buy_ratio)
    entry_idx = idx + IMB_WINDOW
    if entry_idx >= n:
        return None
    entry_price = closes[entry_idx]
    row = {
        "bar_idx": idx,
        "entry_idx": entry_idx,
        "timestamp": df["timestamp"].iloc[idx],
        "direction": direction,
        "pivot_price": pivot_price,
        "close": closes[idx],
        "entry_price": entry_price,
        "buy_ratio": buy_ratio,
        "label": label,
        "bars_since_first": 0,
    }
    # Original returns (from breakout bar, as before)
    for h in FORWARD_HORIZONS:
        fwd_idx = idx + h
        if fwd_idx < n:
            fwd_ret = closes[fwd_idx] - closes[idx]
            if direction == "down":
                fwd_ret = -fwd_ret
            row[f"fwd_{h}m"] = fwd_ret
        else:
            row[f"fwd_{h}m"] = np.nan
    # Realistic returns (from entry bar = breakout + IMB_WINDOW, minus spread)
    for h in FORWARD_HORIZONS:
        fwd_idx = entry_idx + h
        if fwd_idx < n:
            fwd_ret = closes[fwd_idx] - entry_price
            if direction == "down":
                fwd_ret = -fwd_ret
            row[f"real_{h}m"] = fwd_ret - spread
        else:
            row[f"real_{h}m"] = np.nan
    return row


def analyze_group(df_grp, label, fwd_cols):
    if len(df_grp) == 0:
        return {}
    row = {"label": label, "n": len(df_grp)}
    for col in fwd_cols:
        h = col.replace("fwd_", "")
        row[f"mean_{h}"] = df_grp[col].mean()
        row[f"med_{h}"] = df_grp[col].median()
        row[f"rev_{h}"] = (df_grp[col] < 0).mean()
    return row


def print_comparison(groups_data, fwd_cols):
    horizons = [c.replace("fwd_", "") for c in fwd_cols]
    header = f"  {'label':>22} {'n':>6}"
    for h in horizons:
        header += f"  mean_{h:>3} rev_{h:>3}"
    print(header)

    for gd in groups_data:
        if not gd:
            continue
        line = f"  {gd['label']:>22} {gd['n']:>6}"
        for h in horizons:
            m = gd.get(f"mean_{h}", np.nan)
            r = gd.get(f"rev_{h}", np.nan)
            line += f"  {m:>+7.3f} {r:>6.1%}"
        print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="XAUUSD")
    args = parser.parse_args()
    symbol = args.symbol.upper()

    spread = SPREAD_COST if symbol == "XAUUSD" else EURUSD_SPREAD
    print(f"=== Confirmed Rebreak Study (REALISTIC): {symbol} ===")
    print(f"    IMB_WINDOW={IMB_WINDOW}, MAX_PULLBACK={MAX_PULLBACK_BARS}, MIN_PULLBACK={MIN_PULLBACK_BARS}")
    print(f"    SPREAD_COST={spread}, ENTRY_DELAY={IMB_WINDOW} bars")

    df = load_data(symbol)
    fwd_cols = [f"fwd_{h}m" for h in FORWARD_HORIZONS]
    real_cols = [f"real_{h}m" for h in FORWARD_HORIZONS]

    for pw in PIVOT_WINDOWS:
        print(f"\n{'='*80}")
        print(f"Pivot window = {pw}")
        pivot_highs, pivot_lows = detect_pivots(df, pw)
        print(f"  Pivots: {np.sum(~np.isnan(pivot_highs)):,} highs, {np.sum(~np.isnan(pivot_lows)):,} lows")

        events = find_rebreak_events(df, pivot_highs, pivot_lows, pw, spread)
        if len(events) == 0:
            print("  No events found")
            continue

        print(f"  Total events: {len(events):,}")
        for lbl in events["label"].unique():
            cnt = len(events[events["label"] == lbl])
            print(f"    {lbl}: {cnt:,}")

        for direction in ["up", "down"]:
            subset = events[events["direction"] == direction]
            if len(subset) < 10:
                continue

            print(f"\n  --- {direction.upper()} breakouts (pw={pw}) ---")

            confirmed = subset[subset["label"] == "confirmed_rebreak"]
            clean = subset[subset["label"] == "clean_first"]
            div_rebreak = subset[subset["label"] == "divergent_rebreak"]
            match_rebreak = subset[subset["label"] == "matching_rebreak"]
            dbl_div = subset[subset["label"] == "double_divergent"]

            # --- ORIGINAL (from breakout bar) ---
            print("\n  ** ORIGINAL returns (from breakout bar) - FULL SAMPLE **")
            groups = [
                analyze_group(confirmed, "confirmed_rebreak", fwd_cols),
                analyze_group(clean, "clean_first", fwd_cols),
                analyze_group(div_rebreak, "divergent_rebreak", fwd_cols),
                analyze_group(match_rebreak, "matching_rebreak", fwd_cols),
                analyze_group(dbl_div, "double_divergent", fwd_cols),
            ]
            print_comparison(groups, fwd_cols)

            # --- REALISTIC (from entry bar = breakout + IMB_WINDOW, minus spread) ---
            print(f"\n  ** REALISTIC returns (entry={IMB_WINDOW}bar delay, spread={spread}) - FULL SAMPLE **")
            real_groups = [
                analyze_group(confirmed, "confirmed_rebreak", real_cols),
                analyze_group(clean, "clean_first", real_cols),
                analyze_group(div_rebreak, "divergent_rebreak", real_cols),
                analyze_group(match_rebreak, "matching_rebreak", real_cols),
                analyze_group(dbl_div, "double_divergent", real_cols),
            ]
            print_comparison(real_groups, real_cols)

            # Edge: confirmed_rebreak vs clean_first (realistic)
            if len(confirmed) > 0 and len(clean) > 0:
                print("\n  Realistic Edge (confirmed_rebreak - clean_first):")
                line = "    "
                for col in real_cols:
                    h = col.replace("real_", "")
                    edge = confirmed[col].mean() - clean[col].mean()
                    line += f"  {h}={edge:+.3f}"
                print(line)

            # Avg bars_since_first for rebreaks
            rebreaks = subset[subset["label"].str.contains("rebreak")]
            if len(rebreaks) > 0:
                print(f"\n  Avg bars between first break and rebreak: {rebreaks['bars_since_first'].mean():.1f}")

            # OOS - realistic only
            oos = subset[subset["timestamp"].dt.year >= 2023]
            if len(oos) > 20:
                print(f"\n  ** OOS REALISTIC (2023-2026, n={len(oos):,}) **")
                oos_labels = ["confirmed_rebreak", "clean_first", "divergent_rebreak",
                              "matching_rebreak", "double_divergent"]
                oos_groups = [analyze_group(oos[oos["label"] == lbl], lbl, real_cols)
                              for lbl in oos_labels]
                print_comparison(oos_groups, real_cols)

                oos_conf = oos[oos["label"] == "confirmed_rebreak"]
                oos_clean = oos[oos["label"] == "clean_first"]
                if len(oos_conf) > 0 and len(oos_clean) > 0:
                    print("\n  OOS Realistic Edge (confirmed_rebreak - clean_first):")
                    line = "    "
                    for col in real_cols:
                        h = col.replace("real_", "")
                        edge = oos_conf[col].mean() - oos_clean[col].mean()
                        line += f"  {h}={edge:+.3f}"
                    print(line)

                # Absolute P&L for confirmed rebreaks (is it positive after costs?)
                if len(oos_conf) > 5:
                    print("\n  OOS Confirmed Rebreak absolute P&L (after spread):")
                    line = "    "
                    for col in real_cols:
                        h = col.replace("real_", "")
                        m = oos_conf[col].mean()
                        pct_pos = (oos_conf[col] > 0).mean()
                        line += f"  {h}: mean={m:+.3f} win%={pct_pos:.1%}"
                    print(line)

    print("\nDone.")


if __name__ == "__main__":
    main()
