# Nautilus0 — Automated Trading System

**Active strategy:** Asian Range Breakout (ORB) on XAUUSD + EURUSD via Interactive Brokers.

> For the full codebase guide, read [`CODEBASE.md`](CODEBASE.md).

---

## Quick Start

```powershell
# View live dashboard
python -m v5_xauusd_orb.status_report

# Dry run (no real orders)
python -m v5_xauusd_orb.orb_multi_live --dry-run

# Paper trading (IB Gateway port 4002)
python -m v5_xauusd_orb.orb_multi_live --port 4002

# Live trading (IB Gateway port 4001)
python -m v5_xauusd_orb.orb_multi_live --port 4001

# Validate live trades against expected behavior
python -m v5_xauusd_orb.reconcile

# Run multi-instrument backtest
python -m v5_xauusd_orb.backtest_multi_fx
```

---

## Strategy Overview

```
UTC 00:00–06:00   Observe Asian session → record High / Low of range
UTC 07:00/08:00   Place bracket: BUY STOP above High, SELL STOP below Low
                  Each with SL (opposite side) and TP (RR × range_size)
UTC 08:00–16:00   Wait for fill → monitor:
                    SL hit → loss    |  TP hit → win
                    After 2h → move SL to breakeven + offset
                    At 16:00 UTC → close at market (EOD)
```

| Parameter | XAUUSD | EURUSD |
|-----------|--------|--------|
| Trade window | 08:00–16:00 UTC | 07:00–16:00 UTC |
| RR ratio | 2.0 | 2.0 |
| BE trigger | 2 hours | 2 hours |
| BE offset | $2.00 | 2 pips |
| Skip days | Wednesday | None |
| Position size | 1 oz | 20,000 units |

---

## Live Performance (as of 2026-03-05)

| Metric | Value |
|--------|-------|
| Account NLV | $4,212 |
| Live trades | 5 (4W / 1L) |
| Win rate | 80% |
| Live P&L | +$244.13 |
| Reconciliation | 5/5 EXCELLENT |

---

## Architecture

```
v5_xauusd_orb/
├── orb_multi_live.py      Main live trading script (state machine + IBKR orders)
├── config.yaml            All strategy parameters (single source of truth)
├── config.py              Typed dataclass loader for config.yaml
├── guardrails.py          Safety: daily loss limit, position guard, orphan detection,
│                          email notifications, graceful shutdown
├── reconcile.py           Live trade parity validator (parses logs, checks math/fills/P&L)
├── status_report.py       HTML dashboard generator
├── ibgw_manager.py        IB Gateway process health monitor
├── backtest_multi_fx.py   Multi-instrument backtest engine
├── daily_launcher.ps1     Windows Task Scheduler launcher
├── logs/                  Runtime: trade CSVs, process log
└── state/                 Runtime: per-instrument JSON state, account snapshot
```

### Guardrails (new — Mar 5, 2026)

| Feature | Description |
|---------|-------------|
| **Daily loss limit** | Halts new trades if realized losses exceed $50/day |
| **Max position check** | Blocks orders if duplicate positions detected |
| **Orphan detection** | Scans IBKR on startup for stale orders/positions |
| **Email notifications** | Alerts on fill, error, startup, shutdown, loss limit |
| **Graceful shutdown** | Cancels pending orders + closes positions on SIGINT/SIGTERM |

---

## Historical Generations

| Gen | Strategy | Status |
|-----|----------|--------|
| v1 | ML-based MTF bracket | Retired |
| v2 | ML MTF + entry confirmation + failsafe | Retired |
| v3 | NautilusTrader replay backtest | Retired |
| v4 | Tick-bar meta-labeling | Retired — no edge found |
| **v5** | **Asian Range Breakout (ORB)** | **ACTIVE — live trading** |

All retired code remains in the repo under `strategies/`, `live/`, `trading_system_v4/`, `v4/`, and `archive/`.

---

## Key Dependencies

```
ib_insync        # IBKR API wrapper
pyyaml           # Config loader
pandas / numpy   # Data handling
```

Requires **IB Gateway** (or TWS) running locally. See `v5_xauusd_orb/config.yaml` for connection settings.

---

*Last updated: March 5, 2026*
