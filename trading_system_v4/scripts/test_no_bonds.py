"""
test_no_bonds.py — What survives without the bond bull market?

TLT returned +3.5% CAGR over 2003-2026 but most of that was 2003-2020
(falling rates). With rates structurally higher, TLT may be dead weight.

Tests:
1. RP+Trend without TLT (SPY/GLD/VNQ only)
2. RP+Trend without any bonds (no TLT, no IEF)
3. Replace TLT with short-term bonds (IEF proxy)
4. Replace TLT with commodities (DBC)
5. Expanded universe without bonds
6. Rising-rate regime analysis (2022-2026)
7. What if bonds just go sideways (flat TLT scenario)?
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
CACHE = DATA_DIR / "multi_asset_daily.parquet"
ANN = 252
COST_RT = 0.0003


def sharpe(r):
    return r.mean() / (r.std() + 1e-10) * np.sqrt(ANN)

def cagr(eq):
    n = len(eq) / ANN
    return (eq.iloc[-1] / eq.iloc[0]) ** (1/n) - 1 if n > 0 and eq.iloc[0] > 0 else 0

def max_dd(eq):
    return ((eq - eq.cummax()) / eq.cummax()).min()

def sortino(r):
    down = r[r < 0].std()
    return r.mean() / (down + 1e-10) * np.sqrt(ANN)


def run_rp_trend(prices, assets, sma_len=200, use_trend=True):
    """Run RP+Trend, return (returns, equity, weights)."""
    avail = [a for a in assets if a in prices.columns]
    if len(avail) < 2:
        return None, None, None
    p = prices[avail].ffill().dropna()
    rets = p.pct_change()
    vol = rets.rolling(60).std()
    sma = p.rolling(sma_len).mean()

    weights_df = pd.DataFrame(0.0, index=p.index, columns=avail)
    current_w = pd.Series(0.0, index=avail)

    for i in range(sma_len, len(p)):
        dt = p.index[i]
        is_month = (i == sma_len) or (dt.month != p.index[i-1].month)
        if is_month:
            new_w = pd.Series(0.0, index=avail)
            for a in avail:
                v = vol[a].iloc[i]
                if np.isnan(v) or v <= 0:
                    v = 0.01
                if use_trend and p[a].iloc[i] < sma[a].iloc[i]:
                    new_w[a] = 0.0
                else:
                    new_w[a] = 1.0 / v
            total = new_w.sum()
            if total > 0:
                new_w /= total
            current_w = new_w
        weights_df.iloc[i] = current_w

    strat_ret = (weights_df.shift(1) * rets).sum(axis=1)
    turnover = weights_df.diff().abs().sum(axis=1)
    costs = turnover * COST_RT
    valid = (strat_ret - costs).iloc[sma_len:]
    eq = (1 + valid).cumprod()
    return valid, eq, weights_df.iloc[sma_len:]


def print_comparison(configs, title):
    """Print a comparison table."""
    print(f"\n  {title}")
    print(f"  {'─'*70}")
    print(f"    {'Strategy':<40s} {'CAGR':>7s} {'Sharpe':>8s} {'Sortino':>9s} {'MaxDD':>8s}")
    print(f"    {'─'*40} {'─'*7} {'─'*8} {'─'*9} {'─'*8}")
    for label, eq, r in configs:
        if r is None:
            print(f"    {label:<40s}  N/A")
            continue
        c = cagr(eq) * 100
        s = sharpe(r)
        so = sortino(r)
        d = max_dd(eq) * 100
        print(f"    {label:<40s} {c:>+6.1f}% {s:>+7.3f} {so:>+8.3f} {d:>7.1f}%")


def yearly_table(configs, start_year=2005):
    """Print yearly returns for multiple strategies side by side."""
    labels = [c[0][:20] for c in configs]
    header = f"    {'Year':>6s}"
    for lbl in labels:
        header += f" {lbl:>20s}"
    print(f"\n{header}")
    print(f"    {'─'*6}" + "".join(f" {'─'*20}" for _ in labels))

    all_years = set()
    for _, _, r in configs:
        if r is not None:
            all_years.update(r.index.year.unique())

    for yr in sorted(all_years):
        if yr < start_year:
            continue
        row = f"    {yr:>6d}"
        for _, _, r in configs:
            if r is None:
                row += f" {'N/A':>20s}"
                continue
            mask = r.index.year == yr
            if mask.sum() < 20:
                row += f" {'—':>20s}"
                continue
            yr_ret = (1 + r[mask]).prod() - 1
            row += f" {yr_ret*100:>+19.1f}%"
        print(row)


def main():
    data = pd.read_parquet(CACHE)

    print("=" * 72)
    print("  WHAT SURVIVES WITHOUT THE BOND BULL MARKET?")
    print("=" * 72)

    # ── First: how bad was TLT actually? ──
    print("\n  TLT PERFORMANCE BY ERA:")
    print("  " + "─" * 60)
    tlt = data['TLT'].ffill().dropna()
    tlt_ret = tlt.pct_change()

    eras = [
        ("2003-2012 (falling rates)", 2003, 2012),
        ("2013-2019 (low rates)", 2013, 2019),
        ("2020 (COVID flight to safety)", 2020, 2020),
        ("2021-2023 (rate hikes)", 2021, 2023),
        ("2024-2026 (higher for longer)", 2024, 2026),
        ("Full period", 2003, 2026),
    ]

    for label, y1, y2 in eras:
        mask = (tlt_ret.index.year >= y1) & (tlt_ret.index.year <= y2)
        if mask.sum() < 50:
            continue
        r = tlt_ret[mask]
        eq = (1 + r).cumprod()
        n = mask.sum() / ANN
        c = (eq.iloc[-1] ** (1/n) - 1) * 100
        d = max_dd(eq) * 100
        print(f"    {label:<40s} CAGR={c:>+6.1f}%  DD={d:>6.1f}%")

    # ── Test different universes ──
    print(f"\n{'='*72}")
    print("  UNIVERSE COMPARISON — FULL PERIOD")
    print("="*72)

    universes = [
        ("Baseline: SPY/TLT/GLD/VNQ", ['SPY', 'TLT', 'GLD', 'VNQ']),
        ("No TLT: SPY/GLD/VNQ", ['SPY', 'GLD', 'VNQ']),
        ("No bonds: SPY/GLD/VNQ/DBC", ['SPY', 'GLD', 'VNQ', 'DBC']),
        ("Replace TLT→IEF: SPY/IEF/GLD/VNQ", ['SPY', 'IEF', 'GLD', 'VNQ']),
        ("No stocks: TLT/GLD", ['TLT', 'GLD']),
        ("No stocks, no bonds: GLD/VNQ", ['GLD', 'VNQ']),
        ("GLD only (trend filter)", ['GLD']),
        ("Broad: SPY/TLT/GLD/VNQ/DBC/EFA", ['SPY', 'TLT', 'GLD', 'VNQ', 'DBC', 'EFA']),
        ("Broad no bonds: SPY/GLD/VNQ/DBC/EFA", ['SPY', 'GLD', 'VNQ', 'DBC', 'EFA']),
        ("Max div: SPY/GLD/VNQ/DBC/EFA/EEM", ['SPY', 'GLD', 'VNQ', 'DBC', 'EFA', 'EEM']),
    ]

    results_full = []
    for label, assets in universes:
        r, eq, w = run_rp_trend(data, assets, sma_len=200, use_trend=True)
        results_full.append((label, eq, r))

    # Add SPY B&H
    spy = data['SPY'].ffill().dropna().pct_change().iloc[200:]
    spy_eq = (1 + spy).cumprod()
    results_full.append(("SPY Buy & Hold", spy_eq, spy))

    print_comparison(results_full, "FULL PERIOD (all available data)")

    # ── Now the critical test: RISING RATE ERA ONLY (2022-2026) ──
    print(f"\n{'='*72}")
    print("  RISING RATE ERA ONLY (2022-2026)")
    print("="*72)

    rate_era_start = "2022-01-01"
    rate_data = data[data.index >= rate_era_start]

    results_rate = []
    for label, assets in universes:
        r, eq, w = run_rp_trend(rate_data, assets, sma_len=200, use_trend=True)
        results_rate.append((label, eq, r))

    spy_rate = rate_data['SPY'].ffill().dropna().pct_change().iloc[200:]
    spy_rate_eq = (1 + spy_rate).cumprod()
    results_rate.append(("SPY Buy & Hold", spy_rate_eq, spy_rate))

    print_comparison(results_rate, "2022-2026 (rising rates, no bond tailwind)")

    # ── Yearly breakdown of key strategies ──
    print(f"\n{'='*72}")
    print("  YEARLY RETURNS — KEY STRATEGIES")
    print("="*72)

    key_configs = []
    for label, assets in [
        ("SPY/TLT/GLD/VNQ", ['SPY', 'TLT', 'GLD', 'VNQ']),
        ("SPY/GLD/VNQ", ['SPY', 'GLD', 'VNQ']),
        ("SPY/GLD/VNQ/DBC/EFA", ['SPY', 'GLD', 'VNQ', 'DBC', 'EFA']),
    ]:
        r, eq, w = run_rp_trend(data, assets, sma_len=200, use_trend=True)
        key_configs.append((label, eq, r))

    key_configs.append(("SPY B&H", spy_eq, spy))
    yearly_table(key_configs)

    # ── Correlation matrix ──
    print(f"\n{'='*72}")
    print("  ASSET CORRELATION MATRIX (daily returns, full period)")
    print("="*72)

    corr_assets = ['SPY', 'TLT', 'GLD', 'VNQ', 'DBC', 'EFA', 'EEM', 'IEF']
    avail = [a for a in corr_assets if a in data.columns]
    r_all = data[avail].ffill().pct_change().dropna()
    corr = r_all.corr()

    print(f"\n    {'':>6s}", end="")
    for a in avail:
        print(f" {a:>6s}", end="")
    print()
    for a in avail:
        print(f"    {a:>6s}", end="")
        for b in avail:
            v = corr.loc[a, b]
            marker = "█" if abs(v) > 0.5 else "▓" if abs(v) > 0.3 else " "
            print(f" {v:>+5.2f}{marker}", end="")
        print()

    # ── What about GLD dependency? ──
    print(f"\n{'='*72}")
    print("  GLD DEPENDENCY CHECK")
    print("="*72)

    gld = data['GLD'].ffill().dropna()
    gld_ret = gld.pct_change()

    print("\n  GLD performance by era:")
    for label, y1, y2 in eras:
        mask = (gld_ret.index.year >= y1) & (gld_ret.index.year <= y2)
        if mask.sum() < 50:
            continue
        r = gld_ret[mask]
        eq = (1 + r).cumprod()
        n = mask.sum() / ANN
        c = (eq.iloc[-1] ** (1/n) - 1) * 100
        print(f"    {label:<40s} CAGR={c:>+6.1f}%")

    # Without GLD
    print("\n  Strategies WITHOUT GLD:")
    no_gld = [
        ("SPY/TLT/VNQ (no GLD)", ['SPY', 'TLT', 'VNQ']),
        ("SPY/VNQ (no GLD, no TLT)", ['SPY', 'VNQ']),
        ("SPY/TLT/VNQ/DBC (no GLD)", ['SPY', 'TLT', 'VNQ', 'DBC']),
        ("SPY/VNQ/DBC/EFA (no GLD no TLT)", ['SPY', 'VNQ', 'DBC', 'EFA']),
    ]

    no_gld_results = []
    for label, assets in no_gld:
        r, eq, w = run_rp_trend(data, assets, sma_len=200, use_trend=True)
        no_gld_results.append((label, eq, r))

    no_gld_results.append(("SPY Buy & Hold", spy_eq, spy))
    print_comparison(no_gld_results, "WITHOUT GLD")

    # ── Verdict ──
    print(f"\n{'='*72}")
    print("  VERDICT: WHAT SURVIVES?")
    print("="*72)

    # Compute key numbers
    r_base, eq_base, _ = run_rp_trend(data, ['SPY', 'TLT', 'GLD', 'VNQ'])
    r_notlt, eq_notlt, _ = run_rp_trend(data, ['SPY', 'GLD', 'VNQ'])
    r_nogld, eq_nogld, _ = run_rp_trend(data, ['SPY', 'TLT', 'VNQ'])
    r_noeith, eq_noeith, _ = run_rp_trend(data, ['SPY', 'VNQ'])
    r_broad, eq_broad, _ = run_rp_trend(data, ['SPY', 'GLD', 'VNQ', 'DBC', 'EFA'])

    print(f"""
    Remove TLT (bond bull):
      Baseline (with TLT):   CAGR {cagr(eq_base)*100:+.1f}%, Sharpe {sharpe(r_base):.3f}, DD {max_dd(eq_base)*100:.1f}%
      Without TLT:           CAGR {cagr(eq_notlt)*100:+.1f}%, Sharpe {sharpe(r_notlt):.3f}, DD {max_dd(eq_notlt)*100:.1f}%
      → TLT removal cost:    {(cagr(eq_base)-cagr(eq_notlt))*100:+.1f}% CAGR, {sharpe(r_base)-sharpe(r_notlt):+.3f} Sharpe

    Remove GLD (gold bull):
      Without GLD:           CAGR {cagr(eq_nogld)*100:+.1f}%, Sharpe {sharpe(r_nogld):.3f}, DD {max_dd(eq_nogld)*100:.1f}%
      → GLD removal cost:    {(cagr(eq_base)-cagr(eq_nogld))*100:+.1f}% CAGR, {sharpe(r_base)-sharpe(r_nogld):+.3f} Sharpe

    Remove BOTH TLT and GLD:
      SPY/VNQ only:          CAGR {cagr(eq_noeith)*100:+.1f}%, Sharpe {sharpe(r_noeith):.3f}, DD {max_dd(eq_noeith)*100:.1f}%

    Replace TLT with intl diversification:
      SPY/GLD/VNQ/DBC/EFA:   CAGR {cagr(eq_broad)*100:+.1f}%, Sharpe {sharpe(r_broad):.3f}, DD {max_dd(eq_broad)*100:.1f}%

    SPY Buy & Hold:          CAGR {cagr(spy_eq)*100:+.1f}%, Sharpe {sharpe(spy):.3f}, DD {max_dd(spy_eq)*100:.1f}%
    """)


if __name__ == "__main__":
    main()
