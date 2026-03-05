"""
test_v2_signal_edge.py — Do v2 and v3 ML signals have edge vs random?

Resamples tick bars → 15m OHLCV, runs both production ML models
(v2 RF-40 and v3 XGB-50), generates signals at production thresholds,
then measures TP/SL win rate and MFE distribution vs a random-entry baseline.

Signal logic (mirrors ml_strategy_mtf_v2_entry_confirmed.py):
    confidence = max(P(class_0), P(class_1))
    direction  = LONG if prediction==1 else SHORT
    entry when confidence >= direction-specific threshold

Usage:
  python -m trading_system_v4.scripts.test_v2_signal_edge
"""
from __future__ import annotations

import warnings
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# Add repo root so we can import from strategies/
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

SPREAD_EST    = 0.00010
LOOKAHEAD_15M = 100   # 100 × 15m = 25 hours


# ── Feature engineering imports ───────────────────────────────────────────────

def _load_rf40_features(df15: pd.DataFrame) -> pd.DataFrame:
    from strategies.feature_engineering_v2_rf40 import compute_rf40_features
    return compute_rf40_features(df15)


def _load_v3_features(df15: pd.DataFrame) -> pd.DataFrame:
    from strategies.feature_engineering_v3 import compute_v3_features
    return compute_v3_features(df15)


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signals(
    feats: pd.DataFrame,
    model,
    threshold_long: float,
    threshold_short: float,
) -> pd.DataFrame:
    """Return signal DataFrame. Mirrors live strategy signal logic exactly:
      confidence = max(P(class_0), P(class_1))
      LONG  when predicted class==1 AND P(class_1) >= threshold_long
      SHORT when predicted class==0 AND P(class_0) >= threshold_short
    """
    X = feats.astype(float).replace([np.inf, -np.inf], np.nan)
    valid = X.notna().all(axis=1)
    X_clean = X[valid]

    if len(X_clean) == 0:
        return pd.DataFrame(columns=["timestamp", "direction", "confidence"])

    proba = model.predict_proba(X_clean.values)   # (N, 2): [P(class_0), P(class_1)]
    p0, p1 = proba[:, 0], proba[:, 1]
    predicted_class = (p1 >= p0).astype(int)      # argmax: 1=LONG, 0=SHORT

    long_mask  = (predicted_class == 1) & (p1 >= threshold_long)
    short_mask = (predicted_class == 0) & (p0 >= threshold_short)

    ts_arr = X_clean.index.to_numpy()
    rows = []
    for i in range(len(ts_arr)):
        if long_mask[i]:
            rows.append({"timestamp": ts_arr[i], "direction":  1, "confidence": float(p1[i])})
        elif short_mask[i]:
            rows.append({"timestamp": ts_arr[i], "direction": -1, "confidence": float(p0[i])})

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["timestamp", "direction", "confidence"])


# ── Trade simulation ──────────────────────────────────────────────────────────

def simulate(
    sig_df: pd.DataFrame,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    atr: np.ndarray,
    bar_pos_map: dict,
    n_total: int,
    sl_atr: float,
    tp_atr: float,
    lookahead: int = LOOKAHEAD_15M,
    spread: float = SPREAD_EST,
):
    mfe_list, outcome_list, pnl_list = [], [], []

    for _, row in sig_df.iterrows():
        pos = int(bar_pos_map.get(row["timestamp"], -1))
        if pos < 0 or pos + lookahead >= n_total:
            continue

        direction = int(row["direction"])
        cv = c[pos]
        av = atr[pos]
        if not np.isfinite(av) or av <= 0:
            continue

        h_path = h[pos + 1 : pos + 1 + lookahead]
        l_path = l[pos + 1 : pos + 1 + lookahead]

        if direction == 1:
            entry    = cv + spread
            tp_level = entry + av * tp_atr
            sl_level = entry - av * sl_atr
        else:
            entry    = cv - spread
            tp_level = entry - av * tp_atr
            sl_level = entry + av * sl_atr

        out, pnl = 0, 0.0
        for j in range(lookahead):
            if direction == 1:
                sl_hit = l_path[j] <= sl_level
                tp_hit = h_path[j] >= tp_level
            else:
                sl_hit = h_path[j] >= sl_level
                tp_hit = l_path[j] <= tp_level

            if sl_hit:
                out, pnl = -1, -(av * sl_atr)
                break
            if tp_hit:
                out, pnl = +1, +(av * tp_atr)
                break
        else:
            out = 0
            pnl = (c[pos + lookahead] - entry) * direction

        # MFE before first SL
        sl_arr = (l_path <= sl_level) if direction == 1 else (h_path >= sl_level)
        idx_sl = int(np.argmax(sl_arr)) if np.any(sl_arr) else lookahead
        if direction == 1:
            mfe = (np.max(h_path[:idx_sl]) - entry) / av if idx_sl > 0 else 0.0
        else:
            mfe = (entry - np.min(l_path[:idx_sl])) / av if idx_sl > 0 else 0.0

        mfe_list.append(float(mfe))
        outcome_list.append(out)
        pnl_list.append(float(pnl))

    return np.array(mfe_list), np.array(outcome_list), np.array(pnl_list)


def _stats(label, mfes, outcomes, pnls, sl_atr, tp_atr, n_bars):
    n_tp = (outcomes == 1).sum()
    n_sl = (outcomes == -1).sum()
    n    = len(outcomes)
    wr   = n_tp / (n_tp + n_sl) if (n_tp + n_sl) > 0 else float("nan")
    be   = sl_atr / (tp_atr + sl_atr)
    edge = (wr - be) * 100

    print(f"\n{'='*66}")
    print(f"  {label}")
    print(f"{'='*66}")
    print(f"  Signals      : {n:,}  ({n/n_bars*100:.2f}% of bars)")
    print(f"  TP @ {tp_atr}ATR  : {n_tp:,}  ({n_tp/n*100:.1f}%)   "
          f"SL @ {sl_atr}ATR: {n_sl:,}  ({n_sl/n*100:.1f}%)")
    print(f"  Win rate     : {wr*100:.1f}%   break-even: {be*100:.1f}%")
    print(f"  Edge         : {edge:+.1f} pp  {'[ABOVE RANDOM]' if edge > 1 else '[No edge]'}")
    print(f"  Mean PnL/trade: {pnls.mean():.4f} ATR   Total PnL: {pnls.sum():.1f} ATR")
    print(f"  MFE  mean={mfes.mean():.3f}  median={np.median(mfes):.3f}  std={mfes.std():.3f}")
    for t in [0.5, 1.0, 1.5, 2.0, 3.0]:
        print(f"    MFE >= {t:.1f} ATR: {(mfes >= t).mean()*100:.1f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    # 1. Load + resample
    print("Loading tick bars ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Resampling to 15m ...")
    df15 = tick.resample("15min", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "total_volume": "sum"}
    ).dropna().rename(columns={"total_volume": "volume"})
    print(f"  {len(df15):,} 15m bars  ({df15.index.min().date()} — {df15.index.max().date()})")

    h15 = df15["high"].to_numpy()
    l15 = df15["low"].to_numpy()
    c15 = df15["close"].to_numpy()
    bar_pos_map = {ts: i for i, ts in enumerate(df15.index)}
    N = len(df15)

    # Compute raw ATR for random baseline
    tr_raw = np.maximum(h15 - l15, np.maximum(
        np.abs(h15 - np.roll(c15, 1)), np.abs(l15 - np.roll(c15, 1))
    ))
    atr_raw = pd.Series(tr_raw).rolling(14).mean().to_numpy()

    # 2. Random baseline
    print("\nRunning random baseline ...")
    rng = np.random.RandomState(42)
    valid_range = np.arange(200, N - LOOKAHEAD_15M - 1)
    n_rand = 10_000
    rand_idx = rng.choice(valid_range, size=n_rand, replace=False)
    rand_dir = rng.choice([-1, 1], size=n_rand)
    rand_sig = pd.DataFrame({
        "timestamp": [df15.index[i] for i in rand_idx],
        "direction": rand_dir, "confidence": 0.5,
    })
    r_mfes, r_oc, r_pnls = simulate(rand_sig, h15, l15, c15, atr_raw, bar_pos_map, N, 1.4, 1.5)
    _stats("RANDOM BASELINE (n=10k, SL=1.4, TP=1.5)", r_mfes, r_oc, r_pnls, 1.4, 1.5, N)

    # 3. v2 RF-40 model
    model_v2_path = ROOT / "models" / "ml_model_mtf_backup.pkl"
    print(f"\n{'--'*33}")
    print(f"MODEL A: v2 RF-40  ({model_v2_path.name})")
    print(f"{'--'*33}")
    if model_v2_path.exists():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model_v2 = joblib.load(model_v2_path)

        print("Computing RF-40 features ...")
        feats_v2 = _load_rf40_features(df15)
        atr_v2   = feats_v2["atr"].reindex(df15.index).to_numpy()

        # Print confidence distribution
        X_a = feats_v2.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            proba_a = model_v2.predict_proba(X_a.values)
        conf_a = np.maximum(proba_a[:, 0], proba_a[:, 1])
        print(f"  Confidence distribution: min={conf_a.min():.3f}  p50={np.median(conf_a):.3f}  "
              f"p75={np.percentile(conf_a,75):.3f}  p90={np.percentile(conf_a,90):.3f}  max={conf_a.max():.3f}")

        # Test multiple thresholds
        for (thr_l, thr_s, sl_m, tp_m) in [
            (0.75, 0.65, 1.8, 1.4),
            (0.60, 0.60, 1.8, 1.4),
            (0.55, 0.55, 1.8, 1.4),
            (0.52, 0.52, 1.0, 1.5),
        ]:
            sig = generate_signals(feats_v2, model_v2, thr_l, thr_s)
            label = f"v2 RF40 · thr_L={thr_l} thr_S={thr_s}  SL={sl_m} TP={tp_m}"
            if len(sig) < 10:
                print(f"\n  [No signals] {label}  (conf max={conf_a.max():.3f} < threshold)")
                continue
            mfes, oc, pnls = simulate(sig, h15, l15, c15, atr_v2, bar_pos_map, N, sl_m, tp_m)
            _stats(label, mfes, oc, pnls, sl_m, tp_m, N)
    else:
        print(f"  [SKIP] {model_v2_path} not found")

    # 4. v3 XGB-50 model
    model_v3_path = ROOT / "models" / "ml_model_mtf_v3_xgb.pkl"
    print(f"\n{'--'*33}")
    print(f"MODEL B: v3 XGB-50  ({model_v3_path.name})")
    print(f"{'--'*33}")
    if model_v3_path.exists():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model_v3 = joblib.load(model_v3_path)

        print("Computing v3 features (1h/4h resampling included) ...")
        feats_v3 = _load_v3_features(df15)
        atr_v3   = feats_v3["atr_pct"].reindex(df15.index).to_numpy() * c15

        # Confidence distribution
        X_b = feats_v3.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            proba_b = model_v3.predict_proba(X_b.values)
        conf_b = np.maximum(proba_b[:, 0], proba_b[:, 1])
        p1_b = proba_b[:, 1]
        pct_long  = (p1_b >= proba_b[:, 0]).mean() * 100
        print(f"  Confidence distribution: min={conf_b.min():.3f}  p50={np.median(conf_b):.3f}  "
              f"p75={np.percentile(conf_b,75):.3f}  p90={np.percentile(conf_b,90):.3f}  max={conf_b.max():.3f}")
        print(f"  Direction split: {pct_long:.1f}% LONG predictions  {100-pct_long:.1f}% SHORT")

        for (thr_l, thr_s, sl_m, tp_m) in [
            (0.70, 0.70, 1.4, 1.5),
            (0.65, 0.65, 1.4, 1.5),
            (0.60, 0.60, 1.4, 1.5),
            (0.55, 0.55, 1.4, 1.5),
        ]:
            sig = generate_signals(feats_v3, model_v3, thr_l, thr_s)
            label = f"v3 XGB  · thr={thr_l}  SL={sl_m} TP={tp_m}"
            if len(sig) < 10:
                print(f"\n  [No signals] {label}")
                continue
            mfes, oc, pnls = simulate(sig, h15, l15, c15, atr_v3, bar_pos_map, N, sl_m, tp_m)
            _stats(label, mfes, oc, pnls, sl_m, tp_m, N)

        # Detailed threshold sweep for v3
        print(f"\n{'--'*33}")
        print("  Threshold sweep (v3 XGB, SL=1.4 TP=1.5)")
        print(f"  break-even win rate = {1.4/(1.5+1.4)*100:.1f}%")
        print(f"  {'Thr':>5} {'N':>7} {'Rate%':>7} {'WR%':>7} {'Edge pp':>8} {'MnPnL':>8} {'MFE>1.5':>8}")

        # pre-fetch signals for all thresholds from pre-computed proba
        ts_arr_b  = X_b.index.to_numpy()
        pred_b    = (p1_b >= proba_b[:, 0]).astype(int)

        for thr in [0.50, 0.52, 0.54, 0.55, 0.58, 0.60, 0.63, 0.65, 0.70, 0.75]:
            lm = (pred_b == 1) & (p1_b      >= thr)
            sm = (pred_b == 0) & (proba_b[:, 0] >= thr)
            dirs = np.where(lm, 1, np.where(sm, -1, 0))
            used = dirs != 0
            if used.sum() < 10:
                print(f"  {thr:.2f}   < 10 signals")
                continue
            sig_t = pd.DataFrame({"timestamp": ts_arr_b[used], "direction": dirs[used], "confidence": conf_b[used]})
            mfes_t, oc_t, pnls_t = simulate(sig_t, h15, l15, c15, atr_v3, bar_pos_map, N, 1.4, 1.5)
            n_t = len(oc_t)
            tp_t = (oc_t == 1).sum(); sl_t = (oc_t == -1).sum()
            wr_t = tp_t/(tp_t+sl_t) if (tp_t+sl_t) > 0 else float("nan")
            be   = 1.4/(1.5+1.4)
            print(f"  {thr:.2f}  {n_t:>7,}  {n_t/N*100:>6.2f}%  {wr_t*100:>6.1f}%  "
                  f"{(wr_t-be)*100:>+8.1f}  {pnls_t.mean():>8.4f}  {(mfes_t>=1.5).mean()*100:>7.1f}%")
    else:
        print(f"  [SKIP] {model_v3_path} not found")

    print("\nDone.")


if __name__ == "__main__":
    run()
