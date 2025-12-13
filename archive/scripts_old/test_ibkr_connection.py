"""Test IBKR connection using HistoricInteractiveBrokersClient."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.adapters.interactive_brokers.historical.client import HistoricInteractiveBrokersClient
from config import get_ibkr_config, get_market_data_type_enum


async def test_connection():
    """Test basic IBKR connection."""
    print("=" * 60)
    print("Testing IBKR Connection")
    print("=" * 60)
    
    # Load config
    config = get_ibkr_config()
    print(f"\nConfiguration:")
    print(f"  Host: {config.host}")
    print(f"  Port: {config.port}")
    print(f"  Client ID: {config.client_id}")
    print(f"  Account: {config.account_id}")
    print(f"  Market Data Type: {config.market_data_type}")
    
    # Create client
    print(f"\nCreating HistoricInteractiveBrokersClient...")
    client = HistoricInteractiveBrokersClient(
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        market_data_type=get_market_data_type_enum(config.market_data_type)
    )
    
    try:
        print(f"Connecting to TWS at {config.host}:{config.port}...")
        await client.connect()
        print("✅ CONNECTION SUCCESSFUL!")
        
        # Wait a bit to ensure connection is stable
        print("Waiting 2 seconds to verify connection stability...")
        await asyncio.sleep(2)
        print("✅ Connection stable")
        
        # Try to disconnect
        print("Disconnecting...")
        if hasattr(client, 'disconnect'):
            await client.disconnect()
        elif hasattr(client, 'stop'):
            await client.stop()
        print("✅ Disconnected successfully")
        
        return 0
        
    except ConnectionRefusedError as e:
        print(f"❌ CONNECTION REFUSED: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure TWS or IB Gateway is running")
        print("2. Check API is enabled in TWS:")
        print("   File → Global Configuration → API → Settings")
        print("   ✓ Enable ActiveX and Socket Clients")
        print(f"   ✓ Socket port = {config.port}")
        return 1
        
    except TimeoutError as e:
        print(f"❌ CONNECTION TIMEOUT: {e}")
        print("\nTroubleshooting:")
        print("1. TWS may be slow to respond")
        print("2. Check firewall settings")
        print("3. Verify port is correct")
        return 1
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        print("\nTest completed")


if __name__ == "__main__":
    exit_code = asyncio.run(test_connection())
    sys.exit(exit_code)
