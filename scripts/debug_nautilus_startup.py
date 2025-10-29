"""Debug NautilusTrader startup sequence to identify connection cancellation."""
import asyncio
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from nautilus_trader.adapters.interactive_brokers.common import IB
from nautilus_trader.adapters.interactive_brokers.config import (
    IBMarketDataTypeEnum,
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
)
from nautilus_trader.config import LoggingConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode


async def main():
    load_dotenv()
    
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "7497"))
    client_id = int(os.getenv("IB_CLIENT_ID", "1"))
    
    print("=" * 70)
    print("NautilusTrader Startup Debug")
    print("=" * 70)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Client ID: {client_id}")
    print("=" * 70)
    
    # Minimal config - just one data client
    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        load_ids=frozenset({"EUR/USD.IDEALPRO"}),
    )
    
    data_client_config = InteractiveBrokersDataClientConfig(
        instrument_provider=instrument_provider_config,
        ibg_host=host,
        ibg_port=port,
        ibg_client_id=client_id,
        market_data_type=IBMarketDataTypeEnum.DELAYED_FROZEN,
        use_regular_trading_hours=True,
    )
    
    trading_node_config = TradingNodeConfig(
        trader_id="DEBUG-TRADER",
        logging=LoggingConfig(log_level="DEBUG"),
        data_clients={IB: data_client_config},
        timeout_connection=90.0,
    )
    
    print("\n[1/5] Creating TradingNode...")
    node = TradingNode(config=trading_node_config)
    print("      ✓ Node created")
    
    print("\n[2/5] Adding data client factory...")
    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    print("      ✓ Factory added")
    
    print("\n[3/5] Building node (this starts clients)...")
    node.build()
    print("      ✓ Node built")
    print("      (Clients should start connecting now)")
    
    print("\n[4/5] Waiting 5 seconds for connection to establish...")
    await asyncio.sleep(5)
    
    print("\n[5/5] Starting node.run()...")
    print("      (Running for 10 seconds to observe behavior)")
    
    # Run in background
    run_task = asyncio.create_task(asyncio.to_thread(node.run))
    
    try:
        await asyncio.sleep(10)
        print("\n[RESULT] Node ran for 10 seconds")
        print("         Check logs above for connection status")
    finally:
        print("\n[CLEANUP] Stopping node...")
        node.stop()
        node.dispose()
        run_task.cancel()
        try:
            await run_task
        except:
            pass
    
    print("\n" + "=" * 70)
    print("Debug complete - check the logs above for:")
    print("  1. Did the client connect successfully?")
    print("  2. Were there any 'Connection cancelled' messages?")
    print("  3. Any errors about 'Not connected' (code 504)?")
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    sys.exit(0)
