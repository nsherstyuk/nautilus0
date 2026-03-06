# Nautilus0 — Codebase Guide for Agent Review

> **Purpose:** This document gives a new agent (or human) everything needed to understand,
> review, and improve this codebase. Read it top-to-bottom before touching any code.

---

## 1. Project Summary

**Nautilus0** is an automated trading system that trades Gold (XAUUSD) and EUR/USD (EURUSD)
via Interactive Brokers (IBKR). It has gone through multiple strategy generations:

| Generation | Strategy | Status | Outcome |
|-----------|----------|--------|---------|
| v1 | ML-based MTF (multi-timeframe) bracket | **Retired** | Moderate backtests, poor live parity |
| v2 | ML MTF with entry confirmation + failsafe | **Retired** | Best ML variant, but still parity issues |
| v3 | NautilusTrader-based replay backtest | **Retired** | Framework experiment, abandoned |
| v4 | Tick-bar meta-labeling system | **Retired** | No robust edge found after exhaustive audit |
| **v5** | **Asian Range Breakout (ORB)** | **ACTIVE — LIVE TRADING** | Simple rule-based, profitable, validated |

**The only code that runs in production is inside `v5_xauusd_orb/`.** Everything else is historical.

### Live Performance (as of 2026-03-05)
- **Account NLV:** $4,212
- **Live trades:** 5 (4W / 1L = 80% win rate)
- **Live P&L:** +$244.13
- **Instruments:** XAUUSD (1 oz), EURUSD (20k units)
- **Reconciliation:** 5/5 trades EXCELLENT (all math/fill/BE/exit/P&L checks pass)

---

## 2. Project History (Read `docs/journal/` for Full Details)

The project evolved through five phases. Each phase is documented in session handover files
inside `docs/journal/`. Read these chronologically to understand every decision.

### Phase 1: ML Parity Investigation (Feb 20-21, 2026)
**Problem:** Live ML strategy produced different results from backtest.
**Root cause:** Idempotency bug causing duplicate bars in live data feed.
**Fix:** Added deduplication guard. But deeper parity issues remained.
**Files:** `docs/journal/2026-02-20_*`, `docs/journal/2026-02-21_*`

### Phase 2: ML Model Critique & v4 Architecture (Feb 22-23, 2026)
**Decision:** ML model had fundamental issues (overfitting, noisy features).
Started building `trading_system_v4/` — a modular tick-bar system with meta-labeling.
**Files:** `docs/journal/2026-02-22_*`, `docs/journal/2026-02-23_*`

### Phase 3: v4 Tick-Bar Exploration (Feb 23-25, 2026)
**Explored:** EURUSD tick-level market-making, breakout signals, meta-labeling.
**Conclusion:** After exhaustive signal audit, **no robust edge found at tick level.**
**Files:** `docs/journal/2026-02-24_*`, `docs/journal/2026-02-25_*`

### Phase 4: Pivot to v5 ORB (Feb 27-28, 2026)
**Insight:** Simple rule-based Asian Range Breakout has strong backtest edge on XAUUSD.
Backtested 2015-2025 (2,268 trading days). Optimized BE rule, RR ratio, slippage modeling.
**Key config:** 2h breakeven trigger, $2 BE offset, RR=2.0, skip Wednesdays.
**Files:** `docs/journal/2026-02-27_*`, `docs/journal/2026-02-28_*`

### Phase 5: Live Deployment (Mar 2-5, 2026)
**Deployed** multi-instrument live trading. Fixed 5 bugs in first 3 days.
Added EURUSD as second instrument. Built HTML dashboard.
**Files:** `docs/journal/2026-03-02_*` through `docs/journal/2026-03-05_*`

### Phase 6: Guardrails & Reconciliation (Mar 5, 2026)
**Added** 5 safety guardrails for real-money readiness: daily loss limit, max position check,
orphaned order detection, email notifications, graceful shutdown. Built log-based
reconciliation script that validates live trade math, fills, BE timing, exits, and P&L.
**Files:** `v5_xauusd_orb/guardrails.py`, `v5_xauusd_orb/reconcile.py`

---

## 3. Active System Architecture (v5 ORB)

### Strategy Logic: Asian Range Breakout

```
UTC 00:00-06:00   Observe Asian session → record High/Low of range
UTC 07:00/08:00   Place bracket: BUY STOP above High, SELL STOP below Low
                  Each with SL (opposite side of range) and TP (RR × range_size away)
UTC 08:00-16:00   Wait for fill → monitor position:
                    - If SL hit → loss, done
                    - If TP hit → win, done
                    - After be_hours (2h): move SL to entry + offset (breakeven rule)
                    - At trade_end_hour (16:00 UTC): close at market (EOD rule)
```

### State Machine (per instrument)

```
IDLE → RANGE_COMPUTED → ORDERS_PLACED → IN_TRADE → DONE_TODAY
  │         │                │              │
  │         │                │              └─ SL/TP/BE/EOD triggers exit
  │         │                └─ Fill detected → IN_TRADE
  │         └─ Range too tight/wide → DONE_TODAY (skip)
  └─ Asian range closes → compute range
```

State is persisted to JSON after every transition. Process can restart without losing state.

### Process Architecture

```
orb_multi_live.py
  ├── SharedConnection (1 IBKR connection via ib_insync)
  ├── Guardrails (daily loss limit, position guard, orphan scan, notifications)
  ├── InstrumentManager[XAUUSD] (own state machine, own state file)
  ├── InstrumentManager[EURUSD] (own state machine, own state file)
  └── Main loop: poll all managers every 10 seconds
        ├── Pre-trade guardrail check (loss limit + max positions)
        ├── Writes STATUS line to log every cycle
        └── Updates account_snapshot.json periodically
```

### Daily Lifecycle

The process is launched by Windows Task Scheduler via `daily_launcher.ps1`:
1. **19:10 UTC (day before)** — Process starts, connects to IB Gateway
2. **00:00 UTC** — Asian range observation begins
3. **06:00 UTC** — Range computed, filters applied
4. **07:00-08:00 UTC** — Bracket orders placed (EURUSD at 07:00, XAUUSD at 08:00)
5. **One side fills** → IN_TRADE, other side cancelled
6. **BE rule** — After 2h in trade, move SL to breakeven + offset
7. **16:00 UTC** — EOD close: any open position closed at market
8. **Process exits** after all instruments reach DONE_TODAY

---

## 4. Directory Structure

```
nautilus0/                              # Repository root
│
├── CODEBASE.md                         # THIS FILE — start here
├── README.md                           # Legacy readme (v2 focused, outdated)
├── requirements.txt                    # Python dependencies
├── .env                                # Base environment variables
├── .gitignore                          # Excludes archive/, tick_vault_data/, state files
│
├── v5_xauusd_orb/                      # ★ ACTIVE LIVE TRADING CODE ★
│   ├── config.yaml                     #   All strategy parameters (instruments, sessions, BE, RR)
│   ├── config.py                       #   Dataclass definitions + YAML loader
│   ├── orb_multi_live.py               #   ★ Main live trading script (multi-instrument)
│   ├── orb_live.py                     #   Legacy single-instrument version (superseded)
│   ├── orb_signal.py                   #   Standalone signal checker (no trading)
│   ├── ibgw_manager.py                 #   IB Gateway process health monitor
│   ├── daily_launcher.ps1              #   Windows Task Scheduler launcher
│   ├── setup_scheduler.ps1             #   Installs the scheduled task
│   ├── guardrails.py                   #   ★ Safety guardrails (loss limit, pos guard, orphans, notify)
│   ├── reconcile.py                    #   ★ Live trade parity validator (log-based)
│   ├── status_report.py                #   ★ HTML dashboard generator
│   ├── status.html                     #   Generated dashboard output (gitignored)
│   ├── backtest.py                     #   Single-instrument XAUUSD backtest
│   ├── backtest_exits.py               #   Exit-only backtest (test SL/TP/BE variants)
│   ├── backtest_multi_fx.py            #   Multi-instrument backtest engine
│   ├── analyze_seasonality.py          #   Day-of-week / hour analysis
│   ├── analyze_be_sensitivity.py       #   Breakeven parameter sensitivity
│   ├── _tmp_backtest_stats.py          #   Temporary analysis script
│   ├── _tmp_cutoff_sweep.py            #   Temporary analysis script
│   ├── logs/                           #   Runtime logs (gitignored)
│   │   ├── orb_multi_live.log          #     Main process log (STATUS lines every 10s)
│   │   ├── orb_xauusd_trades.csv       #     Completed XAUUSD trade log
│   │   ├── orb_eurusd_trades.csv       #     Completed EURUSD trade log
│   │   └── backtest_trades.csv         #     Full backtest results (2,268 days)
│   └── state/                          #   Runtime state files (gitignored)
│       ├── orb_xauusd_state.json       #     XAUUSD state machine snapshot
│       ├── orb_eurusd_state.json       #     EURUSD state machine snapshot
│       └── account_snapshot.json       #     Latest IBKR account summary
│
├── docs/                               # All documentation
│   ├── journal/                        #   ★ Session handovers (chronological project story)
│   │   ├── README.md                   #     Timeline index with phases & key decisions
│   │   ├── 2026-02-20_*.md             #     ... through ...
│   │   └── 2026-03-05_*.md             #     20 session documents
│   ├── design/                         #   Architecture docs, action plans (23 files)
│   │   ├── project_overview.md         #     Most comprehensive single overview
│   │   ├── development_guidelines.md   #     Coding rules
│   │   ├── failsafe_implementation.md  #     v2 fail-safe design
│   │   └── ...
│   └── reference/                      #   User guides (5 files)
│       ├── live_trading_startup.md     #     How to start live trading
│       └── mtf_v2_user_guide.md        #     v2 user guide (historical)
│
├── strategies/                         # v2/v3 ML strategies (HISTORICAL, not running)
│   ├── ml_strategy_mtf_v2.py           #   "Classic V2" — source of truth for ML approach
│   ├── ml_strategy_mtf_v2_entry_confirmed.py
│   ├── ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py
│   ├── feature_engineering_v3.py       #   Feature computation
│   └── ...
│
├── live/                               # v2/v3 live trading runners (HISTORICAL)
│   ├── run_live_mtf_v2.py
│   ├── ib_bar_streamer.py
│   └── ...
│
├── config/                             # v2/v3 config loaders (HISTORICAL)
├── models/                             # ML models (.pkl files, gitignored)
├── scripts/                            # Utility scripts (data download, analysis)
├── backtest/                           # v2/v3 backtest infrastructure
├── tests/                              # Test files
├── utils/                              # Shared utilities
├── data/                               # Historical data (gitignored)
│
├── trading_system_v4/                  # v4 tick-bar system (HISTORICAL — no edge found)
│   ├── execution/                      #   Live execution layer
│   ├── features/                       #   Feature engineering
│   ├── model/                          #   Meta-labeling models
│   ├── scripts/                        #   Research scripts
│   └── ...
│
├── v4/                                 # v4 strategy attempt (HISTORICAL)
│
├── run_backtest_mtf_v2_entry_confirmed.py  # Active v2 backtest runner (kept for reference)
│
├── IBKR-MCP-Server/                    # MCP server for IBKR (gitignored, separate repo)
│
└── archive/                            # ★ All old/unused files (gitignored)
    ├── analysis_scripts/               #   ~70 one-off analysis scripts
    ├── backtest_runners/               #   13 old backtest variants
    ├── env_backups/                    #   26 .env backup files
    ├── logs/                           #   Old trader logs (67MB+)
    ├── outputs/                        #   Backtest outputs, tmp files, CSVs
    ├── optimization_results/           #   612 optimization run folders
    ├── optimization/                   #   Optimization infrastructure
    ├── patches/                        #   IBKR adapter patches
    ├── reports/                        #   27 report files
    └── research/                       #   10 research scripts
```

---

## 5. Key Files Deep Dive

### 5.1 `v5_xauusd_orb/orb_multi_live.py` (~1,400 lines)
The heart of the live system. Key classes:

- **`SharedConnection`** — Manages single IBKR connection via `ib_insync`. Handles reconnection with exponential backoff. Provides `get_price()`, `get_asian_range()`, `place_bracket()`.
- **`InstrumentManager`** — One per instrument. Contains the state machine (`tick()` method called every cycle). Handles: range computation, order placement, fill detection, SL/TP monitoring, breakeven application, EOD close. Receives `Guardrails` instance for pre-trade checks and post-trade P&L tracking.
- **`InstrumentState`** — Persisted JSON state. Fields: `status`, `direction`, `entry_price`, `sl_price`, `tp_price`, `be_applied`, `entry_time`, order IDs, range data.
- **`status_line()`** — Generates the periodic log line (parsed by dashboard).
- **`run_day()`** — Orchestrates one trading day: init managers, guardrail daily reset, verify orders on startup, poll loop, cleanup.
- **`graceful_shutdown()`** — Imported from `guardrails.py`. Cancels pending orders, closes open positions, sends shutdown notification.

### 5.2 `v5_xauusd_orb/config.yaml` (~170 lines)
Single source of truth for all parameters. Three sections matter most:

- **`instruments.XAUUSD`** — Gold config: London 08:00-16:00 UTC, RR=2.0, BE=2h/$2, skip Wed, 1 oz
- **`instruments.EURUSD`** — FX config: London 07:00-16:00 UTC, RR=2.0, BE=2h/2pips, no skip days, 20k units
- **`guardrails`** — Safety config: daily loss limit ($50), max positions per instrument (1), orphan detection, email notification settings

### 5.3 `v5_xauusd_orb/status_report.py` (~1,240 lines)
Generates `status.html` dashboard. Features:
- Account summary (from `account_snapshot.json`)
- Per-instrument state cards with live price, price ladder, distances
- "Why still open?" panel for IN_TRADE positions
- Time progress bars (trade duration, EOD countdown, BE countdown)
- Process health banner (alive/down based on last log age)
- Account staleness warning
- Activity timeline (parsed from log)
- Trade history with statistics

### 5.4 `v5_xauusd_orb/backtest_multi_fx.py` (~500 lines)
Multi-instrument backtest engine using OHLC data. Simulates exact same logic as live:
Asian range detection → bracket placement → fill simulation → SL/TP/BE/EOD exits.
Outputs: per-trade CSV, summary statistics, Sharpe, drawdown.

### 5.5 `v5_xauusd_orb/config.py` (~250 lines)
Dataclass definitions matching `config.yaml`. `load_config()` returns typed config objects:
`StrategyConfig`, `PositionConfig`, `IBKRConfig`, `GatewayConfig`, `PathsConfig`,
`InstrumentConfig`, `GuardrailsConfig`, `NotificationConfig`.

### 5.6 `v5_xauusd_orb/guardrails.py` (~440 lines)
Safety guardrails for live trading. Created once in `main()`, passed to all managers.

- **`Guardrails`** — Composite class. `on_startup()` runs orphan scan + loads today's P&L. `can_trade()` checks loss limit + position count before every order placement. `on_trade_closed()` tracks P&L and sends fill notification.
- **`DailyLossTracker`** — Tracks realized P&L per day. Loads from trade CSVs on restart. Halts trading if losses exceed `daily_loss_limit_usd`.
- **`PositionGuard`** — Queries IBKR positions to prevent duplicate entries. Scans for orphaned orders/positions on startup.
- **`Notifier`** — SMTP email sender. Sends alerts on fill, error, startup, shutdown, and daily loss limit breach. Disabled by default.
- **`graceful_shutdown()`** — Called on SIGINT/SIGTERM and in `finally` block. Cancels pending orders, closes positions, logs forced exits, sends notification.

### 5.7 `v5_xauusd_orb/reconcile.py` (~640 lines)
Live trade parity validator. Parses `orb_multi_live.log` to extract what the system computed
and validates correctness:

- **Math check** — Are entry/SL/TP correctly derived from the Asian range?
- **Fill check** — How much slippage on the stop-entry fill?
- **BE check** — Was breakeven applied at the right time (2h) with correct offset?
- **Exit check** — Did the trade exit at the expected TP/SL/TIME price?
- **P&L check** — Does logged P&L match entry→exit arithmetic?

Grades each trade: `EXCELLENT`, `GOOD`, `OK`, `ISSUE`. Run with:
```powershell
python -m v5_xauusd_orb.reconcile           # all trades
python -m v5_xauusd_orb.reconcile --save     # save CSV
python -m v5_xauusd_orb.reconcile --date 2026-03-05
```

---

## 6. Data Files & Formats

### Live Trade Logs (`v5_xauusd_orb/logs/orb_*_trades.csv`)
```csv
timestamp,date,instrument,direction,entry,exit,sl,tp,range_high,range_low,range_size,qty,pnl_per_unit,pnl_total,result,hold_minutes
2026-03-03T11:29:05,2026-03-03,XAUUSD,SHORT,5304.73,5153.7,5302.73,5156.19,5379.96,5305.37,74.59,1,151.03,151.03,TP,174
```
- **result** values: `TP` (take profit), `SL` (stop loss), `TIME` (EOD close)

### Live Process Log (`v5_xauusd_orb/logs/orb_multi_live.log`)
Contains timestamped STATUS lines every 10 seconds:
```
2026-03-05 10:59:23 [XAUUSD] SHORT | price=5098.93 | entry=5147.91 SL=5145.91 TP=5055.31 | PnL=+49.98 | BE applied
```

### State Files (`v5_xauusd_orb/state/orb_*_state.json`)
```json
{
  "status": "IN_TRADE",
  "trade_date": "2026-03-05",
  "direction": "SHORT",
  "entry_price": 5147.91,
  "sl_price": 5145.91,
  "tp_price": 5055.31,
  "be_applied": true,
  "entry_time": "2026-03-05T08:10:23",
  "range_high": 5195.02,
  "range_low": 5148.45,
  "range_size": 46.57
}
```

### Account Snapshot (`v5_xauusd_orb/state/account_snapshot.json`)
```json
{
  "timestamp": "2026-03-05T15:59:23+00:00",
  "net_liquidation": "4212.49",
  "total_cash": "9306.58",
  "unrealized_pnl": "51.83",
  "buying_power": "9951.35",
  "maint_margin": "1120.80"
}
```

### Backtest Data (`v5_xauusd_orb/logs/backtest_trades.csv`)
2,268 rows covering XAUUSD from 2015-01-01 to 2025-12-31. Same CSV format as live trades
but with additional `range_pct` and `hold_bars` columns.

---

## 7. Configuration Reference

### `v5_xauusd_orb/config.yaml` — Key Parameters

| Parameter | XAUUSD | EURUSD | Description |
|-----------|--------|--------|-------------|
| `asian_start_hour` | 0 | 0 | UTC hour range observation starts |
| `asian_end_hour` | 6 | 6 | UTC hour range observation ends |
| `trade_start_hour` | 8 | 7 | UTC hour bracket orders placed |
| `trade_end_hour` | 16 | 16 | UTC hour positions force-closed |
| `rr_ratio` | 2.0 | 2.0 | TP = RR × range_size from entry |
| `be_hours` | 2 | 2 | Hours in trade before breakeven applied |
| `be_offset` | $2.0 | 2 pips | Distance SL moves past entry (covers costs) |
| `skip_weekdays` | [2] (Wed) | [] | Days with no edge |
| `max_pending_hours` | 4 | 4 | Cancel unfilled orders after N hours |
| `qty` | 1 oz | 20,000 units | Position size |
| `min_range_pct` | 0.05% | 0.01% | Skip if range too tight |
| `max_range_pct` | 2.0% | 2.0% | Skip if range too wide |

### IBKR Connection
- **Port 4002:** Paper trading (IB Gateway)
- **Port 4001:** Live trading (IB Gateway)
- **Client ID 60:** Used by live process
- **Client ID 99:** Used by data ingestion (avoid conflicts)

---

## 8. Backtest Results Summary

### XAUUSD (2015-2025, 2,268 trading days)
From `v5_xauusd_orb/logs/backtest_trades.csv`:
- Simulated with realistic slippage ($0.15) + spread ($0.10)
- Config: 2h BE rule, $2 offset, RR=2.0, skip Wednesdays
- Results documented in `docs/journal/2026-02-28_v5_orb_session_handover.md`

### Key Backtest Metrics
- **Sharpe ratio:** ~4.28 (with corrected cost model)
- **Profit factor:** ~3.31
- **Max drawdown:** ~$36
- **Robust:** Neighboring parameter values (90min BE, no BE) perform similarly → not overfitted

### EURUSD (Backtested Separately)
- Lower edge than XAUUSD but still positive
- Added for diversification
- Results in `docs/journal/2026-03-02_v5_orb_handover.md`

---

## 9. Known Issues & Improvement Areas

### Bugs Fixed (for reference)
1. **`skip_weekdays` used wall-clock day** instead of trade date → skipped wrong days
2. **Stale order handling** — orders from previous crash not detected on restart → added `verify_orders_on_startup()`
3. **EURUSD trade window** mismatch between live and backtest → aligned to 07:00 UTC
4. **Gap-open stale price** skip logic was counterproductive → removed (gap trades are profitable)
5. **Cancel scope** — cancelled wrong side's orders on fill → fixed

### Implemented (Previously Planned)
- ~~**Slippage tracking**~~ → Implemented in `reconcile.py` (mean slippage: $0.24)
- ~~**Dashboard automation / push notifications**~~ → Implemented in `guardrails.py` (email on fill/error/restart)
- ~~**Backtest validation**~~ → Implemented in `reconcile.py` (5/5 trades pass all checks)
- ~~**Daily loss limit, max trades per day**~~ → Implemented in `guardrails.py`

### Potential Improvements to Investigate
1. **Position sizing** — Currently fixed (1 oz XAUUSD, 20k EURUSD). Could scale with account size or volatility.
2. **Additional instruments** — GBP/USD, AUD/USD, or other session-breakout candidates.
3. **Range quality filters** — Beyond min/max%, consider range shape, volume, or volatility regime.
4. **Adaptive BE timing** — BE at 2h is static. Could adapt based on range size or time of day.
5. **Trailing stop after BE** — Once SL is at breakeven, add a trailing component to capture runners.
6. **Multi-day analysis** — Does yesterday's result predict today's edge? Consecutive loss avoidance?
7. **Correlation analysis** — When both instruments trigger, are they correlated? Should we reduce size?
8. **Code quality** — `orb_multi_live.py` is ~1,400 lines. Could refactor into smaller modules.
9. **Test coverage** — No automated tests for the v5 code. Add unit tests for state machine, BE logic, range computation.

---

## 10. How to Run

### View Dashboard
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.status_report
# Opens status.html in browser
```

### Run Reconciliation (validate live trades)
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.reconcile           # all trades
python -m v5_xauusd_orb.reconcile --save     # also save CSV
python -m v5_xauusd_orb.reconcile --date 2026-03-05  # single date
```

### Run Backtest (XAUUSD only)
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.backtest
```

### Run Multi-Instrument Backtest
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.backtest_multi_fx
```

### Start Live Trading (dry run)
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.orb_multi_live --dry-run
```

### Start Live Trading (paper)
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.orb_multi_live --port 4002
```

### Start Live Trading (real money)
```powershell
cd c:\nautilus0
python -m v5_xauusd_orb.orb_multi_live --port 4001
```

### Run v2 ML Backtest (historical reference)
```powershell
cd c:\nautilus0
python run_backtest_mtf_v2_entry_confirmed.py
```

---

## 11. Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| IBKR connectivity | `ib_insync` (wrapper around IB TWS/Gateway API) |
| Broker | Interactive Brokers (IBKR) |
| Gateway | IB Gateway 10.41 (auto-managed by `ibgw_manager.py`) |
| Scheduling | Windows Task Scheduler (via `daily_launcher.ps1`) |
| Config | YAML (`config.yaml`) + Python dataclasses (`config.py`) |
| State persistence | JSON files (one per instrument) |
| Logging | Python `logging` module → rotating file handler |
| Dashboard | Static HTML generated by `status_report.py` (no web server needed) |
| Historical backtesting | Custom engine (`backtest_multi_fx.py`) using OHLC bars |
| Data format | CSV (trade logs, backtest results) |
| ML (v2, retired) | NautilusTrader framework + scikit-learn/XGBoost models |

### Key Dependencies (`requirements.txt`)
```
ib_insync
pyyaml
pandas
numpy
```

---

## 12. For the Reviewing Agent

### Priority Review Areas
1. **`v5_xauusd_orb/orb_multi_live.py`** — This is the production code managing real money. Review for:
   - Edge cases in state machine transitions
   - Reconnection/failure handling robustness
   - Order management correctness (fill detection, cancellation, modification)
   - Breakeven application logic
   - EOD close reliability

2. **`v5_xauusd_orb/config.yaml`** — Are the parameters well-justified? Cross-reference with backtest data.

3. **`v5_xauusd_orb/backtest_multi_fx.py`** — Does it accurately simulate live logic? Any discrepancies that would invalidate results?

4. **`v5_xauusd_orb/logs/backtest_trades.csv`** — 2,268 days of backtest data. Analyze for:
   - Regime changes (does the edge persist across all years?)
   - Seasonal patterns (which months/days are strongest?)
   - Drawdown clustering (are losses correlated?)
   - Parameter sensitivity (is the edge fragile?)

5. **Live vs backtest comparison** — Run `python -m v5_xauusd_orb.reconcile` to validate all live trades against expected behavior. Currently 5/5 EXCELLENT.

6. **`v5_xauusd_orb/guardrails.py`** — Review guardrail logic for edge cases: daily loss tracker persistence, orphan detection scope, notification reliability.

### Questions to Answer
- Are there race conditions in the order management code?
- What happens if IB Gateway restarts mid-trade?
- Is the $2 BE offset for XAUUSD justified given current spread/slippage?
- Should the RR ratio be different for each instrument?
- Is the EURUSD edge strong enough to justify trading it?
- Is the $50 daily loss limit appropriate for this account size and strategy?
- Should orphaned positions be auto-closed or manually reviewed?

### Data Analysis Opportunities
- **Regime analysis:** Split backtest by year, by volatility regime (VIX), by trend direction
- **Time-in-trade analysis:** Do trades closed by TIME (EOD) vs TP/SL have different characteristics?
- **Range quality:** Does range size, shape, or Asian session volume predict trade outcome?
- **Entry timing:** Is there an optimal time within the trade window for fills?
- **Correlation:** When both XAUUSD and EURUSD trade the same day, are outcomes correlated?
- **Cost sensitivity:** How sensitive is the edge to spread/slippage assumptions?
- **Walk-forward:** Run rolling 2-year train / 1-year test to confirm out-of-sample stability
