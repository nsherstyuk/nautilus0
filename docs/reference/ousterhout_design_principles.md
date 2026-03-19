# Ousterhout's Design Principles Reference

Based on John Ousterhout's *A Philosophy of Software Design* (2018/2021 editions)

---

## Core Philosophy

**Primary goal of software design:** Minimize complexity (cognitive burden on developers)

**Complexity** = anything in the structure that makes the system hard to understand and modify

---

## Main Causes of Complexity

### 1. Dependencies
Code that cannot be understood or changed in isolation. Requires knowing/touching distant parts of the system.

**Examples:**
- Strategy logic directly calling IBKR APIs
- Backtest code duplicated in live trading system
- Global state shared across modules
- Tight coupling between data format and business logic

### 2. Obscurity
Important information is not obvious. Hidden assumptions, magic behavior, poor naming, inadequate documentation.

**Examples:**
- `if self.dry_run` branches scattered throughout
- Magic constants without explanation
- Side effects not documented
- Temporal dependencies (order matters but not obvious)

---

## Symptoms of Complexity (Red Flags)

### Change Amplification
Small conceptual change requires edits in many distant places.

**Example:** Changing velocity threshold requires editing backtest code, live code, config, and multiple state checks.

### Cognitive Load
Need to keep large amounts of system knowledge in head to work safely.

**Example:** To modify order placement, must understand: IBKR API, state machine, dry-run simulation, velocity gate, risk checks, and fill detection.

### Unknown-Unknowns
Easy to introduce subtle bugs/side-effects in distant/unexpected places.

**Example:** Changing poll interval affects velocity detection, order placement timing, and fill race conditions—but this isn't obvious from the code.

---

## Core Fighting Techniques

### 1. Information Hiding (Parnas)
Each module should encapsulate a few key design decisions. Expose only a clean, narrow, simplified interface.

**Example:**
```python
# Bad (leaky)
def place_order(ib_contract, ib_order, is_dry_run, broker_api):
    if is_dry_run:
        simulate_fill(...)
    else:
        broker_api.placeOrder(ib_contract, ib_order)

# Good (hidden)
execution_engine.place_bracket(entry, sl, tp, direction)
# Engine hides: IBKR details, dry-run logic, order IDs, callbacks
```

### 2. Deep Modules (Most Important)
Prefer **deep** modules: lots of powerful/complex functionality hidden behind a **simple, narrow, obvious interface**.

Avoid **shallow** modules: simple implementation but complex/leaky interface that forces callers to understand too much.

**Deep module characteristics:**
- Simple interface (few parameters, clear names)
- Complex implementation (hides difficult details)
- High abstraction value (does a lot with little caller burden)

**Example (Deep):**
```python
class DataProvider(ABC):
    @abstractmethod
    def get_bars(self, start: datetime, end: datetime) -> List[Bar]:
        """Get bars. Caller doesn't know if CSV, IBKR, or database."""
        pass
```

**Example (Shallow):**
```python
class DataProvider:
    def get_bars_from_csv(self, path, format, delimiter, ...):
        """Caller must know file format details."""
        pass
    def get_bars_from_ibkr(self, contract, timeframe, ...):
        """Different interface for different sources."""
        pass
```

### 3. Pull Complexity Downwards
Implementations should absorb/hide complexity so higher layers see something obvious and easy.

**Prioritize:** Simple **interfaces** over simple **implementations**

**Example:**
```python
# Bad: Strategy code handles complexity
if dry_run:
    # Complex simulation logic in strategy
    if price >= entry:
        if check_spread() and check_slippage():
            fill_at = simulate_fill_price(...)
else:
    # Complex IBKR logic in strategy
    order = create_bracket_order(...)
    ib.placeOrder(contract, order)

# Good: Complexity pulled into ExecutionEngine
execution_engine.place_bracket(entry, sl, tp, direction)
# Engine handles ALL complexity internally
```

### 4. Avoid Decomposition for Its Own Sake
Many small interdependent modules can **increase** complexity rather than reduce it.

**Bad decomposition:**
- `OrderValidator` → `OrderPlacer` → `OrderTracker` → `FillChecker`
- Each needs to know about the others
- Simple change requires touching all 4

**Good decomposition:**
- `ExecutionEngine` (deep module)
- Hides all order lifecycle complexity
- Caller just places bracket, gets fill events

---

## Specific Patterns to Eliminate

### 1. Environment Awareness in Business Logic
**Bad:**
```python
class Strategy:
    def on_tick(self, tick):
        if self.is_backtest:
            # Different logic for backtest
        else:
            # Different logic for live
```

**Good:**
```python
class Strategy:
    def on_tick(self, tick: Tick):
        # Same logic always
        # Environment differences hidden in DataProvider and ExecutionEngine
```

### 2. Global State
**Bad:**
```python
CURRENT_POSITION = None
DRY_RUN_MODE = False

def place_order(...):
    if DRY_RUN_MODE:
        simulate(...)
```

**Good:**
```python
class ExecutionEngine:
    def __init__(self, mode: ExecutionMode):
        self._mode = mode  # Encapsulated
    
    def place_bracket(self, ...):
        # Mode checked internally, not globally
```

### 3. Leaky Abstractions
**Bad:**
```python
# CSV format leaks into strategy
df = strategy.get_data()  # Returns Pandas DataFrame
strategy.process(df['close'], df['volume'])

# IBKR types leak into strategy
ticker = strategy.get_price()  # Returns ib_insync.Ticker
price = ticker.marketPrice()
```

**Good:**
```python
# Universal types hide data source
price = data_provider.get_current_price()  # Returns float
# Could be CSV, IBKR, or database—strategy doesn't know
```

---

## Trading System Specific Guidance

### Backtesting vs Live
**Core principle:** Should differ only in data source and execution simulator—strategy logic must not know/care.

**Ideal architecture:**
```
Strategy (pure logic, environment-agnostic)
    ↓
DataProvider interface    ExecutionEngine interface
    ↓                           ↓
LiveDataProvider          IBKRExecutor
HistoricalDataProvider    SimExecutor
```

**Anti-patterns:**
- Strategy reading CSVs directly
- Strategy talking to broker APIs
- `if is_backtest` checks in business logic
- Different code paths for backtest vs live

### Hidden Complexity Targets
These should be hidden inside deep modules:

**In ExecutionEngine:**
- Risk checks
- Slippage modeling
- Fill simulation
- Order ID tracking
- Broker-specific APIs

**In DataProvider:**
- File formats (CSV, Parquet, HDF5)
- API differences (IBKR, Dukascopy, etc.)
- Data gaps handling
- Timezone conversions
- Tick aggregation

**In Strategy:**
- None! Strategy should be pure business logic.

---

## Design Quality Checklist

Use these questions to evaluate module design:

### Interface Simplicity
- [ ] Can I explain what this module does in one sentence?
- [ ] Are parameter names self-explanatory?
- [ ] Does caller need to read implementation to use it?
- [ ] Could I use this module without knowing implementation details?

### Information Hiding
- [ ] Are implementation details truly hidden?
- [ ] Can I change implementation without affecting callers?
- [ ] Does interface force callers to know about internal state?

### Deep vs Shallow
- [ ] Does this module hide significant complexity?
- [ ] Is the benefit proportional to interface size?
- [ ] Could I merge this with another module to make it deeper?

### Dependencies
- [ ] Can I understand this module in isolation?
- [ ] How many other modules must I know about?
- [ ] Does changing this module require changing others?

### Obscurity
- [ ] Are side effects documented?
- [ ] Are temporal dependencies obvious?
- [ ] Would a new developer understand the intent?

---

## Example: Deep Module Design

### Bad (Shallow)
```python
class BacktestExecutor:
    def place_order(self, price, sl, tp, bars, spread):
        # Caller must provide bars and spread
        pass

class LiveExecutor:
    def place_order(self, contract, ib_connection, order_type):
        # Completely different interface
        pass

# Strategy must know which executor and adapt
if backtest:
    executor.place_order(price, sl, tp, bars, spread)
else:
    executor.place_order(contract, ib, "MKT")
```

### Good (Deep)
```python
class ExecutionEngine(ABC):
    @abstractmethod
    def place_bracket(self, entry: float, sl: float, tp: float, 
                     direction: str) -> OrderSet:
        """Place bracket order. Returns order IDs."""
        pass

class SimExecutor(ExecutionEngine):
    def place_bracket(self, entry, sl, tp, direction):
        # Hides: bar access, spread model, fill simulation
        pass

class IBKRExecutor(ExecutionEngine):
    def place_bracket(self, entry, sl, tp, direction):
        # Hides: contract, connection, IBKR API details
        pass

# Strategy code identical for both
engine.place_bracket(entry=2850, sl=2840, tp=2860, direction="LONG")
```

**Why this is deep:**
- Simple interface (4 parameters, clear purpose)
- Complex implementation hidden (bars, spread, IBKR API, simulation)
- High abstraction value (caller doesn't care about execution details)
- Easy to add new executors without changing strategy

---

## Quick Reference Card

**When designing a module, ask:**

1. **What complexity am I hiding?**
   - If answer is "not much" → consider merging into larger module

2. **What must callers know?**
   - If answer is "a lot" → interface is too leaky

3. **Can I implement this differently without changing the interface?**
   - If answer is "no" → you're leaking implementation details

4. **Does this module do one thing well?**
   - If answer is "it does many things" → check if it's shallow decomposition

5. **Would I want to use this interface if I didn't write it?**
   - If answer is "no" → interface needs simplification

---

## Anti-Pattern Detection

### Code Smells Indicating Complexity Problems

**Smell:** Many small classes that reference each other
**Problem:** Shallow decomposition
**Fix:** Merge into fewer, deeper modules

**Smell:** `if environment` checks in business logic
**Problem:** Leaky abstraction
**Fix:** Hide environment in implementation layer

**Smell:** Caller must pass many parameters
**Problem:** Module not hiding enough
**Fix:** Pull parameters into module state or config

**Smell:** Change in A requires change in B, C, D
**Problem:** High coupling, poor information hiding
**Fix:** Define clear interfaces, hide dependencies

**Smell:** Can't understand module without reading others
**Problem:** Excessive dependencies
**Fix:** Make modules more self-contained

---

## Further Reading

- *A Philosophy of Software Design* by John Ousterhout (2018, 2nd ed. 2021)
- Key chapters:
  - Ch 4: Modules Should Be Deep
  - Ch 5: Information Hiding (and Leakage)
  - Ch 6: General-Purpose Modules are Deeper
  - Ch 7: Different Layer, Different Abstraction
  - Ch 9: Better Together Or Better Apart?

---

**Last updated:** 2026-03-16  
**Context:** Applied to v6 ORB trading system refactor
