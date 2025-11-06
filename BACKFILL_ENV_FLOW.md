# Backfill Requirements Calculation Flow

## Overview

The backfill requirements are calculated from environment variables stored in the **`.env`** file in the project root directory. Here's the complete flow:

## Data Flow

```
.env file
    ↓
config/live_config.py (get_live_config())
    ↓
live/run_live.py (main())
    ↓
live/historical_backfill.py (calculate functions)
```

## Step-by-Step Flow

### 1. **`.env` File** (Project Root)
Contains environment variables:
```env
LIVE_SLOW_PERIOD=270
LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL
LIVE_SYMBOL=EUR/USD
LIVE_VENUE=IDEALPRO
# ... other LIVE_* variables
```

### 2. **`config/live_config.py`** - `get_live_config()` Function
```python
def get_live_config() -> LiveConfig:
    load_dotenv()  # ← Loads .env file
    
    # Read environment variables
    slow_period = _parse_int("LIVE_SLOW_PERIOD", os.getenv("LIVE_SLOW_PERIOD"), 20)
    bar_spec = os.getenv("LIVE_BAR_SPEC", "1-MINUTE-LAST")
    
    # Returns LiveConfig object with these values
    return LiveConfig(
        slow_period=slow_period,  # ← From LIVE_SLOW_PERIOD env var
        bar_spec=bar_spec,         # ← From LIVE_BAR_SPEC env var
        # ... other fields
    )
```

**Key Environment Variables Read:**
- `LIVE_SLOW_PERIOD` → `live_config.slow_period`
- `LIVE_BAR_SPEC` → `live_config.bar_spec`
- `LIVE_SYMBOL` → `live_config.symbol`
- `LIVE_VENUE` → `live_config.venue`

### 3. **`live/run_live.py`** - `main()` Function
```python
async def main() -> int:
    # Load configuration from .env
    live_config = get_live_config()  # ← Calls config/live_config.py
    
    # ... setup trading node ...
    
    # Calculate backfill requirements
    duration_days = calculate_required_duration_days(
        live_config.slow_period,  # ← From LIVE_SLOW_PERIOD env var
        bar_spec                   # ← From LIVE_BAR_SPEC env var
    )
    
    # Perform backfill
    backfill_success, bars_loaded, historical_bars = await backfill_historical_data(
        slow_period=live_config.slow_period,  # ← From LIVE_SLOW_PERIOD
        bar_spec=bar_spec,                     # ← From LIVE_BAR_SPEC
        # ...
    )
```

### 4. **`live/historical_backfill.py`** - Calculation Functions
```python
def calculate_required_bars(slow_period: int, bar_spec: str) -> int:
    """
    slow_period: From LIVE_SLOW_PERIOD env var
    bar_spec: From LIVE_BAR_SPEC env var
    """
    required_bars = int(slow_period * 1.2)  # Add 20% buffer
    return max(required_bars, slow_period)

def calculate_required_duration_hours(slow_period: int, bar_spec: str) -> float:
    """
    Calculates hours needed based on:
    - slow_period: From LIVE_SLOW_PERIOD env var
    - bar_spec: From LIVE_BAR_SPEC env var (parsed to get minutes per bar)
    """
    required_bars = calculate_required_bars(slow_period, bar_spec)
    
    # Parse bar_spec to determine minutes per bar
    # "15-MINUTE-MID-EXTERNAL" → 15 minutes per bar
    # "1-HOUR-MID-EXTERNAL" → 60 minutes per bar
    
    total_minutes = required_bars * minutes_per_bar
    total_hours = total_minutes / 60.0
    return total_hours
```

## Key Environment Variables for Backfill

### Required Variables:
```env
# Primary calculation inputs
LIVE_SLOW_PERIOD=270          # Used to calculate required bars
LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL  # Used to calculate duration

# Additional context (not directly used in calculation, but needed)
LIVE_SYMBOL=EUR/USD           # Instrument symbol
LIVE_VENUE=IDEALPRO           # Trading venue
```

### Calculation Formula:
```
Required Bars = LIVE_SLOW_PERIOD × 1.2 (20% buffer)

Duration = Required Bars × (minutes_per_bar from LIVE_BAR_SPEC) / 60

Example (Phase 6):
  LIVE_SLOW_PERIOD = 270
  LIVE_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
  
  Required Bars = 270 × 1.2 = 324 bars
  Minutes per bar = 15 (parsed from "15-MINUTE-...")
  Duration = 324 × 15 / 60 = 81 hours = 3.38 days
```

## Where `.env` File is Located

The `.env` file is located in the **project root directory** (`C:\nautilus0\.env`).

The `load_dotenv()` function in `config/live_config.py` automatically searches for `.env` in:
1. Current working directory
2. Parent directories (up to project root)
3. Project root (where `live/run_live.py` is executed from)

## Verification

You can verify which values are being used by checking the logs:

```bash
python live/run_live.py
```

Look for these log messages:
```
Analyzing historical data requirements...
Strategy warmup requires 270 bars of 15-MINUTE-MID-EXTERNAL (approximately 3.38 days)

HISTORICAL DATA BACKFILL ANALYSIS
Slow indicator period: 270          ← From LIVE_SLOW_PERIOD
Bar specification: 15-MINUTE-MID-EXTERNAL  ← From LIVE_BAR_SPEC
Required bars for warmup: 324
Required duration: 81.00 hours (3.38 days)
```

## Changing Backfill Requirements

To change backfill requirements, edit the `.env` file:

```env
# Change slow period (affects required bars)
LIVE_SLOW_PERIOD=100  # Will require ~120 bars instead of 324

# Change bar spec (affects duration calculation)
LIVE_BAR_SPEC=1-HOUR-MID-EXTERNAL  # Will require different duration
```

**Note:** After changing `.env`:
- Restart the live trading application
- Backfill calculations will use new values automatically

## Default Values

If environment variables are not set in `.env`, defaults are used:

```python
# From config/live_config.py
slow_period = _parse_int("LIVE_SLOW_PERIOD", os.getenv("LIVE_SLOW_PERIOD"), 20)
bar_spec = os.getenv("LIVE_BAR_SPEC", "1-MINUTE-LAST")
```

**Defaults:**
- `LIVE_SLOW_PERIOD`: 20 (if not set)
- `LIVE_BAR_SPEC`: "1-MINUTE-LAST" (if not set)

## Summary

**Backfill requirements are calculated from:**
1. **`.env` file** → Contains `LIVE_SLOW_PERIOD` and `LIVE_BAR_SPEC`
2. **`config/live_config.py`** → Loads `.env` and creates `LiveConfig` object
3. **`live/run_live.py`** → Passes `live_config.slow_period` and `live_config.bar_spec` to backfill
4. **`live/historical_backfill.py`** → Calculates required bars and duration

**Key Environment Variables:**
- `LIVE_SLOW_PERIOD` → Determines number of bars needed
- `LIVE_BAR_SPEC` → Determines time duration per bar

**Result:** System automatically calculates backfill requirements based on your Phase 6 configuration in `.env` file.

