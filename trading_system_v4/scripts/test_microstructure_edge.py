"""
test_microstructure_edge.py — Test tick-bar microstructure as a direct signal

Session breakouts failed the edge test (42.8% WR = identical to random).
This script tests whether tick-bar ORDER FLOW information (vol_imbalance,
buy_ratio, tick_velocity) directly predicts future price direction.

Hypothesis: Volume imbalance and tick velocity from 1000-tick bars, aggregated
at 15m boundaries, reflect institutional order flow that most participants
cannot see. This information should predict short-term direction.

Signal definitions tested:
  A) Volume Imbalance Z-score: when 15m aggregate vol_imbalance deviates >N σ
     from rolling mean → trade in direction of imbalance
  B) Buy Ratio Extreme: when 15m aggregate buy_ratio deviates strongly from 0.5
  C) Tick Velocity Spike + Imbalance: high activity + directional flow
  D) Spread Compression + Imbalance: tight spread + directional flow
     (confident market makers backing a direction)
  E) Composite: all above combined via rank scoring

Usage:
  python -m trading_system_v4.scripts.test_microstructure_edge
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

# Simulation constants
SPREAD_EST = 0.00010
SL_ATR     = 1.4
TP_ATR     = 1.5
LOOKAHEAD  = 100
BE_WR      = SL_ATR / (SL_ATR + TP_ATR)

# Feature aggregation lookback (in 15m bars)
ZSCORE_WINDOW = 96   # 24 hours of 15m bars


def _atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=13, adjust=False).mean()


# ── Aggregate tick-bar microstructure to 15-minute ────────────────────────────
def aggregate_tick_to_15m(tick: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate tick-bar microstructure features to 15m boundaries.
    
    For each 15m period, compute:
      - mean/std of tick_velocity, vol_imbalance, buy_ratio, avg_spread
      - net vol_imbalance (sum)
      - max tick_velocity (peak activity)
      - tick bar count (liquidity indicator)
    """
    agg = tick.resample("15min", label="right", closed="right").agg(
        # OHLCV
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("total_volume", "sum"),
        # Microstructure aggregates
        tick_velocity_mean=("tick_velocity", "mean"),
        tick_velocity_max=("tick_velocity", "max"),
        tick_velocity_std=("tick_velocity", "std"),
        vol_imbalance_sum=("vol_imbalance", "sum"),
        vol_imbalance_mean=("vol_imbalance", "mean"),
        vol_imbalance_std=("vol_imbalance", "std"),
        buy_ratio_mean=("buy_ratio", "mean"),
        buy_ratio_std=("buy_ratio", "std"),
        avg_spread_mean=("avg_spread", "mean"),
        avg_spread_min=("avg_spread", "min"),
        max_spread_max=("max_spread", "max"),
        n_tick_bars=("open", "count"),
    ).dropna(subset=["open", "close"])

    return agg


# ── Z-score computation ──────────────────────────────────────────────────────
def add_zscore_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling z-scores for microstructure features."""
    w = ZSCORE_WINDOW
    
    for col in ["vol_imbalance_sum", "vol_imbalance_mean", "buy_ratio_mean",
                "tick_velocity_mean", "tick_velocity_max", "avg_spread_mean",
                "n_tick_bars"]:
        roll_mean = df[col].rolling(w, min_periods=w//2).mean()
        roll_std  = df[col].rolling(w, min_periods=w//2).std()
        df[f"{col}_z"] = (df[col] - roll_mean) / roll_std.replace(0, np.nan)

    # Signed buy_ratio deviation from 0.5 (positive = net buying)
    df["buy_pressure"] = df["buy_ratio_mean"] - 0.5
    roll_std = df["buy_pressure"].rolling(w, min_periods=w//2).std()
    df["buy_pressure_z"] = df["buy_pressure"] / roll_std.replace(0, np.nan)

    # Spread tightness (negative z = tighter than normal = more confident)
    df["spread_tightness_z"] = -df["avg_spread_mean_z"]

    return df


# ── Signal generators ─────────────────────────────────────────────────────────
def signal_vol_imbalance(df: pd.DataFrame, threshold: float = 2.0) -> pd.DataFrame:
    """
    Signal A: Volume Imbalance Z-score.
    LONG when vol_imbalance_sum z-score > +threshold
    SHORT when vol_imbalance_sum z-score < -threshold
    """
    z = df["vol_imbalance_sum_z"]
    long_mask  = z > threshold
    short_mask = z < -threshold

    signals = []
    for i in range(len(df)):
        if long_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": 1, "bar_idx": i,
                           "z_score": float(z.iloc[i])})
        elif short_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": -1, "bar_idx": i,
                           "z_score": float(z.iloc[i])})
    return pd.DataFrame(signals) if signals else pd.DataFrame()


def signal_buy_ratio(df: pd.DataFrame, threshold: float = 2.0) -> pd.DataFrame:
    """
    Signal B: Buy Ratio Extreme.
    LONG when buy_pressure_z > +threshold (buying dominance)
    SHORT when buy_pressure_z < -threshold (selling dominance)
    """
    z = df["buy_pressure_z"]
    long_mask  = z > threshold
    short_mask = z < -threshold

    signals = []
    for i in range(len(df)):
        if long_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": 1, "bar_idx": i,
                           "z_score": float(z.iloc[i])})
        elif short_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": -1, "bar_idx": i,
                           "z_score": float(z.iloc[i])})
    return pd.DataFrame(signals) if signals else pd.DataFrame()


def signal_velocity_imbalance(
    df: pd.DataFrame,
    vel_threshold: float = 1.5,
    imb_threshold: float = 1.0,
) -> pd.DataFrame:
    """
    Signal C: Tick Velocity Spike + Imbalance.
    Requires BOTH conditions:
      - tick_velocity z-score > vel_threshold (unusual activity)
      - vol_imbalance z-score > imb_threshold or < -imb_threshold (directional)
    Direction determined by imbalance sign.
    """
    vel_z = df["tick_velocity_mean_z"]
    imb_z = df["vol_imbalance_sum_z"]

    active = vel_z > vel_threshold
    long_mask  = active & (imb_z > imb_threshold)
    short_mask = active & (imb_z < -imb_threshold)

    signals = []
    for i in range(len(df)):
        if long_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": 1, "bar_idx": i,
                           "vel_z": float(vel_z.iloc[i]), "imb_z": float(imb_z.iloc[i])})
        elif short_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": -1, "bar_idx": i,
                           "vel_z": float(vel_z.iloc[i]), "imb_z": float(imb_z.iloc[i])})
    return pd.DataFrame(signals) if signals else pd.DataFrame()


def signal_spread_imbalance(
    df: pd.DataFrame,
    spread_threshold: float = 0.5,
    imb_threshold: float = 1.5,
) -> pd.DataFrame:
    """
    Signal D: Tight Spread + Directional Imbalance.
    Tight spread → market makers are confident.
    Combined with directional volume imbalance → informed flow.
    """
    tight = df["spread_tightness_z"] > spread_threshold  # tighter than normal
    imb_z = df["vol_imbalance_sum_z"]

    long_mask  = tight & (imb_z > imb_threshold)
    short_mask = tight & (imb_z < -imb_threshold)

    signals = []
    for i in range(len(df)):
        if long_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": 1, "bar_idx": i,
                           "spread_z": float(df["spread_tightness_z"].iloc[i]),
                           "imb_z": float(imb_z.iloc[i])})
        elif short_mask.iloc[i]:
            signals.append({"timestamp": df.index[i], "direction": -1, "bar_idx": i,
                           "spread_z": float(df["spread_tightness_z"].iloc[i]),
                           "imb_z": float(imb_z.iloc[i])})
    return pd.DataFrame(signals) if signals else pd.DataFrame()


def signal_composite(
    df: pd.DataFrame,
    score_threshold: float = 3.0,
) -> pd.DataFrame:
    """
    Signal E: Composite score from all microstructure indicators.
    Score = abs(vol_imbalance_z) + abs(buy_pressure_z) + tick_velocity_z + spread_tightness_z
    Direction from sign of vol_imbalance_z.
    """
    imb_z  = df["vol_imbalance_sum_z"].fillna(0)
    buy_z  = df["buy_pressure_z"].fillna(0)
    vel_z  = df["tick_velocity_mean_z"].fillna(0)
    spr_z  = df["spread_tightness_z"].fillna(0)

    # Directional strength: all imbalance indicators point same way
    dir_score = imb_z.abs() + buy_z.abs()
    # Activity/confidence: velocity + spread tightness (non-directional boosters)
    activity_score = vel_z.clip(lower=0) + spr_z.clip(lower=0)
    total_score = dir_score + activity_score

    # Direction alignment: imbalance and buy_pressure agree
    aligned = (imb_z * buy_z) > 0  # same sign
    direction = np.sign(imb_z)

    trigger = (total_score > score_threshold) & aligned & (direction != 0)

    signals = []
    for i in range(len(df)):
        if trigger.iloc[i]:
            signals.append({
                "timestamp": df.index[i], "direction": int(direction.iloc[i]),
                "bar_idx": i, "composite_score": float(total_score.iloc[i]),
            })
    return pd.DataFrame(signals) if signals else pd.DataFrame()


# ── Trade simulation ──────────────────────────────────────────────────────────
def simulate_trades(
    sig_df: pd.DataFrame,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_arr: np.ndarray,
    n_total: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (mfe_arr, outcome_arr, pnl_arr)."""
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
            entry = cv + SPREAD_EST
            tp_level = entry + av * TP_ATR
            sl_level = entry - av * SL_ATR
        else:
            entry = cv - SPREAD_EST
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

        # MFE
        if direction == 1:
            sl_arr = l_path <= sl_level
        else:
            sl_arr = h_path >= sl_level
        idx_sl = int(np.argmax(sl_arr)) if np.any(sl_arr) else len(h_path)
        if idx_sl > 0:
            mfe = ((np.max(h_path[:idx_sl]) - entry) / av if direction == 1
                   else (entry - np.min(l_path[:idx_sl])) / av)
        else:
            mfe = 0.0

        mfes.append(float(mfe))
        outcomes.append(out)
        pnls.append(float(pnl))

    return np.array(mfes), np.array(outcomes), np.array(pnls)


def _print_stats(label: str, mfes, outcomes, pnls, n_bars: int, show_mfe=True):
    n = len(outcomes)
    if n == 0:
        print(f"\n  [{label}] No trades")
        return
    n_tp = (outcomes == 1).sum()
    n_sl = (outcomes == -1).sum()
    nr = n_tp + n_sl
    wr = n_tp / nr if nr > 0 else float("nan")
    edge = (wr - BE_WR) * 100

    marker = "*** EDGE ***" if edge > 2 else "[Marginal]" if edge > 0 else "[No edge]"
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Signals: {n:,}  ({n/n_bars*100:.2f}% of bars)")
    print(f"  TP: {n_tp:,} ({n_tp/n*100:.1f}%)  SL: {n_sl:,} ({n_sl/n*100:.1f}%)")
    print(f"  WR: {wr*100:.1f}%  (BE: {BE_WR*100:.1f}%)  Edge: {edge:+.1f} pp  {marker}")
    print(f"  Mean PnL: {pnls.mean():.5f}  Total: {pnls.sum():.1f} ATR")
    if show_mfe:
        print(f"  MFE: mean={mfes.mean():.3f}  median={np.median(mfes):.3f}")

    # Direction split
    if "direction" in label.lower():
        return
    sig_count = min(n, len(outcomes))
    return wr, edge


def _yearly(sig_df, mfes, outcomes, pnls):
    if len(sig_df) == 0:
        return
    ts = pd.DatetimeIndex(sig_df["timestamp"].values[:len(outcomes)])
    years = ts.year
    print(f"\n  {'Year':>6} {'N':>7} {'WR%':>6} {'Edge':>7} {'MnPnL':>10}")
    for y in sorted(years.unique()):
        mask = years == y
        o = outcomes[mask]; p = pnls[mask]
        ntp = (o == 1).sum(); nsl = (o == -1).sum()
        nr = ntp + nsl
        wr = ntp / nr if nr > 0 else float("nan")
        edge = (wr - BE_WR) * 100
        print(f"  {y:>6} {mask.sum():>7,} {wr*100:>6.1f} {edge:>+7.1f} {p.mean():>10.5f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print("=" * 70)
    print("  TICK MICROSTRUCTURE DIRECT SIGNAL — EDGE TEST")
    print("  Path C — Pivot: microstructure as signal source")
    print("=" * 70)

    # 1. Load + aggregate
    print(f"\nLoading tick bars ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Aggregating to 15m with microstructure features ...")
    df = aggregate_tick_to_15m(tick)
    print(f"  {len(df):,} 15m bars with microstructure")

    # Add z-scores
    print("Computing z-scores ...")
    df = add_zscore_features(df)

    # Remove warmup period
    df = df.iloc[ZSCORE_WINDOW:]
    print(f"  {len(df):,} bars after warmup removal")

    # Numpy arrays
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr = _atr14(df).to_numpy()
    N = len(df)

    # Fix bar_idx for simulation (need sequential indices)
    # Since we sliced df, bar_idx in signals should be 0-based into this df
    # We'll handle by reindexing

    # 2. Random baseline
    print("\nRandom baseline ...")
    rng = np.random.RandomState(42)
    n_rand = 10000
    valid = np.arange(200, N - LOOKAHEAD - 1)
    rid = rng.choice(valid, size=n_rand, replace=False)
    rand_df = pd.DataFrame({"bar_idx": rid, "direction": rng.choice([-1, 1], size=n_rand),
                            "timestamp": [df.index[i] for i in rid]})
    r_m, r_o, r_p = simulate_trades(rand_df, h, l, c, atr, N)
    _print_stats("RANDOM BASELINE (n=10k)", r_m, r_o, r_p, N)

    # 3. Test all signals
    signal_tests = [
        # (name, generator_func, kwargs_list)
        ("A: Vol Imbalance z>1.5", signal_vol_imbalance, {"threshold": 1.5}),
        ("A: Vol Imbalance z>2.0", signal_vol_imbalance, {"threshold": 2.0}),
        ("A: Vol Imbalance z>2.5", signal_vol_imbalance, {"threshold": 2.5}),
        ("A: Vol Imbalance z>3.0", signal_vol_imbalance, {"threshold": 3.0}),
        ("B: Buy Ratio z>1.5", signal_buy_ratio, {"threshold": 1.5}),
        ("B: Buy Ratio z>2.0", signal_buy_ratio, {"threshold": 2.0}),
        ("B: Buy Ratio z>2.5", signal_buy_ratio, {"threshold": 2.5}),
        ("C: Velocity+Imbalance (vel>1.5, imb>1.0)", signal_velocity_imbalance,
         {"vel_threshold": 1.5, "imb_threshold": 1.0}),
        ("C: Velocity+Imbalance (vel>2.0, imb>1.5)", signal_velocity_imbalance,
         {"vel_threshold": 2.0, "imb_threshold": 1.5}),
        ("D: Tight Spread+Imbalance (spr>0.5, imb>1.5)", signal_spread_imbalance,
         {"spread_threshold": 0.5, "imb_threshold": 1.5}),
        ("D: Tight Spread+Imbalance (spr>1.0, imb>1.5)", signal_spread_imbalance,
         {"spread_threshold": 1.0, "imb_threshold": 1.5}),
        ("E: Composite score>3.0", signal_composite, {"score_threshold": 3.0}),
        ("E: Composite score>4.0", signal_composite, {"score_threshold": 4.0}),
        ("E: Composite score>5.0", signal_composite, {"score_threshold": 5.0}),
        ("E: Composite score>6.0", signal_composite, {"score_threshold": 6.0}),
    ]

    results = []
    for name, gen_func, kwargs in signal_tests:
        print(f"\n{'-'*70}")
        print(f"  Testing: {name}")
        sig = gen_func(df, **kwargs)
        if len(sig) < 20:
            print(f"  Only {len(sig)} signals — insufficient")
            continue

        m, o, p = simulate_trades(sig, h, l, c, atr, N)
        if len(o) == 0:
            continue

        ret = _print_stats(name, m, o, p, N)
        n_tp = (o == 1).sum(); n_sl = (o == -1).sum()
        nr = n_tp + n_sl
        wr = n_tp / nr if nr > 0 else float("nan")
        edge = (wr - BE_WR) * 100

        results.append({"name": name, "n": len(o), "wr": wr, "edge": edge,
                        "mean_pnl": p.mean(), "mfe_med": np.median(m)})

        # Yearly breakdown for promising signals
        if edge > 1:
            _yearly(sig, m, o, p)

            # Direction split
            for d, dn in [(1, "LONG"), (-1, "SHORT")]:
                dm = sig["direction"].values[:len(o)] == d
                if dm.sum() < 10:
                    continue
                dtp = (o[dm] == 1).sum(); dsl = (o[dm] == -1).sum()
                dnr = dtp + dsl
                dwr = dtp / dnr if dnr > 0 else float("nan")
                de = (dwr - BE_WR) * 100
                print(f"    {dn:5s}: n={dm.sum():>5,}  WR={dwr*100:5.1f}%  edge={de:+5.1f}pp")

    # Summary table
    if results:
        print(f"\n\n{'='*70}")
        print(f"  SUMMARY TABLE")
        print(f"{'='*70}")
        print(f"  {'Signal':<50} {'N':>7} {'WR%':>6} {'Edge':>7} {'MnPnL':>10}")
        print(f"  {'-'*50} {'-'*7} {'-'*6} {'-'*7} {'-'*10}")
        for r in sorted(results, key=lambda x: x["edge"], reverse=True):
            marker = " ***" if r["edge"] > 2 else ""
            print(f"  {r['name']:<50} {r['n']:>7,} {r['wr']*100:>6.1f} "
                  f"{r['edge']:>+7.1f} {r['mean_pnl']:>10.5f}{marker}")
        print(f"  {'RANDOM BASELINE':<50} {len(r_o):>7,} "
              f"{(r_o==1).sum()/((r_o==1).sum()+(r_o==-1).sum())*100:>6.1f} "
              f"{((r_o==1).sum()/((r_o==1).sum()+(r_o==-1).sum()) - BE_WR)*100:>+7.1f} "
              f"{r_p.mean():>10.5f}")

    print(f"\n{'='*70}")
    print(f"  DONE — Microstructure edge test complete")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
