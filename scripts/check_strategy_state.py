"""
Summarize the current state of the strategy file after revert
"""
from pathlib import Path

strategy_file = Path('strategies/moving_average_crossover.py')
content = strategy_file.read_text(encoding='utf-8')

print('='*80)
print('CURRENT STRATEGY FILE STATE')
print('='*80)
print(f'\nFile: {strategy_file}')
print(f'Size: {len(content)} bytes')
print(f'Lines: {len(content.splitlines())}')

# Check for key features
features = {
    'Dormant Mode': 'dormant_mode_enabled' in content,
    'Time Filter': '_check_time_filter' in content,
    'Trend Filter': '_check_trend_alignment' in content,
    'Entry Timing': '_check_entry_timing' in content,
    'DMI Filter': '_check_dmi_trend' in content,
    'Stochastic Filter': '_check_stochastic_momentum' in content,
    'Excluded Hours': '_excluded_hours_set' in content,
    'Trailing Stop': '_update_trailing_stop' in content,
}

print('\n' + '='*80)
print('FEATURES PRESENT')
print('='*80)
for feature, present in features.items():
    status = 'YES' if present else 'NO'
    print(f'{feature:<25} {status}')

# Check for merge conflict markers
if '<<<<<<<' in content or '=======' in content or '>>>>>>>' in content:
    print('\n' + '='*80)
    print('WARNING: MERGE CONFLICT MARKERS FOUND!')
    print('='*80)
else:
    print('\n' + '='*80)
    print('STATUS: No merge conflict markers found')
    print('='*80)

# Check key methods
print('\n' + '='*80)
print('KEY METHODS')
print('='*80)
methods = ['on_bar', '_on_buy_signal', '_on_sell_signal', '_check_dmi_trend', 
           '_check_stochastic_momentum', '_update_trailing_stop']
for method in methods:
    if f'def {method}' in content:
        print(f'✓ {method}')
    else:
        print(f'✗ {method} - MISSING')






