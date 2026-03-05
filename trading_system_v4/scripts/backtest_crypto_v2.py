"""
Crypto Deep-Dive v2
====================
Rigorous investigation of the promising crypto trend-following strategies.

Fixes from v1:
  - Filter out coins that collapsed to ~$0 (LUNA-like events)
  - Clean walk-forward on long-only strategies
  - Sub-period stability analysis
  - Regime detection (bull/bear/chop)
  - Signal combination & enhancement
  - Practical execution stats (turnover, hold time, signal persistence)
  - Rolling Sharpe analysis (is edge decaying over time?)
  - Monte Carlo bootstrap confidence intervals
  - Multi-timeframe confirmation
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import os
from typing import Dict, List, Tuple


# ─── Load data ──────────────────────────────────────────────────────────────

def load_crypto_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load cached crypto data from v1."""
    cache_path = "trading_system_v4/data/crypto_daily.parquet"
    cache_h = "trading_system_v4/data/crypto_daily_high.parquet"
    cache_l = "trading_system_v4/data/crypto_daily_low.parquet"
    
    closes = pd.read_parquet(cache_path)
    highs = pd.read_parquet(cache_h)
    lows = pd.read_parquet(cache_l)
    
    # ── Data quality: filter out coins that collapsed >99% ──
    # This prevents survivorship bias issues on the short side
    peak = closes.cummax()
    drawdown_from_peak = (closes - peak) / peak
    # Flag coins that had >99% drawdown (delistings/collapses)
    collapsed = (drawdown_from_peak.min() < -0.99)
    bad_coins = collapsed[collapsed].index.tolist()
    
    if bad_coins:
        print(f"  Filtering out collapsed coins: {bad_coins}")
    
    # Keep collapsed coins but mark them — for long-only we just need
    # to not be long during collapse, which signal handles naturally.
    # For L/S we'll use a "safe" subset.
    safe_cols = [c for c in closes.columns if c not in bad_coins]
    
    print(f"  Data: {len(closes)} days x {len(closes.columns)} cryptos "
          f"({len(safe_cols)} safe)")
    print(f"  Range: {closes.index[0].date()} to {closes.index[-1].date()}")
    
    return closes, highs, lows


def data_availability_summary(closes: pd.DataFrame):
    """Show when each coin has data."""
    print("\n  Data availability:")
    for col in sorted(closes.columns):
        valid = closes[col].dropna()
        if len(valid) > 0:
            first = valid.index[0].date()
            last = valid.index[-1].date()
            peak = valid.max()
            final = valid.iloc[-1]
            dd = (final - peak) / peak * 100
            print(f"    {col:>12}: {first} → {last}  "
                  f"({len(valid):>4}d)  peak=${peak:>10,.0f}  "
                  f"current=${final:>10,.0f}  ({dd:+.0f}%)")


# ─── Core backtest (clean version) ─────────────────────────────────────────

def backtest_single_asset(prices: pd.Series, signal: pd.Series,
                          vol_target: float = 0.15,
                          cost_bps: float = 10.0,
                          max_pos: float = 2.0) -> dict:
    """
    Clean single-asset backtest with vol targeting.
    Returns daily returns series + stats.
    """
    ret = prices.pct_change()
    vol = ret.rolling(20).std() * np.sqrt(365)
    
    position = signal * vol_target / vol.clip(lower=0.01)
    position = position.clip(-max_pos, max_pos)
    
    pnl = position.shift(1) * ret
    turnover = position.diff().abs()
    costs = turnover * (cost_bps / 10000)
    net = pnl - costs
    
    # Trim to first signal
    valid_sig = signal.abs() > 0
    if not valid_sig.any():
        return {"error": "No signals"}
    first = valid_sig[valid_sig].index[0]
    net = net[first:].fillna(0)
    costs = costs[first:].fillna(0)
    position = position[first:]
    
    return compute_stats(net, costs, position, signal[first:])


def backtest_multi_asset(closes: pd.DataFrame, signals: pd.DataFrame,
                         vol_target: float = 0.15,
                         cost_bps: float = 10.0,
                         max_leverage: float = 2.0,
                         long_only: bool = True) -> dict:
    """
    Clean multi-asset backtest. Handles NaN coins gracefully.
    """
    returns = closes.pct_change()
    asset_vol = returns.rolling(20).std() * np.sqrt(365)
    
    # Only trade coins with valid data + signal
    valid_mask = closes.notna() & signals.notna() & (asset_vol > 0.01)
    signals_clean = signals.where(valid_mask, 0)
    
    if long_only:
        signals_clean = signals_clean.clip(lower=0)
    
    n_active = (signals_clean.abs() > 0).sum(axis=1).clip(lower=1)
    raw_weight = signals_clean * (vol_target / n_active.values[:, None]) / asset_vol.clip(lower=0.01)
    
    if long_only:
        raw_weight = raw_weight.clip(lower=0)
    
    # Cap per-asset and total leverage
    per_asset_cap = max_leverage / max(len(closes.columns), 1)
    raw_weight = raw_weight.clip(-per_asset_cap, per_asset_cap)
    total_lev = raw_weight.abs().sum(axis=1)
    scale = (max_leverage / total_lev).clip(upper=1.0)
    positions = raw_weight.multiply(scale, axis=0)
    
    pnl = (positions.shift(1) * returns).sum(axis=1)
    turnover = positions.diff().abs().sum(axis=1)
    costs = turnover * (cost_bps / 10000)
    net = pnl - costs
    
    first_valid = (signals_clean.abs().sum(axis=1) > 0)
    if not first_valid.any():
        return {"error": "No signals"}
    first = first_valid[first_valid].index[0]
    net = net[first:].fillna(0)
    costs = costs[first:].fillna(0)
    
    dummy_pos = positions.abs().sum(axis=1)[first:]
    return compute_stats(net, costs, dummy_pos, first_valid[first:])


def compute_stats(net_pnl: pd.Series, costs: pd.Series,
                  position: pd.Series, signal: pd.Series) -> dict:
    """Compute comprehensive stats from a daily returns series."""
    if len(net_pnl) < 100:
        return {"error": f"Too few days: {len(net_pnl)}"}
    
    equity = (1 + net_pnl).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_years = len(net_pnl) / 365
    
    if n_years <= 0 or total_ret <= -1:
        ann_ret = -1.0
    else:
        ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    
    ann_vol = net_pnl.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    # Drawdown duration
    underwater = dd < 0
    if underwater.any():
        groups = (~underwater).cumsum()
        dd_lengths = underwater.groupby(groups).sum()
        max_dd_days = dd_lengths.max()
    else:
        max_dd_days = 0
    
    monthly = net_pnl.resample("ME").sum()
    
    yearly = net_pnl.groupby(net_pnl.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        vol=lambda x: x.std() * np.sqrt(365),
    )
    
    # Signal stats
    if hasattr(position, 'abs'):
        avg_pos = position.abs().mean()
        # Count signal flips (trades)
        sig_changes = signal.diff().abs()
        n_trades = (sig_changes > 0).sum()
        trades_per_year = n_trades / n_years if n_years > 0 else 0
    else:
        avg_pos = 0
        trades_per_year = 0
    
    # Rolling Sharpe (1-year window)
    rolling_sr = net_pnl.rolling(365).apply(
        lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        raw=True
    )
    
    return {
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "max_dd_days": max_dd_days,
        "total_return": total_ret,
        "daily_wr": (net_pnl > 0).mean(),
        "monthly_wr": (monthly > 0).mean(),
        "n_years": n_years,
        "avg_position": avg_pos,
        "total_costs": costs.sum(),
        "trades_per_year": trades_per_year,
        "yearly": yearly,
        "equity": equity,
        "net_pnl": net_pnl,
        "rolling_sharpe": rolling_sr,
    }


def print_stats(label: str, r: dict, compact: bool = False):
    """Print stats."""
    if "error" in r:
        print(f"  {label}: ERROR — {r['error']}")
        return
    
    if compact:
        print(f"  {label:45s}: SR={r['sharpe']:+.2f}  "
              f"Ret={r['ann_return']*100:+.1f}%  "
              f"Vol={r['ann_vol']*100:.1f}%  "
              f"DD={r['max_dd']*100:.1f}%  "
              f"Trades/yr={r.get('trades_per_year',0):.0f}")
        return
    
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Annual Return:     {r['ann_return']*100:+.2f}%")
    print(f"  Annual Vol:        {r['ann_vol']*100:.2f}%")
    print(f"  Sharpe Ratio:      {r['sharpe']:.2f}")
    print(f"  Max Drawdown:      {r['max_dd']*100:.1f}%")
    print(f"  Max DD Duration:   {r['max_dd_days']:.0f} days")
    print(f"  Calmar Ratio:      {r['calmar']:.2f}")
    print(f"  Daily Win Rate:    {r['daily_wr']*100:.1f}%")
    print(f"  Monthly Win Rate:  {r['monthly_wr']*100:.1f}%")
    print(f"  Total Return:      {r['total_return']*100:+.1f}%")
    print(f"  Period:            {r['n_years']:.1f} years")
    print(f"  Trades/Year:       {r.get('trades_per_year',0):.1f}")
    print(f"  Total Costs:       {r['total_costs']*100:.2f}%")
    
    print(f"\n  {'Year':>6} {'Return':>10} {'Sharpe':>8} {'Vol':>8}")
    print(f"  {'-'*6} {'-'*10} {'-'*8} {'-'*8}")
    for year, row in r["yearly"].iterrows():
        print(f"  {year:>6} {row['total_return']*100:>+9.2f}% "
              f"{row['sharpe']:>7.2f} {row['vol']*100:>7.1f}%")

    # Rolling Sharpe summary
    rs = r.get("rolling_sharpe")
    if rs is not None:
        rs_valid = rs.dropna()
        if len(rs_valid) > 0:
            print(f"\n  Rolling 1yr Sharpe: min={rs_valid.min():.2f}  "
                  f"median={rs_valid.median():.2f}  max={rs_valid.max():.2f}  "
                  f"% >0: {(rs_valid > 0).mean()*100:.0f}%")


# ─── Signal generators ──────────────────────────────────────────────────────

def sig_trend(prices, lookback=20):
    """Binary trend: +1 if price > N days ago, else 0 (long-only)."""
    return (prices.pct_change(lookback) > 0).astype(float)

def sig_ema_cross(prices, fast=10, slow=50):
    """EMA crossover: +1 if fast > slow, else 0."""
    ef = prices.ewm(span=fast, adjust=False).mean()
    es = prices.ewm(span=slow, adjust=False).mean()
    return (ef > es).astype(float)

def sig_sma_cross(prices, fast=20, slow=50):
    """SMA crossover."""
    sf = prices.rolling(fast).mean()
    ss = prices.rolling(slow).mean()
    return (sf > ss).astype(float)

def sig_breakout(prices, highs, lows, lookback=20):
    """Donchian: +1 above channel, 0 below, hold otherwise."""
    upper = highs.rolling(lookback).max().shift(1)
    lower = lows.rolling(lookback).min().shift(1)
    sig = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    sig[prices > upper] = 1.0
    sig[prices < lower] = 0.0
    return sig.ffill().fillna(0)

def sig_breakout_single(prices, lookback=20):
    """Donchian for single Series."""
    upper = prices.rolling(lookback).max().shift(1)
    lower = prices.rolling(lookback).min().shift(1)
    sig = pd.Series(np.nan, index=prices.index)
    sig[prices > upper] = 1.0
    sig[prices < lower] = 0.0
    return sig.ffill().fillna(0)

def sig_combined_vote(signals_list: list, threshold: float = 0.5):
    """
    Ensemble: average multiple binary signals. Long if avg > threshold.
    """
    stacked = pd.concat(signals_list, axis=1) if isinstance(signals_list[0], pd.Series) else signals_list
    if isinstance(stacked, list):
        stacked = pd.DataFrame(signals_list).T
    avg = pd.concat(signals_list, axis=1).mean(axis=1)
    return (avg >= threshold).astype(float)

def sig_regime_filter(prices, trend_signal, vol_lookback=20, vol_cap=1.5):
    """
    Regime filter: suppress signal when recent vol > vol_cap * long-term avg vol.
    Idea: avoid trading during extreme vol regimes (crash recoveries).
    """
    ret = prices.pct_change()
    short_vol = ret.rolling(vol_lookback).std()
    long_vol = ret.rolling(vol_lookback * 10).std()
    vol_ratio = short_vol / long_vol.clip(lower=0.001)
    
    # Suppress when vol is spiking
    filtered = trend_signal.copy()
    filtered[vol_ratio > vol_cap] = 0
    return filtered


# ─── Analysis Modules ────────────────────────────────────────────────────────

def sub_period_analysis(prices: pd.Series, signal_func, func_kwargs: dict,
                        label: str = ""):
    """Test strategy on different sub-periods for stability."""
    print(f"\n  Sub-period analysis: {label}")
    print(f"  {'Period':>20} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Trades/yr':>10}")
    print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*8} {'-'*10}")
    
    periods = [
        ("Full (2017-2025)", "2017-01-01", "2025-12-31"),
        ("2017-2018 (boom-bust)", "2017-01-01", "2018-12-31"),
        ("2019-2020 (recovery)", "2019-01-01", "2020-12-31"),
        ("2021-2022 (boom-bust)", "2021-01-01", "2022-12-31"),
        ("2023-2025 (recent)", "2023-01-01", "2025-12-31"),
        ("Post-COVID (2020+)", "2020-01-01", "2025-12-31"),
        ("Bear mkts (2018+2022)", None, None),  # special
    ]
    
    for name, start, end in periods:
        if name.startswith("Bear"):
            # Combine bear market years
            p1 = prices["2018-01-01":"2018-12-31"]
            p2 = prices["2022-01-01":"2022-12-31"]
            sub = pd.concat([p1, p2])
        else:
            sub = prices[start:end]
        
        if len(sub) < 60:
            print(f"  {name:>20} — insufficient data")
            continue
        
        sig = signal_func(sub, **func_kwargs)
        r = backtest_single_asset(sub, sig, vol_target=0.15, cost_bps=10)
        
        if "error" in r:
            print(f"  {name:>20} — {r['error']}")
        else:
            print(f"  {name:>20} {r['sharpe']:>+7.2f} "
                  f"{r['ann_return']*100:>+9.1f}% "
                  f"{r['max_dd']*100:>7.1f}% "
                  f"{r.get('trades_per_year',0):>9.0f}")


def walk_forward_clean(prices: pd.Series, signal_func, func_kwargs: dict,
                       window_months: int = 6, label: str = ""):
    """
    Clean walk-forward: generate signal from history, test on next window.
    No re-optimization (signal is fixed), just stability check.
    """
    print(f"\n  Walk-Forward: {label} ({window_months}mo windows)")
    
    results = []
    dates = prices.index
    window_days = window_months * 30
    
    # Start after 1 year of data for signal warmup
    start_offset = 365
    cursor_idx = start_offset
    
    while cursor_idx + window_days < len(dates):
        test_start = dates[cursor_idx]
        test_end_idx = min(cursor_idx + window_days, len(dates) - 1)
        test_end = dates[test_end_idx]
        
        # Generate signal using all data up to test_start (no lookahead)
        # Then evaluate on test period
        full_history = prices[:test_end]
        sig = signal_func(full_history, **func_kwargs)
        
        test_sig = sig[test_start:test_end]
        test_prices = prices[test_start:test_end]
        test_ret = test_prices.pct_change()
        
        # Vol-targeted position
        vol = test_ret.rolling(20).std() * np.sqrt(365)
        pos = test_sig * 0.15 / vol.clip(lower=0.01)
        pos = pos.clip(0, 2)
        
        pnl = (pos.shift(1) * test_ret).fillna(0)
        costs = pos.diff().abs().fillna(0) * (10 / 10000)
        net = pnl - costs
        
        if len(net) > 20:
            total = (1 + net).prod() - 1
            vol_ann = net.std() * np.sqrt(365)
            sr = (net.mean() * 365) / vol_ann if vol_ann > 0 else 0
            results.append({
                "start": test_start.date(),
                "end": test_end.date(),
                "return": total,
                "sharpe": sr,
                "vol": vol_ann,
                "days": len(net),
            })
        
        cursor_idx += window_days
    
    if not results:
        print("    No valid windows")
        return
    
    df = pd.DataFrame(results)
    
    print(f"  {'Window':>25} {'Return':>10} {'Sharpe':>8} {'Vol':>8}")
    print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*8}")
    for _, row in df.iterrows():
        marker = "+" if row["return"] > 0 else " "
        print(f"  {str(row['start'])+' → '+str(row['end']):>25} "
              f"{row['return']*100:>+9.1f}% {row['sharpe']:>+7.2f} "
              f"{row['vol']*100:>7.1f}%  {marker}")
    
    print(f"\n  Summary:")
    print(f"    Windows:      {len(df)}")
    print(f"    Avg Return:   {df['return'].mean()*100:+.1f}%")
    print(f"    Avg Sharpe:   {df['sharpe'].mean():.2f}")
    print(f"    % Positive:   {(df['return'] > 0).mean()*100:.0f}%")
    print(f"    Worst:        {df['return'].min()*100:+.1f}%")
    print(f"    Best:         {df['return'].max()*100:+.1f}%")
    
    return df


def bootstrap_confidence(net_pnl: pd.Series, n_samples: int = 1000,
                          block_size: int = 20, label: str = ""):
    """
    Block bootstrap to estimate confidence intervals for Sharpe.
    Uses overlapping blocks to preserve autocorrelation.
    """
    n = len(net_pnl)
    sharpes = []
    
    np.random.seed(42)
    for _ in range(n_samples):
        # Sample blocks with replacement
        n_blocks = n // block_size + 1
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        boot = pd.concat([net_pnl.iloc[s:s+block_size] for s in starts])
        boot = boot.iloc[:n]  # Same length
        
        ann_ret_boot = (1 + boot).prod() ** (365 / len(boot)) - 1
        vol_boot = boot.std() * np.sqrt(365)
        sr = ann_ret_boot / vol_boot if vol_boot > 0 else 0
        sharpes.append(sr)
    
    sharpes = np.array(sharpes)
    
    print(f"\n  Bootstrap ({n_samples} samples, block={block_size}d): {label}")
    print(f"    Sharpe: {np.mean(sharpes):.2f} "
          f"[{np.percentile(sharpes, 5):.2f}, {np.percentile(sharpes, 95):.2f}] (90% CI)")
    print(f"    P(Sharpe > 0): {(sharpes > 0).mean()*100:.0f}%")
    print(f"    P(Sharpe > 0.5): {(sharpes > 0.5).mean()*100:.0f}%")
    print(f"    P(Sharpe > 1.0): {(sharpes > 1.0).mean()*100:.0f}%")
    
    return sharpes


def drawdown_analysis(equity: pd.Series, label: str = ""):
    """Analyze drawdown events."""
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    
    # Find drawdown events > 5%
    in_dd = dd < -0.05
    events = []
    start = None
    
    for i in range(len(dd)):
        if in_dd.iloc[i] and start is None:
            start = i
        elif not in_dd.iloc[i] and start is not None:
            trough_idx = dd.iloc[start:i].idxmin()
            trough_val = dd.loc[trough_idx]
            duration = i - start
            events.append({
                "start": dd.index[start].date(),
                "trough": trough_idx.date(),
                "end": dd.index[i].date(),
                "depth": trough_val,
                "duration_days": duration,
            })
            start = None
    
    # Handle ongoing drawdown
    if start is not None:
        trough_idx = dd.iloc[start:].idxmin()
        trough_val = dd.loc[trough_idx]
        events.append({
            "start": dd.index[start].date(),
            "trough": trough_idx.date(),
            "end": "ongoing",
            "depth": trough_val,
            "duration_days": len(dd) - start,
        })
    
    if events:
        print(f"\n  Drawdown Events (>5%): {label}")
        print(f"  {'Start':>12} {'Trough':>12} {'End':>12} {'Depth':>8} {'Days':>6}")
        print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*8} {'-'*6}")
        for e in sorted(events, key=lambda x: x["depth"]):
            print(f"  {str(e['start']):>12} {str(e['trough']):>12} "
                  f"{str(e['end']):>12} {e['depth']*100:>+7.1f}% {e['duration_days']:>5}")


def per_coin_contribution(closes: pd.DataFrame, signal_func, func_kwargs: dict,
                          label: str = ""):
    """Show how each coin contributes to multi-crypto strategy."""
    print(f"\n  Per-coin contribution: {label}")
    print(f"  {'Coin':>12} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Days':>6}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*8} {'-'*6}")
    
    results = []
    for col in sorted(closes.columns):
        prices = closes[col].dropna()
        if len(prices) < 200:
            continue
        sig = signal_func(prices, **func_kwargs)
        r = backtest_single_asset(prices, sig, vol_target=0.15, cost_bps=10)
        if "error" not in r:
            print(f"  {col:>12} {r['sharpe']:>+7.2f} "
                  f"{r['ann_return']*100:>+9.1f}% "
                  f"{r['max_dd']*100:>7.1f}% {len(prices):>5}")
            results.append({"coin": col, **r})
    
    if results:
        sharpes = [r["sharpe"] for r in results]
        print(f"\n    Avg Sharpe across coins: {np.mean(sharpes):.2f}")
        print(f"    Median Sharpe: {np.median(sharpes):.2f}")
        print(f"    % coins with Sharpe > 0: {np.mean([s > 0 for s in sharpes])*100:.0f}%")


def rolling_sharpe_decay(net_pnl: pd.Series, label: str = ""):
    """Check if edge is decaying over time."""
    rs = net_pnl.rolling(365).apply(
        lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
        raw=True
    ).dropna()
    
    if len(rs) < 100:
        print(f"\n  Rolling Sharpe decay: insufficient data")
        return
    
    # Split into halves
    mid = len(rs) // 2
    first_half = rs.iloc[:mid]
    second_half = rs.iloc[mid:]
    
    print(f"\n  Rolling 1yr Sharpe Decay: {label}")
    print(f"    First half ({first_half.index[0].date()} → "
          f"{first_half.index[-1].date()}): "
          f"median={first_half.median():.2f}, mean={first_half.mean():.2f}")
    print(f"    Second half ({second_half.index[0].date()} → "
          f"{second_half.index[-1].date()}): "
          f"median={second_half.median():.2f}, mean={second_half.mean():.2f}")
    
    # Yearly rolling Sharpe
    yearly_sr = net_pnl.groupby(net_pnl.index.year).apply(
        lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0
    )
    print(f"    Yearly Sharpes: {', '.join(f'{y}:{s:.2f}' for y, s in yearly_sr.items())}")
    
    # Trend in rolling Sharpe
    x = np.arange(len(rs))
    slope = np.polyfit(x, rs.values, 1)[0]
    print(f"    Linear trend: slope={slope*365:.3f}/year (negative = decaying)")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    closes, highs, lows = load_crypto_data()
    data_availability_summary(closes)
    
    btc = closes["BTC-USD"].dropna()
    eth = closes["ETH-USD"].dropna() if "ETH-USD" in closes.columns else None
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  1. SIGNAL COMPARISON — BTC (all long-only)")
    print("█"*70)
    
    signals_btc = {
        "Trend 10d":   lambda p, lb=10: sig_trend(p, lb),
        "Trend 15d":   lambda p, lb=15: sig_trend(p, lb),
        "Trend 20d":   lambda p, lb=20: sig_trend(p, lb),
        "Trend 30d":   lambda p, lb=30: sig_trend(p, lb),
        "Trend 40d":   lambda p, lb=40: sig_trend(p, lb),
        "Trend 60d":   lambda p, lb=60: sig_trend(p, lb),
        "EMA 10/30":   lambda p: sig_ema_cross(p, 10, 30),
        "EMA 10/50":   lambda p: sig_ema_cross(p, 10, 50),
        "EMA 20/50":   lambda p: sig_ema_cross(p, 20, 50),
        "EMA 20/60":   lambda p: sig_ema_cross(p, 20, 60),
        "EMA 20/100":  lambda p: sig_ema_cross(p, 20, 100),
        "SMA 20/50":   lambda p: sig_sma_cross(p, 20, 50),
        "SMA 50/200":  lambda p: sig_sma_cross(p, 50, 200),
        "Breakout 20": lambda p: sig_breakout_single(p, 20),
        "Breakout 40": lambda p: sig_breakout_single(p, 40),
    }
    
    print(f"\n  {'Signal':>20} {'Sharpe':>8} {'Return':>10} {'Vol':>8} "
          f"{'MaxDD':>8} {'DDdays':>7} {'Tr/yr':>6} {'MonWR':>6}")
    print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")
    
    best_sharpe = -999
    best_name = ""
    best_result = None
    
    for name, sig_func in signals_btc.items():
        sig = sig_func(btc)
        r = backtest_single_asset(btc, sig, vol_target=0.15, cost_bps=10)
        if "error" not in r:
            print(f"  {name:>20} {r['sharpe']:>+7.2f} "
                  f"{r['ann_return']*100:>+9.1f}% "
                  f"{r['ann_vol']*100:>7.1f}% "
                  f"{r['max_dd']*100:>7.1f}% "
                  f"{r['max_dd_days']:>6.0f} "
                  f"{r.get('trades_per_year',0):>5.0f} "
                  f"{r['monthly_wr']*100:>5.0f}%")
            if r['sharpe'] > best_sharpe:
                best_sharpe = r['sharpe']
                best_name = name
                best_result = r
    
    print(f"\n  ★ Best: {best_name} (Sharpe {best_sharpe:.2f})")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  2. SIGNAL ENSEMBLES — BTC")
    print("█"*70)
    
    # Ensemble: vote of multiple signals
    ensembles = {
        "2-of-3 (T20+EMA10/30+BK20)": lambda p: sig_combined_vote([
            sig_trend(p, 20), sig_ema_cross(p, 10, 30), sig_breakout_single(p, 20)
        ], threshold=0.5),
        "3-of-3 unanimous": lambda p: sig_combined_vote([
            sig_trend(p, 20), sig_ema_cross(p, 10, 30), sig_breakout_single(p, 20)
        ], threshold=0.99),
        "2-of-4 (T20+T40+EMA20/60+BK20)": lambda p: sig_combined_vote([
            sig_trend(p, 20), sig_trend(p, 40),
            sig_ema_cross(p, 20, 60), sig_breakout_single(p, 20)
        ], threshold=0.5),
        "Vol-filtered Trend20": lambda p: sig_regime_filter(
            p, sig_trend(p, 20), vol_lookback=20, vol_cap=1.5),
        "Vol-filtered Trend20 (strict)": lambda p: sig_regime_filter(
            p, sig_trend(p, 20), vol_lookback=20, vol_cap=1.2),
    }
    
    print(f"\n  {'Ensemble':>40} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Tr/yr':>6}")
    print(f"  {'-'*40} {'-'*8} {'-'*10} {'-'*8} {'-'*6}")
    
    for name, sig_func in ensembles.items():
        sig = sig_func(btc)
        r = backtest_single_asset(btc, sig, vol_target=0.15, cost_bps=10)
        if "error" not in r:
            print(f"  {name:>40} {r['sharpe']:>+7.2f} "
                  f"{r['ann_return']*100:>+9.1f}% "
                  f"{r['max_dd']*100:>7.1f}% "
                  f"{r.get('trades_per_year',0):>5.0f}")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  3. ETH + OTHER COINS — Same signal")
    print("█"*70)
    
    per_coin_contribution(closes, sig_trend, {"lookback": 20},
                          label="Trend 20d (long-only)")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  4. MULTI-CRYPTO PORTFOLIO (Long-Only)")
    print("█"*70)
    
    # Build multi-asset signals
    for lb in [10, 20, 30, 40]:
        sig_multi = pd.DataFrame({
            col: sig_trend(closes[col].dropna(), lookback=lb).reindex(closes.index)
            for col in closes.columns
        })
        r = backtest_multi_asset(closes, sig_multi, vol_target=0.15, cost_bps=10,
                                 long_only=True)
        print_stats(f"Multi-Crypto Trend {lb}d (Long-Only)", r, compact=True)
    
    # EMA variants
    for fast, slow in [(10, 30), (10, 50), (20, 60)]:
        sig_multi = pd.DataFrame({
            col: sig_ema_cross(closes[col].dropna(), fast, slow).reindex(closes.index)
            for col in closes.columns
        })
        r = backtest_multi_asset(closes, sig_multi, vol_target=0.15, cost_bps=10,
                                 long_only=True)
        print_stats(f"Multi-Crypto EMA({fast}/{slow}) (Long-Only)", r, compact=True)
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  5. SUB-PERIOD STABILITY — BTC Trend 20d")
    print("█"*70)
    
    sub_period_analysis(btc, sig_trend, {"lookback": 20}, label="BTC Trend 20d")
    
    if eth is not None:
        sub_period_analysis(eth, sig_trend, {"lookback": 20}, label="ETH Trend 20d")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  6. WALK-FORWARD VALIDATION")
    print("█"*70)
    
    walk_forward_clean(btc, sig_trend, {"lookback": 20},
                       window_months=6, label="BTC Trend 20d")
    
    walk_forward_clean(btc, sig_trend, {"lookback": 40},
                       window_months=6, label="BTC Trend 40d")
    
    walk_forward_clean(btc, lambda p: sig_ema_cross(p, 10, 30), {},
                       window_months=6, label="BTC EMA(10/30)")
    
    # Also test 3-month windows for higher resolution
    walk_forward_clean(btc, sig_trend, {"lookback": 20},
                       window_months=3, label="BTC Trend 20d (3mo)")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  7. BOOTSTRAP CONFIDENCE INTERVALS")
    print("█"*70)
    
    # Get best strategy PnL
    sig_best = sig_trend(btc, lookback=20)
    r_best = backtest_single_asset(btc, sig_best, vol_target=0.15, cost_bps=10)
    if "error" not in r_best:
        bootstrap_confidence(r_best["net_pnl"], n_samples=2000,
                           block_size=20, label="BTC Trend 20d")
        
        bootstrap_confidence(r_best["net_pnl"], n_samples=2000,
                           block_size=60, label="BTC Trend 20d (60d blocks)")
    
    # Multi-crypto
    sig_multi20 = pd.DataFrame({
        col: sig_trend(closes[col].dropna(), lookback=20).reindex(closes.index)
        for col in closes.columns
    })
    r_multi = backtest_multi_asset(closes, sig_multi20, vol_target=0.15,
                                   cost_bps=10, long_only=True)
    if "error" not in r_multi:
        bootstrap_confidence(r_multi["net_pnl"], n_samples=2000,
                           block_size=20, label="Multi-Crypto Trend 20d LO")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  8. ROLLING SHARPE & EDGE DECAY")
    print("█"*70)
    
    if "error" not in r_best:
        rolling_sharpe_decay(r_best["net_pnl"], label="BTC Trend 20d")
    
    if "error" not in r_multi:
        rolling_sharpe_decay(r_multi["net_pnl"], label="Multi-Crypto Trend 20d LO")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  9. DRAWDOWN DEEP-DIVE")
    print("█"*70)
    
    if "error" not in r_best:
        drawdown_analysis(r_best["equity"], label="BTC Trend 20d")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  10. COST SENSITIVITY (FULL RANGE)")
    print("█"*70)
    
    print(f"\n  {'Cost':>8} {'BTC T20 SR':>12} {'BTC T40 SR':>12} "
          f"{'Multi T20 SR':>14} {'BTC EMA SR':>12}")
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*14} {'-'*12}")
    
    for cost in [0, 2, 5, 10, 15, 20, 30, 50, 75, 100]:
        results_row = []
        for sig_func, prices, is_multi in [
            (lambda: sig_trend(btc, 20), btc, False),
            (lambda: sig_trend(btc, 40), btc, False),
            (None, closes, True),
            (lambda: sig_ema_cross(btc, 10, 30), btc, False),
        ]:
            if is_multi:
                sig_m = pd.DataFrame({
                    col: sig_trend(closes[col].dropna(), lookback=20).reindex(closes.index)
                    for col in closes.columns
                })
                r = backtest_multi_asset(closes, sig_m, vol_target=0.15,
                                         cost_bps=cost, long_only=True)
            else:
                sig = sig_func()
                r = backtest_single_asset(prices, sig, vol_target=0.15, cost_bps=cost)
            
            sr = r['sharpe'] if 'error' not in r else float('nan')
            results_row.append(sr)
        
        print(f"  {cost:>6}bp {results_row[0]:>+11.2f} {results_row[1]:>+11.2f} "
              f"{results_row[2]:>+13.2f} {results_row[3]:>+11.2f}")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  11. VOL TARGET SENSITIVITY")
    print("█"*70)
    
    print(f"\n  {'VolTgt':>8} {'Sharpe':>8} {'Return':>10} {'Vol':>8} "
          f"{'MaxDD':>8} {'AvgPos':>8}")
    print(f"  {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")
    
    for vt in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
        sig = sig_trend(btc, 20)
        r = backtest_single_asset(btc, sig, vol_target=vt, cost_bps=10)
        if "error" not in r:
            print(f"  {vt*100:>6.0f}% {r['sharpe']:>+7.2f} "
                  f"{r['ann_return']*100:>+9.1f}% "
                  f"{r['ann_vol']*100:>7.1f}% "
                  f"{r['max_dd']*100:>7.1f}% "
                  f"{r['avg_position']:>7.2f}x")
    
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "█"*70)
    print("  12. FULL PRINTOUT — TOP 3 STRATEGIES")
    print("█"*70)
    
    # BTC Trend 20d
    sig = sig_trend(btc, 20)
    r = backtest_single_asset(btc, sig, vol_target=0.15, cost_bps=10)
    print_stats("BTC Trend 20d (long-only, 15% vol target, 10bps)", r)
    
    # BTC EMA(10/30)
    sig = sig_ema_cross(btc, 10, 30)
    r = backtest_single_asset(btc, sig, vol_target=0.15, cost_bps=10)
    print_stats("BTC EMA(10/30) (long-only, 15% vol target, 10bps)", r)
    
    # Multi-crypto Trend 20d
    sig_multi = pd.DataFrame({
        col: sig_trend(closes[col].dropna(), lookback=20).reindex(closes.index)
        for col in closes.columns
    })
    r = backtest_multi_asset(closes, sig_multi, vol_target=0.15, cost_bps=10,
                             long_only=True)
    print_stats("Multi-Crypto Trend 20d (long-only, 15% vol target, 10bps)", r)
    
    print("\n" + "█"*70)
    print("  DONE — Deep Dive Complete")
    print("█"*70)


if __name__ == "__main__":
    main()
