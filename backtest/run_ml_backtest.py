#!/usr/bin/env python3
"""
Backtesting runner for the ML Signal strategy using NautilusTrader.

Uses the same BacktestNode pipeline as run_backtest.py but configures for ML strategy.
Loads existing backtest config (symbol, venue, dates, etc.) from environment.
"""
from __future__ import annotations

# Add project root to path first
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Now import everything else
import json
import logging
from datetime import datetime

import pandas as pd

from nautilus_trader.backtest.config import (
    BacktestRunConfig,
    BacktestEngineConfig,
    BacktestVenueConfig,
    BacktestDataConfig,
)
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar

from config.backtest_config import get_backtest_config, validate_backtest_config
from utils.instruments import create_instrument

def create_ml_backtest_config(
    symbol: str,
    venue: str,
    start_date: str,
    end_date: str,
    catalog_path: str,
    bar_spec: str,
    position_size: int,
    starting_capital: float,
    # ML strategy specific
    model_path: str = "models/strategy_model.joblib",
    prediction_threshold: float = 0.6,
    enforce_position_limit: bool = True,
    max_positions: int = 1,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.0,
    partial_close_enabled: bool = True,
    partial_close_fraction: float = 0.5,
    partial_close_move_sl_to_be: bool = True,
    session_start: str = "02:00",
    session_end: str = "16:00",
    excluded_hours: list[int] = [0, 1],
    feature_warmup_bars: int = 30,
) -> BacktestRunConfig:
    """Create BacktestRunConfig for ML strategy, mirroring run_backtest.py pattern."""
    # Get instrument (reuse create_instrument from run_backtest.py)
    instrument = create_instrument(symbol, venue)
    
    # Create strategy config using ImportableStrategyConfig
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy:MLSignalStrategy",
        config_path="strategies.ml_strategy_config:MLSignalStrategyConfig",
        config={
            "instrument_id": str(instrument.id),
            "bar_spec": bar_spec,
            "position_size": str(position_size),
            "order_id_tag": "ML_SIGNAL",
            "model_path": model_path,
            "prediction_threshold": prediction_threshold,
            "enforce_position_limit": enforce_position_limit,
            "max_positions": max_positions,
            "sl_atr_mult": sl_atr_mult,
            "tp_atr_mult": tp_atr_mult,
            "partial_close_enabled": partial_close_enabled,
            "partial_close_fraction": partial_close_fraction,
            "partial_close_move_sl_to_be": partial_close_move_sl_to_be,
            "session_start": session_start,
            "session_end": session_end,
            "excluded_hours": excluded_hours,
            "feature_warmup_bars": feature_warmup_bars,
        },
    )
    
    # Create venue config (same as run_backtest.py)
    venue_config = BacktestVenueConfig(
        name=venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=[f"{starting_capital:.2f} USD"],
    )
    
    # Create data config (same as run_backtest.py)
    start_ns = dt_to_unix_nanos(pd.Timestamp(start_date, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(end_date, tz="UTC").to_pydatetime())
    
    data_config = BacktestDataConfig(
        catalog_path=catalog_path,
        data_cls=Bar,
        instrument_id=str(instrument.id),
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )
    
    # Create engine config (same as run_backtest.py)
    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )
    
    # Build final config (same pattern as run_backtest.py)
    config = BacktestRunConfig(
        engine=engine_config,
        data=[data_config],
        venues=[venue_config],
        raise_exception=True,
        dispose_on_completion=False,
    )
    
    return config


def run_backtest() -> None:
    """Run ML strategy backtest using BacktestNode pipeline."""
    # Load backtest config from environment (same as run_backtest.py)
    config = get_backtest_config()
    validate_backtest_config(config)
    
    # Create ML-specific BacktestRunConfig
    run_config = create_ml_backtest_config(
        symbol=config.symbol,  # EUR/USD
        venue=config.venue,
        start_date=config.start_date,
        end_date=config.end_date,
        catalog_path=str(config.catalog_path),
        bar_spec=config.bar_spec,
        position_size=config.trade_size,
        starting_capital=config.starting_capital,
        # ML strategy specific params
        model_path="models/strategy_model.joblib",
        prediction_threshold=0.45,  # Higher threshold for better win rate (fewer but higher quality trades)
        enforce_position_limit=True,
        max_positions=1,
        sl_atr_mult=1.5,  # Same as training
        tp_atr_mult=2.0,  # Reward:Risk > 1
        partial_close_enabled=True,
        partial_close_fraction=0.5,
        partial_close_move_sl_to_be=True,
        session_start="02:00",  # London pre
        session_end="16:00",   # NY close
        excluded_hours=[0, 1], # Illiquid hours
        feature_warmup_bars=50,  # Increased from 30 to ensure MACD (26+9=35) has enough data
    )
    
    # Create and run backtest node (same as run_backtest.py)
    node = BacktestNode(configs=[run_config])
    node.build()
    node.run()
    
    # Get engine and reports
    engine = node.get_engine(run_config.id)
    orders_df = engine.trader.generate_orders_report()
    positions_df = engine.trader.generate_positions_report()
    
    # Save reports
    output_dir = PROJECT_ROOT / "backtest_results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    orders_df.to_csv(output_dir / "orders.csv")
    positions_df.to_csv(output_dir / "positions.csv")
    
    # Print summary
    print("\nBacktest Results:")
    print("-" * 50)
    print(f"Period: {config.start_date} to {config.end_date}")
    print(f"Total Trades: {len(positions_df)}")
    
    if len(positions_df) > 0:
        # Convert realized_pnl to numeric (remove " USD" suffix if present)
        if positions_df['realized_pnl'].dtype == 'object':
            positions_df['realized_pnl'] = positions_df['realized_pnl'].str.replace(' USD', '', regex=False)
        positions_df['realized_pnl'] = pd.to_numeric(positions_df['realized_pnl'], errors='coerce')
        
        # Basic metrics
        total_pnl = positions_df['realized_pnl'].sum()
        win_rate = (positions_df['realized_pnl'] > 0).mean() * 100
        profit_factor = abs(positions_df[positions_df['realized_pnl'] > 0]['realized_pnl'].sum() / 
                           positions_df[positions_df['realized_pnl'] < 0]['realized_pnl'].sum())
        
        # Trade analysis
        avg_win = positions_df[positions_df['realized_pnl'] > 0]['realized_pnl'].mean()
        avg_loss = positions_df[positions_df['realized_pnl'] < 0]['realized_pnl'].mean()
        reward_risk_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        
        # Print results
        print("\nProfitability Metrics:")
        print(f"Total PnL: ${total_pnl:,.2f}")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Profit Factor: {profit_factor:.2f}")
        
        print("\nTrade Statistics:")
        print(f"Average Win: ${avg_win:,.2f}")
        print(f"Average Loss: ${avg_loss:,.2f}")
        print(f"Largest Win: ${positions_df['realized_pnl'].max():,.2f}")
        print(f"Largest Loss: ${positions_df['realized_pnl'].min():,.2f}")
        print(f"Average Trade: ${positions_df['realized_pnl'].mean():,.2f}")
        print(f"Reward/Risk Ratio: {reward_risk_ratio:.2f}")
        
        # Save performance metrics
        metrics = {
            'period': {'start': config.start_date, 'end': config.end_date},
            'total_trades': len(positions_df),
            'total_pnl': float(total_pnl),
            'win_rate': float(win_rate),
            'profit_factor': float(profit_factor),
            'reward_risk_ratio': float(reward_risk_ratio),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'largest_win': float(positions_df['realized_pnl'].max()),
            'largest_loss': float(positions_df['realized_pnl'].min()),
            'avg_trade': float(positions_df['realized_pnl'].mean())
        }
        
        with open(output_dir / "performance_metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_dir}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        run_backtest()
    except Exception as exc:  
        logging.error("Backtest failed", exc_info=exc)
        sys.exit(1)
