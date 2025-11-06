"""
Check what Phase 6 actually used for configuration.
The grid_search.py doesn't control time_filter, so it would use env defaults.
"""
import pandas as pd
from pathlib import Path

# Check Phase 6 CSV to see what was actually used
csv_file = Path("optimization/results/phase6_refinement_results.csv")
if csv_file.exists():
    df = pd.read_csv(csv_file)
    row = df[df['run_id'] == 21]
    
    if len(row) > 0:
        print("=" * 80)
        print("PHASE 6 RUN_ID 21 ACTUAL CONFIGURATION")
        print("=" * 80)
        print()
        print("Parameters from optimization results:")
        print(f"  fast_period: {row['fast_period'].values[0]}")
        print(f"  slow_period: {row['slow_period'].values[0]}")
        print(f"  dmi_enabled: {row['dmi_enabled'].values[0]}")
        print(f"  stoch_enabled: {row['stoch_enabled'].values[0]}")
        print()
        print("Results:")
        print(f"  total_pnl: ${row['total_pnl'].values[0]:.2f}")
        print(f"  sharpe_ratio: {row['sharpe_ratio'].values[0]:.3f}")
        print(f"  trade_count: {row['trade_count'].values[0]}")
        print()
        
        # Check if trend_filter or entry_timing are in the CSV
        if 'trend_filter_enabled' in df.columns:
            print(f"  trend_filter_enabled: {row['trend_filter_enabled'].values[0]}")
        if 'entry_timing_enabled' in df.columns:
            print(f"  entry_timing_enabled: {row['entry_timing_enabled'].values[0]}")
        
        # Note: time_filter is NOT in ParameterSet, so it wasn't controlled by Phase 6
        print()
        print("NOTE: time_filter_enabled is NOT in ParameterSet dataclass.")
        print("      Phase 6 would have used whatever was in environment variables.")
        print("      Default in BacktestConfig is False, so Phase 6 likely had time_filter disabled.")
    else:
        print("Run ID 21 not found in Phase 6 results")
else:
    print(f"Phase 6 results CSV not found: {csv_file}")

