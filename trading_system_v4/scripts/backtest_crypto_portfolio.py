"""
Multi-Crypto Portfolio Backtest
================================
Same 40d/70th percentile signal on each coin independently.
Capital allocated equally across coins, each coin vol-targeted separately.

Tests:
  1. Each coin standalone (recap)
  2. Equal-weight portfolio: all 5 coins
  3. Top 3 combos: BTC+ETH, BTC+SOL, BTC+ETH+SOL
  4. Weighted combos (risk-parity)
  5. Year-by-year breakdown
  6. Correlation of signals (how often are they in/out at the same time?)
  7. Current signal state for all coins
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


LOOKBACK     = 40
ENTRY_PCT    = 70
COST_BPS     = 20
VOL_TARGET   = 0.40
VOL_LOOKBACK = 20


def load_data():
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    # Rename columns to drop -USD suffix
    closes.columns = [c.replace("-USD", "") for c in closes.columns]
    return closes


def percentile_signal(price, lookback=LOOKBACK, pct=ENTRY_PCT):
    lvl = price.rolling(lookback).quantile(pct / 100)
    return (price > lvl).astype(float), lvl


def bt_single(price, signal, cost_bps=COST_BPS, vol_target=VOL_TARGET):
    """Backtest a single asset. Returns daily net return series and stats."""
    ret = price.pct_change()
    vol = ret.rolling(VOL_LOOKBACK).std() * np.sqrt(365)

    pos = (signal * vol_target / vol.clip(lower=0.01)).clip(0, 1.0)
    pos_d = pos.shift(1)

    pnl   = pos_d * ret
    costs = pos_d.diff().abs() * (cost_bps / 10000)
    net   = (pnl - costs).fillna(0)

    first = signal[signal > 0].index
    if len(first) == 0:
        return pd.Series(0.0, index=price.index), {}
    net = net[first[0]:]
    sig_t = signal[first[0]:]

    if len(net) < 200:
        return net, {}

    equity  = (1 + net).cumprod()
    n_yr    = len(net) / 365
    total   = equity.iloc[-1] - 1
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if total > -1 else -1.0
    ann_vol = net.std() * np.sqrt(365)
    sr      = ann_ret / ann_vol if ann_vol > 0 else 0
    dd      = (equity / equity.cummax() - 1).min()
    yearly  = net.resample("YE").sum()

    return net, {
        "sr": sr, "ret": ann_ret, "dd": dd,
        "time_in": (sig_t > 0).mean(),
        "yearly": yearly,
        "equity": equity,
    }


def portfolio_bt(coin_rets: dict, weights: dict, start=None):
    """
    Combine per-coin daily net return series into a portfolio.
    weights: {coin: fraction_of_capital}  (should sum to 1.0)
    Each coin's return already reflects its own vol-targeting.
    Portfolio return = weighted average of coin returns.
    """
    # Align all series
    df = pd.DataFrame(coin_rets).fillna(0)
    if start:
        df = df[start:]

    port_ret = sum(df[c] * w for c, w in weights.items() if c in df.columns)
    port_ret = port_ret.fillna(0)

    if len(port_ret) < 200:
        return {}

    equity  = (1 + port_ret).cumprod()
    n_yr    = len(port_ret) / 365
    total   = equity.iloc[-1] - 1
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if total > -1 else -1.0
    ann_vol = port_ret.std() * np.sqrt(365)
    sr      = ann_ret / ann_vol if ann_vol > 0 else 0
    dd      = (equity / equity.cummax() - 1).min()
    yearly  = port_ret.resample("YE").sum()
    mwr     = (port_ret.resample("ME").sum() > 0).mean()

    return {
        "sr": sr, "ret": ann_ret, "dd": dd,
        "yearly": yearly, "equity": equity,
        "monthly_wr": mwr, "n_yr": n_yr,
    }


def get_yr(yearly, yr):
    matches = [v for d, v in yearly.items() if d.year == yr]
    return matches[0] if matches else np.nan


def main():
    print("=" * 72)
    print("  MULTI-CRYPTO PORTFOLIO BACKTEST")
    print("  Signal: 40d/70th percentile on each coin independently")
    print("=" * 72)

    closes = load_data()
    coins  = ["BTC", "ETH", "SOL", "LINK", "LTC"]

    # ── Per-coin signals and returns ──────────────────────────────────────────
    coin_rets  = {}
    coin_sigs  = {}
    coin_stats = {}
    coin_lvls  = {}

    for coin in coins:
        if coin not in closes.columns:
            continue
        price = closes[coin].dropna()
        if len(price) < 300:
            continue
        sig, lvl = percentile_signal(price)
        net, stats = bt_single(price, sig)
        if stats:
            coin_rets[coin]  = net
            coin_sigs[coin]  = sig
            coin_stats[coin] = stats
            coin_lvls[coin]  = lvl

    available = list(coin_rets.keys())

    # ── 1. Individual coin recap ───────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  1. INDIVIDUAL COINS (standalone, 100% capital each)")
    print("─" * 72)
    print(f"\n  {'Coin':>5s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'TimeIn':>7s}  {'History':>10s}")
    print(f"  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*10}")

    for coin in available:
        s = coin_stats[coin]
        eq = s["equity"]
        start = str(eq.index[0].date())
        end   = str(eq.index[-1].date())
        print(f"  {coin:>5s}  {s['sr']:>+5.2f}  {s['ret']:>+7.1%}  "
              f"{s['dd']:>+7.1%}  {s['time_in']:>6.0%}  {start} - {end[:7]}")

    # ── 2. Signal correlation ─────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  2. SIGNAL CORRELATION (how often are coins in/out together?)")
    print("─" * 72)

    sig_df = pd.DataFrame({c: coin_sigs[c] for c in available}).dropna()
    corr   = sig_df.corr()

    print(f"\n  {'':>6s}", end="")
    for c in available:
        print(f"  {c:>6s}", end="")
    print()
    print(f"  {'─'*6}", end="")
    for _ in available:
        print(f"  {'─'*6}", end="")
    print()
    for c1 in available:
        print(f"  {c1:>6s}", end="")
        for c2 in available:
            v = corr.loc[c1, c2]
            print(f"  {v:>+5.2f}", end="")
        print()

    # Pct of days all coins in same state
    all_long = (sig_df > 0).all(axis=1).mean()
    all_flat = (sig_df == 0).all(axis=1).mean()
    mixed    = 1 - all_long - all_flat
    print(f"\n  All coins LONG together: {all_long:.0%} of days")
    print(f"  All coins FLAT together: {all_flat:.0%} of days")
    print(f"  Mixed (different states): {mixed:.0%} of days")

    # ── 3. Portfolio combinations ─────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  3. PORTFOLIO COMBINATIONS (equal weight per coin)")
    print("─" * 72)

    combos = []
    # Two-coin
    for i, c1 in enumerate(available):
        for c2 in available[i+1:]:
            combos.append(([c1, c2], "equal"))
    # Three-coin
    for i, c1 in enumerate(available):
        for j, c2 in enumerate(available[i+1:], i+1):
            for c3 in available[j+1:]:
                combos.append(([c1, c2, c3], "equal"))
    # Four/five coin
    if len(available) >= 4:
        combos.append((available[:4], "equal"))
    if len(available) >= 5:
        combos.append((available[:5], "equal"))

    # Also add baseline BTC-only
    combos_with_base = [([c], "equal") for c in available] + combos

    # Find common start date
    common_start = max(coin_stats[c]["equity"].index[0] for c in available)

    print(f"\n  (Portfolio period starts {common_start.date()} for fair comparison)")
    print(f"\n  {'Portfolio':>28s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'MonWR':>6s}  {'OOS_SR':>7s}")
    print(f"  {'─'*28}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*7}")

    best_sr  = -99
    best_combo_coins = []
    best_combo_r     = {}

    all_combo_results = []

    for coin_list, wtype in combos_with_base:
        n = len(coin_list)
        w = {c: 1.0 / n for c in coin_list}
        r = portfolio_bt(coin_rets, w, start=str(common_start.date()))
        if not r:
            continue

        # OOS
        oos_start = "2022"
        r_oos = portfolio_bt(
            {c: coin_rets[c] for c in coin_list},
            w, start=oos_start
        )

        label = "+".join(coin_list)
        solo  = " *" if len(coin_list) == 1 else "  "
        print(f"  {label:>28s}{solo}  {r['sr']:>+5.2f}  {r['ret']:>+7.1%}  "
              f"{r['dd']:>+7.1%}  {r.get('monthly_wr', 0):>5.0%}  "
              f"{r_oos.get('sr', float('nan')):>+6.2f}")

        all_combo_results.append((label, coin_list, w, r, r_oos))

        if r["sr"] > best_sr and len(coin_list) > 1:
            best_sr          = r["sr"]
            best_combo_coins = coin_list
            best_combo_r     = r

    # ── 4. Year-by-year for key combos ───────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  4. YEAR-BY-YEAR (BTC only vs BTC+ETH vs BTC+ETH+SOL vs All 5)")
    print("─" * 72)

    key_combos = {
        "BTC only":      (["BTC"], {c: 1.0 for c in ["BTC"]}),
        "BTC+ETH":       (["BTC", "ETH"], {c: 0.5 for c in ["BTC", "ETH"]}),
        "BTC+ETH+SOL":   (["BTC", "ETH", "SOL"], {c: 1/3 for c in ["BTC", "ETH", "SOL"]}),
        "All 5 coins":   (available, {c: 1/len(available) for c in available}),
    }

    years = list(range(common_start.year, 2026))
    header = f"  {'Year':>5s}" + "".join(f"  {k:>13s}" for k in key_combos)
    print(header)
    print("  " + "─" * (7 + 15 * len(key_combos)))

    for yr in years:
        row = f"  {yr:>5d}"
        for label, (cl, w) in key_combos.items():
            r = portfolio_bt({c: coin_rets[c] for c in cl if c in coin_rets}, w)
            if not r:
                row += f"  {'--':>13s}"
                continue
            v = get_yr(r["yearly"], yr)
            if np.isnan(v):
                row += f"  {'--':>13s}"
            else:
                row += f"  {v:>+12.1%}"
        print(row)

    # ── 5. Risk-parity weighting (inverse vol) ────────────────────────────────
    print(f"\n{'─'*72}")
    print("  5. RISK-PARITY: Weight each coin by inverse of its volatility")
    print("─" * 72)
    print("     (coins with lower vol get larger allocation)")

    # Compute each coin's realized vol over common period
    vols = {}
    for coin in available:
        price = closes[coin].dropna()[str(common_start.date()):]
        rv = price.pct_change().std() * np.sqrt(365)
        vols[coin] = rv

    inv_vols = {c: 1.0 / v for c, v in vols.items()}
    total_inv = sum(inv_vols.values())
    rp_weights = {c: v / total_inv for c, v in inv_vols.items()}

    print(f"\n  Risk-parity weights:")
    for coin, w in rp_weights.items():
        print(f"    {coin:>6s}:  {w:.0%}  (vol={vols[coin]:.0%})")

    r_rp    = portfolio_bt(coin_rets, rp_weights, start=str(common_start.date()))
    r_rp_oos = portfolio_bt(coin_rets, rp_weights, start="2022")

    if r_rp:
        print(f"\n  {'Portfolio':>20s}  SR={r_rp['sr']:+.2f}  "
              f"Ret={r_rp['ret']:+.1%}  DD={r_rp['dd']:.1%}  "
              f"OOS_SR={r_rp_oos.get('sr', float('nan')):+.2f}")

    # ── 6. Current signal state for all coins ─────────────────────────────────
    print(f"\n{'─'*72}")
    print("  6. CURRENT SIGNAL STATE — ALL COINS")
    print("─" * 72)

    import yfinance as yf
    print(f"\n  Fetching live prices...")

    tickers = [f"{c}-USD" for c in available]
    live = yf.download(tickers, period="60d", interval="1d",
                       progress=False)["Close"]
    if hasattr(live, "columns"):
        live.columns = [c.replace("-USD", "") for c in live.columns]

    print(f"\n  {'Coin':>6s}  {'Price':>10s}  {'Entry Level':>12s}  "
          f"{'Gap':>10s}  {'Signal':>6s}  {'Vol':>6s}  {'Deploy':>7s}")
    print(f"  {'─'*6}  {'─'*10}  {'─'*12}  {'─'*10}  {'─'*6}  {'─'*6}  {'─'*7}")

    for coin in available:
        col = coin if coin in live.columns else f"{coin}-USD"
        if col not in live.columns:
            continue
        series = live[col].dropna()
        if len(series) < 41:
            continue

        current = float(series.iloc[-1])
        last40  = series.iloc[-40:]
        lvl     = float(last40.quantile(ENTRY_PCT / 100))
        sig     = "LONG" if current > lvl else "FLAT"
        gap_pct = (current - lvl) / lvl

        # Vol-target weight
        rv      = float(series.pct_change().rolling(20).std().iloc[-1]) * np.sqrt(365)
        weight  = min(VOL_TARGET / rv, 1.0) if rv > 0.01 else 0.0
        deploy  = weight if sig == "LONG" else 0.0

        gap_str = f"{gap_pct:+.1%}"
        print(f"  {coin:>6s}  ${current:>9,.1f}  ${lvl:>11,.1f}  "
              f"{gap_str:>10s}  {sig:>6s}  {rv:>5.0%}  {deploy:>6.0%}")

    # ── 7. Portfolio signal summary ───────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  7. PORTFOLIO SUGGESTION (if trading BTC+ETH+SOL equally)")
    print("─" * 72)

    portfolio_coins = ["BTC", "ETH", "SOL"]
    total_deploy = 0.0
    print(f"\n  With $10,000 capital split equally ($3,333 per coin):")
    for coin in portfolio_coins:
        col = coin if coin in live.columns else f"{coin}-USD"
        if col not in live.columns:
            continue
        series = live[col].dropna()
        current = float(series.iloc[-1])
        last40  = series.iloc[-40:]
        lvl     = float(last40.quantile(ENTRY_PCT / 100))
        sig     = "LONG" if current > lvl else "FLAT"
        rv      = float(series.pct_change().rolling(20).std().iloc[-1]) * np.sqrt(365)
        weight  = min(VOL_TARGET / rv, 1.0) if rv > 0.01 else 0.0
        alloc   = 10_000 / 3
        dollars = alloc * weight if sig == "LONG" else 0.0
        units   = dollars / current if current > 0 else 0.0
        print(f"  {coin:>4s}:  {sig:>4s}  → deploy ${dollars:>6,.0f}  "
              f"({units:.6f} {coin})")
        total_deploy += dollars

    print(f"\n  Total deployed: ${total_deploy:,.0f} of $10,000 ({total_deploy/10000:.0%})")
    print(f"  Cash remaining: ${10000-total_deploy:,.0f}")


if __name__ == "__main__":
    main()
