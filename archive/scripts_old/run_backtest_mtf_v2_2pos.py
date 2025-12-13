"""
Backtest runner for V2 2-Position Strategy.

Compares 2-position split against 3-position V2.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model.identifiers import Venue

from config.mtf_v2_2pos_config import load_mtf_v2_2pos_config, print_mtf_v2_2pos_config
from strategies.ml_strategy_mtf_v2_2pos import MLSignalStrategyV2_2Pos, MLSignalStrategyV2_2PosConfig


def main():
    parser = argparse.ArgumentParser(description="V2 2-Position Backtest")
    parser.add_argument("--config", type=str, help="Path to env config file")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="2024-10-31", help="End date")
    parser.add_argument("--catalog", type=str, default="data/historical", help="Catalog path")
    args = parser.parse_args()
    
    # Load config
    config = load_mtf_v2_2pos_config(args.config)
    print_mtf_v2_2pos_config(config)
    
    # Build instrument ID and bar type
    instrument_id = f"{config.symbol.replace('/', '')}.{config.venue}"
    bar_type = f"{instrument_id}-{config.bar_spec}"
    
    print(f"\nBacktest Period: {args.start} to {args.end}")
    print(f"Catalog: {args.catalog}")
    print(f"Instrument: {instrument_id}")
    print(f"Bar Type: {bar_type}")
    
    # Strategy config
    strategy_config = MLSignalStrategyV2_2PosConfig(
        strategy_id="MLSignalStrategyV2_2Pos-001",
        instrument_id=f"{config.symbol}.{config.venue}",
        bar_type=f"{config.symbol}.{config.venue}-{config.bar_spec}",
        model_path=config.model_path,
        total_position_size=config.total_position_size,
        pos1_fraction=config.pos1_fraction,
        pos2_fraction=config.pos2_fraction,
        sl_atr_mult=config.sl_atr_mult,
        pos1_tp_atr_mult=config.pos1_tp_atr_mult,
        pos2_tp_atr_mult=config.pos2_tp_atr_mult,
        trailing_distance_atr_mult=config.trailing_distance_atr_mult,
        prediction_threshold=config.prediction_threshold,
        trade_start_hour=config.trade_start_hour,
        trade_end_hour=config.trade_end_hour,
        min_atr=config.min_atr,
        max_atr=config.max_atr,
    )
    
    # Data config
    data_config = BacktestDataConfig(
        catalog_path=args.catalog,
        data_cls_path="nautilus_trader.model.data:Bar",
        instrument_id=instrument_id,
        bar_spec=config.bar_spec,
        start_time=args.start,
        end_time=args.end,
    )
    
    # Venue config
    venue_config = BacktestVenueConfig(
        name=config.venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=["100000 USD"],
    )
    
    # Engine config
    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )
    
    # Run config
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config],
    )
    
    print("\n" + "=" * 60)
    print("STARTING V2 2-POSITION BACKTEST")
    print("=" * 60)
    
    # Run backtest
    node = BacktestNode(configs=[run_config])
    
    try:
        results = node.run()
        
        if results:
            result = results[0]
            
            print("\n" + "=" * 60)
            print("BACKTEST RESULTS")
            print("=" * 60)
            
            # Get fills
            fills = list(result.engine.cache.fills())
            print(f"Total Fills: {len(fills)}")
            
            # Calculate basic stats
            if fills:
                # Estimate trades (each trade has 2 entries + exits)
                num_trades = len([f for f in fills if "POS1" in str(f.client_order_id) and "ENTRY" not in str(f.client_order_id)]) // 2
                print(f"Estimated Trades: ~{num_trades}")
            
            # Account info
            try:
                account = result.engine.trader.generate_account_report()
                if account:
                    print(f"\nAccount Report:")
                    for key, value in account.items():
                        print(f"  {key}: {value}")
            except Exception as e:
                print(f"Could not generate account report: {e}")
                
            # Stats if available
            if hasattr(result, 'stats_pnls'):
                print(f"\nPnL Stats:")
                for key, value in result.stats_pnls.items():
                    print(f"  {key}: {value}")
                    
    except Exception as e:
        print(f"Backtest error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        node.dispose()
        
    print("\nBacktest complete.")


if __name__ == "__main__":
    main()
