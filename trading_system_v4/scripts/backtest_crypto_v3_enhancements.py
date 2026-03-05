"""
Crypto Signal Enhancement Investigation (v3)
=============================================
Can we combat the trend-following edge decay (rolling SR dropped 2.1→0.7)?

Enhancements tested:
  1. Adaptive lookback — shorter in high-vol, longer in low-vol
  2. Multi-timeframe confirmation — require both short + long trend aligned
  3. Momentum acceleration — rate-of-change of momentum (2nd derivative)
  4. Trend strength filter — only trade strong trends (slope/vol ratio)
  5. RSI overbought filter — reduce position when RSI extreme
  6. Cross-asset confirmation — BTC must confirm before alts trade
  7. Drawdown protection — reduce exposure during equity DD
  8. Mean reversion overlay — fade entry slightly if too extended
  9. Volatility breakout filter — only enter on vol expansion
  10. Calendar filter — skip historically weak months
  11. Adaptive EMA — speed up/slow down based on noise ratio

All tested on:
  - Full period (2017-2025) — headline numbers
  - Recent period (2023-2025) — does it help WHERE WE NEED IT?
  - 2021-2022 — the problem period (boom-bust)
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from typing import Tuple


# ─── Load data (reuse from v2) ──────────────────────────────────────────────

def load_crypto_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    highs = pd.read_parquet("trading_system_v4/data/crypto_daily_high.parquet")
    lows = pd.read_parquet("trading_system_v4/data/crypto_daily_low.parquet")
    print(f"  Data: {len(closes)} days x {len(closes.columns)} cryptos")
    print(f"  Range: {closes.index[0].date()} to {closes.index[-1].date()}")
    return closes, highs, lows


# ─── Core backtest ──────────────────────────────────────────────────────────

def bt(prices: pd.Series, signal: pd.Series,
       vol_target: float = 0.15, cost_bps: float = 10.0) -> dict:
    """Compact single-asset backtest returning stats dict."""
    ret = prices.pct_change()
    vol = ret.rolling(20).std() * np.sqrt(365)

    position = signal * vol_target / vol.clip(lower=0.01)
    position = position.clip(0, 2.0)   # long-only, max 2x

    pnl = position.shift(1) * ret
    turnover = position.diff().abs()
    costs = turnover * (cost_bps / 10000)
    net = pnl - costs

    valid_sig = signal.abs() > 0
    if not valid_sig.any():
        return {"sharpe": float("nan"), "ann_ret": 0, "max_dd": 0,
                "trades_yr": 0, "n_years": 0}
    first = valid_sig[valid_sig].index[0]
    net = net[first:].fillna(0)
    costs = costs[first:].fillna(0)
    signal_trimmed = signal[first:]

    if len(net) < 100:
        return {"sharpe": float("nan"), "ann_ret": 0, "max_dd": 0,
                "trades_yr": 0, "n_years": 0}

    equity = (1 + net).cumprod()
    total = equity.iloc[-1] - 1
    n_yr = len(net) / 365
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if (n_yr > 0 and total > -1) else -1.0
    ann_vol = net.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    dd = (equity / equity.cummax() - 1).min()
    monthly_wr = ((net.resample("ME").sum()) > 0).mean()

    n_trades = (signal_trimmed.diff().abs() > 0).sum()
    trades_yr = n_trades / n_yr if n_yr > 0 else 0

    # Yearly breakdown
    yearly = net.groupby(net.index.year).apply(
        lambda x: pd.Series({
            "ret": (1 + x).prod() - 1,
            "sr": x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        })
    )

    return {
        "sharpe": sharpe, "ann_ret": ann_ret, "ann_vol": ann_vol,
        "max_dd": dd, "monthly_wr": monthly_wr,
        "trades_yr": trades_yr, "n_years": n_yr,
        "total_costs": costs.sum(),
        "net_pnl": net, "equity": equity, "yearly": yearly,
    }


def bt_multi(closes: pd.DataFrame, signals: pd.DataFrame,
             vol_target: float = 0.15, cost_bps: float = 10.0) -> dict:
    """Multi-asset long-only backtest."""
    returns = closes.pct_change()
    asset_vol = returns.rolling(20).std() * np.sqrt(365)

    valid = closes.notna() & signals.notna() & (asset_vol > 0.01)
    sig = signals.where(valid, 0).clip(lower=0)   # long-only

    n_active = (sig.abs() > 0).sum(axis=1).clip(lower=1)
    w = sig * (vol_target / n_active.values[:, None]) / asset_vol.clip(lower=0.01)
    w = w.clip(0, 2.0 / max(len(closes.columns), 1))
    total_lev = w.sum(axis=1)
    scale = (2.0 / total_lev).clip(upper=1.0)
    positions = w.multiply(scale, axis=0)

    pnl = (positions.shift(1) * returns).sum(axis=1)
    turnover = positions.diff().abs().sum(axis=1)
    costs = turnover * (cost_bps / 10000)
    net = pnl - costs

    first_valid = (sig.abs().sum(axis=1) > 0)
    if not first_valid.any():
        return {"sharpe": float("nan")}
    first = first_valid[first_valid].index[0]
    net = net[first:].fillna(0)
    costs = costs[first:].fillna(0)

    if len(net) < 100:
        return {"sharpe": float("nan")}

    equity = (1 + net).cumprod()
    total = equity.iloc[-1] - 1
    n_yr = len(net) / 365
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if (n_yr > 0 and total > -1) else -1.0
    ann_vol = net.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    dd = (equity / equity.cummax() - 1).min()

    n_trades = (sig.diff().abs().sum(axis=1) > 0).sum()
    trades_yr = n_trades / n_yr if n_yr > 0 else 0

    yearly = net.groupby(net.index.year).apply(
        lambda x: pd.Series({
            "ret": (1 + x).prod() - 1,
            "sr": x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        })
    )

    return {
        "sharpe": sharpe, "ann_ret": ann_ret, "ann_vol": ann_vol,
        "max_dd": dd, "trades_yr": trades_yr, "n_years": n_yr,
        "total_costs": costs.sum(), "net_pnl": net, "equity": equity,
        "yearly": yearly,
    }


# ─── BASELINE SIGNALS ──────────────────────────────────────────────────────

def sig_trend(p, lb=20):
    return (p.pct_change(lb) > 0).astype(float)

def sig_ema_cross(p, fast=10, slow=30):
    return (p.ewm(span=fast, adjust=False).mean() >
            p.ewm(span=slow, adjust=False).mean()).astype(float)


# ─── ENHANCED SIGNALS ──────────────────────────────────────────────────────

def sig_adaptive_lookback(p, short_lb=10, long_lb=40, vol_window=20):
    """
    Use shorter lookback in high-vol regimes (trends move faster),
    longer lookback in low-vol regimes (trends are slower).
    """
    ret = p.pct_change()
    vol = ret.rolling(vol_window).std()
    vol_ma = vol.rolling(vol_window * 5).mean()
    vol_ratio = (vol / vol_ma.clip(lower=1e-8)).clip(0.5, 2.0)

    # Interpolate lookback: high vol → short_lb, low vol → long_lb
    # vol_ratio=1 → mid, >1 → shorter, <1 → longer
    lb = long_lb + (short_lb - long_lb) * (vol_ratio - 0.5) / 1.5
    lb = lb.clip(short_lb, long_lb).fillna(long_lb).round().astype(int)

    sig = pd.Series(0.0, index=p.index)
    for i in range(long_lb, len(p)):
        lookback = lb.iloc[i]
        if p.iloc[i] > p.iloc[i - lookback]:
            sig.iloc[i] = 1.0
    return sig


def sig_mtf_confirmation(p, short_lb=10, long_lb=40):
    """
    Multi-timeframe: require BOTH short-term and long-term trend to agree.
    Only long when both 10d and 40d trends are up.
    """
    short_trend = (p.pct_change(short_lb) > 0).astype(float)
    long_trend = (p.pct_change(long_lb) > 0).astype(float)
    return (short_trend * long_trend)


def sig_mtf_3level(p, fast=5, mid=20, slow=60):
    """
    3-level MTF: fast + mid + slow must all agree. Very selective.
    """
    f = (p.pct_change(fast) > 0).astype(float)
    m = (p.pct_change(mid) > 0).astype(float)
    s = (p.pct_change(slow) > 0).astype(float)
    return (f * m * s)


def sig_momentum_acceleration(p, lb=20, accel_lb=5):
    """
    Standard trend + momentum acceleration filter.
    Only enter when momentum is INCREASING (2nd derivative positive).
    """
    trend = (p.pct_change(lb) > 0).astype(float)
    mom = p.pct_change(lb)
    mom_accel = mom.diff(accel_lb)
    # Only enter when trend up AND momentum accelerating
    return trend * (mom_accel > 0).astype(float)


def sig_trend_strength(p, lb=20, min_strength=0.5):
    """
    Trend strength filter: normalize momentum by volatility.
    Only enter when trend is strong relative to noise.
    t-stat of returns over lookback.
    """
    ret = p.pct_change()
    rolling_mean = ret.rolling(lb).mean()
    rolling_std = ret.rolling(lb).std()
    t_stat = rolling_mean / rolling_std.clip(lower=1e-8) * np.sqrt(lb)

    # Long when t-stat > threshold (strong uptrend)
    return (t_stat > min_strength).astype(float)


def sig_trend_with_rsi_filter(p, lb=20, rsi_period=14, rsi_cap=75):
    """
    Standard trend, but reduce signal when RSI > cap (overbought).
    Idea: avoid buying into blow-off tops.
    """
    trend = (p.pct_change(lb) > 0).astype(float)

    delta = p.diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.clip(lower=1e-8)
    rsi = 100 - 100 / (1 + rs)

    # Full signal below cap, reduced above
    signal = trend.copy()
    signal[rsi > rsi_cap] = 0.5     # half position when overbought
    signal[rsi > 85] = 0.0          # exit when extremely overbought
    return signal


def sig_trend_rsi_entry(p, lb=20, rsi_period=14, rsi_floor=40, rsi_cap=70):
    """
    Only ENTER when trend is up AND RSI is in sweet spot (not overbought,
    not deeply oversold). Hold until trend flips.
    """
    trend = (p.pct_change(lb) > 0).astype(float)

    delta = p.diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.clip(lower=1e-8)
    rsi = 100 - 100 / (1 + rs)

    # Entry: trend up & RSI in sweet spot
    entry = trend * ((rsi > rsi_floor) & (rsi < rsi_cap)).astype(float)
    # Hold: stay in while trend is up, exit when trend flips
    sig = pd.Series(0.0, index=p.index)
    in_pos = False
    for i in range(1, len(p)):
        if not in_pos:
            if entry.iloc[i] > 0:
                sig.iloc[i] = 1.0
                in_pos = True
        else:
            if trend.iloc[i] > 0:
                sig.iloc[i] = 1.0
            else:
                in_pos = False
    return sig


def sig_drawdown_protection(p, lb=20, dd_threshold=-0.10, reduce_factor=0.5):
    """
    Baseline trend, but reduce position when strategy equity is in drawdown.
    """
    trend = (p.pct_change(lb) > 0).astype(float)

    # Simulate a quick equity curve to detect DD
    ret = p.pct_change()
    vol = ret.rolling(20).std() * np.sqrt(365)
    pos = trend * 0.15 / vol.clip(lower=0.01)
    pos = pos.clip(0, 2)
    pnl = (pos.shift(1) * ret).fillna(0)
    eq = (1 + pnl).cumprod()
    dd = eq / eq.cummax() - 1

    # Enhanced signal: reduce in DD
    signal = trend.copy()
    signal[dd < dd_threshold] = reduce_factor
    signal[dd < dd_threshold * 2] = 0  # exit in deep DD
    return signal


def sig_vol_breakout_confirm(p, lb=20, vol_lookback=20, vol_mult=1.2):
    """
    Trend + volume breakout: only enter when recent vol > avg vol.
    Idea: real breakouts come with increased volatility.
    """
    trend = (p.pct_change(lb) > 0).astype(float)
    ret = p.pct_change()
    vol = ret.abs().rolling(vol_lookback).mean()
    vol_avg = ret.abs().rolling(vol_lookback * 5).mean()
    vol_expanding = (vol > vol_avg * vol_mult).astype(float)

    return trend * vol_expanding


def sig_calendar_filter(p, lb=20, bad_months=None):
    """
    Trend + skip historically weak months.
    """
    if bad_months is None:
        bad_months = []  # will determine empirically
    trend = (p.pct_change(lb) > 0).astype(float)
    month = p.index.month
    month_mask = ~pd.Series(month, index=p.index).isin(bad_months)
    return trend * month_mask.astype(float)


def sig_kaufman_ama(p, fast_period=2, slow_period=30, lookback=10):
    """
    Kaufman Adaptive Moving Average (KAMA).
    Adapts speed based on efficiency ratio (signal/noise).
    """
    direction = (p - p.shift(lookback)).abs()
    volatility = p.diff().abs().rolling(lookback).sum()
    er = direction / volatility.clip(lower=1e-8)  # efficiency ratio

    fast_sc = 2 / (fast_period + 1)
    slow_sc = 2 / (slow_period + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    kama = pd.Series(np.nan, index=p.index)
    kama.iloc[lookback] = p.iloc[lookback]
    for i in range(lookback + 1, len(p)):
        kama.iloc[i] = kama.iloc[i-1] + sc.iloc[i] * (p.iloc[i] - kama.iloc[i-1])

    return (p > kama).astype(float)


def sig_dual_ema_with_atr_stop(p, fast=10, slow=30, atr_mult=2.0, atr_period=14):
    """
    EMA crossover entry, but use ATR trailing stop for exit.
    More responsive exit than waiting for crossover to flip.
    """
    ema_f = p.ewm(span=fast, adjust=False).mean()
    ema_s = p.ewm(span=slow, adjust=False).mean()

    # ATR
    high_low = p.rolling(2).max() - p.rolling(2).min()  # proxy without H/L
    atr = high_low.rolling(atr_period).mean()

    sig = pd.Series(0.0, index=p.index)
    in_pos = False
    trail_stop = 0.0

    for i in range(slow, len(p)):
        if not in_pos:
            if ema_f.iloc[i] > ema_s.iloc[i]:
                sig.iloc[i] = 1.0
                in_pos = True
                trail_stop = p.iloc[i] - atr.iloc[i] * atr_mult
        else:
            # Update trailing stop
            new_stop = p.iloc[i] - atr.iloc[i] * atr_mult
            trail_stop = max(trail_stop, new_stop)

            if p.iloc[i] < trail_stop:
                # Stopped out
                in_pos = False
            else:
                sig.iloc[i] = 1.0
    return sig


def sig_cross_asset_confirm(p, btc, lb=20):
    """
    Only go long alt when BOTH alt trend AND BTC trend are up.
    BTC as market leader confirmation.
    """
    alt_trend = (p.pct_change(lb) > 0).astype(float)
    btc_trend = (btc.pct_change(lb) > 0).astype(float).reindex(p.index).ffill()
    return alt_trend * btc_trend


def sig_regime_switch(p, lb_bull=15, lb_bear=40):
    """
    Use different lookbacks based on regime.
    Bull regime (above 60d SMA): use shorter lookback (more responsive).
    Bear regime (below 60d SMA): use longer lookback (more conservative).
    """
    regime_line = p.rolling(60).mean()
    is_bull = p > regime_line

    short_sig = (p.pct_change(lb_bull) > 0).astype(float)
    long_sig = (p.pct_change(lb_bear) > 0).astype(float)

    sig = long_sig.copy()
    sig[is_bull] = short_sig[is_bull]
    return sig


def sig_percentile_breakout(p, lookback=60, pct=75):
    """
    Long when price is above the N-th percentile of last `lookback` days.
    More robust than simple trend — less affected by single outlier days.
    """
    rolling_pct = p.rolling(lookback).quantile(pct / 100)
    return (p > rolling_pct).astype(float)


def sig_trend_with_mean_distance(p, lb=20, max_dist=1.5):
    """
    Trend + mean reversion guard: don't enter if price is too far
    above its moving average (> max_dist standard deviations).
    Idea: avoid buying blow-off tops.
    """
    trend = (p.pct_change(lb) > 0).astype(float)
    ma = p.rolling(lb * 2).mean()
    std = p.rolling(lb * 2).std()
    z = (p - ma) / std.clip(lower=1e-8)

    signal = trend.copy()
    signal[z > max_dist] = 0.5   # reduce when extended
    signal[z > max_dist * 1.5] = 0   # exit when very extended
    return signal


# ─── Test harness ────────────────────────────────────────────────────────────

def test_signal(label: str, prices: pd.Series, signal: pd.Series,
                show_yearly: bool = False):
    """Test on full + sub-periods, print row."""
    full = bt(prices, signal)

    # Sub-periods
    sub_2122 = bt(prices["2021":"2022"], signal["2021":"2022"])
    sub_2325 = bt(prices["2023":"2025"], signal["2023":"2025"])
    sub_2025 = bt(prices["2025":"2025"], signal["2025":"2025"])

    def sr(r):
        s = r.get("sharpe", float("nan"))
        return f"{s:+.2f}" if not np.isnan(s) else "  N/A"

    def ret(r):
        a = r.get("ann_ret", 0)
        return f"{a*100:+.1f}%" if a != 0 else "   N/A"

    def dd(r):
        d = r.get("max_dd", 0)
        return f"{d*100:.1f}%" if d != 0 else "  N/A"

    print(f"  {label:42s}  {sr(full)}  {ret(full):>8}  {dd(full):>7}  "
          f"{full.get('trades_yr',0):>5.0f}  │ {sr(sub_2122)}  {sr(sub_2325)}  {sr(sub_2025)}")

    if show_yearly and "yearly" in full and full["yearly"] is not None:
        for yr, row in full["yearly"].iterrows():
            print(f"    {yr}: ret={row['ret']*100:+.1f}%, sr={row['sr']:.2f}")

    return full


def test_multi_signal(label: str, closes: pd.DataFrame,
                      signals: pd.DataFrame):
    """Test multi-asset version."""
    full = bt_multi(closes, signals)
    sub_2122 = bt_multi(closes["2021":"2022"], signals["2021":"2022"])
    sub_2325 = bt_multi(closes["2023":"2025"], signals["2023":"2025"])
    sub_2025 = bt_multi(closes["2025":"2025"], signals["2025":"2025"])

    def sr(r):
        s = r.get("sharpe", float("nan"))
        return f"{s:+.2f}" if not np.isnan(s) else "  N/A"

    def ret(r):
        a = r.get("ann_ret", 0)
        return f"{a*100:+.1f}%" if a != 0 else "   N/A"

    def dd(r):
        d = r.get("max_dd", 0)
        return f"{d*100:.1f}%" if d != 0 else "  N/A"

    print(f"  {label:42s}  {sr(full)}  {ret(full):>8}  {dd(full):>7}  "
          f"{full.get('trades_yr',0):>5.0f}  │ {sr(sub_2122)}  {sr(sub_2325)}  {sr(sub_2025)}")
    return full


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    closes, highs, lows = load_crypto_data()
    btc = closes["BTC-USD"].dropna()

    header = (f"  {'Signal':42s}  {'SR':>5}  {'AnnRet':>8}  {'MaxDD':>7}  "
              f"{'Tr/y':>5}  │ {'21-22':>5}  {'23-25':>5}  {'2025':>5}")
    sep = "  " + "-" * 42 + "  -----  --------  -------  -----  │ -----  -----  -----"

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  A. BTC-ONLY SIGNAL ENHANCEMENTS")
    print("█" * 70)
    print(header)
    print(sep)

    # ── Baselines ──
    print("  --- BASELINES ---")
    test_signal("Baseline: Trend 20d", btc, sig_trend(btc, 20))
    test_signal("Baseline: Trend 40d", btc, sig_trend(btc, 40))
    test_signal("Baseline: EMA(10/30)", btc, sig_ema_cross(btc, 10, 30))

    # ── 1. Adaptive lookback ──
    print("  --- ADAPTIVE LOOKBACK ---")
    test_signal("Adaptive LB (10-40, vol-based)", btc,
                sig_adaptive_lookback(btc, 10, 40, 20))
    test_signal("Adaptive LB (15-60, vol-based)", btc,
                sig_adaptive_lookback(btc, 15, 60, 20))

    # ── 2. Multi-timeframe confirmation ──
    print("  --- MULTI-TIMEFRAME ---")
    test_signal("MTF: 10d + 40d aligned", btc,
                sig_mtf_confirmation(btc, 10, 40))
    test_signal("MTF: 10d + 60d aligned", btc,
                sig_mtf_confirmation(btc, 10, 60))
    test_signal("MTF: 20d + 60d aligned", btc,
                sig_mtf_confirmation(btc, 20, 60))
    test_signal("MTF 3-level: 5d + 20d + 60d", btc,
                sig_mtf_3level(btc, 5, 20, 60))
    test_signal("MTF 3-level: 10d + 30d + 90d", btc,
                sig_mtf_3level(btc, 10, 30, 90))

    # ── 3. Momentum acceleration ──
    print("  --- MOMENTUM ACCELERATION ---")
    test_signal("Mom accel: 20d trend + 5d accel", btc,
                sig_momentum_acceleration(btc, 20, 5))
    test_signal("Mom accel: 20d trend + 10d accel", btc,
                sig_momentum_acceleration(btc, 20, 10))
    test_signal("Mom accel: 40d trend + 10d accel", btc,
                sig_momentum_acceleration(btc, 40, 10))

    # ── 4. Trend strength ──
    print("  --- TREND STRENGTH ---")
    test_signal("Trend strength t>0.5 (20d)", btc,
                sig_trend_strength(btc, 20, 0.5))
    test_signal("Trend strength t>0.75 (20d)", btc,
                sig_trend_strength(btc, 20, 0.75))
    test_signal("Trend strength t>1.0 (20d)", btc,
                sig_trend_strength(btc, 20, 1.0))
    test_signal("Trend strength t>0.5 (40d)", btc,
                sig_trend_strength(btc, 40, 0.5))

    # ── 5. RSI filters ──
    print("  --- RSI FILTERS ---")
    test_signal("Trend20 + RSI cap 75", btc,
                sig_trend_with_rsi_filter(btc, 20, 14, 75))
    test_signal("Trend20 + RSI cap 70", btc,
                sig_trend_with_rsi_filter(btc, 20, 14, 70))
    test_signal("RSI sweet-spot entry (40-70)", btc,
                sig_trend_rsi_entry(btc, 20, 14, 40, 70))
    test_signal("RSI sweet-spot entry (30-65)", btc,
                sig_trend_rsi_entry(btc, 20, 14, 30, 65))

    # ── 6. Drawdown protection ──
    print("  --- DRAWDOWN PROTECTION ---")
    test_signal("DD protect: -10% reduce, -20% exit", btc,
                sig_drawdown_protection(btc, 20, -0.10, 0.5))
    test_signal("DD protect: -7% reduce, -15% exit", btc,
                sig_drawdown_protection(btc, 20, -0.07, 0.5))
    test_signal("DD protect: -15% reduce, -30% exit", btc,
                sig_drawdown_protection(btc, 20, -0.15, 0.5))

    # ── 7. Vol breakout confirmation ──
    print("  --- VOL BREAKOUT CONFIRM ---")
    test_signal("Trend20 + vol expansion (1.2x)", btc,
                sig_vol_breakout_confirm(btc, 20, 20, 1.2))
    test_signal("Trend20 + vol expansion (1.0x)", btc,
                sig_vol_breakout_confirm(btc, 20, 20, 1.0))
    test_signal("Trend20 + vol expansion (1.5x)", btc,
                sig_vol_breakout_confirm(btc, 20, 20, 1.5))

    # ── 8. Calendar filter ──
    print("  --- CALENDAR FILTER ---")
    # First, find which months are historically weak for trend-following
    print("    (Monthly P&L of Trend20d baseline:)")
    r_base = bt(btc, sig_trend(btc, 20))
    if "net_pnl" in r_base:
        monthly_by_month = r_base["net_pnl"].groupby(r_base["net_pnl"].index.month).mean() * 30
        for m in range(1, 13):
            v = monthly_by_month.get(m, 0)
            bar = "+" * int(max(0, v * 500)) + "-" * int(max(0, -v * 500))
            print(f"      Month {m:>2}: {v*100:+.3f}%  {bar}")

    # Skip worst months
    test_signal("Skip months: Jun, Sep", btc,
                sig_calendar_filter(btc, 20, [6, 9]))
    test_signal("Skip months: Jun, Sep, Nov", btc,
                sig_calendar_filter(btc, 20, [6, 9, 11]))

    # ── 9. Kaufman AMA ──
    print("  --- ADAPTIVE MOVING AVERAGE ---")
    test_signal("Kaufman AMA (2/30/10)", btc,
                sig_kaufman_ama(btc, 2, 30, 10))
    test_signal("Kaufman AMA (2/30/20)", btc,
                sig_kaufman_ama(btc, 2, 30, 20))

    # ── 10. ATR trailing stop ──
    print("  --- ATR TRAILING STOP ---")
    test_signal("EMA(10/30) + ATR stop 2.0x", btc,
                sig_dual_ema_with_atr_stop(btc, 10, 30, 2.0))
    test_signal("EMA(10/30) + ATR stop 2.5x", btc,
                sig_dual_ema_with_atr_stop(btc, 10, 30, 2.5))
    test_signal("EMA(10/30) + ATR stop 3.0x", btc,
                sig_dual_ema_with_atr_stop(btc, 10, 30, 3.0))

    # ── 11. Regime switching ──
    print("  --- REGIME SWITCH ---")
    test_signal("Regime switch (15d bull / 40d bear)", btc,
                sig_regime_switch(btc, 15, 40))
    test_signal("Regime switch (10d bull / 30d bear)", btc,
                sig_regime_switch(btc, 10, 30))
    test_signal("Regime switch (10d bull / 60d bear)", btc,
                sig_regime_switch(btc, 10, 60))

    # ── 12. Percentile breakout ──
    print("  --- PERCENTILE BREAKOUT ---")
    test_signal("60d 75th percentile breakout", btc,
                sig_percentile_breakout(btc, 60, 75))
    test_signal("40d 70th percentile breakout", btc,
                sig_percentile_breakout(btc, 40, 70))
    test_signal("90d 80th percentile breakout", btc,
                sig_percentile_breakout(btc, 90, 80))

    # ── 13. Mean-distance guard ──
    print("  --- MEAN-DISTANCE GUARD ---")
    test_signal("Trend20 + z-cap 1.5σ", btc,
                sig_trend_with_mean_distance(btc, 20, 1.5))
    test_signal("Trend20 + z-cap 2.0σ", btc,
                sig_trend_with_mean_distance(btc, 20, 2.0))
    test_signal("Trend20 + z-cap 1.0σ", btc,
                sig_trend_with_mean_distance(btc, 20, 1.0))

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  B. BEST ENHANCEMENTS → MULTI-CRYPTO PORTFOLIO")
    print("█" * 70)
    print(header)
    print(sep)

    # Baseline multi-crypto
    sig_m_base = pd.DataFrame({
        col: sig_trend(closes[col].dropna(), 20).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Baseline: Multi Trend 20d", closes, sig_m_base)

    # MTF confirmation multi
    sig_m_mtf = pd.DataFrame({
        col: sig_mtf_confirmation(closes[col].dropna(), 10, 40).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi MTF (10d+40d)", closes, sig_m_mtf)

    # MTF 3-level multi
    sig_m_mtf3 = pd.DataFrame({
        col: sig_mtf_3level(closes[col].dropna(), 5, 20, 60).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi MTF 3-level (5+20+60)", closes, sig_m_mtf3)

    # Trend strength multi
    sig_m_ts = pd.DataFrame({
        col: sig_trend_strength(closes[col].dropna(), 20, 0.5).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Trend Strength t>0.5", closes, sig_m_ts)

    # RSI filter multi
    sig_m_rsi = pd.DataFrame({
        col: sig_trend_with_rsi_filter(closes[col].dropna(), 20, 14, 75).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Trend20 + RSI cap 75", closes, sig_m_rsi)

    # Adaptive lookback multi
    sig_m_alb = pd.DataFrame({
        col: sig_adaptive_lookback(closes[col].dropna(), 10, 40, 20).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Adaptive LB (10-40)", closes, sig_m_alb)

    # Cross-asset (BTC) confirmation for alts
    btc_full = closes["BTC-USD"].dropna()
    sig_m_xconf = pd.DataFrame({
        col: sig_cross_asset_confirm(
            closes[col].dropna(), btc_full, 20
        ).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Cross-asset (BTC confirm)", closes, sig_m_xconf)

    # Regime switch multi
    sig_m_regime = pd.DataFrame({
        col: sig_regime_switch(closes[col].dropna(), 15, 40).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Regime Switch (15/40)", closes, sig_m_regime)

    # Kaufman AMA multi
    sig_m_kama = pd.DataFrame({
        col: sig_kaufman_ama(closes[col].dropna(), 2, 30, 10).reindex(closes.index)
        for col in closes.columns
    })
    test_multi_signal("Multi Kaufman AMA", closes, sig_m_kama)

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  C. COMBO STRATEGIES (stack multiple enhancements)")
    print("█" * 70)
    print(header)
    print(sep)

    # Combo 1: MTF + RSI filter
    def combo_mtf_rsi(p, short_lb=10, long_lb=40, rsi_cap=75):
        mtf = sig_mtf_confirmation(p, short_lb, long_lb)
        delta = p.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.clip(lower=1e-8)
        rsi = 100 - 100 / (1 + rs)
        sig = mtf.copy()
        sig[rsi > rsi_cap] = 0.5
        sig[rsi > 85] = 0.0
        return sig

    test_signal("Combo: MTF(10+40) + RSI 75", btc,
                combo_mtf_rsi(btc, 10, 40, 75))

    # Combo 2: MTF + trend strength
    def combo_mtf_strength(p, short_lb=10, long_lb=40, min_t=0.5):
        mtf = sig_mtf_confirmation(p, short_lb, long_lb)
        ret = p.pct_change()
        t = ret.rolling(20).mean() / ret.rolling(20).std().clip(1e-8) * np.sqrt(20)
        return mtf * (t > min_t).astype(float)

    test_signal("Combo: MTF(10+40) + t-stat>0.5", btc,
                combo_mtf_strength(btc, 10, 40, 0.5))

    # Combo 3: Adaptive LB + RSI + DD protection
    def combo_adaptive_rsi_dd(p):
        base = sig_adaptive_lookback(p, 10, 40, 20)
        delta = p.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.clip(lower=1e-8)
        rsi = 100 - 100 / (1 + rs)
        sig = base.copy()
        sig[rsi > 75] = 0.5
        sig[rsi > 85] = 0.0
        # DD protection
        ret = p.pct_change()
        vol = ret.rolling(20).std() * np.sqrt(365)
        pos = sig * 0.15 / vol.clip(lower=0.01)
        pnl = (pos.shift(1) * ret).fillna(0)
        eq = (1 + pnl).cumprod()
        dd = eq / eq.cummax() - 1
        sig[dd < -0.10] *= 0.5
        sig[dd < -0.20] = 0
        return sig

    test_signal("Combo: Adaptive + RSI + DD protect", btc,
                combo_adaptive_rsi_dd(btc))

    # Combo 4: Regime switch + mean distance guard
    def combo_regime_meandist(p):
        base = sig_regime_switch(p, 15, 40)
        ma = p.rolling(40).mean()
        std = p.rolling(40).std()
        z = (p - ma) / std.clip(lower=1e-8)
        sig = base.copy()
        sig[z > 1.5] = 0.5
        sig[z > 2.0] = 0.0
        return sig

    test_signal("Combo: Regime switch + z-guard", btc,
                combo_regime_meandist(btc))

    # Combo 5: 3-level MTF + vol confirm
    def combo_mtf3_vol(p):
        base = sig_mtf_3level(p, 5, 20, 60)
        ret = p.pct_change()
        vol = ret.abs().rolling(20).mean()
        vol_avg = ret.abs().rolling(100).mean()
        return base * (vol > vol_avg).astype(float)

    test_signal("Combo: MTF3(5+20+60) + vol confirm", btc,
                combo_mtf3_vol(btc))

    # Combo 6: Kaufman AMA + RSI
    def combo_kama_rsi(p):
        base = sig_kaufman_ama(p, 2, 30, 10)
        delta = p.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.clip(lower=1e-8)
        rsi = 100 - 100 / (1 + rs)
        sig = base.copy()
        sig[rsi > 75] = 0.5
        sig[rsi > 85] = 0.0
        return sig

    test_signal("Combo: KAMA + RSI 75", btc, combo_kama_rsi(btc))

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  D. YEARLY BREAKDOWN — TOP CANDIDATES vs BASELINE")
    print("█" * 70)

    candidates = {
        "Baseline Trend 20d":     sig_trend(btc, 20),
        "MTF(10+40)":             sig_mtf_confirmation(btc, 10, 40),
        "MTF 3-level(5+20+60)":   sig_mtf_3level(btc, 5, 20, 60),
        "Trend strength t>0.5":   sig_trend_strength(btc, 20, 0.5),
        "Regime switch(15/40)":   sig_regime_switch(btc, 15, 40),
        "Kaufman AMA":            sig_kaufman_ama(btc, 2, 30, 10),
        "ATR stop(10/30, 2.5x)":  sig_dual_ema_with_atr_stop(btc, 10, 30, 2.5),
        "Combo MTF+RSI":          combo_mtf_rsi(btc, 10, 40, 75),
    }

    years = sorted(btc.index.year.unique())
    yr_header = "  " + f"{'Signal':30s}" + "".join(f" {y:>7}" for y in years)
    print(yr_header)
    print("  " + "-" * 30 + "-" * 8 * len(years))

    for name, sig in candidates.items():
        r = bt(btc, sig)
        if "yearly" not in r or r["yearly"] is None:
            continue
        row = f"  {name:30s}"
        for y in years:
            if y in r["yearly"].index:
                sr_y = r["yearly"].loc[y, "sr"]
                row += f" {sr_y:>+6.2f} "
            else:
                row += "    N/A "
        print(row)

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  E. OVERFITTING CHECK: RECENT PERIOD ONLY (2022-2025)")
    print("█" * 70)
    print("  Testing signals trained on pre-2022 data, evaluated post-2022.")
    print("  If enhancement only works in-sample, it's overfit.\n")

    btc_oos = btc["2022":]
    print(f"  {'Signal':42s}  {'SR':>5}  {'AnnRet':>8}  {'MaxDD':>7}")
    print(f"  {'-'*42}  -----  --------  -------")

    oos_tests = {
        "Baseline Trend 20d":           sig_trend(btc_oos, 20),
        "Baseline Trend 40d":           sig_trend(btc_oos, 40),
        "Baseline EMA(10/30)":          sig_ema_cross(btc_oos, 10, 30),
        "MTF(10+40)":                   sig_mtf_confirmation(btc_oos, 10, 40),
        "MTF 3-level(5+20+60)":         sig_mtf_3level(btc_oos, 5, 20, 60),
        "Trend strength t>0.5":         sig_trend_strength(btc_oos, 20, 0.5),
        "Trend20 + RSI cap 75":         sig_trend_with_rsi_filter(btc_oos, 20, 14, 75),
        "Adaptive LB (10-40)":          sig_adaptive_lookback(btc_oos, 10, 40, 20),
        "Regime switch (15/40)":        sig_regime_switch(btc_oos, 15, 40),
        "Kaufman AMA":                  sig_kaufman_ama(btc_oos, 2, 30, 10),
        "EMA(10/30)+ATR stop 2.5x":    sig_dual_ema_with_atr_stop(btc_oos, 10, 30, 2.5),
        "Percentile 60d 75th":          sig_percentile_breakout(btc_oos, 60, 75),
        "Combo MTF+RSI":               combo_mtf_rsi(btc_oos, 10, 40, 75),
        "Combo Regime+z-guard":         combo_regime_meandist(btc_oos),
    }

    for name, sig in oos_tests.items():
        r = bt(btc_oos, sig)
        sr = r.get("sharpe", float("nan"))
        ar = r.get("ann_ret", 0)
        dd = r.get("max_dd", 0)
        sr_s = f"{sr:+.2f}" if not np.isnan(sr) else "  N/A"
        ar_s = f"{ar*100:+.1f}%" if ar != 0 else "   N/A"
        dd_s = f"{dd*100:.1f}%" if dd != 0 else "  N/A"
        print(f"  {name:42s}  {sr_s}  {ar_s:>8}  {dd_s:>7}")

    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 70)
    print("  SUMMARY")
    print("█" * 70)
    print("""
  Key question: Does any enhancement improve the RECENT-period Sharpe
  without destroying full-period performance?

  The baseline Trend 20d has:
    Full:  SR=1.64   2021-22: SR=-0.51   2023-25: SR=0.76   2025: SR=-0.56

  If we find an enhancement with:
    Full:  SR≥1.3    2021-22: SR>0.0     2023-25: SR>1.0    2025: SR>0.0
  ...that would be meaningfully better.

  Check the tables above to see which enhancements (if any) achieve this.
""")


if __name__ == "__main__":
    main()
