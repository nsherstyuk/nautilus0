#!/usr/bin/env python3
"""
Update .env file with correct date range for 14k PnL baseline.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"

# Correct dates from 14k PnL baseline
CORRECT_START_DATE = "2025-01-08"
CORRECT_END_DATE = "2025-10-03"

def update_env_dates():
    """Update BACKTEST_START_DATE and BACKTEST_END_DATE in .env file."""
    
    if not ENV_FILE.exists():
        print(f"ERROR: .env file not found at {ENV_FILE}")
        return False
    
    # Read current .env file
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Update dates
    updated_lines = []
    start_found = False
    end_found = False
    
    for line in lines:
        if line.startswith("BACKTEST_START_DATE="):
            updated_lines.append(f"BACKTEST_START_DATE={CORRECT_START_DATE}\n")
            start_found = True
        elif line.startswith("BACKTEST_END_DATE="):
            updated_lines.append(f"BACKTEST_END_DATE={CORRECT_END_DATE}\n")
            end_found = True
        else:
            updated_lines.append(line)
    
    # Write back
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(updated_lines)
    
    if start_found and end_found:
        print(f"[OK] Updated BACKTEST_START_DATE to {CORRECT_START_DATE}")
        print(f"[OK] Updated BACKTEST_END_DATE to {CORRECT_END_DATE}")
        return True
    else:
        print(f"WARNING: Could not find both date variables in .env file")
        print(f"  START_DATE found: {start_found}")
        print(f"  END_DATE found: {end_found}")
        return False

if __name__ == "__main__":
    print("=" * 80)
    print("UPDATING .ENV FILE WITH CORRECT DATE RANGE")
    print("=" * 80)
    print(f"Target dates: {CORRECT_START_DATE} to {CORRECT_END_DATE}")
    print("(These match the 14k PnL baseline backtest)")
    print()
    
    success = update_env_dates()
    
    if success:
        print()
        print("=" * 80)
        print("SUCCESS!")
        print("=" * 80)
        print("You can now re-run the regime detection optimization:")
        print("  python optimize_regime_detection.py --focused")
    else:
        print()
        print("=" * 80)
        print("FAILED!")
        print("=" * 80)
        print("Please manually update .env file with:")
        print(f"  BACKTEST_START_DATE={CORRECT_START_DATE}")
        print(f"  BACKTEST_END_DATE={CORRECT_END_DATE}")

