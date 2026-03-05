"""
Probe IBKR for crypto data availability.
Check what instruments, bar sizes, and history depth we can get.
"""

from ib_insync import IB, Crypto, Contract, util
import pandas as pd
from datetime import datetime, timedelta

def main():
    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=50)
    print(f"  Connected: {ib.isConnected()}")
    
    # ── 1. Check available crypto contracts ──
    print("\n  === CRYPTO CONTRACTS ===")
    symbols = ["BTC", "ETH", "LTC", "BCH", "SOL", "ADA", "DOT", "LINK",
               "AVAX", "DOGE", "XRP", "BNB", "MATIC", "UNI", "AAVE"]
    
    available = []
    for sym in symbols:
        try:
            contract = Crypto(sym, "PAXOS", "USD")
            details = ib.reqContractDetails(contract)
            if details:
                d = details[0]
                print(f"    {sym:>6}/USD: ✓  exchange={d.contract.exchange}  "
                      f"minSize={d.minSize}  priceMag={d.priceMagnifier}")
                available.append(sym)
            else:
                print(f"    {sym:>6}/USD: ✗  (no contract details)")
        except Exception as e:
            print(f"    {sym:>6}/USD: ✗  ({e})")
    
    print(f"\n  Available: {len(available)} / {len(symbols)}")
    
    if not available:
        print("  No crypto available on this account. Checking other exchanges...")
        # Try different exchange
        for exch in ["PAXOS", "COINBASE", "GEMINI"]:
            try:
                contract = Crypto("BTC", exch, "USD")
                details = ib.reqContractDetails(contract)
                if details:
                    print(f"    BTC on {exch}: ✓")
                else:
                    print(f"    BTC on {exch}: ✗")
            except Exception as e:
                print(f"    BTC on {exch}: error - {e}")
    
    # ── 2. Test historical data for available cryptos ──
    if available:
        test_sym = available[0]
        contract = Crypto(test_sym, "PAXOS", "USD")
        ib.qualifyContracts(contract)
        
        print(f"\n  === HISTORICAL DATA TEST: {test_sym} ===")
        
        bar_sizes = [
            "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins",
            "30 mins", "1 hour", "2 hours", "4 hours", "1 day",
        ]
        
        for bs in bar_sizes:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr="2 D",
                    barSizeSetting=bs,
                    whatToShow="MIDPOINT",
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    first = df["date"].iloc[0]
                    last = df["date"].iloc[-1]
                    print(f"    {bs:>10}: {len(df):>5} bars  "
                          f"({first} → {last})  "
                          f"close={df['close'].iloc[-1]:.2f}")
                else:
                    print(f"    {bs:>10}: no data")
            except Exception as e:
                print(f"    {bs:>10}: error - {e}")
        
        # ── 3. Test max history depth ──
        print(f"\n  === MAX HISTORY DEPTH: {test_sym} (5 min bars) ===")
        
        durations = ["1 D", "3 D", "1 W", "2 W", "1 M", "3 M", "6 M", "1 Y"]
        for dur in durations:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting="5 mins",
                    whatToShow="MIDPOINT",
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    first = df["date"].iloc[0]
                    last = df["date"].iloc[-1]
                    n_days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
                    print(f"    {dur:>5}: {len(df):>6} bars  "
                          f"({first} → {last})  [{n_days}d span]")
                else:
                    print(f"    {dur:>5}: no data")
            except Exception as e:
                print(f"    {dur:>5}: error - {e}")
        
        # ── 4. Test 1-min depth ──
        print(f"\n  === MAX HISTORY DEPTH: {test_sym} (1 min bars) ===")
        for dur in ["1 D", "3 D", "1 W", "2 W"]:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting="1 min",
                    whatToShow="MIDPOINT",
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    first = df["date"].iloc[0]
                    last = df["date"].iloc[-1]
                    print(f"    {dur:>5}: {len(df):>6} bars  ({first} → {last})")
                else:
                    print(f"    {dur:>5}: no data")
            except Exception as e:
                print(f"    {dur:>5}: error - {e}")
        
        # ── 5. Test hourly depth ──
        print(f"\n  === MAX HISTORY DEPTH: {test_sym} (1 hour bars) ===")
        for dur in ["1 W", "1 M", "3 M", "6 M", "1 Y", "2 Y"]:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting="1 hour",
                    whatToShow="MIDPOINT",
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    first = df["date"].iloc[0]
                    last = df["date"].iloc[-1]
                    print(f"    {dur:>5}: {len(df):>6} bars  ({first} → {last})")
                else:
                    print(f"    {dur:>5}: no data")
            except Exception as e:
                print(f"    {dur:>5}: error - {e}")
        
        # ── 6. Check what data types are available ──
        print(f"\n  === DATA TYPES: {test_sym} ===")
        for what in ["MIDPOINT", "BID", "ASK", "TRADES", "BID_ASK",
                      "HISTORICAL_VOLATILITY", "AGGTRADES"]:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr="1 D",
                    barSizeSetting="1 hour",
                    whatToShow=what,
                    useRTH=False,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    print(f"    {what:>25}: ✓ ({len(df)} bars)")
                else:
                    print(f"    {what:>25}: no data")
            except Exception as e:
                err = str(e)[:60]
                print(f"    {what:>25}: ✗ ({err})")

        # ── 7. Second available crypto ──
        if len(available) > 1:
            test2 = available[1]
            print(f"\n  === SECOND CRYPTO: {test2} (1 hour, 1M) ===")
            c2 = Crypto(test2, "PAXOS", "USD")
            ib.qualifyContracts(c2)
            try:
                bars = ib.reqHistoricalData(
                    c2, endDateTime="", durationStr="1 M",
                    barSizeSetting="1 hour", whatToShow="MIDPOINT",
                    useRTH=False, formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    print(f"    {len(df)} bars: {df['date'].iloc[0]} → {df['date'].iloc[-1]}")
                    print(f"    Price: {df['close'].iloc[-1]:.2f}")
            except Exception as e:
                print(f"    Error: {e}")
    
    ib.disconnect()
    print("\n  Done.")


if __name__ == "__main__":
    main()
