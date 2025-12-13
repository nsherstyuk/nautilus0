#!/usr/bin/env python3
"""
Run backtest for a specific date period using current .env.mtf config.
Usage: python run_backtest_period.py 2024-01-01 2024-12-31
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import BacktestEngineConfig, BacktestRunConfig, BacktestDataConfig, BacktestVenueConfig, LoggingConfig
from nautilus_trader.model.identifiers import Venue
from strategies.ml_strategy_config import MLSignalStrategyConfig
from config.mtf_config import load_mtf_config, print_mtf_config

def run_backtest(start_date: str, end_date: str):
    """Run MTF ML strategy backtest for specific period using .env.mtf configuration."""
    
    # Load configuration from .env.mtf (same as live trading!)
    print("="*80)
    print("MTF ML STRATEGY BACKTEST - CUSTOM PERIOD")
    print("="*80)
    print(f"\n🗓️  Testing Period: {start_date} to {end_date}")
    print("\nLoading configuration from .env.mtf (same as live trading)...\n")
    
    mtf_config = load_mtf_config()
    print_mtf_config(mtf_config)
    
    # Use config values
    instrument_id = f"{mtf_config.symbol}.{mtf_config.venue}"
    
    print("\n" + "="*80)
    print("BACKTEST PARAMETERS")
    print("="*80)
    print(f"Instrument: {instrument_id}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Model: {mtf_config.model_path}")
    print(f"Timeframe: {mtf_config.bar_spec}")
    print(f"Confidence Threshold: {mtf_config.prediction_threshold}")
    print(f"Position Size: ${mtf_config.position_size:,}")
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
    print("\n🚀 Starting backtest...\n")
    node = BacktestNode()
    node.run(run_config)
    
    # Get results
    engine = node.get_engine(run_config.engine.trader_id)
    
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    
    # Account statistics
    account = engine.cache.account_for_venue(Venue(mtf_config.venue))
    if account:
        starting_balance = 100000.0
        ending_balance = float(account.balance_total())
        pnl = ending_balance - starting_balance
        return_pct = (pnl / starting_balance) * 100
        
        print(f"\n💰 ACCOUNT:")
        print(f"   Starting Balance: ${starting_balance:,.2f}")
        print(f"   Ending Balance: ${ending_balance:,.2f}")
        print(f"   P&L: ${pnl:,.2f}")
        print(f"   Return: {return_pct:.2f}%")
    
    # Trade statistics
    positions = list(engine.cache.positions())
    orders = list(engine.cache.orders())
    
    print(f"\n📊 TRADING:")
    print(f"   Total Orders: {len(orders)}")
    print(f"   Total Positions: {len(positions)}")
    
    # Position analysis
    if positions:
        long_positions = [p for p in positions if str(p.entry) == "BUY"]
        short_positions = [p for p in positions if str(p.entry) == "SELL"]
        
        print(f"   Long Positions: {len(long_positions)}")
        print(f"   Short Positions: {len(short_positions)}")
        
        # P&L analysis
        winning = [p for p in positions if p.realized_pnl and float(p.realized_pnl) > 0]
        losing = [p for p in positions if p.realized_pnl and float(p.realized_pnl) < 0]
        
        if winning or losing:
            total_trades = len(winning) + len(losing)
            win_rate = (len(winning) / total_trades * 100) if total_trades > 0 else 0
            
            print(f"\n📈 PERFORMANCE:")
            print(f"   Winning Trades: {len(winning)}")
            print(f"   Losing Trades: {len(losing)}")
            print(f"   Win Rate: {win_rate:.1f}%")
            
            if winning:
                avg_win = sum(float(p.realized_pnl) for p in winning) / len(winning)
                total_wins = sum(float(p.realized_pnl) for p in winning)
                print(f"   Average Win: ${avg_win:,.2f}")
                print(f"   Total Wins: ${total_wins:,.2f}")
            
            if losing:
                avg_loss = sum(float(p.realized_pnl) for p in losing) / len(losing)
                total_losses = sum(float(p.realized_pnl) for p in losing)
                print(f"   Average Loss: ${avg_loss:,.2f}")
                print(f"   Total Losses: ${total_losses:,.2f}")
            
            if winning and losing:
                rr_ratio = abs(avg_win / avg_loss)
                print(f"   Reward/Risk Ratio: {rr_ratio:.2f}")
    
    print("\n" + "="*80)
    print(f"✅ BACKTEST COMPLETE: {start_date} to {end_date}")
    print("="*80)
    
    return engine

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python run_backtest_period.py <start_date> <end_date>")
        print("\nExamples:")
        print("  python run_backtest_period.py 2024-01-01 2024-12-31  # Test 2024")
        print("  python run_backtest_period.py 2025-01-01 2025-06-30  # Test H1 2025")
        print("  python run_backtest_period.py 2023-01-01 2023-12-31  # Test 2023")
        print("\nThis will use your current .env.mtf configuration (same as live trading)")
        sys.exit(1)
    
    start_date = sys.argv[1]
    end_date = sys.argv[2]
    
    engine = run_backtest(start_date, end_date)
