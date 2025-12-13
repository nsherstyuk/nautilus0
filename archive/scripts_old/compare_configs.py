from dotenv import dotenv_values

bt = dotenv_values('.env')
live = dotenv_values('.env.live')

print('=' * 80)
print('BACKTEST vs LIVE CONFIGURATION COMPARISON')
print('=' * 80)

comparisons = [
    ('STOP LOSS (pips)', 'BACKTEST_STOP_LOSS_PIPS', 'LIVE_STOP_LOSS_PIPS'),
    ('TAKE PROFIT (pips)', 'BACKTEST_TAKE_PROFIT_PIPS', 'LIVE_TAKE_PROFIT_PIPS'),
    ('TRAILING ACTIVATION (pips)', 'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS', 'LIVE_TRAILING_STOP_ACTIVATION_PIPS'),
    ('TRAILING DISTANCE (pips)', 'BACKTEST_TRAILING_STOP_DISTANCE_PIPS', 'LIVE_TRAILING_STOP_DISTANCE_PIPS'),
    ('', '', ''),
    ('TIME FILTER ENABLED', 'BACKTEST_TIME_FILTER_ENABLED', 'LIVE_TIME_FILTER_ENABLED'),
    ('EXCLUDED HOURS', 'BACKTEST_EXCLUDED_HOURS', 'LIVE_EXCLUDED_HOURS'),
    ('EXCLUDED HOURS MODE', 'BACKTEST_EXCLUDED_HOURS_MODE', 'LIVE_EXCLUDED_HOURS_MODE'),
    ('', '', ''),
    ('DMI FILTER ENABLED', 'STRATEGY_DMI_ENABLED', 'LIVE_DMI_ENABLED'),
    ('STOCH FILTER ENABLED', 'STRATEGY_STOCH_ENABLED', 'LIVE_STOCH_ENABLED'),
    ('RSI FILTER ENABLED', 'STRATEGY_RSI_ENABLED', 'LIVE_RSI_ENABLED'),
    ('ATR FILTER ENABLED', 'STRATEGY_ATR_ENABLED', 'LIVE_ATR_ENABLED'),
    ('VOLUME FILTER ENABLED', 'STRATEGY_VOLUME_ENABLED', 'LIVE_VOLUME_ENABLED'),
    ('TREND FILTER ENABLED', 'STRATEGY_TREND_FILTER_ENABLED', 'LIVE_TREND_FILTER_ENABLED'),
    ('', '', ''),
    ('PARTIAL1 ENABLED', 'STRATEGY_PARTIAL1_ENABLED', 'LIVE_PARTIAL1_ENABLED'),
    ('PARTIAL1 FRACTION', 'STRATEGY_PARTIAL1_FRACTION', 'LIVE_PARTIAL1_FRACTION'),
    ('PARTIAL1 THRESHOLD (pips)', 'STRATEGY_PARTIAL1_THRESHOLD_PIPS', 'LIVE_PARTIAL1_THRESHOLD_PIPS'),
    ('PARTIAL CLOSE ENABLED', 'STRATEGY_PARTIAL_CLOSE_ENABLED', 'LIVE_PARTIAL_CLOSE_ENABLED'),
    ('PARTIAL CLOSE FRACTION', 'STRATEGY_PARTIAL_CLOSE_FRACTION', 'LIVE_PARTIAL_CLOSE_FRACTION'),
]

mismatches = []

for label, bt_key, live_key in comparisons:
    if not label:
        print()
        continue
    
    bt_val = bt.get(bt_key, 'NOT SET')
    live_val = live.get(live_key, 'NOT SET')
    match = '✓' if bt_val == live_val else '✗'
    
    print(f'{label:35} | Backtest: {bt_val:20} | Live: {live_val:20} | {match}')
    
    if bt_val != live_val:
        mismatches.append((label, bt_val, live_val))

if mismatches:
    print('\n' + '=' * 80)
    print(f'FOUND {len(mismatches)} MISMATCHES:')
    print('=' * 80)
    for label, bt_val, live_val in mismatches:
        print(f'\n{label}:')
        print(f'  Backtest: {bt_val}')
        print(f'  Live:     {live_val}')
else:
    print('\n' + '=' * 80)
    print('✓ ALL SETTINGS MATCH!')
    print('=' * 80)
