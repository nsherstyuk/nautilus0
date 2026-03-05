"""
audit_xauusd_1h.py — Comprehensive XAUUSD Signal Audit (1h timeframe)

Same pipeline as audit_xauusd_15m.py but at 1-hour resolution.
Hypothesis: gold may have stronger trend signal at 1h due to lower noise.

  A. Resample 1000-tick bars → 1h OHLCV (label='right', closed='right')
  B. Feature engineering: 37 standard + gold-specific features
  C. ATR-based TP/SL labeling (TP=1.5×ATR, SL=1.4×ATR, lookahead=50 bars)
  D. XGBoost 4-fold purged walk-forward CV → LONG AUC, SHORT AUC
  E. Session breakout test (Asian→London, London→NY)
  F. Microstructure ML test (63 features)
  G. Summary verdict

Comparison baselines:
  EURUSD 15m AUC  = 0.519  (zero edge)
  XAUUSD 15m AUC  = 0.526  (marginal / noise)

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\audit_xauusd_1h.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "xauusd_1000t_bars.parquet"

# ── Labeling parameters ──────────────────────────────────────────────────────
TP_ATR     = 1.5
SL_ATR     = 1.4
LOOKAHEAD  = 50        # 50 × 1h = ~50 hours ≈ 2 trading days
SPREAD_EST = 0.30      # ~$0.30 gold spread (USD/oz)
BE_WR      = SL_ATR / (SL_ATR + TP_ATR)   # ~48.3% break-even

# ── CV parameters ─────────────────────────────────────────────────────────────
PURGE_GAP  = 60        # 60h gap between train/test (~2.5 trading days)
ZSCORE_W   = 24        # 24 hours for z-score normalisation

TIMEFRAME  = "1h"
TF_LABEL   = "1h"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _atr14(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """ATR(14) using Wilder's smoothing."""
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)),
                                       np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(com=13, adjust=False).mean().to_numpy()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX normalised to [0, 1]."""
    h, l, c = df['high'].astype(float), df['low'].astype(float), df['close'].astype(float)
    up_move = h - h.shift(1)
    down_move = l.shift(1) - l
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_w = tr.ewm(com=period - 1, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(com=period - 1, adjust=False).mean() / 100


def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A: Resample tick bars → 1h
# ══════════════════════════════════════════════════════════════════════════════

def load_and_resample():
    print("=" * 70)
    print(f"  SECTION A: LOAD & RESAMPLE XAUUSD TICK BARS → {TF_LABEL}")
    print("=" * 70)

    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")
    print(f"  Tick bars loaded: {len(tick):,}")
    print(f"  Range: {tick.index.min()} → {tick.index.max()}")

    df = tick.resample(TIMEFRAME, label="right", closed="right").agg(
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

    print(f"  {TF_LABEL} bars: {len(df):,}")
    print(f"  Range: {df.index.min()} → {df.index.max()}")
    print(f"  Gold price range: ${df['close'].min():.2f} → ${df['close'].max():.2f}")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B: Feature engineering
# ══════════════════════════════════════════════════════════════════════════════

def add_standard_features(df: pd.DataFrame) -> pd.DataFrame:
    """37 standard + gold-specific features."""
    print("\n" + "=" * 70)
    print("  SECTION B: FEATURE ENGINEERING")
    print("=" * 70)

    eps = 1e-10
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    bar_range = (h - l).clip(lower=eps)

    feat = pd.DataFrame(index=df.index)

    # ── 1. Price action ──────────────────────────────────────────────────
    feat['body_ratio']  = (c - o) / bar_range
    feat['upper_wick']  = (h - np.maximum(o, c)) / bar_range
    feat['lower_wick']  = (np.minimum(o, c) - l) / bar_range

    # ── 2. Momentum / returns ────────────────────────────────────────────
    feat['return_1']  = c.pct_change(1, fill_method=None)
    feat['return_3']  = c.pct_change(3, fill_method=None)    # 3h
    feat['return_6']  = c.pct_change(6, fill_method=None)    # 6h (quarter day)
    feat['return_12'] = c.pct_change(12, fill_method=None)   # 12h (half day)
    feat['return_24'] = c.pct_change(24, fill_method=None)   # 24h (full day)

    # ── 3. Volatility ────────────────────────────────────────────────────
    atr_5  = _atr_series(df, 5)
    atr_14 = _atr_series(df, 14)
    feat['atr_ratio'] = atr_5 / (atr_14 + eps)
    feat['atr_norm']  = atr_14 / (c + eps)

    vol_5  = c.pct_change().rolling(5).std()
    vol_20 = c.pct_change().rolling(20).std()
    feat['vol_5']     = vol_5
    feat['vol_20']    = vol_20
    feat['vol_ratio'] = vol_5 / (vol_20 + eps)

    # ── 4. Trend context (EMA) ──────────────────────────────────────────
    ema5   = _ema(c, 5)
    ema20  = _ema(c, 20)
    ema50  = _ema(c, 50)
    ema200 = _ema(c, 200)
    feat['ema_ratio_5_20']  = ema5 / (ema20 + eps) - 1
    feat['close_vs_ema20']  = c / (ema20 + eps) - 1
    feat['close_vs_ema50']  = c / (ema50 + eps) - 1
    feat['close_vs_ema200'] = c / (ema200 + eps) - 1

    # ── 5. Oscillators ──────────────────────────────────────────────────
    feat['rsi_14'] = _rsi(c, 14) / 100 - 0.5
    feat['adx_14'] = _adx(df, 14)

    # ── 6. Session / time ────────────────────────────────────────────────
    hour = df.index.hour
    feat['hour_sin']     = np.sin(2 * math.pi * hour / 24)
    feat['hour_cos']     = np.cos(2 * math.pi * hour / 24)
    dow = df.index.dayofweek
    feat['dow_sin']      = np.sin(2 * math.pi * dow / 5)
    feat['dow_cos']      = np.cos(2 * math.pi * dow / 5)
    feat['is_london']    = ((hour >= 7) & (hour < 16)).astype(float)
    feat['is_ny']        = ((hour >= 13) & (hour < 21)).astype(float)
    feat['is_overlap']   = ((hour >= 13) & (hour < 16)).astype(float)

    # ── 7. Regime ────────────────────────────────────────────────────────
    atr_mean50 = atr_14.rolling(50).mean()
    feat['vol_regime'] = atr_14 / (atr_mean50 + eps)

    high_20 = h.rolling(20).max()
    low_20  = l.rolling(20).min()
    feat['range_position'] = (c - low_20) / (high_20 - low_20 + eps)

    # ── 8. Pattern / structure ───────────────────────────────────────────
    feat['return_max_10'] = c.pct_change().rolling(10).max()
    feat['return_min_10'] = c.pct_change().rolling(10).min()

    _bull = (c > c.shift(1))
    _bear = (c < c.shift(1))
    _bull_grp = (~_bull).cumsum()
    _bear_grp = (~_bear).cumsum()
    bull_run = _bull.astype(int).groupby(_bull_grp).cumsum()
    bear_run = _bear.astype(int).groupby(_bear_grp).cumsum()
    feat['consecutive_up_bars']   = bull_run.clip(upper=10) / 10
    feat['consecutive_down_bars'] = bear_run.clip(upper=10) / 10

    feat['dist_to_20bar_high'] = (high_20 - c) / (atr_14 + eps)
    feat['dist_to_20bar_low']  = (c - low_20) / (atr_14 + eps)

    # ── 9. GOLD-SPECIFIC: swing_proximity ────────────────────────────────
    # Confirmed swing high/low using 10-bar window, shifted 5 bars (no lookahead)
    swing_high = h.rolling(10, center=False).max().shift(5)
    swing_low  = l.rolling(10, center=False).min().shift(5)
    feat['swing_proximity_high'] = (swing_high - c) / (atr_14 + eps)
    feat['swing_proximity_low']  = (c - swing_low) / (atr_14 + eps)

    # ── 10. GOLD-SPECIFIC: gold_session flag ─────────────────────────────
    feat['gold_session'] = ((hour >= 13) & (hour < 17)).astype(float)
    feat['is_asian'] = ((hour >= 0) & (hour < 7)).astype(float)

    n_features = len(feat.columns)
    print(f"  Standard + gold-specific features: {n_features}")
    return feat


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION C: ATR-based TP/SL labeling
# ══════════════════════════════════════════════════════════════════════════════

def label_tp_sl(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print(f"  SECTION C: ATR-BASED TP/SL LABELING ({TF_LABEL})")
    print(f"  TP={TP_ATR}×ATR  SL={SL_ATR}×ATR  Lookahead={LOOKAHEAD} bars  Spread=${SPREAD_EST}")
    print("=" * 70)

    h = df['high'].to_numpy()
    l = df['low'].to_numpy()
    c = df['close'].to_numpy()
    atr = _atr14(h, l, c)
    N = len(df)

    y_long  = np.full(N, np.nan)
    y_short = np.full(N, np.nan)

    for i in range(N - LOOKAHEAD):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        h_path = h[i + 1: i + 1 + LOOKAHEAD]
        l_path = l[i + 1: i + 1 + LOOKAHEAD]

        # LONG
        entry_l = c[i] + SPREAD_EST
        tp_l = entry_l + a * TP_ATR
        sl_l = entry_l - a * SL_ATR
        sl_hit_l = np.where(l_path <= sl_l)[0]
        tp_hit_l = np.where(h_path >= tp_l)[0]
        i_sl_l = sl_hit_l[0] if len(sl_hit_l) > 0 else LOOKAHEAD
        i_tp_l = tp_hit_l[0] if len(tp_hit_l) > 0 else LOOKAHEAD
        y_long[i] = 1.0 if (i_tp_l < i_sl_l and i_tp_l < LOOKAHEAD) else 0.0

        # SHORT
        entry_s = c[i] - SPREAD_EST
        tp_s = entry_s - a * TP_ATR
        sl_s = entry_s + a * SL_ATR
        sl_hit_s = np.where(h_path >= sl_s)[0]
        tp_hit_s = np.where(l_path <= tp_s)[0]
        i_sl_s = sl_hit_s[0] if len(sl_hit_s) > 0 else LOOKAHEAD
        i_tp_s = tp_hit_s[0] if len(tp_hit_s) > 0 else LOOKAHEAD
        y_short[i] = 1.0 if (i_tp_s < i_sl_s and i_tp_s < LOOKAHEAD) else 0.0

    valid = np.isfinite(y_long)
    n_valid = valid.sum()
    long_wr = y_long[valid].mean()
    short_wr = y_short[valid].mean()
    print(f"  Valid labeled bars: {n_valid:,} / {N:,}")
    print(f"  Long  base rate (TP hit): {long_wr * 100:.1f}%")
    print(f"  Short base rate (TP hit): {short_wr * 100:.1f}%")
    print(f"  Break-even WR:            {BE_WR * 100:.1f}%")

    return y_long, y_short, atr


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION D: XGBoost purged walk-forward CV
# ══════════════════════════════════════════════════════════════════════════════

def purged_cv(X: np.ndarray, y: np.ndarray, n_splits: int = 4,
              label: str = ""):
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

        valid_tr = np.isfinite(y_tr)
        valid_te = np.isfinite(y_te)
        X_tr, y_tr = X_tr[valid_tr], y_tr[valid_tr]
        X_te, y_te = X_te[valid_te], y_te[valid_te]

        if len(X_tr) < 500 or len(X_te) < 200:
            print(f"  Fold {fold + 1}: SKIPPED (train={len(X_tr)}, test={len(X_te)})")
            continue

        pos_count = (y_tr == 1).sum()
        neg_count = (y_tr == 0).sum()
        scale_weight = neg_count / (pos_count + 1e-10)

        model = XGBClassifier(
            max_depth=4, learning_rate=0.05, n_estimators=300,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
            eval_metric="logloss", verbosity=0, random_state=42,
            scale_pos_weight=scale_weight,
        )
        model.fit(X_tr, y_tr)

        prob = model.predict_proba(X_te)[:, 1]
        pred = (prob >= 0.5).astype(int)

        auc = roc_auc_score(y_te, prob)
        acc = accuracy_score(y_te, pred)
        base_rate = y_te.mean()

        wr_info = []
        for thr in [0.50, 0.55, 0.60, 0.65]:
            mask = prob >= thr
            if mask.sum() > 20:
                wr = y_te[mask].mean()
                wr_info.append(f"≥{thr:.2f}:{wr * 100:.1f}%({mask.sum():,})")

        results.append({
            "fold": fold + 1, "train_n": len(y_tr), "test_n": len(y_te),
            "auc": auc, "acc": acc, "base_rate": base_rate,
            "wr_info": "  ".join(wr_info), "model": model,
        })

        print(f"  Fold {fold + 1}: AUC={auc:.4f}  Acc={acc * 100:.1f}%  "
              f"BR={base_rate * 100:.1f}%  train={len(y_tr):,}  test={len(y_te):,}")
        if wr_info:
            print(f"    WR: {' | '.join(wr_info)}")

    if results:
        avg_auc = np.mean([r["auc"] for r in results])
        print(f"\n  → {label} AVERAGE AUC: {avg_auc:.4f}  "
              f"(baselines: random=0.50, EURUSD-15m=0.519, XAUUSD-15m=0.526)")
        edge_pp = (avg_auc - 0.5) * 100
        if avg_auc < 0.52:
            print(f"    VERDICT: No edge ({edge_pp:+.1f}pp from random)")
        elif avg_auc < 0.54:
            print(f"    VERDICT: Marginal ({edge_pp:+.1f}pp) — likely noise")
        else:
            print(f"    VERDICT: Potential edge ({edge_pp:+.1f}pp) — investigate further!")

    return results


def run_xgb_cv(feat: pd.DataFrame, y_long: np.ndarray, y_short: np.ndarray):
    print("\n" + "=" * 70)
    print(f"  SECTION D: XGBOOST PURGED WALK-FORWARD CV ({TF_LABEL} STANDARD FEATURES)")
    print("=" * 70)

    feature_cols = feat.columns.tolist()
    X = feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    warmup = 200
    X = X[warmup:]
    y_l = y_long[warmup:]
    y_s = y_short[warmup:]

    print(f"\n  Samples after warmup: {len(X):,}")
    valid_l = np.isfinite(y_l)
    valid_s = np.isfinite(y_s)
    print(f"  LONG  valid: {valid_l.sum():,}  base rate: {y_l[valid_l].mean() * 100:.1f}%")
    print(f"  SHORT valid: {valid_s.sum():,}  base rate: {y_s[valid_s].mean() * 100:.1f}%")

    print(f"\n--- LONG direction ---")
    results_long = purged_cv(X, y_l, n_splits=4, label="LONG")

    print(f"\n--- SHORT direction ---")
    results_short = purged_cv(X, y_s, n_splits=4, label="SHORT")

    if results_long:
        model = results_long[-1]["model"]
        imp = model.feature_importances_
        top_idx = np.argsort(imp)[::-1][:15]
        print(f"\n  TOP 15 FEATURES (LONG, last fold):")
        for rank, idx in enumerate(top_idx, 1):
            print(f"    {rank:>2}. {feature_cols[idx]:<30s}  {imp[idx]:.4f}")

    return results_long, results_short, feature_cols


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION E: Session breakout test
# ══════════════════════════════════════════════════════════════════════════════

def session_breakout_test(df: pd.DataFrame, y_long: np.ndarray, y_short: np.ndarray):
    print("\n" + "=" * 70)
    print(f"  SECTION E: GOLD SESSION BREAKOUT TEST ({TF_LABEL})")
    print("=" * 70)

    hour = df.index.hour
    valid = np.isfinite(y_long)

    sessions = {
        "Asian (00-07)":       (hour >= 0) & (hour < 7),
        "London (07-13)":      (hour >= 7) & (hour < 13),
        "NY (13-22)":          (hour >= 13) & (hour < 22),
        "London open (07-10)": (hour >= 7) & (hour < 10),
        "Overlap (13-16)":     (hour >= 13) & (hour < 16),
        "NY close (19-22)":    (hour >= 19) & (hour < 22),
    }

    print(f"\n  {'Session':<25s} {'Bars':>7s} {'Long WR':>8s} {'Short WR':>9s} "
          f"{'Long Edge':>10s} {'Short Edge':>11s}")
    print("  " + "-" * 75)

    session_results = {}
    for name, mask in sessions.items():
        m = np.asarray(mask) & valid
        n = m.sum()
        if n < 50:
            continue
        lwr = y_long[m].mean()
        swr = y_short[m].mean()
        l_edge = (lwr - BE_WR) * 100
        s_edge = (swr - BE_WR) * 100
        session_results[name] = {"n": n, "long_wr": lwr, "short_wr": swr}
        flag_l = " ◄" if abs(l_edge) > 2 else ""
        flag_s = " ◄" if abs(s_edge) > 2 else ""
        print(f"  {name:<25s} {n:>7,d} {lwr * 100:>7.1f}% {swr * 100:>8.1f}% "
              f"{l_edge:>+9.1f}pp{flag_l} {s_edge:>+10.1f}pp{flag_s}")

    overall_n = valid.sum()
    overall_lwr = y_long[valid].mean()
    overall_swr = y_short[valid].mean()
    print(f"\n  {'OVERALL':<25s} {overall_n:>7,d} {overall_lwr * 100:>7.1f}% {overall_swr * 100:>8.1f}%")

    # London open breakout analysis
    print("\n  London Open Breakout Analysis:")
    london_open = (hour >= 7) & (hour < 10)
    m_lo = np.asarray(london_open) & valid
    if m_lo.sum() > 50:
        lo_lwr = y_long[m_lo].mean()
        lo_swr = y_short[m_lo].mean()
        non_lo = np.asarray(~london_open) & valid
        nlo_lwr = y_long[non_lo].mean()
        nlo_swr = y_short[non_lo].mean()
        print(f"    London open LONG WR:  {lo_lwr * 100:.1f}%  vs rest: {nlo_lwr * 100:.1f}%  "
              f"(diff: {(lo_lwr - nlo_lwr) * 100:+.1f}pp)")
        print(f"    London open SHORT WR: {lo_swr * 100:.1f}%  vs rest: {nlo_swr * 100:.1f}%  "
              f"(diff: {(lo_swr - nlo_swr) * 100:+.1f}pp)")
    else:
        print("    Not enough London open bars")

    # Yearly consistency for best session
    if session_results:
        best_session = max(session_results, key=lambda k: max(
            abs(session_results[k]["long_wr"] - BE_WR),
            abs(session_results[k]["short_wr"] - BE_WR)))
        best_mask = np.asarray(sessions[best_session]) & valid
        print(f"\n  Yearly consistency for '{best_session}':")
        years = np.asarray(df.index.year)
        for yr in sorted(np.unique(years[best_mask])):
            yr_mask = best_mask & (df.index.year == yr)
            n_yr = yr_mask.sum()
            if n_yr < 20:
                continue
            lwr_yr = y_long[yr_mask].mean()
            swr_yr = y_short[yr_mask].mean()
            print(f"    {yr}: n={n_yr:,}  Long={lwr_yr * 100:.1f}%  Short={swr_yr * 100:.1f}%")

    return session_results


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION F: Microstructure ML test
# ══════════════════════════════════════════════════════════════════════════════

def build_microstructure_features(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print(f"  SECTION F: MICROSTRUCTURE ML TEST ({TF_LABEL})")
    print("=" * 70)

    h = df['high'].to_numpy()
    l = df['low'].to_numpy()
    c = df['close'].to_numpy()
    atr = _atr14(h, l, c)

    feat = pd.DataFrame(index=df.index)

    # Raw microstructure
    feat["vol_imb_sum"]    = df["vol_imbalance_sum"]
    feat["vol_imb_mean"]   = df["vol_imbalance_mean"]
    feat["buy_ratio"]      = df["buy_ratio_mean"]
    feat["buy_ratio_std"]  = df["buy_ratio_std"]
    feat["buy_pressure"]   = df["buy_ratio_mean"] - 0.5
    feat["tick_vel_mean"]  = df["tick_velocity_mean"]
    feat["tick_vel_max"]   = df["tick_velocity_max"]
    feat["tick_vel_std"]   = df["tick_velocity_std"]
    feat["avg_spread"]     = df["avg_spread_mean"]
    feat["min_spread"]     = df["avg_spread_min"]
    feat["max_spread"]     = df["max_spread_max"]
    feat["spread_range"]   = df["max_spread_max"] - df["avg_spread_min"]
    feat["n_tick_bars"]    = df["n_tick_bars"]
    feat["volume"]         = df["volume"]

    # Bar price features normalised by ATR
    feat["bar_range"]       = (h - l) / (atr + 1e-10)
    feat["bar_body"]        = np.abs(c - df["open"].to_numpy()) / (atr + 1e-10)
    feat["bar_body_signed"] = (c - df["open"].to_numpy()) / (atr + 1e-10)
    feat["upper_wick"]      = (h - np.maximum(c, df["open"].to_numpy())) / (atr + 1e-10)
    feat["lower_wick"]      = (np.minimum(c, df["open"].to_numpy()) - l) / (atr + 1e-10)
    feat["close_position"]  = (c - l) / (h - l + 1e-10)

    # Z-scores
    for col in ["vol_imb_sum", "buy_pressure", "tick_vel_mean", "avg_spread",
                "n_tick_bars", "volume", "bar_range"]:
        rm = feat[col].rolling(ZSCORE_W, min_periods=ZSCORE_W // 2).mean()
        rs = feat[col].rolling(ZSCORE_W, min_periods=ZSCORE_W // 2).std()
        feat[f"{col}_z"] = (feat[col] - rm) / rs.replace(0, np.nan)

    # Rolling lookback
    for w in [4, 8, 16]:
        feat[f"vol_imb_sum_ma{w}"]   = feat["vol_imb_sum"].rolling(w).mean()
        feat[f"buy_pressure_ma{w}"]  = feat["buy_pressure"].rolling(w).mean()
        feat[f"tick_vel_mean_ma{w}"] = feat["tick_vel_mean"].rolling(w).mean()
        feat[f"avg_spread_ma{w}"]    = feat["avg_spread"].rolling(w).mean()
        feat[f"volume_ma{w}"]        = feat["volume"].rolling(w).mean()
        feat[f"bar_range_ma{w}"]     = feat["bar_range"].rolling(w).mean()
        feat[f"vol_imb_chg{w}"]      = feat["vol_imb_sum"] - feat[f"vol_imb_sum_ma{w}"]
        feat[f"tick_vel_chg{w}"]     = feat["tick_vel_mean"] - feat[f"tick_vel_mean_ma{w}"]

    # Time features
    feat["hour"]         = df.index.hour
    feat["dow"]          = df.index.dayofweek
    feat["is_london"]    = ((feat["hour"] >= 7) & (feat["hour"] < 16)).astype(int)
    feat["is_ny"]        = ((feat["hour"] >= 13) & (feat["hour"] < 21)).astype(int)
    feat["is_overlap"]   = ((feat["hour"] >= 13) & (feat["hour"] < 16)).astype(int)
    feat["is_asian"]     = ((feat["hour"] >= 0)  & (feat["hour"] < 7)).astype(int)
    feat["gold_session"] = ((feat["hour"] >= 13) & (feat["hour"] < 17)).astype(int)

    # Return features (past only)
    for n in [1, 2, 4, 8]:
        ret = c / np.roll(c, n) - 1
        ret[:n] = np.nan
        feat[f"ret_{n}"] = ret

    print(f"  Microstructure features: {len(feat.columns)}")
    return feat


def run_microstructure_cv(micro_feat: pd.DataFrame,
                          y_long: np.ndarray, y_short: np.ndarray):
    feature_cols = micro_feat.columns.tolist()
    X = micro_feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    warmup = ZSCORE_W + 20
    X = X[warmup:]
    y_l = y_long[warmup:]
    y_s = y_short[warmup:]

    print(f"\n  Samples after warmup: {len(X):,}")

    print(f"\n--- MICROSTRUCTURE → LONG ---")
    results_long = purged_cv(X, y_l, n_splits=4, label="MICRO-LONG")

    print(f"\n--- MICROSTRUCTURE → SHORT ---")
    results_short = purged_cv(X, y_s, n_splits=4, label="MICRO-SHORT")

    if results_long:
        model = results_long[-1]["model"]
        imp = model.feature_importances_
        top_idx = np.argsort(imp)[::-1][:15]
        print(f"\n  TOP 15 MICROSTRUCTURE FEATURES (LONG, last fold):")
        for rank, idx in enumerate(top_idx, 1):
            print(f"    {rank:>2}. {feature_cols[idx]:<30s}  {imp[idx]:.4f}")

        time_cols = {"hour", "dow", "is_london", "is_ny",
                     "is_overlap", "is_asian", "gold_session"}
        top_names = [feature_cols[i] for i in top_idx[:5]]
        time_in_top5 = sum(1 for n in top_names if n in time_cols)
        if time_in_top5 >= 3:
            print(f"\n  ⚠ WARNING: {time_in_top5}/5 top features are TIME-BASED")
            print(f"    Model learns session patterns, not microstructure")

    return results_long, results_short


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION G: Summary verdict
# ══════════════════════════════════════════════════════════════════════════════

def print_verdict(std_long, std_short, micro_long, micro_short, session_results):
    print("\n" + "=" * 70)
    print(f"  SECTION G: FINAL VERDICT — XAUUSD {TF_LABEL} SIGNAL AUDIT")
    print("=" * 70)

    all_aucs = {}
    if std_long:
        all_aucs["Standard LONG"] = np.mean([r["auc"] for r in std_long])
    if std_short:
        all_aucs["Standard SHORT"] = np.mean([r["auc"] for r in std_short])
    if micro_long:
        all_aucs["Microstructure LONG"] = np.mean([r["auc"] for r in micro_long])
    if micro_short:
        all_aucs["Microstructure SHORT"] = np.mean([r["auc"] for r in micro_short])

    print(f"\n  {'Test':<25s} {'Avg AUC':>8s} {'vs Rand':>8s} {'vs EU15m':>8s} {'vs XAU15m':>9s}")
    print("  " + "-" * 60)
    for name, auc in all_aucs.items():
        vs_rand   = (auc - 0.500) * 100
        vs_eur15  = (auc - 0.519) * 100
        vs_xau15  = (auc - 0.526) * 100
        print(f"  {name:<25s} {auc:>8.4f} {vs_rand:>+7.1f}pp {vs_eur15:>+7.1f}pp {vs_xau15:>+8.1f}pp")

    # Session edge summary
    print(f"\n  Session TP/SL Win Rate Deviations from Break-Even ({BE_WR * 100:.1f}%):")
    for name, sr in session_results.items():
        l_edge = (sr["long_wr"] - BE_WR) * 100
        s_edge = (sr["short_wr"] - BE_WR) * 100
        if abs(l_edge) > 1.5 or abs(s_edge) > 1.5:
            print(f"    {name}: Long {l_edge:+.1f}pp  Short {s_edge:+.1f}pp  (n={sr['n']:,})")

    max_auc = max(all_aucs.values()) if all_aucs else 0.5

    print(f"\n  {'─' * 60}")
    if max_auc < 0.52:
        print(f"  VERDICT: ❌ ZERO EDGE on XAUUSD {TF_LABEL}")
        print("  No improvement over 15m — noise at this timeframe too.")
        print("  RECOMMENDED NEXT STEP: Test XAUUSD at DAILY timeframe")
    elif max_auc < 0.54:
        print(f"  VERDICT: ⚠️  MARGINAL SIGNAL on XAUUSD {TF_LABEL}")
        print(f"  Max AUC: {max_auc:.4f} — similar to 15m, likely noise")
        print("  RECOMMENDED NEXT STEP: Test XAUUSD at DAILY timeframe")
    else:
        print(f"  VERDICT: ✅ POTENTIAL EDGE DETECTED on XAUUSD {TF_LABEL}")
        print(f"  Max AUC: {max_auc:.4f} — exceeds threshold!")
        print("  NEXT STEP: Walk-forward PnL simulation + spread sensitivity")

    print("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    df = load_and_resample()
    std_feat = add_standard_features(df)
    y_long, y_short, atr = label_tp_sl(df)
    std_long, std_short, feature_cols = run_xgb_cv(std_feat, y_long, y_short)
    session_results = session_breakout_test(df, y_long, y_short)
    micro_feat = build_microstructure_features(df)
    micro_long, micro_short = run_microstructure_cv(micro_feat, y_long, y_short)
    print_verdict(std_long, std_short, micro_long, micro_short, session_results)

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s ({elapsed / 60:.1f}m)")


if __name__ == "__main__":
    main()
