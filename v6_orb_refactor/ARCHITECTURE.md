# V6 ORB Refactor — Deep Modules Architecture
**Date:** 2026-03-11  
**Philosophy:** John Ousterhout's *A Philosophy of Software Design*

## The Core Mandate: Absolute Parity
The highest priority of this architecture is **absolute zero-diff parity** between backtesting and live execution. The trading algorithm (`ORBStrategy`) must run exactly the same code regardless of the data source. It should not even know whether the ticks are coming from a CSV file or a live IBKR socket.

**Previous Problems (v5 score: 3.5/10):**
1. Strategy logic duplicated in backtest (Pandas) and live (state machine)
2. `if self.dry_run` branches pollute core logic (shallow abstraction)
3. God object `InstrumentManager` does everything
4. Direct coupling to IBKR APIs and data formats
5. Strategy acting as data plumber (managing its own tick buffers)

---

## 1. The Strategy Interface (The "Inside")
We design outside-in. We start by defining the ideal, clean, plain-English strategy interface.

The `ORBStrategy` contains **zero** data plumbing, **zero** disk I/O, **zero** Pandas, and **zero** order ID management.

```python
class ORBStrategy:
    """Pure strategy logic. Environment-agnostic."""
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.state = StrategyState.IDLE
        self.range = None

    def on_tick(self, tick: Tick, context: MarketContext, execution: ExecutionEngine):
        """Called on every tick. Pure state machine."""
        if self.state == StrategyState.DONE_TODAY:
            return

        if self.state == StrategyState.IDLE:
            if context.time_is_in_trade_window(tick.timestamp):
                self.range = context.get_asian_range()
                if self.range.is_valid(self.config):
                    self.state = StrategyState.RANGE_READY
                else:
                    self.state = StrategyState.DONE_TODAY

        if self.state == StrategyState.RANGE_READY:
            vel = context.get_velocity(lookback_minutes=self.config.lookback_minutes)
            
            if vel >= self.config.velocity_threshold:
                # Execution handles order IDs, sizing, and bracket legs invisibly
                execution.set_orb_brackets(self.range, self.config.rr_ratio)
                self.state = StrategyState.ORDERS_PLACED
            else:
                execution.cancel_orb_brackets()
                
    def on_fill(self, fill: Fill, context: MarketContext):
        """Called when execution engine reports a fill."""
        self.state = StrategyState.IN_TRADE
        
    def on_trade_closed(self):
        """Called when SL or TP is hit."""
        self.state = StrategyState.DONE_TODAY
```

---

## 2. The Deep Modules (The "Infrastructure")
To support this simple Strategy, we bury the complexity in these deep modules. These modules absorb the complexity of buffering, execution routing, and environment differences.

### Module A: `MarketContext`
* **Purpose:** Hides data history, tick buffering, timezone conversions, and complex aggregations.
* **Interface:** 
  - `get_velocity(lookback_minutes: int) -> float`
  - `get_asian_range() -> RangeInfo`
  - `time_is_in_trade_window(dt: datetime) -> bool`
* **Implementations:**
  - `HistoricalMarketContext`: Pre-loads or streams CSV data, manages an internal tick deque.
  - `LiveMarketContext`: Subscribes to IBKR ticks, maintains a rolling deque, handles connection drops.

### Module B: `ExecutionEngine`
* **Purpose:** Hides broker order IDs, bracket leg tracking, slippage, and fill simulation.
* **Interface:**
  - `set_orb_brackets(range_info: RangeInfo, rr_ratio: float)`
  - `cancel_orb_brackets()`
  - `close_at_market()`
* **Implementations:**
  - `SimExecutionEngine`: Takes brackets, checks tick prices against stop limits to simulate fills, applies spread/slippage, emits `Fill` events back to the strategy.
  - `IBKRExecutionEngine`: Translates `set_orb_brackets` into IBKR Order objects, tracks native Order IDs internally, handles IBKR API race conditions.

### Module C: `Runner` (The Orchestrator)
* **Purpose:** Hides the event loop, state persistence, and module wiring.
* **Responsibilities:**
  - Instantiates Config, Strategy, Context, and Execution.
  - Feeds ticks from the source into the Context (updating history) *before* passing them to `strategy.on_tick()`.
  - In live mode: Transparently saves the Strategy's `self.state` to JSON after every tick/event (Information Hiding: Strategy shouldn't know it's being saved).
* **Implementations:**
  - `BacktestRunner`: High-speed while loop over historical ticks. No JSON state saving.
  - `LiveRunner`: Async event loop. Handles the 2-second polling rhythm, daily resets, JSON state persistence, and safe shutdowns.

---

## 3. Universal Data Types
Both IBKR and CSV data get converted to these at the boundary.

```python
@dataclass(frozen=True)
class Tick:
    timestamp: datetime
    bid: float
    ask: float
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

@dataclass(frozen=True)
class Fill:
    timestamp: datetime
    price: float
    direction: str  # LONG/SHORT
    reason: str     # ENTRY, SL, TP, MARKET
```

---

## 4. Implementation Plan (Strictly Outside-In)

### Phase 1: The Domain Logic (Day 1)
1. Write `strategy/orb_strategy.py` exactly as envisioned above. 
2. Define the ABCs for `MarketContext` and `ExecutionEngine` in `core/` based *only* on what `orb_strategy.py` needs to call.
3. Define the `Tick`, `Fill`, and `RangeInfo` dataclasses in `core/market_event.py`.
4. Define the separated `StrategyConfig` in `config/config.py`.

### Phase 2: The Simulator & Backtest Runner (Day 2-3)
1. Implement `HistoricalMarketContext` (loads CSV, manages tick buffer).
2. Implement `SimExecutionEngine` (takes `set_orb_brackets`, checks tick prices to simulate fills, applies exact $0.30 spread and $0.10 slippage rules from v5).
3. Write `backtest/engine.py` to loop through data and pass it to the strategy.
4. **Integration Test:** Run it on XAUUSD. Prove it perfectly matches the V5 Sharpe 1.81 OOS baseline. This is the ultimate proof the architecture works.

### Phase 3: The Live Infrastructure (Day 4-5)
1. Implement `LiveMarketContext` (wraps IBKR tick feed, manages the same buffer).
2. Implement `IBKRExecutionEngine` (translates `set_orb_brackets` to IBKR API calls).
3. Implement `live/runner.py` (handles state saving/loading from JSON transparently).

### Phase 4: Validation & Swap
1. Run v6 backtest again, verify metrics still match exactly.
2. Run v6 live in dry-run mode, compare velocity logs to v5.
3. Switch production to v6. Archive v5.

---

## Configuration Separation
To prevent environment bleed, configurations are strictly separated:
* `StrategyConfig`: Core parameters (thresholds, hours, RR). Injected into Strategy.
* `BacktestConfig`: File paths, slippage models. Injected into BacktestRunner.
* `LiveConfig`: Risk limits, IBKR ports, JSON paths. Injected into LiveRunner.

## SimExecutor Fill Specification (Crucial for Parity)
To ensure the backtest matches v5, the `SimExecutionEngine` must strictly follow:
1. **Fill Condition:** High >= stop (long), Low <= stop (short)
2. **Fill Price:** Stop price + defined spread (e.g., $0.30)
3. **Sequence:** Check Entry first. If entry fills, activate SL/TP and check them *in the same bar/tick*.
4. **Precedence:** If both SL and TP are hit in the same event, SL takes precedence (conservative).
