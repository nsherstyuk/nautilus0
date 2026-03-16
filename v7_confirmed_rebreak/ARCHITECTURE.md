# V7 Confirmed Rebreak Strategy -- Deep Modules Architecture

**Date:** 2026-03-12
**Philosophy:** John Ousterhout's *A Philosophy of Software Design*
**Based on:** Tick Volume Imbalance Investigation (docs/journal/2026-03-12)

---

## Strategy Summary

Trade the "confirmed rebreak" pattern on XAUUSD:
1. Price crosses a local pivot level (high or low)
2. Volume imbalance DIVERGES from the breakout direction (weak breakout)
3. Price pulls back through the level
4. Price re-crosses the same level with MATCHING imbalance (confirmed breakout)
5. Enter in the breakout direction after imbalance confirmation

Research shows OOS edge of +$0.50 to +$2.16 per trade (after $0.30 spread)
at 30-60 min hold, 55-60% win rate, with pw=30-60.

---

## Design Principles

1. **Deep modules, simple interfaces.** Each module hides significant complexity
   behind a narrow interface. The strategy never touches raw arrays or indices.

2. **The strategy is a pure state machine.** It receives signals from deep modules
   and issues commands to the execution engine. No data plumbing, no Pandas,
   no file I/O.

3. **Backtest/live parity by construction.** The strategy code runs identically
   in both environments. Only the Runner and ExecutionEngine implementations differ.

4. **Information hiding.** The PatternDetector hides the full state machine of
   pivot tracking, breakout detection, pullback monitoring, and rebreak detection.
   The strategy just receives a `RebreakSignal` when the pattern completes.

---

## Module Map

```
v7_confirmed_rebreak/
  ARCHITECTURE.md
  __init__.py
  config/
    __init__.py
    strategy_config.py      # Frozen dataclass: strategy parameters
  core/
    __init__.py
    market_types.py          # Bar, Fill, RebreakSignal dataclasses
    interfaces.py            # ABCs: MarketContext, ExecutionEngine
    pivot_tracker.py         # Deep: rolling pivot detection, level management
    imbalance_classifier.py  # Deep: buy_ratio computation, divergence classification
    pattern_detector.py      # Deep: full rebreak state machine (orchestrates pivot + imbalance)
  strategy/
    __init__.py
    rebreak_strategy.py      # Pure state machine strategy
  execution/
    __init__.py
    sim_executor.py          # Backtest fill simulation with spread/slippage
  backtest/
    __init__.py
    engine.py                # BacktestRunner: loads data, wires modules, runs loop
    run_backtest.py          # Entry point script
```

---

## The Strategy Interface (The "Inside")

The strategy is trivially simple. It receives signals and manages state:

```python
class RebreakStrategy:
    def on_bar(self, bar: Bar, detector: PatternDetector, execution: ExecutionEngine):
        # Check for new confirmed rebreak signals
        signal = detector.process_bar(bar)
        if signal and signal.confirmed:
            execution.enter(signal.direction, signal.entry_price, signal.sl_price, signal.tp_price)

        # Manage time-based exit
        if self.state == IN_TRADE and self._hold_expired(bar):
            execution.close_at_market(bar)
```

---

## Deep Module A: PatternDetector

**Purpose:** Hides ALL complexity of the multi-step pattern detection.
Internally manages pivot tracking, breakout detection, pullback monitoring,
imbalance classification, and rebreak detection.

**Interface:**
- `process_bar(bar: Bar) -> Optional[RebreakSignal]`
- That's it. One method. Maximum information hiding.

**Internal complexity absorbed:**
- Rolling window pivot high/low detection
- Tracking which levels have been broken and in which direction
- Monitoring for pullbacks after divergent breakouts
- Computing buy_ratio over the imbalance window
- Classifying divergence vs matching
- Managing multiple simultaneous level-tracking states
- Cooldown and deduplication logic

---

## Deep Module B: PivotTracker

**Purpose:** Maintains rolling pivot highs and lows from bar data.

**Interface:**
- `update(bar: Bar)` -- feed new bar
- `current_pivot_high -> Optional[float]`
- `current_pivot_low -> Optional[float]`

**Internal complexity:**
- Circular buffer of highs/lows
- Rolling max/min computation
- Pivot confirmation logic (left-side only for live-safe detection)

---

## Deep Module C: ImbalanceClassifier

**Purpose:** Computes and classifies volume imbalance.

**Interface:**
- `add_bar(bar: Bar)` -- accumulate volume data
- `get_buy_ratio(window: int) -> float` -- buy_ratio over last N bars
- `is_divergent(direction: str, window: int) -> bool`
- `is_matching(direction: str, window: int) -> bool`

---

## Deep Module D: SimExecutionEngine

**Purpose:** Simulates order fills for backtesting.

**Interface:**
- `enter(direction, entry_price, sl_price, tp_price)`
- `close_at_market(bar)`
- `process_bar(bar) -> Optional[Fill]` -- checks SL/TP hits

**Internal complexity:**
- Spread/slippage modeling
- SL/TP bracket tracking
- Fill price computation
- Position state management

---

## Configuration

```python
@dataclass(frozen=True)
class StrategyConfig:
    instrument: str
    pivot_window: int           # bars each side for pivot detection (30 or 60)
    imbalance_window: int       # bars after breakout to measure buy_ratio (3)
    divergence_threshold: float # 0.50
    max_pullback_bars: int      # max bars between first break and rebreak (60)
    min_pullback_bars: int      # min bars for pullback (3)
    tp_atr_multiple: float      # TP as multiple of recent ATR
    sl_atr_multiple: float      # SL as multiple of recent ATR
    max_hold_bars: int          # time stop (60)
    spread_cost: float          # $0.30 for XAUUSD
    atr_period: int             # bars for ATR computation (60)
```

---

## Data Flow

```
1-min CSV bar -> BacktestRunner
  -> PatternDetector.process_bar(bar)
       -> PivotTracker.update(bar)
       -> ImbalanceClassifier.add_bar(bar)
       -> Internal state machine checks
       -> Returns Optional[RebreakSignal]
  -> RebreakStrategy.on_bar(bar, detector, execution)
       -> If signal: execution.enter(...)
       -> If hold expired: execution.close_at_market(bar)
  -> SimExecutionEngine.process_bar(bar)
       -> Checks SL/TP against bar high/low
       -> Returns Optional[Fill]
  -> If fill: strategy.on_fill(fill)
```
