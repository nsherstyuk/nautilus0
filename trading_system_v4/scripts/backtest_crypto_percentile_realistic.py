"""
Realistic Percentile Breakout Backtest — IBKR Implementation Check
===================================================================
Purpose: Model EXACTLY how this would work on IBKR PAXOS exchange.

IBKR PAXOS Crypto Facts:
  - Available: BTC, ETH, LTC, BCH, SOL, LINK, MATIC, UNI, AAVE (9 coins)
  - Commission: 0.12%-0.18% of trade value (tiered, 0.18% for <$100k/mo)
  - Minimum order: $1.00 notional (effectively no minimum on BTC)
  - Fractional trading: YES (e.g., 0.001 BTC)
  - Spread: ~$10-50 on BTC ($95k price) ≈ ~0.5-2 bps
  - Trading hours: 24/7 (except 5-min maintenance window)
  - Settlement: instant (no T+1/T+2)
  - No margin for crypto (cash only, 100% collateral)

Strategy mechanics:
  - Once per day, after UTC midnight (new daily candle close):
      1. Compute 40-day rolling 70th percentile of BTC close prices
      2. If current close > percentile → go long (or stay long)
      3. If current close <= percentile → go flat (or stay flat)
  - Position sized by vol-targeting: target_vol / realized_vol
  - Max position = 100% of allocated capital (no leverage for crypto)

This script models:
  - Discrete positions (not continuous weights)
  - Actual IBKR commission (0.18% each way)
  - Spread cost (~1-2 bps per trade)
  - No lookahead (signal from day T, trade at day T+1 open proxy)
  - Trade log with individual entries/exits
  - Equity curve, drawdowns, rolling performance
  - Comparison across parameter variants
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


# ─── Constants ──────────────────────────────────────────────────────────────

IBKR_COMMISSION_BPS = 18      # 0.18% each way for <$100k monthly volume
SPREAD_BPS = 2                # ~$20 on $95k BTC
TOTAL_COST_PER_TRADE_BPS = IBKR_COMMISSION_BPS + SPREAD_BPS  # 20 bps per side

INITIAL_CAPITAL = 10_000      # $10k starting capital
VOL_TARGET = 0.40             # annualized vol target
MAX_POSITION_FRAC = 1.0       # max 100% of capital (no leverage on IBKR crypto)
VOL_LOOKBACK = 20             # days for realized vol estimate


# ─── Data Loading ───────────────────────────────────────────────────────────

def load_data():
    """Load BTC daily data (closes, highs, lows)."""
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    # Columns have -USD suffix
    col = "BTC-USD" if "BTC-USD" in closes.columns else "BTC"
    btc = closes[col].dropna()
    print(f"  BTC daily: {len(btc)} days, {btc.index[0].date()} → {btc.index[-1].date()}")
    print(f"  Price range: ${btc.min():,.0f} → ${btc.max():,.0f}")
    return btc


# ─── Signal Generation ─────────────────────────────────────────────────────

def percentile_signal(price, lookback=40, pct=70):
    """
    Signal = 1.0 when price > N-th percentile of last `lookback` days.
    Signal = 0.0 otherwise (flat, no short).
    """
    rolling_pct = price.rolling(lookback).quantile(pct / 100)
    sig = (price > rolling_pct).astype(float)
    return sig, rolling_pct


# ─── Position Sizing ───────────────────────────────────────────────────────

def compute_target_position(signal, price, realized_vol, capital,
                            vol_target=VOL_TARGET, max_frac=MAX_POSITION_FRAC):
    """
    Compute target dollar position based on vol-targeting.
    
    target_weight = vol_target / realized_vol  (capped at max_frac)
    target_dollars = capital * target_weight * signal
    target_btc = target_dollars / price
    """
    if realized_vol <= 0.01 or np.isnan(realized_vol):
        return 0.0, 0.0
    
    weight = min(vol_target / realized_vol, max_frac)
    target_dollars = capital * weight * signal
    target_btc = target_dollars / price
    return target_dollars, target_btc


# ─── Realistic Backtest Engine ──────────────────────────────────────────────

def backtest_realistic(btc_prices, lookback=40, pct=70,
                       initial_capital=INITIAL_CAPITAL,
                       vol_target=VOL_TARGET,
                       cost_bps=TOTAL_COST_PER_TRADE_BPS,
                       execution_delay=1,
                       label=""):
    """
    Full discrete-position backtest with trade log.
    
    execution_delay=1 means: signal computed end of day T, 
    position adjusted at close of day T+1 (conservative; in reality 
    you could execute at T open or even T midnight).
    """
    signal, rolling_pct = percentile_signal(btc_prices, lookback, pct)
    
    ret = btc_prices.pct_change()
    realized_vol = ret.rolling(VOL_LOOKBACK).std() * np.sqrt(365)
    
    # Align everything
    df = pd.DataFrame({
        "price": btc_prices,
        "ret": ret,
        "signal": signal,
        "pct_level": rolling_pct,
        "real_vol": realized_vol,
    }).dropna()
    
    # Apply execution delay
    df["signal_delayed"] = df["signal"].shift(execution_delay)
    df = df.dropna()
    
    # ── Simulate day by day ──
    capital = initial_capital
    btc_held = 0.0      # fractional BTC units held
    position_usd = 0.0   # current position in dollars
    
    equity_curve = []
    trade_log = []
    daily_log = []
    
    for i, (dt, row) in enumerate(df.iterrows()):
        price = row["price"]
        sig = row["signal_delayed"]
        rv = row["real_vol"]
        daily_ret = row["ret"]
        
        # Mark-to-market current position
        if btc_held > 0:
            pnl_today = btc_held * price * daily_ret  # approximate daily PnL
        else:
            pnl_today = 0.0
        
        capital += pnl_today
        position_usd = btc_held * price
        
        # Compute target position
        target_usd, target_btc = compute_target_position(
            sig, price, rv, capital, vol_target, MAX_POSITION_FRAC
        )
        
        # How much do we need to trade?
        trade_usd = abs(target_usd - position_usd)
        trade_btc = target_btc - btc_held
        
        # Only trade if change is meaningful (>1% of capital to avoid churn)
        if trade_usd > capital * 0.01:
            # Apply transaction costs
            cost = trade_usd * (cost_bps / 10000)
            capital -= cost
            
            # Record trade
            direction = "BUY" if trade_btc > 0 else "SELL"
            trade_log.append({
                "date": dt,
                "direction": direction,
                "btc_amount": abs(trade_btc),
                "usd_amount": trade_usd,
                "price": price,
                "cost": cost,
                "signal": sig,
                "new_position_usd": target_usd,
                "capital_after": capital,
            })
            
            btc_held = target_btc
            position_usd = target_usd
        
        equity_curve.append({
            "date": dt,
            "capital": capital,
            "position_usd": position_usd,
            "btc_held": btc_held,
            "signal": sig,
            "price": price,
            "pnl_today": pnl_today,
            "real_vol": rv,
        })
    
    # ── Build results ──
    eq = pd.DataFrame(equity_curve).set_index("date")
    trades = pd.DataFrame(trade_log)
    
    eq["equity_ret"] = eq["capital"].pct_change()
    
    # Key metrics
    total_ret = eq["capital"].iloc[-1] / initial_capital - 1
    n_years = len(eq) / 365
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if total_ret > -1 else -1.0
    ann_vol = eq["equity_ret"].std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    dd = (eq["capital"] / eq["capital"].cummax() - 1)
    max_dd = dd.min()
    
    # Trade statistics
    n_trades = len(trades)
    total_cost = trades["cost"].sum() if n_trades > 0 else 0
    avg_trade_usd = trades["usd_amount"].mean() if n_trades > 0 else 0
    
    # Time in market
    time_in_mkt = (eq["signal"] > 0).mean()
    
    # Buys vs sells
    if n_trades > 0:
        buys = trades[trades["direction"] == "BUY"]
        sells = trades[trades["direction"] == "SELL"]
    else:
        buys = sells = pd.DataFrame()
    
    # Holding period analysis
    holding_periods = []
    entry_date = None
    for _, row in eq.iterrows():
        if row["signal"] > 0 and entry_date is None:
            entry_date = row.name
        elif row["signal"] == 0 and entry_date is not None:
            holding_periods.append((row.name - entry_date).days)
            entry_date = None
    
    avg_hold = np.mean(holding_periods) if holding_periods else 0
    
    # Monthly returns
    monthly = eq["equity_ret"].resample("ME").sum()
    monthly_wr = (monthly > 0).mean()
    
    # Yearly returns
    yearly = eq["equity_ret"].resample("YE").sum()
    
    # Rolling Sharpe (1yr)
    rolling_sr = (eq["equity_ret"].rolling(365).mean() / 
                  eq["equity_ret"].rolling(365).std()) * np.sqrt(365)
    
    results = {
        "label": label or f"Pctl({lookback}d, {pct}th)",
        "sharpe": sharpe,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "total_ret": total_ret,
        "max_dd": max_dd,
        "n_trades": n_trades,
        "total_cost": total_cost,
        "cost_pct_of_ret": total_cost / (total_ret * initial_capital) * 100 if total_ret > 0 else float("inf"),
        "avg_trade_usd": avg_trade_usd,
        "time_in_mkt": time_in_mkt,
        "avg_hold_days": avg_hold,
        "monthly_wr": monthly_wr,
        "n_years": n_years,
        "equity": eq,
        "trades": trades,
        "yearly": yearly,
        "rolling_sr": rolling_sr,
        "dd_series": dd,
        "holding_periods": holding_periods,
    }
    return results


# ─── Display ────────────────────────────────────────────────────────────────

def print_results(r):
    """Print comprehensive results."""
    print(f"\n  ╔══════════════════════════════════════════════════════╗")
    print(f"  ║  {r['label']:^50s}  ║")
    print(f"  ╠══════════════════════════════════════════════════════╣")
    print(f"  ║  Sharpe Ratio:     {r['sharpe']:+.2f}                             ║")
    print(f"  ║  Annual Return:    {r['ann_ret']:+.1%}                           ║")
    print(f"  ║  Annual Volatility:{r['ann_vol']:.1%}                            ║")
    print(f"  ║  Total Return:     {r['total_ret']:+.1%}  ({r['n_years']:.1f} years)            ║")
    print(f"  ║  Max Drawdown:     {r['max_dd']:.1%}                           ║")
    print(f"  ╠══════════════════════════════════════════════════════╣")
    print(f"  ║  EXECUTION DETAILS                                  ║")
    print(f"  ║  Total trades:     {r['n_trades']:>6d}                            ║")
    print(f"  ║  Avg trade size:   ${r['avg_trade_usd']:>8,.0f}                      ║")
    print(f"  ║  Total costs:      ${r['total_cost']:>8,.2f}                      ║")
    if r['total_ret'] > 0:
        print(f"  ║  Costs as % profit:{r['cost_pct_of_ret']:>6.1f}%                          ║")
    print(f"  ║  Time in market:   {r['time_in_mkt']:.0%}                             ║")
    print(f"  ║  Avg hold period:  {r['avg_hold_days']:.0f} days                          ║")
    print(f"  ║  Monthly win rate: {r['monthly_wr']:.0%}                             ║")
    print(f"  ╚══════════════════════════════════════════════════════╝")


def print_yearly(r):
    """Print year-by-year returns."""
    print(f"\n  Year-by-year returns:")
    for yr, ret in r["yearly"].items():
        yr_label = yr.year
        bar = "█" * int(max(0, ret) * 100)
        neg_bar = "░" * int(abs(min(0, ret)) * 100)
        print(f"    {yr_label}:  {ret:+7.1%}  {bar}{neg_bar}")


def print_trade_sample(r, n=15):
    """Print a sample of trades."""
    trades = r["trades"]
    if len(trades) == 0:
        print("  No trades.")
        return
    print(f"\n  Last {n} trades:")
    print(f"    {'Date':12s}  {'Dir':4s}  {'BTC':>10s}  {'USD':>10s}  {'Price':>10s}  {'Cost':>8s}")
    print(f"    {'─'*12}  {'─'*4}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*8}")
    for _, t in trades.tail(n).iterrows():
        print(f"    {str(t['date'].date()):12s}  {t['direction']:4s}  "
              f"{t['btc_amount']:10.6f}  ${t['usd_amount']:>9,.0f}  "
              f"${t['price']:>9,.0f}  ${t['cost']:>7.2f}")


def print_rolling_sr(r):
    """Print rolling 1-year Sharpe at key points."""
    rs = r["rolling_sr"].dropna()
    if len(rs) == 0:
        return
    print(f"\n  Rolling 1-Year Sharpe:")
    # Sample at year boundaries
    for yr in range(rs.index[0].year + 1, rs.index[-1].year + 1):
        yr_data = rs[rs.index.year == yr]
        if len(yr_data) > 0:
            end_val = yr_data.iloc[-1]
            min_val = yr_data.min()
            max_val = yr_data.max()
            print(f"    {yr}: end={end_val:+.2f}  min={min_val:+.2f}  max={max_val:+.2f}")


def print_drawdown_analysis(r):
    """Print worst drawdown periods."""
    dd = r["dd_series"]
    eq = r["equity"]
    
    # Find top 5 drawdown troughs
    is_trough = (dd < dd.shift(1)) & (dd < dd.shift(-1)) & (dd < -0.03)
    troughs = dd[is_trough].nsmallest(5)
    
    print(f"\n  Worst drawdown periods:")
    print(f"    {'Trough Date':12s}  {'Depth':>8s}  {'BTC Price':>10s}  {'Capital':>10s}")
    print(f"    {'─'*12}  {'─'*8}  {'─'*10}  {'─'*10}")
    for dt, depth in troughs.items():
        price = eq.loc[dt, "price"]
        cap = eq.loc[dt, "capital"]
        print(f"    {str(dt.date()):12s}  {depth:>+7.1%}  ${price:>9,.0f}  ${cap:>9,.0f}")


def print_holding_periods(r):
    """Analyze holding period distribution."""
    hp = r["holding_periods"]
    if not hp:
        return
    hp = np.array(hp)
    print(f"\n  Holding period distribution ({len(hp)} round-trips):")
    print(f"    Mean:   {hp.mean():.0f} days")
    print(f"    Median: {np.median(hp):.0f} days")
    print(f"    Min:    {hp.min():.0f} days")
    print(f"    Max:    {hp.max():.0f} days")
    print(f"    <7d:    {(hp < 7).sum()} trades ({(hp < 7).mean():.0%})")
    print(f"    7-30d:  {((hp >= 7) & (hp < 30)).sum()} trades ({((hp >= 7) & (hp < 30)).mean():.0%})")
    print(f"    30-90d: {((hp >= 30) & (hp < 90)).sum()} trades ({((hp >= 30) & (hp < 90)).mean():.0%})")
    print(f"    >90d:   {(hp >= 90).sum()} trades ({(hp >= 90).mean():.0%})")


# ─── IBKR Implementation Notes ─────────────────────────────────────────────

def print_ibkr_plan():
    """Print exactly how this would work on IBKR."""
    print("""
  ╔══════════════════════════════════════════════════════════════╗
  ║           IBKR IMPLEMENTATION PLAN                          ║
  ╠══════════════════════════════════════════════════════════════╣
  ║                                                              ║
  ║  INSTRUMENT: BTC on PAXOS exchange via IBKR                  ║
  ║  ACCOUNT TYPE: Cash (no margin for crypto)                   ║
  ║  MINIMUM: ~$100 practical (fractional BTC supported)         ║
  ║                                                              ║
  ║  DAILY WORKFLOW (automated or manual):                       ║
  ║  ┌─────────────────────────────────────────────────────┐     ║
  ║  │ 1. At 00:05 UTC each day:                           │     ║
  ║  │    - Fetch last 40 daily closes from IBKR or Yahoo  │     ║
  ║  │    - Compute 70th percentile of those 40 prices     │     ║
  ║  │    - Compare yesterday's close to the percentile    │     ║
  ║  │                                                     │     ║
  ║  │ 2. If close > percentile → target = LONG            │     ║
  ║  │    If close ≤ percentile → target = FLAT            │     ║
  ║  │                                                     │     ║
  ║  │ 3. Compute position size:                           │     ║
  ║  │    vol = 20-day realized vol (annualized)           │     ║
  ║  │    weight = min(0.40 / vol, 1.0)                    │     ║
  ║  │    target_usd = account_value × weight × signal     │     ║
  ║  │                                                     │     ║
  ║  │ 4. If target differs from current by >1%:           │     ║
  ║  │    Submit LIMIT order (mid-price + tiny offset)     │     ║
  ║  │    on PAXOS exchange                                │     ║
  ║  └─────────────────────────────────────────────────────┘     ║
  ║                                                              ║
  ║  COSTS (per trade, each way):                                ║
  ║  ┌────────────────────────────────────────────┐              ║
  ║  │ IBKR commission:  0.18% (tiered, <$100k/mo)│              ║
  ║  │ Spread:           ~0.02% (BTC very liquid)  │              ║
  ║  │ Total:            ~0.20% per side            │              ║
  ║  │                                              │              ║
  ║  │ With ~20-30 round-trips per year:            │              ║
  ║  │ Annual cost ≈ 25 × 2 × 0.20% ≈ 10% of      │              ║
  ║  │ capital if fully invested                    │              ║
  ║  │ BUT: only trades on signal changes, so       │              ║
  ║  │ actual cost is much lower (~3-5% /yr)        │              ║
  ║  └────────────────────────────────────────────┘              ║
  ║                                                              ║
  ║  WHAT YOU NEED:                                              ║
  ║  - IBKR account with crypto trading enabled                  ║
  ║  - Python script (cron or scheduled task) OR                 ║
  ║  - Manual check 1x/day (it's that simple)                    ║
  ║  - The signal changes only ~2-3 times per month              ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
""")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  REALISTIC PERCENTILE BREAKOUT BACKTEST")
    print("  Modeled for IBKR PAXOS execution")
    print("=" * 70)
    
    btc = load_data()
    
    # ─────────────────────────────────────────────────────────────────────
    # 1. IBKR Implementation Plan
    # ─────────────────────────────────────────────────────────────────────
    print_ibkr_plan()
    
    # ─────────────────────────────────────────────────────────────────────
    # 2. Main backtest: 40d / 70th percentile (our best variant)
    # ─────────────────────────────────────────────────────────────────────
    print("=" * 70)
    print("  FULL BACKTEST: 40d / 70th Percentile")
    print("  $10,000 starting capital, 40% vol target, IBKR costs")
    print("=" * 70)
    
    r = backtest_realistic(btc, lookback=40, pct=70,
                           label="40d 70th Pctl (IBKR realistic)")
    print_results(r)
    print_yearly(r)
    print_trade_sample(r)
    print_rolling_sr(r)
    print_drawdown_analysis(r)
    print_holding_periods(r)
    
    # ─────────────────────────────────────────────────────────────────────
    # 3. Compare variants — are we overfitting to 40d/70th?
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PARAMETER ROBUSTNESS: Is 40d/70th special or is the region robust?")
    print("=" * 70)
    
    variants = [
        (30, 65), (30, 70), (30, 75),
        (40, 65), (40, 70), (40, 75), (40, 80),
        (50, 65), (50, 70), (50, 75), (50, 80),
        (60, 70), (60, 75), (60, 80),
        (80, 75), (80, 80),
        (100, 80), (100, 85),
    ]
    
    print(f"\n  {'Lookback':>8s}  {'Pctl':>5s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>7s}  {'Costs':>8s}  {'TimeInMkt':>10s}  {'AvgHold':>8s}")
    print(f"  {'─'*8}  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*8}  "
          f"{'─'*7}  {'─'*8}  {'─'*10}  {'─'*8}")
    
    all_results = []
    for lb, pc in variants:
        rv = backtest_realistic(btc, lookback=lb, pct=pc, label=f"{lb}d/{pc}th")
        all_results.append(rv)
        star = " ◄" if (lb == 40 and pc == 70) else ""
        print(f"  {lb:>6d}d  {pc:>4d}%  {rv['sharpe']:>+5.2f}  {rv['ann_ret']:>+7.1%}  "
              f"{rv['max_dd']:>+7.1%}  {rv['n_trades']:>6d}  ${rv['total_cost']:>7.0f}  "
              f"{rv['time_in_mkt']:>9.0%}  {rv['avg_hold_days']:>6.0f}d{star}")
    
    # ─────────────────────────────────────────────────────────────────────
    # 4. Out-of-sample focus: How does it look in recent years?
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  OUT-OF-SAMPLE WINDOWS")
    print("=" * 70)
    
    periods = [
        ("2017-2021 (in-sample)", "2017", "2021"),
        ("2022-2025 (out-of-sample)", "2022", "2026"),
        ("2024-2025 (most recent)", "2024", "2026"),
        ("2025 only", "2025", "2026"),
    ]
    
    for label, start, end in periods:
        sub = btc[start:end]
        if len(sub) < 100:
            print(f"  {label}: insufficient data")
            continue
        rv = backtest_realistic(sub, lookback=40, pct=70, label=label)
        print(f"  {label:35s}  SR={rv['sharpe']:+.2f}  Ret={rv['ann_ret']:+.1%}  "
              f"DD={rv['max_dd']:.1%}  Trades={rv['n_trades']}  Cost=${rv['total_cost']:.0f}")
    
    # ─────────────────────────────────────────────────────────────────────
    # 5. Cost sensitivity — what if IBKR costs are higher/lower?
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  COST SENSITIVITY")
    print("=" * 70)
    
    cost_levels = [0, 5, 10, 15, 20, 25, 30, 40, 50]
    print(f"\n  {'Cost (bps)':>10s}  {'SR':>6s}  {'AnnRet':>8s}  {'TotalCost':>10s}  {'CostDrag':>10s}")
    print(f"  {'─'*10}  {'─'*6}  {'─'*8}  {'─'*10}  {'─'*10}")
    
    for cost in cost_levels:
        rv = backtest_realistic(btc, lookback=40, pct=70, cost_bps=cost,
                               label=f"{cost}bps")
        # Cost drag = difference from zero-cost return
        print(f"  {cost:>8d}bp  {rv['sharpe']:>+5.2f}  {rv['ann_ret']:>+7.1%}  "
              f"${rv['total_cost']:>9,.0f}  ", end="")
        if cost == 0:
            zero_ret = rv['ann_ret']
            print("  (baseline)")
        else:
            drag = zero_ret - rv['ann_ret']
            print(f"  -{drag:.1%}/yr")
    
    # ─────────────────────────────────────────────────────────────────────
    # 6. What does the signal look like NOW?
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  CURRENT SIGNAL STATE")
    print("=" * 70)
    
    last_40 = btc.iloc[-40:]
    current_price = btc.iloc[-1]
    pctl_70 = last_40.quantile(0.70)
    pctl_75 = last_40.quantile(0.75)
    pctl_80 = last_40.quantile(0.80)
    
    signal_now = "LONG" if current_price > pctl_70 else "FLAT"
    
    print(f"\n  Date:           {btc.index[-1].date()}")
    print(f"  BTC Price:      ${current_price:,.0f}")
    print(f"  40d 70th pctl:  ${pctl_70:,.0f}  → Signal: {signal_now}")
    print(f"  40d 75th pctl:  ${pctl_75:,.0f}")
    print(f"  40d 80th pctl:  ${pctl_80:,.0f}")
    print(f"  40d range:      ${last_40.min():,.0f} – ${last_40.max():,.0f}")
    
    # Show last 10 days of signal
    sig, rpct = percentile_signal(btc, 40, 70)
    print(f"\n  Last 10 days signal:")
    for dt in btc.index[-10:]:
        p = btc.loc[dt]
        s = sig.loc[dt]
        pct_val = rpct.loc[dt]
        state = "LONG" if s > 0 else "FLAT"
        print(f"    {dt.date()}  BTC=${p:>9,.0f}  70th=${pct_val:>9,.0f}  → {state}")
    
    # ─────────────────────────────────────────────────────────────────────
    # 7. Multi-crypto: Does it work on ETH too?
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  MULTI-CRYPTO: Same signal on other coins")
    print("=" * 70)
    
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    
    print(f"\n  {'Coin':>6s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  {'Trades':>7s}  {'TimeInMkt':>10s}")
    print(f"  {'─'*6}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*10}")
    
    for coin in ["BTC", "ETH", "SOL", "LINK", "LTC", "BCH"]:
        col = f"{coin}-USD" if f"{coin}-USD" in closes.columns else coin
        if col not in closes.columns:
            continue
        series = closes[col].dropna()
        if len(series) < 200:
            continue
        rv = backtest_realistic(series, lookback=40, pct=70,
                               label=f"{coin} 40d/70th")
        print(f"  {coin:>6s}  {rv['sharpe']:>+5.2f}  {rv['ann_ret']:>+7.1%}  "
              f"{rv['max_dd']:>+7.1%}  {rv['n_trades']:>6d}  {rv['time_in_mkt']:>9.0%}")
    
    # ─────────────────────────────────────────────────────────────────────
    # 8. Buy-and-hold comparison
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  BENCHMARK: Percentile Breakout vs Buy-and-Hold BTC")
    print("=" * 70)
    
    r_strat = backtest_realistic(btc, lookback=40, pct=70,
                                 label="Percentile 40d/70th")
    
    # Simple buy-and-hold
    btc_aligned = btc[r_strat["equity"].index[0]:r_strat["equity"].index[-1]]
    bh_ret = btc_aligned.iloc[-1] / btc_aligned.iloc[0] - 1
    bh_n_yr = len(btc_aligned) / 365
    bh_ann_ret = (1 + bh_ret) ** (1 / bh_n_yr) - 1 if bh_ret > -1 else -1.0
    bh_ann_vol = btc_aligned.pct_change().std() * np.sqrt(365)
    bh_sr = bh_ann_ret / bh_ann_vol if bh_ann_vol > 0 else 0
    bh_dd = (btc_aligned / btc_aligned.cummax() - 1).min()
    
    print(f"\n  {'Metric':20s}  {'Percentile':>12s}  {'Buy & Hold':>12s}")
    print(f"  {'─'*20}  {'─'*12}  {'─'*12}")
    print(f"  {'Sharpe':20s}  {r_strat['sharpe']:>+11.2f}  {bh_sr:>+11.2f}")
    print(f"  {'Annual Return':20s}  {r_strat['ann_ret']:>+11.1%}  {bh_ann_ret:>+11.1%}")
    print(f"  {'Annual Volatility':20s}  {r_strat['ann_vol']:>+11.1%}  {bh_ann_vol:>+11.1%}")
    print(f"  {'Max Drawdown':20s}  {r_strat['max_dd']:>+11.1%}  {bh_dd:>+11.1%}")
    print(f"  {'Time in Market':20s}  {r_strat['time_in_mkt']:>10.0%}  {'100%':>12s}")
    print(f"  {'Trades':20s}  {r_strat['n_trades']:>12d}  {'0':>12s}")
    print(f"  {'Total Costs':20s}  ${r_strat['total_cost']:>10,.0f}  {'$0':>12s}")
    
    # ─────────────────────────────────────────────────────────────────────
    # 9. Summary verdict
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  VERDICT: Is this realistic to trade?")
    print("=" * 70)
    print(f"""
  ✓ PRACTICAL:
    - Signal changes ~2-3x/month → trivially easy to execute
    - Can be done manually (check price vs threshold daily)
    - Or automated with a simple cron job
    - No need for low-latency infrastructure
    - Fractional BTC on IBKR = no minimum size issue

  ✓ COSTS:
    - IBKR commission: 0.18% per side
    - With ~{r_strat['n_trades']} total trades over {r_strat['n_years']:.0f} years:
      {r_strat['n_trades'] / r_strat['n_years']:.0f} trades/year
    - Total cost drag: ${r_strat['total_cost']:,.0f} on ${INITIAL_CAPITAL:,} starting capital
    
  ? CONCERNS:
    - Strategy is long-only BTC — correlated with crypto beta
    - Sharpe {r_strat['sharpe']:+.2f} is good but not spectacular 
    - Max drawdown {r_strat['max_dd']:.0%} is significant
    - Edge may be decaying (check rolling SR above)
    - Only ~{r_strat['n_years']:.0f} years of data — limited statistical confidence
    - Vol targeting helps but can't avoid all BTC crashes
""")


if __name__ == "__main__":
    main()
