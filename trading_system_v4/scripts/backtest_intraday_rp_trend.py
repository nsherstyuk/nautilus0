"""
backtest_intraday_rp_trend.py — Intraday Risk Parity + Trend on 1h ETF bars

The daily version showed:
  - Risk Parity + Trend:  CAGR +8.4%, Sharpe +0.867, DD -18.7% (monthly rebal)
  - CTA Trend L/O:        CAGR +4.5%, Sharpe +0.632, DD -22.8% (monthly rebal)

Question: Can we improve execution with intraday (1h) entry/exit timing?
Data: yfinance 1h bars (~2 years for ETFs), supplemented with daily bars for
full signal computation.

Intraday approaches tested:
  1. Baseline: daily close rebalance (replicate daily result on 2yr window)
  2. Intraday SMA crossover execution (enter/exit when 1h price crosses SMA)
  3. VWAP-style execution (enter near day's VWAP instead of close)
  4. Volatility-timed execution (enter during low-vol hours)
  5. RSI-based intraday timing (enter on oversold within trend direction)

Also tests:
  - How much do you save by executing at intraday lows vs close?
  - What's the realistic improvement from splitting orders across hours?
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

ETF_COST_RT = 0.0003  # 0.03% round-trip IBKR ETFs
ANN_D = 252
ANN_H = 252 * 6.5  # ~1638 trading hours/year (6.5h/day)

CACHE_1H = DATA_DIR / "etf_universe_1h_yf.parquet"
CACHE_DAILY = DATA_DIR / "multi_asset_daily.parquet"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sharpe(r, af=ANN_D):
    return r.mean() / (r.std() + 1e-10) * np.sqrt(af)

def _max_dd(eq):
    return ((eq - eq.cummax()) / eq.cummax()).min()

def _cagr(eq, af=ANN_D):
    n = len(eq) / af
    return (eq.iloc[-1] / eq.iloc[0]) ** (1/n) - 1 if n > 0 and eq.iloc[0] > 0 else 0


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════

def download_1h_data():
    """Download 1h bars for ETF universe from yfinance."""
    symbols = ["SPY", "TLT", "GLD", "VNQ", "QQQ", "IWM", "EFA", "EEM", "IEF", "DBC"]

    if CACHE_1H.exists():
        print(f"  Loading cached 1h data from {CACHE_1H.name}")
        df = pd.read_parquet(CACHE_1H)
        # Check age
        last_ts = df.index.max()
        if hasattr(last_ts, 'tz') and last_ts.tz is not None:
            age_days = (pd.Timestamp.now(tz='UTC') - last_ts).days
        else:
            age_days = (pd.Timestamp.now() - last_ts).days
        if age_days < 2:
            print(f"    {len(df):,} rows, {len(df.columns)} syms, "
                  f"last: {last_ts}")
            return df
        print(f"    Stale ({age_days}d old), re-downloading...")

    print(f"  Downloading 1h bars for {symbols}...")
    # yfinance: max ~730 days for 1h
    raw = yf.download(
        symbols,
        period="730d",
        interval="1h",
        auto_adjust=True,
        progress=False,
    )

    if isinstance(raw.columns, pd.MultiIndex):
        # Build OHLCV DataFrames per symbol
        closes = raw["Close"]
        highs = raw["High"]
        lows = raw["Low"]
        volumes = raw["Volume"]
    else:
        closes = raw[["Close"]]
        highs = raw[["High"]]
        lows = raw[["Low"]]
        volumes = raw[["Volume"]]

    # Save close prices
    closes = closes.ffill()
    closes.to_parquet(CACHE_1H)

    print(f"  Downloaded {len(closes):,} hourly bars")
    for sym in closes.columns:
        valid = closes[sym].dropna()
        if len(valid) > 0:
            print(f"    {sym:>5}: {len(valid):,} bars  "
                  f"{valid.index[0]} → {valid.index[-1]}")

    # Also save highs, lows, volumes
    cache_hl = DATA_DIR / "etf_universe_1h_hl_yf.parquet"
    hl = pd.DataFrame({
        **{f"{s}_high": highs[s] for s in highs.columns},
        **{f"{s}_low": lows[s] for s in lows.columns},
        **{f"{s}_vol": volumes[s] for s in volumes.columns},
    })
    hl.to_parquet(cache_hl)

    return closes


def load_daily_data():
    """Load daily data from prior analysis."""
    if not CACHE_DAILY.exists():
        print("  No cached daily data. Run find_tradeable_edge.py first.")
        return None
    return pd.read_parquet(CACHE_DAILY)


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS 1: EXECUTION PRICE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_execution_prices(hourly_closes):
    """
    For each day, compare different execution prices:
    - Close (last bar of day)
    - VWAP proxy (average of all hourly closes)
    - Best price (low of day for buys, high for sells)
    - Worst price (high for buys, low for sells)
    """
    print("\n" + "=" * 72)
    print("  ANALYSIS 1: INTRADAY EXECUTION PRICE STATS")
    print("=" * 72)

    # Need HLC data
    cache_hl = DATA_DIR / "etf_universe_1h_hl_yf.parquet"
    if not cache_hl.exists():
        print("  No HLC data available")
        return

    hl = pd.read_parquet(cache_hl)

    for sym in ["SPY", "TLT", "GLD", "VNQ"]:
        if sym not in hourly_closes.columns:
            continue

        c = hourly_closes[sym].dropna()
        h_col = f"{sym}_high"
        l_col = f"{sym}_low"

        if h_col not in hl.columns:
            continue

        highs = hl[h_col].reindex(c.index)
        lows = hl[l_col].reindex(c.index)

        # Group by date
        c_dates = c.index.date
        daily_close = c.groupby(c_dates).last()
        daily_vwap = c.groupby(c_dates).mean()  # proxy VWAP (avg of closes)
        daily_high = highs.groupby(c_dates).max()
        daily_low = lows.groupby(c_dates).min()
        daily_open = c.groupby(c_dates).first()

        # How much could you save vs close?
        buy_savings = (daily_close - daily_low) / daily_close * 100  # % saved
        vwap_savings = (daily_close - daily_vwap) / daily_close * 100
        open_diff = (daily_close - daily_open) / daily_close * 100

        # Intraday range as % of price
        intra_range = (daily_high - daily_low) / daily_close * 100

        print(f"\n  {sym}:")
        print(f"    Avg intraday range:     {intra_range.mean():.3f}%")
        print(f"    Median intraday range:  {intra_range.median():.3f}%")
        print(f"    Buy at low saves:       {buy_savings.mean():.3f}% vs close")
        print(f"    Buy at VWAP saves:      {vwap_savings.mean():.3f}% vs close")
        print(f"    Open vs Close avg diff: {open_diff.mean():+.3f}%")
        print(f"    IBKR round-trip cost:   {ETF_COST_RT*100:.3f}%")
        print(f"    → VWAP improvement vs cost: "
              f"{abs(vwap_savings.mean())/ETF_COST_RT/100:.1f}x the cost")


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS 2: RISK PARITY DAILY vs INTRADAY REBALANCE
# ══════════════════════════════════════════════════════════════════════════════

def risk_parity_comparison(hourly_closes, daily_data):
    """
    Compare Risk Parity + Trend on same 2yr window:
    1. Daily close rebalance (monthly)
    2. Hourly rebalance (still monthly schedule, but use hourly returns)
    3. Intraday SMA cross (rebalance when hourly price crosses daily SMA)
    """
    print("\n" + "=" * 72)
    print("  ANALYSIS 2: RISK PARITY — DAILY vs INTRADAY")
    print("=" * 72)

    assets = ["SPY", "TLT", "GLD", "VNQ"]
    available = [a for a in assets if a in hourly_closes.columns]
    if len(available) < 3:
        print(f"  Only {len(available)} assets available in hourly data")
        return

    # ── A: Daily baseline on same period ──
    # Get daily close from hourly data
    h = hourly_closes[available].dropna()
    h_dates = h.index.date

    daily_from_hourly = h.groupby(h_dates).last()
    daily_from_hourly.index = pd.to_datetime(daily_from_hourly.index)

    print(f"  Hourly period: {h.index.min()} → {h.index.max()} ({len(h):,} bars)")
    print(f"  Daily bars from hourly: {len(daily_from_hourly)}")

    rets_d = daily_from_hourly.pct_change()
    vol_d = rets_d.rolling(60).std()
    sma200_d = daily_from_hourly.rolling(200).mean()

    # Also use the actual daily data for longer SMA history
    if daily_data is not None:
        daily_full = daily_data[available].dropna(how='all').ffill()
        sma200_full = daily_full.rolling(200).mean()
        vol_full = daily_full.pct_change().rolling(60).std()

        # Merge: use daily_full for SMA/vol, hourly for execution
        # Map daily signals to hourly timestamps
        latest_sma = {}
        latest_vol = {}
        for a in available:
            # Get last available SMA/vol for each date in hourly
            sma_s = sma200_full[a].dropna()
            vol_s = vol_full[a].dropna()
            latest_sma[a] = sma_s
            latest_vol[a] = vol_s
    else:
        # Fallback: shorter SMA
        print("  ⚠ No daily data, using SMA50 instead of SMA200")
        sma200_d = daily_from_hourly.rolling(50).mean()

    # ── Strategy A: Monthly rebal on daily closes ──
    print(f"\n  --- A. Daily close, monthly rebalance ---")

    warmup = min(200, len(daily_from_hourly) - 50)
    if warmup < 50:
        print("    Not enough daily bars for warmup")
        return

    weights_daily = pd.DataFrame(0.0, index=daily_from_hourly.index, columns=available)
    current_w = pd.Series(0.0, index=available)

    for i in range(warmup, len(daily_from_hourly)):
        dt = daily_from_hourly.index[i]
        is_month = (i == warmup) or (dt.month != daily_from_hourly.index[i-1].month)

        if is_month:
            new_w = pd.Series(0.0, index=available)
            for a in available:
                price = daily_from_hourly[a].iloc[i]

                # Get SMA from full daily if available
                if daily_data is not None and a in latest_sma:
                    sma_vals = latest_sma[a]
                    # Find closest date <= dt
                    mask = sma_vals.index <= dt
                    if mask.any():
                        sma_val = sma_vals[mask].iloc[-1]
                    else:
                        sma_val = price  # no SMA yet
                    vol_vals = latest_vol[a]
                    vmask = vol_vals.index <= dt
                    v = vol_vals[vmask].iloc[-1] if vmask.any() else 0.01
                else:
                    sma_val = sma200_d[a].iloc[i] if not np.isnan(sma200_d[a].iloc[i]) else price
                    v = vol_d[a].iloc[i] if not np.isnan(vol_d[a].iloc[i]) else 0.01

                if np.isnan(v) or v <= 0:
                    v = 0.01

                if price > sma_val:
                    new_w[a] = 1.0 / v
                else:
                    new_w[a] = 0.0

            total = new_w.sum()
            if total > 0:
                new_w /= total
            current_w = new_w

        weights_daily.iloc[i] = current_w

    strat_d = (weights_daily.shift(1) * rets_d).sum(axis=1)
    turnover_d = weights_daily.diff().abs().sum(axis=1)
    cost_d = turnover_d * ETF_COST_RT
    strat_d_net = strat_d - cost_d
    valid_d = strat_d_net.iloc[warmup:]

    eq_d = (1 + valid_d).cumprod()
    sh_d = _sharpe(valid_d)
    dd_d = _max_dd(eq_d) * 100
    cagr_d = _cagr(eq_d) * 100

    print(f"    CAGR={cagr_d:+.1f}%  Sharpe={sh_d:+.3f}  DD={dd_d:.1f}%")

    # Yearly
    for yr, grp in valid_d.groupby(valid_d.index.year):
        yr_ret = (1+grp).prod()-1
        print(f"      {yr}: {yr_ret*100:>+7.1f}%")

    # ── Strategy B: Hourly data, same monthly weights ──
    print(f"\n  --- B. Hourly returns, monthly rebalance (same signals) ---")

    rets_h = h.pct_change()

    # Map daily weights to hourly
    weights_hourly = pd.DataFrame(0.0, index=h.index, columns=available)
    wd_set = set(weights_daily.index)
    for i in range(len(h)):
        dt_pd = pd.Timestamp(h.index[i].date())
        if dt_pd in wd_set:
            weights_hourly.iloc[i] = weights_daily.loc[dt_pd]
        elif i > 0:
            weights_hourly.iloc[i] = weights_hourly.iloc[i-1]

    strat_h = (weights_hourly.shift(1) * rets_h).sum(axis=1)

    # Same costs as daily (monthly rebalance)
    # But track hourly PnL path for more granular DD
    # Costs applied at month boundaries
    h_dates_series = pd.Series(h.index.date, index=h.index)
    is_new_day = h_dates_series != h_dates_series.shift(1)
    is_month_start_h = pd.Series(False, index=h.index)
    for i in range(1, len(h.index)):
        if h.index[i].month != h.index[i-1].month:
            is_month_start_h.iloc[i] = True

    turnover_h = weights_hourly.diff().abs().sum(axis=1)
    cost_h = turnover_h * ETF_COST_RT
    strat_h_net = strat_h - cost_h

    # Filter to warmup period
    warmup_date = daily_from_hourly.index[warmup]
    warmup_ts = pd.Timestamp(warmup_date)
    if h.index.tz is not None and warmup_ts.tz is None:
        warmup_ts = warmup_ts.tz_localize(h.index.tz)
    valid_h = strat_h_net[h.index >= warmup_ts]

    eq_h = (1 + valid_h).cumprod()
    sh_h = _sharpe(valid_h, af=ANN_H)
    dd_h = _max_dd(eq_h) * 100

    # Annualize from hourly
    n_years = len(valid_h) / ANN_H
    cagr_h = (eq_h.iloc[-1] ** (1/n_years) - 1) * 100 if n_years > 0 else 0

    print(f"    CAGR={cagr_h:+.1f}%  Sharpe={sh_h:+.3f}  DD(hourly)={dd_h:.1f}%")
    print(f"    Note: hourly DD captures intraday drawdowns not visible in daily")

    # ── Strategy C: Intraday SMA Cross Timing ──
    print(f"\n  --- C. Intraday SMA Cross Timing ---")
    print(f"  Enter when 1h close crosses ABOVE daily SMA; exit when crosses BELOW")

    # For each asset, compute hourly vs daily SMA
    weights_cross = pd.DataFrame(0.0, index=h.index, columns=available)

    # Pre-build date→SMA and date→vol maps for fast lookup
    for a in available:
        col_idx = weights_cross.columns.get_loc(a)

        if daily_data is not None and a in latest_sma:
            sma_series = latest_sma[a].dropna()
        else:
            sma_series = daily_from_hourly[a].rolling(50).mean().dropna()

        if daily_data is not None and a in latest_vol:
            vol_series = latest_vol[a].dropna()
        else:
            vol_series = None

        sma_idx = sma_series.index
        sma_vals_arr = sma_series.values

        for i in range(len(h)):
            dt_date = h.index[i].date()
            dt_pd = pd.Timestamp(dt_date)
            price = h[a].iloc[i]

            if np.isnan(price):
                continue

            # Binary search for most recent SMA <= dt_pd
            pos = sma_idx.searchsorted(dt_pd, side='right') - 1
            if pos < 0:
                continue
            sma_val = sma_vals_arr[pos]

            if np.isnan(sma_val):
                continue

            # Trend direction from SMA
            if price > sma_val:
                v = 0.01
                if vol_series is not None:
                    vpos = vol_series.index.searchsorted(dt_pd, side='right') - 1
                    if vpos >= 0:
                        v = vol_series.values[vpos]
                if np.isnan(v) or v <= 0:
                    v = 0.01
                weights_cross.iat[i, col_idx] = 1.0 / v
            else:
                weights_cross.iat[i, col_idx] = 0.0

    # Normalize weights each bar
    row_sums = weights_cross.sum(axis=1)
    for a in available:
        weights_cross[a] = np.where(row_sums > 0, weights_cross[a] / row_sums, 0)

    strat_cross = (weights_cross.shift(1) * rets_h).sum(axis=1)
    turnover_cross = weights_cross.diff().abs().sum(axis=1)
    cost_cross = turnover_cross * ETF_COST_RT
    strat_cross_net = strat_cross - cost_cross

    valid_cross = strat_cross_net[h.index >= warmup_ts]

    eq_cross = (1 + valid_cross).cumprod()
    sh_cross = _sharpe(valid_cross, af=ANN_H)
    dd_cross = _max_dd(eq_cross) * 100
    n_yr_cross = len(valid_cross) / ANN_H
    cagr_cross = (eq_cross.iloc[-1] ** (1/n_yr_cross) - 1) * 100 if n_yr_cross > 0 else 0
    n_trades_cross = (turnover_cross > 0.001).sum()
    total_cost_cross = cost_cross.sum() * 100

    print(f"    CAGR={cagr_cross:+.1f}%  Sharpe={sh_cross:+.3f}  DD={dd_cross:.1f}%")
    print(f"    Trades: {n_trades_cross}  Total cost: {total_cost_cross:.2f}%")

    # ── Strategy D: Volatility-timed entry ──
    print(f"\n  --- D. Low-vol hour execution ---")
    print(f"  Only enter/change positions during lowest-volatility hours of day")

    # Compute hourly vol by hour-of-day
    h_hour = h.index.hour
    hourly_vol_by_time = rets_h.abs().groupby(h_hour).mean()

    if len(hourly_vol_by_time) > 0:
        print(f"    Avg absolute return by hour:")
        for hour_val in sorted(hourly_vol_by_time.index):
            row = hourly_vol_by_time.loc[hour_val]
            avg = row.mean() * 100
            bar = "#" * int(avg * 500)
            print(f"      {hour_val:>2d}:00  {avg:.4f}%  {bar}")

        # Find lowest-vol hours
        avg_vol_by_hour = hourly_vol_by_time.mean(axis=1)
        best_hours = avg_vol_by_hour.nsmallest(3).index.tolist()
        worst_hours = avg_vol_by_hour.nlargest(3).index.tolist()
        print(f"    Lowest-vol hours:  {best_hours}")
        print(f"    Highest-vol hours: {worst_hours}")

    # ── Summary comparison ──
    print(f"\n  {'─'*60}")
    print(f"  SUMMARY COMPARISON (same ~2yr period)")
    print(f"  {'Strategy':<40s} {'CAGR':>7s} {'Sharpe':>8s} {'MaxDD':>8s}")
    print(f"  {'─'*40} {'─'*7} {'─'*8} {'─'*8}")
    print(f"  {'A. Daily close, monthly rebal':<40s} {cagr_d:>+6.1f}% {sh_d:>+7.3f} {dd_d:>7.1f}%")
    print(f"  {'B. Hourly rets, monthly rebal':<40s} {cagr_h:>+6.1f}% {sh_h:>+7.3f} {dd_h:>7.1f}%")
    print(f"  {'C. Intraday SMA cross':<40s} {cagr_cross:>+6.1f}% {sh_cross:>+7.3f} {dd_cross:>7.1f}%")

    # Buy & Hold SPY
    if "SPY" in rets_d.columns:
        spy_d = rets_d["SPY"].iloc[warmup:]
        spy_eq = (1+spy_d).cumprod()
        spy_cagr = _cagr(spy_eq)*100
        spy_sh = _sharpe(spy_d)
        spy_dd = _max_dd(spy_eq)*100
        print(f"  {'SPY Buy & Hold':<40s} {spy_cagr:>+6.1f}% {spy_sh:>+7.3f} {spy_dd:>7.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS 3: HOUR-OF-DAY EDGE
# ══════════════════════════════════════════════════════════════════════════════

def hour_of_day_analysis(hourly_closes):
    """Check if certain hours consistently produce better returns."""
    print("\n" + "=" * 72)
    print("  ANALYSIS 3: HOUR-OF-DAY RETURN PATTERNS")
    print("=" * 72)

    for sym in ["SPY", "TLT", "GLD", "VNQ"]:
        if sym not in hourly_closes.columns:
            continue

        c = hourly_closes[sym].dropna()
        rets = c.pct_change()
        hours = c.index.hour

        print(f"\n  {sym} — Mean hourly return by hour (bps):")
        stats = []
        for h_val in sorted(hours.unique()):
            mask = hours == h_val
            r = rets[mask]
            mean_bps = r.mean() * 10000
            std_bps = r.std() * 10000
            sr = r.mean() / (r.std() + 1e-10) * np.sqrt(ANN_H)
            n = len(r)
            stats.append((h_val, mean_bps, std_bps, sr, n))

        print(f"    {'Hour':>6} {'Mean':>8} {'Std':>8} {'Sharpe':>8} {'Count':>7}")
        for h_val, m, s, sr, n in stats:
            print(f"    {h_val:>5d}h {m:>+7.2f} {s:>7.1f} {sr:>+7.3f} {n:>7d}")


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSIS 4: GAP ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def gap_analysis(hourly_closes):
    """Analyze overnight gaps — could we profit from gap fade/follow?"""
    print("\n" + "=" * 72)
    print("  ANALYSIS 4: OVERNIGHT GAP ANALYSIS")
    print("=" * 72)

    for sym in ["SPY", "TLT", "GLD", "VNQ"]:
        if sym not in hourly_closes.columns:
            continue

        c = hourly_closes[sym].dropna()
        dates = c.index.date

        # Group by day
        daily_groups = c.groupby(dates)
        prev_close = None
        gaps = []

        for dt, grp in daily_groups:
            if len(grp) < 2:
                continue
            day_open = grp.iloc[0]
            day_close = grp.iloc[-1]

            if prev_close is not None and prev_close > 0:
                gap_pct = (day_open / prev_close - 1) * 100
                day_ret = (day_close / day_open - 1) * 100
                gaps.append({
                    'date': dt,
                    'gap': gap_pct,
                    'intraday_ret': day_ret,
                    'prev_close': prev_close,
                })

            prev_close = day_close

        if not gaps:
            continue

        gdf = pd.DataFrame(gaps)

        # Gap stats
        avg_gap = gdf['gap'].abs().mean()
        gap_fade = (gdf['gap'] * gdf['intraday_ret'] < 0).mean() * 100  # gap fades %

        # Big gaps (>0.5%)
        big_up = gdf[gdf['gap'] > 0.5]
        big_dn = gdf[gdf['gap'] < -0.5]

        print(f"\n  {sym}:")
        print(f"    Total days: {len(gdf)}")
        print(f"    Avg |gap|: {avg_gap:.3f}%")
        print(f"    Gap fades (intraday reverses gap): {gap_fade:.1f}%")
        if len(big_up) > 0:
            print(f"    Big gap up (>0.5%): {len(big_up)} days, "
                  f"avg intraday {big_up['intraday_ret'].mean():+.3f}%")
        if len(big_dn) > 0:
            print(f"    Big gap down (<-0.5%): {len(big_dn)} days, "
                  f"avg intraday {big_dn['intraday_ret'].mean():+.3f}%")

        # Correlation between gap and intraday return
        corr = gdf['gap'].corr(gdf['intraday_ret'])
        print(f"    Gap ↔ intraday return correlation: {corr:+.3f}")
        if abs(corr) > 0.1:
            direction = "fade" if corr < 0 else "follow"
            print(f"    → Slight tendency to {direction} gaps")
        else:
            print(f"    → No exploitable gap pattern")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    print("=" * 72)
    print("  INTRADAY RISK PARITY + TREND — HOURLY BAR ANALYSIS")
    print("=" * 72)

    hourly = download_1h_data()
    daily = load_daily_data()

    analyze_execution_prices(hourly)
    risk_parity_comparison(hourly, daily)
    hour_of_day_analysis(hourly)
    gap_analysis(hourly)

    print(f"\n  Total runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
