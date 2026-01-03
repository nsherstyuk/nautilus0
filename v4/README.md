# V4 Dynamic SL/TP Strategy

## Overview
V4 implements dynamic stop loss and take profit based on trading hours and weekdays, building on MTF V2 but keeping it completely separate.

## Key Features
- Dynamic SL multipliers by hour (1.0x to 1.6x ATR)
- Dynamic TP multipliers for high-performance hours (0.6x to 0.8x ATR)
- Weekday performance adjustments
- Separate configuration and backtest infrastructure

## File Structure
```
v4/
├── config/
│   ├── mtf_v4_config.py          # V4 configuration loader
│   └── dynamic_params.py         # Dynamic SL/TP parameters
├── strategies/
│   └── ml_strategy_mtf_v4.py     # V4 strategy with dynamic SL/TP
├── backtest/
│   ├── run_backtest_mtf_v4_replay.py
│   └── analyze_v4_results.py
├── live/
│   └── run_live_mtf_v4.py
├── .env.mtf_v4                   # V4 environment file
└── README.md                     # This file
```

## Quick Start
1. Configure `.env.mtf_v4` with your settings
2. Run backtest: `python v4/backtest/run_backtest_mtf_v4_replay.py`
3. Analyze results: `python v4/backtest/analyze_v4_results.py`

## Dynamic Parameters
- Hour-based SL: 1.0x (low fade) to 1.6x (high fade) ATR
- Hour-based TP: 0.5x (poor performance) to 0.8x (high performance) ATR
- Weekday multipliers: ±10% adjustment

## vs V2
- V2: Static SL=1.2x, TP=0.6x ATR
- V4: Dynamic SL/TP based on extensive backtest analysis
- Separate codebase - no impact on V2 live trading
