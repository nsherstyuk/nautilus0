# Session Handover -- 2026-03-12 11:36 EDT

## Strategy: V7 Confirmed Rebreak (Engine V2)

### What Was Done This Session

1. **Full-sample backtest (2018-2026)** -- COMPLETED
2. **Walk-forward validation (16 half-year windows)** -- COMPLETED
3. **Multi-instrument test (XAUUSD + EURUSD)** -- COMPLETED
4. **Live trading module built** -- COMPLETED

### Backtest Results

**Full-sample (2018-2026):**
- 2,816 trades, +$2,128 PnL, +$0.756/trade, 52.3% WR
- 8/9 years positive (2019 barely negative at -$6.67)
- Edge stronger in recent years (gold volatility regime)

**OOS (2023-2026):**
- 1,150 trades, +$1,863 PnL, +$1.62/trade, 57.4% WR
- All years positive, 7/38 months negative
- Exit reasons: 1,055 TIME_STOP, 95 CATASTROPHE_SL

**Walk-forward (half-year windows 2019-2026):**
- 11/16 windows positive (69%)
- Max consecutive negative windows: 1
- Edge improving: first half avg +$0.15/trade, second half avg +$1.73/trade
- Negative windows are small (worst -$77), positive windows large (best +$680)

**Multi-instrument (OOS 2023+):**
- XAUUSD: 1,150 trades, +$1,863, Sharpe 3.34
- EURUSD: 711 trades, +$20, Sharpe 3.07 (not tradeable after costs)
- Strategy is XAUUSD-specific

### Recommended Config (unchanged)

```
pivot_window=60, confirm_bars=3, max_hold_bars=60
sl_atr_multiple=10, tp_atr_multiple=99 (disabled)
min_bar_ticks=50, spread_cost=0.30
```

### Files Created/Modified

**Modified:**
- `v7_confirmed_rebreak/backtest/engine_v2.py`
  - Added `preloaded_df` parameter and `load_csv()` static method
  - Added empty DataFrame guard in `run()`

**Created:**
- `v7_confirmed_rebreak/backtest/walk_forward.py`
  - 16 half-year windows, loads data once, slices per window
  - Reports PnL, WR, Sharpe, L/S split, SL exits, edge decay analysis
  - Auto-runs EURUSD multi-instrument test if data exists

- `v7_confirmed_rebreak/live/__init__.py`
- `v7_confirmed_rebreak/live/live_config.py`
  - LiveConfig dataclass: IBKR connection, strategy params, safety limits
- `v7_confirmed_rebreak/live/live_engine.py`
  - RollingBuffer (deque, 500 bars), real-time pivot computation
  - Delayed pattern detection (processes bar n-1-imb_w for buy_ratio lookahead)
  - Fixed deque-full stalling bug (monotonic bar_count tracking)
- `v7_confirmed_rebreak/live/run_live.py`
  - IBKRConnection (connect/reconnect, contract qual, price stream, orders)
  - BarAggregator (price updates -> 1-min bars, uptick/downtick buy/sell)
  - Seeds buffer from IBKR historical 1-min bars
  - Trade CSV logging, daily safety limits, graceful shutdown

### Architecture: Live Engine

```
reqMktData (IBKR) -> BarAggregator -> 1-min Bar -> LiveEngine.on_bar()
                                                        |
                                    RollingBuffer (500 bars, deque)
                                                        |
                                    compute_pivots (centered + confirm_bars delay)
                                                        |
                                    pattern detection at bar [n-1-imb_w]
                                    (delayed so buy_ratio lookahead available)
                                                        |
                                    signal -> IBKRConnection.submit_market_order()
                                                   + submit_stop_order()
```

Key design: pattern detection processes bar at index `n-1-imb_w` (not latest).
This provides the `imb_w`-bar lookahead window needed for buy_ratio computation,
exactly matching backtest behavior. Entry happens at current bar `n-1`.

### Commands

```powershell
# Use .venv (NOT .venv312 which has broken numpy)
cd c:\nautilus0

# Full-sample backtest
.\.venv\Scripts\python.exe -m v7_confirmed_rebreak.backtest.run_backtest_v2 --pw 60 --confirm 3 --max-hold 60 --sl 10 --start 2018-01-01

# Walk-forward + multi-instrument
.\.venv\Scripts\python.exe -m v7_confirmed_rebreak.backtest.walk_forward --pw 60 --confirm 3 --max-hold 60 --sl 10

# Live dry-run (needs IBKR Gateway on port 4002)
.\.venv\Scripts\python.exe -m v7_confirmed_rebreak.live.run_live --dry-run
```

### Next Steps

1. **Fix .venv312** -- numpy 2.3.4 has C-extension mismatch with Python 3.12. Either reinstall numpy or use .venv consistently.
2. **Dry-run live test** -- Start IBKR Gateway, run `--dry-run` to verify bar streaming, pivot computation, and signal generation work in real-time.
3. **Paper trade** -- Run without `--dry-run` on paper account to validate order execution flow.
4. **Investigate edge regime dependency** -- The strategy's edge is 10x stronger post-2023 vs 2018-2022. Likely driven by gold volatility ($1300 -> $2900). Consider normalizing PnL by ATR to confirm.
5. **Position sizing** -- Current backtest uses $1/point. Scale qty based on account size and risk tolerance.

### Known Issues

- `.venv312` has broken numpy (C-extension mismatch). Use `.venv` instead.
- EURUSD has near-zero edge (+$0.03/trade) -- not tradeable.
- Live BarAggregator uses uptick/downtick as buy/sell proxy (not true tick data). This is a simplification since XAUUSD CMDTY does not support reqTickByTickData on IBKR.
- Historical bar seeding uses MIDPOINT bars which lack buy/sell volume split. First ~imb_w bars after seeding may have inaccurate buy_ratio until real tick-classified bars accumulate.
