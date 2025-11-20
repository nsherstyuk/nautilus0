# Historical Data Backfill Fix Plan

## Current Status (November 20, 2025)

### Problem
Historical data backfill is **DISABLED** because it fails with:
```
AttributeError: 'TradingNode' object has no attribute 'data_engine'
```

### Root Cause
The backfill attempts to access `node.data_engine` **BEFORE** `node.run()` starts. The data engine is only available **AFTER** the node begins running.

### Current Impact
- Strategy requires **260 bars (65 hours = 2.7 days)** to warm up naturally
- No trading signals generated during warmup period
- System works but with delayed strategy activation

---

## Backfill Fix Implementation Plan

### Phase 1: Research NautilusTrader Data Injection (2-3 hours)

**Objective:** Understand the correct way to inject historical bars into a running TradingNode

**Tasks:**
1. Review NautilusTrader documentation for:
   - Data client historical bar request APIs
   - Cache.add_bar() or similar methods
   - Strategy warmup patterns
   - Actor/Strategy data subscription mechanisms

2. Examine existing NautilusTrader examples:
   - Check `nautilus_trader/examples/` for backfill patterns
   - Search GitHub issues for "historical data" or "backfill"
   - Look for "warmup" or "replay" functionality

3. Investigate alternative approaches:
   - **Option A:** Request bars through data client subscription BEFORE node starts
   - **Option B:** Use node lifecycle hooks (on_start) to inject bars
   - **Option C:** Create custom Actor that backfills then starts strategy
   - **Option D:** Pre-populate cache with Parquet data files

**Expected Output:** Technical approach document with chosen method

---

### Phase 2: Implement Backfill Solution (4-6 hours)

#### Option A: Pre-Start Subscription (Recommended if API supports)
```python
# Before node.run()
bar_type = BarType(...)
historical_bars = await data_client.request_bars(
    bar_type=bar_type,
    start=start_time,
    end=end_time
)

# Add to cache before node starts
for bar in historical_bars:
    node.cache.add_bar(bar)
```

**Pros:** Simple, clean separation
**Cons:** May not work if cache requires running node

#### Option B: Lifecycle Hook Approach
```python
class BackfillActor(Actor):
    async def on_start(self):
        # Backfill logic here after node starts
        # Access self.data_engine
        bars = await self._request_historical_bars()
        for bar in bars:
            self.cache.add_bar(bar)
        # Signal strategy to start

# Add BackfillActor before strategy
node.trader.add_actor(backfill_actor)
node.trader.add_strategy(strategy)
```

**Pros:** Access to data_engine, clean architecture
**Cons:** More complex, need to coordinate with strategy

#### Option C: Async Task After Node Start
```python
async def run_node_with_backfill(node):
    # Start node in background
    node_task = asyncio.create_task(asyncio.to_thread(node.run))
    
    # Wait for node to be running
    while node.state != TradingState.RUNNING:
        await asyncio.sleep(0.1)
    
    # Now backfill
    data_engine = node.data_engine
    bars = await request_historical_bars(...)
    for bar in bars:
        data_engine.process(bar)  # or cache.add_bar(bar)
    
    # Wait for node completion
    await node_task
```

**Pros:** Access to running node, straightforward
**Cons:** Threading complexity, race conditions possible

---

### Phase 3: Testing & Validation (2-3 hours)

**Test Cases:**
1. **Backfill Success:** Verify bars are loaded and indicators populate
2. **Strategy Warmup:** Confirm strategy._warmup_complete becomes True
3. **No Duplicate Bars:** Ensure backfilled bars don't overlap with live bars
4. **Error Handling:** Test with no historical data available
5. **Live Transition:** Verify smooth transition from backfilled to live bars

**Validation Metrics:**
- [ ] All 260 bars loaded successfully
- [ ] Fast SMA (40) and Slow SMA (260) calculated correctly
- [ ] Strategy state transitions: INITIALIZING → WARMING_UP → READY
- [ ] First live bar processed correctly after backfill
- [ ] No errors in logs during backfill
- [ ] Strategy generates signals immediately after warmup

---

### Phase 4: Integration & Documentation (1-2 hours)

**Tasks:**
1. Update `live/run_live.py` with working backfill
2. Remove `if False:` wrapper
3. Add error handling and fallback to natural warmup
4. Update `LIVE_TRADING_READY.md` with backfill info
5. Add logging for backfill progress
6. Document any IBKR API limitations (bar count, lookback period)

---

## Implementation Files to Modify

### Primary Files
1. **`live/run_live.py`** (lines 346-430)
   - Remove `if False:` wrapper
   - Implement chosen backfill approach
   - Add proper error handling

2. **`live/historical_backfill.py`** (entire file)
   - May need refactoring based on chosen approach
   - Fix data injection method
   - Update documentation

### Supporting Files (if needed)
3. **`config/live_config.py`**
   - Add backfill configuration options
   - Enable/disable backfill flag

4. **New file: `live/backfill_actor.py`** (if using Actor approach)
   - Implement custom Actor for coordinated backfill

---

## Risk Assessment

### Low Risk
- ✅ Current system works without backfill (just slower warmup)
- ✅ Changes are isolated to live trading code
- ✅ Backtest functionality unaffected

### Medium Risk
- ⚠️ Bar duplication if backfill overlaps with live bars
- ⚠️ Threading issues if not properly synchronized
- ⚠️ IBKR rate limits on historical data requests

### Mitigation Strategies
1. **Duplication:** End backfill 1-2 hours before current time
2. **Threading:** Use proper asyncio synchronization primitives
3. **Rate Limits:** Implement retry logic with exponential backoff
4. **Rollback:** Keep `if False:` version as backup plan

---

## Timeline Estimate

| Phase | Duration | Complexity |
|-------|----------|------------|
| Phase 1: Research | 2-3 hours | Medium |
| Phase 2: Implementation | 4-6 hours | High |
| Phase 3: Testing | 2-3 hours | Medium |
| Phase 4: Documentation | 1-2 hours | Low |
| **Total** | **9-14 hours** | **High** |

---

## Alternative: Accept Natural Warmup

If backfill proves too complex or unstable:

**Recommendation:** Run paper trading for 3 days without live capital risk, then enable real positions after warmup completes.

**Timeline:**
- Day 1-3: Strategy warming up (no trades)
- Day 3+: Strategy active and generating signals
- Total delay: Same as fixing backfill (~10 hours effort vs 65 hours wait)

**Benefits:**
- Zero implementation risk
- Validates live trading infrastructure
- Tests IBKR connection stability
- Monitors strategy behavior in real-time

---

## Next Steps

1. **Commit current changes** to preserve live trading setup
2. **Create feature branch** for backfill work: `feature/historical-backfill-fix`
3. **Begin Phase 1** research into NautilusTrader data injection APIs
4. **Decision point:** After Phase 1, decide if backfill is worth the complexity

---

## Success Criteria

✅ **Minimum Success:**
- Strategy receives 260 bars before going live
- Indicators calculate correctly from historical data
- No errors during backfill process

✅ **Full Success:**
- Strategy ready within 5 minutes of startup
- Smooth transition to live bars
- Comprehensive error handling
- Clear logging of backfill progress
- Works reliably across restarts

---

**Status:** PLAN CREATED - Awaiting approval to proceed
**Created:** November 20, 2025
**Author:** GitHub Copilot
**Priority:** Medium (system works without it, but 65-hour warmup is inconvenient)
