"""
audit_btc_multi_tf.py — BTC/USD Multi-Timeframe Signal Audit

Pulls BTC/USD data from Coinbase (free, no API key needed for public OHLCV).
Tests daily + 1h timeframes for trend-following AND ML edge.

Sections:
  A. Pull BTC data from Coinbase (daily + 1h)
  B. Daily trend-following strategies
  C. Daily ML (XGBoost purged CV)
  D. 1h trend-following strategies
  E. 1h ML (XGBoost purged CV)
  F. Regime analysis
  G. Summary verdict

Why BTC:
  - 3-5x FX volatility → more room for signal above spread
  - Crypto momentum is documented in academic literature
  - 24/7 market → more bars → better ML training
  - Coinbase spread ~$5–20 on ~$60k price = ~0.01-0.03% (tiny)

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\audit_btc_multi_tf.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# -- Parameters ----------------------------------------------------------------
SPREAD_PCT  = 0.0005     # 0.05% spread (Coinbase taker fee ~0.4-0.6%, but for
                         # signal audit we use just spread, not fee)
TAKER_FEE   = 0.006      # 0.6% round-trip Coinbase Advanced fee (maker+taker)
                         # This is the REAL cost for trading

ANNUAL_DAYS_CRYPTO = 365  # crypto trades 365 days/year
ANNUAL_HOURS_CRYPTO = 365 * 24

# ATR labeling
TP_ATR = 1.5
SL_ATR = 1.4
BE_WR  = SL_ATR / (SL_ATR + TP_ATR)

# Daily ML
LOOKAHEAD_D  = 20
PURGE_GAP_D  = 25

# Hourly ML
LOOKAHEAD_H  = 72        # 3 days in hours
PURGE_GAP_H  = 168       # 1 week purge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def _atr_series(h: pd.Series, l: pd.Series, c: pd.Series, period: int) -> pd.Series:
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _atr14_np(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)),
                                       np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(com=13, adjust=False).mean().to_numpy()


def _adx(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 14) -> pd.Series:
    up = h - h.shift(1)
    down = l.shift(1) - l
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_w = tr.ewm(com=period - 1, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / (atr_w + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(com=period - 1, adjust=False).mean() / 100


def _sharpe(returns: pd.Series, annual_factor: int = 365) -> float:
    if returns.std() == 0:
        return 0.0
    return returns.mean() / returns.std() * np.sqrt(annual_factor)


def _max_dd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return dd.min()


def _strategy_stats(daily_ret: pd.Series, label: str, annual_factor: int = 365, verbose=True):
    equity = (1 + daily_ret).cumprod()
    sharpe = _sharpe(daily_ret, annual_factor)
    ann_ret = daily_ret.mean() * annual_factor * 100
    max_dd = _max_dd(equity) * 100
    vol = daily_ret.std() * np.sqrt(annual_factor) * 100
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    win_rate = (daily_ret > 0).mean() * 100
    n_years = len(daily_ret) / annual_factor

    stats = {"label": label, "sharpe": sharpe, "ann_ret": ann_ret,
             "max_dd": max_dd, "vol": vol, "calmar": calmar,
             "win_rate": win_rate, "equity": equity, "returns": daily_ret}
    if verbose:
        print(f"\n  {label}")
        print(f"    Sharpe:    {sharpe:+.3f}")
        print(f"    Ann Ret:   {ann_ret:+.2f}%")
        print(f"    Ann Vol:   {vol:.2f}%")
        print(f"    Max DD:    {max_dd:.2f}%")
        print(f"    Calmar:    {calmar:.3f}")
        print(f"    Win Rate:  {win_rate:.1f}% of periods")
        print(f"    Total Ret: {(equity.iloc[-1] - 1) * 100:+.1f}%  over {n_years:.1f} years")
    return stats


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A: Pull BTC data from Coinbase
# ══════════════════════════════════════════════════════════════════════════════

def pull_btc_data():
    print("=" * 70)
    print("  SECTION A: PULL BTC/USD DATA (yfinance)")
    print("=" * 70)

    cache_daily = DATA_DIR / "btc_usd_daily.parquet"
    cache_hourly = DATA_DIR / "btc_usd_1h.parquet"

    # --- Daily (full history from 2015) ---
    if cache_daily.exists():
        df_d = pd.read_parquet(cache_daily)
        df_d.index = pd.to_datetime(df_d.index, utc=True)
        print(f"  Daily: loaded from cache ({len(df_d):,} bars)")
    else:
        print("  Fetching daily BTC-USD from yfinance...")
        raw = yf.download("BTC-USD", start="2015-01-01", interval="1d", progress=False)
        # yfinance returns MultiIndex columns with (Price, Ticker)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df_d = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df_d.columns = ["open", "high", "low", "close", "volume"]
        df_d.index = pd.to_datetime(df_d.index, utc=True)
        df_d = df_d.dropna(subset=["close"])
        df_d.to_parquet(cache_daily)
        print(f"  Daily: fetched {len(df_d):,} bars, cached")

    print(f"  Daily range: {df_d.index.min().date()} → {df_d.index.max().date()}")
    print(f"  BTC price:   ${df_d['close'].min():,.0f} → ${df_d['close'].max():,.0f}")
    bnh = df_d['close'].iloc[-1] / df_d['close'].iloc[0] - 1
    n_yr = len(df_d) / 365
    print(f"  Buy & Hold:  {bnh*100:+,.0f}% total ({((1+bnh)**(1/n_yr)-1)*100:+.1f}%/yr over {n_yr:.1f}yr)")

    # --- Hourly (yfinance: last ~730 days) ---
    if cache_hourly.exists():
        df_h = pd.read_parquet(cache_hourly)
        df_h.index = pd.to_datetime(df_h.index, utc=True)
        print(f"\n  Hourly: loaded from cache ({len(df_h):,} bars)")
    else:
        print("\n  Fetching 1h BTC-USD from yfinance (last ~730 days)...")
        raw = yf.download("BTC-USD", period="730d", interval="1h", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df_h = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df_h.columns = ["open", "high", "low", "close", "volume"]
        df_h.index = pd.to_datetime(df_h.index, utc=True)
        df_h = df_h.dropna(subset=["close"])
        df_h.to_parquet(cache_hourly)
        print(f"  Hourly: fetched {len(df_h):,} bars, cached")

    print(f"  Hourly range: {df_h.index.min().date()} → {df_h.index.max().date()}")
    print(f"  Hourly bars:  {len(df_h):,}")

    return df_d, df_h


# ══════════════════════════════════════════════════════════════════════════════
#  Build feature matrix (shared for daily / hourly)
# ══════════════════════════════════════════════════════════════════════════════

def build_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    eps = 1e-10
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    bar_range = (h - l).clip(lower=eps)
    vol = df['volume'].astype(float) if 'volume' in df.columns else pd.Series(0, index=df.index)

    feat = pd.DataFrame(index=df.index)

    # Candle shape
    feat['body_ratio']  = (c - o) / bar_range
    feat['upper_wick']  = (h - np.maximum(o, c)) / bar_range
    feat['lower_wick']  = (np.minimum(o, c) - l) / bar_range

    # Returns
    for n in [1, 2, 3, 5, 10, 20]:
        feat[f'ret_{n}'] = c.pct_change(n, fill_method=None)

    # Longer-term momentum
    for n in [40, 60]:
        feat[f'ret_{n}'] = c.pct_change(n, fill_method=None)

    # Volatility
    atr5  = _atr_series(h, l, c, 5)
    atr14 = _atr_series(h, l, c, 14)
    feat['atr_ratio']   = atr5 / (atr14 + eps)
    feat['atr_norm']    = atr14 / (c + eps)
    feat['vol_5']       = c.pct_change().rolling(5).std()
    feat['vol_20']      = c.pct_change().rolling(20).std()
    feat['vol_ratio']   = feat['vol_5'] / (feat['vol_20'] + eps)

    # Trend
    ema10  = _ema(c, 10)
    ema20  = _ema(c, 20)
    ema50  = _ema(c, 50)
    ema200 = _ema(c, 200)
    feat['c_vs_ema10']  = c / (ema10 + eps) - 1
    feat['c_vs_ema20']  = c / (ema20 + eps) - 1
    feat['c_vs_ema50']  = c / (ema50 + eps) - 1
    feat['c_vs_ema200'] = c / (ema200 + eps) - 1
    feat['ema10_vs_20'] = ema10 / (ema20 + eps) - 1
    feat['ema20_vs_50'] = ema20 / (ema50 + eps) - 1
    feat['ema50_vs_200']= ema50 / (ema200 + eps) - 1

    # Oscillators
    feat['rsi_14'] = _rsi(c, 14) / 100 - 0.5
    feat['adx_14'] = _adx(h, l, c, 14)

    # Channel position
    high20  = h.rolling(20).max()
    low20   = l.rolling(20).min()
    high60  = h.rolling(60).max()
    low60   = l.rolling(60).min()
    feat['dch_20_pos'] = (c - low20) / (high20 - low20 + eps)
    feat['dch_60_pos'] = (c - low60) / (high60 - low60 + eps)

    # Vol regime
    atr_mean50 = atr14.rolling(50).mean()
    feat['vol_regime'] = atr14 / (atr_mean50 + eps)

    # Volume features (crypto volume is meaningful unlike FX)
    if vol.sum() > 0:
        vol_ma20 = vol.rolling(20).mean()
        feat['vol_ratio_20'] = vol / (vol_ma20 + eps)
        feat['vol_zscore'] = (vol - vol_ma20) / (vol.rolling(20).std() + eps)
        # Price-volume divergence
        feat['pv_corr_10'] = c.pct_change().rolling(10).corr(vol.pct_change())

    # Consecutive bars
    _bull = (c > c.shift(1))
    _bear = (c < c.shift(1))
    bull_grp = (~_bull).cumsum()
    bear_grp = (~_bear).cumsum()
    bull_run = _bull.astype(int).groupby(bull_grp).cumsum()
    bear_run = _bear.astype(int).groupby(bear_grp).cumsum()
    feat['consec_up']   = bull_run.clip(upper=10) / 10
    feat['consec_down'] = bear_run.clip(upper=10) / 10

    # Distance to highs/lows in ATR
    feat['dist_20d_high'] = (high20 - c) / (atr14 + eps)
    feat['dist_20d_low']  = (c - low20) / (atr14 + eps)

    # Day of week (crypto trades 7 days but weekends are quieter)
    dow = df.index.dayofweek
    feat['dow_sin'] = np.sin(2 * math.pi * dow / 7)
    feat['dow_cos'] = np.cos(2 * math.pi * dow / 7)

    # Hour of day (for hourly data)
    if hasattr(df.index, 'hour') and df.index.hour.nunique() > 1:
        feat['hour_sin'] = np.sin(2 * math.pi * df.index.hour / 24)
        feat['hour_cos'] = np.cos(2 * math.pi * df.index.hour / 24)

    print(f"  {prefix}Features built: {len(feat.columns)}")
    return feat


# ══════════════════════════════════════════════════════════════════════════════
#  ATR-based TP/SL labeling
# ══════════════════════════════════════════════════════════════════════════════

def label_tpsl(df: pd.DataFrame, lookahead: int, spread_pct: float):
    h = df['high'].to_numpy()
    l = df['low'].to_numpy()
    c = df['close'].to_numpy()
    atr = _atr14_np(h, l, c)
    N = len(df)

    y_long  = np.full(N, np.nan)
    y_short = np.full(N, np.nan)

    for i in range(N - lookahead):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        spread = c[i] * spread_pct
        h_path = h[i + 1: i + 1 + lookahead]
        l_path = l[i + 1: i + 1 + lookahead]

        # Long
        entry_l = c[i] + spread
        tp_l = entry_l + a * TP_ATR
        sl_l = entry_l - a * SL_ATR
        sl_hit = np.where(l_path <= sl_l)[0]
        tp_hit = np.where(h_path >= tp_l)[0]
        i_sl = sl_hit[0] if len(sl_hit) else lookahead
        i_tp = tp_hit[0] if len(tp_hit) else lookahead
        y_long[i] = 1.0 if (i_tp < i_sl and i_tp < lookahead) else 0.0

        # Short
        entry_s = c[i] - spread
        tp_s = entry_s - a * TP_ATR
        sl_s = entry_s + a * SL_ATR
        sl_hit = np.where(h_path >= sl_s)[0]
        tp_hit = np.where(l_path <= tp_s)[0]
        i_sl = sl_hit[0] if len(sl_hit) else lookahead
        i_tp = tp_hit[0] if len(tp_hit) else lookahead
        y_short[i] = 1.0 if (i_tp < i_sl and i_tp < lookahead) else 0.0

    return y_long, y_short


# ══════════════════════════════════════════════════════════════════════════════
#  Purged CV
# ══════════════════════════════════════════════════════════════════════════════

def run_purged_cv(X: np.ndarray, y: np.ndarray, purge_gap: int,
                  label: str, feature_cols: list):
    n = len(X)
    fold_size = n // 5
    results = []

    for fold in range(4):
        train_end = fold_size * (fold + 1)
        test_start = train_end + purge_gap
        test_end = test_start + fold_size
        if test_end > n:
            break

        X_tr, y_tr = X[:train_end], y[:train_end]
        X_te, y_te = X[test_start:test_end], y[test_start:test_end]

        vtr = np.isfinite(y_tr); vte = np.isfinite(y_te)
        X_tr, y_tr = X_tr[vtr], y_tr[vtr]
        X_te, y_te = X_te[vte], y_te[vte]

        if len(X_tr) < 100 or len(X_te) < 30:
            continue

        pos_c = (y_tr == 1).sum()
        neg_c = (y_tr == 0).sum()
        sw = neg_c / (pos_c + 1e-10)

        model = XGBClassifier(
            max_depth=4, learning_rate=0.05, n_estimators=300,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
            eval_metric="logloss", verbosity=0, random_state=42,
            scale_pos_weight=sw,
        )
        model.fit(X_tr, y_tr)
        prob = model.predict_proba(X_te)[:, 1]
        auc = roc_auc_score(y_te, prob)
        br = y_te.mean()

        wr_info = []
        for thr in [0.50, 0.55, 0.60]:
            mask = prob >= thr
            if mask.sum() > 10:
                wr = y_te[mask].mean()
                wr_info.append(f"≥{thr:.2f}:{wr*100:.1f}%({mask.sum()})")

        results.append({"fold": fold+1, "auc": auc, "br": br,
                        "train_n": len(y_tr), "test_n": len(y_te),
                        "wr_info": wr_info, "model": model})

        print(f"    Fold {fold+1}: AUC={auc:.4f}  BR={br*100:.1f}%  "
              f"train={len(y_tr):,}  test={len(y_te):,}")
        if wr_info:
            print(f"      WR: {' | '.join(wr_info)}")

    if results:
        avg = np.mean([r["auc"] for r in results])
        print(f"    → {label} AVG AUC: {avg:.4f}  ({(avg-0.5)*100:+.1f}pp vs random)")

        # Feature importance from last fold
        model = results[-1]["model"]
        imp = model.feature_importances_
        top_idx = np.argsort(imp)[::-1][:10]
        print(f"\n    TOP 10 FEATURES ({label}):")
        for rank, idx in enumerate(top_idx, 1):
            name = feature_cols[idx] if idx < len(feature_cols) else f"feat_{idx}"
            print(f"      {rank:>2}. {name:<25s}  {imp[idx]:.4f}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B+C: Daily Analysis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_daily(df_d: pd.DataFrame):
    print("\n" + "=" * 70)
    print("  SECTION B: DAILY TREND-FOLLOWING STRATEGIES (BTC)")
    print("=" * 70)

    c = df_d['close']
    h = df_d['high']
    l = df_d['low']

    # Total cost per trade = spread + fees
    total_cost_pct = SPREAD_PCT + TAKER_FEE  # ~0.65%
    trade_cost = total_cost_pct  # applied on position changes

    all_stats = {}

    # Buy & Hold
    bnh_ret = c.pct_change().dropna()
    all_stats["Buy & Hold"] = _strategy_stats(bnh_ret, "Buy & Hold (baseline)", ANNUAL_DAYS_CRYPTO)

    # EMA 50/200 long/short
    ema50  = _ema(c, 50)
    ema200 = _ema(c, 200)
    sig = pd.Series(np.where(ema50 > ema200, 1.0, -1.0), index=c.index)
    pos = sig.shift(1).fillna(0)
    chg = (pos != pos.shift(1)).astype(float)
    ret = c.pct_change() * pos - chg * trade_cost
    all_stats["EMA 50/200"] = _strategy_stats(ret.dropna(), "EMA 50/200 Long/Short", ANNUAL_DAYS_CRYPTO)

    # EMA 50/200 long-only
    pos_lo = pd.Series(np.where(ema50 > ema200, 1.0, 0.0), index=c.index).shift(1).fillna(0)
    chg_lo = (pos_lo != pos_lo.shift(1)).astype(float)
    ret_lo = c.pct_change() * pos_lo - chg_lo * trade_cost
    all_stats["EMA 50/200 LO"] = _strategy_stats(ret_lo.dropna(), "EMA 50/200 Long-Only", ANNUAL_DAYS_CRYPTO)

    # EMA 20/50 (faster)
    ema20 = _ema(c, 20)
    sig_fast = pd.Series(np.where(ema20 > ema50, 1.0, -1.0), index=c.index)
    pos_fast = sig_fast.shift(1).fillna(0)
    chg_fast = (pos_fast != pos_fast.shift(1)).astype(float)
    ret_fast = c.pct_change() * pos_fast - chg_fast * trade_cost
    all_stats["EMA 20/50"] = _strategy_stats(ret_fast.dropna(), "EMA 20/50 Long/Short", ANNUAL_DAYS_CRYPTO)

    # Donchian 20
    dc_high = h.rolling(20).max().shift(1)
    dc_low  = l.rolling(20).min().shift(1)
    dc_sig = pd.Series(0.0, index=c.index)
    dc_sig[c > dc_high] = 1.0
    dc_sig[c < dc_low] = -1.0
    dc_sig = dc_sig.replace(0, np.nan).ffill().fillna(0)
    dc_pos = dc_sig.shift(1).fillna(0)
    dc_chg = (dc_pos != dc_pos.shift(1)).astype(float)
    dc_ret = c.pct_change() * dc_pos - dc_chg * trade_cost
    all_stats["Donchian 20"] = _strategy_stats(dc_ret.dropna(), "Donchian 20-day Breakout", ANNUAL_DAYS_CRYPTO)

    # Momentum 20-day
    mom20 = c.pct_change(20)
    mom_sig = pd.Series(np.where(mom20 > 0, 1.0, -1.0), index=c.index)
    mom_pos = mom_sig.shift(1).fillna(0)
    mom_chg = (mom_pos != mom_pos.shift(1)).astype(float)
    mom_ret = c.pct_change() * mom_pos - mom_chg * trade_cost
    all_stats["Mom 20"] = _strategy_stats(mom_ret.dropna(), "Momentum 20-day", ANNUAL_DAYS_CRYPTO)

    # Momentum 60-day
    mom60 = c.pct_change(60)
    mom60_sig = pd.Series(np.where(mom60 > 0, 1.0, -1.0), index=c.index)
    mom60_pos = mom60_sig.shift(1).fillna(0)
    mom60_chg = (mom60_pos != mom60_pos.shift(1)).astype(float)
    mom60_ret = c.pct_change() * mom60_pos - mom60_chg * trade_cost
    all_stats["Mom 60"] = _strategy_stats(mom60_ret.dropna(), "Momentum 60-day", ANNUAL_DAYS_CRYPTO)

    # Mean reversion: RSI oversold/overbought
    rsi = _rsi(c, 14)
    mr_sig = pd.Series(0.0, index=c.index)
    mr_sig[rsi < 30] = 1.0   # oversold → buy
    mr_sig[rsi > 70] = -1.0  # overbought → sell
    mr_sig = mr_sig.replace(0, np.nan).ffill().fillna(0)
    mr_pos = mr_sig.shift(1).fillna(0)
    mr_chg = (mr_pos != mr_pos.shift(1)).astype(float)
    mr_ret = c.pct_change() * mr_pos - mr_chg * trade_cost
    all_stats["RSI MR"] = _strategy_stats(mr_ret.dropna(), "RSI Mean-Reversion (30/70)", ANNUAL_DAYS_CRYPTO)

    # Summary table
    print("\n" + "=" * 70)
    print("  DAILY STRATEGY COMPARISON (with 0.6% round-trip Coinbase fee)")
    print("=" * 70)
    print(f"\n  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s} {'Calmar':>7s}")
    print("  " + "-" * 62)
    for key in ["Buy & Hold", "EMA 50/200", "EMA 50/200 LO", "EMA 20/50",
                "Donchian 20", "Mom 20", "Mom 60", "RSI MR"]:
        s = all_stats[key]
        print(f"  {s['label'][:30]:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% "
              f"{s['max_dd']:>7.1f}% {s['calmar']:>7.3f}")

    # --- ML ---
    print("\n" + "=" * 70)
    print("  SECTION C: DAILY ML (XGBoost Purged CV)")
    print("=" * 70)

    feat = build_features(df_d, prefix="Daily ")
    feature_cols = feat.columns.tolist()
    y_long, y_short = label_tpsl(df_d, LOOKAHEAD_D, SPREAD_PCT)

    valid = np.isfinite(y_long)
    print(f"  Valid labeled: {valid.sum():,} / {len(df_d):,}")
    print(f"  Long  base rate: {y_long[valid].mean()*100:.1f}%  (BE={BE_WR*100:.1f}%)")
    print(f"  Short base rate: {y_short[valid].mean()*100:.1f}%  (BE={BE_WR*100:.1f}%)")

    X = feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    warmup = 200
    X_w = X[warmup:]
    y_l_w = y_long[warmup:]
    y_s_w = y_short[warmup:]

    print(f"\n--- DAILY LONG ---")
    res_d_long = run_purged_cv(X_w, y_l_w, PURGE_GAP_D, "DAILY LONG", feature_cols)
    print(f"\n--- DAILY SHORT ---")
    res_d_short = run_purged_cv(X_w, y_s_w, PURGE_GAP_D, "DAILY SHORT", feature_cols)

    # Yearly OOS
    print(f"\n  YEARLY BREAKDOWN (EMA 50/200):")
    years = sorted(df_d.index.year.unique())
    print(f"  {'Year':>6s} {'AnnRet':>8s} {'Sharpe':>8s} {'MaxDD':>8s} {'Verdict':>10s}")
    print("  " + "-" * 45)
    oos_sharpes = []
    for yr in years:
        mask = df_d.index.year == yr
        yr_ret = ret[mask].dropna()
        if len(yr_ret) < 30:
            continue
        s = _sharpe(yr_ret, ANNUAL_DAYS_CRYPTO)
        ar = yr_ret.mean() * ANNUAL_DAYS_CRYPTO * 100
        eq = (1 + yr_ret).cumprod()
        dd = _max_dd(eq) * 100
        oos_sharpes.append(s)
        print(f"  {yr:>6d} {ar:>+7.1f}% {s:>+7.3f} {dd:>7.1f}% {'WIN' if ar > 0 else 'LOSS':>10s}")

    return all_stats, res_d_long, res_d_short, oos_sharpes


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION D+E: Hourly Analysis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_hourly(df_h: pd.DataFrame):
    print("\n" + "=" * 70)
    print("  SECTION D: 1-HOUR TREND STRATEGIES (BTC)")
    print("=" * 70)

    c = df_h['close']
    h = df_h['high']
    l = df_h['low']

    # For hourly: lower fee impact per trade but more trades
    total_cost_pct = SPREAD_PCT + TAKER_FEE

    all_stats = {}

    bnh_ret = c.pct_change().dropna()
    all_stats["Buy & Hold"] = _strategy_stats(bnh_ret, "Buy & Hold (hourly)", ANNUAL_HOURS_CRYPTO)

    # EMA 24/72 (≈1d/3d)
    ema24 = _ema(c, 24)
    ema72 = _ema(c, 72)
    sig = pd.Series(np.where(ema24 > ema72, 1.0, -1.0), index=c.index)
    pos = sig.shift(1).fillna(0)
    chg = (pos != pos.shift(1)).astype(float)
    ret = c.pct_change() * pos - chg * total_cost_pct
    all_stats["EMA 24/72"] = _strategy_stats(ret.dropna(), "EMA 24/72h Long/Short", ANNUAL_HOURS_CRYPTO)

    # EMA 24/72 long-only
    pos_lo = pd.Series(np.where(ema24 > ema72, 1.0, 0.0), index=c.index).shift(1).fillna(0)
    chg_lo = (pos_lo != pos_lo.shift(1)).astype(float)
    ret_lo = c.pct_change() * pos_lo - chg_lo * total_cost_pct
    all_stats["EMA 24/72 LO"] = _strategy_stats(ret_lo.dropna(), "EMA 24/72h Long-Only", ANNUAL_HOURS_CRYPTO)

    # Momentum 72h
    mom72 = c.pct_change(72)
    mom_sig = pd.Series(np.where(mom72 > 0, 1.0, -1.0), index=c.index)
    mom_pos = mom_sig.shift(1).fillna(0)
    mom_chg = (mom_pos != mom_pos.shift(1)).astype(float)
    mom_ret = c.pct_change() * mom_pos - mom_chg * total_cost_pct
    all_stats["Mom 72h"] = _strategy_stats(mom_ret.dropna(), "Momentum 72h", ANNUAL_HOURS_CRYPTO)

    # Donchian 48h (2-day channel)
    dc_hi = h.rolling(48).max().shift(1)
    dc_lo = l.rolling(48).min().shift(1)
    dc_sig = pd.Series(0.0, index=c.index)
    dc_sig[c > dc_hi] = 1.0
    dc_sig[c < dc_lo] = -1.0
    dc_sig = dc_sig.replace(0, np.nan).ffill().fillna(0)
    dc_pos = dc_sig.shift(1).fillna(0)
    dc_chg = (dc_pos != dc_pos.shift(1)).astype(float)
    dc_ret = c.pct_change() * dc_pos - dc_chg * total_cost_pct
    all_stats["Donchian 48h"] = _strategy_stats(dc_ret.dropna(), "Donchian 48h Breakout", ANNUAL_HOURS_CRYPTO)

    # RSI mean reversion (hourly)
    rsi = _rsi(c, 14)
    mr_sig = pd.Series(0.0, index=c.index)
    mr_sig[rsi < 25] = 1.0
    mr_sig[rsi > 75] = -1.0
    mr_sig = mr_sig.replace(0, np.nan).ffill().fillna(0)
    mr_pos = mr_sig.shift(1).fillna(0)
    mr_chg = (mr_pos != mr_pos.shift(1)).astype(float)
    mr_ret = c.pct_change() * mr_pos - mr_chg * total_cost_pct
    all_stats["RSI MR 1h"] = _strategy_stats(mr_ret.dropna(), "RSI Mean-Rev 25/75 (1h)", ANNUAL_HOURS_CRYPTO)

    # Summary
    print("\n  1H STRATEGY COMPARISON (with 0.6% Coinbase fee)")
    print(f"\n  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 55)
    for key in ["Buy & Hold", "EMA 24/72", "EMA 24/72 LO", "Mom 72h",
                "Donchian 48h", "RSI MR 1h"]:
        s = all_stats[key]
        print(f"  {s['label'][:30]:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # ML
    print("\n" + "=" * 70)
    print("  SECTION E: 1-HOUR ML (XGBoost Purged CV)")
    print("=" * 70)

    feat = build_features(df_h, prefix="1h ")
    feature_cols = feat.columns.tolist()
    y_long, y_short = label_tpsl(df_h, LOOKAHEAD_H, SPREAD_PCT)

    valid = np.isfinite(y_long)
    print(f"  Valid labeled: {valid.sum():,} / {len(df_h):,}")
    print(f"  Long  base rate: {y_long[valid].mean()*100:.1f}%  (BE={BE_WR*100:.1f}%)")
    print(f"  Short base rate: {y_short[valid].mean()*100:.1f}%  (BE={BE_WR*100:.1f}%)")

    X = feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    warmup = 200
    X_w = X[warmup:]
    y_l = y_long[warmup:]
    y_s = y_short[warmup:]

    print(f"\n--- 1H LONG ---")
    res_h_long = run_purged_cv(X_w, y_l, PURGE_GAP_H, "1H LONG", feature_cols)
    print(f"\n--- 1H SHORT ---")
    res_h_short = run_purged_cv(X_w, y_s, PURGE_GAP_H, "1H SHORT", feature_cols)

    return all_stats, res_h_long, res_h_short


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION F+G: Verdict
# ══════════════════════════════════════════════════════════════════════════════

def print_verdict(daily_stats, d_long, d_short, d_sharpes,
                  hourly_stats, h_long, h_short):
    print("\n" + "=" * 70)
    print("  SECTION G: FINAL VERDICT — BTC/USD SIGNAL AUDIT")
    print("=" * 70)

    print(f"\n  DAILY STRATEGIES (net of 0.6% Coinbase fee):")
    print(f"  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 55)
    for key in ["Buy & Hold", "EMA 50/200", "EMA 50/200 LO", "EMA 20/50",
                "Donchian 20", "Mom 20", "Mom 60", "RSI MR"]:
        s = daily_stats[key]
        print(f"  {key:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    print(f"\n  1H STRATEGIES (net of 0.6% Coinbase fee):")
    print(f"  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 55)
    for key in ["Buy & Hold", "EMA 24/72", "EMA 24/72 LO", "Mom 72h",
                "Donchian 48h", "RSI MR 1h"]:
        s = hourly_stats[key]
        print(f"  {key:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # ML summary
    ml_results = {}
    if d_long:
        ml_results["Daily LONG"] = np.mean([r["auc"] for r in d_long])
    if d_short:
        ml_results["Daily SHORT"] = np.mean([r["auc"] for r in d_short])
    if h_long:
        ml_results["1h LONG"] = np.mean([r["auc"] for r in h_long])
    if h_short:
        ml_results["1h SHORT"] = np.mean([r["auc"] for r in h_short])

    if ml_results:
        print(f"\n  ML (XGBoost) PREDICTION:")
        for name, auc in ml_results.items():
            status = "✅" if auc > 0.53 else "⚠️ " if auc > 0.51 else "❌"
            print(f"    {status} {name}: AUC={auc:.4f}  ({(auc-0.5)*100:+.1f}pp vs random)")

    # Best overall
    best_d = max([k for k in daily_stats if k != "Buy & Hold"],
                 key=lambda k: daily_stats[k]["sharpe"])
    best_h = max([k for k in hourly_stats if k != "Buy & Hold"],
                 key=lambda k: hourly_stats[k]["sharpe"])

    print(f"\n  {'─' * 60}")
    print(f"  BEST DAILY:  {best_d} — Sharpe {daily_stats[best_d]['sharpe']:+.3f}")
    print(f"  BEST HOURLY: {best_h} — Sharpe {hourly_stats[best_h]['sharpe']:+.3f}")

    # Overall edge assessment
    best_ml_auc = max(ml_results.values()) if ml_results else 0
    best_strat_sharpe = max(daily_stats[best_d]["sharpe"],
                            hourly_stats[best_h]["sharpe"])

    if best_ml_auc > 0.54 or best_strat_sharpe > 0.5:
        print(f"\n  VERDICT: ✅ BTC/USD HAS TRADEABLE EDGE")
        if best_ml_auc > 0.54:
            print(f"    ML shows genuine predictive power (AUC {best_ml_auc:.4f})")
        if best_strat_sharpe > 0.5:
            print(f"    Trend-following Sharpe {best_strat_sharpe:+.3f} after fees")
        print(f"\n  NEXT STEPS:")
        print(f"    1. Build walk-forward backtest with position sizing")
        print(f"    2. Test with realistic Coinbase fees (maker 0.4% vs taker 0.6%)")
        print(f"    3. If ML edge: combine ML filter with trend signal")
        print(f"    4. Explore ETH/USD for diversification")
    elif best_ml_auc > 0.52 or best_strat_sharpe > 0.3:
        print(f"\n  VERDICT: ⚠️  MARGINAL EDGE on BTC/USD")
        print(f"    Edge exists but may not survive higher fees / slippage")
    else:
        print(f"\n  VERDICT: ❌ NO EDGE on BTC/USD")
        print(f"    Similar to FX — noise dominates")

    print("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    df_d, df_h = pull_btc_data()
    daily_stats, d_long, d_short, d_sharpes = analyze_daily(df_d)
    hourly_stats, h_long, h_short = analyze_hourly(df_h)
    print_verdict(daily_stats, d_long, d_short, d_sharpes,
                  hourly_stats, h_long, h_short)

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s ({elapsed / 60:.1f}m)")


if __name__ == "__main__":
    main()
