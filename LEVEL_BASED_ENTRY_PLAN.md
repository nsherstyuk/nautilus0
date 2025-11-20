# Level-Based Entry Timing Enhancement Plan

## Current State: Pullback Entry (DISABLED)

### Existing Code:
Your strategy **already has** pullback entry timing implemented but disabled:

```properties
# In .env
STRATEGY_ENTRY_TIMING_ENABLED=false  # Currently disabled
STRATEGY_ENTRY_TIMING_METHOD=pullback
STRATEGY_ENTRY_TIMING_TIMEOUT_BARS=10
```

### How Current Pullback Logic Works:

**BUY Signal:**
1. MA crossover signals BUY
2. Instead of entering immediately, wait for:
   - Price to pull back within 3 pips of fast MA
   - Bullish candle (close > open)
3. Enter on confirmation

**SELL Signal:**
1. MA crossover signals SELL  
2. Wait for:
   - Price to rally within 3 pips of fast MA
   - Bearish candle (close < open)
3. Enter on confirmation

**Code Location:** `_check_pullback_entry()` at line 877

## Proposed Enhancement: Add Level-Based Logic

### Why Enhance?

Current pullback only looks at **fast MA** as the level. We can improve by:
1. **Swing high/low levels** (recent support/resistance)
2. **Round number levels** (psychological barriers like 1.0800, 1.0850)
3. **Multi-timeframe levels** (higher TF swing points)

### Enhancement Strategy

Add **3 new config parameters** to work with existing pullback code:

```python
# Add to MovingAverageCrossoverConfig:
use_swing_levels: bool = False  # Track swing high/low for entries
swing_level_lookback: int = 50  # Bars to look back for swings
use_round_number_filter: bool = False  # Filter entries near round numbers
round_number_buffer_pips: float = 3.0  # Buffer around round numbers
```

### Enhanced Logic

#### Option 1: Swing Level Pullback (Recommended)
```
For BUY signals:
1. Calculate swing low = lowest low in last 50 bars
2. When MA crossover occurs:
   - If price within 5-10 pips of swing low → ENTER (at support)
   - If price > 15 pips from swing low → WAIT for pullback
   - Timeout after 10 bars if no pullback
```

#### Option 2: Round Number Filter
```
Before any entry:
1. Calculate distance to nearest round number (50-pip or 100-pip level)
2. If within 3 pips of round number:
   - WAIT for clear break (2 bars above/below)
   - OR REJECT if can't break within timeout
```

#### Option 3: Combined (Best)
```
On MA crossover signal:
1. Check swing levels (support/resistance)
2. Check round numbers (psychological levels)
3. Only enter if:
   - Near swing level (good entry) AND
   - Not stuck at round number (barrier)
```

## Implementation Steps

### Step 1: Enable Current Pullback (Test Baseline)

**Update .env:**
```properties
STRATEGY_ENTRY_TIMING_ENABLED=true
```

**Run backtest** to see if basic pullback improves results.

**Expected:**
- Fewer trades (waits for pullback)
- Better entry prices
- Potentially higher win rate

### Step 2: Add Swing Level Tracking

**Add to strategy code:**
```python
# In __init__:
self.swing_high = None
self.swing_low = None
self.swing_lookback_bars = []

# In on_bar (main timeframe):
def _update_swing_levels(self, bar: Bar):
    """Track swing highs and lows"""
    self.swing_lookback_bars.append(bar)
    if len(self.swing_lookback_bars) > self.cfg.swing_level_lookback:
        self.swing_lookback_bars.pop(0)
    
    if len(self.swing_lookback_bars) >= self.cfg.swing_level_lookback:
        highs = [b.high for b in self.swing_lookback_bars]
        lows = [b.low for b in self.swing_lookback_bars]
        self.swing_high = max(highs)
        self.swing_low = min(lows)
```

### Step 3: Enhance Pullback Logic

**Modify `_check_pullback_entry():`**
```python
def _check_pullback_entry(self, bar: Bar, direction: str) -> bool:
    # ... existing code ...
    
    # NEW: Check swing levels
    if self.cfg.use_swing_levels and self.swing_low and self.swing_high:
        current_price = Decimal(str(bar.close))
        pip_value = self._calculate_pip_value()
        
        if direction == "BUY":
            # Check if near swing low (support)
            dist_to_swing_low = (current_price - Decimal(str(self.swing_low))) / pip_value
            
            if dist_to_swing_low > 15:  # Too far from support
                self.log.debug(f"BUY signal: {dist_to_swing_low:.1f} pips from swing low, waiting")
                return False
            
            if 5 <= dist_to_swing_low <= 10:  # Sweet spot at support
                self.log.info(f"BUY signal: perfect entry at {dist_to_swing_low:.1f} pips from support")
                return True
    
    # ... rest of existing logic ...
```

### Step 4: Add Round Number Filter

```python
def _is_near_round_number(self, price: float, buffer_pips: float = 3.0) -> bool:
    """Check if price is near a round number"""
    pip_value = float(self._calculate_pip_value())
    
    # Check 50-pip levels (e.g., 1.0850, 1.0900)
    round_50 = round(price / 0.0050) * 0.0050
    dist_50 = abs(price - round_50) / pip_value
    
    # Check 100-pip levels (e.g., 1.0800, 1.0900)
    round_100 = round(price / 0.0100) * 0.0100
    dist_100 = abs(price - round_100) / pip_value
    
    return dist_50 < buffer_pips or dist_100 < buffer_pips
```

## Expected Impact

### Baseline Pullback Only (Step 1):
- **Trade reduction**: -20-30% (waits for pullback)
- **Win rate change**: +2-5% (better entries)
- **PnL impact**: +$200-500 (fewer bad entries)

### With Swing Levels (Step 2-3):
- **Trade reduction**: -30-40% (selective entries)
- **Win rate change**: +5-10% (entries at support/resistance)
- **PnL impact**: +$500-1,000 (much better entries)

### With Round Number Filter (Step 4):
- **Additional filtering**: -5-10% trades
- **Win rate change**: +2-3% (avoids barrier levels)
- **PnL impact**: +$200-400 (avoids false breakouts)

### Total Combined Expected:
- **Trades**: 150-180 (vs 211 baseline)
- **Win Rate**: 56-63% (vs 54% baseline)
- **PnL**: $10,000-11,500 (vs $9,022 baseline)
- **Improvement**: +$1,000-2,500 (+11-28%)

## Testing Plan

### Phase 1: Enable Basic Pullback
```bash
# Update .env
STRATEGY_ENTRY_TIMING_ENABLED=true

# Run backtest
python backtest/run_backtest.py

# Compare to baseline
python compare_baseline_vs_new.py
```

### Phase 2: Add Swing Levels (if Phase 1 works)
```python
# Add config parameters
use_swing_levels: bool = True
swing_level_lookback: int = 50

# Implement tracking code
# Run backtest
# Compare results
```

### Phase 3: Add Round Number Filter (if Phase 2 works)
```python
# Add config parameter
use_round_number_filter: bool = True
round_number_buffer_pips: float = 3.0

# Implement filter
# Run backtest
# Compare results
```

## Quick Win: Test Phase 1 Now

The **easiest immediate improvement** is to enable the existing pullback entry:

**Just change one line in .env:**
```properties
STRATEGY_ENTRY_TIMING_ENABLED=true  # Change from false to true
```

This requires **ZERO code changes** and will test if waiting for pullbacks improves results.

If it works, we can then add swing levels and round number filters for additional gains.

## Summary

✅ **You already have pullback entry code** - just disabled
✅ **Quick test**: Enable it and backtest
✅ **If successful**: Enhance with swing levels (support/resistance)
✅ **Advanced**: Add round number psychological level filtering
✅ **Expected total improvement**: +$1,000-2,500 (+11-28%)

**Recommendation**: Start with Phase 1 (enable existing pullback), measure results, then decide if additional enhancements are worth it.
