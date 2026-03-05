"""
Flatten all open positions utility.
Closes all open positions immediately with market orders.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.adapters.interactive_brokers.config import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    IBMarketDataTypeEnum,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce, PositionSide
from nautilus_trader.core.uuid import UUID4
import threading
import time

from config.ibkr_config import get_ibkr_config


def flatten_all_positions():
    """Close all open positions with market orders."""
    # Load config
    ibkr_config = get_ibkr_config()
    
    print("\nFlatten Position Utility")
    print("=" * 50)
    print(f"Connecting to IB Gateway at {ibkr_config.host}:{ibkr_config.port}...")
    
    # Create minimal trading node config
    config = TradingNodeConfig(
        trader_id="FLATTEN-TRADER-001",
        data_clients={
            "INTERACTIVE_BROKERS": InteractiveBrokersDataClientConfig(
                ibg_host=ibkr_config.host,
                ibg_port=ibkr_config.port,
                ibg_client_id=ibkr_config.client_id + 200,  # Different client ID
                market_data_type=IBMarketDataTypeEnum.REALTIME,
            )
        },
        exec_clients={
            "INTERACTIVE_BROKERS": InteractiveBrokersExecClientConfig(
                ibg_host=ibkr_config.host,
                ibg_port=ibkr_config.port,
                ibg_client_id=ibkr_config.client_id + 201,  # Different client ID
                account_id=ibkr_config.account_id,
            )
        },
    )
    
    # Create and start node
    node = TradingNode(config=config)
    node.add_data_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveExecClientFactory)
    node.build()
    
    try:
        # Start node in background thread
        node_thread = threading.Thread(target=node.run, daemon=True)
        node_thread.start()
        print("✓ Connected to IB Gateway")
        
        # Wait for account and positions to load
        print("\nLoading account and positions...")
        time.sleep(10)  # Give more time for positions to load from IB
        
        # Get all open positions
        open_positions = node.cache.positions_open()
        all_positions = node.cache.positions()
        
        print(f"\nCache status:")
        print(f"  - Open positions: {len(open_positions)}")
        print(f"  - All positions: {len(all_positions)}")
        print(f"  - Instruments: {len(node.cache.instruments())}")
        print(f"  - Accounts: {len(node.cache.accounts())}")
        
        if not open_positions:
            print("\n✓ No open positions to flatten")
            if all_positions:
                print("  (Found closed positions in cache)")
            return
        
        print(f"\nFound {len(open_positions)} open position(s):")
        
        for position in open_positions:
            print(f"\n  Position: {position.instrument_id}")
            print(f"    Side: {position.side}")
            print(f"    Quantity: {position.quantity}")
            print(f"    Entry: {position.avg_px_open}")
            print(f"    Unrealized P&L: ${position.unrealized_pnl(position.last_px):.2f}")
            
            # Determine closing side
            close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            
            # Get instrument
            instrument = node.cache.instrument(position.instrument_id)
            if not instrument:
                print(f"    ERROR: Could not load instrument")
                continue
            
            # Create market order to close
            order = MarketOrder(
                trader_id=node.trader_id,
                strategy_id=node.trader_id,
                instrument_id=position.instrument_id,
                client_order_id=node.cache.client_order_id(),
                order_side=close_side,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
                reduce_only=True,  # Important: only close existing position
                init_id=UUID4(),
                ts_init=node.clock.timestamp_ns(),
            )
            
            print(f"    Submitting {close_side.name} order to close...")
            
            # Submit order
            node.trader.submit_order(order)
        
        # Wait for orders to fill
        print("\nWaiting for orders to fill...")
        time.sleep(3)
        
        # Check final positions
        remaining_positions = node.cache.positions_open()
        
        if not remaining_positions:
            print("\n✓ All positions successfully closed!")
        else:
            print(f"\n⚠ {len(remaining_positions)} position(s) still open")
            for pos in remaining_positions:
                print(f"    {pos.instrument_id}: {pos.side} {pos.quantity}")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nShutting down...")
        time.sleep(1)  # Allow pending tasks to complete
        node.stop()
        time.sleep(1)
        node.dispose()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Flatten all open positions")
    parser.add_argument("--confirm", action="store_true",
                       help="Skip confirmation prompt")
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("\n⚠ WARNING: This will close ALL open positions immediately!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return
    
    # Run function
    flatten_all_positions()


if __name__ == "__main__":
    main()
