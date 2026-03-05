"""
Intraday Crypto Investigation
==============================
IBKR probe results:
  - 9 cryptos available on PAXOS: BTC, ETH, LTC, BCH, SOL, LINK, MATIC, UNI, AAVE
  - Bar sizes: 1m through 1d all work
  - History depth: ~1 month for 5m bars, times out at 3M+
  - BTC price: $64,159

yfinance provides longer history:
  - 1h bars: up to 730 days (~2 years)
  - 15m bars: up to 60 days
  - 5m bars: up to 60 days

Strategy: download hourly data (2yr) for backtesting, 15m (60d) for validation.
Test intraday trend-following, mean-reversion, breakout, and momentum strategies.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from typing import Dict

CACHE_DIR = Path("trading_system_v4/data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─── Data Download ──────────────────────────────────────────────────────────

def download_hourly_data(symbols: list, period: str = "730d") -> Dict[str, pd.DataFrame]:
    """Download hourly OHLCV data from yfinance."""
    cache = CACHE_DIR / "crypto_hourly.parquet"
    
    if cache.exists():
        print(f"  Loading cached hourly data from {cache}")
        df = pd.read_parquet(cache)
        # Check if all symbols are in cache
        missing = [s for s in symbols if s not in df.columns.get_level_values(1).unique()]
        if not missing:
            return {s: df.xs(s, axis=1, level=1) for s in symbols}
        print(f"  Missing symbols: {missing}, re-downloading...")
    
    print(f"  Downloading hourly data for {len(symbols)} cryptos (period={period})...")
    all_data = {}
    
    for sym in symbols:
        ticker = f"{sym}-USD"
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval="1h")
            if len(df) > 100:
                df.index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert("UTC").tz_localize(None)
                all_data[sym] = df[["Open", "High", "Low", "Close", "Volume"]]
                print(f"    {sym:>6}: {len(df):>6} bars  "
                      f"({df.index[0]} → {df.index[-1]})")
            else:
                print(f"    {sym:>6}: insufficient data ({len(df)} bars)")
        except Exception as e:
            print(f"    {sym:>6}: error - {e}")
    
    # Save to parquet
    if all_data:
        combined = pd.concat({s: d for s, d in all_data.items()}, axis=1)
        combined.columns = pd.MultiIndex.from_tuples(
            [(col, sym) for sym, d in all_data.items() for col in d.columns],
        )
        combined.to_parquet(cache)
        print(f"  Saved to {cache}")
    
    return all_data


def download_15m_data(symbols: list, period: str = "60d") -> Dict[str, pd.DataFrame]:
    """Download 15-min OHLCV data from yfinance."""
    cache = CACHE_DIR / "crypto_15m.parquet"
    
    if cache.exists():
        print(f"  Loading cached 15m data from {cache}")
        df = pd.read_parquet(cache)
        missing = [s for s in symbols if s not in df.columns.get_level_values(1).unique()]
        if not missing:
            return {s: df.xs(s, axis=1, level=1) for s in symbols}
    
    print(f"  Downloading 15m data for {len(symbols)} cryptos (period={period})...")
    all_data = {}
    
    for sym in symbols:
        ticker = f"{sym}-USD"
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval="15m")
            if len(df) > 100:
                df.index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert("UTC").tz_localize(None)
                all_data[sym] = df[["Open", "High", "Low", "Close", "Volume"]]
                print(f"    {sym:>6}: {len(df):>6} bars  "
                      f"({df.index[0]} → {df.index[-1]})")
            else:
                print(f"    {sym:>6}: insufficient data ({len(df)} bars)")
        except Exception as e:
            print(f"    {sym:>6}: error - {e}")
    
    if all_data:
        combined = pd.concat({s: d for s, d in all_data.items()}, axis=1)
        combined.columns = pd.MultiIndex.from_tuples(
            [(col, sym) for sym, d in all_data.items() for col in d.columns],
        )
        combined.to_parquet(cache)
    
    return all_data


# ─── Backtest Engine ────────────────────────────────────────────────────────

def bt_intraday(prices: pd.Series, signal: pd.Series,
                vol_target: float = 0.15, cost_bps: float = 5.0,
                vol_window: int = 48, ann_factor: float = np.sqrt(365 * 24),
                max_pos: float = 2.0) -> dict:
    """
    Intraday backtest with vol targeting.
    ann_factor: sqrt(hours in year) for hourly data.
    """
    ret = prices.pct_change()
    vol = ret.rolling(vol_window).std() * ann_factor

    position = signal * vol_target / vol.clip(lower=0.01)
    position = position.clip(-max_pos, max_pos)

    pnl = position.shift(1) * ret
    turnover = position.diff().abs()
    costs = turnover * (cost_bps / 10000)
    net = pnl - costs

    valid_sig = signal.abs() > 0
    if not valid_sig.any():
        return {"sharpe": float("nan"), "error": "no signals"}
    first = valid_sig[valid_sig].index[0]
    net = net[first:].fillna(0)
    costs = costs[first:].fillna(0)
    position = position[first:]

    if len(net) < 100:
        return {"sharpe": float("nan"), "error": f"too few bars: {len(net)}"}

    equity = (1 + net).cumprod()
    total = equity.iloc[-1] - 1
    hours = len(net)
    n_yr = hours / (365 * 24)

    ann_ret = (1 + total) ** (1 / n_yr) - 1 if (n_yr > 0 and total > -1) else -1.0
    ann_vol = net.std() * ann_factor
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    dd = (equity / equity.cummax() - 1).min()

    monthly_wr = ((net.resample("ME").sum()) > 0).mean() if n_yr > 0.1 else 0

    n_trades = (signal[first:].diff().abs() > 0).sum()
    trades_per_day = n_trades / (hours / 24) if hours > 24 else 0

    # Daily P&L
    daily_pnl = net.resample("D").sum()
    daily_sr = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(365)) if daily_pnl.std() > 0 else 0

    return {
        "sharpe": sharpe,
        "daily_sharpe": daily_sr,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "max_dd": dd,
        "monthly_wr": monthly_wr,
        "trades_per_day": trades_per_day,
        "total_costs": costs.sum(),
        "n_hours": hours,
        "n_years": n_yr,
        "net_pnl": net,
        "equity": equity,
    }


# ─── Signal Generators (Intraday) ──────────────────────────────────────────

# --- Trend following ---
def sig_trend_h(p, lookback=24):
    """Hourly trend: price above N hours ago."""
    return (p.pct_change(lookback) > 0).astype(float)

def sig_ema_cross_h(p, fast=6, slow=24):
    """Hourly EMA crossover."""
    return (p.ewm(span=fast, adjust=False).mean() >
            p.ewm(span=slow, adjust=False).mean()).astype(float)

def sig_sma_cross_h(p, fast=12, slow=48):
    """Hourly SMA crossover."""
    return (p.rolling(fast).mean() > p.rolling(slow).mean()).astype(float)

def sig_percentile_h(p, lookback=72, pct=75):
    """Hourly percentile breakout."""
    rolling_pct = p.rolling(lookback).quantile(pct / 100)
    return (p > rolling_pct).astype(float)

# --- Mean reversion ---
def sig_bollinger_reversion(p, window=24, num_std=2.0):
    """
    Bollinger band mean reversion: long when price touches lower band,
    exit when price returns to mean.
    """
    ma = p.rolling(window).mean()
    std = p.rolling(window).std()
    lower = ma - num_std * std
    
    sig = pd.Series(0.0, index=p.index)
    in_pos = False
    for i in range(window, len(p)):
        if not in_pos:
            if p.iloc[i] < lower.iloc[i]:
                sig.iloc[i] = 1.0
                in_pos = True
        else:
            if p.iloc[i] > ma.iloc[i]:
                in_pos = False
            else:
                sig.iloc[i] = 1.0
    return sig

def sig_rsi_reversion(p, period=14, oversold=30, overbought=70):
    """
    RSI mean reversion: long when RSI < oversold, exit when RSI > overbought.
    """
    delta = p.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.clip(lower=1e-8)
    rsi = 100 - 100 / (1 + rs)
    
    sig = pd.Series(0.0, index=p.index)
    in_pos = False
    for i in range(period, len(p)):
        if not in_pos:
            if rsi.iloc[i] < oversold:
                sig.iloc[i] = 1.0
                in_pos = True
        else:
            if rsi.iloc[i] > overbought:
                in_pos = False
            else:
                sig.iloc[i] = 1.0
    return sig

def sig_zscore_reversion(p, lookback=48, entry_z=-1.5, exit_z=0.0):
    """
    Z-score mean reversion: long when z < entry, exit when z > exit.
    """
    ma = p.rolling(lookback).mean()
    std = p.rolling(lookback).std()
    z = (p - ma) / std.clip(lower=1e-8)
    
    sig = pd.Series(0.0, index=p.index)
    in_pos = False
    for i in range(lookback, len(p)):
        if not in_pos:
            if z.iloc[i] < entry_z:
                sig.iloc[i] = 1.0
                in_pos = True
        else:
            if z.iloc[i] > exit_z:
                in_pos = False
            else:
                sig.iloc[i] = 1.0
    return sig

# --- Breakout / Momentum ---
def sig_donchian_h(p, lookback=48):
    """Donchian breakout."""
    upper = p.rolling(lookback).max().shift(1)
    lower = p.rolling(lookback).min().shift(1)
    sig = pd.Series(np.nan, index=p.index)
    sig[p > upper] = 1.0
    sig[p < lower] = 0.0
    return sig.ffill().fillna(0)

def sig_vol_breakout_h(p, lookback=24, vol_mult=1.5):
    """Long after large up moves (vol breakout)."""
    ret = p.pct_change()
    vol = ret.rolling(lookback * 5).std()
    big_up = ret > vol * vol_mult
    
    sig = pd.Series(0.0, index=p.index)
    hold_bars = 0
    for i in range(1, len(p)):
        if big_up.iloc[i]:
            sig.iloc[i] = 1.0
            hold_bars = lookback  # hold for lookback bars
        elif hold_bars > 0:
            sig.iloc[i] = 1.0
            hold_bars -= 1
    return sig

# --- Time-of-day ---
def sig_time_of_day_trend(p, lookback=24, good_hours=None):
    """
    Trend signal active only during specific hours (UTC).
    Crypto has 24/7 trading — some hours may have better trends.
    """
    if good_hours is None:
        good_hours = list(range(12, 22))  # US session hours
    
    trend = (p.pct_change(lookback) > 0).astype(float)
    hour = p.index.hour
    hour_mask = pd.Series(hour, index=p.index).isin(good_hours).astype(float)
    return trend * hour_mask

# --- Multi-timeframe ---
def sig_mtf_intraday(p, fast_lb=6, slow_lb=48):
    """Both fast and slow intraday trends must agree."""
    fast = (p.pct_change(fast_lb) > 0).astype(float)
    slow = (p.pct_change(slow_lb) > 0).astype(float)
    return fast * slow

# --- Overnight / Session ---
def sig_overnight_momentum(p, session_hours=8):
    """
    Buy during Asian session if previous US session was positive.
    Captures overnight momentum effect.
    """
    # Define sessions by hour (UTC)
    hour = p.index.hour
    # US: 14-22 UTC, Asia: 0-8 UTC
    us_session = (hour >= 14) & (hour < 22)
    asia_session = (hour >= 0) & (hour < 8)
    
    # Calculate US session return (rolling)
    ret = p.pct_change()
    us_ret = ret.where(us_session, 0).rolling(8).sum()
    
    sig = pd.Series(0.0, index=p.index)
    # Be long during Asia if US was positive
    sig[asia_session & (us_ret.shift(1) > 0)] = 1.0
    return sig

# --- Intraday momentum (continuation) ---
def sig_intraday_momentum(p, lookback=4, hold=4):
    """
    Short-term momentum: if last N hours positive, stay long for next N hours.
    """
    ret_lb = p.pct_change(lookback)
    sig = pd.Series(0.0, index=p.index)
    hold_remaining = 0
    for i in range(lookback, len(p)):
        if hold_remaining > 0:
            sig.iloc[i] = 1.0
            hold_remaining -= 1
        elif ret_lb.iloc[i] > 0:
            sig.iloc[i] = 1.0
            hold_remaining = hold - 1
    return sig


# ─── Main ───────────────────────────────────────────────────────────────────

def print_result(label, r, compact=True):
    """Print backtest result."""
    if "error" in r:
        print(f"  {label:45s}: ERROR — {r['error']}")
        return
    
    sr = r.get("sharpe", float("nan"))
    dsr = r.get("daily_sharpe", float("nan"))
    
    if compact:
        print(f"  {label:45s}: SR={sr:+.2f}  DSR={dsr:+.2f}  "
              f"Ret={r['ann_ret']*100:+.1f}%  "
              f"DD={r['max_dd']*100:.1f}%  "
              f"Tr/d={r['trades_per_day']:.1f}  "
              f"Cost={r['total_costs']*100:.2f}%")
    else:
        print(f"\n  {label}")
        print(f"  {'='*60}")
        print(f"    Sharpe (ann):    {sr:.2f}")
        print(f"    Daily Sharpe:    {dsr:.2f}")
        print(f"    Annual Return:   {r['ann_ret']*100:+.1f}%")
        print(f"    Annual Vol:      {r['ann_vol']*100:.1f}%")
        print(f"    Max Drawdown:    {r['max_dd']*100:.1f}%")
        print(f"    Monthly WR:      {r.get('monthly_wr',0)*100:.0f}%")
        print(f"    Trades/Day:      {r['trades_per_day']:.1f}")
        print(f"    Total Costs:     {r['total_costs']*100:.2f}%")
        print(f"    Period:          {r['n_years']:.2f} years")


def main():
    # IBKR-tradeable cryptos
    symbols = ["BTC", "ETH", "LTC", "BCH", "SOL", "LINK"]
    
    # ── 1. Download hourly data ──
    print("\n" + "█" * 70)
    print("  DOWNLOADING HOURLY DATA (up to 2 years)")
    print("█" * 70)
    hourly = download_hourly_data(symbols, period="730d")
    
    if not hourly:
        print("  ERROR: No hourly data downloaded!")
        return
    
    # ── 2. Download 15m data (for validation) ──
    print("\n" + "█" * 70)
    print("  DOWNLOADING 15-MIN DATA (up to 60 days)")
    print("█" * 70)
    data_15m = download_15m_data(symbols, period="60d")
    
    # ── 3. BTC Hourly — Signal Scan ──
    btc_h = hourly.get("BTC")
    if btc_h is None:
        print("  ERROR: No BTC hourly data!")
        return
    
    btc_close = btc_h["Close"]
    print(f"\n  BTC hourly: {len(btc_close)} bars, "
          f"{btc_close.index[0]} → {btc_close.index[-1]}")
    
    print("\n" + "█" * 70)
    print("  A. BTC HOURLY — TREND FOLLOWING SIGNALS")
    print("█" * 70)
    
    header = (f"  {'Signal':45s}  {'SR':>5}  {'DSR':>5}  {'Ret':>7}  "
              f"{'DD':>6}  {'Tr/d':>5}  {'Cost':>7}")
    sep = f"  {'-'*45}  -----  -----  -------  ------  -----  -------"
    print(header)
    print(sep)
    
    # --- Trend following ---
    for lb in [6, 12, 24, 48, 72, 120, 168]:
        sig = sig_trend_h(btc_close, lb)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Trend {lb}h", r)
    
    print()
    for fast, slow in [(3, 12), (6, 24), (6, 48), (12, 48), (12, 72), (24, 72), (24, 168)]:
        sig = sig_ema_cross_h(btc_close, fast, slow)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"EMA({fast}/{slow}h)", r)
    
    print()
    for fast, slow in [(6, 24), (12, 48), (24, 72), (24, 168)]:
        sig = sig_sma_cross_h(btc_close, fast, slow)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"SMA({fast}/{slow}h)", r)
    
    print()
    for lb, pct in [(48, 75), (72, 75), (120, 75), (72, 70), (168, 80)]:
        sig = sig_percentile_h(btc_close, lb, pct)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Pctl({lb}h, {pct}th)", r)
    
    # --- Breakout ---
    print("\n" + "█" * 70)
    print("  B. BTC HOURLY — BREAKOUT / MOMENTUM SIGNALS")
    print("█" * 70)
    print(header)
    print(sep)
    
    for lb in [24, 48, 72, 120, 168]:
        sig = sig_donchian_h(btc_close, lb)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Donchian {lb}h", r)
    
    print()
    for lb, mult in [(12, 1.5), (24, 1.5), (24, 2.0), (48, 1.5), (48, 2.0)]:
        sig = sig_vol_breakout_h(btc_close, lb, mult)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"VolBreak({lb}h, {mult}x)", r)
    
    # --- MTF ---
    print()
    for fast, slow in [(6, 48), (6, 72), (12, 72), (12, 168), (24, 168)]:
        sig = sig_mtf_intraday(btc_close, fast, slow)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"MTF({fast}h+{slow}h)", r)
    
    # --- Short-term momentum ---
    print()
    for lb, hold in [(2, 4), (4, 4), (4, 8), (6, 6), (6, 12), (8, 8)]:
        sig = sig_intraday_momentum(btc_close, lb, hold)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"ShortMom({lb}h→{hold}h hold)", r)
    
    # --- Mean reversion ---
    print("\n" + "█" * 70)
    print("  C. BTC HOURLY — MEAN REVERSION SIGNALS")
    print("█" * 70)
    print(header)
    print(sep)
    
    for w, nstd in [(12, 2.0), (24, 2.0), (24, 1.5), (48, 2.0), (48, 2.5)]:
        sig = sig_bollinger_reversion(btc_close, w, nstd)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Bollinger({w}h, {nstd}σ)", r)
    
    print()
    for period, os, ob in [(14, 30, 70), (14, 25, 75), (24, 30, 70), (24, 20, 80)]:
        sig = sig_rsi_reversion(btc_close, period, os, ob)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"RSI-Rev({period}h, {os}/{ob})", r)
    
    print()
    for lb, ez, xz in [(24, -1.5, 0), (48, -1.5, 0), (48, -2.0, 0), (72, -1.5, 0)]:
        sig = sig_zscore_reversion(btc_close, lb, ez, xz)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Z-Rev({lb}h, z<{ez})", r)
    
    # --- Session / Time effects ---
    print("\n" + "█" * 70)
    print("  D. BTC HOURLY — SESSION / TIME-OF-DAY EFFECTS")
    print("█" * 70)
    print(header)
    print(sep)
    
    # Time-of-day analysis
    ret = btc_close.pct_change()
    hour_returns = ret.groupby(ret.index.hour).agg(["mean", "std", "count"])
    print("\n  Hourly return profile (UTC):")
    print(f"  {'Hour':>6} {'MeanRet':>10} {'Std':>10} {'t-stat':>8} {'Count':>7}")
    for h in range(24):
        if h in hour_returns.index:
            m = hour_returns.loc[h, "mean"]
            s = hour_returns.loc[h, "std"]
            n = hour_returns.loc[h, "count"]
            t = m / (s / np.sqrt(n)) if s > 0 else 0
            bar = "+" * int(max(0, t * 2)) + "-" * int(max(0, -t * 2))
            print(f"  {h:>6} {m*100:>+9.4f}% {s*100:>9.4f}% {t:>+7.2f}  {n:>6.0f}  {bar}")
    
    print()
    
    # Best hours as filter
    for hours_label, hours in [
        ("US (14-22 UTC)", list(range(14, 22))),
        ("Asia (0-8 UTC)", list(range(0, 8))),
        ("Europe (8-16 UTC)", list(range(8, 16))),
        ("US+EU (8-22 UTC)", list(range(8, 22))),
    ]:
        sig = sig_time_of_day_trend(btc_close, 24, hours)
        r = bt_intraday(btc_close, sig, cost_bps=5)
        print_result(f"Trend24h + {hours_label}", r)
    
    print()
    sig = sig_overnight_momentum(btc_close)
    r = bt_intraday(btc_close, sig, cost_bps=5)
    print_result("Overnight momentum (US→Asia)", r)
    
    # --- Day of week ---
    print("\n  Day-of-week return profile:")
    daily_ret = btc_close.resample("D").last().pct_change()
    dow_returns = daily_ret.groupby(daily_ret.index.dayofweek).agg(["mean", "std", "count"])
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for d in range(7):
        if d in dow_returns.index:
            m = dow_returns.loc[d, "mean"]
            s = dow_returns.loc[d, "std"]
            n = dow_returns.loc[d, "count"]
            t = m / (s / np.sqrt(n)) if s > 0 else 0
            print(f"    {days[d]:>4}: {m*100:>+.4f}%  t={t:+.2f}")
    
    # ── 4. Multi-Crypto Hourly —————————————————————————————
    print("\n" + "█" * 70)
    print("  E. MULTI-CRYPTO HOURLY — BEST SIGNALS")
    print("█" * 70)
    
    # Test best BTC signals on other cryptos
    best_signals = {
        "Trend 24h": lambda p: sig_trend_h(p, 24),
        "Trend 48h": lambda p: sig_trend_h(p, 48),
        "EMA(6/24h)": lambda p: sig_ema_cross_h(p, 6, 24),
        "EMA(12/48h)": lambda p: sig_ema_cross_h(p, 12, 48),
        "Pctl(72h, 75th)": lambda p: sig_percentile_h(p, 72, 75),
        "Donchian 48h": lambda p: sig_donchian_h(p, 48),
        "MTF(6+48h)": lambda p: sig_mtf_intraday(p, 6, 48),
    }
    
    print(f"\n  {'':12s}", end="")
    for sig_name in best_signals:
        print(f"  {sig_name:>15}", end="")
    print()
    print(f"  {'':12s}", end="")
    for _ in best_signals:
        print(f"  {'─'*15}", end="")
    print()
    
    for sym, data in hourly.items():
        close = data["Close"]
        if len(close) < 200:
            continue
        row = f"  {sym:>10}  "
        for sig_name, sig_func in best_signals.items():
            sig = sig_func(close)
            r = bt_intraday(close, sig, cost_bps=5)
            sr = r.get("sharpe", float("nan"))
            if np.isnan(sr):
                row += f"  {'N/A':>15}"
            else:
                row += f"  {sr:>+14.2f}"
        print(row)
    
    # ── 5. Cost sensitivity for intraday ──
    print("\n" + "█" * 70)
    print("  F. COST SENSITIVITY — INTRADAY vs DAILY")
    print("█" * 70)
    
    # Compare best intraday vs daily signal at different costs
    sig_daily = sig_trend_h(btc_close, 168)   # ~7 day trend on hourly
    sig_intra = sig_ema_cross_h(btc_close, 6, 24)  # fast intraday
    sig_mid = sig_trend_h(btc_close, 48)      # 2-day trend
    
    print(f"\n  {'Cost':>8}  {'Trend 168h':>12}  {'Trend 48h':>12}  {'EMA 6/24h':>12}")
    print(f"  {'─'*8}  {'─'*12}  {'─'*12}  {'─'*12}")
    for cost in [0, 1, 2, 3, 5, 10, 15, 20, 30]:
        r1 = bt_intraday(btc_close, sig_daily, cost_bps=cost)
        r2 = bt_intraday(btc_close, sig_mid, cost_bps=cost)
        r3 = bt_intraday(btc_close, sig_intra, cost_bps=cost)
        
        sr1 = r1.get("sharpe", float("nan"))
        sr2 = r2.get("sharpe", float("nan"))
        sr3 = r3.get("sharpe", float("nan"))
        
        print(f"  {cost:>6}bp  {sr1:>+11.2f}  {sr2:>+11.2f}  {sr3:>+11.2f}")
    
    # ── 6. 15-min validation ──
    if data_15m:
        btc_15m = data_15m.get("BTC")
        if btc_15m is not None:
            btc_15m_close = btc_15m["Close"]
            print("\n" + "█" * 70)
            print("  G. BTC 15-MIN VALIDATION (last 60 days)")
            print("█" * 70)
            print(f"  Data: {len(btc_15m_close)} bars, "
                  f"{btc_15m_close.index[0]} → {btc_15m_close.index[-1]}")
            
            # On 15m data, scale lookbacks by 4 (hourly→15m)
            ann_15m = np.sqrt(365 * 24 * 4)
            
            signals_15m = {
                "Trend 96 bars (=24h)":   lambda p: sig_trend_h(p, 96),
                "Trend 192 bars (=48h)":  lambda p: sig_trend_h(p, 192),
                "EMA(24/96) (=6/24h)":    lambda p: sig_ema_cross_h(p, 24, 96),
                "EMA(48/192) (=12/48h)":  lambda p: sig_ema_cross_h(p, 48, 192),
                "Pctl(288, 75th) (=72h)": lambda p: sig_percentile_h(p, 288, 75),
                "Donchian 192 (=48h)":    lambda p: sig_donchian_h(p, 192),
            }
            
            print(f"\n  {'Signal':45s}  {'SR':>5}  {'Ret':>7}  {'DD':>6}  {'Tr/d':>5}")
            print(f"  {'-'*45}  -----  -------  ------  -----")
            for name, sig_func in signals_15m.items():
                sig = sig_func(btc_15m_close)
                r = bt_intraday(btc_15m_close, sig, cost_bps=5,
                               vol_window=192, ann_factor=ann_15m)
                sr = r.get("sharpe", float("nan"))
                ar = r.get("ann_ret", 0)
                dd = r.get("max_dd", 0)
                tpd = r.get("trades_per_day", 0)
                print(f"  {name:45s}  {sr:>+.2f}  {ar*100:>+6.1f}%  {dd*100:>5.1f}%  {tpd:>4.1f}")
    
    # ── 7. Summary ──
    print("\n" + "█" * 70)
    print("  SUMMARY")
    print("█" * 70)
    print("""
  IBKR Crypto Available (PAXOS exchange):
    BTC, ETH, LTC, BCH, SOL, LINK, MATIC, UNI, AAVE (9 coins)

  IBKR Data Limits:
    - 5m bars: ~1 month history
    - 1h bars: unknown (timed out at >1 month)
    - Day bars: full history

  yfinance Data Used:
    - 1h: ~2 years (for backtesting above)
    - 15m: ~60 days (for validation)

  Key findings from intraday investigation above.
  Compare hourly Sharpes with daily Sharpes (~1.6 for Trend 20d).
  If intraday adds edge, consider combining daily + intraday signals.
""")


if __name__ == "__main__":
    main()
