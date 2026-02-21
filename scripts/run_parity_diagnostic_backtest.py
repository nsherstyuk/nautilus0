#!/usr/bin/env python3
"""
Run backtest with parity diagnostics enabled.

Exports:
- Bar delivery counts
- Feature DataFrame snapshots at specified timestamp
- Detailed BAR_DELIVERY logs
"""
import os
import sys
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, '.')

from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest


def main():
    # Configure snapshot timestamp (comparison window start)
    snapshot_timestamp = "2026-02-20T05:15:00+00:00"
    
    print(f"Running parity diagnostic backtest...")
    print(f"Snapshot export timestamp: {snapshot_timestamp}")
    print(f"DMI parity debug: ENABLED")
    print()
    
    # Set environment variables
    os.environ["MTF2_DMI_PARITY_DEBUG"] = "1"
    os.environ["MTF2_PARITY_SNAPSHOT_TS"] = snapshot_timestamp
    
    # Run backtest with extended warmup
    result, path = run_v2_entry_confirmed_adaptive_backtest(
        symbol='EUR/USD',
        venue='IDEALPRO',
        start_date='2026-02-15',
        end_date='2026-02-21',
    )
    
    print()
    print("="*80)
    print("Backtest Complete")
    print("="*80)
    print(f"Results directory: {path}")
    print()
    print("Generated files:")
    print(f"  - {path}/replay.log (contains [BAR_DELIVERY] and [BAR_METRICS] logs)")
    print(f"  - parity_snapshots/features_15m_replay_*.csv")
    print(f"  - parity_snapshots/features_30m_replay_*.csv")
    print(f"  - parity_snapshots/bar_delivery_replay_*.csv")
    print()
    print("Next steps:")
    print("  1. Run live trading with same env vars to generate live snapshots")
    print("  2. Compare CSV files using scripts/compare_feature_snapshots.py")
    print("  3. Analyze bar delivery counts")
    

if __name__ == '__main__':
    main()
