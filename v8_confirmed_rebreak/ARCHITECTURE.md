# V8 Confirmed Rebreak -- Architecture

## Design Principles

1. **Single PatternDetector for backtest AND live** -- no code duplication
2. **Pure state machine** -- PatternDetector receives pivots + buy_ratio from outside
3. **No delayed assessment** -- caller provides buy_ratio via callback; same interface, different data sources
4. **Proven parity** -- V8 backtest reproduces V7 engine_v2 results exactly (1150 trades, +$1863, 57.4% WR)

## Module Map

```
v8_confirmed_rebreak/
├── config/
│   └── strategy_config.py      # Frozen dataclass: pure strategy parameters
├── core/
│   ├── types.py                # Bar, RebreakSignal, Fill, TradeRecord (frozen)
│   ├── pivot_computer.py       # batch_centered() + rolling_centered()
│   ├── imbalance_classifier.py # Rolling buy/sell volume buffer (used by live)
│   └── pattern_detector.py     # THE deep module: pure state machine
├── backtest/
│   ├── runner.py               # Pre-computes pivots+ATR, loops PatternDetector
│   ├── run_backtest.py         # CLI entry point
│   └── walk_forward.py         # Walk-forward validation + multi-instrument
├── live/
│   ├── live_config.py          # Broker + environment config
│   ├── live_engine.py          # RollingBuffer + PatternDetector + trade mgmt
│   └── run_live.py             # IBKR connection, bar aggregation, main loop
├── execution/                  # (empty -- trade mgmt is inline in runner/engine)
├── strategy/                   # (empty -- pattern detection IS the strategy)
└── tests/
    ├── test_pivot.py           # 6 tests: peak/trough, shift, forward-fill, flat
    ├── test_imbalance.py       # 14 tests: buy_ratio, divergence, matching, reset
    └── test_pattern.py         # 8 tests: long/short signals, timeout, retry, ATR
```

## Data Flow

### Backtest
```
CSV → numpy arrays
         ↓
    batch_centered(highs, lows, window, shift)
         ↓
    pivot_high[], pivot_low[] arrays
         ↓
    for each bar i:
        PatternDetector.process_bar(close[i], i, pivot_high[i], pivot_low[i], get_buy_ratio)
                                                                                    ↑
                                                          lambda: array slice [i+1 : i+imb_w+1]
         ↓
    signal → enter trade at bar i+imb_w → SL/time-stop management inline
```

### Live
```
IBKR stream → BarAggregator → 1-min bars → RollingBuffer
         ↓
    rolling_centered(buffer.highs, buffer.lows, window, shift)
         ↓
    pivot_high[], pivot_low[] over buffer
         ↓
    Process bar at DELAY position (buf_len - 1 - imb_w):
        PatternDetector.process_bar(close[pos], pos, pivot_high[pos], pivot_low[pos], get_buy_ratio)
                                                                                          ↑
                                                              lambda: buffer slice [pos+1 : pos+imb_w+1]
         ↓
    signal → IBKR market order + SL stop order
```

## Key Design Decision: Why No Delayed Assessment

V7's PatternDetector used internal pending dicts to delay buy_ratio assessment by `imb_w` bars.
This created behavioral differences vs engine_v2:
- Blocking: state machine paused during assessment window, missing pullback events
- Kill-on-fail: non-divergent breaks permanently killed the level state

V8 eliminates this by making the caller provide buy_ratio immediately:
- **Backtest**: array lookahead `bars[i+1 : i+imb_w+1]` (same as engine_v2)
- **Live**: processes bars at `imb_w` delay, so lookahead bars exist in buffer

Same PatternDetector code. Same results. Zero divergence.

## Verified Results

| Metric | V7 engine_v2 | V8 runner |
|--------|-------------|-----------|
| Trades | 1,150 | 1,150 |
| PnL | +$1,863.40 | +$1,863.40 |
| Win Rate | 57.4% | 57.4% |
| Avg Hold | 58.1 bars | 58.1 bars |
| Exit Reasons | TIME_STOP: 1055, SL: 95 | TIME_STOP: 1055, SL: 95 |

## Running

```bash
# Backtest
python -m v8_confirmed_rebreak.backtest.run_backtest --pw 60 --confirm 3 --max-hold 60 --sl 10 --start 2023-01-01

# Walk-forward
python -m v8_confirmed_rebreak.backtest.walk_forward --pw 60 --confirm 3

# Unit tests
python -m pytest v8_confirmed_rebreak/tests/ -v

# Live (dry-run)
python -m v8_confirmed_rebreak.live.run_live --dry-run --port 4002
```
