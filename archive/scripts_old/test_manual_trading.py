#!/usr/bin/env python3
"""
Manual Trading Test Script for MTF Strategy
Allows you to manually send buy/sell/flatten orders to test IBKR connection.
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patches import apply_ib_connection_patch
apply_ib_connection_patch()

from nautilus_trader.adapters.interactive_brokers.common import IB, IB_VENUE
from nautilus_trader.adapters.interactive_brokers.config import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import TradingNodeConfig, LoggingConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, TraderId
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.objects import Quantity

from config.ibkr_config import get_ibkr_config


class ManualTrader:
    """Simple manual trading interface for testing."""
    
    def __init__(self):
        self.node = None
        self.instrument_id = None
        self.exec_client = None
        
    async def setup(self):
        """Initialize trading node and connect to IBKR."""
        print("="*80)
        print("MANUAL TRADING TEST - MTF Strategy")
        print("="*80)
        print("\nInitializing connection to IBKR...")
        
        # Get IBKR config
        ibkr_config = get_ibkr_config()
        
        # Create instrument provider config
        instrument_provider_config = InteractiveBrokersInstrumentProviderConfig()
        
        # Create data client config
        data_client_config = InteractiveBrokersDataClientConfig(
            instrument_provider=instrument_provider_config,
            ibg_host=ibkr_config.host,
            ibg_port=ibkr_config.port,
            ibg_client_id=ibkr_config.client_id,
        )
        
        # Create exec client config
        exec_client_config = InteractiveBrokersExecClientConfig(
            instrument_provider=instrument_provider_config,
            ibg_host=ibkr_config.host,
            ibg_port=ibkr_config.port,
            ibg_client_id=ibkr_config.client_id + 1,
            account_id=ibkr_config.account_id,
        )
        
        # Create trading node config
        node_config = TradingNodeConfig(
            trader_id=TraderId("MANUAL-TRADER-001"),
            logging=LoggingConfig(log_level="INFO"),
            data_clients={IB: data_client_config},
            exec_clients={IB: exec_client_config},
        )
        
        # Create and build node
        self.node = TradingNode(config=node_config)
        self.node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
        self.node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)
        self.node.build()
        
        # Start node (run in background)
        print("Starting trading node...")
        
        # Create a task to run the node in the background
        self.node_task = asyncio.create_task(self.node.run_async())
        
        # Wait for connection
        await asyncio.sleep(10)
        
        # Set instrument
        self.instrument_id = InstrumentId(Symbol("EUR/USD"), Venue("IDEALPRO"))
        
        print("\n✅ Connected to IBKR!")
        print(f"Account: {ibkr_config.account_id}")
        print(f"Instrument: {self.instrument_id}")
        print("\n" + "="*80)
        
    async def buy(self, quantity: int = 100000):
        """Place a market buy order."""
        print(f"\n📈 Placing BUY order for {quantity:,} {self.instrument_id}...")
        
        from nautilus_trader.model.identifiers import ClientOrderId
        
        order = MarketOrder(
            trader_id=self.node.trader_id,
            strategy_id=self.node.trader_id,
            instrument_id=self.instrument_id,
            client_order_id=ClientOrderId(f"MANUAL-{self.node.clock.timestamp_ns()}"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(quantity),
            time_in_force=TimeInForce.GTC,
            init_id=self.node.clock.generate_event_id(),
            ts_init=self.node.clock.timestamp_ns(),
        )
        
        self.node.trader.submit_order(order)
        print(f"✅ Order submitted: {order.client_order_id}")
        await asyncio.sleep(2)
        
    async def sell(self, quantity: int = 100000):
        """Place a market sell order."""
        print(f"\n📉 Placing SELL order for {quantity:,} {self.instrument_id}...")
        
        from nautilus_trader.model.identifiers import ClientOrderId
        
        order = MarketOrder(
            trader_id=self.node.trader_id,
            strategy_id=self.node.trader_id,
            instrument_id=self.instrument_id,
            client_order_id=ClientOrderId(f"MANUAL-{self.node.clock.timestamp_ns()}"),
            order_side=OrderSide.SELL,
            quantity=Quantity.from_int(quantity),
            time_in_force=TimeInForce.GTC,
            init_id=self.node.clock.generate_event_id(),
            ts_init=self.node.clock.timestamp_ns(),
        )
        
        self.node.trader.submit_order(order)
        print(f"✅ Order submitted: {order.client_order_id}")
        await asyncio.sleep(2)
        
    async def flatten(self):
        """Close all open positions."""
        print("\n🔄 Flattening all positions...")
        
        from nautilus_trader.model.identifiers import ClientOrderId
        
        positions = self.node.cache.positions_open(instrument_id=self.instrument_id)
        
        if not positions:
            print("ℹ️  No open positions to flatten")
            return
            
        for position in positions:
            print(f"Closing position: {position.id} (side={position.side}, qty={position.quantity})")
            
            # Determine opposite side
            close_side = OrderSide.SELL if position.side.name == "LONG" else OrderSide.BUY
            
            order = MarketOrder(
                trader_id=self.node.trader_id,
                strategy_id=self.node.trader_id,
                instrument_id=self.instrument_id,
                client_order_id=ClientOrderId(f"MANUAL-{self.node.clock.timestamp_ns()}"),
                order_side=close_side,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
                init_id=self.node.clock.generate_event_id(),
                ts_init=self.node.clock.timestamp_ns(),
            )
            
            self.node.trader.submit_order(order)
            print(f"✅ Close order submitted: {order.client_order_id}")
            
        await asyncio.sleep(2)
        
    def show_status(self):
        """Show current account and position status."""
        print("\n" + "="*80)
        print("CURRENT STATUS")
        print("="*80)
        
        # Account info
        account = self.node.cache.account_for_venue(IB_VENUE)
        if account:
            print(f"\n💰 Account: {account.id}")
            for balance in account.balances():
                print(f"   {balance.currency}: {balance.total} (free: {balance.free})")
        
        # Positions
        positions = self.node.cache.positions_open(instrument_id=self.instrument_id)
        print(f"\n📊 Open Positions: {len(positions)}")
        for position in positions:
            pnl = position.unrealized_pnl(position.last)
            print(f"   {position.id}: {position.side} {position.quantity} @ {position.avg_px_open}")
            print(f"      Unrealized P&L: {pnl}")
        
        # Orders
        orders = self.node.cache.orders_open(instrument_id=self.instrument_id)
        print(f"\n📝 Open Orders: {len(orders)}")
        for order in orders:
            print(f"   {order.client_order_id}: {order.side} {order.quantity} {order.order_type}")
        
        print("="*80)
        
    async def interactive_mode(self):
        """Run interactive command loop."""
        print("\n" + "="*80)
        print("INTERACTIVE MODE")
        print("="*80)
        print("\nCommands:")
        print("  buy [qty]   - Place market buy order (default: 100,000)")
        print("  sell [qty]  - Place market sell order (default: 100,000)")
        print("  flatten     - Close all positions")
        print("  status      - Show account and position status")
        print("  quit        - Exit")
        print("\n" + "="*80)
        
        while True:
            try:
                cmd = input("\n> ").strip().lower()
                
                if not cmd:
                    continue
                    
                parts = cmd.split()
                command = parts[0]
                
                if command == "quit" or command == "exit":
                    print("\nExiting...")
                    break
                    
                elif command == "buy":
                    qty = int(parts[1]) if len(parts) > 1 else 100000
                    await self.buy(qty)
                    
                elif command == "sell":
                    qty = int(parts[1]) if len(parts) > 1 else 100000
                    await self.sell(qty)
                    
                elif command == "flatten":
                    await self.flatten()
                    
                elif command == "status":
                    self.show_status()
                    
                else:
                    print(f"Unknown command: {command}")
                    
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
                
    async def cleanup(self):
        """Stop node and cleanup."""
        if self.node and self.node.is_running():
            print("\nStopping trading node...")
            await self.node.stop_async()
            
        # Cancel the background task
        if hasattr(self, 'node_task') and not self.node_task.done():
            self.node_task.cancel()
            try:
                await self.node_task
            except asyncio.CancelledError:
                pass
                
        if self.node:
            self.node.dispose()


async def main():
    """Main entry point."""
    trader = ManualTrader()
    
    try:
        await trader.setup()
        await trader.interactive_mode()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await trader.cleanup()
        

if __name__ == "__main__":
    # Fix for Windows event loop
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
