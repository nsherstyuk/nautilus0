"""
Phase 0: Download Missing Historical Data

This script guides you through downloading the historical data needed
for proper train/validation/forward testing.

Current situation:
- You have: 2023-12-27 → 2025-11-04 (mostly 2024-2025)
- You need: 2022-01-01 → 2023-12-31 (discovery period)

This will download ~70,000 bars (15-minute) in 60-day chunks.
Estimated time: 15-20 minutes.
"""

import subprocess
import sys
from pathlib import Path

def main():
    print("=" * 80)
    print("PHASE 0: DATA INGESTION FOR PNL IMPROVEMENT")
    print("=" * 80)
    print()
    
    print("📊 Current Status:")
    print("  - Validation (2024): ✅ Complete")
    print("  - Forward (2025): ✅ Complete")
    print("  - Discovery (2022-2023): ❌ Missing")
    print()
    
    print("🎯 Goal:")
    print("  Download 2022-2023 data to enable proper out-of-sample validation")
    print()
    
    print("📋 Prerequisites:")
    print("  1. IB Gateway or TWS is running")
    print("  2. You have forex market data subscription")
    print("  3. .env file updated with DATA_* settings")
    print()
    
    print("⏱️  Estimated Time: 15-20 minutes")
    print("💾 Data Size: ~70,000 bars (15-minute, EUR/USD)")
    print()
    
    response = input("Ready to proceed? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("\n❌ Cancelled. Run this script when ready.")
        return
    
    print()
    print("=" * 80)
    print("STEP 1: Verify Current Coverage")
    print("=" * 80)
    print()
    
    try:
        subprocess.run([sys.executable, "check_data_coverage_for_validation.py"], check=True)
    except subprocess.CalledProcessError:
        print("\n⚠️  Coverage check failed, but continuing...")
    
    print()
    print("=" * 80)
    print("STEP 2: Download Historical Data")
    print("=" * 80)
    print()
    print("Starting data ingestion...")
    print("This will download in chunks. Watch for progress messages.")
    print()
    
    try:
        result = subprocess.run(
            [sys.executable, "data/ingest_historical.py"],
            check=True,
            capture_output=False
        )
        
        print()
        print("=" * 80)
        print("✅ DATA DOWNLOAD COMPLETE")
        print("=" * 80)
        print()
        
    except subprocess.CalledProcessError as e:
        print()
        print("=" * 80)
        print("❌ DATA DOWNLOAD FAILED")
        print("=" * 80)
        print()
        print("Possible issues:")
        print("  1. IB Gateway/TWS not running")
        print("  2. No market data subscription")
        print("  3. Connection timeout")
        print()
        print("Check logs/data_ingestion.log for details")
        return
    
    print()
    print("=" * 80)
    print("STEP 3: Verify Final Coverage")
    print("=" * 80)
    print()
    
    try:
        subprocess.run([sys.executable, "check_data_coverage_for_validation.py"], check=True)
    except subprocess.CalledProcessError:
        print("\n⚠️  Coverage check failed")
        return
    
    print()
    print("=" * 80)
    print("🎉 PHASE 0 COMPLETE!")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Review plan_pnl_improvement.md")
    print("  2. Proceed to Phase 1: Baseline validation")
    print("  3. Run backtests on 2022-2023 (discovery)")
    print("  4. Compare against 2024 (validation) and 2025 (forward)")
    print()
    print("Expected outcome:")
    print("  Your current $10.9k config will likely UNDERPERFORM on 2022-2023")
    print("  because the aggressive time filter is overfit to 2024-2025.")
    print()

if __name__ == "__main__":
    main()
