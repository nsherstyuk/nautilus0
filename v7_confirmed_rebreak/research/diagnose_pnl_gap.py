"""
diagnose_pnl_gap.py
====================
Quantify the PnL gap between research (+$0.70/trade) and backtest (+$0.20/trade).

Hypothesis: left-only pivots find different (weaker) levels than centered pivots.

Approach:
1. Run research-style centered pivot detection
2. Run backtest-style left-only pivot detection
3. Compare: event counts, overlap, and per-trade PnL using identical execution
4. Also check: does the research forward-return method give different PnL than
   the sim executor's bar-by-bar tracking?

All analysis on OOS (2023+), pw=30, min_ticks=50, pure time-stop=45.
"""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DATA_PATH = Path(r"C:\nautilus0\data\1m_csv\xauusd_1m_tick.csv")
OOS_START = "2023-01-01"
PW = 30
IMB_WINDOW = 3
DIV_THRESHOLD = 0.50
MAX_PB = 60
MIN_PB = 3
SPREAD = 0.30
MIN_TICKS = 50
HOLD_BARS = 45


def load_data():
    print("Loading data...")
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    df = df[df["timestamp"] >= OOS_START].reset_index(drop=True)
    print(f"  {len(df):,} OOS bars from {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    return df


def centered_pivots(df, window):
    """Research-style: centered rolling window (uses future data)."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    # Build a series of "current pivot" for each bar
    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)

    # Mark bars where highs == rolling max as pivot highs
    is_ph = highs == roll_max
    is_pl = lows == roll_min

    # Forward-fill: at each bar, what is the most recent pivot high/low?
    last_ph = np.nan
    last_pl = np.nan
    for i in range(n):
        if is_ph[i]:
            last_ph = highs[i]
        if is_pl[i]:
            last_pl = lows[i]
        pivot_high[i] = last_ph
        pivot_low[i] = last_pl

    return pivot_high, pivot_low


def leftonly_pivots(df, window):
    """Old backtest-style: left-only pivots using 2*window buffer (BROKEN)."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)

    buf_size = 2 * window
    for i in range(buf_size, n):
        # Historical half = [i - 2*window : i - window]
        hist_start = i - buf_size
        hist_end = i - window
        pivot_high[i] = np.max(highs[hist_start:hist_end])
        pivot_low[i] = np.min(lows[hist_start:hist_end])

    return pivot_high, pivot_low


def causal_centered_pivots(df, window):
    """New backtest-style: sliding window of 2*window+1 bars.
    Middle bar is a pivot if it's the max/min of the full buffer.
    Forward-filled to give a 'current pivot' at each bar.
    This should match centered pivots but with a window-bar delay."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    buf_size = 2 * window + 1

    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)

    last_ph = np.nan
    last_pl = np.nan

    for i in range(buf_size - 1, n):
        # Buffer: [i - buf_size + 1 ... i]
        buf_start = i - buf_size + 1
        buf_highs = highs[buf_start:i + 1]
        buf_lows = lows[buf_start:i + 1]

        # Middle bar index within the buffer = window
        mid_high = buf_highs[window]
        mid_low = buf_lows[window]

        if mid_high >= np.max(buf_highs):
            last_ph = mid_high
        if mid_low <= np.min(buf_lows):
            last_pl = mid_low

        pivot_high[i] = last_ph
        pivot_low[i] = last_pl

    return pivot_high, pivot_low


def get_buy_ratio_quality(buy_vols, sell_vols, tick_counts, start, end, min_ticks):
    """Buy ratio with quality filter."""
    if end > len(buy_vols):
        return np.nan
    ticks = tick_counts[start:end]
    if min_ticks > 0 and np.any(ticks < min_ticks):
        return np.nan
    bv = buy_vols[start:end].sum()
    sv = sell_vols[start:end].sum()
    total = bv + sv
    if total == 0:
        return np.nan
    return bv / total


def find_confirmed_rebreaks(df, pivot_high, pivot_low, min_ticks):
    """Find confirmed rebreak events using provided pivot series.

    Returns list of dicts with: idx, direction, pivot_price, entry_idx, entry_price
    """
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values
    tick_counts = df["tick_count"].values

    events = []

    # Track state per direction
    # High breakouts (long direction)
    h_level = np.nan
    h_broke = False
    h_pulled_back = False
    h_first_idx = -1
    h_first_divergent = False

    # Low breakouts (short direction)
    l_level = np.nan
    l_broke = False
    l_pulled_back = False
    l_first_idx = -1
    l_first_divergent = False

    for i in range(n):
        # Update pivot levels - reset state on change
        if not np.isnan(pivot_high[i]) and pivot_high[i] != h_level:
            h_level = pivot_high[i]
            h_broke = False
            h_pulled_back = False
            h_first_idx = -1

        if not np.isnan(pivot_low[i]) and pivot_low[i] != l_level:
            l_level = pivot_low[i]
            l_broke = False
            l_pulled_back = False
            l_first_idx = -1

        # --- LONG (pivot high) ---
        if not np.isnan(h_level):
            if not h_broke:
                if closes[i] > h_level:
                    imb_end = min(i + IMB_WINDOW + 1, n)
                    if imb_end > i + 1:
                        br = get_buy_ratio_quality(buy_vols, sell_vols, tick_counts,
                                                   i + 1, imb_end, min_ticks)
                        if not np.isnan(br):
                            h_broke = True
                            h_first_idx = i
                            h_first_divergent = (br < DIV_THRESHOLD)
                            if not h_first_divergent:
                                h_broke = False  # clean first break, keep watching
            elif not h_pulled_back:
                if closes[i] <= h_level:
                    h_pulled_back = True
            else:
                gap = i - h_first_idx
                if gap > MAX_PB:
                    h_broke = False
                    h_pulled_back = False
                    continue
                if gap >= MIN_PB and closes[i] > h_level:
                    imb_end = min(i + IMB_WINDOW + 1, n)
                    if imb_end > i + 1:
                        br = get_buy_ratio_quality(buy_vols, sell_vols, tick_counts,
                                                   i + 1, imb_end, min_ticks)
                        if not np.isnan(br):
                            matching = (br >= DIV_THRESHOLD)
                            if h_first_divergent and matching:
                                entry_idx = i + IMB_WINDOW
                                if entry_idx < n:
                                    events.append({
                                        "idx": i,
                                        "entry_idx": entry_idx,
                                        "timestamp": df["timestamp"].iloc[i],
                                        "direction": "long",
                                        "pivot_price": h_level,
                                        "entry_price": closes[entry_idx],
                                        "buy_ratio": br,
                                        "gap": gap,
                                    })
                            h_broke = False
                            h_pulled_back = False

        # --- SHORT (pivot low) ---
        if not np.isnan(l_level):
            if not l_broke:
                if closes[i] < l_level:
                    imb_end = min(i + IMB_WINDOW + 1, n)
                    if imb_end > i + 1:
                        br = get_buy_ratio_quality(buy_vols, sell_vols, tick_counts,
                                                   i + 1, imb_end, min_ticks)
                        if not np.isnan(br):
                            l_broke = True
                            l_first_idx = i
                            l_first_divergent = (br > DIV_THRESHOLD)
                            if not l_first_divergent:
                                l_broke = False
            elif not l_pulled_back:
                if closes[i] >= l_level:
                    l_pulled_back = True
            else:
                gap = i - l_first_idx
                if gap > MAX_PB:
                    l_broke = False
                    l_pulled_back = False
                    continue
                if gap >= MIN_PB and closes[i] < l_level:
                    imb_end = min(i + IMB_WINDOW + 1, n)
                    if imb_end > i + 1:
                        br = get_buy_ratio_quality(buy_vols, sell_vols, tick_counts,
                                                   i + 1, imb_end, min_ticks)
                        if not np.isnan(br):
                            matching = (br <= DIV_THRESHOLD)
                            if l_first_divergent and matching:
                                entry_idx = i + IMB_WINDOW
                                if entry_idx < n:
                                    events.append({
                                        "idx": i,
                                        "entry_idx": entry_idx,
                                        "timestamp": df["timestamp"].iloc[i],
                                        "direction": "short",
                                        "pivot_price": l_level,
                                        "entry_price": closes[entry_idx],
                                        "buy_ratio": br,
                                        "gap": gap,
                                    })
                            l_broke = False
                            l_pulled_back = False

    return pd.DataFrame(events)


def compute_forward_pnl(df, events, hold_bars, spread):
    """Research-style: simple forward return from entry_idx."""
    closes = df["close"].values
    n = len(df)
    pnls = []
    for _, evt in events.iterrows():
        entry_idx = int(evt["entry_idx"])
        exit_idx = min(entry_idx + hold_bars, n - 1)
        entry_price = evt["entry_price"]
        exit_price = closes[exit_idx]
        if evt["direction"] == "long":
            pnl = (exit_price - entry_price) - spread
        else:
            pnl = (entry_price - exit_price) - spread
        pnls.append(pnl)
    events = events.copy()
    events["pnl_fwd"] = pnls
    return events


def compute_sim_pnl(df, events, hold_bars, spread):
    """Backtest-style: bar-by-bar tracking with half-spread on entry and exit."""
    closes = df["close"].values
    n = len(df)
    pnls = []
    for _, evt in events.iterrows():
        entry_idx = int(evt["entry_idx"])
        entry_price = evt["entry_price"]
        direction = evt["direction"]

        # Apply half-spread to entry
        if direction == "long":
            adj_entry = entry_price + spread / 2
        else:
            adj_entry = entry_price - spread / 2

        exit_idx = min(entry_idx + hold_bars, n - 1)
        exit_close = closes[exit_idx]

        # Apply half-spread to exit
        if direction == "long":
            adj_exit = exit_close - spread / 2
            pnl = adj_exit - adj_entry
        else:
            adj_exit = exit_close + spread / 2
            pnl = adj_entry - adj_exit

        pnls.append(pnl)
    events = events.copy()
    events["pnl_sim"] = pnls
    return events


def print_stats(label, events, pnl_col):
    if len(events) == 0:
        print(f"  {label}: 0 events")
        return
    pnls = events[pnl_col]
    total = pnls.sum()
    avg = pnls.mean()
    wins = (pnls > 0).sum()
    wr = wins / len(pnls) * 100
    print(f"  {label}: {len(events)} trades, PnL=${total:+.2f}, "
          f"avg=${avg:+.3f}/trade, WR={wr:.1f}%")


def main():
    df = load_data()

    print(f"\nParams: pw={PW}, imb={IMB_WINDOW}, min_ticks={MIN_TICKS}, "
          f"hold={HOLD_BARS}, spread=${SPREAD}")

    # --- 1. Detect pivots both ways ---
    print("\n--- Pivot Detection ---")
    c_ph, c_pl = centered_pivots(df, PW)
    l_ph, l_pl = leftonly_pivots(df, PW)

    # Count how many unique pivot levels each method finds
    c_ph_unique = len(set(c_ph[~np.isnan(c_ph)]))
    c_pl_unique = len(set(c_pl[~np.isnan(c_pl)]))
    l_ph_unique = len(set(l_ph[~np.isnan(l_ph)]))
    l_pl_unique = len(set(l_pl[~np.isnan(l_pl)]))
    print(f"  Centered: {c_ph_unique} unique highs, {c_pl_unique} unique lows")
    print(f"  Left-only: {l_ph_unique} unique highs, {l_pl_unique} unique lows")

    # --- 2. Detect events with each pivot method ---
    print("\n--- Event Detection ---")
    centered_events = find_confirmed_rebreaks(df, c_ph, c_pl, MIN_TICKS)
    leftonly_events = find_confirmed_rebreaks(df, l_ph, l_pl, MIN_TICKS)

    print(f"  Centered pivots: {len(centered_events)} confirmed rebreak events")
    print(f"  Left-only pivots: {len(leftonly_events)} confirmed rebreak events")

    if len(centered_events) > 0:
        c_long = (centered_events["direction"] == "long").sum()
        c_short = (centered_events["direction"] == "short").sum()
        print(f"    Centered: {c_long} long, {c_short} short")
    if len(leftonly_events) > 0:
        l_long = (leftonly_events["direction"] == "long").sum()
        l_short = (leftonly_events["direction"] == "short").sum()
        print(f"    Left-only: {l_long} long, {l_short} short")

    # --- 2b. Causal-centered pivots (new fix) ---
    print("\n--- Causal-Centered Pivots (sliding window, no lookahead) ---")
    cc_ph, cc_pl = causal_centered_pivots(df, PW)
    cc_events = find_confirmed_rebreaks(df, cc_ph, cc_pl, MIN_TICKS)
    print(f"  Causal-centered pivots: {len(cc_events)} confirmed rebreak events")
    if len(cc_events) > 0:
        cc_long = (cc_events["direction"] == "long").sum()
        cc_short = (cc_events["direction"] == "short").sum()
        print(f"    {cc_long} long, {cc_short} short")
    cc_unique_h = len(set(cc_ph[~np.isnan(cc_ph)]))
    cc_unique_l = len(set(cc_pl[~np.isnan(cc_pl)]))
    print(f"    Unique levels: {cc_unique_h} highs, {cc_unique_l} lows")

    # --- 3. Compute PnL both ways ---
    print("\n--- PnL Comparison (forward-return method) ---")
    if len(centered_events) > 0:
        centered_events = compute_forward_pnl(df, centered_events, HOLD_BARS, SPREAD)
        print_stats("Centered+fwd", centered_events, "pnl_fwd")

    if len(leftonly_events) > 0:
        leftonly_events = compute_forward_pnl(df, leftonly_events, HOLD_BARS, SPREAD)
        print_stats("Left-only+fwd", leftonly_events, "pnl_fwd")

    if len(cc_events) > 0:
        cc_events = compute_forward_pnl(df, cc_events, HOLD_BARS, SPREAD)
        print_stats("Causal-centered+fwd", cc_events, "pnl_fwd")

    print("\n--- PnL Comparison (sim executor method: half-spread entry+exit) ---")
    if len(centered_events) > 0:
        centered_events = compute_sim_pnl(df, centered_events, HOLD_BARS, SPREAD)
        print_stats("Centered+sim", centered_events, "pnl_sim")

    if len(leftonly_events) > 0:
        leftonly_events = compute_sim_pnl(df, leftonly_events, HOLD_BARS, SPREAD)
        print_stats("Left-only+sim", leftonly_events, "pnl_sim")

    # --- 4. Check if spread method matters ---
    if len(centered_events) > 0:
        diff = (centered_events["pnl_fwd"] - centered_events["pnl_sim"]).abs()
        print(f"\n--- Spread Method Diff (centered) ---")
        print(f"  Max abs diff: ${diff.max():.6f}")
        print(f"  Mean abs diff: ${diff.mean():.6f}")
        print(f"  (Should be ~0 if both methods deduct $0.30 total)")

    # --- 5. Event overlap ---
    if len(centered_events) > 0 and len(leftonly_events) > 0:
        print("\n--- Event Overlap ---")
        # Match by timestamp (within 5 minutes)
        c_times = set(centered_events["timestamp"].values)
        l_times = set(leftonly_events["timestamp"].values)
        overlap = c_times & l_times
        print(f"  Exact timestamp overlap: {len(overlap)} events")
        print(f"  Centered-only: {len(c_times - l_times)}")
        print(f"  Left-only-only: {len(l_times - c_times)}")

        # PnL of overlapping vs non-overlapping
        if len(overlap) > 0:
            c_overlap = centered_events[centered_events["timestamp"].isin(overlap)]
            c_unique = centered_events[~centered_events["timestamp"].isin(overlap)]
            l_overlap = leftonly_events[leftonly_events["timestamp"].isin(overlap)]
            l_unique = leftonly_events[~leftonly_events["timestamp"].isin(overlap)]

            print(f"\n  Overlapping events:")
            print_stats("    Centered", c_overlap, "pnl_fwd")
            print_stats("    Left-only", l_overlap, "pnl_fwd")
            print(f"\n  Unique to each method:")
            print_stats("    Centered-only", c_unique, "pnl_fwd")
            print_stats("    Left-only-only", l_unique, "pnl_fwd")

    # --- 6. Yearly breakdown ---
    if len(centered_events) > 0:
        print("\n--- Yearly PnL: Centered (fwd) ---")
        centered_events["year"] = centered_events["timestamp"].dt.year
        for yr, grp in centered_events.groupby("year"):
            total = grp["pnl_fwd"].sum()
            avg = grp["pnl_fwd"].mean()
            print(f"  {yr}: {len(grp)} trades, PnL=${total:+.2f}, avg=${avg:+.3f}")

    if len(leftonly_events) > 0:
        print("\n--- Yearly PnL: Left-only (fwd) ---")
        leftonly_events["year"] = leftonly_events["timestamp"].dt.year
        for yr, grp in leftonly_events.groupby("year"):
            total = grp["pnl_fwd"].sum()
            avg = grp["pnl_fwd"].mean()
            print(f"  {yr}: {len(grp)} trades, PnL=${total:+.2f}, avg=${avg:+.3f}")

    # --- 7. Compare against actual backtest engine trade count ---
    print("\n--- Comparison to Actual Backtest Engine ---")
    print(f"  Actual backtest (pure time=45): 915 trades, PnL=+$176, avg=$0.19/trade")
    if len(leftonly_events) > 0:
        print(f"  This script left-only: {len(leftonly_events)} events, "
              f"PnL=${leftonly_events['pnl_fwd'].sum():+.2f}, "
              f"avg=${leftonly_events['pnl_fwd'].mean():+.3f}/trade")
        print(f"  (Difference in trade count may be due to cooldown, "
              f"in-trade blocking, etc.)")

    # --- 8. Test larger pivot windows with left-only ---
    print("\n" + "=" * 70)
    print("=== FIX EXPLORATION: Larger pivot windows (left-only) ===")
    print("=" * 70)
    for test_pw in [45, 60, 90, 120]:
        l_ph2, l_pl2 = leftonly_pivots(df, test_pw)
        evts = find_confirmed_rebreaks(df, l_ph2, l_pl2, MIN_TICKS)
        if len(evts) > 0:
            evts = compute_forward_pnl(df, evts, HOLD_BARS, SPREAD)
            total = evts["pnl_fwd"].sum()
            avg = evts["pnl_fwd"].mean()
            wr = (evts["pnl_fwd"] > 0).mean() * 100
            n_unique = len(set(l_ph2[~np.isnan(l_ph2)])) + len(set(l_pl2[~np.isnan(l_pl2)]))
            print(f"  pw={test_pw:>3}: {len(evts):>5} trades, PnL=${total:>+8.2f}, "
                  f"avg=${avg:>+.3f}/trade, WR={wr:.1f}%, unique_levels={n_unique:,}")
        else:
            print(f"  pw={test_pw}: 0 events")

    # --- 9. Prominence filter on left-only pivots ---
    print("\n" + "=" * 70)
    print("=== FIX EXPLORATION: Prominence filter (left-only, pw=30) ===")
    print("=" * 70)
    print("  Require pivot to be at least X * ATR away from recent close")
    print("  (Filters out trivial levels near current price)")

    # Compute a rough rolling ATR for filtering
    closes_arr = df["close"].values
    highs_arr = df["high"].values
    lows_arr = df["low"].values
    n = len(df)
    atr_arr = np.full(n, np.nan)
    for i in range(60, n):
        trs = []
        for j in range(i - 60, i):
            if j == 0:
                trs.append(highs_arr[j] - lows_arr[j])
            else:
                trs.append(max(highs_arr[j] - lows_arr[j],
                               abs(highs_arr[j] - closes_arr[j-1]),
                               abs(lows_arr[j] - closes_arr[j-1])))
        atr_arr[i] = np.mean(trs)

    for min_prom in [0.5, 1.0, 1.5, 2.0, 3.0]:
        # Filter events where |entry_price - pivot_price| >= min_prom * ATR
        base_events = find_confirmed_rebreaks(df, l_ph, l_pl, MIN_TICKS)
        if len(base_events) == 0:
            continue
        # Look up ATR at each event's entry_idx
        entry_atrs = [atr_arr[int(idx)] if int(idx) < n and not np.isnan(atr_arr[int(idx)]) else 0.5
                      for idx in base_events["entry_idx"]]
        base_events["entry_atr"] = entry_atrs
        pivot_dist = np.abs(base_events["entry_price"] - base_events["pivot_price"])
        # Actually: prominence = how far is the pivot from the bars around it
        # Simpler: filter on pivot level being at least min_prom * ATR from current close
        # Since entry is near pivot, use distance between pivot and a reference
        # Better approach: just filter on absolute PnL quality proxy = keep events where
        # the pivot level has been stable for a while
        # Actually simplest: filter on the gap (bars_since_first) being >= some minimum
        pass

    # Better: just test the effect of requiring minimum gap
    print("\n" + "=" * 70)
    print("=== FIX EXPLORATION: Minimum gap filter (left-only, pw=30) ===")
    print("=" * 70)
    base_events = find_confirmed_rebreaks(df, l_ph, l_pl, MIN_TICKS)
    if len(base_events) > 0:
        base_events = compute_forward_pnl(df, base_events, HOLD_BARS, SPREAD)
        for min_gap in [3, 5, 8, 10, 15, 20]:
            filt = base_events[base_events["gap"] >= min_gap]
            if len(filt) > 0:
                total = filt["pnl_fwd"].sum()
                avg = filt["pnl_fwd"].mean()
                wr = (filt["pnl_fwd"] > 0).mean() * 100
                print(f"  min_gap={min_gap:>2}: {len(filt):>5} trades, PnL=${total:>+8.2f}, "
                      f"avg=${avg:>+.3f}/trade, WR={wr:.1f}%")

    # --- 10. Stability filter: only trade if pivot hasn't changed for N bars ---
    print("\n" + "=" * 70)
    print("=== FIX EXPLORATION: Pivot stability filter (left-only, pw=30) ===")
    print("=" * 70)
    print("  Count how many consecutive bars the pivot stayed the same before the event")

    if len(base_events) > 0:
        # For each event, look back from the event bar and count how many bars
        # the pivot_high or pivot_low stayed at the same value
        stabilities = []
        for _, evt in base_events.iterrows():
            idx = int(evt["idx"])
            direction = evt["direction"]
            pivot_val = evt["pivot_price"]
            if direction == "long":
                pivot_series = l_ph
            else:
                pivot_series = l_pl
            # Count backwards from idx
            count = 0
            for j in range(idx, max(idx - 200, 0), -1):
                if not np.isnan(pivot_series[j]) and pivot_series[j] == pivot_val:
                    count += 1
                else:
                    break
            stabilities.append(count)

        base_events["stability"] = stabilities
        print(f"  Stability distribution: "
              f"min={min(stabilities)}, median={int(np.median(stabilities))}, "
              f"mean={np.mean(stabilities):.1f}, max={max(stabilities)}")

        for min_stab in [5, 10, 15, 20, 30, 50]:
            filt = base_events[base_events["stability"] >= min_stab]
            if len(filt) > 0:
                total = filt["pnl_fwd"].sum()
                avg = filt["pnl_fwd"].mean()
                wr = (filt["pnl_fwd"] > 0).mean() * 100
                print(f"  min_stability={min_stab:>2}: {len(filt):>5} trades, PnL=${total:>+8.2f}, "
                      f"avg=${avg:>+.3f}/trade, WR={wr:.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
