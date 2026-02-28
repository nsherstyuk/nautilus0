"""Quick 2024-2025 backtest stats, Wed excluded."""
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

range_df = df[(df['hour'] >= 0) & (df['hour'] < 6)]
trade_df = df[(df['hour'] >= 8) & (df['hour'] < 16)]

ra = range_df.groupby('date').agg(rh=('high','max'), rl=('low','min'), nb=('high','count'))
ra = ra[(ra['nb'] >= 3)]
ra['rs'] = ra['rh'] - ra['rl']
ra = ra[ra['rs'] > 0]

tg = {dt: grp for dt, grp in trade_df.groupby('date')}
rr = 2.0
trades = []

for dt, rng in ra.iterrows():
    rh, rl, rs = rng['rh'], rng['rl'], rng['rs']
    mid = (rh + rl) / 2
    rpct = rs / mid
    if rpct < 0.0001 or rpct > 0.02:
        continue
    bars = tg.get(dt)
    if bars is None or len(bars) < 2:
        continue
    pos = 0; entry = sl = tp = 0
    for _, bar in bars.iterrows():
        if pos == 0:
            if bar['high'] > rh:
                pos = 1; entry = rh; sl = rl; tp = rh + rr * rs
            elif bar['low'] < rl:
                pos = -1; entry = rl; sl = rh; tp = rl - rr * rs
        else:
            hit_tp = hit_sl = False
            if pos == 1:
                if bar['low'] <= sl: hit_sl = True
                if bar['high'] >= tp: hit_tp = True
            else:
                if bar['high'] >= sl: hit_sl = True
                if bar['low'] <= tp: hit_tp = True
            if hit_sl and hit_tp: hit_tp = False
            if hit_tp:
                pnl = abs(tp - entry)
                trades.append({'date': dt, 'dir': 'L' if pos==1 else 'S',
                               'result': 'TP', 'pnl': pnl, 'entry': entry,
                               'exit': tp, 'range': rs})
                pos = 0; break
            elif hit_sl:
                pnl = -abs(sl - entry)
                trades.append({'date': dt, 'dir': 'L' if pos==1 else 'S',
                               'result': 'SL', 'pnl': pnl, 'entry': entry,
                               'exit': sl, 'range': rs})
                pos = 0; break
    if pos != 0:
        last = bars['close'].iloc[-1]
        pnl = pos * (last - entry)
        trades.append({'date': dt, 'dir': 'L' if pos==1 else 'S',
                       'result': 'TIME', 'pnl': pnl, 'entry': entry,
                       'exit': last, 'range': rs})

tdf = pd.DataFrame(trades)
tdf['year'] = pd.to_datetime(tdf['date']).dt.year
tdf['month'] = pd.to_datetime(tdf['date']).dt.month
tdf['win'] = tdf['pnl'] > 0

print('=' * 65)
print('  XAUUSD ORB Backtest -- 2024-2025, Wed excluded, RR=2.0')
print('=' * 65)

for yr in [2024, 2025]:
    yt = tdf[tdf['year'] == yr]
    wins = yt[yt['win']]
    losses = yt[~yt['win']]
    tp_trades = yt[yt['result'] == 'TP']
    sl_trades = yt[yt['result'] == 'SL']
    time_trades = yt[yt['result'] == 'TIME']
    time_w = (time_trades['pnl'] > 0).sum()
    time_l = (time_trades['pnl'] <= 0).sum()

    print(f'\n  --- {yr} ---')
    print(f'  Total trades:    {len(yt)}')
    print(f'  Wins:            {len(wins)}  ({len(wins)/len(yt)*100:.0f}%)')
    print(f'  Losses:          {len(losses)}  ({len(losses)/len(yt)*100:.0f}%)')
    print(f'  TP hits:         {len(tp_trades)}')
    print(f'  SL hits:         {len(sl_trades)}')
    print(f'  Time exits:      {len(time_trades)}  (W:{time_w} L:{time_l})')
    print()
    print(f'  Avg win size:    ${wins["pnl"].mean():+.2f} /oz')
    print(f'  Avg loss size:   ${losses["pnl"].mean():+.2f} /oz')
    print(f'  Median win:      ${wins["pnl"].median():+.2f} /oz')
    print(f'  Median loss:     ${losses["pnl"].median():+.2f} /oz')
    print(f'  Max win:         ${wins["pnl"].max():+.2f} /oz')
    print(f'  Max loss:        ${losses["pnl"].min():+.2f} /oz')
    print()
    print(f'  Total PnL:       ${yt["pnl"].sum():+.2f} /oz')
    print(f'  Avg PnL/trade:   ${yt["pnl"].mean():+.2f} /oz')
    print()

    if len(tp_trades) > 0:
        print(f'  TP wins (size = 2x range, varies daily):')
        print(f'    Avg TP win:    ${tp_trades["pnl"].mean():.2f}')
        print(f'    Min TP:        ${tp_trades["pnl"].min():.2f}')
        print(f'    Max TP:        ${tp_trades["pnl"].max():.2f}')
    if len(sl_trades) > 0:
        print(f'  SL losses (size = 1x range, varies daily):')
        print(f'    Avg SL loss:   ${sl_trades["pnl"].mean():.2f}')
        print(f'    Min SL:        ${sl_trades["pnl"].min():.2f}')
        print(f'    Max SL:        ${sl_trades["pnl"].max():.2f}')

print('\n' + '=' * 65)
print('  MONTHLY BREAKDOWN')
print('=' * 65)
print(f'  {"Month":>8s}  {"Trades":>6s}  {"Wins":>5s}  {"Loss":>5s}  '
      f'{"Win%":>5s}  {"PnL/oz":>9s}')
for yr in [2024, 2025]:
    for m in range(1, 13):
        sub = tdf[(tdf['year'] == yr) & (tdf['month'] == m)]
        if len(sub) == 0:
            continue
        w = (sub['pnl'] > 0).sum()
        l = (sub['pnl'] <= 0).sum()
        pnl = sub['pnl'].sum()
        print(f'  {yr}-{m:02d}    {len(sub):>4d}   {w:>4d}   {l:>4d}  '
              f'{w/len(sub)*100:>4.0f}%  ${pnl:>+9.2f}')

print()
print('  ARE WIN/LOSS SIZES FIXED?')
print('  No -- they vary with the daily Asian range:')
print(f'    TP payout = 2x range  (range varies ${tdf["range"].min():.1f} - ${tdf["range"].max():.1f})')
print(f'    SL payout = 1x range')
print(f'    2024 avg range: ${tdf[tdf["year"]==2024]["range"].mean():.1f}')
print(f'    2025 avg range: ${tdf[tdf["year"]==2025]["range"].mean():.1f}')
print(f'    So a TP win is always exactly 2x the day\'s SL loss.')
