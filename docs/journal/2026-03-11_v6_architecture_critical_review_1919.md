# V6 Architecture Critical Review
**Date:** 2026-03-11 19:19 EST  
**Reviewer:** Cascade (Windsurf AI)  
**Reviewed Documents:** `v6_orb_refactor/ARCHITECTURE.md`, `SESSION_HANDOVER_2026-03-11_1910.md`

---

## Executive Summary

**Architecture philosophy: 9/10** — Deep modules approach is correct.

**Implementation plan: 5/10** — Phase sequencing is backwards, critical components missing.

**Recommendation:** Pause v6 implementation until architecture gaps are filled. Proceed with v5 dry-run (correct priority).

---

## ✅ What's Excellent

### 1. Core Problem Diagnosis is Correct
The dual codebase problem (backtest pandas vs live state machine) is real and expensive. You're addressing the right pain point. The duplication between backtest logic and live state machine has been a source of bugs and maintenance burden throughout v2-v5.

### 2. Deep Modules Approach is Sound
The ABC-based abstraction (DataProvider, ExecutionEngine) correctly pulls complexity downward following Ousterhout's principles. Strategy being environment-agnostic is the right architectural goal.

### 3. Universal Types are Clean
`Tick`, `Bar`, `Fill` dataclasses eliminate the IBKR/NautilusTrader type confusion that's plagued previous versions. This is a strong foundation for type safety and clarity.

### 4. Information Hiding is Properly Applied
The separation of concerns (data/execution/strategy) follows good software engineering principles. Each module encapsulates its design decisions.

---

## ⚠️ Critical Issues to Address

### 1. **Phase 1 is Backwards (Major Risk)**

**Problem:** Starting with "universal types + pure math" creates **orphaned abstractions**.

Current plan:
```
Phase 1: Create Tick/Bar dataclasses + pure functions
Phase 2: Create ExecutionEngine
Phase 3: Create DataProvider
Phase 4: Extract strategy
```

**Why this fails:**
- You'll build types/functions in a vacuum without knowing actual usage patterns
- When you hit Phase 4 (strategy extraction), you'll discover the types are wrong
- You'll either retrofit (contaminating the clean design) or restart Phase 1
- This is classic "bottom-up" design that leads to speculative generality

**Better approach: Outside-in, not bottom-up**

Start with the interface you WANT, then discover what types are needed:

```python
# Start here (Phase 1):
class ORBStrategy:
    def on_range_close(self, bars: List[Bar]):
        # What do I actually need from Bar?
        range_high = max(b.high for b in bars)
        range_size = range_high - range_low
        tick_count = sum(b.tick_count for b in bars)
        velocity = sum(b.tick_count for b in bars) / len(bars)
        # NOW you know what Bar needs
    
    def on_tick(self, tick: Tick):
        # What do I need from Tick?
        mid_price = tick.mid
        spread = tick.ask - tick.bid
        # NOW you know what Tick needs
```

**Concrete recommendation:**
Write the strategy skeleton FIRST with placeholder types. Let the usage patterns dictate the type structure.

---

### 2. **Missing State Persistence Layer (Critical Gap)**

**Problem:** Architecture has no answer for "where does state live between restarts?"

**In v5:**
- `orb_xauusd_state.json` persists `DONE_TODAY`, range values, orders placed time
- This prevents duplicate trades on restart
- Essential for production safety

**In v6:**
- No state abstraction mentioned
- No file I/O layer specified
- Live runner would be stateless → **dangerous**

**Required addition:**

```python
# core/state_manager.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class StrategyState:
    """State that must persist across restarts."""
    trade_date: str
    state: str  # IDLE, RANGE_READY, ORDERS_PLACED, etc.
    done_today: bool
    range_high: Optional[float]
    range_low: Optional[float]
    orders_placed_time: Optional[datetime]
    position_entry_price: Optional[float]
    
class StateManager(ABC):
    """Deep module: hides all persistence complexity."""
    
    @abstractmethod
    def save(self, state: StrategyState):
        """Persist state to storage."""
        pass
    
    @abstractmethod
    def load(self) -> Optional[StrategyState]:
        """Load state from storage. Returns None if no saved state."""
        pass
    
    @abstractmethod
    def clear(self):
        """Clear all saved state (new trading day)."""
        pass

# Implementations:
class JSONStateManager(StateManager):
    """For live trading - persists to disk."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
    
    def save(self, state: StrategyState):
        with open(self.filepath, 'w') as f:
            json.dump(asdict(state), f)
    # ...

class MemoryStateManager(StateManager):
    """For backtesting - no disk I/O."""
    def __init__(self):
        self._state = None
    
    def save(self, state: StrategyState):
        self._state = state
    # ...
```

**Strategy usage:**
```python
class ORBStrategy:
    def __init__(self, config, data, execution, state_manager):
        self.state_mgr = state_manager
        saved = state_mgr.load()
        if saved and saved.trade_date == today():
            self._restore_state(saved)
    
    def on_fill(self, fill):
        # Update state
        self.state_mgr.save(self._build_state())
```

**This needs to be in the architecture doc NOW, not discovered in Phase 5.**

---

### 3. **Velocity Filter Doesn't Fit the Architecture**

**Problem:** Velocity monitoring requires **continuous polling** of tick history, but DataProvider only supports streaming.

Current DataProvider interface:
```python
class DataProvider(ABC):
    @abstractmethod
    def subscribe_ticks(self, callback: Callable[[Tick], None]):
        """Subscribe to live tick stream."""
        pass
```

**Where do historical ticks live for velocity calculation?**

```python
def on_tick(self, tick: Tick):
    # Strategy needs access to historical ticks for velocity calc
    velocity = calc_velocity(???, lookback_min=3)
    # Where does ??? come from?
```

**Three possible solutions:**

**Option A: Add stateful method to DataProvider (breaks single responsibility)**
```python
class DataProvider(ABC):
    @abstractmethod
    def get_recent_ticks(self, lookback_seconds: int) -> List[Tick]:
        """Last N seconds of ticks (for velocity calc)."""
        pass
```
Problem: Now DataProvider does two things (streaming + buffering).

**Option B: Strategy buffers internally (leaky abstraction)**
```python
class ORBStrategy:
    def __init__(self, ...):
        self._tick_buffer = deque(maxlen=10000)
    
    def on_tick(self, tick):
        self._tick_buffer.append(tick)
        velocity = calc_velocity(self._tick_buffer, ...)
```
Problem: Every strategy reimplements buffering.

**Option C: Separate TickBuffer component (recommended)**
```python
# core/tick_buffer.py
class TickBuffer:
    """Deep module: manages tick history for velocity/stats."""
    
    def __init__(self, max_size: int = 100000):
        self._buffer = deque(maxlen=max_size)
    
    def append(self, tick: Tick):
        """Add tick to buffer."""
        self._buffer.append(tick)
    
    def get_velocity(self, lookback_minutes: int) -> float:
        """Calculate avg ticks/min over lookback window."""
        cutoff = datetime.now() - timedelta(minutes=lookback_minutes)
        recent = [t for t in self._buffer if t.timestamp >= cutoff]
        if not recent:
            return 0.0
        duration_min = (recent[-1].timestamp - recent[0].timestamp).total_seconds() / 60
        return len(recent) / max(duration_min, 0.01)
    
    def get_recent_ticks(self, lookback_minutes: int) -> List[Tick]:
        """Get ticks from last N minutes."""
        cutoff = datetime.now() - timedelta(minutes=lookback_minutes)
        return [t for t in self._buffer if t.timestamp >= cutoff]

# Strategy usage:
class ORBStrategy:
    def __init__(self, config, data, execution, tick_buffer):
        self.tick_buffer = tick_buffer
        data.subscribe_ticks(self._on_tick)
    
    def _on_tick(self, tick: Tick):
        self.tick_buffer.append(tick)  # Keep history
        velocity = self.tick_buffer.get_velocity(lookback_minutes=3)
        if velocity >= self.config.velocity_threshold:
            # Place orders
```

**Add TickBuffer to ARCHITECTURE.md as a core component.**

---

### 4. **SimExecutor Fill Logic is Underspecified**

**From architecture:**
> Uses bar H/L to determine fills, applies spread + slippage

**Critical questions unanswered:**

1. **Stop order fill logic:** Does HIGH touch = guaranteed fill? What about wicks?
2. **Spread application:** Do you widen H/L by spread, or apply at fill time?
3. **Slippage model:** Fixed $ amount? Percentage? Volume-dependent?
4. **Bracket semantics:** If entry fills, do SL/TP go live in same bar or next bar?
5. **Multiple fills per bar:** If entry stop is hit AND SL level is hit in same bar, what happens?

**Real scenario from v5 backtest that must be specified:**

```python
# Bar data:
Bar(timestamp='2024-01-15 08:01', 
    high=2650.50, low=2644.00, 
    open=2648.00, close=2649.00)

# Orders:
entry_stop_long = 2650.00  # Above current price
stop_loss = 2645.00        # Below entry
take_profit = 2655.00      # Above entry

# Questions:
# 1. Does entry fill because bar.high (2650.50) >= entry_stop (2650.00)?
# 2. Fill price = 2650.00 or 2650.00 + spread?
# 3. Bar.low (2644.00) < SL (2645.00) - does SL fill in SAME bar?
# 4. If yes, fill order is: entry first, then SL?
# 5. Final result: small loss on whipsaw?
```

**These need to be documented in architecture, not left to implementation.**

Otherwise v6 backtest won't match v5, and you won't know if discrepancies are bugs or intentional differences.

**Required addition to ARCHITECTURE.md:**

```markdown
### SimExecutor Fill Logic Specification

#### Stop Order Fill Rules
1. **Long entry stop:** Fills if `bar.high >= stop_price`
2. **Short entry stop:** Fills if `bar.low <= stop_price`
3. **Fill price:** `stop_price + spread` (conservative assumption)
4. **Spread:** XAUUSD = $0.30 average (from Dukascopy data analysis)

#### Bracket Order Fill Sequence (Same Bar)
1. Check if entry stop is hit → fill entry at `stop_price + spread`
2. If entry filled, activate SL/TP for remainder of bar
3. Check SL: `bar.low <= sl_price` (long) or `bar.high >= sl_price` (short)
4. Check TP: `bar.high >= tp_price` (long) or `bar.low <= tp_price` (short)
5. If both SL and TP hit same bar → SL takes precedence (conservative)

#### Slippage Model
- Market orders (velocity rejects): +$0.10 (0.1 pips)
- Stop orders: no additional slippage (already in spread)
- Assumes normal market conditions (no flash crashes)

#### Edge Cases
- Entry stop exactly at bar.high: DOES fill
- Zero-spread bars (data gaps): use previous bar's spread
- Multiple bounces (bar crosses SL/TP multiple times): first touch wins
```

---

### 5. **Configuration Management is Vague**

**From plan:**
> config/config.yaml - Same config for both modes

**Problem:** Backtest and live have **fundamentally different** config needs.

**Backtest-only config:**
```yaml
# backtest.yaml
data:
  source: csv
  file_path: data/1m_csv/xauusd_1m_tick.csv
  start_date: 2018-01-01
  end_date: 2026-03-10

simulation:
  spread: 0.30  # USD per oz
  slippage: 0.10
  commission: 0.0  # IBKR included in spread
```

**Live-only config:**
```yaml
# live.yaml
ibkr:
  host: 127.0.0.1
  port: 4002
  client_id: 100

risk:
  max_daily_loss: 100.0  # USD
  max_position_size: 1   # oz
  
state:
  file_path: state/orb_xauusd_state.json
  
logging:
  velocity_csv: logs/velocity_xauusd.csv
  trade_csv: logs/orb_xauusd_trades.csv
```

**Shared strategy config:**
```yaml
# strategy.yaml
instrument: XAUUSD
symbol: XAUUSD
exchange: SMART
sec_type: CMDTY

range_window:
  start_hour: 0
  end_hour: 6
  timezone: UTC

trade_window:
  start_hour: 8
  end_hour: 16
  timezone: UTC

skip_weekdays: [2]  # Wednesday

velocity_filter:
  enabled: true
  lookback_minutes: 3
  threshold: 168  # ticks/min (IBKR calibration pending)

risk_reward:
  rr_ratio: 2.5

range_filter:
  min_range: 1.0   # USD
  max_range: 15.0
```

**Don't force these into one YAML.** Better architecture:

```python
# config/config.py
@dataclass
class StrategyConfig:
    """Pure strategy parameters - same for backtest and live."""
    instrument: str
    range_start_hour: int
    range_end_hour: int
    trade_start_hour: int
    trade_end_hour: int
    velocity_threshold: float
    rr_ratio: float
    # ...

@dataclass
class BacktestConfig:
    """Backtest-specific settings."""
    data_file: Path
    start_date: datetime
    end_date: datetime
    spread: float
    slippage: float

@dataclass
class LiveConfig:
    """Live-specific settings."""
    ibkr_host: str
    ibkr_port: int
    max_daily_loss: float
    state_file: Path
    # ...
```

**Runners load appropriate configs:**
```python
# backtest/engine.py
def run_backtest():
    strategy_cfg = load_yaml('config/strategy.yaml')
    backtest_cfg = load_yaml('config/backtest.yaml')
    # Strategy only sees strategy_cfg

# live/runner.py
def run_live():
    strategy_cfg = load_yaml('config/strategy.yaml')
    live_cfg = load_yaml('config/live.yaml')
    # Strategy only sees strategy_cfg
```

This separation prevents leaking live-specific config into backtests and vice versa.

---

### 6. **Testing Strategy is Absent**

**From success criteria:**
> Each module has unit tests (mocks for interfaces)

**But how do you test the FULL SYSTEM end-to-end?**

Unit tests alone won't catch integration bugs. You need a **regression test** that proves v6 matches v5.

**Required: Backtest Parity Integration Test**

```python
# tests/integration/test_backtest_parity.py
def test_v6_matches_v5_backtest():
    """
    V6 backtest must match v5 baseline on identical data.
    
    Baseline (v5 XAUUSD 2021-2026 OOS with velocity filter):
    - Sharpe: 1.81
    - Total P&L: $1,098
    - Win rate: 51.6%
    - Profit factor: 1.30
    """
    # Load v5 baseline metrics
    v5_baseline = {
        'sharpe': 1.81,
        'total_pnl': 1098,
        'win_rate': 0.516,
        'profit_factor': 1.30,
        'num_trades': 658  # OOS count
    }
    
    # Run v6 backtest on same data
    config = load_strategy_config('config/strategy.yaml')
    backtest_cfg = BacktestConfig(
        data_file=Path('data/1m_csv/xauusd_1m_tick.csv'),
        start_date=datetime(2021, 1, 1),
        end_date=datetime(2026, 3, 10),
        spread=0.30,
        slippage=0.10
    )
    
    results = run_backtest(config, backtest_cfg)
    
    # Assert metrics within tolerance
    assert abs(results.sharpe - v5_baseline['sharpe']) < 0.02, \
        f"Sharpe mismatch: {results.sharpe} vs {v5_baseline['sharpe']}"
    
    assert abs(results.total_pnl - v5_baseline['total_pnl']) < 50, \
        f"P&L mismatch: {results.total_pnl} vs {v5_baseline['total_pnl']}"
    
    assert abs(results.win_rate - v5_baseline['win_rate']) < 0.01, \
        f"Win rate mismatch: {results.win_rate} vs {v5_baseline['win_rate']}"
    
    # Trade count should be exact (same entry signals)
    assert results.num_trades == v5_baseline['num_trades'], \
        f"Trade count mismatch: {results.num_trades} vs {v5_baseline['num_trades']}"
```

**This test should be written in Phase 1** (even though it will fail initially). It gives you:
1. Clear success criteria
2. Regression detection
3. Confidence that v6 actually works

**Add to architecture doc:** Section on "Verification & Testing Strategy"

---

### 7. **Phase Plan Has Wrong Dependencies**

**Current plan:**
```
Phase 1: Types + Math (Day 1)
Phase 2: Execution (Day 2-3)
Phase 3: Data (Day 4-5)
Phase 4: Strategy (Day 6-7)
Phase 5: Runners (Day 8)
```

**Problem:** You can't build Execution (Phase 2) without knowing what events Strategy needs (Phase 4).

Example: What does `Fill` dataclass need?
```python
@dataclass
class Fill:
    timestamp: datetime
    price: float
    direction: str
    order_id: str
    # Do you need commission? Slippage amount? Order type?
    # You won't know until you write Strategy.on_fill()
```

**Better sequencing (outside-in):**

```
Phase 1: Strategy Skeleton + Mock Interfaces (Day 1)
- Write ORBStrategy with placeholder providers
- Mock DataProvider, ExecutionEngine, StateManager
- Discover what interfaces actually need
- Write integration test (will fail, that's OK)

Phase 2: Universal Types (Day 2)
- Build Tick/Bar/Fill to fit Phase 1 usage patterns
- Add TickBuffer component
- Write unit tests for dataclasses

Phase 3: Data Abstraction (Day 3-4)
- Implement HistoricalDataProvider (CSV reader)
- Implement TickBuffer
- Test: Strategy receives ticks, can calculate range/velocity

Phase 4: Execution Abstraction (Day 5-6)
- Implement SimExecutor with EXACT fill logic from spec
- Implement StateManager (JSON + Memory)
- Test: Strategy can place bracket, receive fills, persist state

Phase 5: Complete Strategy Logic (Day 7)
- Port v5 state machine to ORBStrategy
- Remove all `if dry_run` branches
- Hook up real providers

Phase 6: Backtest Runner + Parity Test (Day 8)
- Implement backtest/engine.py
- Run on XAUUSD 2021-2026 data
- Run parity test → must match v5 within 1%

Phase 7: Live Components (Day 9-10)
- Implement LiveDataProvider (IBKR wrapper)
- Implement IBKRExecutor
- Implement live/runner.py

Phase 8: Live Dry-Run Validation (Day 11+)
- Run v6 in dry-run mode
- Compare velocity logs to v5
- Verify state persistence across restarts
```

**Key difference:** Start with what you WANT (strategy interface), then build the pieces to support it.

---

## 📋 Recommended Changes to ARCHITECTURE.md

### Add These Sections (Before Implementation Starts)

#### 1. State Persistence
```markdown
### State Management

**Problem:** Live trading must survive restarts without duplicate trades.

**Solution:** StateManager abstraction

[Include StateManager interface + implementations from Issue #2 above]
```

#### 2. Tick History Management
```markdown
### Tick History for Velocity Calculation

**Problem:** Velocity filter needs access to recent tick history.

**Solution:** TickBuffer component (separate from DataProvider)

[Include TickBuffer interface from Issue #3 above]
```

#### 3. Fill Simulation Specification
```markdown
### SimExecutor Fill Logic Specification

**Critical:** Backtest must use identical fill logic to match v5 baseline.

[Include exact fill rules from Issue #4 above]
```

#### 4. Configuration Architecture
```markdown
### Configuration Strategy

**Problem:** Backtest and live need different configs.

**Solution:** Split into strategy.yaml / backtest.yaml / live.yaml

[Include config separation from Issue #5 above]
```

#### 5. Testing & Verification
```markdown
### Verification Strategy

**Success criteria:** V6 backtest must match v5 within 1% on same data.

**Baseline metrics (v5 XAUUSD OOS 2021-2026):**
- Sharpe: 1.81
- Total P&L: $1,098
- Win rate: 51.6%
- Trades: 658

[Include integration test from Issue #6 above]
```

#### 6. Revised Implementation Phases
```markdown
### Implementation Phases (Revised)

[Include corrected phase plan from Issue #7 above]
```

---

## 🎯 Bottom Line

### What Works
- **Core philosophy:** Deep modules + information hiding is the right approach
- **Problem identification:** You've correctly diagnosed the dual codebase issue
- **Universal types:** Clean abstraction for market data

### What Needs Fixing
1. **Phase sequencing is backwards** → Start with strategy interface, not types
2. **Missing state persistence** → Add StateManager to architecture
3. **Velocity doesn't fit** → Add TickBuffer component
4. **Fill logic underspecified** → Document exact simulation rules
5. **Config strategy vague** → Split backtest/live/strategy configs
6. **No integration tests** → Add backtest parity test
7. **Wrong dependencies** → Resequence phases (outside-in)

### Recommendation

**Do NOT start coding v6 yet.** The architecture has critical gaps that will force mid-flight redesign.

**Action items before Phase 1:**
1. Update ARCHITECTURE.md with all 6 new sections above
2. Write integration test skeleton (test_backtest_parity.py)
3. Sketch ORBStrategy interface with mock providers
4. Get feedback on revised architecture

**Then:**
- Proceed with revised Phase 1 (strategy skeleton)
- Build components to fit the interface
- Run parity test continuously during development

**Parallel track:**
- Run v5 dry-run for IBKR velocity calibration (correct priority)
- Use v5 as production system until v6 proves parity

---

**The refactor is worth doing, but only if the design is complete.** Better to spend an extra day on architecture than waste a week building the wrong abstractions.
