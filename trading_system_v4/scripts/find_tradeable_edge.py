"""
find_tradeable_edge.py — Multi-Asset Strategy Scanner
======================================================
Stop trying ML on single assets. Test PORTFOLIO strategies with academic backing.

Strategies tested:
  1. Dual Momentum (Antonacci) — absolute + relative momentum on SPY/EFA/AGG
  2. Multi-Asset Trend Following (CTA-style) — 10+ asset classes, time-series momentum
  3. SPY Mean Reversion (RSI-2) — buy oversold, sell overbought
  4. Cross-Sectional Momentum Rotation — rank ETFs, hold top N
  5. Risk Parity + Trend Overlay
  6. Crypto Momentum (BTC/ETH/SOL rotation)

All use daily bars from yfinance. Costs are realistic IBKR ETF commissions.
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
CACHE = DATA_DIR / "multi_asset_daily.parquet"

# ── Cost assumptions ──────────────────────────────────────────────────────────
# IBKR: $0.005/share ETF, ~$1 per trade for $10k position
# We model as 0.01% per trade (round-trip 0.02%) for ETFs — conservative
ETF_COST_RT   = 0.0002   # 0.02% round-trip for ETFs on IBKR
CRYPTO_COST_RT = 0.0065  # 0.65% round-trip for crypto (Coinbase)
ANN_FACTOR = 252

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sharpe(r, af=ANN_FACTOR):
    if r.std() == 0: return 0
    return r.mean() / (r.std() + 1e-10) * np.sqrt(af)

def _max_dd(eq):
    rm = eq.cummax()
    dd = (eq - rm) / rm
    return dd.min()

def _cagr(eq):
    n_years = len(eq) / ANN_FACTOR
    if n_years <= 0 or eq.iloc[0] <= 0: return 0
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / n_years) - 1

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _rsi(s, period=2):
    d = s.diff()
    g = d.clip(lower=0).rolling(period).mean()
    lo = (-d).clip(lower=0).rolling(period).mean()
    return 100 - 100 / (1 + g / (lo + 1e-10))

def _print_strat_header(name):
    print(f"\n{'='*72}")
    print(f"  STRATEGY: {name}")
    print(f"{'='*72}")

def _print_yearly(daily_ret, label=""):
    if label:
        print(f"\n  {label}")
    groups = daily_ret.groupby(daily_ret.index.year)
    rows = []
    for yr, grp in groups:
        ret = (1+grp).prod()-1
        sh = grp.mean()/(grp.std()+1e-10)*np.sqrt(ANN_FACTOR)
        rows.append({'year': yr, 'ret': ret, 'sharpe': sh})
    yearly = pd.DataFrame(rows).set_index('year')
    wins = (yearly['ret'] > 0).sum()
    total = len(yearly)
    print(f"  {'Year':>6} {'Return':>9} {'Sharpe':>8}")
    print(f"  {'─'*6} {'─'*9} {'─'*8}")
    for yr, row in yearly.iterrows():
        print(f"  {yr:>6} {row['ret']*100:>+8.1f}% {row['sharpe']:>+7.2f}")
    print(f"  {'─'*25}")
    print(f"  Win years: {wins}/{total} ({wins/total*100:.0f}%)")
    return yearly

def _summarize(daily_ret, name, cost_rt=ETF_COST_RT):
    eq = (1 + daily_ret).cumprod()
    sh = _sharpe(daily_ret)
    dd = _max_dd(eq) * 100
    cagr = _cagr(eq) * 100
    calmar = cagr / abs(dd) if dd != 0 else 0
    print(f"\n  Summary:")
    print(f"    CAGR:       {cagr:+.1f}%")
    print(f"    Sharpe:     {sh:+.3f}")
    print(f"    Max DD:     {dd:.1f}%")
    print(f"    Calmar:     {calmar:.2f}")
    return {'name': name, 'cagr': cagr, 'sharpe': sh, 'max_dd': dd, 'calmar': calmar}


# ══════════════════════════════════════════════════════════════════════════════
#  DATA DOWNLOAD
# ══════════════════════════════════════════════════════════════════════════════

def download_data():
    """Download all assets needed for every strategy."""
    tickers = {
        # US Equity
        'SPY': 'S&P 500',
        'QQQ': 'Nasdaq 100',
        'IWM': 'Russell 2000',
        'MDY': 'S&P 400 Mid-Cap',
        # International equity
        'EFA': 'EAFE (Intl Dev)',
        'EEM': 'Emerging Markets',
        # Fixed income
        'TLT': 'Long-Term Treasury',
        'IEF': 'Intermediate Treasury',
        'AGG': 'US Agg Bond',
        'HYG': 'High Yield Corp',
        # Commodities
        'GLD': 'Gold',
        'SLV': 'Silver',
        'DBC': 'Commodities Broad',
        'USO': 'Crude Oil',
        # Alternatives
        'VNQ': 'REITs',
        'UUP': 'US Dollar',
        # Crypto ETFs (newer, less history)
        'BTC-USD': 'Bitcoin',
        'ETH-USD': 'Ethereum',
        'SOL-USD': 'Solana',
    }

    if CACHE.exists():
        print(f"Loading cached data from {CACHE.name}...")
        df = pd.read_parquet(CACHE)
        # Check if we have all tickers
        missing = [t for t in tickers if t not in df.columns]
        if not missing:
            print(f"  {len(df)} days, {len(df.columns)} assets, "
                  f"{df.index.min().date()} → {df.index.max().date()}")
            return df, tickers
        print(f"  Missing {missing}, re-downloading...")

    print(f"Downloading daily data for {len(tickers)} assets...")
    raw = yf.download(
        list(tickers.keys()),
        start="2003-01-01",
        end="2026-12-31",
        auto_adjust=True,
        progress=False,
    )

    # Extract close prices
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]]

    # Clean up columns
    if hasattr(closes.columns, 'droplevel'):
        try:
            closes.columns = closes.columns.droplevel(0)
        except Exception:
            pass

    # Keep only requested tickers
    available = [t for t in tickers if t in closes.columns]
    closes = closes[available]
    closes = closes.ffill()

    print(f"  Downloaded {len(closes)} daily bars for {len(available)} assets")
    for t in tickers:
        if t in closes.columns:
            valid = closes[t].dropna()
            if len(valid) > 0:
                print(f"    {t:>8s} ({tickers[t]:>20s}): {len(valid):>5,} bars  "
                      f"{valid.index.min().date()} → {valid.index.max().date()}")

    closes.to_parquet(CACHE)
    return closes, tickers


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 1: DUAL MOMENTUM (Antonacci)
# ══════════════════════════════════════════════════════════════════════════════

def strategy_dual_momentum(data):
    """
    Gary Antonacci's Dual Momentum:
    - Compare SPY vs EFA on 12-month returns (relative momentum)
    - If winner > T-bills (absolute momentum), hold winner
    - If neither beats T-bills, hold AGG (bonds)
    - Rebalance monthly
    """
    _print_strat_header("DUAL MOMENTUM (Antonacci)")

    required = ['SPY', 'EFA', 'AGG']
    if not all(t in data.columns for t in required):
        print("  Missing required tickers")
        return None

    spy = data['SPY'].dropna()
    efa = data['EFA'].dropna()
    agg = data['AGG'].dropna()

    # Align dates
    common = spy.index.intersection(efa.index).intersection(agg.index)
    spy = spy.loc[common]; efa = efa.loc[common]; agg = agg.loc[common]

    print(f"  Period: {common[0].date()} → {common[-1].date()} ({len(common)} days)")

    # Monthly rebalance
    monthly_idx = spy.resample('ME').last().index

    # 12-month lookback
    lookback = 252

    position = pd.Series(0.0, index=common)  # 0=cash/bonds, 1=SPY, 2=EFA
    current_asset = 'AGG'
    daily_ret = pd.Series(0.0, index=common)

    assets = {'SPY': spy, 'EFA': efa, 'AGG': agg}
    rets = {k: v.pct_change() for k, v in assets.items()}

    all_ret = pd.DataFrame(rets)

    # T-bill proxy: ~0% in low-rate era, doesn't matter much
    tbill_ann = 0.01  # 1% annual as conservative threshold
    tbill_mo = (1 + tbill_ann) ** (1/12) - 1

    holdings = []
    switches = 0

    for i in range(lookback, len(common)):
        dt = common[i]

        # Check if month-end (rebalance)
        is_month_end = (i == len(common)-1) or (common[i].month != common[i+1].month if i+1 < len(common) else True)

        if is_month_end:
            # 12-month return
            spy_12m = spy.iloc[i] / spy.iloc[max(0, i-lookback)] - 1
            efa_12m = efa.iloc[i] / efa.iloc[max(0, i-lookback)] - 1
            tbill_12m = tbill_ann

            old_asset = current_asset

            # Relative momentum: which equity is stronger?
            if spy_12m > efa_12m:
                equity_pick = 'SPY'
                equity_ret = spy_12m
            else:
                equity_pick = 'EFA'
                equity_ret = efa_12m

            # Absolute momentum: is the winner beating T-bills?
            if equity_ret > tbill_12m:
                current_asset = equity_pick
            else:
                current_asset = 'AGG'

            if current_asset != old_asset:
                switches += 1

        # Daily return from current holding
        daily_ret.iloc[i] = rets[current_asset].iloc[i] if not np.isnan(rets[current_asset].iloc[i]) else 0

    # Apply costs on switches
    # Approximate: each switch costs ETF_COST_RT
    daily_ret_net = daily_ret.copy()
    # Distribute switch costs evenly (conservative)
    n_days = (daily_ret != 0).sum()
    total_cost = switches * ETF_COST_RT
    if n_days > 0:
        daily_cost = total_cost / n_days
        daily_ret_net[daily_ret != 0] -= daily_cost

    daily_ret_net = daily_ret_net.iloc[lookback:]

    print(f"  Switches: {switches} over {len(daily_ret_net)/252:.1f} years")
    print(f"  Total cost impact: {total_cost*100:.3f}%")

    _print_yearly(daily_ret_net)
    result = _summarize(daily_ret_net, "Dual Momentum")

    # Compare to buy & hold SPY
    spy_ret = rets['SPY'].iloc[lookback:].fillna(0)
    spy_eq = (1+spy_ret).cumprod()
    print(f"    vs SPY B&H: CAGR={_cagr(spy_eq)*100:+.1f}%, Sharpe={_sharpe(spy_ret):+.3f}, DD={_max_dd(spy_eq)*100:.1f}%")

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 2: MULTI-ASSET TREND FOLLOWING (CTA-style)
# ══════════════════════════════════════════════════════════════════════════════

def strategy_trend_following(data):
    """
    CTA-style trend following across multiple asset classes.
    - Time-series momentum: go long if price > 10-month SMA, else flat (or short)
    - Equal-risk-weighted across assets
    - Monthly rebalance
    """
    _print_strat_header("MULTI-ASSET TREND FOLLOWING (CTA-style)")

    # Use a diverse set
    assets = ['SPY', 'EFA', 'EEM', 'TLT', 'GLD', 'DBC', 'VNQ', 'IEF']
    available = [a for a in assets if a in data.columns]
    if len(available) < 4:
        print(f"  Only {len(available)} assets available, need 4+")
        return None

    prices = data[available].dropna(how='all')
    prices = prices.ffill().dropna()
    print(f"  Assets: {available}")
    print(f"  Period: {prices.index[0].date()} → {prices.index[-1].date()} ({len(prices)} days)")

    rets = prices.pct_change()

    # Rolling vol for risk-parity weighting (60-day)
    vol = rets.rolling(60).std() * np.sqrt(ANN_FACTOR)

    # 10-month (~200 day) SMA trend signal
    sma_200 = prices.rolling(200).mean()

    # Position: +1 if above SMA, -1 if below (long-short), or 0 (long-only)
    # Test both
    for mode_name, short_allowed in [("Long-Only", False), ("Long-Short", True)]:
        print(f"\n  --- {mode_name} ---")

        daily_strat = pd.Series(0.0, index=prices.index)

        for i in range(200, len(prices)):
            # Trend signals
            signals = {}
            for a in available:
                if np.isnan(prices[a].iloc[i]) or np.isnan(sma_200[a].iloc[i]):
                    continue
                if prices[a].iloc[i] > sma_200[a].iloc[i]:
                    signals[a] = 1.0
                elif short_allowed:
                    signals[a] = -1.0
                else:
                    signals[a] = 0.0

            if not signals:
                continue

            # Equal risk weight (inverse vol)
            weights = {}
            total_inv_vol = 0
            for a, sig in signals.items():
                if sig == 0:
                    continue
                v = vol[a].iloc[i]
                if np.isnan(v) or v <= 0:
                    v = 0.15  # default 15% vol
                inv_v = 1.0 / v
                weights[a] = sig * inv_v
                total_inv_vol += inv_v

            if total_inv_vol == 0:
                continue

            # Normalize to target ~10% total portfolio vol
            scale = 0.10 / (sum(abs(w) for w in weights.values()) * 0.15)  # approximate
            scale = min(scale, 2.0)  # cap leverage at 2x

            day_ret = 0
            for a, w in weights.items():
                r = rets[a].iloc[i]
                if not np.isnan(r):
                    day_ret += w * scale * r

            daily_strat.iloc[i] = day_ret

        # Apply monthly rebalance costs
        valid = daily_strat.iloc[200:]
        valid = valid[valid != 0]
        if len(valid) < 100:
            print(f"    Too few trading days")
            continue

        # Estimate ~12 rebalances/year, each touching ~6 assets
        n_years = len(valid) / ANN_FACTOR
        n_trades = 12 * len(available) * n_years
        total_cost = n_trades * ETF_COST_RT
        daily_cost_adj = total_cost / len(valid)
        valid_net = valid - daily_cost_adj

        _print_yearly(valid_net)
        result = _summarize(valid_net, f"Trend Following ({mode_name})")

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 3: SPY MEAN REVERSION (RSI-2)
# ══════════════════════════════════════════════════════════════════════════════

def strategy_spy_mean_reversion(data):
    """
    Classic RSI(2) mean reversion on SPY:
    - Buy when RSI(2) < 10 (oversold)
    - Sell when RSI(2) > 90 (overbought)
    - Only trade above 200-day SMA (trend filter)
    """
    _print_strat_header("SPY MEAN REVERSION (RSI-2)")

    if 'SPY' not in data.columns:
        print("  Missing SPY")
        return None

    spy = data['SPY'].dropna()
    print(f"  Period: {spy.index[0].date()} → {spy.index[-1].date()} ({len(spy)} days)")

    rsi2 = _rsi(spy, 2)
    sma200 = spy.rolling(200).mean()
    daily_ret = spy.pct_change()

    # Test multiple parameter sets
    params = [
        ("RSI2<10, >90, SMA200 filter", 10, 90, True),
        ("RSI2<5, >95, SMA200 filter", 5, 95, True),
        ("RSI2<10, >90, no filter", 10, 90, False),
        ("RSI2<20, >80, SMA200 filter", 20, 80, True),
        ("RSI2<10, >70, SMA200 filter", 10, 70, True),
    ]

    best_result = None
    best_sharpe = -999

    for pname, buy_thr, sell_thr, use_trend in params:
        pos = pd.Series(0.0, index=spy.index)
        in_trade = False

        for i in range(200, len(spy)):
            if use_trend and spy.iloc[i] < sma200.iloc[i]:
                # Below trend: stay out
                in_trade = False
                pos.iloc[i] = 0
                continue

            if not in_trade and rsi2.iloc[i] < buy_thr:
                in_trade = True
            elif in_trade and rsi2.iloc[i] > sell_thr:
                in_trade = False

            pos.iloc[i] = 1.0 if in_trade else 0.0

        # Compute returns
        strat_ret = pos.shift(1) * daily_ret
        trades = (pos.diff().abs() > 0).sum()
        strat_ret_net = strat_ret.copy()

        # Costs on entry/exit
        trade_costs = pos.diff().abs() * ETF_COST_RT
        strat_ret_net -= trade_costs

        valid = strat_ret_net.iloc[200:]
        eq = (1 + valid).cumprod()
        sh = _sharpe(valid)
        dd = _max_dd(eq) * 100
        cagr = _cagr(eq) * 100
        exposure = (pos.iloc[200:] > 0).mean() * 100

        print(f"\n  {pname}:")
        print(f"    CAGR={cagr:+.1f}%  Sharpe={sh:+.3f}  DD={dd:.1f}%  "
              f"Trades={trades}  Exposure={exposure:.0f}%")

        if sh > best_sharpe:
            best_sharpe = sh
            best_result = {'name': f"SPY RSI-2 ({pname})", 'cagr': cagr,
                          'sharpe': sh, 'max_dd': dd, 'calmar': cagr/abs(dd) if dd!=0 else 0}
            best_valid = valid

    # Print yearly for best
    if best_result and best_valid is not None:
        print(f"\n  Best variant: {best_result['name']}")
        _print_yearly(best_valid)

    # SPY B&H comparison
    spy_bh = daily_ret.iloc[200:]
    spy_eq = (1+spy_bh).cumprod()
    print(f"\n  vs SPY B&H: CAGR={_cagr(spy_eq)*100:+.1f}%, Sharpe={_sharpe(spy_bh):+.3f}, "
          f"DD={_max_dd(spy_eq)*100:.1f}%")

    return best_result


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 4: CROSS-SECTIONAL MOMENTUM ROTATION
# ══════════════════════════════════════════════════════════════════════════════

def strategy_momentum_rotation(data):
    """
    Rank ETFs by 12-1 month momentum (skip last month).
    Hold top N (equal weight). Monthly rebalance.
    """
    _print_strat_header("CROSS-SECTIONAL MOMENTUM ROTATION")

    # Use diverse universe
    universe = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'GLD', 'VNQ', 'DBC']
    available = [a for a in universe if a in data.columns]
    if len(available) < 5:
        print(f"  Only {len(available)} available, need 5+")
        return None

    prices = data[available].dropna(how='all').ffill().dropna()
    print(f"  Universe: {available}")
    print(f"  Period: {prices.index[0].date()} → {prices.index[-1].date()} ({len(prices)} days)")

    rets = prices.pct_change()

    for n_hold, skip_month in [(3, True), (3, False), (4, True), (2, True)]:
        label = f"Top {n_hold}, {'skip-1mo' if skip_month else 'no-skip'}"
        print(f"\n  --- {label} ---")

        daily_strat = pd.Series(0.0, index=prices.index)
        current_holdings = []
        n_rebal = 0

        for i in range(252+21, len(prices)):
            dt = prices.index[i]

            # Monthly rebalance (first trading day of month)
            is_new_month = (i == 252+21) or (dt.month != prices.index[i-1].month)

            if is_new_month:
                # 12-1 momentum: 12-month return minus last month return
                mom = {}
                for a in available:
                    if i-252 < 0:
                        continue
                    ret_12m = prices[a].iloc[i] / prices[a].iloc[i-252] - 1
                    if skip_month:
                        ret_1m = prices[a].iloc[i] / prices[a].iloc[i-21] - 1
                        mom[a] = ret_12m - ret_1m  # skip last month
                    else:
                        mom[a] = ret_12m

                if len(mom) < n_hold:
                    continue

                ranked = sorted(mom.items(), key=lambda x: x[1], reverse=True)
                current_holdings = [r[0] for r in ranked[:n_hold]]
                n_rebal += 1

            # Equal weight among holdings
            if current_holdings:
                w = 1.0 / len(current_holdings)
                day_ret = sum(rets[a].iloc[i] * w for a in current_holdings
                             if not np.isnan(rets[a].iloc[i]))
                daily_strat.iloc[i] = day_ret

        valid = daily_strat.iloc[252+21:]
        valid = valid[valid != 0]
        if len(valid) < 100:
            print(f"    Too few days")
            continue

        # Costs: ~12 rebalances/year, ~N trades per rebalance (half change)
        n_years = len(valid) / ANN_FACTOR
        est_trades = n_rebal * n_hold * 0.5  # turnover ~50% per rebalance
        total_cost = est_trades * ETF_COST_RT
        daily_cost = total_cost / len(valid)
        valid_net = valid - daily_cost

        eq = (1+valid_net).cumprod()
        sh = _sharpe(valid_net)
        dd = _max_dd(eq)*100
        cagr = _cagr(eq)*100
        print(f"    CAGR={cagr:+.1f}%  Sharpe={sh:+.3f}  DD={dd:.1f}%  Rebalances={n_rebal}")

        _print_yearly(valid_net)
        result = _summarize(valid_net, f"Momentum Rotation ({label})")

    # SPY B&H
    spy_ret = rets['SPY'].iloc[252+21:].fillna(0)
    spy_eq = (1+spy_ret).cumprod()
    print(f"\n  vs SPY B&H: CAGR={_cagr(spy_eq)*100:+.1f}%, Sharpe={_sharpe(spy_ret):+.3f}, "
          f"DD={_max_dd(spy_eq)*100:.1f}%")

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 5: RISK PARITY + TREND OVERLAY
# ══════════════════════════════════════════════════════════════════════════════

def strategy_risk_parity_trend(data):
    """
    Risk parity: allocate inversely proportional to vol.
    Trend overlay: reduce allocation when below 10-month SMA.
    Assets: SPY, TLT, GLD, VNQ (classic 4-asset risk parity).
    """
    _print_strat_header("RISK PARITY + TREND OVERLAY")

    assets = ['SPY', 'TLT', 'GLD', 'VNQ']
    available = [a for a in assets if a in data.columns]
    if len(available) < 3:
        print(f"  Only {len(available)} available")
        return None

    prices = data[available].dropna(how='all').ffill().dropna()
    print(f"  Assets: {available}")
    print(f"  Period: {prices.index[0].date()} → {prices.index[-1].date()} ({len(prices)} days)")

    rets = prices.pct_change()
    vol = rets.rolling(60).std()
    sma200 = prices.rolling(200).mean()

    for mode_name, use_trend in [("Risk Parity (static)", False), ("Risk Parity + Trend", True)]:
        print(f"\n  --- {mode_name} ---")

        daily_strat = pd.Series(0.0, index=prices.index)

        for i in range(200, len(prices)):
            # Risk parity weights (inverse vol)
            weights = {}
            for a in available:
                v = vol[a].iloc[i]
                if np.isnan(v) or v <= 0:
                    v = 0.01
                w = 1.0 / v
                # Trend overlay: zero weight if below SMA
                if use_trend and prices[a].iloc[i] < sma200[a].iloc[i]:
                    w = 0
                weights[a] = w

            total_w = sum(weights.values())
            if total_w == 0:
                continue

            # Normalize
            day_ret = 0
            for a, w in weights.items():
                nw = w / total_w
                r = rets[a].iloc[i]
                if not np.isnan(r):
                    day_ret += nw * r

            daily_strat.iloc[i] = day_ret

        valid = daily_strat.iloc[200:]
        valid = valid[valid != 0]
        if len(valid) < 100:
            continue

        # Monthly rebal costs
        n_years = len(valid) / ANN_FACTOR
        total_cost = 12 * len(available) * n_years * ETF_COST_RT
        daily_cost = total_cost / len(valid)
        valid_net = valid - daily_cost

        _print_yearly(valid_net)
        result = _summarize(valid_net, mode_name)

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 6: CRYPTO MOMENTUM ROTATION
# ══════════════════════════════════════════════════════════════════════════════

def strategy_crypto_momentum(data):
    """
    Weekly momentum rotation among BTC, ETH, SOL.
    Also test EMA trend filter.
    """
    _print_strat_header("CRYPTO MOMENTUM ROTATION")

    crypto = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    available = [c for c in crypto if c in data.columns]
    if len(available) < 2:
        print(f"  Only {len(available)} crypto available")
        return None

    prices = data[available].dropna(how='all').ffill().dropna()
    print(f"  Assets: {available}")
    print(f"  Period: {prices.index[0].date()} → {prices.index[-1].date()} ({len(prices)} days)")

    rets = prices.pct_change()

    # Test: hold top 1 by 30-day momentum, weekly rebalance
    for lookback, n_hold in [(30, 1), (60, 1), (30, 2)]:
        label = f"Top {n_hold}, {lookback}d momentum"
        print(f"\n  --- {label} ---")

        daily_strat = pd.Series(0.0, index=prices.index)
        current_holdings = []
        n_switches = 0

        for i in range(lookback, len(prices)):
            dt = prices.index[i]

            # Weekly rebalance (Friday)
            is_rebal = (i == lookback) or (dt.dayofweek == 4 and prices.index[i-1].dayofweek != 4)

            if is_rebal:
                mom = {}
                for a in available:
                    if i - lookback < 0:
                        continue
                    ret = prices[a].iloc[i] / prices[a].iloc[i-lookback] - 1
                    if not np.isnan(ret):
                        mom[a] = ret

                if len(mom) < n_hold:
                    continue

                ranked = sorted(mom.items(), key=lambda x: x[1], reverse=True)
                new_holdings = [r[0] for r in ranked[:n_hold]]
                if set(new_holdings) != set(current_holdings):
                    n_switches += 1
                current_holdings = new_holdings

            if current_holdings:
                w = 1.0 / len(current_holdings)
                day_ret = sum(rets[a].iloc[i] * w for a in current_holdings
                             if not np.isnan(rets[a].iloc[i]))
                daily_strat.iloc[i] = day_ret

        valid = daily_strat.iloc[lookback:]
        valid = valid[valid != 0]
        if len(valid) < 50:
            continue

        # Crypto costs are higher
        total_cost = n_switches * n_hold * CRYPTO_COST_RT
        daily_cost = total_cost / len(valid) if len(valid) > 0 else 0
        valid_net = valid - daily_cost

        eq = (1+valid_net).cumprod()
        sh = _sharpe(valid_net)
        dd = _max_dd(eq)*100
        cagr = _cagr(eq)*100
        print(f"    CAGR={cagr:+.1f}%  Sharpe={sh:+.3f}  DD={dd:.1f}%  Switches={n_switches}")
        _print_yearly(valid_net)

    # BTC B&H
    if 'BTC-USD' in rets.columns:
        btc_ret = rets['BTC-USD'].dropna()
        btc_eq = (1+btc_ret).cumprod()
        print(f"\n  vs BTC B&H: CAGR={_cagr(btc_eq)*100:+.1f}%, Sharpe={_sharpe(btc_ret):+.3f}, "
              f"DD={_max_dd(btc_eq)*100:.1f}%")

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 7: ACCELERATING DUAL MOMENTUM (ADM)
# ══════════════════════════════════════════════════════════════════════════════

def strategy_accelerating_dual_momentum(data):
    """
    Enhanced Dual Momentum with weighted lookbacks.
    Average of 1, 3, 6 month momentum for smoother signal.
    Universe: SPY, QQQ, EFA, EEM, TLT, GLD.
    Hold top 2 if above absolute threshold, else AGG.
    """
    _print_strat_header("ACCELERATING DUAL MOMENTUM (ADM)")

    universe = ['SPY', 'QQQ', 'EFA', 'EEM', 'TLT', 'GLD']
    safe = 'AGG'
    available = [a for a in universe if a in data.columns]
    if len(available) < 4 or safe not in data.columns:
        print(f"  Insufficient data")
        return None

    all_assets = available + [safe]
    prices = data[all_assets].dropna(how='all').ffill().dropna()
    print(f"  Universe: {available}, Safe: {safe}")
    print(f"  Period: {prices.index[0].date()} → {prices.index[-1].date()}")

    rets = prices.pct_change()
    daily_strat = pd.Series(0.0, index=prices.index)
    current_holdings = [safe, safe]
    n_rebal = 0

    for i in range(252, len(prices)):
        dt = prices.index[i]
        is_new_month = (i == 252) or (dt.month != prices.index[i-1].month)

        if is_new_month:
            # Accelerating momentum: weighted avg of 1m, 3m, 6m returns
            mom = {}
            for a in available:
                ret_1m = prices[a].iloc[i] / prices[a].iloc[max(0,i-21)] - 1
                ret_3m = prices[a].iloc[i] / prices[a].iloc[max(0,i-63)] - 1
                ret_6m = prices[a].iloc[i] / prices[a].iloc[max(0,i-126)] - 1
                # Weight recent higher: 1m*40%, 3m*30%, 6m*30%
                mom[a] = 0.40 * ret_1m + 0.30 * ret_3m + 0.30 * ret_6m

            ranked = sorted(mom.items(), key=lambda x: x[1], reverse=True)

            # Top 2 if they have positive momentum (absolute threshold)
            new_holdings = []
            for asset, score in ranked[:2]:
                if score > 0:  # absolute momentum filter
                    new_holdings.append(asset)

            # Fill remaining slots with safe asset
            while len(new_holdings) < 2:
                new_holdings.append(safe)

            current_holdings = new_holdings
            n_rebal += 1

        # Equal weight
        w = 1.0 / len(current_holdings)
        day_ret = sum(rets[a].iloc[i] * w for a in current_holdings
                     if a in rets.columns and not np.isnan(rets[a].iloc[i]))
        daily_strat.iloc[i] = day_ret

    valid = daily_strat.iloc[252:]
    valid = valid[valid != 0]
    if len(valid) < 100:
        return None

    # Costs
    total_cost = n_rebal * 2 * ETF_COST_RT  # 2 positions, monthly
    daily_cost = total_cost / len(valid)
    valid_net = valid - daily_cost

    _print_yearly(valid_net)
    result = _summarize(valid_net, "Accelerating Dual Momentum")

    # Benchmarks
    for bench in ['SPY']:
        if bench in rets.columns:
            br = rets[bench].iloc[252:].fillna(0)
            beq = (1+br).cumprod()
            print(f"    vs {bench} B&H: CAGR={_cagr(beq)*100:+.1f}%, "
                  f"Sharpe={_sharpe(br):+.3f}, DD={_max_dd(beq)*100:.1f}%")

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    data, tickers = download_data()

    results = []

    # Run all strategies
    r = strategy_dual_momentum(data)
    if r: results.append(r)

    r = strategy_trend_following(data)
    if r: results.append(r)

    r = strategy_spy_mean_reversion(data)
    if r: results.append(r)

    r = strategy_momentum_rotation(data)
    if r: results.append(r)

    r = strategy_risk_parity_trend(data)
    if r: results.append(r)

    r = strategy_crypto_momentum(data)
    if r: results.append(r)

    r = strategy_accelerating_dual_momentum(data)
    if r: results.append(r)

    # ── FINAL COMPARISON ──────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  FINAL COMPARISON — All Strategies")
    print("=" * 78)

    if not results:
        print("  No strategies produced results")
        return

    results.sort(key=lambda x: x['sharpe'], reverse=True)
    print(f"\n  {'Strategy':<40s} {'CAGR':>7s} {'Sharpe':>8s} {'MaxDD':>8s} {'Calmar':>8s}")
    print(f"  {'─'*40} {'─'*7} {'─'*8} {'─'*8} {'─'*8}")
    for r in results:
        print(f"  {r['name']:<40s} {r['cagr']:>+6.1f}% {r['sharpe']:>+7.3f} "
              f"{r['max_dd']:>7.1f}% {r['calmar']:>7.2f}")

    best = results[0]
    print(f"\n  WINNER: {best['name']}")
    print(f"    CAGR {best['cagr']:+.1f}%, Sharpe {best['sharpe']:+.3f}, Max DD {best['max_dd']:.1f}%")

    # Tradeable assessment
    print(f"\n  {'─'*60}")
    if best['sharpe'] >= 0.7 and best['max_dd'] > -35:
        print(f"  ✅ TRADEABLE: {best['name']} is a viable strategy")
        print(f"     Implement on IBKR with monthly rebalancing")
    elif best['sharpe'] >= 0.5:
        print(f"  ⚠️  MARGINAL: {best['name']} works but needs improvement")
        print(f"     Consider combining with other filters")
    else:
        print(f"  ❌ INSUFFICIENT: No strategy meets minimum Sharpe threshold")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
