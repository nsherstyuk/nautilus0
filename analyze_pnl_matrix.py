import pandas as pd

# Read the PnL matrix
df = pd.read_csv('backtest_results/MTF_V2_REPLAY_20251224_213359/hour_weekday_pnl_matrix.csv')
df = df.set_index('hour_EST')

print('Hour/Weekday PnL Matrix:')
print(df.to_string())
print('\n' + '='*80)
print('\nNegative PnL hours by weekday:')
print('='*80)

excluded_hours = {}
weekday_map = {
    'Monday': 0,
    'Tuesday': 1,
    'Wednesday': 2,
    'Thursday': 3,
    'Friday': 4,
    'Saturday': 5,
    'Sunday': 6
}

for col in df.columns:
    neg_hours = df[df[col] < 0].index.tolist()
    if neg_hours:
        print(f'{col}: {neg_hours}')
        excluded_hours[weekday_map[col]] = neg_hours

print('\n' + '='*80)
print('\nConfiguration for .env.mtf_v2:')
print('='*80)
print('MTF2_EXCLUDED_HOURS_MODE=weekday')
print('MTF2_CONFIG_TIMEZONE=EST')
print('')

weekday_names = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']
for i, name in enumerate(weekday_names):
    hours = excluded_hours.get(i, [])
    hours_str = ','.join(map(str, hours)) if hours else ''
    print(f'MTF2_EXCLUDED_HOURS_{name}={hours_str}')
