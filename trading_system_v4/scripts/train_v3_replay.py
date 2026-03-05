"""
train_v3_replay.py — Train v3 XGBoost model in REPLAY mode.

This script eliminates the batch/live feature skew by computing HTF features
EXACTLY as the live system would see them (bar-by-bar with partial hours).

The approach:
  1. Load 15m bars (from tick data)
  2. Compute 40 pure-15m features (vectorized, same as batch — these are correct)
  3. For HTF (1h, 4h): build "live-equivalent" features efficiently:
     - Pre-compute COMPLETED higher-TF bars (label=right, closed=right)
     - For each 15m bar, compute the PARTIAL current-period cumulative OHLCV
     - Use sliding window: last N completed bars + 1 partial bar → compute indicators
     - Extract last indicator value as that 15m bar's HTF feature
  4. Add TP/SL labels (same as standard pipeline)
  5. Train XGBoost with purged time-series CV
  6. Report AUC and compare with batch (leaked) and clean (no partial) versions

This is ~O(n * window) instead of O(n²), making it feasible for 176k bars.

Usage:
  python -m trading_system_v4.scripts.train_v3_replay
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.feature_engineering_v3 import (
    compute_v3_features,
    FEATURE_COLUMNS_V3,
    _rsi,
    _ema,
    _adx,
)

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

# Label parameters (same as standard v3)
TP_ATR_MULT = 1.5
SL_ATR_MULT = 1.4
LOOKAHEAD = 100  # bars
SPREAD = 0.0001

# Indicator lookback window — enough for EMA(26), RSI(14), ADX(14), SMA(20)
# We use 100 completed bars + 1 partial to stabilize indicators.
INDICATOR_WINDOW = 100


# ── Helper: compute HTF indicators on a short OHLCV series ───────────────────

def _compute_1h_indicators(ohlcv: pd.DataFrame) -> dict:
    """Compute 1h indicator values from a short OHLCV DataFrame.
    Returns the LAST row's indicator values as a dict.
    """
    if len(ohlcv) < 30:
        return {
            "returns_1h_4": np.nan, "rsi_1h": np.nan, "macd_diff_1h": np.nan,
            "price_to_sma20_1h": np.nan, "di_diff_1h": np.nan,
        }

    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]

    returns_4 = close.pct_change(4).iloc[-1]
    rsi_val = _rsi(close, 14).iloc[-1]

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = ema12 - ema26
    macd_sig = _ema(macd, 9)
    macd_diff = (macd - macd_sig).iloc[-1]

    sma20 = close.rolling(20).mean().iloc[-1]
    p2sma = close.iloc[-1] / sma20 if sma20 != 0 else 1.0

    _, dip, dim = _adx(high, low, close, 14)
    di_diff = (dip - dim).iloc[-1]

    return {
        "returns_1h_4": returns_4,
        "rsi_1h": rsi_val,
        "macd_diff_1h": macd_diff,
        "price_to_sma20_1h": p2sma,
        "di_diff_1h": di_diff,
    }


def _compute_4h_indicators(ohlcv: pd.DataFrame) -> dict:
    """Compute 4h indicator values from a short OHLCV DataFrame.
    Returns the LAST row's indicator values as a dict.
    """
    if len(ohlcv) < 30:
        return {
            "returns_4h_4": np.nan, "rsi_4h": np.nan,
            "macd_diff_4h": np.nan, "price_to_sma20_4h": np.nan,
        }

    close = ohlcv["close"]

    returns_4 = close.pct_change(4).iloc[-1]
    rsi_val = _rsi(close, 14).iloc[-1]

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = ema12 - ema26
    macd_sig = _ema(macd, 9)
    macd_diff = (macd - macd_sig).iloc[-1]

    sma20 = close.rolling(20).mean().iloc[-1]
    p2sma = close.iloc[-1] / sma20 if sma20 != 0 else 1.0

    return {
        "returns_4h_4": returns_4,
        "rsi_4h": rsi_val,
        "macd_diff_4h": macd_diff,
        "price_to_sma20_4h": p2sma,
    }


# ── Build completed HTF bars ─────────────────────────────────────────────────

def _build_completed_bars(df15: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Build completed higher-TF bars using label=right, closed=right (no leak)."""
    return df15.resample(rule, label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()


# ── Build within-period cumulative OHLCV for partial bars ────────────────────

def _build_partial_bars(df15: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    For each 15m bar, compute the cumulative OHLCV within its current
    higher-TF period (the partial bar that would exist in live).

    Uses label=left, closed=left to match the bucket assignment the
    live code uses, then computes cumulative aggregates within each group.
    """
    # Determine which HTF period each 15m bar belongs to (label=left, closed=left)
    # A bar at 08:15 falls into the [08:00, 09:00) bucket labeled 08:00
    period_label = df15.index.floor(rule)

    result = pd.DataFrame(index=df15.index)
    result["period_label"] = period_label

    # Within each period, compute cumulative OHLCV
    groups = df15.groupby(period_label)

    result["partial_open"] = groups["open"].transform("first")
    result["partial_high"] = groups["high"].transform(lambda x: x.expanding().max())
    result["partial_low"] = groups["low"].transform(lambda x: x.expanding().min())
    result["partial_close"] = df15["close"]  # Always the current bar's close
    result["partial_volume"] = groups["volume"].transform(lambda x: x.expanding().sum())

    return result


# ── Build replay HTF features for all 15m bars ───────────────────────────────

def _build_replay_htf_features(
    df15: pd.DataFrame,
    completed: pd.DataFrame,
    partials: pd.DataFrame,
    rule: str,
    indicator_fn,
    progress_label: str = "",
) -> pd.DataFrame:
    """
    For each 15m bar, compute HTF indicator values in replay mode:
      - Take last INDICATOR_WINDOW completed HTF bars
      - Append the partial (current period) bar
      - Compute indicators on this augmented series
      - Extract last values

    Returns a DataFrame with indicator columns indexed by 15m timestamps.
    """
    n = len(df15)
    # Pre-convert completed bars to arrays for fast indexing
    completed_ts = completed.index.values
    completed_open = completed["open"].values
    completed_high = completed["high"].values
    completed_low = completed["low"].values
    completed_close = completed["close"].values
    completed_vol = completed["volume"].values

    # Pre-extract partial bar data
    period_labels = partials["period_label"].values
    partial_open = partials["partial_open"].values
    partial_high = partials["partial_high"].values
    partial_low = partials["partial_low"].values
    partial_close = partials["partial_close"].values
    partial_vol = partials["partial_volume"].values

    results = []

    for i in range(n):
        if (i + 1) % 20000 == 0:
            print(f"  {progress_label}: {i+1:,}/{n:,} ...")

        current_period = period_labels[i]

        # Find completed bars BEFORE the current period
        # (completed bars have label=right, so their timestamps are period END times)
        # The partial period starts at `current_period` (left-labeled)
        # Completed bars ending at or before current_period are available
        mask = completed_ts <= current_period
        n_available = mask.sum()

        if n_available < 30:
            results.append(indicator_fn(pd.DataFrame()))  # Will return NaNs
            continue

        # Take the last INDICATOR_WINDOW completed bars
        start_idx = max(0, n_available - INDICATOR_WINDOW)
        end_idx = n_available

        # Build augmented OHLCV: completed window + partial bar
        w_open = np.append(completed_open[start_idx:end_idx], partial_open[i])
        w_high = np.append(completed_high[start_idx:end_idx], partial_high[i])
        w_low = np.append(completed_low[start_idx:end_idx], partial_low[i])
        w_close = np.append(completed_close[start_idx:end_idx], partial_close[i])
        w_vol = np.append(completed_vol[start_idx:end_idx], partial_vol[i])

        window_df = pd.DataFrame({
            "open": w_open, "high": w_high, "low": w_low,
            "close": w_close, "volume": w_vol,
        })

        results.append(indicator_fn(window_df))

    return pd.DataFrame(results, index=df15.index)


# ── Label engineering ─────────────────────────────────────────────────────────

def _add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add y_long and y_short labels using path-dependent TP/SL simulation."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    atr = df["atr_pct"].values * close  # atr_pct is the v3 feature = ATR(14)/close

    n = len(df)
    y_long = np.full(n, -1, dtype=np.int8)
    y_short = np.full(n, -1, dtype=np.int8)

    for i in range(n - LOOKAHEAD):
        c = close[i]
        a = atr[i]
        if a <= 0 or np.isnan(a):
            continue

        # Long: buy at close+spread, TP above, SL below
        entry_long = c + SPREAD
        tp_long = entry_long + a * TP_ATR_MULT
        sl_long = entry_long - a * SL_ATR_MULT

        # Short: sell at close-spread, TP below, SL above
        entry_short = c - SPREAD
        tp_short = entry_short - a * TP_ATR_MULT
        sl_short = entry_short + a * SL_ATR_MULT

        # Simulate forward
        for j in range(i + 1, min(i + 1 + LOOKAHEAD, n)):
            # Long
            if y_long[i] == -1:
                if high[j] >= tp_long:
                    y_long[i] = 1
                elif low[j] <= sl_long:
                    y_long[i] = 0

            # Short
            if y_short[i] == -1:
                if low[j] <= tp_short:
                    y_short[i] = 1
                elif high[j] >= sl_short:
                    y_short[i] = 0

            if y_long[i] != -1 and y_short[i] != -1:
                break

    df = df.copy()
    df["y_long"] = y_long
    df["y_short"] = y_short
    return df


# ── Train + evaluate ──────────────────────────────────────────────────────────

def _train_evaluate(X: pd.DataFrame, y: np.ndarray, label: str) -> float:
    """Purged walk-forward CV. Returns mean AUC across test folds."""
    # Simple time-based 5-fold CV with purge gap
    n = len(X)
    fold_size = n // 6  # Use 5 folds, first fold is pure train
    purge_gap = 200  # ~2 days of 15m bars

    aucs = []
    for fold_idx in range(1, 6):
        test_start = fold_idx * fold_size
        test_end = min(test_start + fold_size, n)
        train_end = test_start - purge_gap

        if train_end < fold_size or test_end - test_start < 100:
            continue

        X_train = X.iloc[:train_end]
        y_train = y[:train_end]
        X_test = X.iloc[test_start:test_end]
        y_test = y[test_start:test_end]

        pos_rate = y_train.mean()
        if pos_rate <= 0 or pos_rate >= 1:
            continue
        spw = (1 - pos_rate) / pos_rate

        model = XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=10,
            scale_pos_weight=spw,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]

        try:
            auc = roc_auc_score(y_test, proba)
            aucs.append(auc)
        except ValueError:
            continue

    if aucs:
        mean_auc = np.mean(aucs)
        print(f"  {label}:  AUC per fold = {[f'{a:.4f}' for a in aucs]}")
        print(f"  {label}:  Mean AUC = {mean_auc:.4f}  ({len(aucs)} folds)")
        return mean_auc
    else:
        print(f"  {label}:  No valid folds")
        return 0.5


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print("=" * 80)
    print("  V3 REPLAY MODE TRAINING")
    print("  Training on features computed exactly as live would see them")
    print("=" * 80)

    # ── Load and resample tick bars to 15m ────────────────────────────────────
    print("\nLoading tick bars ...")
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
    print(f"  {len(df15):,} 15m bars")

    # ── Compute 15m-only features (vectorized, same for all modes) ────────────
    print("\nComputing 15m base features (vectorized) ...")
    # Use compute_v3_features for the 15m features, then we'll replace HTF
    batch_feats = compute_v3_features(df15)

    # The 15m-only features (first 40 of v3's 50)
    htf_cols = [
        "returns_1h_4", "rsi_1h", "macd_diff_1h", "price_to_sma20_1h", "di_diff_1h",
        "returns_4h_4", "rsi_4h", "macd_diff_4h", "price_to_sma20_4h",
        "trend_alignment",
    ]
    base_15m_cols = [c for c in FEATURE_COLUMNS_V3 if c not in htf_cols]
    base_15m_feats = batch_feats[base_15m_cols].copy()
    print(f"  {len(base_15m_cols)} 15m features computed")

    # ── Build REPLAY HTF features ─────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("Building REPLAY mode 1h features ...")
    print("─" * 60)

    completed_1h = _build_completed_bars(df15, "1h")
    print(f"  Completed 1h bars: {len(completed_1h):,}")

    partials_1h = _build_partial_bars(df15, "1h")

    replay_1h = _build_replay_htf_features(
        df15, completed_1h, partials_1h, "1h",
        _compute_1h_indicators, "1h replay"
    )
    print(f"  1h replay features computed")

    print("\n" + "─" * 60)
    print("Building REPLAY mode 4h features ...")
    print("─" * 60)

    completed_4h = _build_completed_bars(df15, "4h")
    print(f"  Completed 4h bars: {len(completed_4h):,}")

    partials_4h = _build_partial_bars(df15, "4h")

    replay_4h = _build_replay_htf_features(
        df15, completed_4h, partials_4h, "4h",
        _compute_4h_indicators, "4h replay"
    )
    print(f"  4h replay features computed")

    # ── Assemble replay feature matrix ────────────────────────────────────────
    print("\nAssembling replay feature matrix ...")

    replay_feats = base_15m_feats.copy()
    for col in replay_1h.columns:
        replay_feats[col] = replay_1h[col]
    for col in replay_4h.columns:
        replay_feats[col] = replay_4h[col]

    # Compute trend_alignment from replay MACD diffs
    align_15m = (replay_feats["macd_diff"] > 0).astype(int) * 2 - 1
    align_1h = (replay_feats["macd_diff_1h"] > 0).astype(int) * 2 - 1
    align_4h = (replay_feats["macd_diff_4h"] > 0).astype(int) * 2 - 1
    replay_feats["trend_alignment"] = align_15m + align_1h + align_4h

    # Ensure column order matches v3
    replay_feats = replay_feats[FEATURE_COLUMNS_V3]

    # Fill NaN with neutral defaults
    neutral = {
        "returns_1h_4": 0.0, "rsi_1h": 50.0, "macd_diff_1h": 0.0,
        "price_to_sma20_1h": 1.0, "di_diff_1h": 0.0,
        "returns_4h_4": 0.0, "rsi_4h": 50.0, "macd_diff_4h": 0.0,
        "price_to_sma20_4h": 1.0, "trend_alignment": 0.0,
    }
    for col, default in neutral.items():
        replay_feats[col] = replay_feats[col].fillna(default)

    # Drop rows with any remaining NaN (warm-up period)
    valid_mask = replay_feats.notna().all(axis=1)
    replay_feats = replay_feats[valid_mask]
    df15_valid = df15.loc[replay_feats.index]
    batch_feats_valid = batch_feats.loc[replay_feats.index]

    print(f"  Valid rows: {len(replay_feats):,}")

    # ── Add labels ────────────────────────────────────────────────────────────
    print("\nAdding TP/SL labels ...")

    # Need ATR for labeling — get it from the feature matrix
    label_df = df15_valid[["open", "high", "low", "close"]].copy()
    label_df["atr_pct"] = replay_feats["atr_pct"].values
    label_df = _add_labels(label_df)

    # Filter to rows where labels are defined
    has_long = label_df["y_long"] >= 0
    has_short = label_df["y_short"] >= 0
    has_label = has_long & has_short

    print(f"  Labeled rows (long):  {has_long.sum():,}")
    print(f"  Labeled rows (short): {has_short.sum():,}")
    print(f"  Labeled rows (both):  {has_label.sum():,}")

    # ── Build CLEAN features for comparison ───────────────────────────────────
    print("\nBuilding CLEAN (label=right) features for comparison ...")
    # Modify the batch features to use clean HTF
    clean_feats = base_15m_feats.copy()

    # Clean 1h: resample with label=right, closed=right, compute indicators, ffill
    from strategies.feature_engineering_v3 import _resample_ohlcv

    df_1h_clean = df15.resample("1h", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()

    feat_1h_clean = pd.DataFrame(index=df_1h_clean.index)
    feat_1h_clean["returns_1h_4"] = df_1h_clean["close"].pct_change(4)
    feat_1h_clean["rsi_1h"] = _rsi(df_1h_clean["close"], 14)
    ema12_c = _ema(df_1h_clean["close"], 12)
    ema26_c = _ema(df_1h_clean["close"], 26)
    macd_c = ema12_c - ema26_c
    macd_sig_c = _ema(macd_c, 9)
    feat_1h_clean["macd_diff_1h"] = macd_c - macd_sig_c
    sma20_c = df_1h_clean["close"].rolling(20).mean()
    feat_1h_clean["price_to_sma20_1h"] = df_1h_clean["close"] / sma20_c
    _, dip_c, dim_c = _adx(df_1h_clean["high"], df_1h_clean["low"], df_1h_clean["close"], 14)
    feat_1h_clean["di_diff_1h"] = dip_c - dim_c
    feat_1h_clean = feat_1h_clean.reindex(clean_feats.index, method="ffill")

    df_4h_clean = df15.resample("4h", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()

    feat_4h_clean = pd.DataFrame(index=df_4h_clean.index)
    feat_4h_clean["returns_4h_4"] = df_4h_clean["close"].pct_change(4)
    feat_4h_clean["rsi_4h"] = _rsi(df_4h_clean["close"], 14)
    ema12_4c = _ema(df_4h_clean["close"], 12)
    ema26_4c = _ema(df_4h_clean["close"], 26)
    macd_4c = ema12_4c - ema26_4c
    macd_sig_4c = _ema(macd_4c, 9)
    feat_4h_clean["macd_diff_4h"] = macd_4c - macd_sig_4c
    sma20_4c = df_4h_clean["close"].rolling(20).mean()
    feat_4h_clean["price_to_sma20_4h"] = df_4h_clean["close"] / sma20_4c
    feat_4h_clean = feat_4h_clean.reindex(clean_feats.index, method="ffill")

    for col in feat_1h_clean.columns:
        clean_feats[col] = feat_1h_clean[col].fillna(neutral.get(col, 0.0))
    for col in feat_4h_clean.columns:
        clean_feats[col] = feat_4h_clean[col].fillna(neutral.get(col, 0.0))

    align_15m_c = (clean_feats["macd_diff"] > 0).astype(int) * 2 - 1
    align_1h_c = (clean_feats.get("macd_diff_1h", pd.Series(0, index=clean_feats.index)) > 0).astype(int) * 2 - 1
    align_4h_c = (clean_feats.get("macd_diff_4h", pd.Series(0, index=clean_feats.index)) > 0).astype(int) * 2 - 1
    clean_feats["trend_alignment"] = align_15m_c + align_1h_c + align_4h_c

    clean_feats = clean_feats.reindex(columns=FEATURE_COLUMNS_V3)
    for col_name, default in neutral.items():
        if col_name in clean_feats.columns:
            clean_feats[col_name] = clean_feats[col_name].fillna(default)

    clean_valid = clean_feats.loc[replay_feats.index].dropna()

    # ── Train and evaluate all three modes ────────────────────────────────────
    print("\n" + "=" * 80)
    print("  TRAINING AND EVALUATION")
    print("=" * 80)

    # Prepare datasets for each mode
    modes = {
        "BATCH (leaked)": batch_feats_valid,
        "CLEAN (label=right)": clean_feats.loc[replay_feats.index],
        "REPLAY (live-equiv)": replay_feats,
    }

    for direction in ["long", "short"]:
        print(f"\n{'─'*60}")
        print(f"  Direction: {direction.upper()}")
        print(f"{'─'*60}")

        y_col = f"y_{direction}"
        y = label_df[y_col].values
        label_mask = y >= 0

        for mode_name, mode_feats in modes.items():
            X = mode_feats.loc[replay_feats.index]

            # Filter to labeled rows
            X_labeled = X[label_mask]
            y_labeled = y[label_mask]

            # Drop any remaining NaN
            valid = X_labeled.notna().all(axis=1)
            X_final = X_labeled[valid]
            y_final = y_labeled[valid.values]

            if len(y_final) < 1000:
                print(f"\n  {mode_name}: insufficient data ({len(y_final)} rows)")
                continue

            pos_rate = y_final.mean()
            print(f"\n  {mode_name}: {len(y_final):,} samples, pos_rate={pos_rate:.3f}")
            _train_evaluate(X_final, y_final, mode_name)

    # ── Feature diff summary ──────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  FEATURE DIFFERENCE SUMMARY: REPLAY vs BATCH vs CLEAN")
    print(f"{'='*80}")

    print(f"\n  {'Feature':<25} {'Replay-Batch RMSE':>18} {'Replay-Clean RMSE':>18} {'Batch-Clean RMSE':>18}")
    print(f"  {'-'*25} {'-'*18} {'-'*18} {'-'*18}")

    for col in htf_cols:
        b = batch_feats_valid[col].values if col in batch_feats_valid.columns else np.zeros(len(replay_feats))
        r = replay_feats[col].values
        c = clean_feats.loc[replay_feats.index][col].values if col in clean_feats.columns else np.zeros(len(replay_feats))

        rb = np.sqrt(np.nanmean((r - b) ** 2))
        rc = np.sqrt(np.nanmean((r - c) ** 2))
        bc = np.sqrt(np.nanmean((b - c) ** 2))

        print(f"  {col:<25} {rb:>18.6f} {rc:>18.6f} {bc:>18.6f}")

    print(f"\n{'='*80}")
    print("  DONE")
    print(f"{'='*80}")


if __name__ == "__main__":
    run()
