"""
session_breakout_signal.py — Session-Range Breakout Signal Generator + Edge Test

Path C, Step 1 & 2: Build session-range breakout signals and test their edge
against a random baseline.

Signal Logic:
  1. Asian consolidation range: High/Low of 15m bars from 00:00–07:00 UTC each day
  2. London breakout window: 07:00–10:00 UTC
     - LONG  signal: first bar whose close > Asian High
     - SHORT signal: first bar whose close < Asian Low
  3. NY breakout window: 13:00–16:00 UTC (using London-session range 07:00–13:00)
     - Same logic: first bar closing beyond the updated range

Trade simulation:
  TP = 1.5 × ATR(14), SL = 1.4 × ATR(14), LOOKAHEAD = 100 bars (15m)
  Same framework as test_v2_signal_edge.py for apples-to-apples comparison.

Usage:
  python -m trading_system_v4.scripts.session_breakout_signal
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

# ── Simulation constants (match existing pipeline) ────────────────────────────
SPREAD_EST    = 0.00010
SL_ATR        = 1.4
TP_ATR        = 1.5
LOOKAHEAD     = 100       # 100 × 15m = 25 hours
BE_WR         = SL_ATR / (SL_ATR + TP_ATR)  # 48.3%

# ── Session time boundaries (UTC hours) ───────────────────────────────────────
ASIAN_START_H  = 0    # 00:00 UTC
ASIAN_END_H    = 7    # 07:00 UTC (last Asian bar timestamp = 07:00)
LONDON_START_H = 7    # 07:00 UTC
LONDON_END_H   = 10   # 10:00 UTC (breakout window closes)
NY_START_H     = 13   # 13:00 UTC
NY_END_H       = 16   # 16:00 UTC


# ── ATR (14-period Wilder EWM) ────────────────────────────────────────────────
def _atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=13, adjust=False).mean()


# ── Session range computation ─────────────────────────────────────────────────
def compute_daily_session_ranges(df15: pd.DataFrame) -> pd.DataFrame:
    """
    For each trading day, compute the Asian session (00:00-07:00 UTC) high/low.
    Also compute London-morning range (07:00-13:00 UTC) for NY breakouts.

    Returns DataFrame indexed by date with columns:
      asian_high, asian_low, asian_range_atr, london_am_high, london_am_low
    """
    hour = df15.index.hour
    date = df15.index.date

    # Asian session: bars timestamped 00:15 .. 07:00 (hour 0..6 for the close, 
    # but with label='right', a bar at 07:00 covers 06:45-07:00, so hour==7 means 
    # the last bar of the Asian session has timestamp at exactly 07:00)
    # Bars with hour in [0, 6] have timestamps 00:15..06:45
    # Bar with hour==7 and minute==0 is the 07:00 bar covering 06:45-07:00
    # So Asian bars: hour < 7, OR (hour == 7 AND minute == 0)
    asian_mask = (hour < ASIAN_END_H) | ((hour == ASIAN_END_H) & (df15.index.minute == 0))

    # London AM: bars with timestamps 07:15..13:00
    london_am_mask = (hour >= LONDON_START_H) & (hour < NY_START_H)
    london_am_mask |= ((hour == NY_START_H) & (df15.index.minute == 0))

    rows = []
    for d in sorted(set(date)):
        day_mask = date == d

        # Asian range
        asian_bars = df15[day_mask & asian_mask]
        if len(asian_bars) < 10:  # need enough bars for a meaningful range
            continue
        a_high = asian_bars["high"].max()
        a_low  = asian_bars["low"].min()

        # London AM range (for NY breakout reference)
        london_am_bars = df15[day_mask & london_am_mask]
        l_high = london_am_bars["high"].max() if len(london_am_bars) > 5 else np.nan
        l_low  = london_am_bars["low"].min()  if len(london_am_bars) > 5 else np.nan

        rows.append({
            "date": d,
            "asian_high": a_high,
            "asian_low": a_low,
            "asian_range": a_high - a_low,
            "london_am_high": l_high,
            "london_am_low": l_low,
        })

    return pd.DataFrame(rows).set_index("date")


# ── Signal generation ─────────────────────────────────────────────────────────
def generate_session_breakout_signals(
    df15: pd.DataFrame,
    ranges: pd.DataFrame,
    session: str = "london",
) -> pd.DataFrame:
    """
    Generate breakout signals from session ranges.

    session = "london": Asian range breakout during London open (07:00-10:00)
    session = "ny":     London AM range breakout during NY open (13:00-16:00)

    Returns DataFrame with columns:
      timestamp, direction, entry_close, range_high, range_low, range_width,
      atr_at_signal, session
    """
    hour = df15.index.hour
    minute = df15.index.minute
    date = df15.index.date

    if session == "london":
        # Breakout window: bars timestamped 07:15 to 10:00
        # hour==7 and minute>0, or hour in [8,9], or hour==10 and minute==0
        window_mask = (
            ((hour == LONDON_START_H) & (minute > 0)) |
            ((hour > LONDON_START_H) & (hour < LONDON_END_H)) |
            ((hour == LONDON_END_H) & (minute == 0))
        )
        range_high_col = "asian_high"
        range_low_col  = "asian_low"
    elif session == "ny":
        # Breakout window: bars timestamped 13:15 to 16:00
        window_mask = (
            ((hour == NY_START_H) & (minute > 0)) |
            ((hour > NY_START_H) & (hour < NY_END_H)) |
            ((hour == NY_END_H) & (minute == 0))
        )
        range_high_col = "london_am_high"
        range_low_col  = "london_am_low"
    else:
        raise ValueError(f"Unknown session: {session}")

    atr = _atr14(df15).to_numpy()
    close_arr = df15["close"].to_numpy()

    signals = []
    seen_dates_long  = set()
    seen_dates_short = set()

    for i in range(len(df15)):
        if not window_mask.iloc[i] if hasattr(window_mask, 'iloc') else not window_mask[i]:
            continue

        d = date[i]
        if d not in ranges.index:
            continue

        rng_high = ranges.loc[d, range_high_col]
        rng_low  = ranges.loc[d, range_low_col]
        if not np.isfinite(rng_high) or not np.isfinite(rng_low):
            continue

        c = close_arr[i]
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # LONG breakout: first bar closing above range high
        if d not in seen_dates_long and c > rng_high:
            seen_dates_long.add(d)
            signals.append({
                "timestamp": df15.index[i],
                "direction": 1,
                "entry_close": c,
                "range_high": rng_high,
                "range_low": rng_low,
                "range_width": rng_high - rng_low,
                "range_width_atr": (rng_high - rng_low) / a,
                "atr_at_signal": a,
                "bar_idx": i,
                "session": session,
            })

        # SHORT breakout: first bar closing below range low
        if d not in seen_dates_short and c < rng_low:
            seen_dates_short.add(d)
            signals.append({
                "timestamp": df15.index[i],
                "direction": -1,
                "entry_close": c,
                "range_high": rng_high,
                "range_low": rng_low,
                "range_width": rng_high - rng_low,
                "range_width_atr": (rng_high - rng_low) / a,
                "atr_at_signal": a,
                "bar_idx": i,
                "session": session,
            })

    return pd.DataFrame(signals) if signals else pd.DataFrame()


# ── Trade simulation (reused from test_v2_signal_edge.py) ─────────────────────
def simulate_trades(
    sig_df: pd.DataFrame,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_arr: np.ndarray,
    n_total: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (mfe_array, outcome_array, pnl_array)
      outcome: +1 = TP hit, -1 = SL hit, 0 = expired
    """
    mfes, outcomes, pnls = [], [], []

    for _, row in sig_df.iterrows():
        pos = int(row["bar_idx"])
        direction = int(row["direction"])

        if pos + LOOKAHEAD >= n_total:
            continue

        cv = close_arr[pos]
        av = atr_arr[pos]
        if not np.isfinite(av) or av <= 0:
            continue

        h_path = high_arr[pos + 1 : pos + 1 + LOOKAHEAD]
        l_path = low_arr[pos + 1 : pos + 1 + LOOKAHEAD]

        if direction == 1:
            entry    = cv + SPREAD_EST
            tp_level = entry + av * TP_ATR
            sl_level = entry - av * SL_ATR
        else:
            entry    = cv - SPREAD_EST
            tp_level = entry - av * TP_ATR
            sl_level = entry + av * SL_ATR

        out, pnl = 0, 0.0
        for j in range(len(h_path)):
            if direction == 1:
                sl_hit = l_path[j] <= sl_level
                tp_hit = h_path[j] >= tp_level
            else:
                sl_hit = h_path[j] >= sl_level
                tp_hit = l_path[j] <= tp_level

            if sl_hit and tp_hit:
                # Both touched same bar — conservative: SL wins
                out, pnl = -1, -(av * SL_ATR)
                break
            if sl_hit:
                out, pnl = -1, -(av * SL_ATR)
                break
            if tp_hit:
                out, pnl = +1, +(av * TP_ATR)
                break
        else:
            out = 0
            final_pos = min(pos + LOOKAHEAD, n_total - 1)
            pnl = (close_arr[final_pos] - entry) * direction

        # MFE before first SL hit
        if direction == 1:
            sl_arr = l_path <= sl_level
        else:
            sl_arr = h_path >= sl_level
        idx_sl = int(np.argmax(sl_arr)) if np.any(sl_arr) else len(h_path)

        if idx_sl > 0:
            if direction == 1:
                mfe = (np.max(h_path[:idx_sl]) - entry) / av
            else:
                mfe = (entry - np.min(l_path[:idx_sl])) / av
        else:
            mfe = 0.0

        mfes.append(float(mfe))
        outcomes.append(out)
        pnls.append(float(pnl))

    return np.array(mfes), np.array(outcomes), np.array(pnls)


# ── Random baseline ──────────────────────────────────────────────────────────
def random_baseline(
    n_signals: int,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_arr: np.ndarray,
    n_total: int,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate random entry signals restricted to London/NY hours (same time distribution)."""
    rng = np.random.RandomState(seed)
    n_rand = max(n_signals, 5000)
    valid = np.arange(200, n_total - LOOKAHEAD - 1)
    idx = rng.choice(valid, size=n_rand, replace=False)
    dirs = rng.choice([-1, 1], size=n_rand)

    rand_df = pd.DataFrame({
        "bar_idx": idx,
        "direction": dirs,
    })
    return simulate_trades(rand_df, high_arr, low_arr, close_arr, atr_arr, n_total)


# ── Stats printing ───────────────────────────────────────────────────────────
def _print_stats(label: str, mfes, outcomes, pnls, n_bars: int):
    n = len(outcomes)
    if n == 0:
        print(f"\n  [{label}] No trades")
        return

    n_tp = (outcomes == 1).sum()
    n_sl = (outcomes == -1).sum()
    n_exp = (outcomes == 0).sum()
    n_resolved = n_tp + n_sl
    wr = n_tp / n_resolved if n_resolved > 0 else float("nan")
    edge = (wr - BE_WR) * 100

    print(f"\n{'='*66}")
    print(f"  {label}")
    print(f"{'='*66}")
    print(f"  Total signals : {n:,}  ({n/n_bars*100:.2f}% of bars)")
    print(f"  TP hit        : {n_tp:,}  ({n_tp/n*100:.1f}%)")
    print(f"  SL hit        : {n_sl:,}  ({n_sl/n*100:.1f}%)")
    print(f"  Expired       : {n_exp:,}  ({n_exp/n*100:.1f}%)")
    print(f"  Win rate      : {wr*100:.1f}%  (break-even: {BE_WR*100:.1f}%)")
    print(f"  Edge          : {edge:+.1f} pp  {'*** ABOVE RANDOM ***' if edge > 2 else '[Marginal]' if edge > 0 else '[No edge]'}")
    print(f"  Mean PnL/trade: {pnls.mean():.5f}   Total PnL: {pnls.sum():.1f} ATR")
    print(f"  MFE  mean={mfes.mean():.3f}  median={np.median(mfes):.3f}  std={mfes.std():.3f}")
    for t in [0.5, 1.0, 1.5, 2.0, 3.0]:
        print(f"    MFE >= {t:.1f} ATR: {(mfes >= t).mean()*100:.1f}%")


def _print_direction_breakdown(label, sig_df, mfes, outcomes, pnls):
    """Break down by LONG vs SHORT."""
    if len(sig_df) == 0:
        return
    directions = sig_df["direction"].values[:len(outcomes)]
    for d, d_name in [(1, "LONG"), (-1, "SHORT")]:
        mask = directions == d
        if mask.sum() == 0:
            continue
        m = mfes[mask]; o = outcomes[mask]; p = pnls[mask]
        n_tp = (o == 1).sum(); n_sl = (o == -1).sum()
        nr = n_tp + n_sl
        wr = n_tp / nr if nr > 0 else float("nan")
        edge = (wr - BE_WR) * 100
        print(f"    {d_name:5s}: n={mask.sum():>5,}  WR={wr*100:5.1f}%  edge={edge:+5.1f}pp  "
              f"meanPnL={p.mean():.5f}  MFE_med={np.median(m):.3f}")


def _print_yearly_breakdown(sig_df, mfes, outcomes, pnls):
    """Break down by year."""
    if len(sig_df) == 0:
        return
    ts = pd.DatetimeIndex(sig_df["timestamp"].values[:len(outcomes)])
    years = ts.year
    print(f"\n  {'Year':>6} {'N':>6} {'WR%':>6} {'Edge':>7} {'MnPnL':>9} {'MFE_med':>8}")
    for y in sorted(years.unique()):
        mask = years == y
        o = outcomes[mask]; p = pnls[mask]; m = mfes[mask]
        n_tp = (o == 1).sum(); n_sl = (o == -1).sum()
        nr = n_tp + n_sl
        wr = n_tp / nr if nr > 0 else float("nan")
        edge = (wr - BE_WR) * 100
        print(f"  {y:>6} {mask.sum():>6,} {wr*100:>6.1f} {edge:>+7.1f} {p.mean():>9.5f} {np.median(m):>8.3f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print("=" * 66)
    print("  SESSION-RANGE BREAKOUT: SIGNAL EDGE TEST")
    print("  Path C — Step 1 & 2")
    print("=" * 66)

    # 1. Load tick bars → resample to 15m
    print(f"\nLoading tick bars from {TICK_BARS_FILE} ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Resampling to 15m ...")
    df15 = tick.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("total_volume", "sum"),
    ).dropna()
    print(f"  {len(df15):,} 15m bars  ({df15.index.min().date()} — {df15.index.max().date()})")

    # Numpy arrays for fast simulation
    h15 = df15["high"].to_numpy()
    l15 = df15["low"].to_numpy()
    c15 = df15["close"].to_numpy()
    atr = _atr14(df15).to_numpy()
    N = len(df15)

    # 2. Compute session ranges
    print("\nComputing daily session ranges ...")
    ranges = compute_daily_session_ranges(df15)
    print(f"  {len(ranges):,} trading days with Asian ranges")
    print(f"  Asian range: mean={ranges['asian_range'].mean()*10000:.1f} pips  "
          f"median={ranges['asian_range'].median()*10000:.1f} pips  "
          f"std={ranges['asian_range'].std()*10000:.1f} pips")

    # 3. Random baseline
    print("\n" + "-" * 66)
    print("  RANDOM BASELINE")
    print("-" * 66)
    r_mfes, r_oc, r_pnls = random_baseline(10000, h15, l15, c15, atr, N)
    _print_stats("RANDOM BASELINE (n=10k, SL=1.4, TP=1.5)", r_mfes, r_oc, r_pnls, N)

    # 4. London breakout signals
    print("\n" + "-" * 66)
    print("  LONDON SESSION BREAKOUT (Asian range break at 07:00-10:00 UTC)")
    print("-" * 66)
    london_signals = generate_session_breakout_signals(df15, ranges, session="london")
    if len(london_signals) > 0:
        l_mfes, l_oc, l_pnls = simulate_trades(london_signals, h15, l15, c15, atr, N)
        _print_stats("LONDON BREAKOUT (Asian range)", l_mfes, l_oc, l_pnls, N)
        print("\n  Direction breakdown:")
        _print_direction_breakdown("LONDON", london_signals, l_mfes, l_oc, l_pnls)
        print("\n  Yearly breakdown:")
        _print_yearly_breakdown(london_signals, l_mfes, l_oc, l_pnls)
    else:
        print("  [NO SIGNALS]")

    # 5. NY breakout signals
    print("\n" + "-" * 66)
    print("  NY SESSION BREAKOUT (London AM range break at 13:00-16:00 UTC)")
    print("-" * 66)
    ny_signals = generate_session_breakout_signals(df15, ranges, session="ny")
    if len(ny_signals) > 0:
        n_mfes, n_oc, n_pnls = simulate_trades(ny_signals, h15, l15, c15, atr, N)
        _print_stats("NY BREAKOUT (London AM range)", n_mfes, n_oc, n_pnls, N)
        print("\n  Direction breakdown:")
        _print_direction_breakdown("NY", ny_signals, n_mfes, n_oc, n_pnls)
        print("\n  Yearly breakdown:")
        _print_yearly_breakdown(ny_signals, n_mfes, n_oc, n_pnls)
    else:
        print("  [NO SIGNALS]")

    # 6. Combined (both sessions)
    if len(london_signals) > 0 and len(ny_signals) > 0:
        print("\n" + "-" * 66)
        print("  COMBINED (London + NY)")
        print("-" * 66)
        all_signals = pd.concat([london_signals, ny_signals], ignore_index=True)
        a_mfes, a_oc, a_pnls = simulate_trades(all_signals, h15, l15, c15, atr, N)
        _print_stats("ALL SESSION BREAKOUTS", a_mfes, a_oc, a_pnls, N)

    # 7. Filter: only tight Asian ranges (compression → expansion)
    if len(london_signals) > 0:
        print("\n" + "-" * 66)
        print("  LONDON BREAKOUT — FILTERED BY RANGE WIDTH")
        print("-" * 66)
        for max_atr_width, label_suffix in [
            (0.5, "Tight range < 0.5 ATR"),
            (0.75, "Medium range < 0.75 ATR"),
            (1.0, "Wide range < 1.0 ATR"),
        ]:
            filtered = london_signals[london_signals["range_width_atr"] < max_atr_width]
            if len(filtered) < 20:
                print(f"\n  [{label_suffix}] Only {len(filtered)} signals, skipping")
                continue
            f_mfes, f_oc, f_pnls = simulate_trades(filtered, h15, l15, c15, atr, N)
            _print_stats(f"LONDON — {label_suffix}", f_mfes, f_oc, f_pnls, N)
            print("  Direction breakdown:")
            _print_direction_breakdown(label_suffix, filtered, f_mfes, f_oc, f_pnls)

    # 8. Filter: range percentile (narrowest vs widest ranges)
    if len(london_signals) > 0:
        print("\n" + "-" * 66)
        print("  LONDON BREAKOUT — RANGE PERCENTILE BUCKETS")
        print("-" * 66)
        rw = london_signals["range_width_atr"]
        for lo_pct, hi_pct in [(0, 25), (25, 50), (50, 75), (75, 100)]:
            lo_val = np.percentile(rw, lo_pct)
            hi_val = np.percentile(rw, hi_pct)
            mask = (rw >= lo_val) & (rw < hi_val) if hi_pct < 100 else (rw >= lo_val)
            bucket = london_signals[mask]
            if len(bucket) < 20:
                continue
            b_mfes, b_oc, b_pnls = simulate_trades(bucket, h15, l15, c15, atr, N)
            n_tp = (b_oc == 1).sum(); n_sl = (b_oc == -1).sum()
            nr = n_tp + n_sl
            wr = n_tp / nr if nr > 0 else float("nan")
            edge = (wr - BE_WR) * 100
            print(f"  P{lo_pct:02d}-P{hi_pct:02d} (range {lo_val:.2f}-{hi_val:.2f} ATR): "
                  f"n={len(bucket):,}  WR={wr*100:.1f}%  edge={edge:+.1f}pp  "
                  f"MFE_med={np.median(b_mfes):.3f}")

    print("\n" + "=" * 66)
    print("  DONE — Path C Step 1 & 2 Complete")
    print("=" * 66)


if __name__ == "__main__":
    run()
