"""
Crypto Strategy Backtest
========================
Crypto markets are structurally less efficient than FX/equities:
  - 24/7 trading, fragmented liquidity, retail-dominated
  - Momentum persists longer (trend-following works)
  - Mean reversion at short horizons (overreaction)
  - High vol = bigger opportunity set

Tests:
  1. Time-series momentum (trend following) — single asset
  2. Cross-sectional momentum — rank N cryptos
  3. Breakout / channel — buy highs, sell lows
  4. Mean reversion (RSI-based)
  5. Combined signals
  6. BTC-only trend following (simplest possible)

Universe: Top cryptos by market cap with sufficient history.
Data: yfinance (free, daily bars).
Period: 2018-2025 (post-ICO-bubble, realistic era).
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional
import os


# ─── Crypto Universe ────────────────────────────────────────────────────────
# yfinance crypto tickers (USD pairs)
CRYPTO_TICKERS = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "BNB-USD": "BNB",
    "SOL-USD": "Solana",
    "XRP-USD": "XRP",
    "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin",
    "AVAX-USD": "Avalanche",
    "DOT-USD": "Polkadot",
    "LINK-USD": "Chainlink",
    "MATIC-USD": "Polygon",
    "LTC-USD": "Litecoin",
    "UNI-USD": "Uniswap",  # DeFi
    "ATOM-USD": "Cosmos",
    "NEAR-USD": "NEAR",
    "FIL-USD": "Filecoin",
    "AAVE-USD": "Aave",
    "ALGO-USD": "Algorand",
    "XLM-USD": "Stellar",
    "ETC-USD": "Ethereum Classic",
}


def download_crypto_data(tickers: dict, start: str = "2017-01-01",
                         end: str = "2025-12-31") -> pd.DataFrame:
    """Download daily OHLCV for crypto tickers."""
    print(f"Downloading {len(tickers)} cryptos from {start} to {end}...")
    
    ticker_list = list(tickers.keys())
    data = yf.download(ticker_list, start=start, end=end,
                       auto_adjust=True, progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
        volumes = data["Volume"]
        highs = data["High"]
        lows = data["Low"]
    else:
        closes = data[["Close"]]
        closes.columns = ticker_list
        volumes = data[["Volume"]]
        volumes.columns = ticker_list
        highs = data[["High"]]
        highs.columns = ticker_list
        lows = data[["Low"]]
        lows.columns = ticker_list
    
    # Forward fill small gaps (weekends are traded but yfinance may have gaps)
    closes = closes.ffill().bfill()
    
    # Drop assets with >30% missing
    missing = closes.isna().mean()
    good = missing[missing < 0.30].index
    closes = closes[good]
    highs = highs[good]
    lows = lows[good]
    volumes = volumes[good]
    
    print(f"  Got {len(closes)} days x {len(closes.columns)} cryptos")
    print(f"  Date range: {closes.index[0].date()} to {closes.index[-1].date()}")
    
    for col in closes.columns:
        first_valid = closes[col].first_valid_index()
        if first_valid is not None:
            print(f"    {col:>12}: from {first_valid.date()}")
    
    return closes, highs, lows, volumes


# ─── Signal Generators ──────────────────────────────────────────────────────

def signal_ts_momentum(closes: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Time-series momentum: sign of trailing return.
    +1 if price > price N days ago, -1 if below.
    This is trend-following: go with the direction of recent move.
    """
    ret = closes.pct_change(lookback)
    return np.sign(ret)


def signal_ts_momentum_smooth(closes: pd.DataFrame, fast: int = 10,
                               slow: int = 50) -> pd.DataFrame:
    """
    Smoothed time-series momentum via EMA crossover.
    Long when fast EMA > slow EMA, short otherwise.
    """
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    return np.sign(ema_fast - ema_slow)


def signal_breakout(closes: pd.DataFrame, highs: pd.DataFrame,
                    lows: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Donchian channel breakout: +1 if close > highest high of last N days,
    -1 if close < lowest low. 0 otherwise.
    """
    upper = highs.rolling(lookback).max().shift(1)
    lower = lows.rolling(lookback).min().shift(1)
    
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig[closes > upper] = 1.0
    sig[closes < lower] = -1.0
    # Hold position until opposite signal (forward fill non-zero)
    for col in sig.columns:
        s = sig[col].copy()
        last = 0.0
        for i in range(len(s)):
            if s.iloc[i] != 0:
                last = s.iloc[i]
            else:
                s.iloc[i] = last
        sig[col] = s
    return sig


def signal_rsi_reversion(closes: pd.DataFrame, period: int = 14,
                          oversold: float = 30, overbought: float = 70) -> pd.DataFrame:
    """
    RSI mean reversion: buy when RSI < oversold, sell when RSI > overbought.
    """
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig[rsi < oversold] = 1.0      # Buy oversold
    sig[rsi > overbought] = -1.0   # Sell overbought
    # Hold until opposite
    for col in sig.columns:
        s = sig[col].copy()
        last = 0.0
        for i in range(len(s)):
            if s.iloc[i] != 0:
                last = s.iloc[i]
            else:
                s.iloc[i] = last
        sig[col] = s
    return sig


def signal_cross_sectional_momentum(closes: pd.DataFrame,
                                     lookback: int = 21) -> pd.DataFrame:
    """
    Cross-sectional momentum: rank cryptos by trailing return.
    Top half get +1, bottom half get -1.
    """
    ret = closes.pct_change(lookback)
    ranks = ret.rank(axis=1, pct=True)
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig[ranks > 0.5] = 1.0
    sig[ranks <= 0.5] = -1.0
    return sig


def signal_vol_breakout(closes: pd.DataFrame, lookback: int = 20,
                         threshold: float = 2.0) -> pd.DataFrame:
    """
    Volatility breakout: if today's return exceeds 2x the rolling std,
    go with the move (momentum after vol spike).
    """
    ret = closes.pct_change()
    vol = ret.rolling(lookback).std()
    z_score = ret / vol
    
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig[z_score > threshold] = 1.0
    sig[z_score < -threshold] = -1.0
    # Hold for N days then flatten
    for col in sig.columns:
        s = sig[col].copy()
        last = 0.0
        hold_remaining = 0
        for i in range(len(s)):
            if s.iloc[i] != 0:
                last = s.iloc[i]
                hold_remaining = lookback  # Hold for lookback days
            elif hold_remaining > 0:
                s.iloc[i] = last
                hold_remaining -= 1
            else:
                s.iloc[i] = 0
        sig[col] = s
    return sig


# ─── Backtest Engine ────────────────────────────────────────────────────────

def run_crypto_backtest(closes: pd.DataFrame, signals: pd.DataFrame,
                        vol_target: float = 0.15,
                        cost_bps: float = 10.0,
                        max_leverage: float = 2.0,
                        long_only: bool = False,
                        label: str = "") -> dict:
    """
    Run a crypto backtest with volatility targeting.
    
    - Each asset gets position sized by inverse vol to target portfolio vol.
    - Signals: +1 long, -1 short, 0 flat.
    - If long_only, clamp shorts to 0.
    """
    returns = closes.pct_change()
    
    # 20-day rolling vol per asset
    asset_vol = returns.rolling(20).std() * np.sqrt(365)  # crypto trades 365 days
    
    # Position size: signal * (vol_target / N_assets) / asset_vol
    n_assets = signals.abs().sum(axis=1).clip(lower=1)
    raw_weight = signals * (vol_target / n_assets.values[:, None]) / asset_vol.clip(lower=0.01)
    
    if long_only:
        raw_weight = raw_weight.clip(lower=0)
    
    # Cap individual position
    raw_weight = raw_weight.clip(-max_leverage / len(closes.columns),
                                  max_leverage / len(closes.columns))
    
    # Cap total leverage
    total_leverage = raw_weight.abs().sum(axis=1)
    scale = (max_leverage / total_leverage).clip(upper=1.0)
    positions = raw_weight.multiply(scale, axis=0)
    
    # Daily PnL (positions decided at close, return earned next day)
    daily_pnl = (positions.shift(1) * returns).sum(axis=1)
    
    # Transaction costs
    turnover = positions.diff().abs().sum(axis=1)
    costs = turnover * (cost_bps / 10000)
    net_pnl = daily_pnl - costs
    
    # Trim to first valid signal
    first_valid = signals.abs().sum(axis=1)
    start_idx = first_valid[first_valid > 0].index[0] if (first_valid > 0).any() else None
    if start_idx is None:
        return {"error": "No signals generated"}
    
    net_pnl = net_pnl[start_idx:]
    daily_pnl = daily_pnl[start_idx:]
    positions = positions[start_idx:]
    costs = costs[start_idx:]
    
    if len(net_pnl) < 100:
        return {"error": f"Too few days: {len(net_pnl)}"}
    
    # Metrics
    equity = (1 + net_pnl).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_years = len(net_pnl) / 365  # crypto calendar days ≈ trading days
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = net_pnl.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    monthly = net_pnl.resample("ME").sum()
    
    # Yearly breakdown
    yearly = net_pnl.groupby(net_pnl.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        vol=lambda x: x.std() * np.sqrt(365),
    )
    
    # Average leverage
    avg_leverage = positions.abs().sum(axis=1).mean()
    
    return {
        "label": label,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "total_return": total_ret,
        "daily_wr": (net_pnl > 0).mean(),
        "monthly_wr": (monthly > 0).mean(),
        "n_years": n_years,
        "avg_leverage": avg_leverage,
        "total_costs": costs.sum(),
        "yearly": yearly,
        "equity": equity,
        "net_pnl": net_pnl,
    }


def run_btc_only_backtest(closes: pd.Series, signal: pd.Series,
                           vol_target: float = 0.15,
                           cost_bps: float = 10.0,
                           label: str = "") -> dict:
    """Single-asset backtest for BTC strategies."""
    ret = closes.pct_change()
    vol = ret.rolling(20).std() * np.sqrt(365)
    
    # Vol-targeted position
    position = signal * vol_target / vol.clip(lower=0.01)
    position = position.clip(-2, 2)  # max 2x leverage
    
    daily_pnl = position.shift(1) * ret
    turnover = position.diff().abs()
    costs = turnover * (cost_bps / 10000)
    net_pnl = daily_pnl - costs
    
    # Trim
    start_idx = signal.abs()[signal.abs() > 0].index[0]
    net_pnl = net_pnl[start_idx:]
    position = position[start_idx:]
    costs = costs[start_idx:]
    
    if len(net_pnl) < 100:
        return {"error": f"Too few days"}
    
    equity = (1 + net_pnl).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_years = len(net_pnl) / 365
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = net_pnl.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    monthly = net_pnl.resample("ME").sum()
    yearly = net_pnl.groupby(net_pnl.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
    )
    
    return {
        "label": label,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "total_return": total_ret,
        "daily_wr": (net_pnl > 0).mean(),
        "monthly_wr": (monthly > 0).mean(),
        "n_years": n_years,
        "avg_position": position.abs().mean(),
        "total_costs": costs.sum(),
        "yearly": yearly,
        "equity": equity,
    }


def print_results(r: dict):
    """Pretty-print results."""
    if "error" in r:
        print(f"  {r.get('label', '???')}: ERROR — {r['error']}")
        return
    
    print(f"\n{'='*70}")
    print(f"  {r['label']}")
    print(f"{'='*70}")
    print(f"  Annual Return:    {r['ann_return']*100:+.2f}%")
    print(f"  Annual Vol:       {r['ann_vol']*100:.2f}%")
    print(f"  Sharpe Ratio:     {r['sharpe']:.2f}")
    print(f"  Max Drawdown:     {r['max_dd']*100:.1f}%")
    print(f"  Calmar Ratio:     {r['calmar']:.2f}")
    print(f"  Daily Win Rate:   {r['daily_wr']*100:.1f}%")
    print(f"  Monthly Win Rate: {r['monthly_wr']*100:.1f}%")
    print(f"  Total Return:     {r['total_return']*100:+.1f}%")
    print(f"  Period:           {r['n_years']:.1f} years")
    if "avg_leverage" in r:
        print(f"  Avg Leverage:     {r['avg_leverage']:.2f}x")
    if "avg_position" in r:
        print(f"  Avg Position:     {r['avg_position']:.2f}x")
    print(f"  Total Costs:      {r['total_costs']*100:.2f}%")
    
    print(f"\n  {'Year':>6} {'Return':>10} {'Sharpe':>8} {'Vol':>8}")
    print(f"  {'-'*6} {'-'*10} {'-'*8} {'-'*8}")
    for year, row in r["yearly"].iterrows():
        vol_str = f"{row['vol']*100:.1f}%" if 'vol' in row else ""
        print(f"  {year:>6} {row['total_return']*100:>+9.2f}% {row['sharpe']:>7.2f} {vol_str:>8}")
    print()


# ─── Walk-Forward Out-of-Sample ─────────────────────────────────────────────

def walk_forward_crypto(closes: pd.DataFrame, signal_func, signal_kwargs: dict,
                         train_years: float = 2, test_months: int = 6,
                         label: str = "") -> dict:
    """
    Walk-forward: train on N years, test on M months, step forward.
    For crypto we just check stability of the signal OOS.
    """
    results = []
    start_date = closes.index[0]
    end_date = closes.index[-1]
    
    train_days = int(train_years * 365)
    test_days = int(test_months * 30)
    
    cursor = start_date + pd.Timedelta(days=train_days)
    
    while cursor + pd.Timedelta(days=test_days) <= end_date:
        test_end = cursor + pd.Timedelta(days=test_days)
        test_closes = closes[cursor:test_end]
        
        if len(test_closes) < 30:
            cursor += pd.Timedelta(days=test_days)
            continue
        
        # Generate signals on full history up to test period
        # (signal uses lookback from before test period — no lookahead)
        full_closes = closes[:test_end]
        sig = signal_func(full_closes, **signal_kwargs)
        test_sig = sig[cursor:test_end]
        test_ret = test_closes.pct_change()
        
        # Simple equal-weight PnL
        pnl = (test_sig.shift(1) * test_ret).sum(axis=1)
        pnl = pnl.dropna()
        
        if len(pnl) > 0:
            total = (1 + pnl).prod() - 1
            vol = pnl.std() * np.sqrt(365)
            sr = (pnl.mean() * 365) / vol if vol > 0 else 0
            results.append({
                "start": cursor.date(),
                "end": test_end.date(),
                "return": total,
                "sharpe": sr,
                "vol": vol,
            })
        
        cursor += pd.Timedelta(days=test_days)
    
    if not results:
        return {"error": "No walk-forward windows"}
    
    df = pd.DataFrame(results)
    return {
        "label": label,
        "n_windows": len(df),
        "avg_return": df["return"].mean(),
        "avg_sharpe": df["sharpe"].mean(),
        "pct_positive": (df["return"] > 0).mean(),
        "worst_window": df["return"].min(),
        "best_window": df["return"].max(),
        "windows": df,
    }


def print_wf_results(r: dict):
    if "error" in r:
        print(f"  {r.get('label', '???')}: {r['error']}")
        return
    print(f"\n  Walk-Forward: {r['label']}")
    print(f"    Windows:        {r['n_windows']}")
    print(f"    Avg Return:     {r['avg_return']*100:+.2f}%")
    print(f"    Avg Sharpe:     {r['avg_sharpe']:.2f}")
    print(f"    % Positive:     {r['pct_positive']*100:.0f}%")
    print(f"    Worst Window:   {r['worst_window']*100:+.1f}%")
    print(f"    Best Window:    {r['best_window']*100:+.1f}%")
    for _, row in r["windows"].iterrows():
        marker = "+" if row["return"] > 0 else "-"
        print(f"      {row['start']} → {row['end']}: {row['return']*100:+.1f}%  "
              f"SR={row['sharpe']:.2f}  {marker}")


def main():
    # ──────────────────────────────────────────────────────────────────────
    # 1. Download / load data
    # ──────────────────────────────────────────────────────────────────────
    cache_path = "trading_system_v4/data/crypto_daily.parquet"
    cache_h = "trading_system_v4/data/crypto_daily_high.parquet"
    cache_l = "trading_system_v4/data/crypto_daily_low.parquet"
    
    if os.path.exists(cache_path):
        print(f"Loading cached data...")
        closes = pd.read_parquet(cache_path)
        highs = pd.read_parquet(cache_h)
        lows = pd.read_parquet(cache_l)
        print(f"  {len(closes)} days x {len(closes.columns)} cryptos")
    else:
        closes, highs, lows, volumes = download_crypto_data(
            CRYPTO_TICKERS, start="2017-01-01", end="2025-12-31"
        )
        closes.to_parquet(cache_path)
        highs.to_parquet(cache_h)
        lows.to_parquet(cache_l)
        print(f"  Saved to {cache_path}")
    
    btc = closes["BTC-USD"] if "BTC-USD" in closes.columns else None
    
    # ══════════════════════════════════════════════════════════════════════
    #  SECTION A: BTC-ONLY STRATEGIES
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  SECTION A: BTC-ONLY STRATEGIES")
    print("█"*70)
    
    if btc is not None:
        btc_closes = btc.dropna()
        
        # A1: Simple trend following — 20-day breakout
        print("\n--- A1: BTC Trend Following (various lookbacks) ---")
        for lb in [10, 20, 40, 60]:
            sig = np.sign(btc_closes.pct_change(lb))
            r = run_btc_only_backtest(btc_closes, sig, vol_target=0.15,
                                       cost_bps=10, label=f"BTC Trend {lb}d")
            print_results(r)
        
        # A2: EMA crossover
        print("\n--- A2: BTC EMA Crossover ---")
        for fast, slow in [(10, 30), (10, 50), (20, 60), (20, 100)]:
            ema_f = btc_closes.ewm(span=fast, adjust=False).mean()
            ema_s = btc_closes.ewm(span=slow, adjust=False).mean()
            sig = pd.Series(np.sign(ema_f - ema_s), index=btc_closes.index)
            r = run_btc_only_backtest(btc_closes, sig, vol_target=0.15,
                                       cost_bps=10, label=f"BTC EMA({fast}/{slow})")
            print_results(r)
        
        # A3: RSI mean reversion on BTC
        print("\n--- A3: BTC RSI Mean Reversion ---")
        for period, ob, os_ in [(14, 70, 30), (14, 65, 35), (7, 75, 25), (7, 80, 20)]:
            delta = btc_closes.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
            avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
            rs = avg_g / avg_l.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            
            sig = pd.Series(0.0, index=btc_closes.index)
            sig[rsi < os_] = 1.0
            sig[rsi > ob] = -1.0
            # Hold
            last = 0.0
            for i in range(len(sig)):
                if sig.iloc[i] != 0:
                    last = sig.iloc[i]
                else:
                    sig.iloc[i] = last
            
            r = run_btc_only_backtest(btc_closes, sig, vol_target=0.15,
                                       cost_bps=10,
                                       label=f"BTC RSI({period}) {os_}/{ob}")
            print_results(r)
        
        # A4: BTC long-only trend (no shorting — simpler + avoids bear rallies)
        print("\n--- A4: BTC Long-Only Trend (hold when trend up, cash when down) ---")
        for lb in [20, 40, 60]:
            sig = np.sign(btc_closes.pct_change(lb)).clip(lower=0)  # 1 or 0
            r = run_btc_only_backtest(btc_closes, sig, vol_target=0.20,
                                       cost_bps=10,
                                       label=f"BTC Long-Only Trend {lb}d")
            print_results(r)
    
    # ══════════════════════════════════════════════════════════════════════
    #  SECTION B: MULTI-CRYPTO STRATEGIES
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  SECTION B: MULTI-CRYPTO STRATEGIES")
    print("█"*70)
    
    # B1: Time-series momentum (all assets, long/short)
    print("\n--- B1: Multi-Crypto Time-Series Momentum ---")
    for lb in [10, 20, 40]:
        sig = signal_ts_momentum(closes, lookback=lb)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                label=f"TS Momentum {lb}d (L/S)")
        print_results(r)
    
    # B2: Time-series momentum, LONG ONLY
    print("\n--- B2: Multi-Crypto TS Momentum (Long Only) ---")
    for lb in [10, 20, 40]:
        sig = signal_ts_momentum(closes, lookback=lb).clip(lower=0)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                long_only=True,
                                label=f"TS Momentum {lb}d (Long Only)")
        print_results(r)
    
    # B3: EMA crossover multi-crypto
    print("\n--- B3: Multi-Crypto EMA Crossover ---")
    for fast, slow in [(10, 50), (20, 60)]:
        sig = signal_ts_momentum_smooth(closes, fast=fast, slow=slow)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                label=f"EMA({fast}/{slow}) L/S")
        print_results(r)
        
        sig_lo = sig.clip(lower=0)
        r = run_crypto_backtest(closes, sig_lo, vol_target=0.15, cost_bps=10,
                                long_only=True,
                                label=f"EMA({fast}/{slow}) Long Only")
        print_results(r)
    
    # B4: Channel breakout
    print("\n--- B4: Donchian Breakout ---")
    for lb in [20, 40]:
        sig = signal_breakout(closes, highs, lows, lookback=lb)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                label=f"Donchian {lb}d L/S")
        print_results(r)
    
    # B5: Cross-sectional momentum
    print("\n--- B5: Cross-Sectional Momentum ---")
    for lb in [7, 21, 63]:
        sig = signal_cross_sectional_momentum(closes, lookback=lb)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                label=f"XS Momentum {lb}d")
        print_results(r)
    
    # B6: Vol breakout
    print("\n--- B6: Volatility Breakout ---")
    for lb, thresh in [(20, 2.0), (20, 1.5), (10, 2.0)]:
        sig = signal_vol_breakout(closes, lookback=lb, threshold=thresh)
        r = run_crypto_backtest(closes, sig, vol_target=0.15, cost_bps=10,
                                label=f"Vol Breakout lb={lb} thr={thresh}")
        print_results(r)
    
    # ══════════════════════════════════════════════════════════════════════
    #  SECTION C: COST SENSITIVITY
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  SECTION C: COST SENSITIVITY (best strategies)")
    print("█"*70)
    
    # Find the best L/S and best long-only from above and sweep costs
    # Using BTC EMA(20/60) and multi TS Mom 20d as candidates
    if btc is not None:
        btc_closes = btc.dropna()
        ema_f = btc_closes.ewm(span=20, adjust=False).mean()
        ema_s = btc_closes.ewm(span=60, adjust=False).mean()
        btc_sig = pd.Series(np.sign(ema_f - ema_s), index=btc_closes.index)
        
        print("\n--- BTC EMA(20/60) cost sensitivity ---")
        for cost in [0, 5, 10, 20, 30, 50]:
            r = run_btc_only_backtest(btc_closes, btc_sig, vol_target=0.15,
                                       cost_bps=cost, label=f"cost={cost}bps")
            if "error" not in r:
                print(f"    cost={cost:>2}bps: Sharpe={r['sharpe']:.2f}, "
                      f"Return={r['ann_return']*100:+.1f}%, MaxDD={r['max_dd']*100:.1f}%")
    
    sig20 = signal_ts_momentum(closes, lookback=20)
    print("\n--- Multi-Crypto TS Mom 20d cost sensitivity ---")
    for cost in [0, 5, 10, 20, 30, 50]:
        r = run_crypto_backtest(closes, sig20, vol_target=0.15, cost_bps=cost,
                                label=f"cost={cost}bps")
        if "error" not in r:
            print(f"    cost={cost:>2}bps: Sharpe={r['sharpe']:.2f}, "
                  f"Return={r['ann_return']*100:+.1f}%, MaxDD={r['max_dd']*100:.1f}%")
    
    # ══════════════════════════════════════════════════════════════════════
    #  SECTION D: WALK-FORWARD VALIDATION
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  SECTION D: WALK-FORWARD OUT-OF-SAMPLE")
    print("█"*70)
    
    wf = walk_forward_crypto(closes, signal_ts_momentum, {"lookback": 20},
                             train_years=2, test_months=6,
                             label="TS Momentum 20d")
    print_wf_results(wf)
    
    wf = walk_forward_crypto(closes, signal_ts_momentum_smooth,
                             {"fast": 20, "slow": 60},
                             train_years=2, test_months=6,
                             label="EMA(20/60)")
    print_wf_results(wf)
    
    wf = walk_forward_crypto(closes, signal_ts_momentum, {"lookback": 40},
                             train_years=2, test_months=6,
                             label="TS Momentum 40d")
    print_wf_results(wf)
    
    # ══════════════════════════════════════════════════════════════════════
    #  SECTION E: BUY-AND-HOLD BENCHMARKS
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  SECTION E: BUY-AND-HOLD BENCHMARKS")
    print("█"*70)
    
    bench_tickers = ["BTC-USD", "ETH-USD"]
    for t in bench_tickers:
        if t in closes.columns:
            c = closes[t].dropna()
            ret = c.pct_change().dropna()
            if len(ret) > 100:
                total = (1 + ret).prod() - 1
                ny = len(ret) / 365
                ar = (1 + total) ** (1/ny) - 1
                av = ret.std() * np.sqrt(365)
                sr = ar / av if av > 0 else 0
                eq = (1 + ret).cumprod()
                mdd = ((eq - eq.cummax()) / eq.cummax()).min()
                print(f"\n  {t} Buy & Hold:")
                print(f"    Ann Return: {ar*100:+.1f}%, Vol: {av*100:.1f}%, "
                      f"Sharpe: {sr:.2f}, MaxDD: {mdd*100:.1f}%")
                print(f"    Total: {total*100:+.0f}%, Period: {ny:.1f}y")
    
    print("\n" + "█"*70)
    print("  DONE")
    print("█"*70)


if __name__ == "__main__":
    main()
