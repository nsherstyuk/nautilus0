# Live Trading Feature Parity Implementation Plan

## Executive Summary

**Goal**: Ensure all backtesting features are available in live trading configuration and code.

**Current Status**: Live trading configuration is missing several critical features that exist in backtest:
- ❌ Adaptive stop-loss/take-profit (ATR-based, percentile-based)
- ❌ Market regime detection (trending vs ranging)
- ❌ Weekday-specific hour exclusions
- ❌ RSI filter
- ❌ Volume filter
- ❌ ATR trend strength filter
- ⚠️ Trend filter exists but with different parameters (trend_ema_period vs trend_fast/slow_period)
- ⚠️ Entry timing exists but limited

**Impact**: Live trading cannot leverage the validated +35.6% PnL improvement from weekday exclusions and other optimizations.

---

## Gap Analysis: Backtest vs Live Configuration

### 1. **MISSING IN LIVE: Adaptive Stop-Loss/Take-Profit** 🔴 CRITICAL

**Backtest Features:**
```python
adaptive_stop_mode: str = "atr"  # 'fixed' | 'atr' | 'percentile'
adaptive_atr_period: int = 14
tp_atr_mult: float = 2.5
sl_atr_mult: float = 1.5
trail_activation_atr_mult: float = 1.0
trail_distance_atr_mult: float = 0.8
volatility_window: int = 200
volatility_sensitivity: float = 0.6
min_stop_distance_pips: float = 5.0
```

**Live Implementation:**
- Currently uses fixed pips only: `stop_loss_pips`, `take_profit_pips`, etc.
- No ATR-based dynamic adjustment
- No percentile-based volatility adaptation

**Benefit**: Adapts stops to market volatility, critical for live trading performance.

---

### 2. **MISSING IN LIVE: Market Regime Detection** 🔴 CRITICAL

**Backtest Features:**
```python
regime_detection_enabled: bool = False
regime_adx_trending_threshold: float = 25.0
regime_adx_ranging_threshold: float = 20.0
regime_tp_multiplier_trending: float = 1.5
regime_tp_multiplier_ranging: float = 0.8
regime_sl_multiplier_trending: float = 1.0
regime_sl_multiplier_ranging: float = 1.0
regime_trailing_activation_multiplier_trending: float = 0.75
regime_trailing_activation_multiplier_ranging: float = 1.25
regime_trailing_distance_multiplier_trending: float = 0.67
regime_trailing_distance_multiplier_ranging: float = 1.33
```

**Live Implementation:**
- No regime detection at all
- Cannot adjust strategy parameters based on market conditions

**Benefit**: Adapts TP/SL/trailing stops to trending vs ranging markets.

---

### 3. **MISSING IN LIVE: Weekday-Specific Hour Exclusions** 🔴 CRITICAL (Validated +35.6% PnL)

**Backtest Features:**
```python
excluded_hours_mode: str = "flat"  # "flat" | "weekday"
excluded_hours_by_weekday: dict[str, list[int]] = field(default_factory=dict)
```

**Live Implementation:**
- Has `excluded_hours` but only flat mode (same hours every day)
- Missing weekday-specific exclusion capability

**Benefit**: **Validated +$3,902 PnL improvement (+35.6%) in backtest!**

---

### 4. **MISSING IN LIVE: RSI Filter** 🟡 MEDIUM

**Backtest Features:**
```python
rsi_enabled: bool = False
rsi_period: int = 14
rsi_overbought: int = 70
rsi_oversold: int = 30
rsi_divergence_lookback: int = 5
```

**Live Implementation:**
- No RSI filter

**Benefit**: Prevents trading in overbought/oversold conditions.

---

### 5. **MISSING IN LIVE: Volume Filter** 🟡 MEDIUM

**Backtest Features:**
```python
volume_enabled: bool = False
volume_avg_period: int = 20
volume_min_multiplier: float = 1.2
```

**Live Implementation:**
- No volume confirmation

**Benefit**: Ensures sufficient liquidity for entries.

---

### 6. **MISSING IN LIVE: ATR Trend Strength Filter** 🟡 MEDIUM

**Backtest Features:**
```python
atr_enabled: bool = False
atr_period: int = 14
atr_min_strength: float = 0.001
```

**Live Implementation:**
- No ATR filter

**Benefit**: Avoids trading during low volatility periods.

---

### 7. **MISMATCH: Trend Filter Parameters** 🟠 LOW

**Backtest:**
```python
trend_filter_enabled: bool = False
trend_bar_spec: str = "1-MINUTE-MID-EXTERNAL"
trend_ema_period: int = 150
trend_ema_threshold_pips: float = 0.0
```

**Live:**
```python
trend_filter_enabled: bool = False
trend_bar_spec: str = "1-HOUR-MID-EXTERNAL"
trend_fast_period: int = 20
trend_slow_period: int = 50
```

**Issue**: Different implementation approach (EMA vs dual MA).

---

## Implementation Plan

### Phase 1: Update LiveConfig Dataclass ✅

**File**: `config/live_config.py`

**Add Missing Fields:**
```python
from dataclasses import dataclass, field

@dataclass
class LiveConfig:
    # ... existing fields ...
    
    # Adaptive stops configuration
    adaptive_stop_mode: str = "atr"  # 'fixed' | 'atr' | 'percentile'
    adaptive_atr_period: int = 14
    tp_atr_mult: float = 2.5
    sl_atr_mult: float = 1.5
    trail_activation_atr_mult: float = 1.0
    trail_distance_atr_mult: float = 0.8
    volatility_window: int = 200
    volatility_sensitivity: float = 0.6
    min_stop_distance_pips: float = 5.0
    
    # Market regime detection
    regime_detection_enabled: bool = False
    regime_adx_trending_threshold: float = 25.0
    regime_adx_ranging_threshold: float = 20.0
    regime_tp_multiplier_trending: float = 1.5
    regime_tp_multiplier_ranging: float = 0.8
    regime_sl_multiplier_trending: float = 1.0
    regime_sl_multiplier_ranging: float = 1.0
    regime_trailing_activation_multiplier_trending: float = 0.75
    regime_trailing_activation_multiplier_ranging: float = 1.25
    regime_trailing_distance_multiplier_trending: float = 0.67
    regime_trailing_distance_multiplier_ranging: float = 1.33
    
    # Weekday-specific exclusions
    excluded_hours_mode: str = "flat"
    excluded_hours_by_weekday: dict[str, list[int]] = field(default_factory=dict)
    
    # RSI filter
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    rsi_divergence_lookback: int = 5
    
    # Volume filter
    volume_enabled: bool = False
    volume_avg_period: int = 20
    volume_min_multiplier: float = 1.2
    
    # ATR filter
    atr_enabled: bool = False
    atr_period: int = 14
    atr_min_strength: float = 0.001
    
    # Align trend filter with backtest
    trend_ema_period: int = 150
    trend_ema_threshold_pips: float = 0.0
```

---

### Phase 2: Update Environment Variable Parsing ✅

**File**: `config/live_config.py` - `get_live_config()` function

**Add Parsing Logic:**
```python
def get_live_config() -> LiveConfig:
    load_dotenv()
    
    # ... existing parsing ...
    
    # Adaptive stops
    adaptive_stop_mode = os.getenv("LIVE_ADAPTIVE_STOP_MODE", "atr")
    adaptive_atr_period = _parse_int("LIVE_ADAPTIVE_ATR_PERIOD", os.getenv("LIVE_ADAPTIVE_ATR_PERIOD"), 14)
    tp_atr_mult = _parse_float("LIVE_TP_ATR_MULT", os.getenv("LIVE_TP_ATR_MULT"), 2.5)
    sl_atr_mult = _parse_float("LIVE_SL_ATR_MULT", os.getenv("LIVE_SL_ATR_MULT"), 1.5)
    trail_activation_atr_mult = _parse_float("LIVE_TRAIL_ACTIVATION_ATR_MULT", os.getenv("LIVE_TRAIL_ACTIVATION_ATR_MULT"), 1.0)
    trail_distance_atr_mult = _parse_float("LIVE_TRAIL_DISTANCE_ATR_MULT", os.getenv("LIVE_TRAIL_DISTANCE_ATR_MULT"), 0.8)
    volatility_window = _parse_int("LIVE_VOLATILITY_WINDOW", os.getenv("LIVE_VOLATILITY_WINDOW"), 200)
    volatility_sensitivity = _parse_float("LIVE_VOLATILITY_SENSITIVITY", os.getenv("LIVE_VOLATILITY_SENSITIVITY"), 0.6)
    min_stop_distance_pips = _parse_float("LIVE_MIN_STOP_DISTANCE_PIPS", os.getenv("LIVE_MIN_STOP_DISTANCE_PIPS"), 5.0)
    
    # Market regime detection
    regime_detection_enabled = _parse_bool(os.getenv("LIVE_REGIME_DETECTION_ENABLED"), False)
    regime_adx_trending_threshold = _parse_float("LIVE_REGIME_ADX_TRENDING_THRESHOLD", os.getenv("LIVE_REGIME_ADX_TRENDING_THRESHOLD"), 25.0)
    regime_adx_ranging_threshold = _parse_float("LIVE_REGIME_ADX_RANGING_THRESHOLD", os.getenv("LIVE_REGIME_ADX_RANGING_THRESHOLD"), 20.0)
    regime_tp_multiplier_trending = _parse_float("LIVE_REGIME_TP_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TP_MULTIPLIER_TRENDING"), 1.5)
    regime_tp_multiplier_ranging = _parse_float("LIVE_REGIME_TP_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TP_MULTIPLIER_RANGING"), 0.8)
    regime_sl_multiplier_trending = _parse_float("LIVE_REGIME_SL_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_SL_MULTIPLIER_TRENDING"), 1.0)
    regime_sl_multiplier_ranging = _parse_float("LIVE_REGIME_SL_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_SL_MULTIPLIER_RANGING"), 1.0)
    regime_trailing_activation_multiplier_trending = _parse_float("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_TRENDING"), 0.75)
    regime_trailing_activation_multiplier_ranging = _parse_float("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TRAILING_ACTIVATION_MULTIPLIER_RANGING"), 1.25)
    regime_trailing_distance_multiplier_trending = _parse_float("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING", os.getenv("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_TRENDING"), 0.67)
    regime_trailing_distance_multiplier_ranging = _parse_float("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING", os.getenv("LIVE_REGIME_TRAILING_DISTANCE_MULTIPLIER_RANGING"), 1.33)
    
    # Weekday exclusions
    excluded_hours_mode = os.getenv("LIVE_EXCLUDED_HOURS_MODE", "flat").lower()
    excluded_hours_by_weekday = {}
    if excluded_hours_mode == "weekday":
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for weekday in weekdays:
            env_var = f"LIVE_EXCLUDED_HOURS_{weekday.upper()}"
            weekday_hours = _parse_excluded_hours(env_var, os.getenv(env_var))
            if weekday_hours:
                excluded_hours_by_weekday[weekday] = weekday_hours
    
    # RSI filter
    rsi_enabled = _parse_bool(os.getenv("LIVE_RSI_ENABLED"), False)
    rsi_period = _parse_int("LIVE_RSI_PERIOD", os.getenv("LIVE_RSI_PERIOD"), 14)
    rsi_overbought = _parse_int("LIVE_RSI_OVERBOUGHT", os.getenv("LIVE_RSI_OVERBOUGHT"), 70)
    rsi_oversold = _parse_int("LIVE_RSI_OVERSOLD", os.getenv("LIVE_RSI_OVERSOLD"), 30)
    rsi_divergence_lookback = _parse_int("LIVE_RSI_DIVERGENCE_LOOKBACK", os.getenv("LIVE_RSI_DIVERGENCE_LOOKBACK"), 5)
    
    # Volume filter
    volume_enabled = _parse_bool(os.getenv("LIVE_VOLUME_ENABLED"), False)
    volume_avg_period = _parse_int("LIVE_VOLUME_AVG_PERIOD", os.getenv("LIVE_VOLUME_AVG_PERIOD"), 20)
    volume_min_multiplier = _parse_float("LIVE_VOLUME_MIN_MULTIPLIER", os.getenv("LIVE_VOLUME_MIN_MULTIPLIER"), 1.2)
    
    # ATR filter
    atr_enabled = _parse_bool(os.getenv("LIVE_ATR_ENABLED"), False)
    atr_period = _parse_int("LIVE_ATR_PERIOD", os.getenv("LIVE_ATR_PERIOD"), 14)
    atr_min_strength = _parse_float("LIVE_ATR_MIN_STRENGTH", os.getenv("LIVE_ATR_MIN_STRENGTH"), 0.001)
    
    # Trend filter alignment
    trend_ema_period = _parse_int("LIVE_TREND_EMA_PERIOD", os.getenv("LIVE_TREND_EMA_PERIOD"), 150)
    trend_ema_threshold_pips = _parse_float("LIVE_TREND_EMA_THRESHOLD_PIPS", os.getenv("LIVE_TREND_EMA_THRESHOLD_PIPS"), 0.0)
    
    return LiveConfig(
        # ... existing fields ...
        adaptive_stop_mode=adaptive_stop_mode,
        adaptive_atr_period=adaptive_atr_period,
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        trail_activation_atr_mult=trail_activation_atr_mult,
        trail_distance_atr_mult=trail_distance_atr_mult,
        volatility_window=volatility_window,
        volatility_sensitivity=volatility_sensitivity,
        min_stop_distance_pips=min_stop_distance_pips,
        regime_detection_enabled=regime_detection_enabled,
        regime_adx_trending_threshold=regime_adx_trending_threshold,
        regime_adx_ranging_threshold=regime_adx_ranging_threshold,
        regime_tp_multiplier_trending=regime_tp_multiplier_trending,
        regime_tp_multiplier_ranging=regime_tp_multiplier_ranging,
        regime_sl_multiplier_trending=regime_sl_multiplier_trending,
        regime_sl_multiplier_ranging=regime_sl_multiplier_ranging,
        regime_trailing_activation_multiplier_trending=regime_trailing_activation_multiplier_trending,
        regime_trailing_activation_multiplier_ranging=regime_trailing_activation_multiplier_ranging,
        regime_trailing_distance_multiplier_trending=regime_trailing_distance_multiplier_trending,
        regime_trailing_distance_multiplier_ranging=regime_trailing_distance_multiplier_ranging,
        excluded_hours_mode=excluded_hours_mode,
        excluded_hours_by_weekday=excluded_hours_by_weekday,
        rsi_enabled=rsi_enabled,
        rsi_period=rsi_period,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        rsi_divergence_lookback=rsi_divergence_lookback,
        volume_enabled=volume_enabled,
        volume_avg_period=volume_avg_period,
        volume_min_multiplier=volume_min_multiplier,
        atr_enabled=atr_enabled,
        atr_period=atr_period,
        atr_min_strength=atr_min_strength,
        trend_ema_period=trend_ema_period,
        trend_ema_threshold_pips=trend_ema_threshold_pips,
    )
```

**Add Helper Functions:**
```python
def _parse_float(name: str, value: Optional[str], default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float, got: {value}") from exc

def _parse_excluded_hours(name: str, value: Optional[str]) -> list[int]:
    """Parse comma-separated list of hours (0-23) to exclude from trading."""
    if value is None or value == "":
        return []
    try:
        hours = [int(h.strip()) for h in value.split(",") if h.strip()]
        for hour in hours:
            if not (0 <= hour <= 23):
                raise ValueError(f"invalid hour {hour}")
        return sorted(set(hours))
    except ValueError as e:
        if "invalid hour" in str(e):
            raise
        raise ValueError(f"{name} must be comma-separated integers (0-23), got: {value}") from e
```

---

### Phase 3: Update Live Trading Strategy Configuration ✅

**File**: `live/run_live.py` - `create_trading_node_config()` function

**Add All Parameters to Strategy Config:**
```python
strategy_config = ImportableStrategyConfig(
    strategy_path="strategies.moving_average_crossover:MovingAverageCrossover",
    config_path="strategies.moving_average_crossover:MovingAverageCrossoverConfig",
    config={
        # ... existing fields ...
        
        # Adaptive stops
        "adaptive_stop_mode": live_config.adaptive_stop_mode,
        "adaptive_atr_period": live_config.adaptive_atr_period,
        "tp_atr_mult": live_config.tp_atr_mult,
        "sl_atr_mult": live_config.sl_atr_mult,
        "trail_activation_atr_mult": live_config.trail_activation_atr_mult,
        "trail_distance_atr_mult": live_config.trail_distance_atr_mult,
        "volatility_window": live_config.volatility_window,
        "volatility_sensitivity": live_config.volatility_sensitivity,
        "min_stop_distance_pips": live_config.min_stop_distance_pips,
        
        # Market regime detection
        "regime_detection_enabled": live_config.regime_detection_enabled,
        "regime_adx_trending_threshold": live_config.regime_adx_trending_threshold,
        "regime_adx_ranging_threshold": live_config.regime_adx_ranging_threshold,
        "regime_tp_multiplier_trending": live_config.regime_tp_multiplier_trending,
        "regime_tp_multiplier_ranging": live_config.regime_tp_multiplier_ranging,
        "regime_sl_multiplier_trending": live_config.regime_sl_multiplier_trending,
        "regime_sl_multiplier_ranging": live_config.regime_sl_multiplier_ranging,
        "regime_trailing_activation_multiplier_trending": live_config.regime_trailing_activation_multiplier_trending,
        "regime_trailing_activation_multiplier_ranging": live_config.regime_trailing_activation_multiplier_ranging,
        "regime_trailing_distance_multiplier_trending": live_config.regime_trailing_distance_multiplier_trending,
        "regime_trailing_distance_multiplier_ranging": live_config.regime_trailing_distance_multiplier_ranging,
        
        # Weekday exclusions
        "excluded_hours_mode": live_config.excluded_hours_mode,
        "excluded_hours_by_weekday": live_config.excluded_hours_by_weekday,
        
        # RSI filter
        "rsi_enabled": live_config.rsi_enabled,
        "rsi_period": live_config.rsi_period,
        "rsi_overbought": live_config.rsi_overbought,
        "rsi_oversold": live_config.rsi_oversold,
        "rsi_divergence_lookback": live_config.rsi_divergence_lookback,
        
        # Volume filter
        "volume_enabled": live_config.volume_enabled,
        "volume_avg_period": live_config.volume_avg_period,
        "volume_min_multiplier": live_config.volume_min_multiplier,
        
        # ATR filter
        "atr_enabled": live_config.atr_enabled,
        "atr_period": live_config.atr_period,
        "atr_min_strength": live_config.atr_min_strength,
        
        # Aligned trend filter
        "trend_ema_period": live_config.trend_ema_period,
        "trend_ema_threshold_pips": live_config.trend_ema_threshold_pips,
    },
)
```

---

### Phase 4: Create Live Trading Environment Template ✅

**File**: `.env.live.template`

Create comprehensive template with all parameters documented.

---

## Testing Plan: Safe Live Trading Validation

### **Critical Rule**: NEVER test with real capital until fully validated! ⚠️

### Option 1: Paper Trading with IBKR (RECOMMENDED) ✅

**Setup:**
1. Open IBKR Paper Trading account (free, unlimited virtual money)
2. Set environment variables using paper account credentials
3. Run live trading in paper mode

**Benefits:**
- Real market data
- Real order execution simulation
- Zero financial risk
- Full feature testing

**Configuration:**
```bash
# Use paper trading TWS/Gateway on port 7497
IBKR_PORT=7497  # Paper trading port
IBKR_HOST=127.0.0.1
IBKR_CLIENT_ID=1
IBKR_ACCOUNT_ID=DU1234567  # Paper account ID starts with DU
```

**Validation Checklist:**
- [ ] Strategy starts without errors
- [ ] Weekday-specific exclusions work (check logs for rejected signals)
- [ ] Adaptive stops calculate correctly (check order prices)
- [ ] Regime detection switches between trending/ranging
- [ ] All filters (RSI, volume, ATR) trigger correctly
- [ ] Orders execute with correct SL/TP prices
- [ ] Trailing stops update as expected

**Duration**: Minimum 1 week (covers all weekdays)

---

### Option 2: Dry-Run Mode (Strategy-Only Testing) ⚠️

**Setup:**
1. Modify `run_live.py` to run strategy without connecting to broker
2. Feed simulated bars to strategy
3. Log all signals without actual orders

**Benefits:**
- No broker needed
- Fast testing
- Configuration validation

**Limitations:**
- No real market data
- No order execution testing
- Cannot validate fills/rejections

**Implementation:**
```python
# In run_live.py, add dry-run mode
if os.getenv("LIVE_DRY_RUN", "false").lower() == "true":
    logger.info("DRY RUN MODE - No orders will be submitted")
    # Skip broker connection, use simulated data
```

---

### Option 3: Micro Position Testing (REAL MONEY - Use Extreme Caution!) 💰

**Setup:**
1. Use smallest possible position size (e.g., 1 micro lot for forex)
2. Set tight stop-loss to limit maximum loss
3. Monitor continuously for first 24 hours

**Configuration:**
```bash
LIVE_TRADE_SIZE=1  # Minimum size
LIVE_STOP_LOSS_PIPS=10  # Tight stop
# Maximum risk: 1 micro lot × 10 pips = $0.10 per trade
```

**Benefits:**
- Real execution validation
- Real slippage/spread experience
- High confidence before scaling

**Risks:**
- Real money at risk (though minimal)
- Requires constant monitoring

**Recommendation**: Only after successful paper trading validation.

---

## Validation Metrics

### Critical Success Criteria:

1. **Configuration Loading** ✅
   - All environment variables parse correctly
   - No missing or invalid parameters

2. **Strategy Initialization** ✅
   - Strategy starts without errors
   - All indicators initialize properly
   - Historical data warmup completes

3. **Filter Validation** ✅
   - Time filter rejects signals during excluded hours
   - Weekday exclusions work correctly (check logs)
   - DMI/Stoch filters reject inappropriate signals

4. **Order Execution** ✅
   - Orders created with correct SL/TP prices
   - Adaptive stops calculate reasonable values
   - Trailing stops update correctly

5. **Regime Detection** ✅
   - Strategy logs regime changes (trending/ranging)
   - TP/SL multipliers adjust correctly
   - Regime-specific parameters apply

6. **Performance Monitoring** ✅
   - Win rate matches backtest expectations (~36% with weekday exclusions)
   - Average winner/loser ratio similar to backtest
   - PnL trend positive over sample period

---

## Risk Management

### Pre-Go-Live Checklist:

- [ ] All code changes committed and tested
- [ ] Paper trading ran successfully for minimum 1 week
- [ ] All filters validated (time, weekday, DMI, stoch, etc.)
- [ ] Adaptive stops calculate reasonable values
- [ ] Emergency stop mechanism tested (Ctrl+C, SIGTERM)
- [ ] Log files capture all critical events
- [ ] Alert/notification system configured
- [ ] Maximum daily loss limit configured
- [ ] Position sizing appropriate for account size
- [ ] Broker connection stable (no disconnects during test)

### Live Monitoring Requirements:

- Monitor first 3 days continuously (24/5 for forex)
- Check logs hourly for unexpected behavior
- Verify each trade against backtest expectations
- Track weekday exclusion effectiveness
- Monitor regime detection accuracy
- Set calendar alerts for weekly performance review

---

## Expected Outcomes

### With Validated Configuration (Weekday Exclusions + DMI + Stoch):

**Backtest Performance** (Jan 2024 - Oct 2025):
- PnL: $14,846
- Win Rate: 35.90%
- Total Trades: 195
- Avg Winner: $407
- Avg Loser: -$109

**Live Trading Expectations** (with some degradation):
- Win Rate: 30-35% (allow for slippage/spread)
- Risk/Reward: ~3.7:1 ratio maintained
- Signal rejection: High (due to filters)
- Trade frequency: ~1-2 per day (EUR/USD)

### Performance Degradation Factors:

1. **Slippage**: 0.5-1 pip typical for forex
2. **Spread**: 0.5-1.5 pips EUR/USD (varies by broker)
3. **Latency**: Order delays vs backtest instant fills
4. **Market Impact**: Minimal for micro/mini lots
5. **Emotional Factors**: None (automated)

**Expected Degradation**: 10-20% vs backtest (still highly profitable)

---

## Rollback Plan

If live performance significantly underperforms:

1. **Immediate Actions:**
   - Stop live trading
   - Preserve all logs
   - Document observed issues

2. **Analysis:**
   - Compare live vs backtest signals
   - Check filter effectiveness
   - Verify parameter passing
   - Review fill prices vs expected

3. **Fixes:**
   - Adjust parameters based on live data
   - Add missing filters if needed
   - Improve error handling
   - Re-test in paper trading

4. **Restart Criteria:**
   - All issues identified and fixed
   - Paper trading validates fixes
   - Risk parameters adjusted appropriately

---

## Implementation Timeline

| Phase | Task | Effort | Dependencies |
|-------|------|--------|--------------|
| 1 | Update LiveConfig dataclass | 1 hour | None |
| 2 | Add environment parsing | 2 hours | Phase 1 |
| 3 | Update run_live.py config | 1 hour | Phase 2 |
| 4 | Create .env.live template | 1 hour | Phase 3 |
| 5 | Test configuration loading | 1 hour | Phase 4 |
| 6 | Paper trading validation | 1 week | Phase 5 |
| 7 | Micro position testing | 3-5 days | Phase 6 |
| 8 | Full live deployment | Ongoing | Phase 7 |

**Total Development Time**: ~6-8 hours
**Total Validation Time**: 10-12 days minimum

---

## Summary

**Critical Features to Add:**
1. ✅ Adaptive stops (ATR-based)
2. ✅ Market regime detection
3. ✅ Weekday-specific hour exclusions (**+35.6% validated improvement**)
4. ✅ RSI/Volume/ATR filters
5. ✅ Align trend filter implementation

**Testing Approach:**
1. Paper trading (minimum 1 week)
2. Dry-run validation (optional)
3. Micro position testing (3-5 days)
4. Full deployment with monitoring

**Key Risk Mitigation:**
- Comprehensive paper trading first
- Graduated position sizing
- Continuous monitoring
- Clear rollback procedures
- Emergency stop mechanisms

**Expected Benefit:**
- Access to validated +35.6% PnL improvement
- Dynamic adaptation to market conditions
- Robust filtering for high-quality signals
- Professional-grade live trading system

---

**Next Steps**: Begin implementation with Phase 1 (LiveConfig update)
