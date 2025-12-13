"""Estimate when to expect first live trade."""
from datetime import datetime, timedelta

# Live system started
live_start = datetime(2025, 11, 20, 13, 33)
now = datetime.now()
hours_running = (now - live_start).total_seconds() / 3600

print('=' * 80)
print('LIVE TRADING TIME ESTIMATE')
print('=' * 80)
print(f'Live system started: {live_start:%Y-%m-%d %H:%M}')
print(f'Current time: {now:%Y-%m-%d %H:%M}')
print(f'Hours running: {hours_running:.1f} hours ({hours_running/24:.1f} days)')
print()
print('Based on backtest statistics:')
print('  - Median time between trades: 61.8 hours (2.6 days)')
print('  - Mean time between trades: 77.5 hours (3.2 days)')
print('  - 25th percentile: 29.8 hours (1.2 days)')
print('  - 10th percentile: 13.0 hours (0.5 days)')
print()
print('Probability estimate:')
print(f'  - 10% chance you see a trade within: 13 hours')
print(f'  - 25% chance you see a trade within: 30 hours (1.2 days)')
print(f'  - 50% chance you see a trade within: 62 hours (2.6 days)')
print(f'  - You have waited: {hours_running:.1f} hours so far')
print()
print('RECOMMENDATION:')
if hours_running < 13:
    print(f'  Still early - only {hours_running:.1f} hours elapsed.')
    print(f'  Wait at least 13 hours (10th percentile) before expecting a trade.')
    remaining = 13 - hours_running
    print(f'  Estimated wait: {remaining:.1f} more hours')
elif hours_running < 30:
    print(f'  {hours_running:.1f} hours elapsed - within normal range.')
    print(f'  25% of trades happen within 30 hours.')
    remaining = 30 - hours_running
    print(f'  Should see a trade within: {remaining:.1f} more hours (25% threshold)')
else:
    print(f'  {hours_running:.1f} hours elapsed - getting closer to median.')
    print(f'  50% chance of trade within 62 hours total.')
    remaining = 62 - hours_running
    if remaining > 0:
        print(f'  Should see a trade within: {remaining:.1f} more hours (median)')
    else:
        print(f'  Past median - trade could happen any time!')
