"""Sweep time-cutoff hours (10-20 UTC) and weekday-specific cutoffs."""
import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np

df = pd.read_parquet('trading_system_v4/data/xauusd_1000t_bars.parquet')
df['timestamp'] = pd.to_datetime(df['timestamp'])
if df['timestamp'].dt.tz is None:
    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
df['hour'] = df['timestamp'].dt.hour
df['date'] = df['timestamp'].dt.date
df['dow'] = df['timestamp'].dt.dayofweek
df = df[(df['dow'] < 5) & (df['dow'] != 2)]  # weekdays, skip Wed
df = df[(df['timestamp'] >= '2024-01-01') & (df['timestamp'] < '2026-01-01')]

# build Asian ranges
range_df = df[(df['hour'] >= 0) & (df['hour'] < 6)]
ra = range_df.groupby('date').agg(rh=('high','max'), rl=('low','min'), nb=('high','count'))
ra = ra[ra['nb'] >= 3]
ra['rs'] = ra['rh'] - ra['rl']
ra = ra[ra['rs'] > 0]
ra['mid'] = (ra['rh'] + ra['rl']) / 2
ra['rpct'] = ra['rs'] / ra['mid']
ra = ra[(ra['rpct'] >= 0.0001) & (ra['rpct'] <= 0.02)]
ra['dow'] = pd.to_datetime(list(ra.index)).dayofweek

RR = 2.0

def run_backtest(cutoff_hour, dates_subset=None):
    """Run backtest with a specific cutoff hour. Returns trade list."""
    trade_bars = df[(df['hour'] >= 8) & (df['hour'] < cutoff_hour)]
    tg = {dt: grp for dt, grp in trade_bars.groupby('date')}
    trades = []
    
    for dt, rng in ra.iterrows():
        if dates_subset is not None and dt not in dates_subset:
            continue
        rh, rl, rs = rng['rh'], rng['rl'], rng['rs']
        bars = tg.get(dt)
        if bars is None or len(bars) < 2:
            continue
        pos = 0; entry = sl = tp = 0
        for _, bar in bars.iterrows():
            if pos == 0:
                if bar['high'] > rh:
                    pos = 1; entry = rh; sl = rl; tp = rh + RR * rs
                elif bar['low'] < rl:
                    pos = -1; entry = rl; sl = rh; tp = rl - RR * rs
            else:
                if pos == 1:
                    hit_sl = bar['low'] <= sl
                    hit_tp = bar['high'] >= tp
                else:
                    hit_sl = bar['high'] >= sl
                    hit_tp = bar['low'] <= tp
                if hit_sl and hit_tp: hit_tp = False
                if hit_tp:
                    trades.append({'date': dt, 'pnl': abs(tp - entry), 'result': 'TP', 'range': rs})
                    pos = 0; break
                elif hit_sl:
                    trades.append({'date': dt, 'pnl': -abs(sl - entry), 'result': 'SL', 'range': rs})
                    pos = 0; break
        if pos != 0:
            last = bars['close'].iloc[-1]
            pnl = pos * (last - entry)
            trades.append({'date': dt, 'pnl': pnl, 'result': 'TIME', 'range': rs})
    return trades


# ── Part 1: Sweep cutoff from 10 to 20 UTC ──────────────────────
print('=' * 70)
print('  PART 1: Time-cutoff sweep (all weekdays, Wed excluded)')
print('=' * 70)
print(f'  {"Cutoff":>8}  {"Trades":>6}  {"Wins":>5}  {"Loss":>5}  {"Win%":>5}  '
      f'{"PnL/oz":>10}  {"Avg/tr":>8}  {"Time%":>6}')
print('-' * 70)

cutoff_results = {}
for cutoff in range(10, 21):
    trades = run_backtest(cutoff)
    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        continue
    wins = (tdf['pnl'] > 0).sum()
    losses = (tdf['pnl'] <= 0).sum()
    total_pnl = tdf['pnl'].sum()
    avg_pnl = tdf['pnl'].mean()
    time_pct = (tdf['result'] == 'TIME').sum() / len(tdf) * 100
    cutoff_results[cutoff] = {'trades': len(tdf), 'wins': wins, 'losses': losses,
                               'total_pnl': total_pnl, 'avg_pnl': avg_pnl}
    print(f'  {cutoff:>5} UTC  {len(tdf):>6}  {wins:>5}  {losses:>5}  {wins/len(tdf)*100:>4.0f}%  '
          f'${total_pnl:>+9.1f}  ${avg_pnl:>+7.2f}  {time_pct:>4.0f}%')

# Best cutoff
best = max(cutoff_results, key=lambda k: cutoff_results[k]['total_pnl'])
print(f'\n  Best total PnL: {best} UTC  (${cutoff_results[best]["total_pnl"]:+.1f}/oz)')
best_avg = max(cutoff_results, key=lambda k: cutoff_results[k]['avg_pnl'])
print(f'  Best PnL/trade: {best_avg} UTC  (${cutoff_results[best_avg]["avg_pnl"]:+.2f}/oz/trade)')


# ── Part 2: Per-weekday cutoff sweep ─────────────────────────────
print('\n' + '=' * 70)
print('  PART 2: Cutoff sweep BY WEEKDAY')
print('=' * 70)

dow_names = {0: 'Mon', 1: 'Tue', 3: 'Thu', 4: 'Fri'}
best_per_dow = {}

for dow, name in sorted(dow_names.items()):
    dates_for_dow = set(ra[ra['dow'] == dow].index)
    print(f'\n  --- {name} (dow={dow}) ---')
    print(f'  {"Cutoff":>8}  {"Trades":>6}  {"Wins":>5}  {"Loss":>5}  {"Win%":>5}  '
          f'{"PnL/oz":>10}  {"Avg/tr":>8}')
    
    dow_results = {}
    for cutoff in range(10, 21):
        trades = run_backtest(cutoff, dates_for_dow)
        tdf = pd.DataFrame(trades)
        if len(tdf) == 0:
            continue
        wins = (tdf['pnl'] > 0).sum()
        losses = (tdf['pnl'] <= 0).sum()
        total_pnl = tdf['pnl'].sum()
        avg_pnl = tdf['pnl'].mean()
        dow_results[cutoff] = {'trades': len(tdf), 'total_pnl': total_pnl, 'avg_pnl': avg_pnl}
        print(f'  {cutoff:>5} UTC  {len(tdf):>6}  {wins:>5}  {losses:>5}  {wins/len(tdf)*100:>4.0f}%  '
              f'${total_pnl:>+9.1f}  ${avg_pnl:>+7.2f}')
    
    if dow_results:
        best_dow = max(dow_results, key=lambda k: dow_results[k]['avg_pnl'])
        best_per_dow[name] = best_dow
        print(f'  Best for {name}: {best_dow} UTC  (${dow_results[best_dow]["avg_pnl"]:+.2f}/trade)')


# ── Part 3: Combined best-per-weekday vs uniform ─────────────────
print('\n' + '=' * 70)
print('  PART 3: Weekday-adaptive cutoff vs. uniform best')
print('=' * 70)

# Adaptive: use best cutoff per weekday
adaptive_trades = []
for dow, name in sorted(dow_names.items()):
    dates_for_dow = set(ra[ra['dow'] == dow].index)
    best_co = best_per_dow.get(name, 16)
    trades = run_backtest(best_co, dates_for_dow)
    adaptive_trades.extend(trades)

adf = pd.DataFrame(adaptive_trades)

# Uniform best
uniform_trades = run_backtest(best_avg)
udf = pd.DataFrame(uniform_trades)

print(f'\n  Uniform cutoff ({best_avg} UTC):')
print(f'    Trades: {len(udf)},  Wins: {(udf["pnl"]>0).sum()},  '
      f'PnL: ${udf["pnl"].sum():+.1f}/oz,  Avg: ${udf["pnl"].mean():+.2f}/trade')

print(f'\n  Weekday-adaptive cutoffs: {best_per_dow}')
print(f'    Trades: {len(adf)},  Wins: {(adf["pnl"]>0).sum()},  '
      f'PnL: ${adf["pnl"].sum():+.1f}/oz,  Avg: ${adf["pnl"].mean():+.2f}/trade')

# Current baseline (16 UTC)
baseline = run_backtest(16)
bdf = pd.DataFrame(baseline)
print(f'\n  Current baseline (16 UTC):')
print(f'    Trades: {len(bdf)},  Wins: {(bdf["pnl"]>0).sum()},  '
      f'PnL: ${bdf["pnl"].sum():+.1f}/oz,  Avg: ${bdf["pnl"].mean():+.2f}/trade')

print('\n  NOTE: Adaptive cutoffs are in-sample optimized on 2024-2025.')
print('  Small sample (~50 trades/weekday). Overfitting risk is HIGH.')
print('  Stick with uniform cutoff unless difference is large & robust.')
