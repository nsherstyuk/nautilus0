"""
Check the current state of the strategy file and identify merge conflicts
"""
import re
from pathlib import Path

strategy_file = Path('strategies/moving_average_crossover.py')
content = strategy_file.read_text(encoding='utf-8')

# Find merge conflict markers
conflicts = []
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if '<<<<<<< HEAD' in line:
        start = i
    elif '=======' in line and 'start' in locals():
        middle = i
    elif '>>>>>>>' in line and 'middle' in locals():
        end = i
        conflicts.append((start, middle, end))
        del start, middle, end

print('='*80)
print('MERGE CONFLICTS DETECTED')
print('='*80)
print(f'\nFound {len(conflicts)} conflict(s):\n')

for i, (start, middle, end) in enumerate(conflicts, 1):
    print(f'Conflict #{i}: Lines {start}-{end}')
    print('-'*80)
    # Show context around conflict
    context_start = max(0, start - 3)
    context_end = min(len(lines), end + 3)
    for j in range(context_start, context_end):
        marker = ''
        if j == start - 1:
            marker = ' <<<<<<< HEAD'
        elif j == middle - 1:
            marker = ' ======='
        elif j == end - 1:
            marker = ' >>>>>>>'
        print(f'{j+1:4d}: {lines[j]}{marker}')
    print()

# Check for key methods
print('='*80)
print('KEY METHODS CHECK')
print('='*80)

methods_to_check = [
    '_check_time_filter',
    '_check_trend_alignment',
    '_check_entry_timing',
    '_position_has_tp_sl',
    '_check_dmi_trend',
    '_check_stochastic_momentum',
]

for method in methods_to_check:
    pattern = rf'def {method}'
    if re.search(pattern, content):
        print(f'✓ {method} - EXISTS')
    else:
        print(f'✗ {method} - MISSING')

print('\n' + '='*80)
print('DORMANT MODE CHECK')
print('='*80)
if 'dormant_mode_enabled' in content:
    print('✓ dormant_mode_enabled - EXISTS')
else:
    print('✗ dormant_mode_enabled - MISSING')

if '_excluded_hours_set' in content:
    print('✓ _excluded_hours_set - EXISTS')
else:
    print('✗ _excluded_hours_set - MISSING')



