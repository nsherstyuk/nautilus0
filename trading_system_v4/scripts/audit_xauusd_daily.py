"""
audit_xauusd_daily.py — XAUUSD Daily Trend-Following Signal Audit

Tests whether XAUUSD has tradeable edge at the daily timeframe.
This is the documented CTA edge — daily gold trend-following.

Sections:
  A. Resample tick bars → daily OHLCV
  B. Trend-following strategies:
     1. EMA crossover (50/200)
     2. Donchian breakout (20-day)
     3. Momentum (20-day, 60-day return sign)
     4. Combined signal (majority vote)
  C. Walk-forward out-of-sample validation
  D. ML with daily features (XGBoost purged CV)
  E. Yearly consistency & regime analysis
  F. Summary verdict

Prior results:
  XAUUSD 15m: AUC 0.526 (marginal / noise)
  XAUUSD 1h:  AUC 0.509 (zero edge)
  Expected: daily trend-following should show positive Sharpe (0.3-0.8)

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\audit_xauusd_daily.py
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "xauusd_1000t_bars.parquet"

SPREAD_EST     = 0.30      # $0.30 gold spread
ANNUAL_TRADING_DAYS = 252

# ML labeling parameters
TP_ATR     = 1.5
SL_ATR     = 1.4
LOOKAHEAD  = 20        # 20 trading days (~1 month)
BE_WR      = SL_ATR / (SL_ATR + TP_ATR)

# CV parameters
PURGE_GAP  = 25        # ~5 weeks gap
ZSCORE_W   = 20        # 20 days


# ── Helpers ───────────────────────────────────────────────────────────────────

def _atr14(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
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


def _adx(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 14) -> pd.Series:
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


def _atr_series(h: pd.Series, l: pd.Series, c: pd.Series, period: int) -> pd.Series:
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _sharpe(returns: pd.Series) -> float:
    if returns.std() == 0:
        return 0.0
    return returns.mean() / returns.std() * np.sqrt(ANNUAL_TRADING_DAYS)


def _max_dd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return dd.min()


def _strategy_stats(daily_returns: pd.Series, label: str, verbose: bool = True):
    """Compute and print strategy statistics."""
    equity = (1 + daily_returns).cumprod()
    sharpe = _sharpe(daily_returns)
    ann_ret = daily_returns.mean() * ANNUAL_TRADING_DAYS * 100
    max_dd = _max_dd(equity) * 100
    vol = daily_returns.std() * np.sqrt(ANNUAL_TRADING_DAYS) * 100
    win_rate = (daily_returns > 0).mean() * 100

    # Calmar ratio
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    stats = {
        "label": label, "sharpe": sharpe, "ann_ret": ann_ret,
        "max_dd": max_dd, "vol": vol, "win_rate": win_rate,
        "calmar": calmar, "equity": equity, "returns": daily_returns,
    }

    if verbose:
        print(f"\n  {label}")
        print(f"    Sharpe:    {sharpe:+.3f}")
        print(f"    Ann Ret:   {ann_ret:+.2f}%")
        print(f"    Ann Vol:   {vol:.2f}%")
        print(f"    Max DD:    {max_dd:.2f}%")
        print(f"    Calmar:    {calmar:.3f}")
        print(f"    Win Rate:  {win_rate:.1f}% of days")
        print(f"    Total Ret: {(equity.iloc[-1] - 1) * 100:+.1f}%  over {len(daily_returns) / ANNUAL_TRADING_DAYS:.1f} years")

    return stats


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A: Resample tick bars → daily
# ══════════════════════════════════════════════════════════════════════════════

def load_and_resample():
    print("=" * 70)
    print("  SECTION A: LOAD & RESAMPLE XAUUSD TICK BARS → DAILY")
    print("=" * 70)

    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")
    print(f"  Tick bars loaded: {len(tick):,}")

    df = tick.resample("1D", label="right", closed="right").agg(
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

    # Remove weekends / holidays with very few ticks
    df = df[df["n_tick_bars"] >= 10]

    print(f"  Daily bars: {len(df):,}")
    print(f"  Range: {df.index.min().date()} → {df.index.max().date()}")
    print(f"  Gold price: ${df['close'].min():.2f} → ${df['close'].max():.2f}")

    # Buy-and-hold benchmark
    bnh_ret = df['close'].iloc[-1] / df['close'].iloc[0] - 1
    n_years = len(df) / ANNUAL_TRADING_DAYS
    bnh_ann = (1 + bnh_ret) ** (1 / n_years) - 1
    print(f"  Buy & Hold: {bnh_ret * 100:+.1f}% total  ({bnh_ann * 100:+.1f}%/yr over {n_years:.1f} years)")

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B: Trend-following strategies
# ══════════════════════════════════════════════════════════════════════════════

def run_trend_strategies(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("  SECTION B: TREND-FOLLOWING STRATEGIES")
    print("=" * 70)

    c = df['close']
    h = df['high']
    l = df['low']
    atr = _atr_series(h, l, c, 14)

    # Cost per trade (round-trip spread in return terms)
    # Only charged on position changes
    spread_cost = SPREAD_EST / c  # varies with price level

    all_stats = {}

    # ── 0. Buy & Hold baseline ───────────────────────────────────────────
    bnh_returns = c.pct_change().dropna()
    bnh = _strategy_stats(bnh_returns, "Buy & Hold (baseline)")
    all_stats["Buy & Hold"] = bnh

    # ── 1. EMA 50/200 crossover ──────────────────────────────────────────
    print("\n  " + "-" * 60)
    ema50 = _ema(c, 50)
    ema200 = _ema(c, 200)
    # Signal: +1 long when EMA50 > EMA200, -1 short when below
    ema_signal = pd.Series(np.where(ema50 > ema200, 1.0, -1.0), index=c.index)
    # Delay by 1 day (trade on next day's close)
    ema_pos = ema_signal.shift(1).fillna(0)
    ema_trades = (ema_pos != ema_pos.shift(1)).sum()
    ema_raw_ret = c.pct_change() * ema_pos
    # Deduct spread on position changes
    pos_change = (ema_pos != ema_pos.shift(1)).astype(float)
    ema_net_ret = ema_raw_ret - pos_change * spread_cost
    ema_net_ret = ema_net_ret.dropna()
    stats = _strategy_stats(ema_net_ret, f"EMA 50/200 Crossover (trades={ema_trades})")
    all_stats["EMA 50/200"] = stats

    # ── 1b. Long-only EMA 50/200 ────────────────────────────────────────
    ema_pos_long = pd.Series(np.where(ema50 > ema200, 1.0, 0.0), index=c.index).shift(1).fillna(0)
    ema_long_ret = c.pct_change() * ema_pos_long
    pos_change_lo = (ema_pos_long != ema_pos_long.shift(1)).astype(float)
    ema_long_net = ema_long_ret - pos_change_lo * spread_cost
    ema_long_net = ema_long_net.dropna()
    stats = _strategy_stats(ema_long_net, "EMA 50/200 Long-Only")
    all_stats["EMA 50/200 LO"] = stats

    # ── 2. Donchian Breakout (20-day) ────────────────────────────────────
    print("\n  " + "-" * 60)
    dc_high = h.rolling(20).max().shift(1)  # yesterday's 20-day high
    dc_low  = l.rolling(20).min().shift(1)
    # Signal: long if close > 20d high, short if close < 20d low, else hold
    dc_signal = pd.Series(0.0, index=c.index)
    dc_signal[c > dc_high] = 1.0
    dc_signal[c < dc_low] = -1.0
    # Forward fill (hold until opposite signal)
    dc_signal = dc_signal.replace(0, np.nan).ffill().fillna(0)
    dc_pos = dc_signal.shift(1).fillna(0)
    dc_trades = (dc_pos != dc_pos.shift(1)).sum()
    dc_raw_ret = c.pct_change() * dc_pos
    pos_change_dc = (dc_pos != dc_pos.shift(1)).astype(float)
    dc_net_ret = dc_raw_ret - pos_change_dc * spread_cost
    dc_net_ret = dc_net_ret.dropna()
    stats = _strategy_stats(dc_net_ret, f"Donchian 20-day Breakout (trades={dc_trades})")
    all_stats["Donchian 20"] = stats

    # ── 2b. Donchian Long-Only ───────────────────────────────────────────
    dc_signal_lo = pd.Series(0.0, index=c.index)
    dc_signal_lo[c > dc_high] = 1.0
    dc_signal_lo[c < dc_low] = 0.0
    dc_signal_lo = dc_signal_lo.replace(0, np.nan).ffill().fillna(0)
    dc_pos_lo = dc_signal_lo.shift(1).fillna(0)
    dc_lo_ret = c.pct_change() * dc_pos_lo
    pos_change_dc_lo = (dc_pos_lo != dc_pos_lo.shift(1)).astype(float)
    dc_lo_net = dc_lo_ret - pos_change_dc_lo * spread_cost
    dc_lo_net = dc_lo_net.dropna()
    stats = _strategy_stats(dc_lo_net, "Donchian 20-day Long-Only")
    all_stats["Donchian 20 LO"] = stats

    # ── 3. Momentum (20-day) ────────────────────────────────────────────
    print("\n  " + "-" * 60)
    mom20 = c.pct_change(20)
    mom_signal = pd.Series(np.where(mom20 > 0, 1.0, -1.0), index=c.index)
    mom_pos = mom_signal.shift(1).fillna(0)
    mom_trades = (mom_pos != mom_pos.shift(1)).sum()
    mom_raw_ret = c.pct_change() * mom_pos
    pos_change_mom = (mom_pos != mom_pos.shift(1)).astype(float)
    mom_net_ret = mom_raw_ret - pos_change_mom * spread_cost
    mom_net_ret = mom_net_ret.dropna()
    stats = _strategy_stats(mom_net_ret, f"Momentum 20-day (trades={mom_trades})")
    all_stats["Mom 20"] = stats

    # ── 4. Momentum (60-day) ────────────────────────────────────────────
    mom60 = c.pct_change(60)
    mom60_signal = pd.Series(np.where(mom60 > 0, 1.0, -1.0), index=c.index)
    mom60_pos = mom60_signal.shift(1).fillna(0)
    mom60_trades = (mom60_pos != mom60_pos.shift(1)).sum()
    mom60_raw_ret = c.pct_change() * mom60_pos
    pos_change_m60 = (mom60_pos != mom60_pos.shift(1)).astype(float)
    mom60_net_ret = mom60_raw_ret - pos_change_m60 * spread_cost
    mom60_net_ret = mom60_net_ret.dropna()
    stats = _strategy_stats(mom60_net_ret, f"Momentum 60-day (trades={mom60_trades})")
    all_stats["Mom 60"] = stats

    # ── 5. Combined signal (majority vote) ───────────────────────────────
    print("\n  " + "-" * 60)
    combined = (ema_signal + dc_signal + mom_signal + mom60_signal)
    combined_pos = pd.Series(np.where(combined > 0, 1.0,
                             np.where(combined < 0, -1.0, 0.0)),
                             index=c.index).shift(1).fillna(0)
    comb_trades = (combined_pos != combined_pos.shift(1)).sum()
    comb_raw_ret = c.pct_change() * combined_pos
    pos_change_comb = (combined_pos != combined_pos.shift(1)).astype(float)
    comb_net_ret = comb_raw_ret - pos_change_comb * spread_cost
    comb_net_ret = comb_net_ret.dropna()
    stats = _strategy_stats(comb_net_ret, f"Combined Signal (majority, trades={comb_trades})")
    all_stats["Combined"] = stats

    # ── 6. ATR-sized trend (volatility-targeted) ─────────────────────────
    # Position size inversely proportional to ATR (target 1% daily risk)
    print("\n  " + "-" * 60)
    target_risk = 0.01
    atr_size = target_risk / (atr / c)  # leverage factor
    atr_size = atr_size.clip(upper=3.0)  # cap leverage at 3x
    atr_ema_pos = ema_signal.shift(1).fillna(0) * atr_size.shift(1).fillna(1)
    atr_raw_ret = c.pct_change() * atr_ema_pos
    pos_change_atr = (ema_signal != ema_signal.shift(1)).astype(float)
    atr_net_ret = atr_raw_ret - pos_change_atr * spread_cost * atr_size.shift(1).fillna(1)
    atr_net_ret = atr_net_ret.dropna()
    stats = _strategy_stats(atr_net_ret, "EMA 50/200 + ATR Sizing (vol-target 1%)")
    all_stats["EMA+ATR"] = stats

    # Summary table
    print("\n" + "=" * 70)
    print("  STRATEGY COMPARISON SUMMARY")
    print("=" * 70)
    print(f"\n  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s} {'Calmar':>7s}")
    print("  " + "-" * 62)
    for key in ["Buy & Hold", "EMA 50/200", "EMA 50/200 LO", "Donchian 20",
                "Donchian 20 LO", "Mom 20", "Mom 60", "Combined", "EMA+ATR"]:
        s = all_stats[key]
        print(f"  {s['label'][:30]:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% "
              f"{s['max_dd']:>7.1f}% {s['calmar']:>7.3f}")

    return all_stats


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION C: Walk-Forward Out-of-Sample
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward_oos(df: pd.DataFrame):
    """Walk-forward test: train signal on 3 years, test on next 1 year."""
    print("\n" + "=" * 70)
    print("  SECTION C: WALK-FORWARD OOS (EMA 50/200, yearly windows)")
    print("=" * 70)

    c = df['close']
    spread_cost = SPREAD_EST / c
    years = sorted(df.index.year.unique())

    print(f"\n  {'Year':>6s} {'AnnRet':>8s} {'Sharpe':>8s} {'MaxDD':>8s} {'Trades':>7s} {'Verdict':>10s}")
    print("  " + "-" * 55)

    oos_sharpes = []
    oos_returns = []

    for yr in years:
        yr_mask = df.index.year == yr
        yr_df = df[yr_mask]
        if len(yr_df) < 50:
            continue

        yr_c = yr_df['close']
        ema50 = _ema(c, 50)   # computed on full data for warmup
        ema200 = _ema(c, 200)

        ema_signal = pd.Series(np.where(ema50 > ema200, 1.0, -1.0), index=c.index)
        ema_pos = ema_signal.shift(1).fillna(0)

        # Extract just this year
        yr_pos = ema_pos[yr_mask]
        yr_ret = yr_c.pct_change() * yr_pos
        pos_chg = (yr_pos != yr_pos.shift(1)).astype(float)
        yr_spread = spread_cost[yr_mask]
        yr_net = yr_ret - pos_chg * yr_spread
        yr_net = yr_net.dropna()

        if len(yr_net) < 20:
            continue

        ann_ret = yr_net.mean() * ANNUAL_TRADING_DAYS * 100
        sharpe = _sharpe(yr_net)
        equity = (1 + yr_net).cumprod()
        max_dd = _max_dd(equity) * 100
        trades = pos_chg.sum()
        verdict = "WIN" if ann_ret > 0 else "LOSS"

        oos_sharpes.append(sharpe)
        oos_returns.append(ann_ret)

        print(f"  {yr:>6d} {ann_ret:>+7.1f}% {sharpe:>+7.3f} {max_dd:>7.1f}% {trades:>7.0f} {verdict:>10s}")

    win_years = sum(1 for r in oos_returns if r > 0)
    total_years = len(oos_returns)
    avg_sharpe = np.mean(oos_sharpes) if oos_sharpes else 0
    avg_return = np.mean(oos_returns) if oos_returns else 0

    print(f"\n  Win years: {win_years}/{total_years} ({win_years/total_years*100:.0f}%)")
    print(f"  Avg OOS Sharpe: {avg_sharpe:+.3f}")
    print(f"  Avg OOS Return: {avg_return:+.1f}%/yr")

    return oos_sharpes, oos_returns


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION D: ML with daily features (XGBoost purged CV)
# ══════════════════════════════════════════════════════════════════════════════

def build_daily_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature set for daily bars."""
    eps = 1e-10
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    bar_range = (h - l).clip(lower=eps)

    feat = pd.DataFrame(index=df.index)

    # Price action
    feat['body_ratio']  = (c - o) / bar_range
    feat['upper_wick']  = (h - np.maximum(o, c)) / bar_range
    feat['lower_wick']  = (np.minimum(o, c) - l) / bar_range

    # Returns at multiple horizons
    for n in [1, 2, 3, 5, 10, 20, 60]:
        feat[f'return_{n}d'] = c.pct_change(n, fill_method=None)

    # Volatility
    atr_5  = _atr_series(h, l, c, 5)
    atr_14 = _atr_series(h, l, c, 14)
    feat['atr_ratio'] = atr_5 / (atr_14 + eps)
    feat['atr_norm']  = atr_14 / (c + eps)
    feat['vol_5']     = c.pct_change().rolling(5).std()
    feat['vol_20']    = c.pct_change().rolling(20).std()
    feat['vol_ratio'] = feat['vol_5'] / (feat['vol_20'] + eps)
    feat['vol_60']    = c.pct_change().rolling(60).std()

    # Trend context
    ema20  = _ema(c, 20)
    ema50  = _ema(c, 50)
    ema200 = _ema(c, 200)
    feat['close_vs_ema20']  = c / (ema20 + eps) - 1
    feat['close_vs_ema50']  = c / (ema50 + eps) - 1
    feat['close_vs_ema200'] = c / (ema200 + eps) - 1
    feat['ema20_vs_50']     = ema20 / (ema50 + eps) - 1
    feat['ema50_vs_200']    = ema50 / (ema200 + eps) - 1

    # Oscillators
    feat['rsi_14'] = _rsi(c, 14) / 100 - 0.5
    feat['adx_14'] = _adx(h, l, c, 14)

    # Regime
    atr_mean50 = atr_14.rolling(50).mean()
    feat['vol_regime'] = atr_14 / (atr_mean50 + eps)
    high_20 = h.rolling(20).max()
    low_20  = l.rolling(20).min()
    feat['range_position'] = (c - low_20) / (high_20 - low_20 + eps)

    # Donchian position (where is price relative to N-day channel)
    feat['donchian_20_pos'] = (c - low_20) / (high_20 - low_20 + eps)
    high_60 = h.rolling(60).max()
    low_60  = l.rolling(60).min()
    feat['donchian_60_pos'] = (c - low_60) / (high_60 - low_60 + eps)

    # Consecutive bars
    _bull = (c > c.shift(1))
    _bear = (c < c.shift(1))
    _bull_grp = (~_bull).cumsum()
    _bear_grp = (~_bear).cumsum()
    bull_run = _bull.astype(int).groupby(_bull_grp).cumsum()
    bear_run = _bear.astype(int).groupby(_bear_grp).cumsum()
    feat['consecutive_up']   = bull_run.clip(upper=10) / 10
    feat['consecutive_down'] = bear_run.clip(upper=10) / 10

    # Distance to highs/lows in ATR
    feat['dist_to_20d_high'] = (high_20 - c) / (atr_14 + eps)
    feat['dist_to_20d_low']  = (c - low_20) / (atr_14 + eps)

    # Day of week
    dow = df.index.dayofweek
    feat['dow_sin'] = np.sin(2 * math.pi * dow / 5)
    feat['dow_cos'] = np.cos(2 * math.pi * dow / 5)

    # Microstructure (daily aggregates)
    if 'vol_imbalance_sum' in df.columns:
        feat['vol_imb'] = df['vol_imbalance_sum']
    if 'buy_ratio_mean' in df.columns:
        feat['buy_pressure'] = df['buy_ratio_mean'] - 0.5
    if 'tick_velocity_mean' in df.columns:
        feat['tick_vel'] = df['tick_velocity_mean']
    if 'avg_spread_mean' in df.columns:
        feat['avg_spread'] = df['avg_spread_mean']

    print(f"  Daily features: {len(feat.columns)}")
    return feat


def run_ml_cv(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("  SECTION D: XGBOOST PURGED CV (DAILY FEATURES)")
    print("=" * 70)

    feat = build_daily_features(df)
    feature_cols = feat.columns.tolist()

    h = df['high'].to_numpy()
    l = df['low'].to_numpy()
    c = df['close'].to_numpy()
    atr = _atr14(h, l, c)
    N = len(df)

    # Label: TP/SL simulation
    y_long  = np.full(N, np.nan)
    y_short = np.full(N, np.nan)

    for i in range(N - LOOKAHEAD):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        h_path = h[i + 1: i + 1 + LOOKAHEAD]
        l_path = l[i + 1: i + 1 + LOOKAHEAD]

        entry_l = c[i] + SPREAD_EST
        tp_l = entry_l + a * TP_ATR
        sl_l = entry_l - a * SL_ATR
        sl_hit_l = np.where(l_path <= sl_l)[0]
        tp_hit_l = np.where(h_path >= tp_l)[0]
        i_sl_l = sl_hit_l[0] if len(sl_hit_l) > 0 else LOOKAHEAD
        i_tp_l = tp_hit_l[0] if len(tp_hit_l) > 0 else LOOKAHEAD
        y_long[i] = 1.0 if (i_tp_l < i_sl_l and i_tp_l < LOOKAHEAD) else 0.0

        entry_s = c[i] - SPREAD_EST
        tp_s = entry_s - a * TP_ATR
        sl_s = entry_s + a * SL_ATR
        sl_hit_s = np.where(h_path >= sl_s)[0]
        tp_hit_s = np.where(l_path <= tp_s)[0]
        i_sl_s = sl_hit_s[0] if len(sl_hit_s) > 0 else LOOKAHEAD
        i_tp_s = tp_hit_s[0] if len(tp_hit_s) > 0 else LOOKAHEAD
        y_short[i] = 1.0 if (i_tp_s < i_sl_s and i_tp_s < LOOKAHEAD) else 0.0

    valid = np.isfinite(y_long)
    print(f"  Valid labeled: {valid.sum():,} / {N:,}")
    print(f"  Long  base rate: {y_long[valid].mean() * 100:.1f}%")
    print(f"  Short base rate: {y_short[valid].mean() * 100:.1f}%")
    print(f"  Break-even WR:   {BE_WR * 100:.1f}%")

    X = feat.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    warmup = 200
    X = X[warmup:]
    y_l = y_long[warmup:]
    y_s = y_short[warmup:]

    # Purged CV
    def _cv(X, y, label):
        n = len(X)
        fold_size = n // 5
        results = []
        for fold in range(4):
            train_end = fold_size * (fold + 1)
            test_start = train_end + PURGE_GAP
            test_end = test_start + fold_size
            if test_end > n:
                break
            X_tr, y_tr = X[:train_end], y[:train_end]
            X_te, y_te = X[test_start:test_end], y[test_start:test_end]
            vtr = np.isfinite(y_tr); vte = np.isfinite(y_te)
            X_tr, y_tr = X_tr[vtr], y_tr[vtr]
            X_te, y_te = X_te[vte], y_te[vte]
            if len(X_tr) < 200 or len(X_te) < 50:
                continue
            pos_c = (y_tr == 1).sum()
            neg_c = (y_tr == 0).sum()
            sw = neg_c / (pos_c + 1e-10)
            model = XGBClassifier(
                max_depth=3, learning_rate=0.05, n_estimators=200,
                subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
                eval_metric="logloss", verbosity=0, random_state=42,
                scale_pos_weight=sw,
            )
            model.fit(X_tr, y_tr)
            prob = model.predict_proba(X_te)[:, 1]
            auc = roc_auc_score(y_te, prob)
            br = y_te.mean()
            # WR at thresholds
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
            print(f"    → {label} AVG AUC: {avg:.4f}")
        return results

    print(f"\n--- LONG ---")
    res_long = _cv(X, y_l, "LONG")
    print(f"\n--- SHORT ---")
    res_short = _cv(X, y_s, "SHORT")

    # Feature importance
    if res_long:
        model = res_long[-1]["model"]
        imp = model.feature_importances_
        top_idx = np.argsort(imp)[::-1][:15]
        print(f"\n  TOP 15 DAILY FEATURES (LONG):")
        for rank, idx in enumerate(top_idx, 1):
            print(f"    {rank:>2}. {feature_cols[idx]:<25s}  {imp[idx]:.4f}")

    return res_long, res_short


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION E: Yearly consistency & regime analysis
# ══════════════════════════════════════════════════════════════════════════════

def regime_analysis(df: pd.DataFrame, all_stats: dict):
    print("\n" + "=" * 70)
    print("  SECTION E: REGIME ANALYSIS")
    print("=" * 70)

    c = df['close']
    atr14 = _atr_series(df['high'], df['low'], c, 14)
    vol_regime = atr14 / atr14.rolling(50).mean()

    # Split into high-vol and low-vol regimes
    median_vol = vol_regime.median()
    high_vol = vol_regime > median_vol
    low_vol = ~high_vol

    ema50 = _ema(c, 50)
    ema200 = _ema(c, 200)
    ema_signal = pd.Series(np.where(ema50 > ema200, 1.0, -1.0), index=c.index)
    ema_pos = ema_signal.shift(1).fillna(0)
    daily_ret = c.pct_change()

    for regime_name, regime_mask in [("High Vol", high_vol), ("Low Vol", low_vol)]:
        r = daily_ret[regime_mask] * ema_pos[regime_mask]
        r = r.dropna()
        if len(r) < 50:
            continue
        sharpe = _sharpe(r)
        ann_ret = r.mean() * ANNUAL_TRADING_DAYS * 100
        print(f"\n  EMA 50/200 in {regime_name} regime ({regime_mask.sum():,} days):")
        print(f"    Sharpe: {sharpe:+.3f}   Ann Ret: {ann_ret:+.1f}%")

    # Trending vs ranging (ADX-based)
    adx = _adx(df['high'], df['low'], c, 14)
    trending = adx > 0.25  # ADX > 25 = strong trend
    ranging = ~trending

    for regime_name, regime_mask in [("Trending (ADX>25)", trending),
                                      ("Ranging (ADX≤25)", ranging)]:
        r = daily_ret[regime_mask] * ema_pos[regime_mask]
        r = r.dropna()
        if len(r) < 50:
            continue
        sharpe = _sharpe(r)
        ann_ret = r.mean() * ANNUAL_TRADING_DAYS * 100
        days_pct = regime_mask.sum() / len(regime_mask) * 100
        print(f"\n  EMA 50/200 in {regime_name} ({regime_mask.sum():,} days, {days_pct:.0f}%):")
        print(f"    Sharpe: {sharpe:+.3f}   Ann Ret: {ann_ret:+.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION F: Verdict
# ══════════════════════════════════════════════════════════════════════════════

def print_verdict(all_stats: dict, oos_sharpes: list, oos_returns: list,
                  res_long: list, res_short: list):
    print("\n" + "=" * 70)
    print("  SECTION F: FINAL VERDICT — XAUUSD DAILY SIGNAL AUDIT")
    print("=" * 70)

    # Strategy comparison
    print(f"\n  TREND-FOLLOWING STRATEGIES:")
    print(f"  {'Strategy':<30s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 55)
    for key in ["Buy & Hold", "EMA 50/200", "EMA 50/200 LO", "Donchian 20",
                "Donchian 20 LO", "Mom 20", "Mom 60", "Combined", "EMA+ATR"]:
        s = all_stats[key]
        print(f"  {key:<30s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # OOS summary
    win_years = sum(1 for r in oos_returns if r > 0)
    print(f"\n  OOS YEARLY CONSISTENCY:")
    print(f"    Win years: {win_years}/{len(oos_returns)}")
    print(f"    Avg OOS Sharpe: {np.mean(oos_sharpes):+.3f}")

    # ML summary
    ml_aucs = {}
    if res_long:
        ml_aucs["ML LONG"] = np.mean([r["auc"] for r in res_long])
    if res_short:
        ml_aucs["ML SHORT"] = np.mean([r["auc"] for r in res_short])
    if ml_aucs:
        print(f"\n  ML (XGBoost) DAILY DIRECTION PREDICTION:")
        for name, auc in ml_aucs.items():
            print(f"    {name}: AUC={auc:.4f}  ({(auc-0.5)*100:+.1f}pp vs random)")

    # Best strategy
    best_key = max([k for k in all_stats if k != "Buy & Hold"],
                   key=lambda k: all_stats[k]["sharpe"])
    best = all_stats[best_key]

    print(f"\n  {'─' * 60}")
    if best["sharpe"] > 0.3:
        print(f"  VERDICT: ✅ TRADEABLE EDGE EXISTS on XAUUSD daily")
        print(f"  Best: {best_key} — Sharpe {best['sharpe']:+.3f}, {best['ann_ret']:+.1f}%/yr")
        if best["sharpe"] > 0.5:
            print(f"  STRONG signal — worth pursuing for live implementation")
        else:
            print(f"  MODERATE signal — consider combining with regime filter")
        print(f"\n  NEXT STEPS:")
        print(f"    1. Optimize lookback periods (walk-forward)")
        print(f"    2. Add vol-targeting / ATR sizing")
        print(f"    3. Test regime filter (only trade when ADX > 20)")
        print(f"    4. Multi-asset portfolio (gold + other commodities)")
    elif best["sharpe"] > 0.1:
        print(f"  VERDICT: ⚠️  WEAK EDGE on XAUUSD daily")
        print(f"  Best: {best_key} — Sharpe {best['sharpe']:+.3f}")
        print(f"  Edge exists but may not survive transaction costs at scale")
    else:
        print(f"  VERDICT: ❌ NO EDGE on XAUUSD daily")
        print(f"  Even daily trend-following shows no edge for gold")
        print(f"  Gold may require fundamental/macro approach")

    print("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    df = load_and_resample()
    all_stats = run_trend_strategies(df)
    oos_sharpes, oos_returns = walk_forward_oos(df)
    res_long, res_short = run_ml_cv(df)
    regime_analysis(df, all_stats)
    print_verdict(all_stats, oos_sharpes, oos_returns, res_long, res_short)

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s ({elapsed / 60:.1f}m)")


if __name__ == "__main__":
    main()
