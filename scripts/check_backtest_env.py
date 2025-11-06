from dotenv import load_dotenv
import os

load_dotenv()

print("=== BACKTEST CONFIGURATION CHECK ===")
print()

required = ['BACKTEST_SYMBOL', 'BACKTEST_START_DATE', 'BACKTEST_END_DATE']
missing = [v for v in required if not os.getenv(v)]

if missing:
    print(f"[ERROR] Missing required vars: {missing}")
else:
    print("[OK] All required vars present")
    
print()
print("Current values:")
print(f"  BACKTEST_SYMBOL: {os.getenv('BACKTEST_SYMBOL', 'NOT SET')}")
print(f"  BACKTEST_VENUE: {os.getenv('BACKTEST_VENUE', 'NOT SET')}")
print(f"  BACKTEST_START_DATE: {os.getenv('BACKTEST_START_DATE', 'NOT SET')}")
print(f"  BACKTEST_END_DATE: {os.getenv('BACKTEST_END_DATE', 'NOT SET')}")
print(f"  BACKTEST_BAR_SPEC: {os.getenv('BACKTEST_BAR_SPEC', 'NOT SET')}")
print(f"  BACKTEST_FAST_PERIOD: {os.getenv('BACKTEST_FAST_PERIOD', 'NOT SET')}")
print(f"  BACKTEST_SLOW_PERIOD: {os.getenv('BACKTEST_SLOW_PERIOD', 'NOT SET')}")
print(f"  BACKTEST_STOP_LOSS_PIPS: {os.getenv('BACKTEST_STOP_LOSS_PIPS', 'NOT SET')}")
print(f"  BACKTEST_TAKE_PROFIT_PIPS: {os.getenv('BACKTEST_TAKE_PROFIT_PIPS', 'NOT SET')}")
print(f"  STRATEGY_DMI_ENABLED: {os.getenv('STRATEGY_DMI_ENABLED', 'NOT SET')}")
print(f"  STRATEGY_STOCH_ENABLED: {os.getenv('STRATEGY_STOCH_ENABLED', 'NOT SET')}")
print(f"  STRATEGY_STOCH_PERIOD_K: {os.getenv('STRATEGY_STOCH_PERIOD_K', 'NOT SET')}")
print(f"  STRATEGY_STOCH_PERIOD_D: {os.getenv('STRATEGY_STOCH_PERIOD_D', 'NOT SET')}")

