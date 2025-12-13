#!/usr/bin/env python3
"""
Run backtest for MTF V2 Strategy (Three-Position Bracket Approach).

This strategy opens 3 simultaneous positions with different TPs:
- POS1 (70%): Quick win at 0.9x ATR
- POS2 (20%): Extended at 1.75x ATR  
- POS3 (10%): Runner with trailing stop
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestEngineConfig, 
    BacktestRunConfig, 
    BacktestDataConfig, 
    BacktestVenueConfig, 
    LoggingConfig
)
from nautilus_trader.model.identifiers import Venue

from strategies.ml_strategy_mtf_v2 import MLSignalStrategyV2, MLSignalStrategyV2Config
from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config


def run_backtest():
    """Run MTF V2 strategy backtest."""
    
    print("=" * 80)
    print("MTF V2 BACKTEST - Three-Position Bracket Strategy")
    print("=" * 80)
    
    # Load configuration
    config = load_mtf_v2_config()
    print_mtf_v2_config(config)
    
    # Build instrument ID
    instrument_id = f"{config.symbol}.{config.venue}"
    
    print("\n" + "-" * 80)
    print("BACKTEST PARAMETERS")
    print("-" * 80)
    print(f"Instrument:  {instrument_id}")
    print(f"Period:      {config.backtest_start} to {config.backtest_end}")
    print(f"Model:       {config.model_path}")
    print(f"Balance:     ${config.initial_balance:,.0f}")
    print("-" * 80)
    
    # Strategy configuration
    strategy_config = MLSignalStrategyV2Config(
        instrument_id=instrument_id,
        bar_type=config.bar_type,
        model_path=config.model_path,
        
        # Position sizing
        total_position_size=config.total_position_size,
        pos1_fraction=config.pos1_fraction,
        pos2_fraction=config.pos2_fraction,
        pos3_fraction=config.pos3_fraction,
        
        # SL/TP
        sl_atr_mult=config.sl_atr_mult,
        pos1_tp_atr_mult=config.pos1_tp_atr_mult,
        pos2_tp_atr_mult=config.pos2_tp_atr_mult,
        pos3_tp_atr_mult=config.pos3_tp_atr_mult,
        
        # Trailing
        trailing_activation_atr_mult=config.trailing_activation_atr_mult,
        trailing_distance_atr_mult=config.trailing_distance_atr_mult,
        
        # Filters
        prediction_threshold=config.prediction_threshold,
        trade_start_hour=config.trade_start_hour,
        trade_end_hour=config.trade_end_hour,
        min_atr=config.min_atr,
        max_atr=config.max_atr,
    )
    
    # Venue configuration - allow 3 positions!
    venue_config = BacktestVenueConfig(
        name=config.venue,
        oms_type="NETTING",  # Changed to HEDGING would allow separate positions
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=[f"{int(config.initial_balance)} USD"]
    )
    
    # Data configuration
    data_config = BacktestDataConfig(
        catalog_path=str(PROJECT_ROOT / "data" / "catalog"),
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=instrument_id,
        bar_spec=config.bar_spec,
        start_time=config.backtest_start,
        end_time=config.backtest_end
    )
    
    # Engine configuration
    engine_config = BacktestEngineConfig(
        trader_id="BACKTESTER-V2-001",
        logging=LoggingConfig(log_level="INFO"),
        strategies=[strategy_config]
    )
    
    # Run configuration
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config]
    )
    
    # Execute backtest
    print("\nStarting backtest...")
    node = BacktestNode(configs=[run_config])
    
    try:
        results = node.run()
    except Exception as e:
        print(f"Backtest error: {e}")
        raise
    
    # Get results
    engine = node.get_engine(run_config.engine.trader_id)
    
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    
    # Account statistics
    account = engine.cache.account_for_venue(Venue(config.venue))
    if account:
        ending_balance = float(account.balance_total())
        pnl = ending_balance - config.initial_balance
        returns = (pnl / config.initial_balance) * 100
        
        print(f"\nStarting Balance: ${config.initial_balance:,.2f}")
        print(f"Ending Balance:   ${ending_balance:,.2f}")
        print(f"P&L:              ${pnl:,.2f}")
        print(f"Return:           {returns:.2f}%")
    
    # Order statistics
    orders = engine.cache.orders()
    print(f"\nTotal Orders:     {len(orders)}")
    
    # Position analysis
    positions = engine.cache.positions()
    print(f"Total Positions:  {len(positions)}")
    
    if positions:
        # Analyze by position tag (POS1, POS2, POS3)
        pos1_count = len([p for p in positions if "POS1" in str(getattr(p, 'tags', ''))])
        pos2_count = len([p for p in positions if "POS2" in str(getattr(p, 'tags', ''))])
        pos3_count = len([p for p in positions if "POS3" in str(getattr(p, 'tags', ''))])
        
        print(f"\nBy Layer:")
        print(f"  POS1 (Quick Win): {pos1_count}")
        print(f"  POS2 (Extended):  {pos2_count}")
        print(f"  POS3 (Runner):    {pos3_count}")
        
        # Win/Loss analysis
        winning = [p for p in positions if p.realized_pnl and float(p.realized_pnl) > 0]
        losing = [p for p in positions if p.realized_pnl and float(p.realized_pnl) < 0]
        
        if winning or losing:
            total_trades = len(winning) + len(losing)
            win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0
            
            print(f"\nTrade Statistics:")
            print(f"  Winning Trades: {len(winning)}")
            print(f"  Losing Trades:  {len(losing)}")
            print(f"  Win Rate:       {win_rate:.1f}%")
            
            if winning:
                total_wins = sum(float(p.realized_pnl) for p in winning)
                avg_win = total_wins / len(winning)
                print(f"  Total Wins:     ${total_wins:,.2f}")
                print(f"  Average Win:    ${avg_win:,.2f}")
            
            if losing:
                total_losses = sum(float(p.realized_pnl) for p in losing)
                avg_loss = total_losses / len(losing)
                print(f"  Total Losses:   ${total_losses:,.2f}")
                print(f"  Average Loss:   ${avg_loss:,.2f}")
            
            if winning and losing:
                profit_factor = abs(total_wins / total_losses) if total_losses != 0 else float('inf')
                print(f"  Profit Factor:  {profit_factor:.2f}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Save summary
    with open(results_dir / "summary.txt", "w") as f:
        f.write(f"MTF V2 Backtest Results\n")
        f.write(f"=" * 50 + "\n")
        f.write(f"Period: {config.backtest_start} to {config.backtest_end}\n")
        f.write(f"Starting Balance: ${config.initial_balance:,.2f}\n")
        if account:
            f.write(f"Ending Balance: ${ending_balance:,.2f}\n")
            f.write(f"P&L: ${pnl:,.2f}\n")
            f.write(f"Return: {returns:.2f}%\n")
        f.write(f"\nTotal Positions: {len(positions)}\n")
        if winning or losing:
            f.write(f"Win Rate: {win_rate:.1f}%\n")
    
    print(f"\nResults saved to: {results_dir}")
    print("=" * 80)
    
    return engine


if __name__ == "__main__":
    engine = run_backtest()
