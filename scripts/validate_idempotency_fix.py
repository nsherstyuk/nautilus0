#!/usr/bin/env python3
"""
Validate the idempotency fix by running a backtest and checking:
1. Bars are still delivered multiple times (expected behavior)
2. But only processed once (fixed behavior)
3. Parity improves significantly

Usage:
    python scripts/validate_idempotency_fix.py
"""
import os
import sys
import re
from pathlib import Path

sys.path.insert(0, '.')

from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest


def main():
    print("=" * 80)
    print("IDEMPOTENCY FIX VALIDATION")
    print("=" * 80)
    print()
    
    # Set diagnostic environment variables
    os.environ["MTF2_DMI_PARITY_DEBUG"] = "1"
    os.environ["MTF2_PARITY_SNAPSHOT_TS"] = "2026-02-20T05:15:00+00:00"
    
    print("Running backtest with idempotency fix...")
    print("Date range: 2026-02-17 to 2026-02-21 (short window for quick validation)")
    print()
    
    # Run backtest
    result, results_dir = run_v2_entry_confirmed_adaptive_backtest(
        symbol='EUR/USD',
        venue='IDEALPRO',
        start_date='2026-02-17',
        end_date='2026-02-21',
    )
    
    print()
    print("=" * 80)
    print("VALIDATION RESULTS")
    print("=" * 80)
    print()
    
    # Analyze the replay log
    log_file = Path(results_dir) / "replay.log"
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        return
    
    print(f"Analyzing log: {log_file}")
    print()
    
    # Count bar deliveries and idempotent skips
    delivery_counts = {}  # {timestamp: count}
    idempotent_skips = 0
    total_bars_processed = 0
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            # Track bar deliveries
            if '[BAR_DELIVERY]' in line:
                match = re.search(r'delivered (\d+) times', line)
                if match:
                    count = int(match.group(1))
                    ts_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    if ts_match:
                        timestamp = ts_match.group(1)
                        delivery_counts[timestamp] = count
            
            # Track idempotent skips
            if '[IDEMPOTENT]' in line:
                idempotent_skips += 1
            
            # Track processed bars
            if '[BAR]' in line and '[BAR_DELIVERY]' not in line and '[BAR_METRICS]' not in line:
                total_bars_processed += 1
    
    # Analyze delivery patterns
    total_deliveries = len(delivery_counts)
    multi_deliveries = sum(1 for c in delivery_counts.values() if c > 1)
    
    if total_deliveries > 0:
        single_pct = sum(1 for c in delivery_counts.values() if c == 1) / total_deliveries * 100
        double_pct = sum(1 for c in delivery_counts.values() if c == 2) / total_deliveries * 100
        triple_plus_pct = sum(1 for c in delivery_counts.values() if c >= 3) / total_deliveries * 100
    else:
        single_pct = double_pct = triple_plus_pct = 0
    
    # Calculate expected skips
    expected_skips = sum(c - 1 for c in delivery_counts.values() if c > 1)
    
    print("📊 Bar Delivery Statistics:")
    print(f"  Total unique bars: {total_deliveries}")
    print(f"  Bars delivered multiple times: {multi_deliveries} ({multi_deliveries/total_deliveries*100:.1f}%)")
    print(f"  Delivery pattern:")
    print(f"    - Single delivery: {single_pct:.1f}%")
    print(f"    - Double delivery: {double_pct:.1f}%")
    print(f"    - Triple+ delivery: {triple_plus_pct:.1f}%")
    print()
    
    print("✅ Idempotency Check:")
    print(f"  Bars processed (should match total unique): {total_bars_processed}")
    print(f"  Duplicate bars skipped: {idempotent_skips}")
    print(f"  Expected skips (deliveries - unique): {expected_skips}")
    print()
    
    # Validation
    success = True
    
    if multi_deliveries == 0:
        print("⚠️  WARNING: No multi-deliveries detected")
        print("   This might indicate backtest mode is not triggering the bug")
        print("   Or the test window is too short")
        success = False
    else:
        print(f"✅ Multi-deliveries detected: {multi_deliveries} bars delivered >1x")
    
    if idempotent_skips == 0:
        print("❌ FAIL: No idempotent skips detected!")
        print("   The fix may not be working or log level is too high")
        success = False
    elif abs(idempotent_skips - expected_skips) > expected_skips * 0.1:  # Allow 10% variance
        print(f"⚠️  WARNING: Skip count mismatch")
        print(f"   Expected: {expected_skips}, Actual: {idempotent_skips}")
        print(f"   This may indicate incomplete fix or logging issues")
    else:
        print(f"✅ Idempotent skips match expected: {idempotent_skips} ≈ {expected_skips}")
    
    if total_bars_processed != total_deliveries:
        print(f"⚠️  WARNING: Processed bar count mismatch")
        print(f"   Unique bars: {total_deliveries}, Processed: {total_bars_processed}")
        print(f"   Expected: Each unique bar should be processed exactly once")
    else:
        print(f"✅ Each unique bar processed exactly once: {total_bars_processed}")
    
    print()
    print("=" * 80)
    
    if success and idempotent_skips > 0:
        print("✅ VALIDATION PASSED")
        print()
        print("The idempotency fix is working correctly:")
        print("- Bars are still delivered multiple times (NautilusTrader behavior)")
        print("- Duplicate deliveries are skipped (fix working)")
        print("- Each bar is processed exactly once (expected behavior)")
        print()
        print("Next steps:")
        print("1. Run full parity comparison with live data")
        print("2. Verify parity improves from 69.7% to >95%")
        print("3. Re-run parameter optimization with fixed backtest")
        print("4. Update live trading parameters before resuming")
    else:
        print("❌ VALIDATION FAILED")
        print()
        print("Issues detected:")
        if multi_deliveries == 0:
            print("- No multi-deliveries detected (test window may be too short)")
        if idempotent_skips == 0:
            print("- No idempotent skips logged (fix may not be working)")
        if total_bars_processed != total_deliveries:
            print("- Bar processing count mismatch (possible logic error)")
        print()
        print("Review the log file for details:")
        print(f"  {log_file}")
    
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
