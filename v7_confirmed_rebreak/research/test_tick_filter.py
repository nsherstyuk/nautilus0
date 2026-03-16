"""
Quick test: does filtering out low-tick-count bars from the imbalance window
improve the confirmed rebreak signal?

Compares: no filter vs min_tick_count = [20, 50, 100]
Only tests pw=30 (the best balanced config) on XAUUSD, OOS only.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")
IMB_WINDOW = 3
FORWARD_HORIZONS = [10, 15, 30, 60]
DIVERGENCE_THRESHOLD = 0.5
MAX_PULLBACK = 60
MIN_PULLBACK = 3
SPREAD = 0.30
PW = 30
MIN_TICK_THRESHOLDS = [0, 20, 50, 100]


def load_data():
    path = DATA_DIR / "xauusd_1m_tick.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    return df


def detect_pivots(df, window):
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    pivot_highs = np.full(n, np.nan)
    pivot_lows = np.full(n, np.nan)
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values
    pivot_highs[highs == roll_max] = highs[highs == roll_max]
    pivot_lows[lows == roll_min] = lows[lows == roll_min]
    return pivot_highs, pivot_lows


def get_buy_ratio_filtered(buy_vols, sell_vols, tick_counts, start, end,
                           min_ticks):
    """Compute buy_ratio, but return NaN if any bar in window has < min_ticks."""
    if min_ticks > 0:
        tc = tick_counts[start:end]
        if np.any(tc < min_ticks):
            return np.nan
    bv = buy_vols[start:end].sum()
    sv = sell_vols[start:end].sum()
    total = bv + sv
    if total == 0:
        return np.nan
    return bv / total


def run_study(df, pivot_highs, pivot_lows, min_ticks):
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values
    tick_counts = df["tick_count"].values
    timestamps = df["timestamp"].values

    events = []

    last_ph = np.nan
    last_pl = np.nan
    h_broke = False
    h_pb = False
    h_div = False
    h_first_idx = -1
    l_broke = False
    l_pb = False
    l_div = False
    l_first_idx = -1

    for i in range(n):
        if not np.isnan(pivot_highs[i]):
            last_ph = pivot_highs[i]
            h_broke = False
            h_pb = False
        if not np.isnan(pivot_lows[i]):
            last_pl = pivot_lows[i]
            l_broke = False
            l_pb = False

        # UP
        if not np.isnan(last_ph):
            if not h_broke:
                if closes[i] > last_ph:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio_filtered(buy_vols, sell_vols,
                                                    tick_counts, i+1, end_imb,
                                                    min_ticks)
                        if not np.isnan(br):
                            h_broke = True
                            h_first_idx = i
                            h_div = br < DIVERGENCE_THRESHOLD
                            if not h_div:
                                _add_event(events, i, IMB_WINDOW, n, closes,
                                           timestamps, "up", last_ph, br,
                                           "clean_first", 0)
            elif not h_pb:
                if closes[i] <= last_ph:
                    h_pb = True
            else:
                gap = i - h_first_idx
                if gap > MAX_PULLBACK:
                    h_broke = False
                    h_pb = False
                    continue
                if gap >= MIN_PULLBACK and closes[i] > last_ph:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio_filtered(buy_vols, sell_vols,
                                                    tick_counts, i+1, end_imb,
                                                    min_ticks)
                        if not np.isnan(br):
                            matching = br >= DIVERGENCE_THRESHOLD
                            if h_div and matching:
                                label = "confirmed_rebreak"
                            else:
                                label = "other_rebreak"
                            _add_event(events, i, IMB_WINDOW, n, closes,
                                       timestamps, "up", last_ph, br,
                                       label, gap)
                            h_broke = False
                            h_pb = False

        # DOWN
        if not np.isnan(last_pl):
            if not l_broke:
                if closes[i] < last_pl:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio_filtered(buy_vols, sell_vols,
                                                    tick_counts, i+1, end_imb,
                                                    min_ticks)
                        if not np.isnan(br):
                            l_broke = True
                            l_first_idx = i
                            l_div = br > DIVERGENCE_THRESHOLD
                            if not l_div:
                                _add_event(events, i, IMB_WINDOW, n, closes,
                                           timestamps, "down", last_pl, br,
                                           "clean_first", 0)
            elif not l_pb:
                if closes[i] >= last_pl:
                    l_pb = True
            else:
                gap = i - l_first_idx
                if gap > MAX_PULLBACK:
                    l_broke = False
                    l_pb = False
                    continue
                if gap >= MIN_PULLBACK and closes[i] < last_pl:
                    end_imb = min(i + IMB_WINDOW + 1, n)
                    if end_imb > i + 1:
                        br = get_buy_ratio_filtered(buy_vols, sell_vols,
                                                    tick_counts, i+1, end_imb,
                                                    min_ticks)
                        if not np.isnan(br):
                            matching = br <= DIVERGENCE_THRESHOLD
                            if l_div and matching:
                                label = "confirmed_rebreak"
                            else:
                                label = "other_rebreak"
                            _add_event(events, i, IMB_WINDOW, n, closes,
                                       timestamps, "down", last_pl, br,
                                       label, gap)
                            l_broke = False
                            l_pb = False

    return pd.DataFrame(events)


def _add_event(events, idx, imb_w, n, closes, timestamps, direction,
               pivot, br, label, gap):
    entry_idx = idx + imb_w
    if entry_idx >= n:
        return
    entry_price = closes[entry_idx]
    row = {
        "timestamp": timestamps[idx],
        "direction": direction,
        "label": label,
        "buy_ratio": br,
        "gap": gap,
    }
    for h in FORWARD_HORIZONS:
        fwd_idx = entry_idx + h
        if fwd_idx < n:
            ret = closes[fwd_idx] - entry_price
            if direction == "down":
                ret = -ret
            row[f"real_{h}m"] = ret - SPREAD
        else:
            row[f"real_{h}m"] = np.nan
    events.append(row)


def main():
    print("Loading XAUUSD data...")
    df = load_data()
    print(f"  {len(df):,} bars")

    pivot_highs, pivot_lows = detect_pivots(df, PW)
    print(f"  Pivots: {np.sum(~np.isnan(pivot_highs)):,} H, "
          f"{np.sum(~np.isnan(pivot_lows)):,} L")

    real_cols = [f"real_{h}m" for h in FORWARD_HORIZONS]

    for mt in MIN_TICK_THRESHOLDS:
        print(f"\n{'='*70}")
        print(f"MIN_TICK_COUNT = {mt}")
        events = run_study(df, pivot_highs, pivot_lows, mt)
        if len(events) == 0:
            print("  No events")
            continue

        # OOS only
        events["ts"] = pd.to_datetime(events["timestamp"])
        oos = events[events["ts"].dt.year >= 2023]

        conf = oos[oos["label"] == "confirmed_rebreak"]
        clean = oos[oos["label"] == "clean_first"]

        print(f"  OOS confirmed_rebreak: {len(conf):,}")
        print(f"  OOS clean_first: {len(clean):,}")

        if len(conf) > 10:
            print(f"\n  Confirmed rebreak OOS P&L (after spread):")
            line = "    "
            for col in real_cols:
                h = col.replace("real_", "")
                m = conf[col].mean()
                w = (conf[col] > 0).mean()
                line += f"  {h}: {m:+.3f} ({w:.0%})"
            print(line)

        if len(clean) > 10:
            print(f"  Clean first OOS P&L (after spread):")
            line = "    "
            for col in real_cols:
                h = col.replace("real_", "")
                m = clean[col].mean()
                w = (clean[col] > 0).mean()
                line += f"  {h}: {m:+.3f} ({w:.0%})"
            print(line)

        if len(conf) > 10 and len(clean) > 10:
            print(f"  Edge (confirmed - clean):")
            line = "    "
            for col in real_cols:
                h = col.replace("real_", "")
                edge = conf[col].mean() - clean[col].mean()
                line += f"  {h}: {edge:+.3f}"
            print(line)

        # Also show per-direction
        for d in ["up", "down"]:
            dc = conf[conf["direction"] == d]
            if len(dc) > 5:
                line = f"    {d:>5} confirmed (n={len(dc):>4}):"
                for col in real_cols:
                    h = col.replace("real_", "")
                    m = dc[col].mean()
                    w = (dc[col] > 0).mean()
                    line += f"  {h}={m:+.3f}({w:.0%})"
                print(line)

    print("\nDone.")


if __name__ == "__main__":
    main()
