# Recommended Timeframe for Regime Detection

## Analysis

### Current Setup
- **Primary Strategy Timeframe**: 15-minute bars (MA crossover signals)
- **DMI/Regime Detection Timeframe**: 2-minute bars (default)
- **Stochastic Timeframe**: 15-minute bars

### Timeframe Trade-offs

#### 1. **Very Short Timeframes (1-2 minutes)**
**Pros:**
- Very responsive to regime changes
- Detects regime shifts quickly
- Good for scalping strategies

**Cons:**
- High noise - frequent false regime changes
- May cause TP/SL to flip-flop between regimes
- ADX can be unstable on very short timeframes
- Requires more computational resources

**Verdict:** ❌ **Not recommended** - Too noisy, causes instability

---

#### 2. **Short-Medium Timeframes (2-5 minutes)** ⭐ CURRENT DEFAULT
**Pros:**
- Responsive to regime changes
- Less noise than 1-minute bars
- Good balance for intraday trading
- 2-minute bars provide ~28 minutes lookback (14 periods)

**Cons:**
- Still some noise, may cause occasional regime flips
- May be too sensitive for some market conditions

**Verdict:** ✅ **Good for active day trading** - Current default works well

---

#### 3. **Medium Timeframes (5-15 minutes)** ⭐⭐ RECOMMENDED
**Pros:**
- **5-minute bars**: Excellent balance
  - Stable regime detection
  - Responsive enough for day trading
  - ~70 minutes lookback (14 periods)
  - Less noise, fewer false regime changes
  - Common timeframe for ADX calculations

- **15-minute bars**: Very stable
  - Matches primary strategy timeframe
  - Very stable regime classification
  - ~3.5 hours lookback (14 periods)
  - Less frequent regime changes
  - Good for swing trading

**Cons:**
- 15-minute may be slower to detect regime changes
- Less responsive than shorter timeframes

**Verdict:** ✅✅ **Best balance** - Recommended for most use cases

---

#### 4. **Longer Timeframes (30 minutes - 1 hour)**
**Pros:**
- Very stable regime detection
- Minimal noise
- Good for swing trading
- Clear trend identification

**Cons:**
- Slow to detect regime changes
- May miss intraday regime shifts
- Less useful for day trading strategies
- ~7-14 hours lookback (14 periods)

**Verdict:** ⚠️ **Only for swing trading** - Too slow for day trading

---

## Recommendation

### **Primary Recommendation: 5-minute bars**

**Why 5-minute bars are ideal:**

1. **Stability**: Less noise than 2-minute bars, fewer false regime changes
2. **Responsiveness**: Still responsive enough to detect regime shifts within reasonable time
3. **Common Practice**: 5-minute is a standard timeframe for ADX/regime detection
4. **Lookback Period**: ~70 minutes (14 periods) provides good trend context
5. **Balance**: Good compromise between stability and responsiveness

**Configuration:**
```bash
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
```

---

### **Alternative: 15-minute bars** (if you want maximum stability)

**Why 15-minute bars:**

1. **Matches Strategy**: Same timeframe as your primary MA crossover signals
2. **Maximum Stability**: Very stable regime classification
3. **Less Frequent Changes**: Regime changes less often, reducing TP/SL adjustments
4. **Good for Swing Trading**: Better for holding positions longer

**Configuration:**
```bash
STRATEGY_DMI_BAR_SPEC=15-MINUTE-MID-EXTERNAL
```

---

## Decision Matrix

| Timeframe | Stability | Responsiveness | Best For | Recommendation |
|-----------|-----------|---------------|----------|---------------|
| 1-minute  | ⭐ Low    | ⭐⭐⭐⭐⭐ Very High | Scalping | ❌ Too noisy |
| 2-minute  | ⭐⭐ Medium | ⭐⭐⭐⭐ High | Day Trading | ✅ Current default |
| **5-minute** | ⭐⭐⭐⭐ **High** | ⭐⭐⭐⭐ **High** | **Day Trading** | ✅✅ **RECOMMENDED** |
| 15-minute | ⭐⭐⭐⭐⭐ Very High | ⭐⭐⭐ Medium | Swing/Day | ✅ Good alternative |
| 30-minute | ⭐⭐⭐⭐⭐ Very High | ⭐⭐ Low | Swing | ⚠️ Too slow |
| 1-hour    | ⭐⭐⭐⭐⭐ Very High | ⭐ Very Low | Swing | ❌ Too slow |

---

## Testing Recommendations

### Step 1: Test Current (2-minute)
Run backtest with current settings and note:
- How often regime changes
- If TP/SL adjustments seem appropriate
- If regime flips too frequently

### Step 2: Test 5-minute (Recommended)
```bash
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL
```
Compare results:
- More stable regime detection?
- Better TP/SL performance?
- Fewer unnecessary adjustments?

### Step 3: Test 15-minute (If needed)
```bash
STRATEGY_DMI_BAR_SPEC=15-MINUTE-MID-EXTERNAL
```
Compare results:
- Maximum stability?
- Still responsive enough?
- Better overall performance?

---

## Key Considerations

### 1. **Regime Detection Happens at Trade Entry**
- Regime is detected when trade signal is generated
- TP/SL are set based on regime at entry
- Regime can change during trade (affects trailing stops)

### 2. **Stability vs Responsiveness Trade-off**
- **Too responsive** (1-2 min): Frequent regime flips → unstable TP/SL
- **Too stable** (30+ min): Slow to adapt → miss regime changes
- **Sweet spot** (5-15 min): Balance between both

### 3. **ADX Calculation Period**
- ADX uses 14-period lookback
- Longer timeframe = longer historical context
- 5-minute: ~70 minutes of history
- 15-minute: ~3.5 hours of history

### 4. **Primary Strategy Timeframe**
- Your strategy uses 15-minute bars for signals
- Regime detection can be:
  - **Same timeframe** (15-min): Maximum alignment
  - **Shorter timeframe** (5-min): More responsive regime detection
  - **Longer timeframe**: Not recommended (too slow)

---

## Final Recommendation

### **Start with 5-minute bars**

**Reasoning:**
1. ✅ Excellent balance of stability and responsiveness
2. ✅ Standard timeframe for ADX/regime detection
3. ✅ Less noise than 2-minute, more responsive than 15-minute
4. ✅ Good lookback period (~70 minutes)
5. ✅ Works well for day trading strategies

**If 5-minute is too responsive:**
- Try 15-minute bars (matches your strategy timeframe)

**If 5-minute is too slow:**
- Keep 2-minute bars (current default)

---

## Implementation

To change the timeframe, update your `.env` file:

```bash
# Recommended: 5-minute bars
STRATEGY_DMI_BAR_SPEC=5-MINUTE-MID-EXTERNAL

# Or try 15-minute bars for maximum stability
STRATEGY_DMI_BAR_SPEC=15-MINUTE-MID-EXTERNAL
```

**Note:** This affects both DMI trend filtering AND regime detection since they share the same indicator.


