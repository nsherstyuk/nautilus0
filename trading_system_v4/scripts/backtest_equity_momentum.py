"""
S&P 500 Equity Momentum Strategy — Backtest
=============================================
Classic cross-sectional momentum: rank S&P 500 stocks by 12-month return
(skipping last month), go long top decile, short bottom decile.
Monthly rebalance.

Data: yfinance (free, no account, 20+ year history).
Period: 2010-2025 (post-GFC, realistic era).

Also tests: 
  - Long-only momentum (top quintile vs SPY benchmark)
  - Short-term mean reversion (5-day reversal)
  - Combined momentum + quality filter
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import List


# ─── S&P 500 Current Constituents ──────────────────────────────────────────
# Using a representative subset (~100 large-cap stocks) for speed.
# Full 500 would be more diversified but takes ~15 min to download.
# We test both a 100-stock subset and can scale up.

SP100_TICKERS = [
    # Tech
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO", "ADBE", "CRM",
    "ORCL", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT",
    # Finance
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "C", "AXP", "USB",
    # Healthcare
    "UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE", "SBUX", "TGT", "CL",
    # Industrial
    "CAT", "BA", "HON", "UPS", "GE", "RTX", "DE", "LMT", "MMM", "UNP",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
    # REITs / Utilities / Materials
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "AMT", "PLD", "CCI", "SPG",
    # Communication
    "DIS", "CMCSA", "NFLX", "T", "VZ", "TMUS", "CHTR", "EA", "ATVI", "WBD",
    # Other
    "V", "MA", "PYPL", "BRK-B", "PM", "MO", "LIN", "APD", "ECL", "SHW",
    "FDX", "DAL", "AAL", "UAL", "LUV", "F", "GM", "TM", "RIVN", "ABNB",
]

# Broader set for full test
SP200_EXTRA = [
    "GILD", "ISRG", "VRTX", "REGN", "MRNA", "ZTS", "SYK", "BDX", "CI", "HUM",
    "ALL", "TRV", "PGR", "MET", "AFL", "PRU", "AIG", "CB", "MMC", "CINF",
    "TJX", "ROST", "LOW", "HD", "ORLY", "AZO", "BBY", "DG", "DLTR", "KR",
    "EMR", "ITW", "PH", "ROK", "ETN", "IR", "CMI", "PCAR", "GD", "NOC",
    "DVN", "FANG", "PXD", "HES", "WMB", "KMI", "OKE", "ET", "TRGP", "LNG",
    "WEC", "ES", "XEL", "AEE", "CMS", "CNP", "PNW", "EVRG", "NI", "ATO",
    "ICE", "CME", "SPGI", "MCO", "MSCI", "NDAQ", "FIS", "FISV", "GPN", "ADP",
    "AMGN", "BIIB", "ILMN", "A", "IQV", "MTD", "WAT", "PKI", "DGX", "LH",
]


def download_data(tickers: List[str], start: str = "2008-01-01", 
                  end: str = "2025-12-31") -> pd.DataFrame:
    """Download daily adjusted close prices for all tickers."""
    print(f"Downloading {len(tickers)} stocks from {start} to {end}...")
    
    # Download in batches to avoid timeout
    batch_size = 50
    all_data = []
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        print(f"  Batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1}: "
              f"{batch[0]}..{batch[-1]}")
        try:
            data = yf.download(batch, start=start, end=end, 
                              auto_adjust=True, progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                closes = data["Close"]
            else:
                closes = data[["Close"]]
                closes.columns = batch
            all_data.append(closes)
        except Exception as e:
            print(f"    ERROR: {e}")
    
    if not all_data:
        raise RuntimeError("No data downloaded")
    
    closes = pd.concat(all_data, axis=1)
    closes = closes.ffill()
    
    # Drop stocks with too much missing data (>20% NaN)
    missing_frac = closes.isna().mean()
    good = missing_frac[missing_frac < 0.20].index
    closes = closes[good].dropna(how="all")
    
    print(f"  Got {len(closes)} days x {len(closes.columns)} stocks")
    print(f"  Date range: {closes.index[0].date()} to {closes.index[-1].date()}")
    print(f"  Dropped {len(tickers) - len(closes.columns)} stocks with >20% missing data")
    
    return closes


def compute_momentum_signal(closes: pd.DataFrame, 
                            lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """
    Classic 12-1 momentum: return over last 12 months, skipping most recent month.
    The skip avoids short-term reversal contaminating the momentum signal.
    """
    lagged = closes.shift(skip)
    mom = lagged.pct_change(lookback - skip)
    return mom


def compute_reversal_signal(closes: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Short-term mean reversion: negative of 5-day return."""
    return -closes.pct_change(lookback)


def compute_quality_signal(closes: pd.DataFrame) -> pd.DataFrame:
    """
    Quality proxy: low volatility stocks tend to outperform (low-vol anomaly).
    Use negative 63-day volatility as quality signal (lower vol = higher score).
    """
    returns = closes.pct_change()
    vol = returns.rolling(63).std()
    return -vol  # negative: lower vol = higher signal


def run_long_short_backtest(closes: pd.DataFrame, signals: pd.DataFrame,
                            n_long: int = 20, n_short: int = 20,
                            rebal_freq: str = "M",
                            cost_bps: float = 10.0,
                            label: str = "") -> dict:
    """
    Run a long/short cross-sectional backtest.
    
    Args:
        closes: daily prices
        signals: signal values (higher = more long)
        n_long: number of stocks to go long
        n_short: number of stocks to go short
        rebal_freq: 'M' for monthly, 'W' for weekly
        cost_bps: round-trip transaction cost in basis points
        label: description
    """
    returns = closes.pct_change()
    
    # Get rebalance dates
    if rebal_freq == "M":
        rebal_mask = returns.index.to_series().dt.is_month_end
    else:
        rebal_mask = returns.index.to_series().dt.dayofweek == 4  # Friday
    
    rebal_dates = returns.index[rebal_mask]
    
    # Build positions (start as NaN so ffill works correctly)
    positions = pd.DataFrame(np.nan, index=returns.index, columns=returns.columns)
    n_rebals = 0
    first_rebal_idx = None
    
    for date in rebal_dates:
        if date not in signals.index:
            continue
        sig = signals.loc[date].dropna()
        if len(sig) < n_long + n_short:
            continue
        
        ranked = sig.sort_values()
        short_names = ranked.index[:n_short].tolist()
        long_names = ranked.index[-n_long:].tolist()
        
        # Full row: explicit zeros for non-held stocks
        new_pos = pd.Series(0.0, index=returns.columns)
        for s in long_names:
            new_pos[s] = 1.0 / n_long
        for s in short_names:
            new_pos[s] = -1.0 / n_short
        
        n_rebals += 1
        pos_idx = returns.index.get_loc(date)
        if first_rebal_idx is None:
            first_rebal_idx = pos_idx
        positions.iloc[pos_idx] = new_pos
    
    if first_rebal_idx is None:
        return {"error": "No valid rebalance dates"}
    
    # Forward-fill: zeros for non-held stocks ARE real positions
    positions = positions.ffill()
    
    positions = positions.fillna(0)
    
    # PnL
    daily_pnl = (positions.shift(1) * returns).sum(axis=1)
    
    # Costs
    turnover = positions.diff().abs().sum(axis=1)
    daily_costs = turnover * (cost_bps / 10000)
    net_pnl = daily_pnl - daily_costs
    
    # Trim to active period
    active_start = positions.index[first_rebal_idx]
    net_pnl = net_pnl[active_start:]
    daily_pnl = daily_pnl[active_start:]
    
    if len(net_pnl) < 50:
        return {"error": f"Too few trading days: {len(net_pnl)}"}
    
    # Metrics
    equity = (1 + net_pnl).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_years = len(net_pnl) / 252
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = net_pnl.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    weekly_pnl = net_pnl.resample("W").sum()
    monthly_pnl = net_pnl.resample("ME").sum()
    
    # Yearly
    yearly = net_pnl.groupby(net_pnl.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0,
        vol=lambda x: x.std() * np.sqrt(252),
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
        "weekly_wr": (weekly_pnl > 0).mean(),
        "monthly_wr": (monthly_pnl > 0).mean(),
        "n_years": n_years,
        "n_rebals": n_rebals,
        "total_cost_frac": daily_costs.sum(),
        "yearly": yearly,
        "equity": equity,
        "net_pnl": net_pnl,
    }


def run_long_only_backtest(closes: pd.DataFrame, signals: pd.DataFrame,
                           n_long: int = 20, rebal_freq: str = "M",
                           cost_bps: float = 10.0, label: str = "") -> dict:
    """Long-only: buy top N stocks by signal, equal weight, monthly rebal."""
    returns = closes.pct_change()
    
    if rebal_freq == "M":
        rebal_mask = returns.index.to_series().dt.is_month_end
    else:
        rebal_mask = returns.index.to_series().dt.dayofweek == 4
    
    rebal_dates = returns.index[rebal_mask]
    
    positions = pd.DataFrame(np.nan, index=returns.index, columns=returns.columns)
    n_rebals = 0
    first_rebal_idx = None
    
    for date in rebal_dates:
        if date not in signals.index:
            continue
        sig = signals.loc[date].dropna()
        if len(sig) < n_long:
            continue
        
        ranked = sig.sort_values()
        long_names = ranked.index[-n_long:].tolist()
        
        new_pos = pd.Series(0.0, index=returns.columns)
        for s in long_names:
            new_pos[s] = 1.0 / n_long
        
        n_rebals += 1
        pos_idx = returns.index.get_loc(date)
        if first_rebal_idx is None:
            first_rebal_idx = pos_idx
        positions.iloc[pos_idx] = new_pos
    
    if first_rebal_idx is None:
        return {"error": "No rebalance dates"}
    
    positions = positions.ffill()
    positions = positions.fillna(0)
    
    daily_pnl = (positions.shift(1) * returns).sum(axis=1)
    turnover = positions.diff().abs().sum(axis=1)
    daily_costs = turnover * (cost_bps / 10000)
    net_pnl = daily_pnl - daily_costs
    
    active_start = positions.index[first_rebal_idx]
    net_pnl = net_pnl[active_start:]
    
    if len(net_pnl) < 50:
        return {"error": f"Too few days: {len(net_pnl)}"}
    
    equity = (1 + net_pnl).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_years = len(net_pnl) / 252
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = net_pnl.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    
    # SPY benchmark (equal weight benchmark)
    spy_ret = returns.mean(axis=1)[active_start:]
    spy_equity = (1 + spy_ret).cumprod()
    spy_total = spy_equity.iloc[-1] - 1
    spy_ann = (1 + spy_total) ** (1 / n_years) - 1
    spy_vol = spy_ret.std() * np.sqrt(252)
    spy_sharpe = spy_ann / spy_vol if spy_vol > 0 else 0
    
    monthly_pnl = net_pnl.resample("ME").sum()
    
    yearly = net_pnl.groupby(net_pnl.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0,
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
        "monthly_wr": (monthly_pnl > 0).mean(),
        "n_years": n_years,
        "n_rebals": n_rebals,
        "yearly": yearly,
        "equity": equity,
        "benchmark_ann_return": spy_ann,
        "benchmark_sharpe": spy_sharpe,
        "excess_return": ann_ret - spy_ann,
    }


def print_results(r: dict):
    """Pretty-print results."""
    if "error" in r:
        print(f"  {r.get('label', '???')}: {r['error']}")
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
    if "monthly_wr" in r:
        print(f"  Monthly Win Rate: {r['monthly_wr']*100:.1f}%")
    print(f"  Total Return:     {r['total_return']*100:+.1f}%")
    print(f"  Period:           {r['n_years']:.1f} years")
    print(f"  Rebalances:       {r['n_rebals']}")
    if "benchmark_ann_return" in r:
        print(f"  Benchmark Return: {r['benchmark_ann_return']*100:+.2f}%")
        print(f"  Benchmark Sharpe: {r['benchmark_sharpe']:.2f}")
        print(f"  Excess Return:    {r['excess_return']*100:+.2f}%")
    if "total_cost_frac" in r:
        print(f"  Total Costs:      {r['total_cost_frac']*100:.2f}% of NAV")
    
    print(f"\n  {'Year':>6} {'Return':>10} {'Sharpe':>8}")
    print(f"  {'-'*6} {'-'*10} {'-'*8}")
    for year, row in r["yearly"].iterrows():
        print(f"  {year:>6} {row['total_return']*100:>+9.2f}% {row['sharpe']:>7.2f}")
    print()


def main():
    # ──────────────────────────────────────────────────────────────────────
    # 1. Download data (or load from cache)
    # ──────────────────────────────────────────────────────────────────────
    import os
    cache_path = "trading_system_v4/data/equity_daily_closes.parquet"
    if os.path.exists(cache_path):
        print(f"Loading cached data from {cache_path}...")
        closes = pd.read_parquet(cache_path)
        print(f"  {len(closes)} days x {len(closes.columns)} stocks")
    else:
        tickers = SP100_TICKERS + SP200_EXTRA
        closes = download_data(tickers, start="2008-01-01", end="2025-12-31")
        closes.to_parquet(cache_path)
        print(f"  Saved to {cache_path}\n")
    
    # ──────────────────────────────────────────────────────────────────────
    # 2. Compute signals
    # ──────────────────────────────────────────────────────────────────────
    print("Computing signals...")
    mom_12_1 = compute_momentum_signal(closes, lookback=252, skip=21)
    mom_6_1  = compute_momentum_signal(closes, lookback=126, skip=21)
    mom_3_1  = compute_momentum_signal(closes, lookback=63, skip=21)
    reversal = compute_reversal_signal(closes, lookback=5)
    quality  = compute_quality_signal(closes)
    
    # ──────────────────────────────────────────────────────────────────────
    # 3. LONG/SHORT MOMENTUM TESTS
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  LONG/SHORT MOMENTUM TESTS")
    print("="*70)
    
    # Classic 12-1 momentum
    r = run_long_short_backtest(closes, mom_12_1, n_long=20, n_short=20,
                                cost_bps=10, label="L/S 12-1 Momentum (20/20)")
    print_results(r)
    
    # 6-1 momentum
    r = run_long_short_backtest(closes, mom_6_1, n_long=20, n_short=20,
                                cost_bps=10, label="L/S 6-1 Momentum (20/20)")
    print_results(r)
    
    # 3-1 momentum
    r = run_long_short_backtest(closes, mom_3_1, n_long=20, n_short=20,
                                cost_bps=10, label="L/S 3-1 Momentum (20/20)")
    print_results(r)
    
    # ──────────────────────────────────────────────────────────────────────
    # 4. LONG-ONLY MOMENTUM TESTS (more practical for retail)
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  LONG-ONLY MOMENTUM (vs equal-weight benchmark)")
    print("="*70)
    
    r = run_long_only_backtest(closes, mom_12_1, n_long=20, cost_bps=10,
                               label="Long-Only 12-1 Mom Top 20")
    print_results(r)
    
    r = run_long_only_backtest(closes, mom_6_1, n_long=20, cost_bps=10,
                               label="Long-Only 6-1 Mom Top 20")
    print_results(r)
    
    # Bigger portfolio
    r = run_long_only_backtest(closes, mom_12_1, n_long=40, cost_bps=10,
                               label="Long-Only 12-1 Mom Top 40")
    print_results(r)
    
    # ──────────────────────────────────────────────────────────────────────
    # 5. SHORT-TERM REVERSAL
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  SHORT-TERM REVERSAL (5-day)")
    print("="*70)
    
    r = run_long_short_backtest(closes, reversal, n_long=20, n_short=20,
                                rebal_freq="W", cost_bps=10,
                                label="L/S 5-Day Reversal (weekly rebal)")
    print_results(r)
    
    # ──────────────────────────────────────────────────────────────────────
    # 6. COMBINED: MOMENTUM + QUALITY
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  COMBINED SIGNALS")
    print("="*70)
    
    # Normalized rank blend
    mom_rank = mom_12_1.rank(axis=1, pct=True)
    qual_rank = quality.rank(axis=1, pct=True)
    rev_rank = reversal.rank(axis=1, pct=True)
    
    # Mom + Quality (low vol)
    combined_mq = 0.7 * mom_rank + 0.3 * qual_rank
    r = run_long_short_backtest(closes, combined_mq, n_long=20, n_short=20,
                                cost_bps=10, label="L/S Momentum(70%) + Quality(30%)")
    print_results(r)
    
    r = run_long_only_backtest(closes, combined_mq, n_long=20, cost_bps=10,
                               label="Long-Only Mom(70%) + Quality(30%) Top 20")
    print_results(r)
    
    # Mom + Reversal
    combined_mr = 0.6 * mom_rank + 0.4 * rev_rank
    r = run_long_short_backtest(closes, combined_mr, n_long=20, n_short=20,
                                rebal_freq="W", cost_bps=10,
                                label="L/S Momentum(60%) + Reversal(40%) weekly")
    print_results(r)
    
    # ──────────────────────────────────────────────────────────────────────
    # 7. PARAMETER SENSITIVITY
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  PARAMETER SENSITIVITY")
    print("="*70)
    
    # N_long/N_short sweep
    print("\n--- Portfolio Size (L/S 12-1 Mom) ---")
    for n in [10, 20, 30, 40]:
        r = run_long_short_backtest(closes, mom_12_1, n_long=n, n_short=n,
                                    cost_bps=10, label=f"n={n}")
        if "error" not in r:
            print(f"  n={n:>2}: Sharpe={r['sharpe']:.2f}, Return={r['ann_return']*100:+.1f}%, "
                  f"MaxDD={r['max_dd']*100:.1f}%, MonthlyWR={r.get('monthly_wr',0)*100:.1f}%")
    
    # Cost sensitivity
    print("\n--- Transaction Cost Sensitivity (L/S 12-1 Mom, n=20) ---")
    for cost in [0, 5, 10, 20, 30, 50]:
        r = run_long_short_backtest(closes, mom_12_1, n_long=20, n_short=20,
                                    cost_bps=cost, label=f"cost={cost}bps")
        if "error" not in r:
            print(f"  cost={cost:>2}bps: Sharpe={r['sharpe']:.2f}, Return={r['ann_return']*100:+.1f}%")
    
    # Momentum lookback sweep
    print("\n--- Momentum Lookback (L/S, n=20, 10bps cost) ---")
    for lb, skip in [(63, 10), (126, 21), (252, 21), (504, 42)]:
        sig = compute_momentum_signal(closes, lookback=lb, skip=skip)
        r = run_long_short_backtest(closes, sig, n_long=20, n_short=20,
                                    cost_bps=10, label=f"lb={lb}")
        if "error" not in r:
            print(f"  lookback={lb:>3}d: Sharpe={r['sharpe']:.2f}, Return={r['ann_return']*100:+.1f}%")
    
    print("\n" + "="*70)
    print("  DONE")
    print("="*70)


if __name__ == "__main__":
    main()
