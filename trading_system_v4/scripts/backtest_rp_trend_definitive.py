"""
backtest_rp_trend_definitive.py — Definitive backtest of Risk Parity + Trend

Strategy:
  - Universe: SPY, TLT, GLD, VNQ (4 uncorrelated ETFs)
  - Trend filter: only hold asset if price > SMA200
  - Position sizing: inverse-volatility (60d rolling vol)
  - Rebalance: first trading day of each month
  - Cost: 0.03% round-trip per ETF trade on IBKR

What this script produces:
  1. Full 22-year backtest (2003-2026) with yearly breakdown
  2. Walk-forward OOS: train on 5yr → test on 1yr, rolling
  3. Drawdown analysis and recovery times
  4. Monthly trade log (what you'd actually trade)
  5. Current signal: what to hold RIGHT NOW
  6. Comparison with alternatives (static RP, SPY B&H, 60/40)
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
CACHE = DATA_DIR / "multi_asset_daily.parquet"

COST_RT = 0.0003  # 0.03% round-trip
ANN = 252


# ── Helpers ───────────────────────────────────────────────────────────────────

def sharpe(r, af=ANN):
    return r.mean() / (r.std() + 1e-10) * np.sqrt(af)

def max_dd(eq):
    return ((eq - eq.cummax()) / eq.cummax()).min()

def cagr(eq, af=ANN):
    n = len(eq) / af
    return (eq.iloc[-1] / eq.iloc[0]) ** (1/n) - 1 if n > 0 and eq.iloc[0] > 0 else 0

def calmar(eq, af=ANN):
    c = cagr(eq, af)
    d = abs(max_dd(eq))
    return c / d if d > 0 else 0

def sortino(r, af=ANN):
    down = r[r < 0].std()
    return r.mean() / (down + 1e-10) * np.sqrt(af)


# ══════════════════════════════════════════════════════════════════════════════
#  CORE STRATEGY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def run_rp_trend(prices: pd.DataFrame,
                 assets: list[str],
                 sma_len: int = 200,
                 vol_window: int = 60,
                 use_trend: bool = True,
                 cost_rt: float = COST_RT) -> dict:
    """
    Run Risk Parity (+Trend) strategy. Returns dict with equity, weights, stats.
    """
    avail = [a for a in assets if a in prices.columns]
    p = prices[avail].ffill().dropna()
    rets = p.pct_change()
    vol = rets.rolling(vol_window).std()
    sma = p.rolling(sma_len).mean()
    warmup = sma_len

    weights_df = pd.DataFrame(0.0, index=p.index, columns=avail)
    current_w = pd.Series(0.0, index=avail)
    rebal_dates = []
    trade_log = []

    for i in range(warmup, len(p)):
        dt = p.index[i]
        is_month = (i == warmup) or (dt.month != p.index[i-1].month)

        if is_month:
            new_w = pd.Series(0.0, index=avail)
            for a in avail:
                v = vol[a].iloc[i]
                if np.isnan(v) or v <= 0:
                    v = 0.01
                if use_trend and p[a].iloc[i] < sma[a].iloc[i]:
                    new_w[a] = 0.0  # below trend → cash
                else:
                    new_w[a] = 1.0 / v

            total = new_w.sum()
            if total > 0:
                new_w /= total

            # Log trades
            delta = new_w - current_w
            if delta.abs().sum() > 1e-6:
                for a in avail:
                    if abs(delta[a]) > 0.001:
                        trade_log.append({
                            'date': dt,
                            'asset': a,
                            'old_wt': current_w[a],
                            'new_wt': new_w[a],
                            'delta': delta[a],
                            'price': p[a].iloc[i],
                        })

            current_w = new_w
            rebal_dates.append(dt)

        weights_df.iloc[i] = current_w

    # PnL
    strat_ret = (weights_df.shift(1) * rets).sum(axis=1)
    turnover = weights_df.diff().abs().sum(axis=1)
    costs = turnover * cost_rt
    strat_net = strat_ret - costs

    valid = strat_net.iloc[warmup:]
    eq = (1 + valid).cumprod()

    return {
        'equity': eq,
        'returns': valid,
        'weights': weights_df.iloc[warmup:],
        'rebal_dates': rebal_dates,
        'trade_log': pd.DataFrame(trade_log) if trade_log else pd.DataFrame(),
        'total_cost': costs.sum(),
        'n_rebal': len(rebal_dates),
        'assets': avail,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def print_stats(label: str, eq: pd.Series, rets: pd.Series, n_rebal: int = 0):
    """Print strategy statistics."""
    c = cagr(eq) * 100
    s = sharpe(rets)
    d = max_dd(eq) * 100
    cal = calmar(eq)
    sor = sortino(rets)

    print(f"  {label}")
    print(f"    CAGR:     {c:+.2f}%")
    print(f"    Sharpe:   {s:+.3f}")
    print(f"    Sortino:  {sor:+.3f}")
    print(f"    MaxDD:    {d:.1f}%")
    print(f"    Calmar:   {cal:.3f}")
    if n_rebal:
        print(f"    Rebalances: {n_rebal}")


def yearly_breakdown(rets: pd.Series, label: str = ""):
    """Print yearly returns."""
    if label:
        print(f"\n  {label} — Yearly Returns:")
    print(f"    {'Year':>6s} {'Return':>8s} {'Sharpe':>8s} {'MaxDD':>8s}")
    print(f"    {'─'*6} {'─'*8} {'─'*8} {'─'*8}")

    for yr, grp in rets.groupby(rets.index.year):
        yr_ret = (1 + grp).prod() - 1
        eq_yr = (1 + grp).cumprod()
        yr_dd = max_dd(eq_yr) * 100
        yr_sh = sharpe(grp)
        mark = "  ✗" if yr_ret < 0 else ""
        print(f"    {yr:>6d} {yr_ret*100:>+7.1f}% {yr_sh:>+7.2f} {yr_dd:>7.1f}%{mark}")

    wins = sum(1 for _, g in rets.groupby(rets.index.year) if (1+g).prod()-1 > 0)
    total = len(rets.groupby(rets.index.year))
    print(f"    Win years: {wins}/{total} ({wins/total*100:.0f}%)")


def drawdown_analysis(eq: pd.Series):
    """Find worst drawdowns and recovery times."""
    print(f"\n  Drawdown Analysis:")

    dd = (eq - eq.cummax()) / eq.cummax()

    # Find drawdown periods
    in_dd = dd < -0.01  # >1% drawdown
    dd_periods = []
    start = None

    for i in range(len(dd)):
        if in_dd.iloc[i] and start is None:
            start = i
        elif not in_dd.iloc[i] and start is not None:
            trough_idx = dd.iloc[start:i].idxmin()
            dd_depth = dd.loc[trough_idx]
            duration = (eq.index[i] - eq.index[start]).days
            dd_periods.append({
                'start': eq.index[start],
                'trough': trough_idx,
                'end': eq.index[i],
                'depth': dd_depth * 100,
                'duration_days': duration,
            })
            start = None

    # Handle ongoing drawdown
    if start is not None:
        trough_idx = dd.iloc[start:].idxmin()
        dd_periods.append({
            'start': eq.index[start],
            'trough': trough_idx,
            'end': eq.index[-1],
            'depth': dd.loc[trough_idx] * 100,
            'duration_days': (eq.index[-1] - eq.index[start]).days,
        })

    if not dd_periods:
        print("    No significant drawdowns found")
        return

    # Sort by depth
    dd_periods.sort(key=lambda x: x['depth'])

    print(f"    {'#':>3s} {'Depth':>7s} {'Start':>12s} {'Trough':>12s} {'End':>12s} {'Days':>6s}")
    print(f"    {'─'*3} {'─'*7} {'─'*12} {'─'*12} {'─'*12} {'─'*6}")
    for idx, p in enumerate(dd_periods[:10]):
        print(f"    {idx+1:>3d} {p['depth']:>6.1f}% "
              f"{p['start'].strftime('%Y-%m-%d'):>12s} "
              f"{p['trough'].strftime('%Y-%m-%d'):>12s} "
              f"{p['end'].strftime('%Y-%m-%d'):>12s} "
              f"{p['duration_days']:>5d}d")


def walk_forward_oos(prices: pd.DataFrame, assets: list[str]):
    """Walk-forward OOS: train SMA params on 5yr, test on 1yr."""
    print(f"\n{'='*72}")
    print("  WALK-FORWARD OUT-OF-SAMPLE TEST")
    print("  Train window: 5 years | Test window: 1 year | Rolling")
    print("="*72)

    train_years = 5
    test_years = 1
    sma_candidates = [100, 150, 200, 250, 300]

    avail = [a for a in assets if a in prices.columns]
    p = prices[avail].ffill().dropna()
    rets = p.pct_change()

    first_year = p.index[0].year + 1  # skip partial first year
    last_year = p.index[-1].year

    # Need train_years + 1 year of warmup (for SMA300)
    start_test_year = first_year + train_years + 1
    end_test_year = last_year

    print(f"  OOS test years: {start_test_year} → {end_test_year}")
    print(f"  SMA candidates: {sma_candidates}")

    oos_results = []

    for test_yr in range(start_test_year, end_test_year + 1):
        train_end = f"{test_yr - 1}-12-31"
        train_start = f"{test_yr - 1 - train_years}-01-01"
        test_start = f"{test_yr}-01-01"
        test_end = f"{test_yr}-12-31"

        train_mask = (p.index >= train_start) & (p.index <= train_end)
        test_mask = (p.index >= test_start) & (p.index <= test_end)

        if train_mask.sum() < 252 * 3 or test_mask.sum() < 50:
            continue

        # Find best SMA in training period
        best_sma = 200
        best_sharpe = -999

        for sma_len in sma_candidates:
            train_p = p[train_mask]
            res = run_rp_trend(train_p, avail, sma_len=sma_len)
            if len(res['returns']) > 100:
                s = sharpe(res['returns'])
                if s > best_sharpe:
                    best_sharpe = s
                    best_sma = sma_len

        # Test with best SMA on OOS year
        # Run on full data up to test_end to get proper SMA warmup
        full_mask = p.index <= test_end
        test_res = run_rp_trend(p[full_mask], avail, sma_len=best_sma)

        # Extract just the test year returns
        test_rets = test_res['returns']
        test_rets = test_rets[(test_rets.index >= test_start) & (test_rets.index <= test_end)]

        if len(test_rets) < 20:
            continue

        oos_ret = (1 + test_rets).prod() - 1
        oos_sh = sharpe(test_rets)
        oos_eq = (1 + test_rets).cumprod()
        oos_dd = max_dd(oos_eq) * 100

        oos_results.append({
            'year': test_yr,
            'best_sma': best_sma,
            'train_sharpe': best_sharpe,
            'oos_return': oos_ret,
            'oos_sharpe': oos_sh,
            'oos_dd': oos_dd,
        })

    if not oos_results:
        print("  No OOS results (not enough data)")
        return

    rdf = pd.DataFrame(oos_results)
    print(f"\n    {'Year':>6s} {'BestSMA':>8s} {'TrainSh':>9s} {'OOS Ret':>9s} {'OOS Sh':>8s} {'OOS DD':>8s}")
    print(f"    {'─'*6} {'─'*8} {'─'*9} {'─'*9} {'─'*8} {'─'*8}")

    for _, row in rdf.iterrows():
        mark = "  ✗" if row['oos_return'] < 0 else ""
        print(f"    {int(row['year']):>6d} "
              f"SMA{int(row['best_sma']):>3d} "
              f"{row['train_sharpe']:>+8.2f} "
              f"{row['oos_return']*100:>+8.1f}% "
              f"{row['oos_sharpe']:>+7.2f} "
              f"{row['oos_dd']:>7.1f}%{mark}")

    avg_ret = rdf['oos_return'].mean() * 100
    avg_sh = rdf['oos_sharpe'].mean()
    win_pct = (rdf['oos_return'] > 0).mean() * 100
    print(f"\n    Average OOS return: {avg_ret:+.1f}%")
    print(f"    Average OOS Sharpe: {avg_sh:+.3f}")
    print(f"    Win rate: {win_pct:.0f}% of years")
    print(f"    Most selected SMA: {rdf['best_sma'].mode().iloc[0]}")


def current_signal(prices: pd.DataFrame, assets: list[str]):
    """Show what the strategy says to hold RIGHT NOW."""
    print(f"\n{'='*72}")
    print("  CURRENT SIGNAL — What to hold today")
    print("="*72)

    avail = [a for a in assets if a in prices.columns]
    p = prices[avail].ffill()

    latest = p.iloc[-1]
    sma200 = p.rolling(200).mean().iloc[-1]
    vol60 = p.pct_change().rolling(60).std().iloc[-1]

    print(f"    Date: {p.index[-1].strftime('%Y-%m-%d')}")
    print(f"\n    {'Asset':>6s} {'Price':>10s} {'SMA200':>10s} {'Signal':>8s} {'Vol60':>8s} {'Weight':>8s}")
    print(f"    {'─'*6} {'─'*10} {'─'*10} {'─'*8} {'─'*8} {'─'*8}")

    raw_w = {}
    for a in avail:
        price = latest[a]
        sma_val = sma200[a]
        v = vol60[a]
        above = price > sma_val
        signal = "LONG" if above else "CASH"

        inv_v = (1.0 / v) if above and v > 0 else 0.0
        raw_w[a] = inv_v

        print(f"    {a:>6s} ${price:>9.2f} ${sma_val:>9.2f} {signal:>8s} {v*100:>7.1f}% ", end="")
        print()  # weight computed after normalization

    # Normalize
    total = sum(raw_w.values())
    if total > 0:
        norm_w = {a: w/total for a, w in raw_w.items()}
    else:
        norm_w = {a: 0.0 for a in avail}

    print(f"\n    Target portfolio allocation:")
    cash_weight = 0.0
    for a in avail:
        w = norm_w[a]
        if w > 0.001:
            print(f"      {a}: {w*100:>5.1f}%")
        else:
            cash_weight += 1.0 / len(avail)  # notional share that's in cash

    total_invested = sum(v for v in norm_w.values() if v > 0)
    print(f"      Cash: {(1-total_invested)*100:>5.1f}%")
    print(f"    (Rebalance on first trading day of next month)")


def compare_strategies(prices: pd.DataFrame):
    """Compare RP+Trend vs alternatives."""
    print(f"\n{'='*72}")
    print("  COMPARISON: RP+Trend vs Alternatives")
    print("="*72)

    assets = ['SPY', 'TLT', 'GLD', 'VNQ']
    avail = [a for a in assets if a in prices.columns]

    # 1. Risk Parity + Trend
    res1 = run_rp_trend(prices, avail, use_trend=True)

    # 2. Static Risk Parity (no trend filter)
    res2 = run_rp_trend(prices, avail, use_trend=False)

    # 3. SPY Buy & Hold
    spy = prices['SPY'].ffill().dropna()
    spy_rets = spy.pct_change().iloc[200:]
    spy_eq = (1 + spy_rets).cumprod()

    # 4. 60/40 SPY/TLT
    if 'TLT' in prices.columns:
        p60 = prices[['SPY', 'TLT']].ffill().dropna()
        r60 = p60.pct_change()
        ret60 = r60['SPY'] * 0.6 + r60['TLT'] * 0.4
        ret60 = ret60.iloc[200:]
        eq60 = (1 + ret60).cumprod()
    else:
        ret60 = spy_rets
        eq60 = spy_eq

    # 5. Equal weight
    p_ew = prices[avail].ffill().dropna()
    r_ew = p_ew.pct_change()
    ret_ew = r_ew.mean(axis=1).iloc[200:]
    eq_ew = (1 + ret_ew).cumprod()

    results = [
        ("Risk Parity + Trend", res1['equity'], res1['returns']),
        ("Static Risk Parity", res2['equity'], res2['returns']),
        ("Equal Weight (4 ETF)", eq_ew, ret_ew),
        ("60/40 SPY/TLT", eq60, ret60),
        ("SPY Buy & Hold", spy_eq, spy_rets),
    ]

    print(f"    {'Strategy':<25s} {'CAGR':>7s} {'Sharpe':>8s} {'Sortino':>9s} "
          f"{'MaxDD':>8s} {'Calmar':>8s}")
    print(f"    {'─'*25} {'─'*7} {'─'*8} {'─'*9} {'─'*8} {'─'*8}")

    for label, eq, rets in results:
        c = cagr(eq) * 100
        s = sharpe(rets)
        so = sortino(rets)
        d = max_dd(eq) * 100
        cal = calmar(eq)
        print(f"    {label:<25s} {c:>+6.1f}% {s:>+7.3f} {so:>+8.3f} "
              f"{d:>7.1f}% {cal:>7.3f}")

    # Correlation of strategies
    print(f"\n    Return correlations (daily):")
    corr_data = {}
    for label, _, rets in results[:3]:
        corr_data[label[:15]] = rets

    corr_df = pd.DataFrame(corr_data)
    # Align indices
    corr_df = corr_df.dropna()
    corr = corr_df.corr()
    print(corr.to_string(float_format=lambda x: f"{x:.3f}"))


def recent_trades(trade_log: pd.DataFrame, n: int = 30):
    """Show recent rebalance trades."""
    if trade_log.empty:
        print("\n  No trade log available")
        return

    print(f"\n{'='*72}")
    print(f"  RECENT REBALANCE TRADES (last {n})")
    print("="*72)

    recent = trade_log.tail(n)
    print(f"    {'Date':>12s} {'Asset':>6s} {'Old Wt':>8s} {'New Wt':>8s} {'Delta':>8s} {'Price':>10s}")
    print(f"    {'─'*12} {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*10}")

    for _, row in recent.iterrows():
        action = "▲BUY " if row['delta'] > 0 else "▼SELL"
        print(f"    {row['date'].strftime('%Y-%m-%d'):>12s} {row['asset']:>6s} "
              f"{row['old_wt']*100:>7.1f}% {row['new_wt']*100:>7.1f}% "
              f"{action} {abs(row['delta'])*100:>4.1f}% "
              f"${row['price']:>9.2f}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    print("=" * 72)
    print("  RISK PARITY + TREND — DEFINITIVE BACKTEST")
    print("  Universe: SPY / TLT / GLD / VNQ")
    print("  Monthly rebalance | SMA200 trend filter | Inverse-vol sizing")
    print("=" * 72)

    data = pd.read_parquet(CACHE)
    assets = ['SPY', 'TLT', 'GLD', 'VNQ']
    avail = [a for a in assets if a in data.columns]
    print(f"\n  Data: {len(data):,} days, {data.index[0].date()} → {data.index[-1].date()}")
    print(f"  Assets: {avail}")

    # ── Full backtest ──
    print(f"\n{'='*72}")
    print("  FULL BACKTEST (22 years)")
    print("="*72)

    res = run_rp_trend(data, avail, sma_len=200, use_trend=True)
    print_stats("Risk Parity + Trend", res['equity'], res['returns'], res['n_rebal'])
    print(f"    Total cost: {res['total_cost']*100:.2f}%")

    yearly_breakdown(res['returns'], "Risk Parity + Trend")
    drawdown_analysis(res['equity'])

    # ── Walk-forward OOS ──
    walk_forward_oos(data, avail)

    # ── Comparison ──
    compare_strategies(data)

    # ── Current signal ──
    current_signal(data, avail)

    # ── Recent trades ──
    recent_trades(res['trade_log'], n=30)

    # ── Parameter sensitivity ──
    print(f"\n{'='*72}")
    print("  PARAMETER SENSITIVITY")
    print("="*72)
    print(f"    {'SMA':>5s} {'VolWin':>7s} {'CAGR':>7s} {'Sharpe':>8s} {'MaxDD':>8s} {'Calmar':>8s}")
    print(f"    {'─'*5} {'─'*7} {'─'*7} {'─'*8} {'─'*8} {'─'*8}")

    for sma_len in [100, 150, 200, 250, 300]:
        for vol_win in [40, 60, 90]:
            r = run_rp_trend(data, avail, sma_len=sma_len, vol_window=vol_win)
            c = cagr(r['equity']) * 100
            s = sharpe(r['returns'])
            d = max_dd(r['equity']) * 100
            cal = calmar(r['equity'])
            marker = " ◄" if sma_len == 200 and vol_win == 60 else ""
            print(f"    {sma_len:>5d} {vol_win:>7d} {c:>+6.1f}% {s:>+7.3f} {d:>7.1f}% {cal:>7.3f}{marker}")

    print(f"\n  Total runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
