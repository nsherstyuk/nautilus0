from dotenv import load_dotenv
import os

load_dotenv()

print("=" * 70)
print("LIVE TRADING TIME FILTER SETTINGS")
print("=" * 70)
print()
print(f"LIVE_TIME_FILTER_ENABLED: {os.getenv('LIVE_TIME_FILTER_ENABLED', 'NOT SET')}")
print(f"LIVE_TRADING_HOURS_START: {os.getenv('LIVE_TRADING_HOURS_START', 'NOT SET')}")
print(f"LIVE_TRADING_HOURS_END: {os.getenv('LIVE_TRADING_HOURS_END', 'NOT SET')}")
print(f"LIVE_TRADING_HOURS_TIMEZONE: {os.getenv('LIVE_TRADING_HOURS_TIMEZONE', 'NOT SET')}")
print(f"LIVE_EXCLUDED_HOURS: {os.getenv('LIVE_EXCLUDED_HOURS', 'NOT SET')}")
print()
print("=" * 70)
print("READY TO RESTART LIVE TRADING")
print("=" * 70)
print()
print("The time filter will exclude these hours from trading:")
excluded = os.getenv('LIVE_EXCLUDED_HOURS', '')
if excluded:
    hours = [h.strip() for h in excluded.split(',')]
    for hour in hours:
        print(f"  - Hour {hour}:00 UTC")
print()
print("Run: python live/run_live.py")

