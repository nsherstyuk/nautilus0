import pandas as pd
import numpy as np

# Load trades
results_dir = 'backtest_results/MTF_V2_20251206_171427'
df = pd.read_csv(f'{results_dir}/trades.csv')
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['exit_time'] = pd.to_datetime(df['exit_time'])
df['entry_date'] = df['entry_time'].dt.date

# ============================================
# 1. SHARPE RATIO
# ============================================
daily_pnl_series = df.groupby('entry_date')['pnl'].sum()
sharpe = (daily_pnl_series.mean() / daily_pnl_series.std()) * np.sqrt(252)

print('=' * 60)
print('1. SHARPE RATIO')
print('=' * 60)
print(f'   Daily Mean PnL: {daily_pnl_series.mean():.2f}')
print(f'   Daily Std Dev:  {daily_pnl_series.std():.2f}')
print(f'   Sharpe Ratio:   {sharpe:.2f}')

# ============================================
# 2. NEGATIVE PnL DAYS
# ============================================
neg_days = (daily_pnl_series < 0).sum()
total_trading_days = len(daily_pnl_series)

print()
print('=' * 60)
print('2. NEGATIVE PnL DAYS')
print('=' * 60)
print(f'   Total Trading Days: {total_trading_days}')
print(f'   Negative Days:      {neg_days} ({neg_days/total_trading_days*100:.1f}%)')
print(f'   Positive Days:      {total_trading_days - neg_days} ({(total_trading_days-neg_days)/total_trading_days*100:.1f}%)')

# ============================================
# 3. CONSECUTIVE NEGATIVE DAYS
# ============================================
is_neg = (daily_pnl_series < 0).astype(int)
neg_day_streaks = []
current_streak = 0
for val in is_neg:
    if val == 1:
        current_streak += 1
    else:
        if current_streak > 0:
            neg_day_streaks.append(current_streak)
        current_streak = 0
if current_streak > 0:
    neg_day_streaks.append(current_streak)

max_neg_day_streak = max(neg_day_streaks) if neg_day_streaks else 0
avg_neg_day_streak = np.mean(neg_day_streaks) if neg_day_streaks else 0

print()
print('=' * 60)
print('3. CONSECUTIVE NEGATIVE DAYS')
print('=' * 60)
print(f'   Max Consecutive Neg Days: {max_neg_day_streak}')
print(f'   Avg Neg Day Streak:       {avg_neg_day_streak:.1f}')
print(f'   Number of Neg Day Streaks: {len(neg_day_streaks)}')

# ============================================
# 4. CONSECUTIVE NEGATIVE TRADES
# ============================================
df['is_loss'] = df['pnl'] < 0
loss_streaks = []
current_streak = 0
for is_loss in df['is_loss']:
    if is_loss:
        current_streak += 1
    else:
        if current_streak > 0:
            loss_streaks.append(current_streak)
        current_streak = 0
if current_streak > 0:
    loss_streaks.append(current_streak)

max_loss_streak = max(loss_streaks) if loss_streaks else 0
avg_loss_streak = np.mean(loss_streaks) if loss_streaks else 0

print('=' * 60)
print('4. CONSECUTIVE NEGATIVE TRADES')
print('=' * 60)
print(f'   Max Consecutive Losses: {max_loss_streak}')
print(f'   Avg Loss Streak Length: {avg_loss_streak:.1f}')
print(f'   Number of Loss Streaks: {len(loss_streaks)}')

# Find worst streaks
df['streak_id'] = (df['is_loss'] != df['is_loss'].shift()).cumsum()
loss_groups = df[df['is_loss']].groupby('streak_id').agg({
    'entry_time': ['first', 'count'],
    'pnl': 'sum'
}).reset_index()
loss_groups.columns = ['streak_id', 'start_time', 'count', 'total_pnl']
loss_groups = loss_groups.sort_values('count', ascending=False).head(5)
print('   Top 5 Worst Trade Streaks:')
for _, row in loss_groups.iterrows():
    print(f'      {int(row["count"])} trades starting {str(row["start_time"])[:10]}: PnL = {row["total_pnl"]:.2f}')

# ============================================
# 5. EXIT REASON BREAKDOWN
# ============================================
print()
print('=' * 60)
print('5. EXIT REASON BREAKDOWN')
print('=' * 60)
exit_counts = df.groupby('exit_reason').agg({
    'pnl': ['count', 'sum', 'mean'],
    'duration_bars': 'mean'
}).reset_index()
exit_counts.columns = ['reason', 'count', 'total_pnl', 'avg_pnl', 'avg_duration_bars']
exit_counts['pct'] = exit_counts['count'] / len(df) * 100
for _, row in exit_counts.iterrows():
    print(f'   {row["reason"]}: {int(row["count"])} trades ({row["pct"]:.1f}%)')
    print(f'      Total PnL: {row["total_pnl"]:.2f}, Avg PnL: {row["avg_pnl"]:.2f}')
    print(f'      Avg Duration: {row["avg_duration_bars"]:.1f} bars')

# ============================================
# 6. WORST DAYS ANALYSIS
# ============================================
print()
print('=' * 60)
print('6. WORST DAYS ANALYSIS')
print('=' * 60)

daily_pnl = df.groupby('entry_date')['pnl'].sum().sort_values()
print('   Top 10 Worst Days:')
for date, pnl in daily_pnl.head(10).items():
    day_trades = df[df['entry_date'] == date]
    sl_count = len(day_trades[day_trades['exit_reason'] == 'SL'])
    print(f'      {date}: PnL={pnl:.2f}, Trades={len(day_trades)}, SL={sl_count}')

print()
print('   Top 10 Best Days:')
for date, pnl in daily_pnl.tail(10).items():
    day_trades = df[df['entry_date'] == date]
    print(f'      {date}: PnL={pnl:.2f}, Trades={len(day_trades)}')

# ============================================
# 7. DAYS WITH NO TRADES (all filtered)
# ============================================
print()
print('=' * 60)
print('7. TRADING ACTIVITY ANALYSIS')
print('=' * 60)

# Get date range
min_date = df['entry_date'].min()
max_date = df['entry_date'].max()
all_dates = pd.date_range(min_date, max_date, freq='D')

# Exclude weekends
trading_dates = [d.date() for d in all_dates if d.weekday() < 5]
dates_with_trades = set(df['entry_date'].unique())
dates_no_trades = [d for d in trading_dates if d not in dates_with_trades]

print(f'   Date Range: {min_date} to {max_date}')
print(f'   Total Weekdays: {len(trading_dates)}')
print(f'   Days with Trades: {len(dates_with_trades)}')
print(f'   Days without Trades: {len(dates_no_trades)} ({len(dates_no_trades)/len(trading_dates)*100:.1f}%)')

# Show some no-trade days
if dates_no_trades:
    print(f'   Sample No-Trade Days: {dates_no_trades[:10]}')

# Daily trade count distribution
daily_counts = df.groupby('entry_date').size()
print()
print(f'   Daily Trade Count Stats:')
print(f'      Min: {daily_counts.min()}')
print(f'      Max: {daily_counts.max()}')
print(f'      Avg: {daily_counts.mean():.1f}')
print(f'      Median: {daily_counts.median():.1f}')

# ============================================
# 8. SL TIMING - ACTUAL DURATION ANALYSIS
# ============================================
print()
print('=' * 60)
print('8. SL TIMING - ACTUAL DURATION')
print('=' * 60)

# Calculate actual duration from timestamps
df['duration'] = df['exit_time'] - df['entry_time']
df['duration_mins'] = df['duration'].dt.total_seconds() / 60

sl_trades = df[df['exit_reason'] == 'SL'].copy()

print(f'   Total SL trades: {len(sl_trades)}')
print(f'   Duration Stats:')
print(f'      Min: {sl_trades["duration_mins"].min():.0f} mins')
print(f'      Max: {sl_trades["duration_mins"].max():.0f} mins')
print(f'      Avg: {sl_trades["duration_mins"].mean():.0f} mins')
print(f'      Median: {sl_trades["duration_mins"].median():.0f} mins')

# Breakdown by duration
immediate = sl_trades[sl_trades['duration_mins'] <= 15]
short = sl_trades[(sl_trades['duration_mins'] > 15) & (sl_trades['duration_mins'] <= 60)]
medium = sl_trades[(sl_trades['duration_mins'] > 60) & (sl_trades['duration_mins'] <= 180)]
late = sl_trades[sl_trades['duration_mins'] > 180]

print()
print('   SL Timing Breakdown:')
print(f'      Immediate (0-15 min): {len(immediate)} ({len(immediate)/len(sl_trades)*100:.1f}%), PnL: {immediate["pnl"].sum():.2f}')
print(f'      Short (15-60 min):    {len(short)} ({len(short)/len(sl_trades)*100:.1f}%), PnL: {short["pnl"].sum():.2f}')
print(f'      Medium (1-3 hours):   {len(medium)} ({len(medium)/len(sl_trades)*100:.1f}%), PnL: {medium["pnl"].sum():.2f}')
print(f'      Late (>3 hours):      {len(late)} ({len(late)/len(sl_trades)*100:.1f}%), PnL: {late["pnl"].sum():.2f}')

# ============================================
# 9. PATTERN ANALYSIS: Direction Changes
# ============================================
print()
print('=' * 60)
print('9. DIRECTION REVERSAL ANALYSIS')
print('=' * 60)

# Check what happens after direction reversal
df_sorted = df.sort_values('entry_time').reset_index(drop=True)
df_sorted['prev_side'] = df_sorted['side'].shift(1)
df_sorted['direction_changed'] = df_sorted['side'] != df_sorted['prev_side']

reversals = df_sorted[df_sorted['direction_changed'] & df_sorted['prev_side'].notna()]
non_reversals = df_sorted[~df_sorted['direction_changed'] & df_sorted['prev_side'].notna()]

print(f'   Total Trades: {len(df_sorted)}')
print(f'   Direction Reversals: {len(reversals)} ({len(reversals)/len(df_sorted)*100:.1f}%)')
print()

rev_wins = reversals[reversals['pnl'] > 0]
rev_losses = reversals[reversals['exit_reason'] == 'SL']
print(f'   After Reversal:')
print(f'      Win Rate: {len(rev_wins)/len(reversals)*100:.1f}%')
print(f'      SL Hit Rate: {len(rev_losses)/len(reversals)*100:.1f}%')
print(f'      Avg PnL: {reversals["pnl"].mean():.2f}')

non_wins = non_reversals[non_reversals['pnl'] > 0]
non_losses = non_reversals[non_reversals['exit_reason'] == 'SL']
print(f'   Same Direction (continuation):')
print(f'      Win Rate: {len(non_wins)/len(non_reversals)*100:.1f}%')
print(f'      SL Hit Rate: {len(non_losses)/len(non_reversals)*100:.1f}%')
print(f'      Avg PnL: {non_reversals["pnl"].mean():.2f}')

# Analyze SL trades specifically - what was the previous trade?
print()
print('   SL Trades Analysis by Previous Direction:')
sl_after_reversal = reversals[reversals['exit_reason'] == 'SL']
sl_same_dir = non_reversals[non_reversals['exit_reason'] == 'SL']

print(f'      SL after reversal: {len(sl_after_reversal)} trades, Avg PnL: {sl_after_reversal["pnl"].mean():.2f}')
print(f'      SL same direction: {len(sl_same_dir)} trades, Avg PnL: {sl_same_dir["pnl"].mean():.2f}')

# ============================================
# 9b. CONSECUTIVE SAME DIRECTION LOSSES
# ============================================
print()
print('   Consecutive Same-Direction Losses:')
# Find cases where we had multiple SL in same direction consecutively
df_sorted['is_sl'] = df_sorted['exit_reason'] == 'SL'
df_sorted['same_side_as_prev'] = df_sorted['side'] == df_sorted['prev_side']

# Count consecutive SL in same direction
consec_sl_same = []
streak = 0
prev_side = None
for idx, row in df_sorted.iterrows():
    if row['is_sl'] and row['side'] == prev_side:
        streak += 1
    else:
        if streak > 0:
            consec_sl_same.append(streak)
        streak = 1 if row['is_sl'] else 0
    prev_side = row['side'] if row['is_sl'] else prev_side

if streak > 0:
    consec_sl_same.append(streak)

if consec_sl_same:
    print(f'      Max consecutive SL same direction: {max(consec_sl_same)}')
    print(f'      Avg streak: {np.mean(consec_sl_same):.1f}')
    print(f'      Total streaks of 2+: {len([x for x in consec_sl_same if x >= 2])}')

# ============================================
# 10. WIN/LOSS BY TRADE DIRECTION
# ============================================
print()
print('=' * 60)
print('10. WIN/LOSS BY DIRECTION')
print('=' * 60)

for direction in ['LONG', 'SHORT']:
    dir_trades = df[df['side'] == direction]
    wins = dir_trades[dir_trades['pnl'] > 0]
    losses = dir_trades[dir_trades['pnl'] < 0]
    
    print(f'   {direction}:')
    print(f'      Total: {len(dir_trades)} trades')
    print(f'      Win Rate: {len(wins)/len(dir_trades)*100:.1f}%')
    print(f'      Total PnL: {dir_trades["pnl"].sum():.2f}')
    print(f'      Avg Win: {wins["pnl"].mean():.2f}' if len(wins) > 0 else '      Avg Win: N/A')
    print(f'      Avg Loss: {losses["pnl"].mean():.2f}' if len(losses) > 0 else '      Avg Loss: N/A')

# ============================================
# 11. MONTHLY PERFORMANCE
# ============================================
print()
print('=' * 60)
print('11. MONTHLY PERFORMANCE')
print('=' * 60)

df['entry_month'] = pd.to_datetime(df['entry_time']).dt.to_period('M')
monthly = df.groupby('entry_month').agg({
    'pnl': ['sum', 'count'],
    'exit_reason': lambda x: (x == 'SL').sum()
}).reset_index()
monthly.columns = ['month', 'pnl', 'trades', 'sl_count']
monthly['win_rate'] = (monthly['trades'] - monthly['sl_count']) / monthly['trades'] * 100

neg_months = monthly[monthly['pnl'] < 0]
print(f'   Total Months: {len(monthly)}')
print(f'   Negative Months: {len(neg_months)}')
print()

if len(neg_months) > 0:
    print('   Negative Months Detail:')
    for _, row in neg_months.iterrows():
        print(f'      {row["month"]}: PnL={row["pnl"]:.2f}, Trades={int(row["trades"])}, SL={int(row["sl_count"])}')
else:
    print('   ALL MONTHS POSITIVE!')
    
print()
print('   Monthly Stats:')
print(f'      Avg Monthly PnL: {monthly["pnl"].mean():.2f}')
print(f'      Best Month: {monthly.loc[monthly["pnl"].idxmax(), "month"]} ({monthly["pnl"].max():.2f})')
print(f'      Worst Month: {monthly.loc[monthly["pnl"].idxmin(), "month"]} ({monthly["pnl"].min():.2f})')
