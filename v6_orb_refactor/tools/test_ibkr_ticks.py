"""
Simple test to verify IBKR is streaming tick data correctly.
"""
from ib_insync import IB, Contract
import time

def main():
    print("Testing IBKR tick-by-tick data stream...")
    
    # Connect
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=998)
    print("Connected to IBKR")
    
    # Create XAUUSD contract
    contract = Contract(
        symbol='XAUUSD',
        secType='CMDTY',
        exchange='SMART',
        currency='USD'
    )
    
    # Request market data (regular ticker updates)
    ticker = ib.reqMktData(contract, '', False, False)
    print(f"Subscribed to {contract.symbol} market data")
    print("Waiting 5 seconds for data...")
    ib.sleep(5)
    
    print(f"\nRegular market data:")
    print(f"  Bid: {ticker.bid}")
    print(f"  Ask: {ticker.ask}")
    print(f"  Last: {ticker.last}")
    
    # Now try tick-by-tick
    print("\nRequesting tick-by-tick BidAsk data...")
    
    tick_count = 0
    
    def on_tick_data(ticker, time, bidPrice, askPrice, bidSize, askSize, *args):
        nonlocal tick_count
        tick_count += 1
        print(f"Tick #{tick_count}: Bid={bidPrice:.2f} Ask={askPrice:.2f}")
    
    # Subscribe to tick-by-tick
    ticker.updateEvent += on_tick_data
    ib.reqTickByTickData(contract, 'BidAsk', 0, True)
    
    print("Listening for 30 seconds...")
    print("(If you see no ticks, market may be closed or very quiet)")
    
    time.sleep(30)
    
    print(f"\nTotal ticks received: {tick_count}")
    
    ib.disconnect()
    print("Disconnected")

if __name__ == "__main__":
    main()
