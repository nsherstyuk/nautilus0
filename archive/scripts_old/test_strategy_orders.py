#!/usr/bin/env python3
"""
Test MTF Strategy Order Execution
This script runs the ACTUAL MTF strategy with manual signals to test order flow.
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

from nautilus_trader.adapters.interactive_brokers.common import IB
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import TradingNodeConfig, LoggingConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId

from config.mtf_config import load_mtf_config, validate_mtf_config
from config.ibkr_config import get_ibkr_config
from live.live_config_ibkr import get_ibkr_config as get_ibkr_client_config


def create_test_node_config(mtf_config, ibkr_config):
    """Create trading node config for testing - SAME AS LIVE!"""
    from nautilus_trader.config import ImportableStrategyConfig
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    
    # Create instrument ID
    instrument_id = InstrumentId(
        symbol=Symbol(mtf_config.symbol.replace("/", "")),
        venue=Venue(mtf_config.venue)
    )
    
    # Strategy config - EXACT SAME as live trading!
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf:MLSignalStrategy",
        config_path="strategies.ml_strategy_mtf:MLSignalStrategyConfig",
        config={
            "instrument_id": str(instrument_id),
            "bar_type": f"{instrument_id}-{mtf_config.bar_spec}",
            "model_path": mtf_config.model_path,
            "prediction_threshold": mtf_config.prediction_threshold,
            "position_size": mtf_config.position_size,
            # Risk Management
            "sl_atr_mult": mtf_config.sl_atr_mult,
            "tp_atr_mult": mtf_config.tp_atr_mult,
            # Trailing Stop
            "trailing_stop_enabled": mtf_config.trailing_stop_enabled,
            "trailing_activation_atr_mult": mtf_config.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": mtf_config.trailing_distance_atr_mult,
            # Partial Close
            "partial_close_enabled": mtf_config.partial_close_enabled,
            "partial_close_fraction": mtf_config.partial_close_fraction,
            "partial_close_move_sl_to_be": mtf_config.partial_close_move_sl_to_be,
            # Trading Session
            "session_start": mtf_config.session_start,
            "session_end": mtf_config.session_end,
            "excluded_hours": mtf_config.excluded_hours if mtf_config.excluded_hours else [],
            "excluded_hours_by_weekday": mtf_config.excluded_hours_by_weekday if mtf_config.excluded_hours_by_weekday else {},
            # Feature warmup
            "feature_warmup_bars": mtf_config.feature_warmup_bars,
            # Order ID tag
            "order_id_tag": mtf_config.order_id_tag,
        },
    )
    
    # Get IBKR client configs
    ibkr_data_config, ibkr_exec_config = get_ibkr_client_config()
    
    # Trading node config
    trading_node_config = TradingNodeConfig(
        trader_id=TraderId(mtf_config.trader_id),
        logging=LoggingConfig(log_level="INFO"),
        data_clients={IB: ibkr_data_config},
        exec_clients={IB: ibkr_exec_config},
        strategies=[strategy_config],
    )
    
    return trading_node_config


async def main():
    """Run MTF strategy in test mode."""
    print("="*80)
    print("MTF STRATEGY ORDER TEST")
    print("="*80)
    print("\nThis runs your ACTUAL MTF strategy code!")
    print("Orders will be submitted using the SAME code path as live trading.\n")
    
    # Load configs
    print("Loading configuration...")
    mtf_config = load_mtf_config()
    if not validate_mtf_config(mtf_config):
        print("❌ Configuration validation failed!")
        return 1
    
    ibkr_config = get_ibkr_config()
    
    print(f"✅ Config loaded: {mtf_config.symbol} on {mtf_config.venue}")
    print(f"   Account: {ibkr_config.account_id}")
    print(f"   Model: {mtf_config.model_path}")
    print(f"   Position Size: ${mtf_config.position_size:,}")
    
    # Create trading node with ACTUAL strategy
    print("\nBuilding trading node with MTF strategy...")
    node_config = create_test_node_config(mtf_config, ibkr_config)
    node = TradingNode(config=node_config)
    
    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)
    
    node.build()
    
    print("✅ Trading node built")
    print("\nStarting node and connecting to IBKR...")
    print("(This will take ~10 seconds)")
    
    # Run node in background
    node_task = asyncio.create_task(node.run_async())
    
    # Wait for connection
    await asyncio.sleep(15)
    
    if not node.is_running():
        print("❌ Node failed to start!")
        return 1
    
    print("\n" + "="*80)
    print("✅ MTF STRATEGY IS RUNNING!")
    print("="*80)
    
    # Get the strategy instance
    strategies = list(node.trader.strategies())
    if not strategies:
        print("❌ No strategy found!")
        await node.stop_async()
        return 1
    
    strategy = strategies[0]
    print(f"\nStrategy: {strategy.id}")
    print(f"Strategy Type: {type(strategy).__name__}")
    
    # Show current status
    print("\n" + "="*80)
    print("CURRENT STATUS")
    print("="*80)
    
    account = node.cache.account_for_venue(IB)
    if account:
        print(f"\n💰 Account: {account.id}")
        for balance in account.balances():
            print(f"   {balance.currency}: ${balance.total:,.2f} (free: ${balance.free:,.2f})")
    
    positions = list(node.cache.positions_open())
    print(f"\n📊 Open Positions: {len(positions)}")
    for pos in positions:
        print(f"   {pos.id}: {pos.side} {pos.quantity} @ {pos.avg_px_open}")
    
    orders = list(node.cache.orders_open())
    print(f"\n📝 Open Orders: {len(orders)}")
    for order in orders:
        print(f"   {order.client_order_id}: {order.side} {order.quantity}")
    
    print("\n" + "="*80)
    print("TESTING INSTRUCTIONS")
    print("="*80)
    print("""
The MTF strategy is now LIVE and monitoring the market!

🔍 What's happening:
   - Strategy is subscribed to EUR/USD 15-minute bars
   - ML model is loaded and ready
   - Every 15 minutes, a new bar arrives
   - Strategy calculates MTF features
   - Gets ML prediction
   - Checks weekday-specific hour exclusions
   - If conditions are met, submits orders to IBKR

📊 To test order execution:
   1. Wait for a new 15-minute bar (check logs)
   2. Strategy will process the bar
   3. If ML signals a trade, order will be submitted
   4. Check TWS to see the order appear
   5. Monitor logs for order fills

⏰ Current time exclusions apply!
   - Only trades during 02:00-16:00 UTC
   - Weekday-specific hours are excluded
   - Check .env.mtf for your exclusions

📝 Monitor logs:
   - Watch console for strategy decisions
   - Check TWS Orders tab for submitted orders
   - Check TWS Trades tab for fills

Press Ctrl+C to stop...
""")
    
    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(10)
            
            # Show any new positions
            new_positions = list(node.cache.positions_open())
            if len(new_positions) != len(positions):
                print(f"\n🔔 Position update: {len(new_positions)} open positions")
                positions = new_positions
                for pos in positions:
                    pnl = pos.unrealized_pnl(pos.last)
                    print(f"   {pos.id}: {pos.side} {pos.quantity} @ {pos.avg_px_open} (P&L: ${pnl:.2f})")
            
            # Show any new orders
            new_orders = list(node.cache.orders_open())
            if len(new_orders) != len(orders):
                print(f"\n🔔 Order update: {len(new_orders)} open orders")
                orders = new_orders
                for order in orders:
                    print(f"   {order.client_order_id}: {order.side} {order.quantity} {order.status}")
                    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping strategy...")
    
    # Cleanup
    print("Stopping trading node...")
    if node.is_running():
        await node.stop_async()
    
    if not node_task.done():
        node_task.cancel()
        try:
            await node_task
        except asyncio.CancelledError:
            pass
    
    node.dispose()
    print("✅ Stopped cleanly")
    
    return 0


if __name__ == "__main__":
    # Fix for Windows event loop
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
