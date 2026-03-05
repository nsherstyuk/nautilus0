"""
test_orb_and_pairs.py — Two final intraday approaches

Part 1: Opening Range Breakout (ORB) & Opening Techniques
  - ORB: first 30/60 min high/low → trade breakout in direction
  - Opening reversal: fade the first bar
  - Gap open strategies (refined from prior test)
  - MOO advantage: buy at open vs close

Part 2: Statistical Arbitrage / Pairs Trading
  - Cointegrated pairs: SPY/QQQ, TLT/IEF, SPY/IWM
  - Z-score mean reversion on spread
  - Bollinger band spread trading
  - Walk-forward cointegration test

Data: IBKR 1h bars (~3 years, 10 ETFs) + yfinance 1h bars
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
ANN = 252
ANN_H = 252 * 7  # ~7 trading hours/day for ETFs
COST_RT = 0.0003  # 0.03% IBKR ETFs


def sharpe(r, af=ANN):
    return r.mean() / (r.std() + 1e-10) * np.sqrt(af)

def max_dd(eq):
    return ((eq - eq.cummax()) / eq.cummax()).min()


def load_ibkr_data():
    """Load all IBKR 1h data into a dict of DataFrames."""
    symbols = ['SPY', 'TLT', 'GLD', 'VNQ', 'QQQ', 'IWM', 'EFA', 'EEM', 'IEF', 'DBC']
    data = {}
    for sym in symbols:
        path = DATA_DIR / f"{sym.lower()}_1h_ibkr.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        # Ensure numeric
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        data[sym] = df
    return data


# ══════════════════════════════════════════════════════════════════════════════
#  PART 1: OPENING RANGE BREAKOUT & OPENING TECHNIQUES
# ══════════════════════════════════════════════════════════════════════════════

def test_opening_techniques(data: dict):
    print("=" * 72)
    print("  PART 1: OPENING RANGE BREAKOUT & OPENING TECHNIQUES")
    print("=" * 72)

    for sym in ['SPY', 'QQQ', 'GLD', 'IWM']:
        if sym not in data:
            continue

        df = data[sym].copy()
        if df.empty:
            continue

        # Convert to US/Eastern if needed for proper market hours
        if df.index.tz is not None:
            df.index = df.index.tz_convert('US/Eastern')
        
        # Filter to regular trading hours (9:30-16:00 ET)
        # IBKR 1h bars: 9:30 bar = hour starting at 9:30
        # Typically hours 9, 10, 11, 12, 13, 14, 15 (close at 16:00)
        df['hour'] = df.index.hour
        df['date'] = df.index.date

        # Group by date
        daily_groups = df.groupby('date')

        # Strategy results
        orb_results = []  # Opening Range Breakout
        fade_results = []  # First bar fade (reversal)
        gap_results = []  # Gap strategies
        follow_results = []  # First bar follow (momentum)

        prev_day_close = None

        for dt, day_df in daily_groups:
            # Filter to RTH only (hour 9-15 for 1h bars)
            rth = day_df[(day_df['hour'] >= 9) & (day_df['hour'] <= 15)]
            if len(rth) < 4:
                continue

            day_open = rth['open'].iloc[0]
            day_close = rth['close'].iloc[-1]
            first_bar_high = rth['high'].iloc[0]
            first_bar_low = rth['low'].iloc[0]
            first_bar_close = rth['close'].iloc[0]
            first_bar_ret = (first_bar_close / day_open - 1) if day_open > 0 else 0

            # Rest of day return (after first bar)
            if len(rth) >= 2:
                rest_open = rth['open'].iloc[1]
                rest_close = rth['close'].iloc[-1]
                rest_ret = (rest_close / rest_open - 1) if rest_open > 0 else 0
            else:
                rest_ret = 0

            # Full day return
            full_ret = (day_close / day_open - 1) if day_open > 0 else 0

            # ── ORB: Opening Range Breakout ──
            # Use first bar high/low as the "opening range"
            # If price breaks above first bar high → go long rest of day
            # If price breaks below first bar low → go short rest of day
            if len(rth) >= 2:
                broke_high = any(rth['high'].iloc[1:] > first_bar_high)
                broke_low = any(rth['low'].iloc[1:] < first_bar_low)

                if broke_high and not broke_low:
                    # Long breakout
                    orb_results.append({
                        'date': dt,
                        'direction': 'LONG',
                        'entry': first_bar_high,
                        'exit': day_close,
                        'ret': (day_close / first_bar_high - 1),
                    })
                elif broke_low and not broke_high:
                    # Short breakout
                    orb_results.append({
                        'date': dt,
                        'direction': 'SHORT',
                        'entry': first_bar_low,
                        'exit': day_close,
                        'ret': (first_bar_low / day_close - 1),
                    })
                elif broke_high and broke_low:
                    # Both broken — skip (choppy day)
                    # Or take first break direction
                    # Find which broke first
                    first_break_up = None
                    first_break_dn = None
                    for i in range(1, len(rth)):
                        if first_break_up is None and rth['high'].iloc[i] > first_bar_high:
                            first_break_up = i
                        if first_break_dn is None and rth['low'].iloc[i] < first_bar_low:
                            first_break_dn = i

                    if first_break_up is not None and (first_break_dn is None or first_break_up < first_break_dn):
                        orb_results.append({
                            'date': dt, 'direction': 'LONG',
                            'entry': first_bar_high, 'exit': day_close,
                            'ret': (day_close / first_bar_high - 1),
                        })
                    elif first_break_dn is not None:
                        orb_results.append({
                            'date': dt, 'direction': 'SHORT',
                            'entry': first_bar_low, 'exit': day_close,
                            'ret': (first_bar_low / day_close - 1),
                        })

            # ── First bar FADE (mean reversion) ──
            # If first bar is UP → go SHORT rest of day
            # If first bar is DOWN → go LONG rest of day
            if abs(first_bar_ret) > 0.001:  # filter tiny moves
                fade_ret = -np.sign(first_bar_ret) * rest_ret
                fade_results.append({
                    'date': dt,
                    'first_bar_ret': first_bar_ret,
                    'rest_ret': rest_ret,
                    'strategy_ret': fade_ret,
                })

            # ── First bar FOLLOW (momentum) ──
            if abs(first_bar_ret) > 0.001:
                follow_ret = np.sign(first_bar_ret) * rest_ret
                follow_results.append({
                    'date': dt,
                    'first_bar_ret': first_bar_ret,
                    'rest_ret': rest_ret,
                    'strategy_ret': follow_ret,
                })

            # ── Gap strategies ──
            if prev_day_close is not None and prev_day_close > 0:
                gap = (day_open / prev_day_close - 1)
                if abs(gap) > 0.002:  # >0.2% gap
                    # Gap fade: short if gap up, long if gap down
                    gap_fade_ret = -np.sign(gap) * full_ret
                    # Gap follow: long if gap up, short if gap down
                    gap_follow_ret = np.sign(gap) * full_ret
                    gap_results.append({
                        'date': dt,
                        'gap_pct': gap,
                        'day_ret': full_ret,
                        'fade_ret': gap_fade_ret,
                        'follow_ret': gap_follow_ret,
                    })

            prev_day_close = day_close

        # Print results
        print(f"\n  ── {sym} ──")

        # ORB
        if orb_results:
            orb_df = pd.DataFrame(orb_results)
            orb_net = orb_df['ret'] - COST_RT  # cost per trade
            win_rate = (orb_net > 0).mean() * 100
            avg_ret = orb_net.mean() * 10000  # in bps
            total_ret = orb_net.sum() * 100
            n_long = (orb_df['direction'] == 'LONG').sum()
            n_short = (orb_df['direction'] == 'SHORT').sum()

            print(f"    ORB (Opening Range Breakout):")
            print(f"      Trades: {len(orb_df)} ({n_long}L/{n_short}S)")
            print(f"      Win rate: {win_rate:.1f}%")
            print(f"      Avg return/trade: {avg_ret:+.1f} bps")
            print(f"      Total return: {total_ret:+.2f}%")
            print(f"      Sharpe (daily): {sharpe(orb_net):+.3f}")
            
            # By year
            orb_df['year'] = pd.to_datetime(orb_df['date']).dt.year
            orb_df['net_ret'] = orb_net.values
            for yr, grp in orb_df.groupby('year'):
                yr_tot = grp['net_ret'].sum() * 100
                yr_wr = (grp['net_ret'] > 0).mean() * 100
                print(f"        {yr}: {yr_tot:+.1f}% ({yr_wr:.0f}% win, {len(grp)} trades)")

        # Fade
        if fade_results:
            fade_df = pd.DataFrame(fade_results)
            fade_net = fade_df['strategy_ret'] - COST_RT
            print(f"\n    First Bar FADE (mean reversion):")
            print(f"      Trades: {len(fade_df)}")
            print(f"      Win rate: {(fade_net > 0).mean()*100:.1f}%")
            print(f"      Avg return/trade: {fade_net.mean()*10000:+.1f} bps")
            print(f"      Total return: {fade_net.sum()*100:+.2f}%")

        # Follow
        if follow_results:
            follow_df = pd.DataFrame(follow_results)
            follow_net = follow_df['strategy_ret'] - COST_RT
            print(f"\n    First Bar FOLLOW (momentum):")
            print(f"      Trades: {len(follow_df)}")
            print(f"      Win rate: {(follow_net > 0).mean()*100:.1f}%")
            print(f"      Avg return/trade: {follow_net.mean()*10000:+.1f} bps")
            print(f"      Total return: {follow_net.sum()*100:+.2f}%")

        # Gap
        if gap_results:
            gap_df = pd.DataFrame(gap_results)
            fade_net = gap_df['fade_ret'] - COST_RT
            follow_net = gap_df['follow_ret'] - COST_RT
            print(f"\n    Gap FADE (>0.2% gaps only, n={len(gap_df)}):")
            print(f"      Win rate: {(fade_net > 0).mean()*100:.1f}%")
            print(f"      Avg return/trade: {fade_net.mean()*10000:+.1f} bps")
            print(f"      Total return: {fade_net.sum()*100:+.2f}%")
            print(f"    Gap FOLLOW:")
            print(f"      Win rate: {(follow_net > 0).mean()*100:.1f}%")
            print(f"      Avg return/trade: {follow_net.mean()*10000:+.1f} bps")
            print(f"      Total return: {follow_net.sum()*100:+.2f}%")

            # Big gaps only
            big = gap_df[gap_df['gap_pct'].abs() > 0.005]
            if len(big) > 0:
                big_fade = big['fade_ret'] - COST_RT
                print(f"    Gap FADE (>0.5% only, n={len(big)}):")
                print(f"      Win rate: {(big_fade > 0).mean()*100:.1f}%")
                print(f"      Avg return/trade: {big_fade.mean()*10000:+.1f} bps")


# ══════════════════════════════════════════════════════════════════════════════
#  PART 2: STATISTICAL ARBITRAGE / PAIRS TRADING
# ══════════════════════════════════════════════════════════════════════════════

def test_cointegration(s1, s2, name1, name2):
    """Test for cointegration between two price series."""
    from scipy.stats import linregress

    # Align
    common = pd.concat([s1, s2], axis=1).dropna()
    if len(common) < 200:
        return None

    x = common.iloc[:, 1].values
    y = common.iloc[:, 0].values

    # OLS regression: y = beta*x + alpha + epsilon
    slope, intercept, r_value, p_value, std_err = linregress(x, y)

    # Spread = y - beta*x
    spread = y - slope * x
    spread_series = pd.Series(spread, index=common.index)

    # ADF test on spread (simple version)
    # Test if spread is stationary
    n = len(spread)
    lag_spread = spread[:-1]
    diff_spread = np.diff(spread)
    slope_adf, intercept_adf, _, p_adf, _ = linregress(lag_spread, diff_spread)

    # Heuristic: if slope_adf < 0 and significant, spread is mean-reverting
    t_stat = slope_adf / (std_err + 1e-10)
    half_life = -np.log(2) / slope_adf if slope_adf < 0 else 9999

    return {
        'name': f"{name1}/{name2}",
        'hedge_ratio': slope,
        'correlation': r_value,
        'spread_std': spread_series.std(),
        'spread_mean': spread_series.mean(),
        'adf_slope': slope_adf,
        'half_life': half_life,
        'spread': spread_series,
        'prices1': common.iloc[:, 0],
        'prices2': common.iloc[:, 1],
    }


def pairs_trading_backtest(spread, prices1, prices2, hedge_ratio, name,
                           entry_z=2.0, exit_z=0.5, max_hold_bars=50):
    """Backtest pairs trading on hourly spread."""
    # Rolling z-score
    lookback = 100  # ~2 weeks of hourly bars
    spread_mean = spread.rolling(lookback).mean()
    spread_std = spread.rolling(lookback).std()
    zscore = (spread - spread_mean) / (spread_std + 1e-10)

    position = 0  # +1 = long spread, -1 = short spread
    entry_price1 = 0
    entry_price2 = 0
    hold_count = 0
    trades = []

    for i in range(lookback, len(spread)):
        z = zscore.iloc[i]
        p1 = prices1.iloc[i]
        p2 = prices2.iloc[i]

        if position == 0:
            # Entry
            if z > entry_z:
                # Spread too high → short spread (sell asset1, buy asset2)
                position = -1
                entry_price1 = p1
                entry_price2 = p2
                hold_count = 0
            elif z < -entry_z:
                # Spread too low → long spread (buy asset1, sell asset2)
                position = 1
                entry_price1 = p1
                entry_price2 = p2
                hold_count = 0
        else:
            hold_count += 1
            # Exit conditions
            should_exit = False

            if position == 1 and z > -exit_z:
                should_exit = True  # spread reverted
            elif position == -1 and z < exit_z:
                should_exit = True  # spread reverted
            elif hold_count >= max_hold_bars:
                should_exit = True  # timeout

            if should_exit:
                # PnL: position * (spread change)
                # Long spread: buy asset1, sell hedge_ratio * asset2
                ret1 = (p1 / entry_price1 - 1) * position
                ret2 = (p2 / entry_price2 - 1) * (-position) * hedge_ratio

                # Scale to roughly equal dollar amounts
                ret_total = (ret1 + ret2) / (1 + abs(hedge_ratio))

                trades.append({
                    'entry_idx': i - hold_count,
                    'exit_idx': i,
                    'hold_bars': hold_count,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_z': zscore.iloc[i - hold_count],
                    'exit_z': z,
                    'gross_ret': ret_total,
                    'net_ret': ret_total - 2 * COST_RT,  # cost on both legs, entry + exit
                })
                position = 0

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def test_pairs_trading(data: dict):
    print(f"\n{'='*72}")
    print("  PART 2: STATISTICAL ARBITRAGE / PAIRS TRADING")
    print("="*72)

    # Build close price matrix
    closes = {}
    for sym in ['SPY', 'QQQ', 'IWM', 'TLT', 'IEF', 'GLD', 'EFA', 'EEM', 'VNQ', 'DBC']:
        if sym in data:
            closes[sym] = data[sym]['close']

    close_df = pd.DataFrame(closes).ffill().dropna()
    print(f"  Hourly data: {len(close_df):,} bars, "
          f"{close_df.index[0]} → {close_df.index[-1]}")

    # ── Cointegration scan ──
    pairs = [
        ('SPY', 'QQQ'),    # equity large cap
        ('SPY', 'IWM'),    # large vs small cap
        ('QQQ', 'IWM'),    # tech vs small cap
        ('TLT', 'IEF'),    # long vs medium bonds
        ('SPY', 'EFA'),    # US vs international
        ('EFA', 'EEM'),    # developed vs emerging
        ('GLD', 'DBC'),    # gold vs broad commodities
        ('SPY', 'VNQ'),    # equity vs REITs
        ('TLT', 'GLD'),    # bonds vs gold (safe havens)
    ]

    print(f"\n  ── Cointegration Scan ──")
    print(f"    {'Pair':<15s} {'Corr':>6s} {'Hedge':>7s} {'HalfLife':>10s} {'SpreadStd':>10s} {'Mean-Rev?':>10s}")
    print(f"    {'─'*15} {'─'*6} {'─'*7} {'─'*10} {'─'*10} {'─'*10}")

    coint_results = []
    for s1, s2 in pairs:
        if s1 not in close_df.columns or s2 not in close_df.columns:
            continue
        result = test_cointegration(close_df[s1], close_df[s2], s1, s2)
        if result is None:
            continue

        mr = "YES" if 5 < result['half_life'] < 200 else "NO"
        print(f"    {result['name']:<15s} "
              f"{result['correlation']:>+5.3f} "
              f"{result['hedge_ratio']:>6.3f} "
              f"{result['half_life']:>9.1f}h "
              f"{result['spread_std']:>9.2f} "
              f"{mr:>10s}")

        if 5 < result['half_life'] < 200:
            coint_results.append(result)

    # ── Backtest best pairs ──
    print(f"\n  ── Pairs Trading Backtests ──")

    all_results = []

    for pair_info in coint_results:
        name = pair_info['name']
        spread = pair_info['spread']
        p1 = pair_info['prices1']
        p2 = pair_info['prices2']
        hr = pair_info['hedge_ratio']

        # Test different entry thresholds
        for entry_z in [1.5, 2.0, 2.5]:
            trades = pairs_trading_backtest(
                spread, p1, p2, hr, name,
                entry_z=entry_z, exit_z=0.5, max_hold_bars=100
            )

            if trades.empty or len(trades) < 10:
                continue

            net_rets = trades['net_ret']
            win_rate = (net_rets > 0).mean() * 100
            avg_ret = net_rets.mean() * 10000
            total_ret = net_rets.sum() * 100
            n_trades = len(trades)
            avg_hold = trades['hold_bars'].mean()

            # Approximate Sharpe: annualize from avg trade duration
            trades_per_year = n_trades / (len(spread) / ANN_H)
            annual_ret = net_rets.mean() * trades_per_year
            annual_std = net_rets.std() * np.sqrt(trades_per_year)
            pair_sharpe = annual_ret / (annual_std + 1e-10)

            all_results.append({
                'pair': name,
                'entry_z': entry_z,
                'n_trades': n_trades,
                'win_rate': win_rate,
                'avg_ret_bps': avg_ret,
                'total_ret': total_ret,
                'avg_hold_h': avg_hold,
                'sharpe': pair_sharpe,
            })

    if all_results:
        rdf = pd.DataFrame(all_results)
        print(f"\n    {'Pair':<15s} {'EntryZ':>7s} {'Trades':>7s} {'WinRate':>8s} "
              f"{'AvgRet':>8s} {'TotalRet':>9s} {'AvgHold':>8s} {'Sharpe':>8s}")
        print(f"    {'─'*15} {'─'*7} {'─'*7} {'─'*8} {'─'*8} {'─'*9} {'─'*8} {'─'*8}")

        for _, row in rdf.iterrows():
            sh_mark = " ◄" if row['sharpe'] > 0.5 else ""
            print(f"    {row['pair']:<15s} "
                  f"{row['entry_z']:>6.1f}σ "
                  f"{int(row['n_trades']):>7d} "
                  f"{row['win_rate']:>7.1f}% "
                  f"{row['avg_ret_bps']:>+7.1f} "
                  f"{row['total_ret']:>+8.1f}% "
                  f"{row['avg_hold_h']:>7.0f}h "
                  f"{row['sharpe']:>+7.3f}{sh_mark}")

        # Best result
        best = rdf.loc[rdf['sharpe'].idxmax()]
        print(f"\n    Best: {best['pair']} at {best['entry_z']}σ → "
              f"Sharpe {best['sharpe']:+.3f}, {int(best['n_trades'])} trades")
    else:
        print("    No viable pairs found")

    # ── Walk-Forward Pairs Test ──
    print(f"\n  ── Walk-Forward OOS Pairs Test ──")
    print(f"  Train: 6 months → Test: 3 months, rolling")

    train_bars = 6 * 21 * 7  # ~6 months of hourly bars
    test_bars = 3 * 21 * 7   # ~3 months

    for s1, s2 in [('SPY', 'QQQ'), ('TLT', 'IEF'), ('SPY', 'IWM')]:
        if s1 not in close_df.columns or s2 not in close_df.columns:
            continue

        p1_full = close_df[s1]
        p2_full = close_df[s2]

        oos_returns = []
        n_windows = 0

        start = 0
        while start + train_bars + test_bars <= len(p1_full):
            # Train period
            train_p1 = p1_full.iloc[start:start+train_bars]
            train_p2 = p2_full.iloc[start:start+train_bars]

            # Compute hedge ratio from training
            from scipy.stats import linregress
            slope, intercept, _, _, _ = linregress(train_p2.values, train_p1.values)

            # Test period
            test_start = start + train_bars
            test_end = test_start + test_bars
            test_p1 = p1_full.iloc[test_start:test_end]
            test_p2 = p2_full.iloc[test_start:test_end]

            # Spread on test data using TRAIN hedge ratio
            test_spread = test_p1 - slope * test_p2

            # Use training spread for z-score parameters
            train_spread = train_p1 - slope * train_p2
            train_mean = train_spread.mean()
            train_std = train_spread.std()

            if train_std <= 0:
                start += test_bars
                continue

            # Simple z-score trading on test period
            zscore_test = (test_spread - train_mean) / train_std

            # Generate daily PnL
            position = 0
            entry_z_val = 2.0
            exit_z_val = 0.5
            window_trades = []

            spread_vals = test_spread.values
            z_vals = zscore_test.values
            p1_vals = test_p1.values
            p2_vals = test_p2.values

            entry_p1 = entry_p2 = 0
            hold_count = 0

            for i in range(len(z_vals)):
                z = z_vals[i]
                if np.isnan(z):
                    continue

                if position == 0:
                    if z > entry_z_val:
                        position = -1
                        entry_p1 = p1_vals[i]
                        entry_p2 = p2_vals[i]
                        hold_count = 0
                    elif z < -entry_z_val:
                        position = 1
                        entry_p1 = p1_vals[i]
                        entry_p2 = p2_vals[i]
                        hold_count = 0
                else:
                    hold_count += 1
                    should_exit = False
                    if position == 1 and z > -exit_z_val:
                        should_exit = True
                    elif position == -1 and z < exit_z_val:
                        should_exit = True
                    elif hold_count > 100:
                        should_exit = True

                    if should_exit and entry_p1 > 0:
                        ret1 = (p1_vals[i] / entry_p1 - 1) * position
                        ret2 = (p2_vals[i] / entry_p2 - 1) * (-position) * slope
                        ret_total = (ret1 + ret2) / (1 + abs(slope)) - 2 * COST_RT
                        window_trades.append(ret_total)
                        position = 0

            if window_trades:
                avg_ret = np.mean(window_trades)
                oos_returns.append({
                    'window': n_windows,
                    'n_trades': len(window_trades),
                    'avg_ret': avg_ret,
                    'total_ret': sum(window_trades),
                    'win_rate': sum(1 for r in window_trades if r > 0) / len(window_trades),
                })

            n_windows += 1
            start += test_bars

        if oos_returns:
            oos_df = pd.DataFrame(oos_returns)
            avg_oos = oos_df['avg_ret'].mean() * 10000
            win_windows = (oos_df['total_ret'] > 0).mean() * 100
            total_oos = oos_df['total_ret'].sum() * 100
            total_trades = oos_df['n_trades'].sum()

            print(f"\n    {s1}/{s2}:")
            print(f"      OOS windows: {len(oos_df)}")
            print(f"      Total OOS trades: {total_trades}")
            print(f"      Avg OOS return/trade: {avg_oos:+.1f} bps")
            print(f"      Total OOS return: {total_oos:+.1f}%")
            print(f"      Profitable windows: {win_windows:.0f}%")

            for _, row in oos_df.iterrows():
                wr = row['win_rate'] * 100
                print(f"        Window {int(row['window'])}: "
                      f"{int(row['n_trades'])} trades, "
                      f"avg {row['avg_ret']*10000:+.1f} bps, "
                      f"total {row['total_ret']*100:+.1f}%, "
                      f"win {wr:.0f}%")
        else:
            print(f"\n    {s1}/{s2}: No OOS trades generated")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Loading IBKR 1h data...")
    data = load_ibkr_data()
    print(f"  Loaded {len(data)} symbols: {list(data.keys())}")

    test_opening_techniques(data)
    test_pairs_trading(data)

    print(f"\n{'='*72}")
    print("  FINAL VERDICT")
    print("="*72)
    print("""
    Refer to the numbers above. The key questions are:
    1. Do ORB trades produce positive avg return after 0.03% cost?
    2. Do pairs produce positive OOS average return?
    3. Is any Sharpe > 0.5 (barely worth trading)?
    """)


if __name__ == "__main__":
    main()
