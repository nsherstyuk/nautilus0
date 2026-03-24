# 2026-03-24: pivot=nan Fix + First 36hr Trade Review

## Morning Trade Review (08:25 EST)

Claude's analysis of first 36 hours of paper trading (`claude-to-cascade/2026-03-24_live-trade-analysis.md`):

### Real Trades (excluding 3 spread_cost bug trades)

| # | Time (UTC) | Pair | Dir | Entry | Exit | PnL | Exit |
|---|-----------|------|-----|-------|------|-----|------|
| 1 | Mar 22 20:32 | XAUUSD | SHORT | 4423.65 | 4421.05 | +$2.45 | TIME_STOP |
| 5 | Mar 23 21:30 | XAUUSD | SHORT | 4354.98 | 4337.47 | +$17.36 | TIME_STOP |
| 6 | Mar 23 22:43 | XAUUSD | SHORT | 4353.79 | 4342.26 | +$11.38 | TIME_STOP |
| 7 | Mar 23 20:59 | USDJPY | LONG | 158.59 | 158.63 | +$0.03 | TIME_STOP |
| 8 | Mar 24 09:28 | EURUSD | SHORT | ~1.16 | ~1.16 | -$0.00 | TIME_STOP |
| 9 | Mar 24 09:00 | USDJPY | LONG | 158.83 | 158.83 | -$0.00 | TIME_STOP |

**Total real PnL: +$31.22** (all from XAUUSD)

### Assessment
- **Mechanically sound**: all orders filling, SLs placed, logging clean per pair
- **XAUUSD delivering**: consistent with backtest. Both Mar 23 shorts caught gold trending down with sell-side imbalance
- **FX flat**: expected at 20k size (3 pip EURUSD move = $6). Verifying mechanics, not returns
- **GBPUSD**: 0 trades in 14 hours. Pivots tracked but no confirmed rebreak fired. Normal for pw=120
- **V6**: range too wide 3 consecutive days (gold vol too high for ORB). Working as designed

## Bug: pivot=nan in USDJPY Signal (11:06 EST)

Claude flagged USDJPY trade #9 logging `pivot=nan`.

### Root Cause
**Display bug, not signal logic bug.** `live_engine.py:281` read `pivot_price` from the rolling centered array at `process_idx`. Centered pivots can go NaN at that position when the pivot window shifts. But `PatternDetector` stores the pivot internally (`_h_level`/`_l_level`) — always valid when signal fires.

### Fix
```python
# OLD (buggy)
pivot_price = float(pivot_high[process_idx]) if direction == "long" \
    else float(pivot_low[process_idx])

# NEW (fixed)
pivot_price = self.detector._h_level if direction == "long" \
    else self.detector._l_level
```

One-line change. No trade impact (SL is ATR-based, not pivot-based).

### Process Restart (11:10 EST)
All 5 processes restarted. Confirmed healthy startup with 481 bars buffered each.

## Messages
- Read: `claude-to-cascade/2026-03-24_live-trade-analysis.md`
- Sent: `cascade-to-claude/2026-03-24_pivot-nan-bug-fixed.md`

## Code Changes

| File | Change |
|------|--------|
| `v8_confirmed_rebreak/live/live_engine.py:281` | Read pivot from detector state instead of array |

## Pending
- V6 keep/cut decision deferred -- V6 sidelined by high gold vol, V8 trading through it
- IB error 10147 investigation (low priority)
- Switch position recon to refuse-to-start before real money
