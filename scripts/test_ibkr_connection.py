#!/usr/bin/env python3
"""
Test IBKR connection and verify setup before live trading.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_connection():
    """Test IBKR connection."""
    print("="*80)
    print("IBKR CONNECTION TEST")
    print("="*80)
    
    # Check environment variables
    print("\n1. Checking environment variables...")
    required_vars = ['IB_HOST', 'IB_PORT', 'IB_CLIENT_ID', 'IB_ACCOUNT']
    missing = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var} = {value}")
        else:
            print(f"   ❌ {var} = NOT SET")
            missing.append(var)
    
    if missing:
        print(f"\n❌ Missing environment variables: {', '.join(missing)}")
        print("   Please set them in .env file")
        return False
    
    # Try to connect to IBKR
    print("\n2. Testing IBKR connection...")
    try:
        from ib_insync import IB, util
        
        ib = IB()
        host = os.getenv('IB_HOST', '127.0.0.1')
        port = int(os.getenv('IB_PORT', '7497'))
        client_id = int(os.getenv('IB_CLIENT_ID', '1'))
        
        print(f"   Connecting to {host}:{port} (client_id={client_id})...")
        ib.connect(host, port, clientId=client_id, timeout=10)
        
        print(f"   ✅ Connected successfully!")
        
        # Get account info
        account = os.getenv('IB_ACCOUNT')
        if account:
            print(f"\n3. Checking account: {account}")
            account_values = ib.accountValues(account)
            
            # Find key values
            for av in account_values:
                if av.tag == 'NetLiquidation':
                    print(f"   ✅ Net Liquidation: ${float(av.value):,.2f}")
                elif av.tag == 'AvailableFunds':
                    print(f"   ✅ Available Funds: ${float(av.value):,.2f}")
                elif av.tag == 'BuyingPower':
                    print(f"   ✅ Buying Power: ${float(av.value):,.2f}")
        
        # Test EUR/USD contract
        print("\n4. Testing EUR/USD contract...")
        from ib_insync import Forex
        
        contract = Forex('EURUSD')
        ib.qualifyContracts(contract)
        print(f"   ✅ EUR/USD contract found: {contract}")
        
        # Test market data
        print("\n5. Testing market data...")
        ticker = ib.reqMktData(contract)
        ib.sleep(2)  # Wait for data
        
        if ticker.last:
            print(f"   ✅ Last price: {ticker.last}")
            print(f"   ✅ Bid: {ticker.bid}, Ask: {ticker.ask}")
        else:
            print(f"   ⚠️  No market data received (may need subscription)")
        
        # Disconnect
        ib.disconnect()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\nYour IBKR connection is ready for trading!")
        print("\nNext steps:")
        print("1. Start paper trading to verify strategy")
        print("2. Monitor for 2+ weeks")
        print("3. Review DEPLOYMENT_GUIDE.md for full checklist")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Is TWS or IB Gateway running?")
        print("2. Is API access enabled in TWS settings?")
        print("3. Is the port correct (7497 for paper, 7496 for live)?")
        print("4. Is your IP address in the trusted list?")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
