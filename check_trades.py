import pandas as pd

df = pd.read_csv('backtest_results/MTF_V2_20251227_201338/trades.csv')
df['entry_time'] = pd.to_datetime(df['entry_time'])

print(f'Total trades: {len(df)}')
print(f'Date range: {df["entry_time"].min()} to {df["entry_time"].max()}')

# Check trades by month
df['month'] = df['entry_time'].dt.to_period('M')
monthly_counts = df.groupby('month').size()
print('\nTrades by month:')
for month, count in monthly_counts.items():
    print(f'  {month}: {count} trades')

# Check specifically for August trades
august_trades = df[df['entry_time'].dt.month == 8]
print(f'\nAugust trades: {len(august_trades)}')
if len(august_trades) > 0:
    print(f'August range: {august_trades["entry_time"].min()} to {august_trades["entry_time"].max()}')
    
    # Check trades around Aug 5-6
    early_aug = august_trades[august_trades['entry_time'] <= pd.Timestamp('2025-08-10')]
    print(f'Early August (Aug 1-10) trades: {len(early_aug)}')
    
    if len(early_aug) > 0:
        print('Early August trade dates:')
        for idx, row in early_aug.iterrows():
            print(f'  {row["entry_time"]}: {row["side"]} @ {row["entry_price"]}')
