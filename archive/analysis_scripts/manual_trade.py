"""
Manual trading utility for MTF strategy.
Allows manual position entry with default TP/SL from command line.
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.adapters.interactive_brokers.config import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    IBMarketDataTypeEnum,
)
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.core.uuid import UUID4

from config.ibkr_config import get_ibkr_config
from config.mtf_config import load_mtf_config


async def get_current_price(node, instrument_id):
    """Get current market price for instrument."""
    # Subscribe to quotes
    data_client = node.data_engine.default_client
    
    # Request quote
    quote = node.cache.quote(instrument_id)
    if quote:
        return (quote.bid_price.as_double() + quote.ask_price.as_double()) / 2
    
    return None


async def place_manual_order(side: str, size: int = None, tp_atr: float = None, sl_atr: float = None):
    """
    Place a manual market order with TP/SL.
    
    Args:
        side: 'BUY' or 'SELL'
        size: Position size (default from config)
        tp_atr: Take profit in ATR multiples (default from config)
        sl_atr: Stop loss in ATR multiples (default from config)
    """
    # Load configs
    ibkr_config = get_ibkr_config()
    mtf_config = load_mtf_config()
    
    # Use defaults from config if not specified
    size = size or mtf_config.position_size
    tp_atr = tp_atr or mtf_config.tp_atr_mult
    sl_atr = sl_atr or mtf_config.sl_atr_mult
    
    print(f"\nManual Trade Request:")
    print(f"  Side: {side}")
    print(f"  Size: {size:,}")
    print(f"  TP: {tp_atr}x ATR")
    print(f"  SL: {sl_atr}x ATR")
    print(f"\nConnecting to IB Gateway...")
    
    # Create minimal trading node config
    config = TradingNodeConfig(
        trader_id="MANUAL-TRADER-001",
        data_clients={
            "INTERACTIVE_BROKERS": InteractiveBrokersDataClientConfig(
                ibg_host=ibkr_config.host,
                ibg_port=ibkr_config.port,
                ibg_client_id=ibkr_config.client_id + 100,  # Different client ID
                market_data_type=IBMarketDataTypeEnum.REALTIME,
            )
        },
        exec_clients={
            "INTERACTIVE_BROKERS": InteractiveBrokersExecClientConfig(
                ibg_host=ibkr_config.host,
                ibg_port=ibkr_config.port,
                ibg_client_id=ibkr_config.client_id + 101,  # Different client ID
                account_id=ibkr_config.account_id,
            )
        },
    )
    
    # Create and start node
    node = TradingNode(config=config)
    
    try:
        await node.start_async()
        print("Connected to IB Gateway")
        
        # Get instrument
        instrument_id = InstrumentId.from_str("EUR/USD.IDEALPRO")
        
        # Wait for instrument to be available
        print("Loading instrument data...")
        await asyncio.sleep(2)
        
        instrument = node.cache.instrument(instrument_id)
        if not instrument:
            print(f"ERROR: Could not load instrument {instrument_id}")
            return
        
        print(f"Instrument loaded: {instrument.id}")
        
        # Get current price (for reference)
        print("Getting current market price...")
        await asyncio.sleep(1)
        
        # Create market order
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        
        order = MarketOrder(
            trader_id=node.trader_id,
            strategy_id=node.trader_id,  # Use trader_id as strategy_id
            instrument_id=instrument_id,
            client_order_id=node.cache.client_order_id(),
            order_side=order_side,
            quantity=instrument.make_qty(size),
            time_in_force=TimeInForce.GTC,
            init_id=UUID4(),
            ts_init=node.clock.timestamp_ns(),
        )
        
        print(f"\nSubmitting {side} order for {size:,} units...")
        
        # Submit order
        node.trader.submit_order(order)
        
        # Wait for fill
        print("Waiting for order fill...")
        await asyncio.sleep(3)
        
        # Check if filled
        filled_order = node.cache.order(order.client_order_id)
        if filled_order and filled_order.is_closed:
            print(f"✓ Order filled!")
            print(f"  Fill price: {filled_order.avg_px}")
            print(f"\nNOTE: TP/SL orders must be placed separately.")
            print(f"      This is a simple market order only.")
            print(f"      Your live strategy will manage the position.")
        else:
            print(f"⚠ Order status: {filled_order.status if filled_order else 'Unknown'}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nShutting down...")
        await node.stop_async()
        await node.dispose_async()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Manual trading utility for MTF strategy")
    parser.add_argument("side", choices=["BUY", "SELL", "buy", "sell"], 
                       help="Order side (BUY or SELL)")
    parser.add_argument("--size", type=int, 
                       help="Position size (default: from config)")
    parser.add_argument("--tp", type=float, 
                       help="Take profit in ATR multiples (default: from config)")
    parser.add_argument("--sl", type=float, 
                       help="Stop loss in ATR multiples (default: from config)")
    
    args = parser.parse_args()
    
    # Run async function
    asyncio.run(place_manual_order(
        side=args.side.upper(),
        size=args.size,
        tp_atr=args.tp,
        sl_atr=args.sl
    ))


if __name__ == "__main__":
    main()
