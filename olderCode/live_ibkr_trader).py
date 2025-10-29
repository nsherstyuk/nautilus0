import asyncio
from ib_insync import IB, util, Forex
import pandas as pd
import json
from data_processor import DataProcessor
from trading_engine_v2 import TradingEngineV2

# Load config
with open("Nick3.json") as f:
    config = json.load(f)

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

contract = Forex('EURUSD')
ib.qualifyContracts(contract)

bars = []
processor = DataProcessor()
engine = TradingEngineV2(config)
trade_history = []

tick_buffer = []

def on_tick(tick):
    tick_data = {
        "Local time": pd.Timestamp.now(),
        "Ask": tick.ask,
        "Bid": tick.bid,
        "AskVolume": tick.askSize,
        "BidVolume": tick.bidSize,
    }
    tick_buffer.append(tick_data)

    # Process every 30s
    if len(tick_buffer) >= 3:  # Approx 10 ticks per second
        new_bar_df = pd.DataFrame(tick_buffer)
        bar = processor.generate_single_bar(new_bar_df)
        if bar:
            bars.append(bar)
            results = engine.run_trading_system(pd.DataFrame(bars))
            trades = results.get("trades", [])
            if len(trades) > len(trade_history):
                trade = trades[-1]
                print("💡 TRADE SIGNAL:", trade)
                trade_history.append(trade)
        tick_buffer.clear()

ib.reqMktData(contract, snapshot=False, regulatorySnapshot=False, mktDataOptions=[])
ib.pendingTickersEvent += on_tick

print("✅ Running minimal live IBKR trading engine...")
ib.run()
