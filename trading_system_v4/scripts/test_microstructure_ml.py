"""
test_microstructure_ml.py — XGBoost on raw tick microstructure features

FINAL DEFINITIVE TEST: Can an XGBoost model find ANY nonlinear combination
of tick-bar microstructure features that predicts TP/SL outcome on EURUSD 15m?

If this fails with 170k+ training samples, there is NOTHING in this data.

Features (all from tick bars aggregated to 15m, NO lookahead):
  - vol_imbalance: sum, mean, z-score
  - buy_ratio: mean, z-score, deviation from 0.5
  - tick_velocity: mean, max, z-score
  - avg_spread: mean, z-score
  - n_tick_bars: count, z-score
  - Rolling features: 4-bar, 8-bar, 16-bar lookbacks
  - Time features: hour, day_of_week, is_london, is_ny

Target: y = 1 if TP (1.5 ATR) hit before SL (1.4 ATR), else 0

Evaluation: Purged 5-fold time-series CV (same as production pipeline)

Usage:
  python -m trading_system_v4.scripts.test_microstructure_ml
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

SPREAD_EST = 0.00010
SL_ATR     = 1.4
TP_ATR     = 1.5
LOOKAHEAD  = 100
BE_WR      = SL_ATR / (SL_ATR + TP_ATR)
ZSCORE_W   = 96
PURGE_GAP  = 120  # bars gap between train/test in CV


def _atr14(h, l, c):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)),
                                       np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).ewm(com=13, adjust=False).mean().to_numpy()
    return atr


def build_dataset():
    """Build labeled dataset: features from tick microstructure, target from TP/SL sim."""
    print("Loading tick bars ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Aggregating to 15m ...")
    df = tick.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("total_volume", "sum"),
        tick_velocity_mean=("tick_velocity", "mean"),
        tick_velocity_max=("tick_velocity", "max"),
        tick_velocity_std=("tick_velocity", "std"),
        vol_imbalance_sum=("vol_imbalance", "sum"),
        vol_imbalance_mean=("vol_imbalance", "mean"),
        buy_ratio_mean=("buy_ratio", "mean"),
        buy_ratio_std=("buy_ratio", "std"),
        avg_spread_mean=("avg_spread", "mean"),
        avg_spread_min=("avg_spread", "min"),
        max_spread_max=("max_spread", "max"),
        n_tick_bars=("open", "count"),
    ).dropna(subset=["open", "close"])

    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr = _atr14(h, l, c)
    N = len(df)
    print(f"  {N:,} 15m bars")

    # ── Features ──────────────────────────────────────────────────────────────
    print("Engineering features ...")
    feat = pd.DataFrame(index=df.index)

    # Raw microstructure (current bar)
    feat["vol_imb_sum"] = df["vol_imbalance_sum"]
    feat["vol_imb_mean"] = df["vol_imbalance_mean"]
    feat["buy_ratio"] = df["buy_ratio_mean"]
    feat["buy_ratio_std"] = df["buy_ratio_std"]
    feat["buy_pressure"] = df["buy_ratio_mean"] - 0.5
    feat["tick_vel_mean"] = df["tick_velocity_mean"]
    feat["tick_vel_max"] = df["tick_velocity_max"]
    feat["tick_vel_std"] = df["tick_velocity_std"]
    feat["avg_spread"] = df["avg_spread_mean"]
    feat["min_spread"] = df["avg_spread_min"]
    feat["max_spread"] = df["max_spread_max"]
    feat["spread_range"] = df["max_spread_max"] - df["avg_spread_min"]
    feat["n_tick_bars"] = df["n_tick_bars"]
    feat["volume"] = df["volume"]

    # Bar price features (non-indicator)
    feat["bar_range"] = (h - l) / atr  # in ATR units
    feat["bar_body"] = np.abs(c - df["open"].to_numpy()) / atr
    feat["bar_body_signed"] = (c - df["open"].to_numpy()) / atr
    feat["upper_wick"] = (h - np.maximum(c, df["open"].to_numpy())) / atr
    feat["lower_wick"] = (np.minimum(c, df["open"].to_numpy()) - l) / atr
    feat["close_position"] = (c - l) / (h - l + 1e-10)  # 0=low, 1=high

    # Z-scores (rolling normalization)
    for col in ["vol_imb_sum", "buy_pressure", "tick_vel_mean", "avg_spread",
                "n_tick_bars", "volume", "bar_range"]:
        rm = feat[col].rolling(ZSCORE_W, min_periods=ZSCORE_W // 2).mean()
        rs = feat[col].rolling(ZSCORE_W, min_periods=ZSCORE_W // 2).std()
        feat[f"{col}_z"] = (feat[col] - rm) / rs.replace(0, np.nan)

    # Rolling lookback features
    for w in [4, 8, 16]:
        feat[f"vol_imb_sum_ma{w}"] = feat["vol_imb_sum"].rolling(w).mean()
        feat[f"buy_pressure_ma{w}"] = feat["buy_pressure"].rolling(w).mean()
        feat[f"tick_vel_mean_ma{w}"] = feat["tick_vel_mean"].rolling(w).mean()
        feat[f"avg_spread_ma{w}"] = feat["avg_spread"].rolling(w).mean()
        feat[f"volume_ma{w}"] = feat["volume"].rolling(w).mean()
        feat[f"bar_range_ma{w}"] = feat["bar_range"].rolling(w).mean()
        # Change from rolling (momentum/acceleration)
        feat[f"vol_imb_chg{w}"] = feat["vol_imb_sum"] - feat[f"vol_imb_sum_ma{w}"]
        feat[f"tick_vel_chg{w}"] = feat["tick_vel_mean"] - feat[f"tick_vel_mean_ma{w}"]

    # Time features
    feat["hour"] = df.index.hour
    feat["minute"] = df.index.minute
    feat["dow"] = df.index.dayofweek
    feat["is_london"] = ((feat["hour"] >= 7) & (feat["hour"] < 16)).astype(int)
    feat["is_ny"] = ((feat["hour"] >= 13) & (feat["hour"] < 21)).astype(int)
    feat["is_overlap"] = ((feat["hour"] >= 13) & (feat["hour"] < 16)).astype(int)
    feat["is_asian"] = ((feat["hour"] >= 0) & (feat["hour"] < 7)).astype(int)

    # Return features (past only!)
    for n in [1, 2, 4, 8]:
        feat[f"ret_{n}"] = (c / np.roll(c, n) - 1)
        feat[f"ret_{n}"].iloc[:n] = np.nan

    print(f"  {len(feat.columns)} features")

    # ── Labels (TP/SL simulation) ─────────────────────────────────────────────
    print("Simulating TP/SL for labels ...")
    y = np.full(N, np.nan)

    for i in range(N - LOOKAHEAD):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # LONG scenario
        entry_l = c[i] + SPREAD_EST
        tp_l = entry_l + a * TP_ATR
        sl_l = entry_l - a * SL_ATR

        h_path = h[i + 1: i + 1 + LOOKAHEAD]
        l_path = l[i + 1: i + 1 + LOOKAHEAD]

        # Check LONG TP/SL
        sl_hit_l = np.where(l_path <= sl_l)[0]
        tp_hit_l = np.where(h_path >= tp_l)[0]
        i_sl_l = sl_hit_l[0] if len(sl_hit_l) > 0 else LOOKAHEAD
        i_tp_l = tp_hit_l[0] if len(tp_hit_l) > 0 else LOOKAHEAD
        long_win = 1.0 if (i_tp_l < i_sl_l and i_tp_l < LOOKAHEAD) else 0.0

        # SHORT scenario
        entry_s = c[i] - SPREAD_EST
        tp_s = entry_s - a * TP_ATR
        sl_s = entry_s + a * SL_ATR

        sl_hit_s = np.where(h_path >= sl_s)[0]
        tp_hit_s = np.where(l_path <= tp_s)[0]
        i_sl_s = sl_hit_s[0] if len(sl_hit_s) > 0 else LOOKAHEAD
        i_tp_s = tp_hit_s[0] if len(tp_hit_s) > 0 else LOOKAHEAD
        short_win = 1.0 if (i_tp_s < i_sl_s and i_tp_s < LOOKAHEAD) else 0.0

        # Label: 1 if EITHER direction has TP hit (best case)
        # This tests if microstructure can predict ANYTHING about trade quality
        y[i] = max(long_win, short_win)

    # Also create direction-specific labels
    y_long = np.full(N, np.nan)
    y_short = np.full(N, np.nan)
    for i in range(N - LOOKAHEAD):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        entry_l = c[i] + SPREAD_EST
        tp_l = entry_l + a * TP_ATR
        sl_l = entry_l - a * SL_ATR
        h_path = h[i + 1: i + 1 + LOOKAHEAD]
        l_path = l[i + 1: i + 1 + LOOKAHEAD]
        sl_hit = np.where(l_path <= sl_l)[0]
        tp_hit = np.where(h_path >= tp_l)[0]
        i_sl = sl_hit[0] if len(sl_hit) > 0 else LOOKAHEAD
        i_tp = tp_hit[0] if len(tp_hit) > 0 else LOOKAHEAD
        y_long[i] = 1.0 if (i_tp < i_sl and i_tp < LOOKAHEAD) else 0.0

        entry_s = c[i] - SPREAD_EST
        tp_s = entry_s - a * TP_ATR
        sl_s = entry_s + a * SL_ATR
        sl_hit = np.where(h_path >= sl_s)[0]
        tp_hit = np.where(l_path <= tp_s)[0]
        i_sl = sl_hit[0] if len(sl_hit) > 0 else LOOKAHEAD
        i_tp = tp_hit[0] if len(tp_hit) > 0 else LOOKAHEAD
        y_short[i] = 1.0 if (i_tp < i_sl and i_tp < LOOKAHEAD) else 0.0

    return feat, y, y_long, y_short, df.index


def purged_cv(X, y, n_splits=5):
    """Purged time-series CV: train on earlier, test on later with gap."""
    n = len(X)
    fold_size = n // (n_splits + 1)

    results = []
    for fold in range(n_splits):
        train_end = fold_size * (fold + 1)
        test_start = train_end + PURGE_GAP
        test_end = test_start + fold_size
        if test_end > n:
            break

        X_tr, y_tr = X[:train_end], y[:train_end]
        X_te, y_te = X[test_start:test_end], y[test_start:test_end]

        # Remove NaN targets
        valid_tr = np.isfinite(y_tr)
        valid_te = np.isfinite(y_te)
        X_tr, y_tr = X_tr[valid_tr], y_tr[valid_tr]
        X_te, y_te = X_te[valid_te], y_te[valid_te]

        if len(X_tr) < 1000 or len(X_te) < 200:
            continue

        model = XGBClassifier(
            max_depth=4, learning_rate=0.05, n_estimators=300,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
            eval_metric="logloss", verbosity=0, random_state=42,
        )
        model.fit(X_tr, y_tr)

        prob = model.predict_proba(X_te)[:, 1]
        pred = (prob >= 0.5).astype(int)

        auc = roc_auc_score(y_te, prob)
        acc = accuracy_score(y_te, pred)
        base_rate = y_te.mean()

        # Win rate at various thresholds
        wr_info = []
        for thr in [0.5, 0.55, 0.60, 0.65, 0.70]:
            mask = prob >= thr
            if mask.sum() > 20:
                wr = y_te[mask].mean()
                wr_info.append(f"thr≥{thr:.2f}:{wr*100:.1f}%({mask.sum():,})")

        results.append({
            "fold": fold, "train_n": len(y_tr), "test_n": len(y_te),
            "auc": auc, "acc": acc, "base_rate": base_rate,
            "wr_info": "  ".join(wr_info),
        })

    return results


def run():
    print("=" * 70)
    print("  XGBOOST ON RAW MICROSTRUCTURE — FINAL DEFINITIVE TEST")
    print("  If this fails, there is nothing in tick microstructure for EURUSD")
    print("=" * 70)

    feat, y_any, y_long, y_short, timestamps = build_dataset()

    # Remove NaN features
    feature_cols = feat.columns.tolist()
    X = feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Skip warmup
    start = ZSCORE_W + 20
    X = X[start:]
    y_any = y_any[start:]
    y_long = y_long[start:]
    y_short = y_short[start:]
    timestamps = timestamps[start:]

    valid = np.isfinite(y_any)
    print(f"\n  Valid samples: {valid.sum():,} / {len(y_any):,}")
    print(f"  Base rate (any dir TP): {y_any[valid].mean()*100:.1f}%")
    print(f"  Base rate (LONG TP):    {y_long[valid].mean()*100:.1f}%")
    print(f"  Base rate (SHORT TP):   {y_short[valid].mean()*100:.1f}%")
    print(f"  Features: {len(feature_cols)}")

    # ── Task 1: Predict if ANY direction TP hits ──────────────────────────────
    print(f"\n{'='*70}")
    print(f"  TASK 1: Predict if TP hits in ANY direction")
    print(f"  (Tests if microstructure predicts volatility/opportunity)")
    print(f"{'='*70}")

    results1 = purged_cv(X, y_any)
    for r in results1:
        print(f"  Fold {r['fold']}: AUC={r['auc']:.4f}  Acc={r['acc']*100:.1f}%  "
              f"BaseRate={r['base_rate']*100:.1f}%  train={r['train_n']:,}  test={r['test_n']:,}")
        print(f"    {r['wr_info']}")
    if results1:
        avg_auc = np.mean([r["auc"] for r in results1])
        avg_acc = np.mean([r["acc"] for r in results1])
        avg_br  = np.mean([r["base_rate"] for r in results1])
        print(f"\n  AVERAGE: AUC={avg_auc:.4f}  Acc={avg_acc*100:.1f}%  BaseRate={avg_br*100:.1f}%")

    # ── Task 2: Predict LONG TP hit ───────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  TASK 2: Predict LONG TP hit (direction-specific)")
    print(f"{'='*70}")

    results2 = purged_cv(X, y_long)
    for r in results2:
        print(f"  Fold {r['fold']}: AUC={r['auc']:.4f}  Acc={r['acc']*100:.1f}%  "
              f"BaseRate={r['base_rate']*100:.1f}%  {r['wr_info']}")
    if results2:
        avg_auc = np.mean([r["auc"] for r in results2])
        print(f"\n  AVERAGE AUC: {avg_auc:.4f}")

    # ── Task 3: Predict SHORT TP hit ──────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  TASK 3: Predict SHORT TP hit (direction-specific)")
    print(f"{'='*70}")

    results3 = purged_cv(X, y_short)
    for r in results3:
        print(f"  Fold {r['fold']}: AUC={r['auc']:.4f}  Acc={r['acc']*100:.1f}%  "
              f"BaseRate={r['base_rate']*100:.1f}%  {r['wr_info']}")
    if results3:
        avg_auc = np.mean([r["auc"] for r in results3])
        print(f"\n  AVERAGE AUC: {avg_auc:.4f}")

    # ── Feature importance (from last fold) ───────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  TOP 15 FEATURE IMPORTANCES (Task 2, last fold)")
    print(f"{'='*70}")
    # Retrain on all valid data for importance
    valid = np.isfinite(y_long)
    model_full = XGBClassifier(
        max_depth=4, learning_rate=0.05, n_estimators=300,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
        eval_metric="logloss", verbosity=0, random_state=42,
    )
    model_full.fit(X[valid], y_long[valid])
    imp = model_full.feature_importances_
    top_idx = np.argsort(imp)[::-1][:15]
    for rank, idx in enumerate(top_idx, 1):
        print(f"  {rank:>2}. {feature_cols[idx]:<30s}  {imp[idx]:.4f}")

    # ── Conclusion ────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    all_aucs = ([r["auc"] for r in results1] +
                [r["auc"] for r in results2] +
                [r["auc"] for r in results3])
    max_auc = max(all_aucs) if all_aucs else 0
    mean_auc = np.mean(all_aucs) if all_aucs else 0

    if max_auc < 0.52:
        print("  VERDICT: ZERO PREDICTIVE POWER")
        print("  XGBoost with 70+ microstructure features cannot predict TP/SL")
        print("  outcome on EURUSD 15m. Max AUC across all tasks and folds:")
        print(f"  {max_auc:.4f} (0.50 = random)")
    elif max_auc < 0.55:
        print("  VERDICT: MARGINAL / QUESTIONABLE")
        print(f"  Max AUC: {max_auc:.4f}  Mean: {mean_auc:.4f}")
        print("  Might have signal but likely not tradeable after costs")
    else:
        print("  VERDICT: POTENTIAL SIGNAL DETECTED")
        print(f"  Max AUC: {max_auc:.4f}  Mean: {mean_auc:.4f}")
        print("  Worth investigating further!")

    print(f"{'='*70}")


if __name__ == "__main__":
    run()
