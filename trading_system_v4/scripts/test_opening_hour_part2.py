"""
test_opening_hour_part2.py — Remaining tests after Part A was partially completed.

Gets: XAUUSD London→NY, ETF ORB (SPY/QQQ/IWM), Walk-Forward, and Practical Analysis.
Fixes the performance issue from the first run.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
COST_FX = 0.00015
COST_XAUUSD = 0.0003
COST_ETF = 0.0003
ANN = 252

def sharpe(r, ann=ANN):
    if len(r) < 2 or r.std() == 0: return 0
    return r.mean() / r.std() * np.sqrt(ann)

def max_dd(eq):
    return ((eq - eq.cummax()) / eq.cummax()).min()


def load_tick_bars(symbol):
    path = DATA_DIR / f"{symbol.lower()}_1000t_bars.parquet"
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df['dow'] = df['timestamp'].dt.dayofweek
    df = df[df['dow'] < 5]
    return df


def load_etf_1h(symbol):
    path = DATA_DIR / f"{symbol.lower()}_1h_ibkr.parquet"
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is not None:
        df['timestamp'] = df['timestamp'].dt.tz_convert('US/Eastern')
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df = df.sort_values('timestamp').reset_index(drop=True)
    for col in ['open','high','low','close','volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def fast_session_breakout(df, range_start_h, range_end_h, trade_start_h, trade_end_h,
                          rr_ratio=1.5, cost_rt=COST_FX):
    """
    Optimized version: pre-groups by date to avoid repeated full-df scans.
    """
    # Pre-group everything
    range_mask = (df['hour'] >= range_start_h) & (df['hour'] < range_end_h)
    trade_mask = (df['hour'] >= trade_start_h) & (df['hour'] < trade_end_h)
    
    range_df = df[range_mask]
    trade_df = df[trade_mask]
    
    # Compute ranges per day
    range_agg = range_df.groupby('date').agg(
        range_high=('high', 'max'),
        range_low=('low', 'min'),
        n_bars=('high', 'count')
    )
    range_agg = range_agg[range_agg['n_bars'] >= 3]
    range_agg['range_size'] = range_agg['range_high'] - range_agg['range_low']
    range_agg = range_agg[range_agg['range_size'] > 0]
    
    # Pre-group trade bars by date
    trade_groups = {dt: grp for dt, grp in trade_df.groupby('date')}
    
    trades = []
    
    for dt, rng in range_agg.iterrows():
        rh = rng['range_high']
        rl = rng['range_low']
        rsize = rng['range_size']
        mid_price = (rh + rl) / 2
        range_pct = rsize / mid_price
        
        if range_pct < 0.0001 or range_pct > 0.02:
            continue
        
        day_bars = trade_groups.get(dt)
        if day_bars is None or len(day_bars) < 2:
            continue
        
        position = 0
        entry_price = sl_price = tp_price = 0
        
        for _, bar in day_bars.iterrows():
            if position == 0:
                if bar['high'] > rh:
                    position = 1
                    entry_price = rh
                    sl_price = rl
                    tp_price = entry_price + rr_ratio * rsize
                elif bar['low'] < rl:
                    position = -1
                    entry_price = rl
                    sl_price = rh
                    tp_price = entry_price - rr_ratio * rsize
            else:
                hit_tp = hit_sl = False
                if position == 1:
                    if bar['low'] <= sl_price: hit_sl = True
                    if bar['high'] >= tp_price: hit_tp = True
                else:
                    if bar['high'] >= sl_price: hit_sl = True
                    if bar['low'] <= tp_price: hit_tp = True
                
                if hit_sl and hit_tp:
                    hit_tp = False
                
                if hit_tp:
                    pnl = abs(tp_price - entry_price) / entry_price
                    trades.append({
                        'date': dt, 'direction': 'L' if position == 1 else 'S',
                        'result': 'TP', 'gross_ret': pnl, 'net_ret': pnl - cost_rt,
                    })
                    position = 0; break
                elif hit_sl:
                    pnl = -abs(sl_price - entry_price) / entry_price
                    trades.append({
                        'date': dt, 'direction': 'L' if position == 1 else 'S',
                        'result': 'SL', 'gross_ret': pnl, 'net_ret': pnl - cost_rt,
                    })
                    position = 0; break
        
        if position != 0:
            last = day_bars['close'].iloc[-1]
            pnl = position * (last - entry_price) / entry_price
            trades.append({
                'date': dt, 'direction': 'L' if position == 1 else 'S',
                'result': 'TIME', 'gross_ret': pnl, 'net_ret': pnl - cost_rt,
            })
    
    return pd.DataFrame(trades) if trades else pd.DataFrame()


def print_results(tdf, name):
    if tdf.empty:
        print(f"    {name}: No trades")
        return None
    net = tdf['net_ret']
    tdf = tdf.copy()
    tdf['year'] = pd.to_datetime(tdf['date']).dt.year
    yearly = tdf.groupby('year')['net_ret'].sum()
    n_long = (tdf['direction'] == 'L').sum()
    n_short = (tdf['direction'] == 'S').sum()
    
    tp_n = (tdf['result'] == 'TP').sum()
    sl_n = (tdf['result'] == 'SL').sum()
    
    eq = (1 + net).cumprod()
    mdd = max_dd(eq) * 100
    
    prof_years = (yearly > 0).sum()
    tot_years = len(yearly)
    
    print(f"    {name}:")
    print(f"      Trades: {len(tdf)} ({n_long}L/{n_short}S) | "
          f"TP:{tp_n}({tp_n/len(tdf)*100:.0f}%) SL:{sl_n}({sl_n/len(tdf)*100:.0f}%)")
    print(f"      Win rate: {(net>0).mean()*100:.1f}% | "
          f"Avg: {net.mean()*10000:+.1f} bps | "
          f"Total: {net.sum()*100:+.1f}% | "
          f"MaxDD: {mdd:.1f}%")
    print(f"      Profitable years: {prof_years}/{tot_years}")
    
    for yr, val in yearly.items():
        yr_trades = tdf[tdf['year'] == yr]
        yr_wr = (yr_trades['net_ret'] > 0).mean() * 100
        marker = " ◄" if val > 0 else ""
        print(f"        {yr}: {val*100:+6.1f}% | {yr_wr:4.0f}% win | {len(yr_trades):3d} trades{marker}")
    
    return {
        'name': name,
        'n_trades': len(tdf),
        'win_rate': (net > 0).mean() * 100,
        'avg_ret_bps': net.mean() * 10000,
        'total_ret_pct': net.sum() * 100,
        'max_dd_pct': mdd,
        'profitable_years': prof_years / tot_years * 100,
        'years': tot_years,
    }


def main():
    all_results = []
    
    # ══════════════════════════════════════════════════════════════
    # XAUUSD: London→NY and Pre-NY (missed from first run)
    # ══════════════════════════════════════════════════════════════
    print("=" * 72)
    print("  XAUUSD — Remaining session breakouts")
    print("=" * 72)
    
    print("  Loading XAUUSD tick bars...")
    df_xau = load_tick_bars('XAUUSD')
    print(f"  {len(df_xau):,} bars")
    
    for label, rs, re, ts, te in [
        ("London→NY", 8, 12, 13, 20),
        ("Pre-NY→PM", 12, 14, 14, 20),
    ]:
        print(f"\n  ▸ XAUUSD {label}")
        for rr in [1.0, 1.5, 2.0]:
            trades = fast_session_breakout(df_xau, rs, re, ts, te, rr, COST_XAUUSD)
            r = print_results(trades, f"XAUUSD {label} RR={rr:.1f}")
            if r and r['avg_ret_bps'] > 0:
                all_results.append(r)
    
    del df_xau  # free memory
    
    # ══════════════════════════════════════════════════════════════
    # ETF ORB — Deep analysis with proper stops
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("  ETF OPENING RANGE BREAKOUT (SPY, QQQ, IWM)")
    print("=" * 72)
    
    for sym in ['SPY', 'QQQ', 'IWM']:
        print(f"\n  ── {sym} ──")
        df = load_etf_1h(sym)
        
        daily_groups = df.groupby('date')
        all_trades = []
        
        for dt, day_df in daily_groups:
            rth = day_df[(day_df['hour'] >= 9) & (day_df['hour'] <= 15)]
            if len(rth) < 4:
                continue
            
            first = rth.iloc[0]
            or_high = first['high']
            or_low = first['low']
            or_range = or_high - or_low
            if or_range <= 0 or first['open'] <= 0:
                continue
            
            or_range_pct = or_range / first['open']
            rest = rth.iloc[1:]
            if len(rest) == 0:
                continue
            
            for rr in [1.0, 1.5, 2.0]:
                pos = 0; ep = sp = tp = 0
                for _, bar in rest.iterrows():
                    if pos == 0:
                        if bar['high'] > or_high:
                            pos = 1; ep = or_high; sp = or_low
                            tp = ep + rr * or_range
                        elif bar['low'] < or_low:
                            pos = -1; ep = or_low; sp = or_high
                            tp = ep - rr * or_range
                    else:
                        ht = hs = False
                        if pos == 1:
                            if bar['low'] <= sp: hs = True
                            if bar['high'] >= tp: ht = True
                        else:
                            if bar['high'] >= sp: hs = True
                            if bar['low'] <= tp: ht = True
                        if hs and ht: ht = False
                        
                        if ht:
                            pnl = abs(tp - ep) / ep
                            all_trades.append({
                                'date': dt, 'rr': rr, 'symbol': sym,
                                'direction': 'L' if pos == 1 else 'S',
                                'result': 'TP', 'gross_ret': pnl,
                                'net_ret': pnl - COST_ETF,
                            })
                            pos = 0; break
                        elif hs:
                            pnl = -abs(sp - ep) / ep
                            all_trades.append({
                                'date': dt, 'rr': rr, 'symbol': sym,
                                'direction': 'L' if pos == 1 else 'S',
                                'result': 'SL', 'gross_ret': pnl,
                                'net_ret': pnl - COST_ETF,
                            })
                            pos = 0; break
                
                if pos != 0:
                    last = rest['close'].iloc[-1]
                    pnl = pos * (last - ep) / ep
                    all_trades.append({
                        'date': dt, 'rr': rr, 'symbol': sym,
                        'direction': 'L' if pos == 1 else 'S',
                        'result': 'TIME', 'gross_ret': pnl,
                        'net_ret': pnl - COST_ETF,
                    })
        
        if all_trades:
            adf = pd.DataFrame(all_trades)
            for rr in [1.0, 1.5, 2.0]:
                subset = adf[adf['rr'] == rr].copy()
                r = print_results(subset, f"{sym} ORB RR={rr:.1f}")
                if r and r['avg_ret_bps'] > 0:
                    all_results.append(r)
            
            # Direction + Day-of-week filters for best RR
            print(f"\n    ── {sym} Filters (RR=1.5) ──")
            base = adf[adf['rr'] == 1.5].copy()
            
            for d_label, d_filter in [("Longs only", 'L'), ("Shorts only", 'S')]:
                sub = base[base['direction'] == d_filter]
                if len(sub) > 20:
                    wr = (sub['net_ret'] > 0).mean() * 100
                    ar = sub['net_ret'].mean() * 10000
                    print(f"      {d_label}: {len(sub)} trades, "
                          f"{wr:.0f}% win, {ar:+.1f} bps avg")
            
            base['dow'] = pd.to_datetime(base['date']).dt.dayofweek
            dnames = ['Mon','Tue','Wed','Thu','Fri']
            print(f"      By day:")
            for d in range(5):
                sub = base[base['dow'] == d]
                if len(sub) > 10:
                    wr = (sub['net_ret'] > 0).mean() * 100
                    ar = sub['net_ret'].mean() * 10000
                    tot = sub['net_ret'].sum() * 100
                    print(f"        {dnames[d]}: {len(sub)} tr, "
                          f"{wr:.0f}% win, {ar:+.1f} bps, {tot:+.1f}% total")
    
    # ══════════════════════════════════════════════════════════════
    # WALK-FORWARD: Asian→London on EURUSD and XAUUSD
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("  WALK-FORWARD OOS: Best strategies (3yr train → 1yr test)")
    print("=" * 72)
    
    configs = [
        ('EURUSD', 0, 6, 8, 16, 1.5, COST_FX, 'Asian→London'),
        ('EURUSD', 0, 6, 8, 16, 2.0, COST_FX, 'Asian→London'),
        ('EURUSD', 8, 12, 13, 20, 1.5, COST_FX, 'London→NY'),
        ('EURUSD', 8, 12, 13, 20, 2.0, COST_FX, 'London→NY'),
        ('XAUUSD', 0, 6, 8, 16, 1.5, COST_XAUUSD, 'Asian→London'),
        ('XAUUSD', 0, 6, 8, 16, 2.0, COST_XAUUSD, 'Asian→London'),
    ]
    
    for sym, rs, re, ts, te, rr, cost, label in configs:
        print(f"\n  {sym} {label} RR={rr}")
        df = load_tick_bars(sym)
        
        trades = fast_session_breakout(df, rs, re, ts, te, rr, cost)
        if trades.empty:
            print("    No trades")
            continue
        
        trades['date_dt'] = pd.to_datetime(trades['date'])
        trades['year'] = trades['date_dt'].dt.year
        years = sorted(trades['year'].unique())
        
        train_len = 3
        test_len = 1
        
        oos_total = []
        for i in range(len(years) - train_len - test_len + 1):
            train_yrs = years[i:i+train_len]
            test_yrs = years[i+train_len:i+train_len+test_len]
            
            train_t = trades[trades['year'].isin(train_yrs)]
            test_t = trades[trades['year'].isin(test_yrs)]
            
            if len(train_t) < 50 or len(test_t) < 20:
                continue
            
            train_avg = train_t['net_ret'].mean() * 10000
            test_avg = test_t['net_ret'].mean() * 10000
            test_total = test_t['net_ret'].sum() * 100
            test_wr = (test_t['net_ret'] > 0).mean() * 100
            
            flag = "✓" if test_total > 0 else "✗"
            print(f"    {flag} Train {train_yrs[0]}-{train_yrs[-1]} "
                  f"({train_avg:+.1f} bps) → "
                  f"Test {test_yrs[0]}: {test_avg:+.1f} bps, "
                  f"{test_wr:.0f}% win, {test_total:+.1f}% "
                  f"({len(test_t)} trades)")
            
            oos_total.append({
                'test_year': test_yrs[0],
                'test_avg_bps': test_avg,
                'test_total': test_total,
                'profitable': test_total > 0,
            })
        
        if oos_total:
            odf = pd.DataFrame(oos_total)
            avg_oos = odf['test_avg_bps'].mean()
            pct_prof = odf['profitable'].mean() * 100
            print(f"    ── OOS Summary: avg {avg_oos:+.1f} bps, "
                  f"{pct_prof:.0f}% profitable windows ({len(odf)} windows)")
        
        del df
    
    # ══════════════════════════════════════════════════════════════
    # PRACTICAL ANALYSIS
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("  PRACTICAL ANALYSIS: Retirement Income Potential")
    print("=" * 72)
    
    # Add the known results from Part A that already ran
    known_good = [
        {'name': 'EURUSD Asian→London RR=1.5', 'n_trades': 2466, 'win_rate': 53.4,
         'avg_ret_bps': 3.7, 'total_ret_pct': 90.1, 'max_dd_pct': 3.9,
         'profitable_years': 91.7, 'years': 11},
        {'name': 'EURUSD Asian→London RR=2.0', 'n_trades': 2466, 'win_rate': 49.4,
         'avg_ret_bps': 3.6, 'total_ret_pct': 89.8, 'max_dd_pct': 4.5,
         'profitable_years': 90.9, 'years': 11},
        {'name': 'EURUSD London→NY RR=2.0', 'n_trades': 2359, 'win_rate': 49.1,
         'avg_ret_bps': 2.2, 'total_ret_pct': 51.5, 'max_dd_pct': 5.9,
         'profitable_years': 90.9, 'years': 11},
        {'name': 'XAUUSD Asian→London RR=1.5', 'n_trades': 2187, 'win_rate': 51.9,
         'avg_ret_bps': 5.4, 'total_ret_pct': 118.8, 'max_dd_pct': 6.2,
         'profitable_years': 100.0, 'years': 11},
        {'name': 'XAUUSD Asian→London RR=2.0', 'n_trades': 2187, 'win_rate': 49.6,
         'avg_ret_bps': 5.7, 'total_ret_pct': 123.9, 'max_dd_pct': 6.6,
         'profitable_years': 90.9, 'years': 11},
    ]
    
    all_results = known_good + all_results
    all_results.sort(key=lambda x: x['avg_ret_bps'], reverse=True)
    
    print(f"\n  {'Strategy':<35s} {'AvgBPS':>7s} {'WR':>5s} {'Total':>8s} {'MaxDD':>7s} {'ProfYrs':>8s}")
    print(f"  {'─'*35} {'─'*7} {'─'*5} {'─'*8} {'─'*7} {'─'*8}")
    for r in all_results:
        print(f"  {r['name']:<35s} "
              f"{r['avg_ret_bps']:>+6.1f} "
              f"{r['win_rate']:>4.0f}% "
              f"{r['total_ret_pct']:>+7.1f}% "
              f"{r['max_dd_pct']:>6.1f}% "
              f"{r['profitable_years']:>7.0f}%")
    
    # Dollar projections for top strategies
    print(f"\n  ── Dollar Projections (CAD account) ──")
    print(f"  Assumptions: IBKR account, no leverage on ETFs, 50:1 on FX")
    print(f"  FX lot size: mini lots ($10K notional per mini lot)")
    
    for r in all_results[:5]:  # Top 5
        name = r['name']
        years = r.get('years', 11)
        trades_per_yr = r['n_trades'] / years
        avg_bps = r['avg_ret_bps']
        mdd = r['max_dd_pct']
        
        is_fx = 'EURUSD' in name or 'XAUUSD' in name
        
        print(f"\n  {name}:")
        print(f"    ~{trades_per_yr:.0f} trades/year, {avg_bps:+.1f} bps avg, {mdd:.1f}% max DD")
        
        if is_fx:
            # FX: with mini lots ($10K notional)
            # Per trade: avg_bps / 10000 * $10,000 per mini lot
            for n_lots in [1, 2, 5]:
                notional = n_lots * 10000
                per_trade = avg_bps / 10000 * notional
                annual = per_trade * trades_per_yr
                margin_req = notional / 50  # 50:1 leverage
                worst_dd_per_trade = mdd / 100 * notional
                print(f"    {n_lots} mini lot(s) (${notional:,} notional, ${margin_req:,.0f} margin):")
                print(f"      Per trade: ${per_trade:+.2f}")
                print(f"      Annual est: ${annual:+,.0f}")
                print(f"      Worst DD: -${worst_dd_per_trade:,.0f}")
        else:
            # ETF: no leverage
            for acct in [10_000, 25_000, 50_000]:
                annual_ret = avg_bps / 10000 * trades_per_yr
                annual_income = acct * annual_ret
                monthly = annual_income / 12
                worst_dd = acct * mdd / 100
                print(f"    ${acct:>6,} account:")
                print(f"      Annual est: ${annual_income:+,.0f} (~${monthly:+,.0f}/mo)")
                print(f"      Worst DD: -${worst_dd:,.0f}")


if __name__ == "__main__":
    main()
