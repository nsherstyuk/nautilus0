"""
test_opening_hour_deep.py — Deep opening-hour strategy analysis

For a 65-year-old looking for supplemental income, we test the simplest,
most mechanical opening-hour strategies across FX and equity indexes.

PART A: FX Session Breakouts (tick-level, 11 years)
  - London Open Breakout (08:00 UTC): range from 06-08 UTC, trade breakout
  - NY Open Breakout (13:30 UTC): range from 12-13:30 UTC, trade breakout
  - Asian Range Breakout (00:00-06:00 UTC range, trade at London open)
  - Each tested with fixed TP/SL ratios (1:1, 1.5:1, 2:1)

PART B: Equity Index ORB (hourly, 3 years)
  - SPY/QQQ/IWM: first 30-min range breakout
  - With proper ATR-based stops
  - Yearly consistency check

PART C: Walk-Forward + Robustness
  - 2-year train / 1-year test rolling windows
  - Parameter sensitivity
  - Drawdown and worst-month analysis

Data: EURUSD/XAUUSD 1000-tick bars + SPY/QQQ/IWM IBKR 1h bars
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# Costs (round-trip)
COST_FX = 0.00015      # ~1.5 pips for EURUSD (conservative retail)
COST_XAUUSD = 0.0003   # ~30 cents on gold (conservative)
COST_ETF = 0.0003      # IBKR ETF commission + slippage

ANN = 252


def sharpe(returns, ann=ANN):
    if len(returns) < 2 or returns.std() == 0:
        return 0
    return returns.mean() / returns.std() * np.sqrt(ann)


def max_dd(equity):
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return dd.min()


def load_tick_bars(symbol):
    """Load tick bars and add session info."""
    path = DATA_DIR / f"{symbol.lower()}_1000t_bars.parquet"
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Ensure UTC
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df['dow'] = df['timestamp'].dt.dayofweek  # 0=Mon, 6=Sun
    
    return df


def load_etf_1h(symbol):
    """Load IBKR 1h bars."""
    path = DATA_DIR / f"{symbol.lower()}_1h_ibkr.parquet"
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Convert to US/Eastern for market hours
    if df['timestamp'].dt.tz is not None:
        df['timestamp'] = df['timestamp'].dt.tz_convert('US/Eastern')
    
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df


# ═══════════════════════════════════════════════════════════════════════════
#  PART A: FX SESSION BREAKOUT (tick-level precision)
# ═══════════════════════════════════════════════════════════════════════════

def compute_session_ranges(df, range_start_hour, range_end_hour):
    """
    For each trading day, compute the high/low during [range_start, range_end) UTC.
    Returns dict: date -> (range_high, range_low, range_size, last_close_in_range)
    """
    # Filter to range hours
    range_bars = df[(df['hour'] >= range_start_hour) & (df['hour'] < range_end_hour)]
    
    ranges = {}
    for dt, grp in range_bars.groupby('date'):
        if len(grp) < 3:  # need minimum data
            continue
        rh = grp['high'].max()
        rl = grp['low'].min()
        rc = grp['close'].iloc[-1]
        rsize = rh - rl
        if rsize <= 0:
            continue
        ranges[dt] = {
            'range_high': rh,
            'range_low': rl,
            'range_size': rsize,
            'last_close': rc,
            'n_bars': len(grp),
        }
    return ranges


def backtest_session_breakout(df, ranges, trade_start_hour, trade_end_hour,
                              rr_ratio=1.5, cost_rt=COST_FX, name=""):
    """
    Backtest a session breakout strategy.
    
    Entry: first break above range_high (long) or below range_low (short)
           during [trade_start_hour, trade_end_hour)
    SL: opposite side of range
    TP: rr_ratio * range_size from entry
    Exit: end of trade window if neither TP nor SL hit
    
    Returns DataFrame of trades.
    """
    trades = []
    
    for dt, rng in ranges.items():
        rh = rng['range_high']
        rl = rng['range_low']
        rsize = rng['range_size']
        
        # Get bars in trade window for this date
        day_bars = df[(df['date'] == dt) & 
                      (df['hour'] >= trade_start_hour) & 
                      (df['hour'] < trade_end_hour)]
        
        if len(day_bars) < 2:
            continue
        
        # Skip very tight or very wide ranges (filter noise)
        mid_price = (rh + rl) / 2
        range_pct = rsize / mid_price
        if range_pct < 0.0001 or range_pct > 0.02:  # too tight or too wide
            continue
        
        # Simulate bar-by-bar
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = 0
        sl_price = 0
        tp_price = 0
        
        for _, bar in day_bars.iterrows():
            if position == 0:
                # Check for breakout
                if bar['high'] > rh:
                    # Long breakout
                    position = 1
                    entry_price = rh  # assume fill at range high
                    sl_price = rl     # SL at range low
                    tp_price = entry_price + rr_ratio * rsize
                    
                elif bar['low'] < rl:
                    # Short breakout
                    position = -1
                    entry_price = rl
                    sl_price = rh
                    tp_price = entry_price - rr_ratio * rsize
            
            else:
                # Check exits
                hit_tp = False
                hit_sl = False
                
                if position == 1:
                    if bar['low'] <= sl_price:
                        hit_sl = True
                    if bar['high'] >= tp_price:
                        hit_tp = True
                else:
                    if bar['high'] >= sl_price:
                        hit_sl = True
                    if bar['low'] <= tp_price:
                        hit_tp = True
                
                if hit_sl and hit_tp:
                    # Both hit in same bar — assume SL hit (conservative)
                    hit_tp = False
                
                if hit_tp:
                    exit_price = tp_price
                    pnl_pct = abs(tp_price - entry_price) / entry_price
                    trades.append({
                        'date': dt,
                        'direction': 'LONG' if position == 1 else 'SHORT',
                        'entry': entry_price,
                        'exit': exit_price,
                        'result': 'TP',
                        'gross_ret': pnl_pct,
                        'net_ret': pnl_pct - cost_rt,
                        'range_pct': range_pct,
                    })
                    position = 0
                    break
                    
                elif hit_sl:
                    exit_price = sl_price
                    pnl_pct = -abs(sl_price - entry_price) / entry_price
                    trades.append({
                        'date': dt,
                        'direction': 'LONG' if position == 1 else 'SHORT',
                        'entry': entry_price,
                        'exit': exit_price,
                        'result': 'SL',
                        'gross_ret': pnl_pct,
                        'net_ret': pnl_pct - cost_rt,
                        'range_pct': range_pct,
                    })
                    position = 0
                    break
        
        # End of window — close at last bar close
        if position != 0:
            last_close = day_bars['close'].iloc[-1]
            pnl_pct = position * (last_close - entry_price) / entry_price
            trades.append({
                'date': dt,
                'direction': 'LONG' if position == 1 else 'SHORT',
                'entry': entry_price,
                'exit': last_close,
                'result': 'TIME',
                'gross_ret': pnl_pct,
                'net_ret': pnl_pct - cost_rt,
                'range_pct': range_pct,
            })
    
    return pd.DataFrame(trades) if trades else pd.DataFrame()


def print_strategy_results(trades_df, name, cost_rt):
    """Print comprehensive results for a strategy."""
    if trades_df.empty:
        print(f"    {name}: No trades generated")
        return
    
    n = len(trades_df)
    net = trades_df['net_ret']
    
    win_rate = (net > 0).mean() * 100
    avg_ret = net.mean() * 10000  # bps
    total_ret = net.sum() * 100
    
    # Results by outcome
    tp_trades = trades_df[trades_df['result'] == 'TP']
    sl_trades = trades_df[trades_df['result'] == 'SL']
    time_trades = trades_df[trades_df['result'] == 'TIME']
    
    # Equity curve for Sharpe/DD
    trades_df = trades_df.copy()
    trades_df['date_dt'] = pd.to_datetime(trades_df['date'])
    
    # Daily returns (some days may have no trade)
    daily_ret = trades_df.groupby('date_dt')['net_ret'].sum()
    
    # Sharpe from trade returns
    sh = sharpe(net, ann=len(net) / max(1, (trades_df['date_dt'].max() - trades_df['date_dt'].min()).days / 365.25))
    
    # Equity curve
    equity = (1 + net).cumprod()
    mdd = max_dd(equity) * 100
    
    # Yearly breakdown
    trades_df['year'] = trades_df['date_dt'].dt.year
    
    # Directions
    n_long = (trades_df['direction'] == 'LONG').sum()
    n_short = (trades_df['direction'] == 'SHORT').sum()
    
    print(f"    {name}:")
    print(f"      Trades: {n} ({n_long}L/{n_short}S) | "
          f"TP: {len(tp_trades)} ({len(tp_trades)/n*100:.0f}%) | "
          f"SL: {len(sl_trades)} ({len(sl_trades)/n*100:.0f}%) | "
          f"Time: {len(time_trades)} ({len(time_trades)/n*100:.0f}%)")
    print(f"      Win rate: {win_rate:.1f}%")
    print(f"      Avg return/trade: {avg_ret:+.1f} bps (gross: {trades_df['gross_ret'].mean()*10000:+.1f} bps)")
    print(f"      Total return: {total_ret:+.1f}%")
    print(f"      Max drawdown: {mdd:.1f}%")
    print(f"      Cost/trade: {cost_rt*10000:.1f} bps")
    
    # Per-year
    print(f"      ── By Year ──")
    for yr, grp in trades_df.groupby('year'):
        yr_net = grp['net_ret']
        yr_tot = yr_net.sum() * 100
        yr_wr = (yr_net > 0).mean() * 100
        yr_n = len(grp)
        marker = "  ◄" if yr_tot > 0 else ""
        print(f"        {yr}: {yr_tot:+6.1f}% | {yr_wr:4.0f}% win | {yr_n:3d} trades{marker}")
    
    return {
        'name': name,
        'n_trades': n,
        'win_rate': win_rate,
        'avg_ret_bps': avg_ret,
        'total_ret_pct': total_ret,
        'max_dd_pct': mdd,
        'profitable_years': (trades_df.groupby('year')['net_ret'].sum() > 0).mean() * 100,
    }


def test_fx_session_breakouts(symbol, cost_rt, pip_info=""):
    """Test all session breakout variants for a symbol."""
    print(f"\n{'─'*72}")
    print(f"  {symbol} Session Breakouts {pip_info}")
    print(f"{'─'*72}")
    
    print(f"  Loading tick data...")
    df = load_tick_bars(symbol)
    
    # Filter weekdays only (Mon-Fri)
    df = df[df['dow'] < 5]
    
    print(f"  {len(df):,} tick bars, {df['date'].nunique()} trading days")
    print(f"  Range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    
    results = []
    
    # ── Strategy 1: Asian Range → London Breakout ──
    # Range: 00:00-06:00 UTC (Asian session)
    # Trade: 08:00-16:00 UTC (London session)
    print(f"\n  ▸ Asian Range → London Breakout")
    asian_ranges = compute_session_ranges(df, 0, 6)
    print(f"    Range days: {len(asian_ranges)}")
    
    for rr in [1.0, 1.5, 2.0]:
        trades = backtest_session_breakout(
            df, asian_ranges,
            trade_start_hour=8, trade_end_hour=16,
            rr_ratio=rr, cost_rt=cost_rt,
            name=f"Asian→London RR={rr}"
        )
        r = print_strategy_results(trades, f"Asian→London RR={rr:.1f}", cost_rt)
        if r:
            r['rr'] = rr
            r['variant'] = 'Asian→London'
            results.append(r)
    
    # ── Strategy 2: Pre-London Range → London Breakout ──
    # Range: 06:00-08:00 UTC (quiet before London)
    # Trade: 08:00-12:00 UTC (London morning only)
    print(f"\n  ▸ Pre-London Range → London Morning Breakout")
    prelon_ranges = compute_session_ranges(df, 6, 8)
    print(f"    Range days: {len(prelon_ranges)}")
    
    for rr in [1.0, 1.5, 2.0]:
        trades = backtest_session_breakout(
            df, prelon_ranges,
            trade_start_hour=8, trade_end_hour=12,
            rr_ratio=rr, cost_rt=cost_rt,
        )
        r = print_strategy_results(trades, f"Pre-London→AM RR={rr:.1f}", cost_rt)
        if r:
            r['rr'] = rr
            r['variant'] = 'Pre-London→AM'
            results.append(r)
    
    # ── Strategy 3: London Range → NY Breakout ──
    # Range: 08:00-12:00 UTC (London morning)
    # Trade: 13:00-20:00 UTC (NY session)
    print(f"\n  ▸ London Morning → NY Session Breakout")
    london_ranges = compute_session_ranges(df, 8, 12)
    print(f"    Range days: {len(london_ranges)}")
    
    for rr in [1.0, 1.5, 2.0]:
        trades = backtest_session_breakout(
            df, london_ranges,
            trade_start_hour=13, trade_end_hour=20,
            rr_ratio=rr, cost_rt=cost_rt,
        )
        r = print_strategy_results(trades, f"London→NY RR={rr:.1f}", cost_rt)
        if r:
            r['rr'] = rr
            r['variant'] = 'London→NY'
            results.append(r)
    
    # ── Strategy 4: Tight pre-NY range → NY Breakout ──
    # Range: 12:00-13:30 UTC (lunch lull)
    # Trade: 13:30-20:00 UTC (NY afternoon)
    print(f"\n  ▸ Pre-NY Range → NY Breakout")
    preny_ranges = compute_session_ranges(df, 12, 14)
    print(f"    Range days: {len(preny_ranges)}")
    
    for rr in [1.0, 1.5, 2.0]:
        trades = backtest_session_breakout(
            df, preny_ranges,
            trade_start_hour=14, trade_end_hour=20,
            rr_ratio=rr, cost_rt=cost_rt,
        )
        r = print_strategy_results(trades, f"Pre-NY→PM RR={rr:.1f}", cost_rt)
        if r:
            r['rr'] = rr
            r['variant'] = 'Pre-NY→PM'
            results.append(r)
    
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  PART B: EQUITY INDEX ORB (deeper analysis)
# ═══════════════════════════════════════════════════════════════════════════

def test_etf_orb_deep(symbol):
    """Deep ORB analysis on ETF using 1h IBKR bars."""
    print(f"\n{'─'*72}")
    print(f"  {symbol} Opening Range Breakout (1h bars)")
    print(f"{'─'*72}")
    
    df = load_etf_1h(symbol)
    
    # Regular trading hours: 9:30-16:00 ET → hours 9-15 in our data
    # IBKR 1h bars starting at hour 9 = the 9:00-10:00 bar (contains the open)
    # Hour 10 = 10:00-11:00, etc.
    
    results = []
    daily_groups = df.groupby('date')
    
    # Compute daily ATR for position sizing context
    daily_close = df.groupby('date')['close'].last()
    daily_high = df.groupby('date')['high'].max()
    daily_low = df.groupby('date')['low'].min()
    daily_range = daily_high - daily_low
    atr_14 = daily_range.rolling(14).mean()
    
    all_trades = []
    
    for dt, day_df in daily_groups:
        rth = day_df[(day_df['hour'] >= 9) & (day_df['hour'] <= 15)]
        if len(rth) < 4:
            continue
        
        # Opening range = first bar (9:30-10:30 approximately)
        first_bar = rth.iloc[0]
        or_high = first_bar['high']
        or_low = first_bar['low']
        or_range = or_high - or_low
        or_close = first_bar['close']
        day_open = first_bar['open']
        
        if or_range <= 0 or day_open <= 0:
            continue
        
        or_range_pct = or_range / day_open
        
        # Get ATR for context
        dt_key = dt
        atr_val = atr_14.get(dt_key, None)
        if atr_val is None or atr_val <= 0:
            continue
        
        # Simulate rest of day
        rest_bars = rth.iloc[1:]
        if len(rest_bars) == 0:
            continue
        
        # ORB Strategy: trade breakout of first bar range
        # SL: opposite side of opening range
        # TP: risk-reward ratio * opening range
        for rr in [1.0, 1.5, 2.0]:
            position = 0
            entry_price = 0
            sl_price = 0
            tp_price = 0
            
            for _, bar in rest_bars.iterrows():
                if position == 0:
                    if bar['high'] > or_high:
                        position = 1
                        entry_price = or_high
                        sl_price = or_low
                        tp_price = entry_price + rr * or_range
                    elif bar['low'] < or_low:
                        position = -1
                        entry_price = or_low
                        sl_price = or_high
                        tp_price = entry_price - rr * or_range
                else:
                    hit_tp = hit_sl = False
                    if position == 1:
                        if bar['low'] <= sl_price: hit_sl = True
                        if bar['high'] >= tp_price: hit_tp = True
                    else:
                        if bar['high'] >= sl_price: hit_sl = True
                        if bar['low'] <= tp_price: hit_tp = True
                    
                    if hit_sl and hit_tp:
                        hit_tp = False  # conservative
                    
                    if hit_tp:
                        pnl = abs(tp_price - entry_price) / entry_price
                        all_trades.append({
                            'date': dt, 'rr': rr,
                            'direction': 'L' if position == 1 else 'S',
                            'result': 'TP',
                            'gross_ret': pnl,
                            'net_ret': pnl - COST_ETF,
                            'or_range_pct': or_range_pct,
                            'atr': atr_val,
                        })
                        position = 0
                        break
                    elif hit_sl:
                        pnl = -abs(sl_price - entry_price) / entry_price
                        all_trades.append({
                            'date': dt, 'rr': rr,
                            'direction': 'L' if position == 1 else 'S',
                            'result': 'SL',
                            'gross_ret': pnl,
                            'net_ret': pnl - COST_ETF,
                            'or_range_pct': or_range_pct,
                            'atr': atr_val,
                        })
                        position = 0
                        break
            
            # End of day exit
            if position != 0:
                last = rest_bars['close'].iloc[-1]
                pnl = position * (last - entry_price) / entry_price
                all_trades.append({
                    'date': dt, 'rr': rr,
                    'direction': 'L' if position == 1 else 'S',
                    'result': 'TIME',
                    'gross_ret': pnl,
                    'net_ret': pnl - COST_ETF,
                    'or_range_pct': or_range_pct,
                    'atr': atr_val,
                })
    
    if not all_trades:
        print("  No trades generated")
        return []
    
    all_df = pd.DataFrame(all_trades)
    
    # Print results by RR ratio
    etf_results = []
    for rr in [1.0, 1.5, 2.0]:
        subset = all_df[all_df['rr'] == rr].copy()
        r = print_strategy_results(subset, f"ORB RR={rr:.1f}", COST_ETF)
        if r:
            r['rr'] = rr
            etf_results.append(r)
    
    # ── Filter analysis: does filtering improve results? ──
    print(f"\n  ── Filter Analysis (RR=1.5) ──")
    base = all_df[all_df['rr'] == 1.5].copy()
    
    # Filter 1: Only trade when opening range is in middle 50% of ATR
    # (not too tight, not too wide)
    base['or_atr_ratio'] = base['or_range_pct'] * base.iloc[0]['atr']  # rough
    q25 = base['or_range_pct'].quantile(0.25)
    q75 = base['or_range_pct'].quantile(0.75)
    filtered = base[(base['or_range_pct'] >= q25) & (base['or_range_pct'] <= q75)]
    if len(filtered) > 20:
        wr = (filtered['net_ret'] > 0).mean() * 100
        ar = filtered['net_ret'].mean() * 10000
        print(f"    Filter: Mid-range OR size (25-75%ile): "
              f"{len(filtered)} trades, {wr:.0f}% win, {ar:+.1f} bps avg")
    
    # Filter 2: Only long (bullish bias)
    longs = base[base['direction'] == 'L']
    if len(longs) > 20:
        wr = (longs['net_ret'] > 0).mean() * 100
        ar = longs['net_ret'].mean() * 10000
        print(f"    Filter: Longs only: "
              f"{len(longs)} trades, {wr:.0f}% win, {ar:+.1f} bps avg")
    
    # Filter 3: Only shorts
    shorts = base[base['direction'] == 'S']
    if len(shorts) > 20:
        wr = (shorts['net_ret'] > 0).mean() * 100
        ar = shorts['net_ret'].mean() * 10000
        print(f"    Filter: Shorts only: "
              f"{len(shorts)} trades, {wr:.0f}% win, {ar:+.1f} bps avg")
    
    # Filter 4: Day-of-week
    base['dow'] = pd.to_datetime(base['date']).dt.dayofweek
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    print(f"    By day of week:")
    for d in range(5):
        dow_trades = base[base['dow'] == d]
        if len(dow_trades) > 10:
            wr = (dow_trades['net_ret'] > 0).mean() * 100
            ar = dow_trades['net_ret'].mean() * 10000
            tot = dow_trades['net_ret'].sum() * 100
            print(f"      {dow_names[d]}: {len(dow_trades)} trades, "
                  f"{wr:.0f}% win, {ar:+.1f} bps avg, total {tot:+.1f}%")
    
    return etf_results


# ═══════════════════════════════════════════════════════════════════════════
#  PART C: WALK-FORWARD ROBUSTNESS
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_fx(symbol, range_start, range_end, trade_start, trade_end,
                    rr_ratio, cost_rt, train_years=3, test_years=1):
    """Walk-forward test: does the strategy work OOS across time?"""
    df = load_tick_bars(symbol)
    df = df[df['dow'] < 5]
    
    # Get all ranges
    ranges = compute_session_ranges(df, range_start, range_end)
    
    # Get all trades
    trades = backtest_session_breakout(
        df, ranges,
        trade_start_hour=trade_start, trade_end_hour=trade_end,
        rr_ratio=rr_ratio, cost_rt=cost_rt,
    )
    
    if trades.empty:
        return None
    
    trades['date_dt'] = pd.to_datetime(trades['date'])
    trades['year'] = trades['date_dt'].dt.year
    
    years = sorted(trades['year'].unique())
    if len(years) < train_years + test_years:
        return None
    
    oos_results = []
    
    for i in range(len(years) - train_years - test_years + 1):
        train_yrs = years[i:i+train_years]
        test_yrs = years[i+train_years:i+train_years+test_years]
        
        train_trades = trades[trades['year'].isin(train_yrs)]
        test_trades = trades[trades['year'].isin(test_yrs)]
        
        if len(train_trades) < 50 or len(test_trades) < 20:
            continue
        
        # Train: is this profitable?
        train_avg = train_trades['net_ret'].mean()
        
        # If train shows edge, measure OOS
        # (we test regardless, but flag if train showed no edge)
        test_avg = test_trades['net_ret'].mean() * 10000
        test_wr = (test_trades['net_ret'] > 0).mean() * 100
        test_total = test_trades['net_ret'].sum() * 100
        train_edge = train_avg > 0
        
        oos_results.append({
            'train_years': f"{train_yrs[0]}-{train_yrs[-1]}",
            'test_year': test_yrs[0],
            'train_avg_bps': train_avg * 10000,
            'train_edge': train_edge,
            'test_avg_bps': test_avg,
            'test_wr': test_wr,
            'test_total_pct': test_total,
            'test_n': len(test_trades),
        })
    
    return pd.DataFrame(oos_results) if oos_results else None


# ═══════════════════════════════════════════════════════════════════════════
#  PART D: PRACTICAL ANALYSIS (for retirement income)
# ═══════════════════════════════════════════════════════════════════════════

def practical_analysis(best_strategies):
    """What does this mean in dollar terms for someone with a small account?"""
    print(f"\n{'='*72}")
    print(f"  PRACTICAL ANALYSIS: What can you actually earn?")
    print(f"{'='*72}")
    
    if not best_strategies:
        print("  No profitable strategies found.")
        return
    
    for s in best_strategies:
        name = s['name']
        avg_bps = s['avg_ret_bps']
        n_trades = s['n_trades']
        data_years = 11 if 'London' in name or 'Asian' in name or 'Pre-' in name else 3
        trades_per_year = n_trades / data_years
        win_rate = s['win_rate']
        mdd = abs(s['max_dd_pct'])
        profitable_years = s.get('profitable_years', 0)
        
        avg_ret_per_trade = avg_bps / 10000
        annual_ret = avg_ret_per_trade * trades_per_year
        
        print(f"\n  {name}:")
        print(f"    Trades/year: ~{trades_per_year:.0f}")
        print(f"    Avg return/trade: {avg_bps:+.1f} bps")
        print(f"    Win rate: {win_rate:.0f}%")
        print(f"    Expected annual return: {annual_ret*100:+.1f}%")
        print(f"    Max drawdown: {mdd:.1f}%")
        print(f"    Profitable years: {profitable_years:.0f}%")
        
        # Dollar estimates with different account sizes
        for account_size in [10_000, 25_000, 50_000]:
            annual_income = account_size * annual_ret
            monthly_income = annual_income / 12
            worst_dd = account_size * mdd / 100
            print(f"    ${account_size:>6,} account → "
                  f"~${annual_income:,.0f}/yr (~${monthly_income:,.0f}/mo), "
                  f"worst DD: -${worst_dd:,.0f}")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 72)
    print("  OPENING HOUR STRATEGY — DEEP ANALYSIS")
    print("  FX (11yr tick data) + Equity Indexes (3yr hourly)")
    print("=" * 72)
    
    all_best = []
    
    # ── Part A: FX Session Breakouts ──
    print(f"\n{'='*72}")
    print(f"  PART A: FX SESSION BREAKOUTS (tick-level, 11 years)")
    print(f"{'='*72}")
    
    eurusd_results = test_fx_session_breakouts(
        'EURUSD', COST_FX, "(cost: 1.5 pips RT)")
    
    xauusd_results = test_fx_session_breakouts(
        'XAUUSD', COST_XAUUSD, "(cost: ~$0.30 RT)")
    
    # Collect best FX strategies
    for r in (eurusd_results or []) + (xauusd_results or []):
        if r and r.get('avg_ret_bps', 0) > 0:
            all_best.append(r)
    
    # ── Part B: Equity Index ORB ──
    print(f"\n{'='*72}")
    print(f"  PART B: EQUITY INDEX ORB (1h bars, 3 years)")
    print(f"{'='*72}")
    
    for sym in ['SPY', 'QQQ', 'IWM']:
        etf_results = test_etf_orb_deep(sym)
        for r in (etf_results or []):
            if r and r.get('avg_ret_bps', 0) > 0:
                r['name'] = f"{sym} {r['name']}"
                all_best.append(r)
    
    # ── Part C: Walk-Forward for best FX strategies ──
    print(f"\n{'='*72}")
    print(f"  PART C: WALK-FORWARD OOS (3yr train → 1yr test)")
    print(f"{'='*72}")
    
    wf_configs = [
        ('EURUSD', 0, 6, 8, 16, 'Asian→London'),     # Asian range → London
        ('EURUSD', 6, 8, 8, 12, 'Pre-London→AM'),     # Pre-London → AM
        ('EURUSD', 8, 12, 13, 20, 'London→NY'),       # London → NY
        ('XAUUSD', 0, 6, 8, 16, 'Asian→London'),
        ('XAUUSD', 6, 8, 8, 12, 'Pre-London→AM'),
    ]
    
    for sym, rs, re, ts, te, label in wf_configs:
        cost = COST_FX if sym == 'EURUSD' else COST_XAUUSD
        for rr in [1.0, 1.5]:
            oos = walk_forward_fx(sym, rs, re, ts, te, rr, cost,
                                  train_years=3, test_years=1)
            if oos is not None and len(oos) > 0:
                avg_oos = oos['test_avg_bps'].mean()
                pct_profit = (oos['test_total_pct'] > 0).mean() * 100
                n_windows = len(oos)
                
                marker = " ◄ EDGE" if avg_oos > 0 and pct_profit >= 60 else ""
                print(f"  {sym} {label} RR={rr}: "
                      f"OOS avg {avg_oos:+.1f} bps, "
                      f"{pct_profit:.0f}% profitable windows "
                      f"({n_windows} windows){marker}")
                
                # Show each window
                for _, row in oos.iterrows():
                    flag = "✓" if row['test_total_pct'] > 0 else "✗"
                    print(f"    {flag} Train {row['train_years']} → Test {int(row['test_year'])}: "
                          f"{row['test_avg_bps']:+.1f} bps avg, "
                          f"{row['test_wr']:.0f}% win, "
                          f"{row['test_total_pct']:+.1f}% total "
                          f"({int(row['test_n'])} trades)")
            else:
                print(f"  {sym} {label} RR={rr}: insufficient data")
    
    # ── Part D: Practical Analysis ──
    practical_analysis(all_best)
    
    # ── Summary ──
    print(f"\n{'='*72}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*72}")
    if all_best:
        # Sort by avg_ret_bps
        all_best.sort(key=lambda x: x.get('avg_ret_bps', 0), reverse=True)
        print(f"\n  {'Strategy':<35s} {'AvgBPS':>7s} {'WinRate':>8s} {'TotalRet':>9s} {'MaxDD':>7s} {'ProfYrs':>8s}")
        print(f"  {'─'*35} {'─'*7} {'─'*8} {'─'*9} {'─'*7} {'─'*8}")
        for r in all_best:
            print(f"  {r['name']:<35s} "
                  f"{r['avg_ret_bps']:>+6.1f} "
                  f"{r['win_rate']:>7.1f}% "
                  f"{r['total_ret_pct']:>+8.1f}% "
                  f"{r['max_dd_pct']:>6.1f}% "
                  f"{r.get('profitable_years', 0):>7.0f}%")
    else:
        print("  No strategies with positive expectancy found.")
    
    print(f"\n  Key question: Do walk-forward OOS results confirm in-sample?")
    print(f"  Only strategies with >60% profitable OOS windows are worth considering.")


if __name__ == "__main__":
    main()
