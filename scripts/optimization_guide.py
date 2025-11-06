"""
Guide: Analyzing TP/SL Impact and Comprehensive Grid Optimization

This document answers:
1. How to see if PnL could be improved by changing TP, SL, trailing stop activation
2. How to run grid optimization with all currently available parameters  
3. Should excluded hours be included in optimization?

ANALYSIS APPROACH:
"""

from pathlib import Path
import pandas as pd
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 100)
print("GUIDE: TP/SL OPTIMIZATION & GRID SEARCH")
print("=" * 100)
print()

print("1. ANALYZING TP/SL IMPACT FROM EXISTING BACKTEST")
print("-" * 100)
print()
print("You can analyze TP/SL impact from your latest backtest results:")
print()
print("  python scripts/analyze_hourly_profitability.py")
print()
print("To see TP/SL impact on profitability, check:")
print("  - Avg winner vs avg loser in positions.csv")
print("  - Win rate vs profit factor")
print("  - Individual trade outcomes")
print()

print("2. RUNNING GRID OPTIMIZATION WITH ALL PARAMETERS")
print("-" * 100)
print()
print("Current available parameters for optimization:")
print("  - Risk Management: stop_loss_pips, take_profit_pips,")
print("                     trailing_stop_activation_pips, trailing_stop_distance_pips")
print("  - MA Parameters: fast_period, slow_period, crossover_threshold_pips")
print("  - Filters: dmi_enabled, dmi_period, stoch_enabled, stoch_period_k,")
print("             stoch_period_d, stoch_bullish_threshold, stoch_bearish_threshold")
print("  - Multi-timeframe: trend_filter_enabled, entry_timing_enabled (and related)")
print()
print("To run grid optimization:")
print()
print("  1. Create/edit YAML config file:")
print("     optimization/configs/comprehensive_optimization.yaml")
print()
print("  2. Set environment variables:")
print("     $env:BACKTEST_SYMBOL = 'EUR/USD'")
print("     $env:BACKTEST_START_DATE = '2025-01-01'")
print("     $env:BACKTEST_END_DATE = '2025-07-31'")
print("     $env:BACKTEST_VENUE = 'IDEALPRO'")
print("     $env:BACKTEST_BAR_SPEC = '1-MINUTE-MID-EXTERNAL'")
print("     $env:CATALOG_PATH = 'data/historical'")
print("     $env:OUTPUT_DIR = 'logs/backtest_results'")
print()
print("  3. Run grid search:")
print("     python optimization/grid_search.py \\")
print("       --config optimization/configs/comprehensive_optimization.yaml \\")
print("       --objective total_pnl \\")
print("       --workers 8 \\")
print("       --output optimization/results/comprehensive_results.csv")
print()

print("3. EXCLUDED HOURS IN OPTIMIZATION")
print("-" * 100)
print()
print("CURRENT STATUS: Excluded hours is NOT currently supported as an optimization parameter.")
print()
print("REASON: Excluded hours is a list of integers (0-23), which creates:")
print("  - Combinatorial explosion (2^24 possible combinations)")
print("  - Difficult to optimize (discrete set selection vs continuous range)")
print("  - Better optimized separately using hourly profitability analysis")
print()
print("RECOMMENDATION:")
print("  1. FIRST: Fix excluded hours based on hourly profitability analysis")
print("     (Use scripts/verify_excluded_hours.py to identify unprofitable hours)")
print()
print("  2. THEN: Run grid optimization with correct excluded hours as FIXED parameter")
print("     (Include BACKTEST_EXCLUDED_HOURS in 'fixed' section of YAML config)")
print()
print("  3. OPTIONAL: If you want to optimize excluded hours, consider:")
print("     - Pre-filtering: Only test combinations of hours that are consistently")
print("       unprofitable across multiple backtests")
print("     - Separate optimization: Optimize excluded hours separately using")
print("       a simpler brute-force approach")
print("     - Genetic algorithm: Use evolutionary algorithm for set selection")
print()

print("=" * 100)
print("NEXT STEPS")
print("=" * 100)
print()
print("1. Fix excluded hours using verification script:")
print("   python scripts/verify_excluded_hours.py")
print()
print("2. Update .env with correct excluded hours")
print()
print("3. Create comprehensive optimization config (see next section)")
print()
print("4. Run grid optimization with fixed excluded hours")
print()

