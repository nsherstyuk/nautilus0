"""
test_microstructure_horizon.py — Test tick microstructure with multiple horizons

Key insight: vol_imbalance may predict the NEXT FEW BARS, not the next 25 hours.
Also test the REVERSE (fade) signal — high buy imbalance → exhaustion → SHORT.

Tests:
  1. Multiple TP/SL horizons: 0.3/0.3, 0.5/0.5, 0.75/0.75, 1.0/1.0, 1.5/1.4
  2. Multiple lookahead windows: 10, 20, 50, 100 bars
  3. Forward (momentum) AND reverse (fade/mean-reversion) directions
  4. Next-bar direction (simplest possible test — does imbalance predict next bar?)

Usage:
  python -m trading_system_v4.scripts.test_microstructure_horizon
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"
SPREAD_EST = 0.00010
ZSCORE_WINDOW = 96


def _atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=13, adjust=False).mean()


def aggregate_tick_to_15m(tick: pd.DataFrame) -> pd.DataFrame:
    agg = tick.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("total_volume", "sum"),
        tick_velocity_mean=("tick_velocity", "mean"),
        tick_velocity_max=("tick_velocity", "max"),
        vol_imbalance_sum=("vol_imbalance", "sum"),
        vol_imbalance_mean=("vol_imbalance", "mean"),
        buy_ratio_mean=("buy_ratio", "mean"),
        avg_spread_mean=("avg_spread", "mean"),
        n_tick_bars=("open", "count"),
    ).dropna(subset=["open", "close"])
    return agg


def add_zscores(df: pd.DataFrame) -> pd.DataFrame:
    w = ZSCORE_WINDOW
    for col in ["vol_imbalance_sum", "buy_ratio_mean", "tick_velocity_mean"]:
        rm = df[col].rolling(w, min_periods=w // 2).mean()
        rs = df[col].rolling(w, min_periods=w // 2).std()
        df[f"{col}_z"] = (df[col] - rm) / rs.replace(0, np.nan)
    df["buy_pressure"] = df["buy_ratio_mean"] - 0.5
    rs = df["buy_pressure"].rolling(w, min_periods=w // 2).std()
    df["buy_pressure_z"] = df["buy_pressure"] / rs.replace(0, np.nan)
    return df


# ── Simulation with variable TP/SL/Lookahead ─────────────────────────────────
def simulate(
    bar_indices: np.ndarray,
    directions: np.ndarray,
    h: np.ndarray, l: np.ndarray, c: np.ndarray, atr: np.ndarray,
    n_total: int,
    tp_atr: float, sl_atr: float, lookahead: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (outcome_arr, pnl_arr): outcome +1=TP, -1=SL, 0=expired."""
    outcomes = np.zeros(len(bar_indices), dtype=np.int8)
    pnls = np.zeros(len(bar_indices), dtype=np.float64)

    for k in range(len(bar_indices)):
        pos = bar_indices[k]
        d = directions[k]
        if pos + lookahead >= n_total:
            outcomes[k] = 0
            continue
        cv = c[pos]
        av = atr[pos]
        if not np.isfinite(av) or av <= 0:
            continue

        h_path = h[pos + 1: pos + 1 + lookahead]
        l_path = l[pos + 1: pos + 1 + lookahead]

        if d == 1:
            entry = cv + SPREAD_EST
            tp_lvl = entry + av * tp_atr
            sl_lvl = entry - av * sl_atr
        else:
            entry = cv - SPREAD_EST
            tp_lvl = entry - av * tp_atr
            sl_lvl = entry + av * sl_atr

        out, pnl = 0, 0.0
        for j in range(len(h_path)):
            if d == 1:
                s = l_path[j] <= sl_lvl
                t = h_path[j] >= tp_lvl
            else:
                s = h_path[j] >= sl_lvl
                t = l_path[j] <= tp_lvl
            if s and t:
                out, pnl = -1, -(av * sl_atr)
                break
            if s:
                out, pnl = -1, -(av * sl_atr)
                break
            if t:
                out, pnl = +1, +(av * tp_atr)
                break
        else:
            fp = min(pos + lookahead, n_total - 1)
            pnl = (c[fp] - entry) * d

        outcomes[k] = out
        pnls[k] = pnl

    return outcomes, pnls


# ── Next-bar direction test (simplest possible) ──────────────────────────────
def next_bar_direction_test(df: pd.DataFrame):
    """
    Most fundamental test: does microstructure predict the SIGN of the next bar?
    No TP/SL, no lookahead — just: is next close > current close?
    """
    print("\n" + "=" * 70)
    print("  TEST 0: NEXT-BAR DIRECTION PREDICTION (no TP/SL)")
    print("  Does high vol_imbalance predict next bar direction?")
    print("=" * 70)

    next_return = df["close"].shift(-1) / df["close"] - 1
    imb_z = df["vol_imbalance_sum_z"]
    buy_z = df["buy_pressure_z"]
    vel_z = df["tick_velocity_mean_z"]

    # For each feature, bucket into quintiles and check next-bar direction
    for feat_name, feat in [("vol_imbalance_z", imb_z), ("buy_pressure_z", buy_z),
                             ("tick_velocity_z", vel_z)]:
        valid = feat.notna() & next_return.notna()
        fv = feat[valid]
        nr = next_return[valid]

        print(f"\n  {feat_name}:")
        print(f"  {'Bucket':<15} {'N':>8} {'MeanRet':>12} {'%Up':>8} {'%Down':>8}")
        
        for lo, hi, label in [(-99, -2.0, "z < -2.0"),
                               (-2.0, -1.0, "-2 < z < -1"),
                               (-1.0, 1.0, "-1 < z < +1"),
                               (1.0, 2.0, "+1 < z < +2"),
                               (2.0, 99, "z > +2.0")]:
            mask = (fv >= lo) & (fv < hi)
            if mask.sum() < 50:
                continue
            sub_ret = nr[mask]
            pct_up = (sub_ret > 0).mean() * 100
            pct_dn = (sub_ret < 0).mean() * 100
            print(f"  {label:<15} {mask.sum():>8,} {sub_ret.mean()*10000:>11.3f}bp "
                  f"{pct_up:>7.1f}% {pct_dn:>7.1f}%")

    # Regression: correlation between features and next return
    print(f"\n  Correlations with next-bar return:")
    for feat_name, feat in [("vol_imbalance_z", imb_z), ("buy_pressure_z", buy_z)]:
        valid = feat.notna() & next_return.notna()
        corr = feat[valid].corr(next_return[valid])
        print(f"    {feat_name}: r = {corr:.6f}")

    # Multi-bar forward returns
    print(f"\n  Correlation: vol_imbalance_z → N-bar forward return:")
    for n_bars in [1, 2, 4, 8, 16, 32, 64]:
        fwd = df["close"].shift(-n_bars) / df["close"] - 1
        valid = imb_z.notna() & fwd.notna()
        if valid.sum() < 100:
            continue
        corr = imb_z[valid].corr(fwd[valid])
        # Also check if extreme imbalance (|z|>2) predicts better
        extreme = valid & (imb_z.abs() > 2)
        if extreme.sum() > 50:
            signed = np.sign(imb_z[extreme])
            correct = (signed * fwd[extreme]) > 0
            hit_rate = correct.mean() * 100
        else:
            hit_rate = float("nan")
        print(f"    {n_bars:>3}-bar: r={corr:+.6f}  "
              f"extreme(|z|>2) hit rate={hit_rate:.1f}%  (n={extreme.sum():,})")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print("=" * 70)
    print("  MICROSTRUCTURE HORIZON SWEEP")
    print("  Testing multiple TP/SL, lookahead, and direction modes")
    print("=" * 70)

    # Load + aggregate
    print("\nLoading tick bars ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Aggregating to 15m ...")
    df = aggregate_tick_to_15m(tick)
    df = add_zscores(df)
    df = df.iloc[ZSCORE_WINDOW:]
    print(f"  {len(df):,} bars after warmup")

    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr = _atr14(df).to_numpy()
    N = len(df)

    # ── TEST 0: Raw next-bar direction prediction ─────────────────────────────
    next_bar_direction_test(df)

    # ── TEST 1: Momentum signals (trade WITH imbalance) ───────────────────────
    # Use vol_imbalance z>2.0 as the signal threshold
    imb_z = df["vol_imbalance_sum_z"].to_numpy()
    valid_mask = np.isfinite(imb_z)
    long_mask  = valid_mask & (imb_z > 2.0)
    short_mask = valid_mask & (imb_z < -2.0)
    
    # Momentum: trade in direction of imbalance
    mom_idx = np.where(long_mask | short_mask)[0]
    mom_dir = np.where(imb_z[mom_idx] > 0, 1, -1)
    
    # Fade: trade AGAINST imbalance (mean reversion)
    fade_dir = -mom_dir

    print("\n" + "=" * 70)
    print("  TEST 1: TP/SL HORIZON SWEEP — Vol Imbalance z>2.0")
    print("  Comparing MOMENTUM (trade with flow) vs FADE (trade against flow)")
    print(f"  Signal count: {len(mom_idx):,}")
    print("=" * 70)

    tp_sl_configs = [
        (0.3, 0.3, 10, "Quick scalp"),
        (0.5, 0.5, 20, "Short-term"),
        (0.75, 0.75, 40, "Medium"),
        (1.0, 1.0, 60, "Standard equal"),
        (1.5, 1.4, 100, "Original"),
        (0.5, 1.0, 20, "2:1 R:R short"),
        (1.0, 0.5, 40, "1:2 R:R short"),
    ]

    # Random baseline for each config
    rng = np.random.RandomState(42)
    rand_n = 10000
    rand_valid = np.arange(200, N - 100 - 1)
    rand_idx = rng.choice(rand_valid, size=rand_n, replace=False)
    rand_dir = rng.choice([-1, 1], size=rand_n)

    print(f"\n  {'Config':<25} {'LA':>4}  |  {'Rand WR':>8} |  {'Mom WR':>8} {'Mom Δ':>7} |  "
          f"{'Fade WR':>8} {'Fade Δ':>7}")
    print(f"  {'-'*25} {'-'*4}  |  {'-'*8} |  {'-'*8} {'-'*7} |  {'-'*8} {'-'*7}")

    for tp, sl, la, label in tp_sl_configs:
        be = sl / (sl + tp)
        
        # Random
        r_oc, _ = simulate(rand_idx, rand_dir, h, l, c, atr, N, tp, sl, la)
        r_tp = (r_oc == 1).sum(); r_sl = (r_oc == -1).sum()
        r_wr = r_tp / (r_tp + r_sl) if (r_tp + r_sl) > 0 else float("nan")

        # Momentum
        m_oc, m_pnl = simulate(mom_idx, mom_dir, h, l, c, atr, N, tp, sl, la)
        m_tp = (m_oc == 1).sum(); m_sl = (m_oc == -1).sum()
        m_wr = m_tp / (m_tp + m_sl) if (m_tp + m_sl) > 0 else float("nan")
        m_delta = (m_wr - r_wr) * 100

        # Fade
        f_oc, f_pnl = simulate(mom_idx, fade_dir, h, l, c, atr, N, tp, sl, la)
        f_tp = (f_oc == 1).sum(); f_sl = (f_oc == -1).sum()
        f_wr = f_tp / (f_tp + f_sl) if (f_tp + f_sl) > 0 else float("nan")
        f_delta = (f_wr - r_wr) * 100

        m_mark = " ***" if m_delta > 2 else ""
        f_mark = " ***" if f_delta > 2 else ""
        
        print(f"  TP={tp} SL={sl} {label:<17} {la:>4}  |  "
              f"{r_wr*100:>7.1f}% |  {m_wr*100:>7.1f}% {m_delta:>+6.1f}{m_mark} |  "
              f"{f_wr*100:>7.1f}% {f_delta:>+6.1f}{f_mark}")

    # ── TEST 2: Higher signal thresholds ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("  TEST 2: SIGNAL STRENGTH SWEEP (TP=0.5 SL=0.5 LA=20)")
    print("  Testing if STRONGER imbalance → better prediction")
    print("=" * 70)

    r_oc_ref, _ = simulate(rand_idx, rand_dir, h, l, c, atr, N, 0.5, 0.5, 20)
    r_tp_ref = (r_oc_ref == 1).sum(); r_sl_ref = (r_oc_ref == -1).sum()
    r_wr_ref = r_tp_ref / (r_tp_ref + r_sl_ref)

    print(f"\n  {'Threshold':<15} {'N':>7}  {'Mom WR':>8} {'Δ vs Rand':>10}  "
          f"{'Fade WR':>8} {'Δ vs Rand':>10}")

    for thr in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
        mask = valid_mask & (np.abs(imb_z) > thr)
        idx = np.where(mask)[0]
        if len(idx) < 50:
            print(f"  z>{thr:.1f}      {len(idx):>7}  (insufficient)")
            continue
        d_mom = np.where(imb_z[idx] > 0, 1, -1)
        d_fade = -d_mom

        oc_mom, _ = simulate(idx, d_mom, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_m = (oc_mom == 1).sum(); sl_m = (oc_mom == -1).sum()
        wr_m = tp_m / (tp_m + sl_m) if (tp_m + sl_m) > 0 else float("nan")

        oc_fade, _ = simulate(idx, d_fade, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_f = (oc_fade == 1).sum(); sl_f = (oc_fade == -1).sum()
        wr_f = tp_f / (tp_f + sl_f) if (tp_f + sl_f) > 0 else float("nan")

        dm = (wr_m - r_wr_ref) * 100
        df_ = (wr_f - r_wr_ref) * 100
        mm = " ***" if dm > 2 else ""
        fm = " ***" if df_ > 2 else ""
        print(f"  z>{thr:.1f}       {len(idx):>7,}  {wr_m*100:>7.1f}% {dm:>+9.1f}pp{mm}  "
              f"{wr_f*100:>7.1f}% {df_:>+9.1f}pp{fm}")

    # ── TEST 3: Combined velocity+imbalance with short horizon ────────────────
    print("\n" + "=" * 70)
    print("  TEST 3: VELOCITY + IMBALANCE COMBO (TP=0.5 SL=0.5 LA=20)")
    print("  High activity + directional flow → immediate follow-through?")
    print("=" * 70)

    vel_z = df["tick_velocity_mean_z"].to_numpy()
    
    print(f"\n  {'Config':<35} {'N':>7}  {'Mom WR':>8} {'Δ':>7}  {'Fade WR':>8} {'Δ':>7}")
    for vel_t, imb_t in [(1.0, 1.0), (1.5, 1.5), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0),
                          (1.5, 2.5), (2.0, 3.0)]:
        v_ok = np.isfinite(vel_z) & (vel_z > vel_t)
        i_ok = np.isfinite(imb_z) & (np.abs(imb_z) > imb_t)
        combo = v_ok & i_ok
        idx = np.where(combo)[0]
        if len(idx) < 50:
            print(f"  vel>{vel_t} imb>{imb_t}  {len(idx):>27}  (insufficient)")
            continue
        d_m = np.where(imb_z[idx] > 0, 1, -1)
        d_f = -d_m

        oc_m, _ = simulate(idx, d_m, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_m = (oc_m == 1).sum(); sl_m = (oc_m == -1).sum()
        wr_m = tp_m / (tp_m + sl_m) if (tp_m + sl_m) > 0 else float("nan")

        oc_f, _ = simulate(idx, d_f, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_f = (oc_f == 1).sum(); sl_f = (oc_f == -1).sum()
        wr_f = tp_f / (tp_f + sl_f) if (tp_f + sl_f) > 0 else float("nan")

        dm = (wr_m - r_wr_ref) * 100
        df2 = (wr_f - r_wr_ref) * 100
        mm = " ***" if dm > 2 else ""
        fm = " ***" if df2 > 2 else ""
        print(f"  vel>{vel_t:.1f} + imb>{imb_t:.1f}  {' '*(25-len(f'vel>{vel_t:.1f} + imb>{imb_t:.1f}'))}"
              f"{len(idx):>7,}  {wr_m*100:>7.1f}% {dm:>+6.1f}{mm}  {wr_f*100:>7.1f}% {df2:>+6.1f}{fm}")

    # ── TEST 4: Buy ratio as signal (maybe more direct than vol_imbalance) ────
    print("\n" + "=" * 70)
    print("  TEST 4: BUY RATIO EXTREME (TP=0.5 SL=0.5 LA=20)")
    print("  buy_ratio > 0.55 → buying; < 0.45 → selling")
    print("=" * 70)

    br = df["buy_ratio_mean"].to_numpy()
    print(f"\n  {'Threshold':<20} {'N':>7}  {'Mom WR':>8} {'Δ':>7}  {'Fade WR':>8} {'Δ':>7}")
    for dev in [0.03, 0.05, 0.07, 0.10, 0.15]:
        mask = np.isfinite(br) & (np.abs(br - 0.5) > dev)
        idx = np.where(mask)[0]
        if len(idx) < 50:
            continue
        d_m = np.where(br[idx] > 0.5, 1, -1)
        d_f = -d_m

        oc_m, _ = simulate(idx, d_m, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_m = (oc_m == 1).sum(); sl_m = (oc_m == -1).sum()
        wr_m = tp_m / (tp_m + sl_m) if (tp_m + sl_m) > 0 else float("nan")

        oc_f, _ = simulate(idx, d_f, h, l, c, atr, N, 0.5, 0.5, 20)
        tp_f = (oc_f == 1).sum(); sl_f = (oc_f == -1).sum()
        wr_f = tp_f / (tp_f + sl_f) if (tp_f + sl_f) > 0 else float("nan")

        dm = (wr_m - r_wr_ref) * 100
        df3 = (wr_f - r_wr_ref) * 100
        mm = " ***" if dm > 2 else ""
        fm = " ***" if df3 > 2 else ""
        print(f"  |br-0.5|>{dev:.2f}        {len(idx):>7,}  {wr_m*100:>7.1f}% {dm:>+6.1f}{mm}  "
              f"{wr_f*100:>7.1f}% {df3:>+6.1f}{fm}")

    print(f"\n{'='*70}")
    print(f"  DONE — Microstructure horizon sweep complete")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
