"""
Proper seasonal hypothesis testing plan.

To confirm if EUR/USD has seasonal patterns, we need:
1. Multi-year data (2023, 2024, 2025)
2. Train models on specific months from one year
3. Test on same months from different years
4. Compare with non-seasonal models

This script outlines the testing methodology.
"""

print("="*80)
print("SEASONAL HYPOTHESIS TESTING METHODOLOGY")
print("="*80)

print("""
HYPOTHESIS:
EUR/USD exhibits seasonal patterns - similar market behavior in the same 
calendar month across different years.

EXAMPLE:
- October 2023, October 2024, October 2025 have similar characteristics
- A model trained on Oct 2023 would perform well on Oct 2024 and Oct 2025

WHY THIS MIGHT BE TRUE:
1. Central bank meeting schedules (Fed, ECB meet on fixed calendars)
2. Quarter-end rebalancing (Mar 31, Jun 30, Sep 30, Dec 31)
3. Holiday seasonality (low volume in Nov-Dec, summer doldrums in Aug)
4. Fiscal year effects (many countries' fiscal years align with calendar)
5. Agricultural cycles affecting commodity currencies

================================================================================
TESTING PLAN
================================================================================

PHASE 1: DATA COLLECTION
-------------------------
Need EUR/USD 15-minute data for:
- 2023: Full year (Jan-Dec)
- 2024: Full year (Jan-Dec)  
- 2025: Jan-Nov (what we have)

Current status:
✅ 2025 data: Available
✅ 2024 data: Available (in rolling windows)
❓ 2023 data: Need to check availability

PHASE 2: SEASONAL MODEL TRAINING
---------------------------------
For each calendar month (Jan-Dec):

Example for OCTOBER:
1. Train model on: Oct 2023 data (6 months: May-Oct 2023)
2. Test on: Oct 2024
3. Test on: Oct 2025
4. Compare with: Model trained on different months

If seasonal effect exists:
- Oct 2023 model should perform well on Oct 2024 AND Oct 2025
- Better than models trained on other months

PHASE 3: CROSS-YEAR VALIDATION
-------------------------------
For each month:
- Train on Year 1 (e.g., 2023)
- Test on Year 2 (e.g., 2024)
- Test on Year 3 (e.g., 2025)

Calculate:
- Seasonal correlation coefficient
- Performance improvement vs non-seasonal baseline

PHASE 4: ENSEMBLE STRATEGY
---------------------------
If seasonal effect confirmed:
1. Create 12 models (one per month)
2. Each month's model trained on that month from previous years
3. Deploy month-specific model at start of each month

================================================================================
WHAT WE CAN DO NOW (Without 2023 data)
================================================================================

Option A: ANALYZE EXISTING ROLLING WINDOWS
-------------------------------------------
We have 16 rolling windows covering 2024-2025.
We can:

1. Check if models trained on Month X in 2024 perform better on Month X in 2025
   
   Example:
   - Window 5 trained on May-Oct 2024
   - Does it perform better on May-Oct 2025 than other windows?

2. Create a "seasonal score" for each window
   - How well does training month overlap with test month?
   - Correlate this with performance

3. Build month-specific recommendations from existing windows

Option B: SIMPLE MONTH-SWITCHING STRATEGY
------------------------------------------
Based on our current findings:

December 2025 (starting next week):
- Use Window 9 (trained on Sep-Dec 2024)
- It has December in training period
- Should perform better than current model

January 2026:
- Use Window 9 (trained on Jan 2025)
- Has January in training period

This is a PRACTICAL test we can deploy immediately!

Option C: DOWNLOAD 2023 DATA
-----------------------------
If you can get 2023 EUR/USD data:
1. Train models on 2023 months
2. Test on corresponding 2024 months
3. Test on corresponding 2025 months
4. This gives us 3-year validation

================================================================================
RECOMMENDED IMMEDIATE ACTION
================================================================================

STEP 1: Test existing windows on full 2025 by month
-------------------------------------------------------
For each month in 2025:
- Find which rolling window has that month in training
- Test that window's performance on that specific month
- Compare with windows that DON'T have that month

STEP 2: Create month-switching backtest
----------------------------------------
Simulate using different models for different months:
- Jan 2025: Use best model trained on Jan 2024
- Feb 2025: Use best model trained on Feb 2024
- etc.

Calculate total P&L with this approach.

STEP 3: If promising, deploy for December
------------------------------------------
Next week is December 2025:
- Switch to Window 9 (has Dec 2024 in training)
- Monitor performance for 1 month
- Real-world validation of seasonal hypothesis

================================================================================
QUESTIONS TO ANSWER
================================================================================

1. Do we have access to 2023 EUR/USD data?
   - Check data/historical folder
   - Check if we can download from broker

2. What's the correlation between training month and test month performance?
   - Statistical analysis of existing 16 windows

3. Is the seasonal effect strong enough to justify monthly model switching?
   - Need to see if improvement > operational complexity

4. Are there specific months with strongest seasonal patterns?
   - Maybe only Oct-Nov-Dec show seasonality
   - Other months might be more random

================================================================================
NEXT SCRIPT TO RUN
================================================================================

I can create a script that:
1. Tests each rolling window on EACH MONTH of 2025 separately
2. Calculates "seasonal alignment score" 
3. Shows which window performs best for each month
4. Simulates a month-switching strategy's total P&L

This will tell us if seasonal switching beats your current $61,791!

Would you like me to create this script?
""")

print("\n" + "="*80)
print("DATA AVAILABILITY CHECK")
print("="*80)

from pathlib import Path

# Check what data we have
data_dir = Path("data/historical/data/bar/EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL")

if data_dir.exists():
    print(f"\n✅ Data directory exists: {data_dir}")
    print("\nAvailable parquet files:")
    
    for file in sorted(data_dir.glob("*.parquet")):
        size_mb = file.stat().st_size / 1024 / 1024
        print(f"  {file.name} ({size_mb:.1f} MB)")
        
        # Parse date range from filename
        parts = file.stem.split('_')
        if len(parts) >= 2:
            start_date = parts[0]
            end_date = parts[1]
            print(f"    Date range: {start_date} to {end_date}")
    
    print("\n" + "-"*80)
    print("CONCLUSION:")
    print("-"*80)
    
    # Check if we have 2023 data
    has_2023 = any('2023' in f.name for f in data_dir.glob("*.parquet"))
    has_2024 = any('2024' in f.name for f in data_dir.glob("*.parquet"))
    has_2025 = any('2025' in f.name for f in data_dir.glob("*.parquet"))
    
    if has_2023:
        print("✅ We have 2023 data - can do full 3-year seasonal analysis!")
    else:
        print("❌ No 2023 data - limited to 2024-2025 analysis")
    
    if has_2024 and has_2025:
        print("✅ We have 2024-2025 data - can test year-over-year patterns")
    
else:
    print(f"❌ Data directory not found: {data_dir}")
