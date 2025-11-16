# Pullback Entry Feature - Post-Mortem Analysis

## Test Results Summary

**Backtest Date**: November 16, 2025  
**Feature**: Entry Timing with Pullback Method  
**Result**: ❌ **CATASTROPHIC FAILURE**

### Performance Impact

| Metric | Baseline (Disabled) | With Pullback | Delta | % Change |
|--------|---------------------|---------------|-------|----------|
| **Total PnL** | $9,517.35 | -$4,185.53 | **-$13,702.88** | **-144%** |
| **Win Rate** | 48.3% | 38.0% | -10.4% | -21.5% |
| **Total Trades** | 211 | 827 | +616 | +292% |
| **Expectancy** | $45.11 | -$5.06 | -$50.17 | -111% |
| **Avg Winner** | N/A | $160.75 | N/A | N/A |
| **Avg Loser** | N/A | -$106.55 | N/A | N/A |

### Critical Issues

1. **Negative PnL**: Destroyed $13,702 in profit, turning $9,517 gain into $4,186 loss
2. **Trade Explosion**: 4x more trades (211 → 827) with terrible quality
3. **Win Rate Collapse**: -10.4 percentage points drop
4. **Negative Expectancy**: -$5.06 per trade (baseline: +$45.11)

### Root Cause Analysis

#### Code Logic Flow
1. **Signal Generation**: 15-minute MA crossover generates trade signal
2. **Pullback Wait**: System switches to 2-minute bars, waits for pullback
3. **Entry Condition**: Price must be within 3 pips of fast EMA + bullish/bearish candle
4. **Timeout**: After 10x 2-min bars (20 minutes), executes anyway

#### Problems Identified

##### 1. **Timeframe Mismatch**
- Strategy runs on **15-minute bars**
- Entry timing uses **2-minute bars**
- Signals generated on 15-min data, but entries occur on 2-min closes
- This creates **random entry timing** relative to the original signal

##### 2. **Overly Restrictive Conditions**
- Pullback buffer: Only **3 pips** from fast EMA
- Fast EMA = 40-period MA (~10 hours of price action)
- Waiting for price to return within 3 pips of a 10-hour average is unrealistic
- 86,347 rejected signals (mostly time filters, but pullback logic still restrictive)

##### 3. **Wrong Reference Level**
- Uses **fast EMA** as pullback target
- Fast EMA is a trend indicator, not a support/resistance level
- Better alternatives: swing highs/lows, round numbers, daily pivots

##### 4. **Timeout Behavior Creates Bad Entries**
- If pullback doesn't occur within 20 minutes, trade executes anyway
- This means entry happens on a **random 2-minute bar close**
- Not at the optimal 15-minute crossover point
- Not at a confirmed pullback level
- Just... whenever the timer expires

##### 5. **Trade Explosion**
- Added 616 extra trades (292% increase)
- These aren't filtered trades - they're **NEW bad trades**
- Likely due to timing out and entering at suboptimal 2-min bar closes
- Multiple timeout entries per original 15-min signal

### Why Performance Degraded

1. **Entry Quality**: Shifted from deliberate 15-min crossover entries to random 2-min timeout entries
2. **Slippage**: Entering on 2-min bars instead of proper 15-min signal points
3. **False Signals**: Pullback logic doesn't align with actual support/resistance
4. **Overtrading**: System executing multiple attempts per original signal

### Lessons Learned

#### ✅ What Worked (Previously)
- **Immediate entry** on 15-minute MA crossover: $9,517 PnL, 48.3% WR
- **Time-based exclusions**: +$495 improvement by avoiding bad hours
- **Data-driven filtering**: Analyzing trade data to find root causes

#### ❌ What Failed
- **Multi-timeframe entry timing**: Mixing 15-min signals with 2-min entries
- **Blind pullback assumptions**: "Better entry price" doesn't guarantee better trades
- **Timeout fallback logic**: Created worse entries than no timing at all

### Recommendations

#### Immediate Actions
1. ✅ **DISABLE entry timing feature** (`STRATEGY_ENTRY_TIMING_ENABLED=false`)
2. ✅ **Stick with immediate 15-minute entries** (proven: $9,517 PnL)
3. ✅ **Focus on proven improvements** (time exclusions working well)

#### If Redesigning Entry Timing (Future)
1. **Same Timeframe**: Use 15-min bars for both signals and entries, not 2-min
2. **Widen Buffer**: 10-15 pips minimum, not 3 pips
3. **Better Reference**: Use swing levels or round numbers, not fast EMA
4. **No Timeout Entries**: If pullback doesn't occur, skip the trade entirely
5. **Breakout Alternative**: Consider waiting for breakout confirmation instead of pullback
6. **Test Incrementally**: Start with 50 trades, validate, then expand

#### Better Alternatives to Explore
1. **Trailing Stops**: Let winners run (trades >12h have 64% WR)
2. **Position Sizing**: Risk-based sizing vs fixed lots
3. **Multi-Timeframe Confirmation**: Trend alignment on higher timeframe
4. **Volatility Filters**: Only trade during specific ATR conditions
5. **Session-Based Rules**: Different parameters for London/NY/Asian sessions

### Technical Debt Created

**Code Status**: Feature exists but disabled
- Lines 877-920: `_check_pullback_entry()` function (unused)
- Lines 1320-1380: Entry timing bar processing logic (bypassed when disabled)
- Config parameters: `entry_timing_enabled`, `entry_timing_method`, `entry_timing_timeout_bars`

**Recommendation**: Keep code for reference but mark as deprecated. If revisiting:
- Start from scratch with proper design
- Test on small sample first (50 trades)
- Validate assumptions with data before full implementation

### Conclusion

The pullback entry feature represents a textbook example of:
- ❌ **Assumption-driven development** ("pullback entry must be better")
- ❌ **Over-engineering** (multi-timeframe complexity)
- ❌ **Ignoring timeframe consistency** (15-min signals + 2-min entries = chaos)

vs. what works:
- ✅ **Data-driven decisions** (time exclusions: predicted +$478-725, actual +$495)
- ✅ **Simplicity** (immediate 15-min entries: $9,517 PnL)
- ✅ **Incremental testing** (validate before scaling)

**Status**: Feature disabled. Baseline performance restored: $9,517 PnL, 48.3% WR, 211 trades.

## Configuration

Current `.env` setting (correct):
```properties
STRATEGY_ENTRY_TIMING_ENABLED=false
STRATEGY_ENTRY_TIMING_METHOD=pullback
STRATEGY_ENTRY_TIMING_TIMEOUT_BARS=10
```

**DO NOT ENABLE** until complete redesign with proper testing methodology.
