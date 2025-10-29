# Phase 6 Live Trading Deployment Guide

## Table of Contents
- Overview
- Prerequisites
- Quick Start
- Detailed Deployment Steps
- Parameter Selection Guidance
- Configuration Reference
- Troubleshooting
- Rollback Procedures
- Monitoring and Maintenance
- FAQ

---

## Overview

This guide covers deploying Phase 6 optimized parameters to an IBKR paper trading account. Phase 6 parameters are optimized for EUR/USD on 15-minute bars. Always paper trade first before any live deployment. The deployment scripts orchestrate `tools/deploy_phase6_config.py` and enforce validation from `config/phase6_validator.py`.

Optimization results reference: `optimization/results/phase6_refinement_results_top_10.json`.

**What You'll Deploy:**
- 14+ Phase 6 parameters including:
  - Moving averages: fast_period, slow_period
  - Risk management: stop_loss_pips, take_profit_pips, trailing_stop_activation_pips, trailing_stop_distance_pips
  - Signal filters: crossover_threshold_pips
  - DMI: dmi_enabled, dmi_period, dmi_bar_spec
  - Stochastic: stoch_enabled, stoch_period_k, stoch_period_d, stoch_bullish_threshold, stoch_bearish_threshold, stoch_bar_spec

**Deployment Workflow:**

```
[Phase 6 Results] → [Validation] → [.env Generation] → [Backup] → [Activation] → [Live Trading]
```

---

## Prerequisites

### 1. IBKR Paper Trading Account

Paper accounts have a "DU" prefix (e.g., DU1234567). Create and configure a paper account with forex permissions and market data. See IBKR docs: https://www.interactivebrokers.com/en/index.php?f=1286

Recommended: $10,000+ paper balance for realistic testing.

### 2. IBKR TWS or Gateway

- Install TWS or IB Gateway
- Enable API: Configure → Settings → API → Settings
  - Enable ActiveX and Socket Clients
  - Read-Only API enabled
  - Socket port: 7497 (TWS paper) or 4002 (Gateway paper)
- Start and keep running during live trading

### 3. Python Environment

- Python 3.10+
- Install dependencies: `pip install -r requirements.txt`

### 4. Historical Data

- EUR/USD ParquetDataCatalog in `data/historical/`
- Bar specs: 15-MINUTE-MID-EXTERNAL (primary), 2-MINUTE-MID-EXTERNAL (DMI)
- Verify: `python data/verify_catalog.py`

### 5. Phase 6 Optimization Results

- Required: `optimization/results/phase6_refinement_results_top_10.json`
- Optional: `optimization/results/phase6_refinement_results_summary.json`

If missing, run Phase 6 optimization: `./optimization/scripts/run_phase6.ps1` (Windows) or `./optimization/scripts/run_phase6.sh` (Linux/Mac).

---

## Quick Start

1. Ensure IBKR TWS/Gateway is running (port 7497 for paper)
2. Run deployment script:

```powershell
# Windows
.\scripts\deploy_phase6_to_paper.ps1 -Rank 1

# Linux/Mac
./scripts/deploy_phase6_to_paper.sh --rank 1
```

3. Configure IBKR connection in `.env`:

```bash
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU1234567
```

4. Start live trading:

```bash
python live/run_live.py
```

5. Monitor logs:

```bash
tail -f logs/live/live_trading.log
```

---

## Detailed Deployment Steps

### Step 1: Review Phase 6 Results

List available configurations:

```bash
python tools/deploy_phase6_config.py --list
```

Example metrics:

```
Rank  Run ID  Sharpe    Total PnL      Win Rate    Trades  Rejected
1     21      0.4809    10859.43       62.07%      58      272
2     15      0.4652    9234.12        59.32%      59      285
```

Recommendation: Start with Rank 1 for paper trading.

### Step 2: Run Deployment Tool (Dry Run)

```powershell
# Windows
.\scripts\deploy_phase6_to_paper.ps1 -Rank 1 -DryRun

# Linux/Mac
./scripts/deploy_phase6_to_paper.sh --rank 1 --dry-run
```

Dry run previews validation and .env generation without writing files.

### Step 3: Run Validation Checks

Validation categories include: symbol matching, bar spec compatibility, IBKR paper account, parameter ranges, position sizing, data feed availability.

Common warnings and fixes:
- Provide account balance: `--account-balance 50000`
- Set IBKR account in `.env`: `IB_ACCOUNT_ID=DU1234567`

### Step 4: Generate .env File

```powershell
# Windows (basic)
.\scripts\deploy_phase6_to_paper.ps1 -Rank 1

# Windows (with account balance)
.\scripts\deploy_phase6_to_paper.ps1 -Rank 1 -AccountBalance 50000

# Linux/Mac (basic)
./scripts/deploy_phase6_to_paper.sh --rank 1

# Linux/Mac (with account balance)
./scripts/deploy_phase6_to_paper.sh --rank 1 --account-balance 50000
```

Outputs:
- `.env.phase6`
- `.env.phase6_summary.txt`

### Step 5: Backup Existing Configuration

Automatic backup: `.env.backup.YYYYMMDD_HHMMSS`

### Step 6: Activate Phase 6 Configuration

The script copies `.env.phase6` to `.env`. Ensure IBKR connection settings are set:

```bash
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU1234567
IB_MARKET_DATA_TYPE=DELAYED_FROZEN
```

### Step 7: Verify IBKR Connection

```powershell
# Windows
Test-NetConnection -ComputerName localhost -Port 7497

# Linux/Mac
nc -zv localhost 7497
```

### Step 8: Pre-Flight Checklist

- [ ] TWS/Gateway running and API enabled
- [ ] Paper account (DU prefix)
- [ ] `.env` contains Phase 6 parameters
- [ ] IBKR connection configured
- [ ] Adequate balance
- [ ] Market data subscription
- [ ] Logs directory exists
- [ ] Backup exists

### Step 9: Start Live Trading

```bash
python live/run_live.py
```

Expected startup includes configuration load, IBKR connection, data subscriptions, and strategy initialization.

### Step 10: Monitor Live Trading

```bash
tail -f logs/live/live_trading.log
```

Look for market data, signal generation, orders, and fills. Use Ctrl+C to stop gracefully.

---

### Step 11: Enable Performance Monitoring

What is Performance Monitoring?

Performance monitoring tracks live trading metrics in real-time and compares them to Phase 6 backtest expectations. It helps you:
- Detect performance degradation early
- Validate that live results match backtest expectations
- Identify when parameters need re-optimization
- Track key metrics: PnL, win rate, Sharpe ratio, drawdown

Enable Monitoring (Recommended):

Performance monitoring is enabled by default. Verify in `.env`:
```bash
ENABLE_PERFORMANCE_MONITORING=true
PERFORMANCE_MONITOR_INTERVAL=60  # Poll every 60 seconds
```

How It Works:
1. Monitor polls portfolio state every 60 seconds (configurable)
2. Captures metrics: PnL, trade count, win rate, Sharpe ratio, drawdown
3. Compares to Phase 6 benchmark expectations
4. Generates alerts when performance deviates significantly
5. Saves snapshots to `logs/live/performance_metrics.json`

Monitored Metrics:
- Cumulative PnL: Total realized profit/loss vs Phase 6 expected PnL
- Win Rate: Percentage of winning trades vs Phase 6 win rate (62.07% for Rank 1)
- Trade Count: Number of trades vs expected frequency (~2 trades/week for Rank 1)
- Rolling Sharpe Ratio: Risk-adjusted returns vs Phase 6 Sharpe (0.4809 for Rank 1)
- Drawdown: Current and maximum drawdown vs Phase 6 max drawdown

Alert Thresholds:
- Win rate drops >10% below backtest (e.g., from 62% to <52%)
- Sharpe ratio drops >20% below backtest
- Drawdown exceeds backtest maximum
- Trade frequency deviates >50% from expected
- Consecutive losses exceed backtest maximum + 2

Viewing Monitoring Data:
```bash
# View raw metrics file
cat logs/live/performance_metrics.json

# Generate daily performance report
python live/generate_performance_report.py --period daily

# Generate weekly performance report
python live/generate_performance_report.py --period weekly

# Generate full report (all data)
python live/generate_performance_report.py --period full
```

Performance Reports:

Reports are generated in `logs/live/reports/` directory:
- `daily_report_{timestamp}.json`: JSON format with detailed metrics
- `daily_report_{timestamp}.md`: Markdown summary for easy reading

Report sections:
1. Live performance summary (actual metrics)
2. Phase 6 benchmark (expected metrics)
3. Performance comparison (deviations)
4. Alerts triggered during period
5. Recommendation (PASS/CAUTION/FAIL)

Interpreting Reports:

PASS: Live performance matches or exceeds backtest expectations
- Continue trading with current parameters
- Monitor weekly for any changes

CAUTION: Minor deviations from backtest expectations
- Review alerts and investigate causes
- Monitor more frequently (daily instead of weekly)
- Consider running out-of-sample validation on recent data
- No immediate action required unless deviations worsen

FAIL: Significant performance degradation
- Action Required: Stop trading and investigate
- Possible causes:
  - Market conditions changed (trending vs ranging)
  - Parameter overfitting (Phase 6 not robust)
  - Execution issues (slippage, rejected orders)
  - Data quality problems
- Next Steps:
  1. Stop live trading immediately
  2. Run out-of-sample validation: `python tools/validate_phase6_oos.py --rank 1 --periods <recent_periods>`
  3. Analyze recent market conditions
  4. Consider re-optimization or switching to different Phase 6 rank
  5. Resume trading only after investigation complete

Disabling Monitoring:

If you need to disable monitoring (not recommended):
```bash
# In .env file
ENABLE_PERFORMANCE_MONITORING=false
```

Reasons to disable:
- Testing/debugging live trading infrastructure
- Minimal system resources (monitoring adds ~1-2% CPU overhead)
- Custom monitoring solution in place

Monitoring Overhead:
- CPU: ~1-2% (polling every 60 seconds)
- Memory: ~10-20 MB (snapshot history)
- Disk: ~1-5 MB per day (metrics file growth)
- Network: None (local monitoring only)

Troubleshooting Monitoring:

Problem: "Performance metrics file not found"
- Cause: Monitoring hasn't started or file creation failed
- Fix: Check logs for monitor initialization errors. Verify `logs/live/` directory exists and is writable.

Problem: "No snapshots in metrics file"
- Cause: Monitor hasn't captured any snapshots yet
- Fix: Wait at least one poll interval (60 seconds). Check that trading node is running and portfolio is accessible.

Problem: "Benchmark not found in metrics file"
- Cause: Metrics file corrupted or created by old version
- Fix: Delete `logs/live/performance_metrics.json` and restart live trading. Monitor will recreate file with proper structure.

Problem: "Monitor alerts are too sensitive"
- Cause: Alert thresholds may be too strict for early trading (small sample size)
- Fix: Alerts require minimum trade count (10+ trades for win rate, Sharpe). Wait for more trades before evaluating alerts. Thresholds are hardcoded but reasonable for Phase 6 expectations.
## Parameter Selection Guidance

- Rank 1: Highest Sharpe, recommended starting point (~2 trades/week)
- Ranks 2-3: Alternatives with similar risk/return
- Ranks 4-10: Experimental; consider for advanced exploration

Selecting by style:
- Conservative: Rank 1-2
- Moderate: Rank 3-5
- Aggressive: Rank 6-10 (higher frequency, higher risk)

Customization: Prefer minimal changes; adjust trade size first. Re-validate if changing parameters.

---

## Configuration Reference

Examples of environment variables:

```bash
# Trading Symbol and Venue
LIVE_SYMBOL=EUR/USD
LIVE_VENUE=IDEALPRO
LIVE_BAR_SPEC=15-MINUTE-MID-EXTERNAL

# Moving Average Parameters
LIVE_FAST_PERIOD=42
LIVE_SLOW_PERIOD=270

# Risk Management
LIVE_STOP_LOSS_PIPS=30
LIVE_TAKE_PROFIT_PIPS=60
LIVE_TRAILING_STOP_ACTIVATION_PIPS=25
LIVE_TRAILING_STOP_DISTANCE_PIPS=18

# Signal Filter
LIVE_CROSSOVER_THRESHOLD_PIPS=0.5

# DMI Trend Filter
LIVE_DMI_ENABLED=true
LIVE_DMI_PERIOD=14
LIVE_DMI_BAR_SPEC=2-MINUTE-MID-EXTERNAL

# Stochastic Momentum Filter
LIVE_STOCH_ENABLED=true
LIVE_STOCH_PERIOD_K=14
LIVE_STOCH_PERIOD_D=3
LIVE_STOCH_BULLISH_THRESHOLD=30
LIVE_STOCH_BEARISH_THRESHOLD=70
LIVE_STOCH_BAR_SPEC=15-MINUTE-MID-EXTERNAL
LIVE_STOCH_MAX_BARS_SINCE_CROSSING=9

# Position Management
LIVE_TRADE_SIZE=100000
LIVE_ENFORCE_POSITION_LIMIT=true
LIVE_ALLOW_POSITION_REVERSAL=false

# IBKR Connection
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU1234567
IB_MARKET_DATA_TYPE=DELAYED_FROZEN
```

---

## Troubleshooting

Deployment issues:
- Python not found → Install Python 3.10+ and ensure PATH
- Phase 6 config not found → Run optimization scripts
- Validation failed → Address messages (symbol, account type, parameter bounds)

IBKR connection issues:
- TWS/Gateway not detected → Start app, enable API, verify port
- Connection refused 7497 → Check port, firewall, try 4002 (Gateway paper)
- Invalid account ID → Ensure DU prefix in `.env`

Live trading issues:
- No data → Market hours, subscription, bar spec availability
- No signals → Strategy selectivity; wait for conditions
- Orders rejected → Margin, order parameters, market hours

Performance issues:
- Worse than backtest → Run OOS validation; consider alternate rank or re-optimization
- Excessive drawdown → Reduce size; compare to max DD in backtest

---

## Rollback Procedures

Quick rollback:

```bash
# Stop live trading (Ctrl+C)
cp .env.backup.YYYYMMDD_HHMMSS .env
python live/run_live.py
```

Complete rollback:

```bash
rm -f .env.phase6 .env.phase6_summary.txt
cp .env.example .env
```

Partial rollback: Edit `.env` and adjust specific parameters (e.g., reduce `LIVE_TRADE_SIZE`).

---

## Monitoring and Maintenance

Daily: verify IBKR running, API enabled, review logs, check balance/margin.

Weekly: review PnL, win rate, trade count, rejected signals, connection stability.

Monthly: generate reports, archive logs, clean backups, validate parameters on recent data.

Log management examples:

```bash
grep "ERROR" logs/live/live_trading.log | tail -20
tar -czf logs/live/archive/logs_$(date +%Y%m%d).tar.gz logs/live/*.log
```

Additional Monitoring Tasks:

Daily:
6. Review performance monitoring alerts in logs
7. Check performance metrics file: logs/live/performance_metrics.json
8. Generate daily performance report if not automated

Weekly:
6. Generate weekly performance report: python live/generate_performance_report.py --period weekly
7. Review performance comparison vs Phase 6 benchmark
8. Investigate any CAUTION or FAIL recommendations
9. Archive old performance reports

Monthly:
6. Generate monthly performance report: python live/generate_performance_report.py --period monthly
7. Comprehensive performance analysis vs Phase 6 expectations
8. Evaluate if parameters need re-optimization (if performance degraded >20%)
9. Archive performance metrics file (backup before cleanup)

---

## FAQ

- Deploy to live? Not initially; paper trade 2-4+ weeks.
- Other symbols? Not recommended; Phase 6 is for EUR/USD; validate first.
- Update parameters? Stop trading, redeploy with new rank, restart.
- Accidental live deploy? Stop immediately; close orders/positions; verify DU account.
- IB Gateway vs TWS? Gateway recommended (use port 4002 for paper).
- Market data not subscribed? Use `IB_MARKET_DATA_TYPE=DELAYED_FROZEN` or subscribe to real-time.

---
Q: How do I know if my live trading is performing as expected?
A: Use performance monitoring. Generate daily reports: `python live/generate_performance_report.py --period daily`. Compare live metrics to Phase 6 benchmark. Look for PASS/CAUTION/FAIL recommendation. Monitor alerts in logs for early warning signs.

Q: What should I do if performance monitoring shows FAIL?
A: Stop trading immediately and investigate. Run out-of-sample validation on recent data. Check for execution issues, market condition changes, or parameter drift. Do not resume trading until investigation is complete and corrective action taken.

Q: How often should I check performance reports?
A: Daily for first 2-4 weeks of paper trading. Weekly after stable performance established. Monthly for long-term monitoring. Always check immediately if alerts are logged.

Q: Can I customize alert thresholds?
A: Alert thresholds are currently hardcoded in `live/performance_monitor.py` (10% win rate drop, 20% Sharpe drop, etc.). These are reasonable defaults based on Phase 6 optimization. Customization requires code modification.

Q: What if I'm not using Phase 6 parameters?
A: Performance monitoring is designed for Phase 6 deployments. If using custom parameters, monitoring will attempt to match them to Phase 6 results or use Rank 1 as default benchmark. For accurate monitoring with custom parameters, disable monitoring or modify the benchmark loading logic.

Document Version: 1.0  
Last Updated: 2025-01-15  
Maintained By: Trading System Team


