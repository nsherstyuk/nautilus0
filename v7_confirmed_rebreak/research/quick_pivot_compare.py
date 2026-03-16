"""Quick comparison: centered vs causal-centered vs left-only pivots.
Just event counts and PnL. No slow explorations."""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

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
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    df = df[df["timestamp"] >= OOS_START].reset_index(drop=True)
    print(f"Loaded {len(df):,} OOS bars")
    return df


def centered_pivots(df, window):
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)
    last_ph = np.nan
    last_pl = np.nan
    for i in range(n):
        if highs[i] == roll_max[i] and not np.isnan(roll_max[i]):
            last_ph = highs[i]
        if lows[i] == roll_min[i] and not np.isnan(roll_min[i]):
            last_pl = lows[i]
        pivot_high[i] = last_ph
        pivot_low[i] = last_pl
    return pivot_high, pivot_low


def causal_centered_pivots(df, window):
    """Sliding window 2*w+1. Middle bar is pivot if max/min of buffer. Forward-filled."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    buf_size = 2 * window + 1

    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)
    last_ph = np.nan
    last_pl = np.nan

    for i in range(buf_size - 1, n):
        buf_start = i - buf_size + 1
        buf_highs = highs[buf_start:i + 1]
        buf_lows = lows[buf_start:i + 1]
        mid_high = buf_highs[window]
        mid_low = buf_lows[window]

        if mid_high >= np.max(buf_highs):
            last_ph = mid_high
        if mid_low <= np.min(buf_lows):
            last_pl = mid_low

        pivot_high[i] = last_ph
        pivot_low[i] = last_pl
    return pivot_high, pivot_low


def shifted_centered_pivots(df, window):
    """Centered pivots with honest delay: detect pivots using centered logic,
    but only make them available `window` bars after the pivot bar.

    A pivot at bar i is detected at bar i (centered knows both sides),
    but in reality you'd only know it at bar i+window. So we forward-fill
    from bar i+window instead of bar i.

    This gives research-quality levels with honest causal timing."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    # Find pivot bars (where bar value == centered rolling extreme)
    is_ph = (highs == roll_max) & ~np.isnan(roll_max)
    is_pl = (lows == roll_min) & ~np.isnan(roll_min)

    # Build pivot series with shifted forward-fill
    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)
    last_ph = np.nan
    last_pl = np.nan

    for i in range(n):
        # Check if a pivot from `window` bars ago is being confirmed now
        lookback = i - window
        if lookback >= 0:
            if is_ph[lookback]:
                last_ph = highs[lookback]
            if is_pl[lookback]:
                last_pl = lows[lookback]
        pivot_high[i] = last_ph
        pivot_low[i] = last_pl

    return pivot_high, pivot_low


def get_buy_ratio_q(buy_vols, sell_vols, tick_counts, start, end, min_ticks):
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


def find_events(df, pivot_high, pivot_low, min_ticks):
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values
    tick_counts = df["tick_count"].values
    events = []

    h_level = np.nan; h_broke = False; h_pb = False; h_idx = -1; h_div = False
    l_level = np.nan; l_broke = False; l_pb = False; l_idx = -1; l_div = False

    for i in range(n):
        if not np.isnan(pivot_high[i]) and pivot_high[i] != h_level:
            h_level = pivot_high[i]; h_broke = False; h_pb = False; h_idx = -1
        if not np.isnan(pivot_low[i]) and pivot_low[i] != l_level:
            l_level = pivot_low[i]; l_broke = False; l_pb = False; l_idx = -1

        # LONG
        if not np.isnan(h_level):
            if not h_broke:
                if closes[i] > h_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_buy_ratio_q(buy_vols, sell_vols, tick_counts, i+1, ie, min_ticks)
                        if not np.isnan(br):
                            h_broke = True; h_idx = i; h_div = (br < DIV_THRESHOLD)
                            if not h_div:
                                h_broke = False
            elif not h_pb:
                if closes[i] <= h_level:
                    h_pb = True
            else:
                gap = i - h_idx
                if gap > MAX_PB:
                    h_broke = False; h_pb = False; continue
                if gap >= MIN_PB and closes[i] > h_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_buy_ratio_q(buy_vols, sell_vols, tick_counts, i+1, ie, min_ticks)
                        if not np.isnan(br):
                            if h_div and br >= DIV_THRESHOLD:
                                eidx = i + IMB_WINDOW
                                if eidx < n:
                                    events.append({"idx": i, "entry_idx": eidx,
                                        "timestamp": df["timestamp"].iloc[i],
                                        "direction": "long", "pivot_price": h_level,
                                        "entry_price": closes[eidx], "buy_ratio": br, "gap": gap})
                            h_broke = False; h_pb = False

        # SHORT
        if not np.isnan(l_level):
            if not l_broke:
                if closes[i] < l_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_buy_ratio_q(buy_vols, sell_vols, tick_counts, i+1, ie, min_ticks)
                        if not np.isnan(br):
                            l_broke = True; l_idx = i; l_div = (br > DIV_THRESHOLD)
                            if not l_div:
                                l_broke = False
            elif not l_pb:
                if closes[i] >= l_level:
                    l_pb = True
            else:
                gap = i - l_idx
                if gap > MAX_PB:
                    l_broke = False; l_pb = False; continue
                if gap >= MIN_PB and closes[i] < l_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_buy_ratio_q(buy_vols, sell_vols, tick_counts, i+1, ie, min_ticks)
                        if not np.isnan(br):
                            if l_div and br <= DIV_THRESHOLD:
                                eidx = i + IMB_WINDOW
                                if eidx < n:
                                    events.append({"idx": i, "entry_idx": eidx,
                                        "timestamp": df["timestamp"].iloc[i],
                                        "direction": "short", "pivot_price": l_level,
                                        "entry_price": closes[eidx], "buy_ratio": br, "gap": gap})
                            l_broke = False; l_pb = False

    return pd.DataFrame(events)


def compute_pnl(df, events, hold_bars, spread):
    closes = df["close"].values
    n = len(df)
    pnls = []
    for _, evt in events.iterrows():
        eidx = int(evt["entry_idx"])
        xidx = min(eidx + hold_bars, n - 1)
        ep = evt["entry_price"]
        xp = closes[xidx]
        if evt["direction"] == "long":
            pnl = (xp - ep) - spread
        else:
            pnl = (ep - xp) - spread
        pnls.append(pnl)
    events = events.copy()
    events["pnl"] = pnls
    return events


def stats(label, events):
    if len(events) == 0:
        print(f"  {label}: 0 events")
        return
    p = events["pnl"]
    print(f"  {label}: {len(events)} trades, PnL=${p.sum():+.2f}, "
          f"avg=${p.mean():+.3f}/trade, WR={((p>0).mean()*100):.1f}%")


def main():
    df = load_data()
    print(f"pw={PW}, hold={HOLD_BARS}, min_ticks={MIN_TICKS}, spread=${SPREAD}")

    print("\n--- Pivot Detection ---")
    c_ph, c_pl = centered_pivots(df, PW)
    cc_ph, cc_pl = causal_centered_pivots(df, PW)
    sc_ph, sc_pl = shifted_centered_pivots(df, PW)

    c_uh = len(set(c_ph[~np.isnan(c_ph)]))
    c_ul = len(set(c_pl[~np.isnan(c_pl)]))
    cc_uh = len(set(cc_ph[~np.isnan(cc_ph)]))
    cc_ul = len(set(cc_pl[~np.isnan(cc_pl)]))
    sc_uh = len(set(sc_ph[~np.isnan(sc_ph)]))
    sc_ul = len(set(sc_pl[~np.isnan(sc_pl)]))
    print(f"  Centered:         {c_uh} unique highs, {c_ul} unique lows")
    print(f"  Causal-centered:  {cc_uh} unique highs, {cc_ul} unique lows")
    print(f"  Shifted-centered: {sc_uh} unique highs, {sc_ul} unique lows")

    # Check bar-by-bar agreement
    valid = ~np.isnan(c_ph) & ~np.isnan(sc_ph)
    if valid.sum() > 0:
        agree_h = (c_ph[valid] == sc_ph[valid]).mean() * 100
        valid_l = ~np.isnan(c_pl) & ~np.isnan(sc_pl)
        agree_l = (c_pl[valid_l] == sc_pl[valid_l]).mean() * 100
        print(f"  Shifted vs Centered bar-by-bar: highs={agree_h:.1f}%, lows={agree_l:.1f}%")

    print("\n--- Event Detection ---")
    c_events = find_events(df, c_ph, c_pl, MIN_TICKS)
    cc_events = find_events(df, cc_ph, cc_pl, MIN_TICKS)
    sc_events = find_events(df, sc_ph, sc_pl, MIN_TICKS)
    print(f"  Centered:         {len(c_events)} events")
    print(f"  Causal-centered:  {len(cc_events)} events")
    print(f"  Shifted-centered: {len(sc_events)} events")

    print("\n--- PnL (hold={} bars, forward return) ---".format(HOLD_BARS))
    if len(c_events) > 0:
        c_events = compute_pnl(df, c_events, HOLD_BARS, SPREAD)
        stats("Centered", c_events)
    if len(cc_events) > 0:
        cc_events = compute_pnl(df, cc_events, HOLD_BARS, SPREAD)
        stats("Causal-centered", cc_events)
    if len(sc_events) > 0:
        sc_events = compute_pnl(df, sc_events, HOLD_BARS, SPREAD)
        stats("Shifted-centered", sc_events)

    # Overlap: shifted vs centered
    ov = set()
    if len(c_events) > 0 and len(sc_events) > 0:
        c_ts = set(c_events["timestamp"].values)
        sc_ts = set(sc_events["timestamp"].values)
        ov = c_ts & sc_ts
        print(f"\n--- Event Overlap (Shifted vs Centered) ---")
        print(f"  Shared: {len(ov)}, centered-only: {len(c_ts - sc_ts)}, "
              f"shifted-only: {len(sc_ts - c_ts)}")
        if len(ov) > 0:
            sc_ov = sc_events[sc_events["timestamp"].isin(ov)]
            sc_uniq = sc_events[~sc_events["timestamp"].isin(ov)]
            stats("Shared (shifted)", sc_ov)
            if len(sc_uniq) > 0:
                stats("Shifted-only", sc_uniq)

    # Yearly
    if len(cc_events) > 0:
        print("\n--- Yearly: Causal-centered ---")
        cc_events["year"] = cc_events["timestamp"].dt.year
        for yr, grp in cc_events.groupby("year"):
            print(f"  {yr}: {len(grp)} trades, PnL=${grp['pnl'].sum():+.2f}, "
                  f"avg=${grp['pnl'].mean():+.3f}")

    # --- What distinguishes good vs bad events? ---
    if len(cc_events) > 0 and len(ov) > 0:
        print("\n" + "=" * 60)
        print("=== FEATURE COMPARISON: Shared (good) vs Causal-only (bad) ===")
        print("=" * 60)

        good = cc_events[cc_events["timestamp"].isin(ov)].copy()
        bad = cc_events[~cc_events["timestamp"].isin(ov)].copy()

        print(f"\n  Good: {len(good)} trades, avg PnL=${good['pnl'].mean():+.3f}")
        print(f"  Bad:  {len(bad)} trades, avg PnL=${bad['pnl'].mean():+.3f}")

        # Gap (bars between first break and rebreak)
        print(f"\n  Gap (bars_since_first):")
        print(f"    Good: mean={good['gap'].mean():.1f}, median={good['gap'].median():.0f}")
        print(f"    Bad:  mean={bad['gap'].mean():.1f}, median={bad['gap'].median():.0f}")

        # Buy ratio
        print(f"\n  Buy ratio at rebreak:")
        print(f"    Good: mean={good['buy_ratio'].mean():.3f}")
        print(f"    Bad:  mean={bad['buy_ratio'].mean():.3f}")

        # Direction split
        g_long = (good['direction'] == 'long').sum()
        g_short = (good['direction'] == 'short').sum()
        b_long = (bad['direction'] == 'long').sum()
        b_short = (bad['direction'] == 'short').sum()
        print(f"\n  Direction:")
        print(f"    Good: {g_long} long ({g_long/len(good)*100:.0f}%), "
              f"{g_short} short ({g_short/len(good)*100:.0f}%)")
        print(f"    Bad:  {b_long} long ({b_long/len(bad)*100:.0f}%), "
              f"{b_short} short ({b_short/len(bad)*100:.0f}%)")

        # Hour of day (UTC)
        good["hour"] = good["timestamp"].dt.hour
        bad["hour"] = bad["timestamp"].dt.hour
        print(f"\n  Hour distribution (top 5):")
        print(f"    Good: {good['hour'].value_counts().head(5).to_dict()}")
        print(f"    Bad:  {bad['hour'].value_counts().head(5).to_dict()}")

        # Pivot distance from entry price
        good["pivot_dist"] = np.abs(good["entry_price"] - good["pivot_price"])
        bad["pivot_dist"] = np.abs(bad["entry_price"] - bad["pivot_price"])
        print(f"\n  Pivot distance (|entry - pivot|):")
        print(f"    Good: mean=${good['pivot_dist'].mean():.2f}, median=${good['pivot_dist'].median():.2f}")
        print(f"    Bad:  mean=${bad['pivot_dist'].mean():.2f}, median=${bad['pivot_dist'].median():.2f}")

        # Test pivot_dist as filter
        print(f"\n  --- Filter test: max pivot_dist ---")
        for max_dist in [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]:
            filt = cc_events[np.abs(cc_events["entry_price"] - cc_events["pivot_price"]) <= max_dist]
            if len(filt) > 0:
                g_in = filt["timestamp"].isin(ov).sum()
                b_in = len(filt) - g_in
                print(f"    dist<={max_dist}: {len(filt)} trades ({g_in} good, {b_in} bad), "
                      f"PnL=${filt['pnl'].sum():+.2f}, avg=${filt['pnl'].mean():+.3f}")

        # Test gap as filter
        print(f"\n  --- Filter test: min gap ---")
        for min_gap in [3, 5, 8, 10, 15, 20, 30]:
            filt = cc_events[cc_events["gap"] >= min_gap]
            if len(filt) > 0:
                g_in = filt["timestamp"].isin(ov).sum()
                b_in = len(filt) - g_in
                print(f"    gap>={min_gap:>2}: {len(filt)} trades ({g_in} good, {b_in} bad), "
                      f"PnL=${filt['pnl'].sum():+.2f}, avg=${filt['pnl'].mean():+.3f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
