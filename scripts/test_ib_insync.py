"""
Test IBKR connection using ib_insync library.

This is based on the old working code from olderCode/live_ibkr_trader.py
which successfully connected to IBKR using ib_insync instead of ibapi.

ib_insync is a higher-level wrapper that handles connection reliability better.
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

try:
    from dotenv import load_dotenv
    from ib_insync import IB, Forex, util
except ImportError as e:
    print(f"ERROR: Missing required package")
    print(f"  {e}")
    print("\nInstall with:")
    print("  pip install ib-insync")
    sys.exit(1)


def test_ib_insync_connection():
    """Test connection using ib_insync library (like the old working code)."""
    
    # Load environment
    load_dotenv()
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "7497"))
    client_id = int(os.getenv("IB_CLIENT_ID", "1"))
    
    print("=" * 70)
    print("IB_INSYNC CONNECTION TEST")
    print("=" * 70)
    print(f"Library:   ib_insync (used by old working code)")
    print(f"Host:      {host}")
    print(f"Port:      {port}")
    print(f"Client ID: {client_id}")
    print("=" * 70)
    print()
    
    # Create IB instance
    print("[1/5] Creating IB instance...")
    ib = IB()
    print("      ✓ IB object created")
    
    # Connect
    print(f"\n[2/5] Connecting to TWS at {host}:{port}...")
    try:
        ib.connect(host, port, clientId=client_id, timeout=15)
        print("      ✓ Connection established!")
    except Exception as e:
        print(f"      ✗ Connection failed: {e}")
        print("\nPossible causes:")
        print("  1. TWS/Gateway not running")
        print("  2. API not enabled in TWS settings")
        print("  3. Wrong port or client ID conflict")
        return 1
    
    # Check connection status
    print("\n[3/5] Checking connection status...")
    if ib.isConnected():
        print("      ✓ Connected to TWS")
        print(f"      ✓ Client ID: {ib.client.clientId}")
    else:
        print("      ✗ Not connected")
        return 1
    
    # Get managed accounts
    print("\n[4/5] Retrieving account information...")
    accounts = ib.managedAccounts()
    if accounts:
        print(f"      ✓ Managed accounts: {', '.join(accounts)}")
    else:
        print("      ⚠ No managed accounts returned (might be normal)")
    
    # Test contract qualification (like old code does)
    print("\n[5/5] Testing contract qualification (EUR/USD)...")
    try:
        contract = Forex('EURUSD')
        qualified = ib.qualifyContracts(contract)
        if qualified:
            print(f"      ✓ Contract qualified: {qualified[0].symbol} {qualified[0].currency}")
            print(f"      ✓ Exchange: {qualified[0].exchange}")
        else:
            print("      ⚠ Contract qualification returned empty")
    except Exception as e:
        print(f"      ✗ Contract qualification failed: {e}")
    
    # Disconnect
    print("\n[CLEANUP] Disconnecting...")
    ib.disconnect()
    print("      ✓ Disconnected")
    
    # Success
    print("\n" + "=" * 70)
    print("✓ SUCCESS - ib_insync connection works!")
    print("=" * 70)
    print("\nYour old code used ib_insync, which is working fine.")
    print("The problem is that NautilusTrader uses the lower-level ibapi library,")
    print("which has different connection behavior and reliability issues.")
    print("\nOptions:")
    print("  1. Continue using ib_insync for your trading (more reliable)")
    print("  2. Debug NautilusTrader's ibapi adapter issues")
    print("  3. Wait for NautilusTrader to fix the adapter bug")
    print()
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = test_ib_insync_connection()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit_code = 130
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    
    sys.exit(exit_code)
