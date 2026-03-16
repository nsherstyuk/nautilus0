"""Test: feed pre-computed centered pivots into a standalone pattern detector
+ execution loop. This bypasses the PivotTracker entirely and tells us the
ceiling PnL achievable if we had perfect pivot detection.

Then test with shifted (delayed) centered pivots to see the honest causal ceiling."""
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


def compute_pivots(highs, lows, n, window, shift=0):
    """Centered pivot detection with optional forward shift.
    shift=0: research-style (pivot known immediately)
    shift=window: honest causal delay"""
    full_win = 2 * window + 1
    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    is_ph = (highs == roll_max) & ~np.isnan(roll_max)
    is_pl = (lows == roll_min) & ~np.isnan(roll_min)

    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)
    last_ph = np.nan
    last_pl = np.nan

    for i in range(n):
        lookback = i - shift
        if lookback >= 0:
            if is_ph[lookback]:
                last_ph = highs[lookback]
            if is_pl[lookback]:
                last_pl = lows[lookback]
        pivot_high[i] = last_ph
        pivot_low[i] = last_pl

    return pivot_high, pivot_low


def run_backtest_with_pivots(df, pivot_high, pivot_low, hold_bars, spread, min_ticks):
    """Run a full backtest using pre-computed pivot series.
    Includes: pattern detection (divergent first break -> pullback -> matching rebreak),
    imbalance quality filter, cooldown, and in-trade blocking."""
    n = len(df)
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values
    tick_counts = df["tick_count"].values

    # Compute ATR
    highs = df["high"].values
    lows = df["low"].values
    atr = np.full(n, np.nan)
    prev_close = closes[0]
    tr_buf = []
    for i in range(n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - prev_close),
                 abs(lows[i] - prev_close))
        tr_buf.append(tr)
        if len(tr_buf) > 60:
            tr_buf.pop(0)
        atr[i] = np.mean(tr_buf)
        prev_close = closes[i]

    trades = []
    # State
    in_trade = False
    trade_entry_idx = 0
    trade_direction = ""
    trade_entry_price = 0.0
    cooldown = 0

    h_level = np.nan; h_broke = False; h_pb = False; h_idx = -1; h_div = False
    l_level = np.nan; l_broke = False; l_pb = False; l_idx = -1; l_div = False

    def get_br(start, end):
        if end > n:
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

    for i in range(n):
        # Cooldown
        if cooldown > 0:
            cooldown -= 1
            continue

        # In-trade management
        if in_trade:
            bars_held = i - trade_entry_idx
            if bars_held >= hold_bars:
                # Time stop
                exit_price = closes[i]
                if trade_direction == "long":
                    pnl = (exit_price - spread/2) - trade_entry_price
                else:
                    pnl = trade_entry_price - (exit_price + spread/2)
                trades.append({
                    "entry_idx": trade_entry_idx,
                    "exit_idx": i,
                    "timestamp": df["timestamp"].iloc[trade_entry_idx],
                    "direction": trade_direction,
                    "pnl": pnl,
                    "hold_bars": bars_held,
                })
                in_trade = False
                cooldown = IMB_WINDOW
            continue

        # Update pivot levels
        if not np.isnan(pivot_high[i]) and pivot_high[i] != h_level:
            h_level = pivot_high[i]; h_broke = False; h_pb = False; h_idx = -1
        if not np.isnan(pivot_low[i]) and pivot_low[i] != l_level:
            l_level = pivot_low[i]; l_broke = False; l_pb = False; l_idx = -1

        signal = None

        # LONG
        if not np.isnan(h_level) and not h_broke:
            if closes[i] > h_level:
                ie = min(i + IMB_WINDOW + 1, n)
                if ie > i + 1:
                    br = get_br(i+1, ie)
                    if not np.isnan(br):
                        h_broke = True; h_idx = i; h_div = (br < DIV_THRESHOLD)
                        if not h_div:
                            h_broke = False
        elif not np.isnan(h_level) and h_broke and not h_pb:
            if closes[i] <= h_level:
                h_pb = True
        elif not np.isnan(h_level) and h_broke and h_pb:
            gap = i - h_idx
            if gap > MAX_PB:
                h_broke = False; h_pb = False
            elif gap >= MIN_PB and closes[i] > h_level:
                ie = min(i + IMB_WINDOW + 1, n)
                if ie > i + 1:
                    br = get_br(i+1, ie)
                    if not np.isnan(br):
                        if h_div and br >= DIV_THRESHOLD:
                            eidx = i + IMB_WINDOW
                            if eidx < n:
                                signal = ("long", eidx, closes[eidx])
                        h_broke = False; h_pb = False

        # SHORT
        if signal is None:
            if not np.isnan(l_level) and not l_broke:
                if closes[i] < l_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_br(i+1, ie)
                        if not np.isnan(br):
                            l_broke = True; l_idx = i; l_div = (br > DIV_THRESHOLD)
                            if not l_div:
                                l_broke = False
            elif not np.isnan(l_level) and l_broke and not l_pb:
                if closes[i] >= l_level:
                    l_pb = True
            elif not np.isnan(l_level) and l_broke and l_pb:
                gap = i - l_idx
                if gap > MAX_PB:
                    l_broke = False; l_pb = False
                elif gap >= MIN_PB and closes[i] < l_level:
                    ie = min(i + IMB_WINDOW + 1, n)
                    if ie > i + 1:
                        br = get_br(i+1, ie)
                        if not np.isnan(br):
                            if l_div and br <= DIV_THRESHOLD:
                                eidx = i + IMB_WINDOW
                                if eidx < n:
                                    signal = ("short", eidx, closes[eidx])
                            l_broke = False; l_pb = False

        # Enter trade
        if signal is not None:
            direction, eidx, ep = signal
            if direction == "long":
                trade_entry_price = ep + spread/2
            else:
                trade_entry_price = ep - spread/2
            trade_entry_idx = eidx
            trade_direction = direction
            in_trade = True

    return pd.DataFrame(trades)


def stats(label, trades):
    if len(trades) == 0:
        print(f"  {label}: 0 trades")
        return
    p = trades["pnl"]
    print(f"  {label}: {len(trades)} trades, PnL=${p.sum():+.2f}, "
          f"avg=${p.mean():+.3f}/trade, WR={((p>0).mean()*100):.1f}%")
    # Yearly
    trades_copy = trades.copy()
    trades_copy["year"] = trades_copy["timestamp"].dt.year
    for yr, grp in trades_copy.groupby("year"):
        print(f"    {yr}: {len(grp)} trades, ${grp['pnl'].sum():+.2f}")


def main():
    df = load_data()
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    for hold in [45, 60]:
        print(f"\n{'='*60}")
        print(f"Hold={hold} bars, pw={PW}, min_ticks={MIN_TICKS}")
        print(f"{'='*60}")

        # Centered (no delay - research style)
        ph0, pl0 = compute_pivots(highs, lows, n, PW, shift=0)
        t0 = run_backtest_with_pivots(df, ph0, pl0, hold, SPREAD, MIN_TICKS)
        stats("Centered (shift=0)", t0)

        # Shifted by window (honest causal delay)
        ph30, pl30 = compute_pivots(highs, lows, n, PW, shift=PW)
        t30 = run_backtest_with_pivots(df, ph30, pl30, hold, SPREAD, MIN_TICKS)
        stats(f"Shifted (shift={PW})", t30)

        # Shifted by smaller delays
        for shift in [5, 10, 15, 20]:
            phs, pls = compute_pivots(highs, lows, n, PW, shift=shift)
            ts = run_backtest_with_pivots(df, phs, pls, hold, SPREAD, MIN_TICKS)
            stats(f"Shifted (shift={shift})", ts)

    print("\nDone.")


if __name__ == "__main__":
    main()
