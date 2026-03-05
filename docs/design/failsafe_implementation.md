# Fail-Safe Position Protection Implementation

## Overview

This document describes the fail-safe position protection system implemented in the entry-confirmed live trading strategy to prevent unprotected positions.

## Problem Statement

The original live code had a critical bug where bracket orders (entry + SL + TP) were submitted individually using `submit_order()` in a loop instead of atomically using `submit_order_list()`. This allowed IBKR to accept the entry order while rejecting or canceling the SL/TP orders, leaving positions unprotected.

## Solution: Multi-Layered Fail-Safe System

### Files Created

1. **Strategy**: `strategies/ml_strategy_mtf_v2_entry_confirmed_failsafe.py`
   - Enhanced version with position protection verification
   - Fail-safe logic to flatten unprotected positions

2. **Live Runner**: `live/run_live_mtf_v2_entry_confirmed_v2_failsafe.py`
   - Uses fail-safe strategy
   - Trader ID: `TRADER-V2-EC-FS-001`

3. **Supervisor**: `live/run_live_mtf_v2_entry_confirmed_v2_supervisor_failsafe.py`
   - Manages fail-safe live runner with auto-restart

4. **Restart Script**: `scripts/restart_live_entry_confirmed_failsafe.ps1`
   - Quick restart command for fail-safe version

## Fail-Safe Features

### 1. Grace Period (30 seconds)

After bracket order submission, the system waits 30 seconds before checking protection status.

**Why**: Orders take time to reach IBKR, get accepted, and appear in cache. Prevents false alarms.

**Implementation**:
```python
"submission_time": self.clock.timestamp_ns(),
"grace_period_ns": 30_000_000_000,  # 30 seconds
```

### 2. Protection Verification Flag

Once SL and TP orders are confirmed accepted by IBKR, the position is marked as verified and no longer checked.

**Why**: Reduces unnecessary checks and false positives.

**Implementation**:
```python
def on_order_accepted(self, event):
    # When both SL and TP accepted
    if has_sl_venue and has_tp_venue:
        pos_info["protection_verified"] = True
        _py_logger.info(f"[PROTECTION_OK] {layer_name} fully protected")
```

### 3. Multiple Verification Checks

Requires **3 consecutive failed checks** before taking emergency action.

**Why**: A single cache miss might be a timing issue. 3 consecutive failures = real problem.

**Timeline**: 3 checks × 15m bars = 45 minutes minimum before flatten

**Implementation**:
```python
"failed_protection_checks": 0,
"max_failed_checks": 3,
```

### 4. Smart Verification Logic

Checks for SL/TP orders using multiple methods:
- By `client_order_id` (our internal ID)
- By `venue_order_id` (IBKR's ID)
- Verifies both SL and TP are present

**Why**: Multiple ways to verify = less chance of false positive.

### 5. Periodic Health Monitoring

Checks position protection **every 15m bar** (not every 1m bar).

**Why**: 15-minute intervals are sufficient and reduce noise.

**Implementation**:
```python
def on_bar(self, bar: Bar):
    # Only check on 15m bars
    if len(self.active_positions) > 0:
        self._check_position_protection()
```

### 6. Emergency Flatten with Detailed Logging

If position is unprotected after all checks, the system:
1. Logs complete state (position, orders, IDs)
2. Flattens all positions immediately
3. Clears tracking and pending signals

**Implementation**:
```python
def _emergency_flatten(self, layer_name: str, reason: str):
    _py_logger.error("=" * 80)
    _py_logger.error(f"[EMERGENCY FLATTEN] Closing {layer_name}")
    _py_logger.error(f"[REASON] {reason}")
    # ... detailed logging ...
    self.flatten_all_positions(self.instrument_id)
```

## Timeline Example

```
T+0s:   Submit bracket order
T+0-30s: GRACE PERIOD - no checks
T+30s:  First check - if SL/TP missing, counter = 1
T+15m:  Second check - if still missing, counter = 2
T+30m:  Third check - if still missing, counter = 3 → FLATTEN
```

**Minimum time before flatten**: 30 seconds + 30 minutes = **30.5 minutes**

## Expected Log Output

### Normal Operation (Protected Position)

```
[SUBMIT] POS1: LONG 85000 units @ MARKET, SL=1.16982, TP=1.17135
[ORDER_IDS] POS1 Entry=O-20260105-..., SL=O-20260105-..., TP=O-20260105-...
[VERIFICATION] Open orders after POS1 submission: 3 orders
  - MarketOrder: O-20260105-... (status: SUBMITTED)
  - StopMarketOrder: O-20260105-... (status: SUBMITTED)
  - LimitOrder: O-20260105-... (status: SUBMITTED)
[SUBMITTED] POS1 bracket order submitted to IBKR
[VERIFIED] POS1 ENTRY accepted: venue_id=123456
[VERIFIED] POS1 SL accepted: venue_id=123457
[VERIFIED] POS1 TP accepted: venue_id=123458
[PROTECTION_OK] POS1 fully protected (SL + TP accepted)
```

### Unprotected Position Detected

```
[PROTECTION_CHECK] POS1 protection check FAILED (1/3)
[PROTECTION_CHECK] POS1 protection check FAILED (2/3)
[PROTECTION_CHECK] POS1 protection check FAILED (3/3)
[FAIL-SAFE] POS1 UNPROTECTED after 3 checks - FLATTENING
================================================================================
[EMERGENCY FLATTEN] Closing POS1
[REASON] Missing SL/TP orders
[TIME] 1736098765123456789
[POSITION] Direction: LONG, Size: 85000
[ORDER_IDS] Entry: O-20260105-..., SL: O-20260105-..., TP: O-20260105-...
[VENUE_IDS] SL: None, TP: None
[OPEN_ORDERS] Count: 1
  - MarketOrder: O-20260105-... (venue: 123456)
[OPEN_POSITIONS] Count: 1
  - POS1: 85000 units
================================================================================
```

## Safeguards Against Accidental Closes

1. **30-second grace period** - No checks during order processing
2. **Protection verified flag** - Once confirmed, stop checking
3. **3 consecutive failures** - Requires sustained problem
4. **15m check frequency** - Not overly aggressive
5. **Multiple verification methods** - Client ID and venue ID
6. **Detailed logging** - Full audit trail before action

## Testing Recommendations

### Before Going Live

1. **Paper trading test**: Run fail-safe version in paper trading for 1 week
2. **Monitor logs**: Verify all positions show `[PROTECTION_OK]` messages
3. **Simulate failure**: Manually cancel SL/TP in TWS to test fail-safe triggers
4. **Check timing**: Verify grace period and check intervals work as expected

### During Live Trading

1. **First trade monitoring**: Watch logs closely for first live trade
2. **Verify 3 orders**: Check `[VERIFICATION]` shows 3 orders after submission
3. **Confirm acceptance**: Look for `[VERIFIED]` logs for SL and TP
4. **Check TWS**: Verify bracket orders appear as linked OCO orders in IBKR

### Warning Signs

**Stop trading immediately if you see**:
- `[VERIFICATION]` showing fewer than 3 orders
- Missing `[VERIFIED]` logs for SL or TP
- `[PROTECTION_CHECK]` failures (investigate before 3rd failure)
- Any `[EMERGENCY FLATTEN]` events (review logs to understand why)

## Comparison with Original Code

| Feature | Original Code | Fail-Safe Code |
|---------|--------------|----------------|
| Order submission | `submit_order()` loop | `submit_order_list()` atomic |
| Order ID tracking | ✓ Yes | ✓ Yes |
| Post-submission verification | ✓ Basic | ✓ Enhanced |
| SL/TP acceptance tracking | ✓ Yes | ✓ Yes + verified flag |
| Grace period | ❌ No | ✓ 30 seconds |
| Protection health checks | ❌ No | ✓ Every 15m |
| Failed check counter | ❌ No | ✓ 3 consecutive |
| Emergency flatten | ❌ No | ✓ Yes |
| Detailed fail-safe logging | ❌ No | ✓ Yes |

## Running the Fail-Safe Version

### Start
```powershell
.\scripts\restart_live_entry_confirmed_failsafe.ps1
```

### Stop
```powershell
Get-Process python | Where-Object { $_.CommandLine -like "*failsafe*" } | Stop-Process -Force
```

### Check Status
```powershell
Get-Process python | Where-Object { $_.CommandLine -like "*failsafe*" }
```

### View Logs
```powershell
Get-Content logs\live_mtf\application.log -Tail 50 -Wait
```

## Industry Best Practices

This implementation follows industry-standard fail-safe practices:

✓ **Grace period** - Standard 30-60 seconds  
✓ **Multiple checks** - 2-5 consecutive failures typical  
✓ **Periodic monitoring** - Every bar/minute standard  
✓ **Emergency flatten** - Industry requirement  
✓ **Detailed logging** - Regulatory compliance  

## Conclusion

The fail-safe system provides **multiple layers of protection** with **conservative safeguards** to prevent accidental position closes while ensuring no unprotected positions can survive more than 30 minutes.

This is a **critical safety feature** that should be considered **mandatory** for live trading with bracket orders.
