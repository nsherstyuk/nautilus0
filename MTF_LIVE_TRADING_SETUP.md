# MTF ML Strategy - Live Trading Setup

## CRITICAL: Custom IBKR Connector

**⚠️ IMPORTANT**: This project uses a **custom patched IBKR connector**, NOT the native NautilusTrader IB adapter.

### Why the Custom Connector?

The native NautilusTrader IB adapter has connection stability issues. Your existing code includes a patched version that fixes these problems.

### How It Works

```python
# In live/run_live.py (lines 19-22)
from patches import apply_ib_connection_patch

# Apply patch BEFORE importing Nautilus IB modules
apply_ib_connection_patch()
```

The patch overrides these methods in `InteractiveBrokersClientConnectionMixin`:
- `_connect`
- `_connect_socket`
- `_send_version_info`
- `_receive_server_info`

**Location**: `patches/nautilus_trader/adapters/interactive_brokers/client/connection.py`

---

## Adapting MTF Strategy for Live Trading

Since your existing live trading infrastructure works with the moving average strategy, we need to adapt it for the MTF ML strategy.

### Option 1: Create New Live Runner (Recommended)

Create `live/run_live_mtf.py` based on your existing `live/run_live.py`:

**Key Changes Needed**:
1. ✅ Use same patched IBKR connector
2. ✅ Change strategy import to `ml_strategy_mtf`
3. ✅ Use 15-minute bars instead of current bar spec
4. ✅ Load MTF model instead of using moving averages
5. ✅ Configure MTF-specific parameters

### Option 2: Modify Existing Runner

Add MTF strategy as an option in your existing `live/run_live.py`.

---

## Step-by-Step Implementation

### 1. Copy Existing Live Infrastructure

```bash
# The MTF strategy will use your proven live trading setup
cp live/run_live.py live/run_live_mtf.py
```

### 2. Key Modifications for MTF

**In `live/run_live_mtf.py`**:

```python
# Line ~19-22: Keep the patch (CRITICAL!)
from patches import apply_ib_connection_patch
apply_ib_connection_patch()

# Line ~152-243: Change strategy configuration
strategy_config = ImportableStrategyConfig(
    strategy_path="strategies.ml_strategy_mtf:MLSignalStrategy",  # Changed
    config_path="strategies.ml_strategy_config:MLSignalStrategyConfig",  # Changed
    config={
        "instrument_id": instrument_id,
        "bar_spec": "15-MINUTE-MID-EXTERNAL",  # Changed to 15m
        "position_size": 100000,
        "model_path": "models/ml_model_mtf.pkl",  # MTF model
        "prediction_threshold": 0.55,  # Optimized threshold
        "enforce_position_limit": True,
        "max_positions": 1,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "trailing_stop_enabled": True,
        "trailing_activation_atr_mult": 1.0,
        "trailing_distance_atr_mult": 0.8,
        "partial_close_enabled": True,  # Optimized feature
        "partial_close_fraction": 0.5,
        "partial_close_atr_mult": 1.5,
        "session_start": "02:00",
        "session_end": "16:00",
        "feature_warmup_bars": 100,
        "order_id_tag": "MTF_ML"
    },
)
```

### 3. Historical Backfill for MTF

The existing backfill logic (lines 395-462) should work, but needs adjustment:

```python
# Line ~379: Update required bars calculation
required_bars = 100  # MTF needs 100 bars for feature warmup (not slow_period)
```

### 4. MTF Strategy Warmup

**MTF warmup requirements**:
- **15-minute bars**: 100 bars needed
- **Time required**: 100 × 15min = 1,500 minutes = 25 hours ≈ 1 day
- **30-minute indicators**: Calculated from 15m bars internally

**Much faster than moving average strategy!** (which needs 260 bars = 65 hours)

---

## Configuration Files Needed

### 1. Create MTF Live Config

**File**: `config/live_config_mtf.py`

```python
from dataclasses import dataclass

@dataclass
class LiveConfigMTF:
    # Core settings
    trader_id: str = "TRADER-001"
    symbol: str = "EUR/USD"
    venue: str = "IDEALPRO"
    bar_spec: str = "15-MINUTE-MID-EXTERNAL"
    
    # Position sizing
    position_size: int = 100000
    enforce_position_limit: bool = True
    max_positions: int = 1
    
    # ML Model
    model_path: str = "models/ml_model_mtf.pkl"
    prediction_threshold: float = 0.55
    
    # Risk Management (ATR-based)
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    
    # Trailing Stop
    trailing_stop_enabled: bool = True
    trailing_activation_atr_mult: float = 1.0
    trailing_distance_atr_mult: float = 0.8
    
    # Partial Close (OPTIMIZED)
    partial_close_enabled: bool = True
    partial_close_fraction: float = 0.5
    partial_close_atr_mult: float = 1.5
    partial_close_move_sl_to_be: bool = True
    
    # Trading Session
    session_start: str = "02:00"
    session_end: str = "16:00"
    excluded_hours: list = None
    
    # Logging
    log_dir: str = "logs/live_mtf"
```

### 2. Environment Variables

**File**: `.env`

```bash
# IBKR Connection (same as before)
IB_HOST=127.0.0.1
IB_PORT=7497  # Paper trading (7496 for live)
IB_CLIENT_ID=1
IB_ACCOUNT=DU1234567  # Your paper account

# MTF Strategy
STRATEGY_TYPE=MTF_ML
STRATEGY_INSTRUMENT=EUR/USD.IDEALPRO
STRATEGY_BAR_SPEC=15-MINUTE-MID-EXTERNAL
STRATEGY_MODEL_PATH=models/ml_model_mtf.pkl
STRATEGY_POSITION_SIZE=100000

# Risk Limits
MAX_DAILY_LOSS=5000
MAX_POSITION_SIZE=100000
```

---

## Testing Procedure

### Phase 1: Connection Test (5 minutes)

```bash
# Test IBKR connection (uses your existing test script)
python scripts/test_ibkr_connection.py
```

**Expected output**:
```
✅ Connected to IBKR
✅ Account: DU1234567
✅ EUR/USD contract found
✅ Market data active
```

### Phase 2: Dry Run Test (1 hour)

```bash
# Run MTF strategy in paper trading mode
python live/run_live_mtf.py
```

**What to verify**:
1. ✅ Strategy starts without errors
2. ✅ 15-minute bars being received
3. ✅ Features calculated correctly (check logs)
4. ✅ Model predictions being made
5. ✅ No trades executed yet (warmup period)

**Check logs**:
```bash
tail -f logs/live_mtf/strategy.log
```

Look for:
```
[INFO] Bar received: EUR/USD 15m close=1.1500
[INFO] Features calculated: 10 features
[INFO] Warmup: 45/100 bars collected
```

### Phase 3: First Trade Verification (Wait for warmup)

After 100 bars (25 hours), first trade should execute.

**Verify**:
1. ✅ Entry order placed correctly
2. ✅ Stop loss set at entry - (1.5 × ATR)
3. ✅ Take profit set at entry + (2.5 × ATR)
4. ✅ Position size = 100,000 units
5. ✅ Logged correctly

**When profit reaches 1.5× ATR**:
1. ✅ 50% of position closed automatically
2. ✅ Remaining 50% still open
3. ✅ Stop loss moved to breakeven

### Phase 4: Paper Trading (2-4 weeks)

Run continuously in paper trading mode.

**Daily checks**:
```bash
# Monitor performance
python scripts/monitor_paper_trading.py
```

**Compare with backtest expectations**:
- Trades/day: ~5
- Win rate: ~45%
- R/R ratio: ~1.38
- Long/Short balance: ~53%/47%

---

## Differences from Moving Average Strategy

| Aspect | Moving Average | MTF ML |
|--------|----------------|--------|
| **Strategy Type** | Rule-based | ML-based |
| **Bar Interval** | Configurable | 15-minute fixed |
| **Warmup Time** | 65 hours (260 bars) | 25 hours (100 bars) |
| **Indicators** | 2 EMAs | MAMA, DMI, Stoch, WMA (MTF) |
| **Entry Logic** | MA crossover | ML model prediction |
| **Confidence** | N/A | 0.55 threshold |
| **Partial Close** | Optional | Enabled (optimized) |
| **Stop Loss** | Fixed pips or ATR | ATR-based (1.5×) |
| **Take Profit** | Fixed pips or ATR | ATR-based (2.5×) |

---

## Common Issues & Solutions

### Issue 1: "Model file not found"

```
Solution:
- Verify model exists: ls -l models/ml_model_mtf.pkl
- Check path in config
- Ensure model was trained successfully
```

### Issue 2: "Feature calculation failed"

```
Possible causes:
- Not enough bars for indicators
- Missing 30m data (resampling issue)
- NaN values in features

Solution:
- Wait for full warmup (100 bars)
- Check indicator calculations in logs
- Verify bar data quality
```

### Issue 3: "No trades executing"

```
Possible causes:
- Confidence threshold too high (0.55)
- ATR threshold not met
- Still in warmup period
- Cooldown active

Solution:
- Check logs for "Skipping trade" messages
- Verify model is making predictions
- Ensure 100 bars collected
```

### Issue 4: "Connection lost"

```
This is why we use the patched connector!

Solution:
- Verify patch is applied (check logs on startup)
- Ensure TWS/Gateway is running
- Check network stability
- Review patches/ib_connection_patch.py
```

---

## Monitoring Dashboard

Create a simple real-time dashboard:

```python
# scripts/mtf_dashboard.py
import time
from pathlib import Path

def display_status():
    """Display live MTF strategy status."""
    while True:
        print("\033[2J\033[H")  # Clear screen
        print("="*80)
        print("MTF ML STRATEGY - LIVE STATUS")
        print("="*80)
        
        # Read latest log entries
        log_file = Path("logs/live_mtf/strategy.log")
        if log_file.exists():
            with open(log_file) as f:
                lines = f.readlines()[-20:]  # Last 20 lines
                for line in lines:
                    print(line.strip())
        
        print("\n" + "="*80)
        print(f"Last update: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("Press Ctrl+C to exit")
        
        time.sleep(5)  # Update every 5 seconds

if __name__ == "__main__":
    display_status()
```

Run it:
```bash
python scripts/mtf_dashboard.py
```

---

## Emergency Procedures

### Stop Strategy Immediately

```bash
# Method 1: Ctrl+C in terminal running the strategy

# Method 2: Kill process
ps aux | grep run_live_mtf
kill -SIGTERM <PID>

# Method 3: Emergency stop script
python scripts/emergency_stop.py
```

### Close All Positions Manually

1. Open TWS/IB Gateway
2. Go to Portfolio → Positions
3. Right-click position → Close Position
4. Confirm closure

---

## Deployment Checklist

### Pre-Deployment
- [ ] MTF model trained and tested (`models/ml_model_mtf.pkl`)
- [ ] Backtest results reviewed (14.6% return, 45% win rate)
- [ ] Optimization complete (confidence=0.55, partial close enabled)
- [ ] Custom IBKR connector verified (patches directory intact)
- [ ] `live/run_live_mtf.py` created and configured
- [ ] Environment variables set (`.env` file)
- [ ] TWS/Gateway configured for API access

### Paper Trading
- [ ] Connection test passed
- [ ] Dry run completed (1 hour, no errors)
- [ ] First trade verified (entry, SL, TP, partial close)
- [ ] Paper trading running (2-4 weeks minimum)
- [ ] Performance matches backtest (±15% deviation acceptable)
- [ ] Monitoring scripts working

### Live Trading (Only after successful paper trading)
- [ ] Paper trading results reviewed and acceptable
- [ ] Risk limits configured
- [ ] Emergency procedures documented
- [ ] Monitoring dashboard running
- [ ] Alert system configured
- [ ] Start with 50% position size
- [ ] Monitor first week closely

---

## Next Steps

1. **Create `live/run_live_mtf.py`** (copy from `run_live.py` and modify)
2. **Test connection** with existing infrastructure
3. **Run dry test** (1 hour)
4. **Start paper trading** (2-4 weeks)
5. **Monitor and compare** with backtest
6. **Go live** (only if paper trading successful)

---

## Support Files

**Required files for MTF live trading**:
```
nautilus0/
├── models/
│   └── ml_model_mtf.pkl          # Trained MTF model
├── strategies/
│   ├── ml_strategy_mtf.py        # MTF strategy (already created)
│   └── ml_strategy_config.py     # Config (already updated)
├── live/
│   ├── run_live.py               # Existing (working)
│   └── run_live_mtf.py           # NEW - to be created
├── patches/                       # CRITICAL - custom IBKR connector
│   ├── __init__.py
│   ├── ib_connection_patch.py
│   └── nautilus_trader/...
├── config/
│   ├── live_config.py            # Existing
│   └── live_config_mtf.py        # NEW - to be created
├── scripts/
│   ├── test_ibkr_connection.py   # Already created
│   ├── monitor_paper_trading.py  # Already created
│   └── mtf_dashboard.py          # NEW - to be created
└── .env                          # Environment variables
```

---

**Remember**: The custom IBKR connector is what makes your live trading stable. Don't bypass it!

**Good luck with deployment! 🚀**
