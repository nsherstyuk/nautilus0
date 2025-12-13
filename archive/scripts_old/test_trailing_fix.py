#!/usr/bin/env python3
"""
Test script to verify trailing stop fix v2.6 works correctly.
Runs a short backtest and analyzes logs for trailing stop activity.
"""

import subprocess
import sys
from pathlib import Path
import re
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent

def run_test_backtest():
    """Run a short backtest to test trailing stops."""
    print("=" * 80)
    print("TESTING TRAILING STOP FIX v2.6")
    print("=" * 80)
    print()
    print("Running 1-month backtest (2025-01-08 to 2025-02-08)...")
    print()
    
    # Run backtest
    cmd = [
        sys.executable,
        "backtest/run_backtest.py"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        return result.returncode == 0, result.stdout, result.stderr
        
    except Exception as e:
        print(f"ERROR running backtest: {e}")
        return False, "", str(e)

def analyze_logs_for_trailing():
    """Analyze application.log for trailing stop activity."""
    log_file = PROJECT_ROOT / "logs" / "application.log"
    
    if not log_file.exists():
        print(f"WARNING: Log file not found: {log_file}")
        return None
    
    print("=" * 80)
    print("ANALYZING LOGS FOR TRAILING STOP ACTIVITY")
    print("=" * 80)
    print()
    
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        log_content = f.read()
    
    # Check for fix version
    version_match = re.search(r'TRAILING STOP FIX v(\d+\.\d+)', log_content)
    if version_match:
        print(f"[OK] Found fix version: v{version_match.group(1)}")
    else:
        print("[WARN] No fix version found in logs")
    
    # Count trailing activations
    activations = len(re.findall(r'TRAILING ACTIVATED', log_content, re.IGNORECASE))
    print(f"[OK] Trailing activations: {activations}")
    
    # Count order modifications
    modifications = len(re.findall(r'MODIFYING ORDER', log_content, re.IGNORECASE))
    print(f"[OK] Order modifications: {modifications}")
    
    # Count order reference clears
    clears = len(re.findall(r'order reference cleared for re-discovery', log_content, re.IGNORECASE))
    print(f"[OK] Order reference clears: {clears}")
    
    # Check for stale order issues
    stale_issues = len(re.findall(r'STILL no stop order|ABORTING trailing', log_content, re.IGNORECASE))
    print(f"[WARN] Stale order issues: {stale_issues}")
    
    # Find example modification sequences
    print()
    print("=" * 80)
    print("SAMPLE TRAILING ACTIVITY")
    print("=" * 80)
    
    # Find modification sequences
    mod_pattern = r'MODIFYING ORDER.*?\n.*?Old trigger.*?\n.*?New trigger.*?\n.*?order reference cleared'
    matches = re.findall(mod_pattern, log_content, re.DOTALL | re.IGNORECASE)
    
    if matches:
        print(f"\nFound {len(matches)} complete modification sequences:")
        for i, match in enumerate(matches[:3], 1):  # Show first 3
            print(f"\n--- Sequence {i} ---")
            lines = match.split('\n')
            for line in lines[:5]:  # Show first 5 lines
                if line.strip():
                    print(f"  {line.strip()}")
    else:
        print("\n⚠ No complete modification sequences found")
    
    # Check for multiple modifications per position
    print()
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    success_criteria = {
        "Fix version present": version_match is not None,
        "Trailing activations > 0": activations > 0,
        "Order modifications > 0": modifications > 0,
        "Order reference clears > 0": clears > 0,
        "No stale order issues": stale_issues == 0,
        "Multiple modifications": modifications >= activations,  # Should have at least 1 mod per activation
    }
    
    for criterion, passed in success_criteria.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}: {criterion}")
    
    all_passed = all(success_criteria.values())
    
    return {
        "version": version_match.group(1) if version_match else None,
        "activations": activations,
        "modifications": modifications,
        "clears": clears,
        "stale_issues": stale_issues,
        "all_passed": all_passed
    }

def check_backtest_results():
    """Check the most recent backtest results folder."""
    results_dir = PROJECT_ROOT / "logs" / "backtest_results"
    
    if not results_dir.exists():
        print(f"WARNING: Results directory not found: {results_dir}")
        return None
    
    # Find most recent folder
    folders = sorted([f for f in results_dir.iterdir() if f.is_dir()], 
                     key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not folders:
        print("WARNING: No backtest result folders found")
        return None
    
    latest_folder = folders[0]
    print()
    print("=" * 80)
    print(f"CHECKING LATEST BACKTEST RESULTS: {latest_folder.name}")
    print("=" * 80)
    print()
    
    # Check positions.csv for trailing stop evidence
    positions_file = latest_folder / "positions.csv"
    if positions_file.exists():
        import pandas as pd
        try:
            df = pd.read_csv(positions_file)
            print(f"[OK] Found {len(df)} positions")
            
            # Check if any positions have multiple stop orders (evidence of trailing)
            orders_file = latest_folder / "orders.csv"
            if orders_file.exists():
                orders_df = pd.read_csv(orders_file)
                stop_orders = orders_df[orders_df['order_type'].str.contains('STOP', case=False, na=False)]
                
                # Count unique stop orders per position
                if 'position_id' in stop_orders.columns:
                    stops_per_position = stop_orders.groupby('position_id').size()
                    multiple_stops = (stops_per_position > 1).sum()
                    
                    print(f"[OK] Positions with multiple stop orders: {multiple_stops}")
                    print(f"[OK] Average stop orders per position: {stops_per_position.mean():.2f}")
                    print(f"[OK] Max stop orders for one position: {stops_per_position.max()}")
                    
                    if multiple_stops > 0:
                        print("\n[SUCCESS] Found evidence of trailing stops (multiple stop orders)")
                    else:
                        print("\n[WARN] No positions with multiple stop orders found")
                else:
                    print("[WARN] Could not analyze stop orders (missing position_id column)")
            else:
                print("[WARN] orders.csv not found")
        except Exception as e:
            print(f"ERROR reading positions.csv: {e}")
                
        except Exception as e:
            print(f"ERROR reading positions.csv: {e}")
    else:
        print("⚠ positions.csv not found")
    
    return latest_folder

def main():
    """Main test function."""
    print()
    print("=" * 80)
    print("TRAILING STOP FIX v2.6 VERIFICATION TEST")
    print("=" * 80)
    print()
    
    # Step 1: Run backtest
    print("STEP 1: Running backtest...")
    success, stdout, stderr = run_test_backtest()
    
    if not success:
        print("ERROR: Backtest failed!")
        print("\nSTDOUT:")
        print(stdout[-2000:] if len(stdout) > 2000 else stdout)
        print("\nSTDERR:")
        print(stderr[-2000:] if len(stderr) > 2000 else stderr)
        return 1
    
    print("[OK] Backtest completed successfully")
    print()
    
    # Step 2: Analyze logs
    print("STEP 2: Analyzing logs...")
    log_analysis = analyze_logs_for_trailing()
    
    # Step 3: Check results
    print()
    print("STEP 3: Checking backtest results...")
    results_folder = check_backtest_results()
    
    # Final summary
    print()
    print("=" * 80)
    print("FINAL VERIFICATION RESULT")
    print("=" * 80)
    print()
    
    if log_analysis and log_analysis.get("all_passed"):
        print("[SUCCESS] ALL TESTS PASSED - Trailing stop fix appears to be working!")
        print()
        print("Evidence:")
        print(f"  - Fix version: v{log_analysis.get('version', 'unknown')}")
        print(f"  - Trailing activations: {log_analysis.get('activations', 0)}")
        print(f"  - Order modifications: {log_analysis.get('modifications', 0)}")
        print(f"  - Order reference clears: {log_analysis.get('clears', 0)}")
        print(f"  - No stale order issues: {log_analysis.get('stale_issues', 0) == 0}")
        return 0
    else:
        print("[FAIL] SOME TESTS FAILED - Trailing stop fix may not be working")
        print()
        if log_analysis:
            print("Issues found:")
            if log_analysis.get('activations', 0) == 0:
                print("  - No trailing activations found")
            if log_analysis.get('modifications', 0) == 0:
                print("  - No order modifications found")
            if log_analysis.get('stale_issues', 0) > 0:
                print(f"  - {log_analysis.get('stale_issues')} stale order issues found")
        return 1

if __name__ == "__main__":
    sys.exit(main())

