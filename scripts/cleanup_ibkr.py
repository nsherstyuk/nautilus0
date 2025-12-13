#!/usr/bin/env python3
"""
Script to cancel ALL open orders globally and close all positions on IBKR.
Uses reqGlobalCancel to cancel all orders regardless of client ID.
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from ib_insync import IB, Forex, MarketOrder, util


def cleanup_ibkr():
    """Cancel all orders globally and close all positions."""
    
    ib = IB()
    
    # Connection settings from environment
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_TRADING_PORT", os.getenv("IB_PORT", "4002")))
    client_id = 99  # Use a different client ID to avoid conflicts
    
    print(f"Connecting to IBKR at {host}:{port} with client_id={client_id}...")
    
    try:
        ib.connect(host, port, clientId=client_id)
        print("Connected successfully!")
        
        # 1. GLOBAL CANCEL - This cancels ALL orders from ALL clients
        print("\n=== GLOBAL CANCEL ALL ORDERS ===")
        print("Requesting global cancel of ALL orders...")
        ib.reqGlobalCancel()
        
        # Wait for cancellations to process
        print("Waiting 5 seconds for cancellations to process...")
        ib.sleep(5)
        
        # Check for remaining orders
        ib.reqAllOpenOrders()
        ib.sleep(2)
        
        remaining_orders = ib.openOrders()
        print(f"Remaining orders after global cancel: {len(remaining_orders)}")
        for o in remaining_orders:
            print(f"  Still open: {o}")
        
        # 2. Close all positions
        print("\n=== CLOSING ALL POSITIONS ===")
        
        # Refresh positions
        ib.reqPositions()
        ib.sleep(2)
        
        positions = ib.positions()
        
        if positions:
            for pos in positions:
                symbol = pos.contract.symbol
                currency = pos.contract.currency  
                qty = pos.position
                
                if qty == 0:
                    continue
                    
                print(f"  Position: {symbol}/{currency} = {qty} units")
                
                # Create forex contract
                pair = symbol + currency
                    
                contract = Forex(pair)
                ib.qualifyContracts(contract)
                
                # Determine order side (opposite of position)
                if qty > 0:
                    action = "SELL"
                    close_qty = abs(qty)
                else:
                    action = "BUY"
                    close_qty = abs(qty)
                
                print(f"  Placing {action} order for {close_qty} {pair}...")
                order = MarketOrder(action, close_qty)
                trade = ib.placeOrder(contract, order)
                
                # Wait for fill
                print(f"  Waiting for fill...")
                for i in range(30):
                    ib.sleep(1)
                    if trade.isDone():
                        break
                
                if trade.orderStatus.status == "Filled":
                    print(f"  ✅ Filled at {trade.orderStatus.avgFillPrice}")
                else:
                    print(f"  ⚠️ Order status: {trade.orderStatus.status}")
                    if trade.log:
                        print(f"     {trade.log[-1]}")
        else:
            print("No open positions found.")
        
        # 3. Final verification
        print("\n=== FINAL VERIFICATION ===")
        
        ib.reqAllOpenOrders()
        ib.sleep(2)
        
        remaining_orders = ib.openOrders()
        
        ib.reqPositions()
        ib.sleep(1)
        remaining_positions = [p for p in ib.positions() if p.position != 0]
        
        print(f"Open orders: {len(remaining_orders)}")
        for o in remaining_orders:
            print(f"  {o}")
            
        print(f"Open positions: {len(remaining_positions)}")
        for p in remaining_positions:
            print(f"  {p.contract.symbol}: {p.position}")
        
        if not remaining_orders and not remaining_positions:
            print("\n✅ CLEANUP COMPLETE - Account is flat with no open orders")
        else:
            print("\n⚠️ WARNING: Some orders or positions remain")
            print("You may need to cancel/close them manually in TWS")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR.")


if __name__ == "__main__":
    print("=" * 60)
    print("IBKR GLOBAL CLEANUP SCRIPT")
    print("This will cancel ALL orders and close ALL positions!")
    print("=" * 60)
    
    cleanup_ibkr()
