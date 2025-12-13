#!/usr/bin/env python3
"""
Run backtest for MTF ML Strategy (15m + 30m indicators).
Phase 4: Baseline backtest with minimal filters.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import BacktestEngineConfig, BacktestRunConfig, BacktestDataConfig, BacktestVenueConfig, LoggingConfig
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from strategies.ml_strategy_mtf import MLSignalStrategy
from strategies.ml_strategy_config import MLSignalStrategyConfig
from config.mtf_config import load_mtf_config, print_mtf_config

def run_backtest():
    """Run MTF ML strategy backtest using .env.mtf configuration."""
    
    # Load configuration from .env.mtf (same as live trading!)
    print("="*80)
    print("MTF ML STRATEGY BACKTEST")
    print("="*80)
    print("\nLoading configuration from .env.mtf (same as live trading)...\n")
    
    mtf_config = load_mtf_config()
    print_mtf_config(mtf_config)
    
    # Use config values
    instrument_id = f"{mtf_config.symbol}.{mtf_config.venue}"
    start_date = mtf_config.backtest_start_date
    end_date = mtf_config.backtest_end_date
    
    print("\n" + "="*80)
    print("BACKTEST PARAMETERS")
    print("="*80)
    print(f"Instrument: {instrument_id}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Model: {mtf_config.model_path}")
    print(f"Timeframe: {mtf_config.bar_spec}")
    print("="*80)
    
    # Strategy configuration - USING .env.mtf VALUES!
    strategy_config = MLSignalStrategyConfig(
        instrument_id=instrument_id,
        bar_spec=mtf_config.bar_spec,
        position_size=mtf_config.position_size,
        model_path=mtf_config.model_path,
        prediction_threshold=mtf_config.prediction_threshold,
        enforce_position_limit=mtf_config.enforce_position_limit,
        max_positions=mtf_config.max_positions,
        sl_atr_mult=mtf_config.sl_atr_mult,
        tp_atr_mult=mtf_config.tp_atr_mult,
        trailing_stop_enabled=mtf_config.trailing_stop_enabled,
        trailing_activation_atr_mult=mtf_config.trailing_activation_atr_mult,
        trailing_distance_atr_mult=mtf_config.trailing_distance_atr_mult,
        partial_close_enabled=mtf_config.partial_close_enabled,
        partial_close_fraction=mtf_config.partial_close_fraction,
        partial_close_move_sl_to_be=mtf_config.partial_close_move_sl_to_be,
        session_start=mtf_config.session_start,
        session_end=mtf_config.session_end,
        excluded_hours=mtf_config.excluded_hours if mtf_config.excluded_hours else [],
        excluded_hours_by_weekday=mtf_config.excluded_hours_by_weekday if mtf_config.excluded_hours_by_weekday else {},
        feature_warmup_bars=mtf_config.feature_warmup_bars,
        order_id_tag=mtf_config.order_id_tag
    )
    
    # Venue configuration
    venue_config = BacktestVenueConfig(
        name=mtf_config.venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=["100000 USD"]
    )
    
    # Data configuration
    data_config = BacktestDataConfig(
        catalog_path=str(PROJECT_ROOT / "data" / "catalog"),
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=instrument_id,
        bar_spec=mtf_config.bar_spec,
        start_time=start_date,
        end_time=end_date
    )
    
    # Backtest engine configuration (strategies go here!)
    engine_config = BacktestEngineConfig(
        trader_id="BACKTESTER-001",
        logging=LoggingConfig(log_level="INFO"),
        strategies=[strategy_config]
    )
    
    # Run configuration
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config]
    )
    
    # Create and run backtest
    node = BacktestNode()
    node.run(run_config)
    
    # Get results
    engine = node.get_engine(run_config.engine.trader_id)
    
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    
    # Account statistics
    account = engine.cache.account_for_venue(Venue("IDEALPRO"))
    if account:
        print(f"\nStarting Balance: $100,000.00")
        print(f"Ending Balance: ${float(account.balance_total()):,.2f}")
        print(f"P&L: ${float(account.balance_total()) - 100000:,.2f}")
        print(f"Return: {((float(account.balance_total()) / 100000) - 1) * 100:.2f}%")
    
    # Trade statistics
    print(f"\nTotal Orders: {len(engine.cache.orders())}")
    print(f"Total Positions: {len(engine.cache.positions())}")
    
    # Position analysis
    positions = engine.cache.positions()
    if positions:
        long_positions = [p for p in positions if p.entry == "BUY"]
        short_positions = [p for p in positions if p.entry == "SELL"]
        
        print(f"\nLong Positions: {len(long_positions)}")
        print(f"Short Positions: {len(short_positions)}")
        
        # P&L analysis
        winning = [p for p in positions if p.realized_pnl and float(p.realized_pnl) > 0]
        losing = [p for p in positions if p.realized_pnl and float(p.realized_pnl) < 0]
        
        if winning or losing:
            print(f"\nWinning Trades: {len(winning)}")
            print(f"Losing Trades: {len(losing)}")
            print(f"Win Rate: {len(winning) / (len(winning) + len(losing)) * 100:.1f}%")
            
            if winning:
                avg_win = sum(float(p.realized_pnl) for p in winning) / len(winning)
                print(f"Average Win: ${avg_win:,.2f}")
            
            if losing:
                avg_loss = sum(float(p.realized_pnl) for p in losing) / len(losing)
                print(f"Average Loss: ${avg_loss:,.2f}")
            
            if winning and losing:
                rr_ratio = abs(avg_win / avg_loss)
                print(f"Reward/Risk Ratio: {rr_ratio:.2f}")
    
    print("\n" + "="*80)
    print("PHASE 4 BASELINE COMPLETE")
    print("="*80)
    print("\nNext: Analyze results and proceed to Phase 5")
    
    return engine

if __name__ == "__main__":
    engine = run_backtest()
