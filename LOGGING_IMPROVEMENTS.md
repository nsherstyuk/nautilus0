# Logging Improvements Summary

## Overview
Enhanced logging infrastructure for live trading to provide better visibility, debugging, and audit trails for order lifecycle, trade execution, and strategy behavior.

## Changes Made

### 1. Enhanced Logging Configuration (`config/logging.live.yaml`)

#### New Log Files Created:
- **`logs/live/strategy.log`** - Strategy-specific logs with detailed formatting
- **`logs/live/orders.log`** - Comprehensive order lifecycle event logging
- **`logs/live/trades.log`** - Trade execution and position event logging
- **`logs/live/errors.log`** - All ERROR-level logs consolidated for easy troubleshooting

#### Enhanced Formatters:
- **`detailed`** formatter: Includes filename and line number for better debugging
  - Format: `%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s`

#### New Loggers:
- **`strategies.moving_average_crossover`** - Captures all strategy-specific logs
- **`orders`** - Dedicated logger for order lifecycle events
- **`trades`** - Dedicated logger for trade execution events

#### File Rotation:
- All log files use `RotatingFileHandler` with 10MB max size and 5 backups (10 for errors.log)
- Prevents log files from growing unbounded

### 2. Order Lifecycle Event Handlers (`strategies/moving_average_crossover.py`)

Added comprehensive `on_order_event()` handler that logs:

#### Order Events Logged:
- **ORDER ACCEPTED** - When venue accepts the order
  - Includes: client_order_id, venue_order_id, instrument_id, side, quantity, order_type, tags
- **ORDER FILLED** - When order is executed
  - Includes: fill details (quantity, price, value), filled vs. total quantity, commission
  - Also logs to trades logger
- **ORDER REJECTED** - When order is rejected by venue
  - Includes: rejection reason (ERROR level)
- **ORDER CANCELED** - When order is canceled
  - Includes: fill status before cancellation
- **ORDER CANCEL REJECTED** - When cancel request is rejected (WARNING level)
- **ORDER EXPIRED** - When order expires
- **ORDER TRIGGERED** - When stop/limit order is triggered
- **ORDER UPDATED** - When order is modified
- **ORDER PENDING UPDATE** - When order update is pending (DEBUG level)

### 3. Position Event Handlers (`strategies/moving_average_crossover.py`)

Added comprehensive `on_position_event()` handler that logs:

#### Position Events Logged:
- **POSITION OPENED** - When new position is opened
  - Includes: position_id, instrument_id, side, entry, quantity, avg_px_open, unrealized_pnl
- **POSITION CHANGED** - When position is modified (partial fills, etc.)
  - Includes: updated quantity, average prices, unrealized PnL
- **POSITION CLOSED** - When position is closed
  - Includes: entry/exit prices, realized PnL, average prices

### 4. Updated Live Runner (`live/run_live.py`)

Enhanced `setup_logging()` function to:
- Automatically configure all new log file paths
- Log initialization message listing all log files created
- Ensure log directory structure is created

## Benefits

### 1. **Better Debugging**
- Detailed logs with filename and line numbers make it easier to trace issues
- Separate log files allow focused investigation (orders vs. trades vs. strategy)

### 2. **Complete Audit Trail**
- Every order lifecycle event is logged with full details
- Trade execution history is preserved
- Position lifecycle is tracked from open to close

### 3. **Easier Monitoring**
- `orders.log` provides quick view of all order activity
- `trades.log` shows actual executions and PnL
- `errors.log` consolidates all errors for quick troubleshooting

### 4. **Performance Analysis**
- Trade logs include realized PnL for closed positions
- Order logs show fill prices and execution details
- Can be used for post-trade analysis and strategy refinement

### 5. **Compliance & Record Keeping**
- Complete audit trail of all trading activity
- Order submission, acceptance, fills, and cancellations are all logged
- Position changes and PnL tracking

## Log File Structure

```
logs/live/
├── application.log          # General application logs
├── live_trading.log         # Main live trading log (comprehensive)
├── strategy.log             # Strategy-specific logs with line numbers
├── orders.log               # Order lifecycle events (detailed)
├── trades.log               # Trade execution and position events
└── errors.log               # All ERROR-level logs (10 backups)
```

## Usage Examples

### Viewing Order Activity
```bash
# View all order events
tail -f logs/live/orders.log

# Search for rejected orders
grep "ORDER REJECTED" logs/live/orders.log

# Find all fills for a specific instrument
grep "EUR/USD" logs/live/orders.log | grep "ORDER FILLED"
```

### Viewing Trade Execution
```bash
# View all trade executions
tail -f logs/live/trades.log

# Find closed positions with PnL
grep "POSITION CLOSED" logs/live/trades.log

# Monitor unrealized PnL changes
grep "POSITION CHANGED" logs/live/trades.log
```

### Troubleshooting Errors
```bash
# View all errors
tail -f logs/live/errors.log

# Search for specific error patterns
grep -i "rejected" logs/live/errors.log
```

## Integration with Existing Logging

- All logs still go to console (INFO level and above)
- Strategy logs also appear in `live_trading.log` for comprehensive view
- Order and trade logs are duplicated to `live_trading.log` for convenience
- Errors are captured in both `errors.log` and `live_trading.log`

## Future Enhancements (Optional)

1. **JSON Structured Logging**: Add option for JSON-formatted logs for easier parsing
2. **Log Aggregation**: Integrate with centralized logging systems (ELK, Splunk, etc.)
3. **Metrics Export**: Export trade/order metrics to time-series databases
4. **Alerting**: Add email/Slack notifications for critical events (rejections, large losses)
5. **Log Compression**: Compress old log files automatically

## Notes

- Log files rotate automatically when they reach 10MB
- Keep up to 5 backups (10 for errors.log) before deletion
- All timestamps are in UTC for consistency
- Log levels: DEBUG (detailed), INFO (normal operations), WARNING (concerns), ERROR (problems)

