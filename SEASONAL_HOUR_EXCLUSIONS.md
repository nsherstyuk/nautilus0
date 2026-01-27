# Seasonal Hour×Weekday Exclusions

## Overview

The seasonal hour×weekday exclusion feature allows you to filter out specific hour+weekday combinations within each meteorological season based on historical performance patterns. This is more precise than flat hour-only filters because it preserves profitable hour+weekday combinations while excluding only the consistently unprofitable ones.

## Configuration

### Environment Variables

Add these to `.env.mtf_v2`:

```bash
# Enable seasonal filtering
MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED=true

# Define exclusions per season (format: hour-weekday pairs, comma-separated)
# Hour: 0-23 (EST timezone)
# Weekday: 1=Monday, 2=Tuesday, 3=Wednesday, 4=Thursday, 5=Friday, 6=Sat, 7=Sun

# Winter (Dec-Jan-Feb) exclusions
MTF2_DJF_EXCLUDED_HOUR_WEEKDAY_PAIRS=16-1,16-3,16-5,14-3,14-5,15-1,15-3,15-5

# Spring (Mar-Apr-May) exclusions
MTF2_MAM_EXCLUDED_HOUR_WEEKDAY_PAIRS=

# Summer (Jun-Jul-Aug) exclusions
MTF2_JJA_EXCLUDED_HOUR_WEEKDAY_PAIRS=17-1,17-3,17-4,16-3,16-5

# Fall (Sep-Oct-Nov) exclusions
MTF2_SON_EXCLUDED_HOUR_WEEKDAY_PAIRS=14-1,14-2,14-3,14-5
```

### Recommended Settings (from 2024-2025 analysis)

Based on cross-year stability analysis showing ≥60% negative months in both years:

**DJF (Winter):**
- 16:00 on Mon/Wed/Fri (keeps profitable Thu/Tue)
- 14:00 on Wed/Fri (keeps profitable Mon/Thu)
- 15:00 on Mon/Wed/Fri

**JJA (Summer):**
- 17:00 on Mon/Wed/Thu
- 16:00 on Wed/Fri

**SON (Fall):**
- 14:00 on Mon/Tue/Wed/Fri (keeps profitable Thu)

**MAM (Spring):**
- Skip (patterns not reliably repeating year-to-year)

## Usage

### Baseline Backtest (no seasonal filtering)

```powershell
python .\run_backtest_mtf_v2_entry_confirmed.py
```

### Seasonal Filtering Backtest

```powershell
# Option 1: Use the dedicated seasonal runner
python .\run_backtest_mtf_v2_entry_confirmed_seasonal_hours.py

# Option 2: Enable via env vars with standard runner
$env:MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED='true'
$env:MTF2_DJF_EXCLUDED_HOUR_WEEKDAY_PAIRS='16-1,16-3,16-5,14-3,14-5'
python .\run_backtest_mtf_v2_entry_confirmed.py
```

### Compare Results

```powershell
# Run baseline
$env:MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED='false'
python .\run_backtest_mtf_v2_entry_confirmed.py

# Run with seasonal exclusions
$env:MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED='true'
$env:MTF2_DJF_EXCLUDED_HOUR_WEEKDAY_PAIRS='16-1,16-3,16-5'
$env:MTF2_JJA_EXCLUDED_HOUR_WEEKDAY_PAIRS='17-1,17-3'
$env:MTF2_SON_EXCLUDED_HOUR_WEEKDAY_PAIRS='14-1,14-2,14-3,14-5'
python .\run_backtest_mtf_v2_entry_confirmed.py
```

## How It Works

1. **Timezone**: All hour×weekday pairs are defined in **EST timezone**, matching how the analysis was performed.

2. **Season Detection**: The strategy automatically determines the current season based on the bar's month:
   - DJF: December, January, February (months 12, 1, 2)
   - MAM: March, April, May (months 3, 4, 5)
   - JJA: June, July, August (months 6, 7, 8)
   - SON: September, October, November (months 9, 10, 11)

3. **Exclusion Check**: Before opening a trade, the strategy:
   - Converts UTC bar time to EST
   - Determines current season
   - Checks if `(EST_hour, weekday)` is in the season's exclusion list
   - Rejects signal if excluded

4. **Integration with Existing Filters**: Seasonal exclusions work **alongside** existing time filters:
   - `excluded_hours_mode='disabled'` → only seasonal filters apply
   - `excluded_hours_mode='simple'` → trade_start_hour/trade_end_hour + seasonal
   - `excluded_hours_mode='weekday'` → all filters active

## Example Scenarios

### DJF 16:00 Thursday (allowed)
- Config has: `16-1,16-3,16-5` (Mon/Wed/Fri excluded)
- Thursday is weekday=4, not in exclusion list
- Trade **allowed** (Thursday was +227.6 pnl in analysis)

### DJF 16:00 Friday (blocked)
- Config has: `16-1,16-3,16-5`
- Friday is weekday=5, in exclusion list
- Trade **blocked** (Friday was -322.5 pnl in analysis)

### SON 14:00 Thursday (allowed)
- Config has: `14-1,14-2,14-3,14-5` (Mon/Tue/Wed/Fri excluded)
- Thursday is weekday=4, not in exclusion list
- Trade **allowed** (Thursday was +30.1 pnl despite 14:00 being 100% negative overall)

## Files

- `run_backtest_mtf_v2_entry_confirmed_seasonal_hours.py`: Dedicated backtest runner
- `strategies/ml_strategy_mtf_v2_entry_confirmed.py`: Strategy with seasonal logic
- `config/mtf_v2_config.py`: Config loader with seasonal parsing
- `.env.mtf_v2.seasonal_example`: Sample configuration
- `analysis_outputs/seasonality_mtf_v2/`: Analysis results supporting these exclusions

## Validation

To verify the implementation:

```powershell
python test_seasonal_exclusions.py
```

This tests config loading and parsing logic.
