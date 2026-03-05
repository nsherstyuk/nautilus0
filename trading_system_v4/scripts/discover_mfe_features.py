"""
Feature discovery for MFE meta-labeling.

Goal:
- Find candidate features with stable predictive relationship to y_meta (MFE in ATR)
- Use time-aware folds to avoid optimistic leakage-like conclusions
- Output ranked report for next feature-engineering iterations

Usage:
  python -m trading_system_v4.scripts.discover_mfe_features
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

LOOKAHEAD_BARS = 100
EMBARGO_BARS = 5

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
INPUT_FILE = DATA_DIR / "meta_labeled_1000t_mfe.parquet"
OUT_CSV = DATA_DIR / "mfe_feature_discovery_report.csv"
OUT_MD = DATA_DIR / "mfe_feature_discovery_report.md"


def _safe_corr(a: pd.Series, b: pd.Series, method: str = "pearson") -> float:
    frame = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 30:
        return 0.0
    if frame["a"].std() == 0 or frame["b"].std() == 0:
        return 0.0
    return float(frame["a"].corr(frame["b"], method=method))


def _add_candidate_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    if {"tick_velocity_ratio", "spread_ratio"}.issubset(d.columns):
        d["edge_vel_over_spread"] = d["tick_velocity_ratio"] / (d["spread_ratio"] + 1e-6)

    if {"vol_imbalance", "tick_velocity_ratio"}.issubset(d.columns):
        d["edge_imbalance_x_velocity"] = d["vol_imbalance"] * d["tick_velocity_ratio"]

    if {"vol_imbalance_sma5", "vol_imbalance_sma50"}.issubset(d.columns):
        d["edge_imbalance_regime_delta"] = d["vol_imbalance_sma5"] - d["vol_imbalance_sma50"]

    if {"ret_10", "ret_50"}.issubset(d.columns):
        d["edge_trend_accel"] = d["ret_10"] - d["ret_50"]

    if {"dist_to_high_10", "dist_to_low_10", "signal"}.issubset(d.columns):
        d["edge_breakout_distance"] = np.where(
            d["signal"] == 1,
            -d["dist_to_high_10"],
            d["dist_to_low_10"],
        )

    if {"volatility_regime", "signal", "ret_10"}.issubset(d.columns):
        d["edge_regime_trend_align"] = d["volatility_regime"] * d["signal"] * d["ret_10"]

    return d


def _fold_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    tscv = TimeSeriesSplit(n_splits=5)
    values: list[float] = []

    idx = np.arange(len(x))
    for train_idx, test_idx in tscv.split(idx):
        corr = _safe_corr(x.iloc[test_idx], y.iloc[test_idx], method="spearman")
        values.append(corr)

    if not values:
        return 0.0, 1.0

    mean_v = float(np.mean(values))
    std_v = float(np.std(values))
    return mean_v, std_v


def run() -> None:
    if not INPUT_FILE.exists():
        print(f"[ERROR] Input not found: {INPUT_FILE}")
        return

    print(f"Loading: {INPUT_FILE}")
    df = pd.read_parquet(INPUT_FILE)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.replace([np.inf, -np.inf], np.nan)

    if "y_meta" not in df.columns:
        print("[ERROR] Missing y_meta column")
        return

    df = _add_candidate_features(df)

    target = df["y_meta"].astype(float)
    hit_target = (target >= 1.5).astype(float)

    exclude = {"timestamp", "y_meta"}
    feature_cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

    rows = []
    for col in feature_cols:
        x = df[col].astype(float)

        pearson = _safe_corr(x, target, method="pearson")
        spearman = _safe_corr(x, target, method="spearman")
        hit_corr = _safe_corr(x, hit_target, method="spearman")

        fold_mean, fold_std = _fold_spearman(x, target)
        stability = max(0.0, 1.0 - (fold_std / (abs(fold_mean) + 1e-6)))

        q10 = float(np.nanquantile(x, 0.10))
        q90 = float(np.nanquantile(x, 0.90))
        low_mask = x <= q10
        high_mask = x >= q90

        high_mean = float(target[high_mask].mean()) if high_mask.any() else np.nan
        low_mean = float(target[low_mask].mean()) if low_mask.any() else np.nan
        spread_mfe = high_mean - low_mean if np.isfinite(high_mean) and np.isfinite(low_mean) else 0.0

        high_hit = float(hit_target[high_mask].mean()) if high_mask.any() else np.nan
        low_hit = float(hit_target[low_mask].mean()) if low_mask.any() else np.nan
        spread_hit = high_hit - low_hit if np.isfinite(high_hit) and np.isfinite(low_hit) else 0.0

        edge_score = (abs(fold_mean) * 0.5) + (abs(spread_mfe) * 0.3) + (abs(spread_hit) * 0.2)
        edge_score *= (0.5 + 0.5 * stability)

        rows.append(
            {
                "feature": col,
                "pearson_mfe": pearson,
                "spearman_mfe": spearman,
                "spearman_hit_1p5": hit_corr,
                "fold_spearman_mean": fold_mean,
                "fold_spearman_std": fold_std,
                "stability": stability,
                "mfe_spread_q90_q10": spread_mfe,
                "hit_spread_q90_q10": spread_hit,
                "edge_score": edge_score,
            }
        )

    report = pd.DataFrame(rows).sort_values("edge_score", ascending=False).reset_index(drop=True)
    report.to_csv(OUT_CSV, index=False)

    top = report.head(20)

    lines = [
        "# MFE Feature Discovery Report",
        "",
        f"Rows: {len(df):,}",
        f"Features evaluated: {len(report):,}",
        "",
        "## Top 20 Features by edge_score",
        "",
    ]

    for _, r in top.iterrows():
        lines.append(
            f"- {r['feature']}: edge={r['edge_score']:.4f}, "
            f"fold_ic={r['fold_spearman_mean']:.4f}±{r['fold_spearman_std']:.4f}, "
            f"mfe_spread={r['mfe_spread_q90_q10']:.4f}, hit_spread={r['hit_spread_q90_q10']:.4f}"
        )

    lines.extend([
        "",
        "## Candidate engineered features included",
        "",
        "- edge_vel_over_spread",
        "- edge_imbalance_x_velocity",
        "- edge_imbalance_regime_delta",
        "- edge_trend_accel",
        "- edge_breakout_distance",
        "- edge_regime_trend_align",
    ])

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved CSV: {OUT_CSV}")
    print(f"Saved MD : {OUT_MD}")
    print("Top 10:")
    print(report[["feature", "edge_score", "fold_spearman_mean", "mfe_spread_q90_q10"]].head(10).to_string(index=False))


if __name__ == "__main__":
    run()
