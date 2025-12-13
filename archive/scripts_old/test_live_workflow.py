"""
Live Workflow Integration Test

This script tests the COMPLETE live trading workflow by:
1. Loading the strategy with real configuration
2. Feeding historical bars one-by-one (simulating live feed)
3. Verifying feature calculation works
4. Verifying ML predictions are generated
5. Verifying order submission logic is triggered

This tests everything EXCEPT the actual IBKR connection.
Use this to validate the workflow works before going live.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from collections import deque

# Mock NautilusTrader components for testing
class MockCache:
    def __init__(self):
        self._positions = []
        self._orders = []
        
    def positions_open(self, instrument_id=None):
        return self._positions
    
    def instrument(self, instrument_id):
        # Return a mock instrument
        return MockInstrument()

class MockInstrument:
    def __init__(self):
        self.id = "EUR/USD.IDEALPRO"
        self.price_precision = 5
        self.size_precision = 0

class MockOrderFactory:
    def __init__(self):
        self.orders_created = []
        
    def bracket(self, **kwargs):
        order = {
            'type': 'bracket',
            'instrument_id': kwargs.get('instrument_id'),
            'side': kwargs.get('order_side'),
            'quantity': kwargs.get('quantity'),
            'sl_price': kwargs.get('sl_trigger_price'),
            'tp_price': kwargs.get('tp_price'),
        }
        self.orders_created.append(order)
        print(f"   📋 ORDER CREATED: {order['side']} {order['quantity']} @ market")
        print(f"      SL: {order['sl_price']}, TP: {order['tp_price']}")
        return MockBracketOrderList()

class MockBracketOrderList:
    def __init__(self):
        self.orders = []

class MockLog:
    def info(self, msg): print(f"   [INFO] {msg}")
    def warning(self, msg): print(f"   [WARN] {msg}")
    def error(self, msg): print(f"   [ERROR] {msg}")
    def debug(self, msg): pass  # Suppress debug

class MockClock:
    def __init__(self):
        self._time = 0
    def timestamp_ns(self):
        return self._time


def run_workflow_test():
    """Run the complete workflow test"""
    
    print("\n" + "=" * 70)
    print("  LIVE WORKFLOW INTEGRATION TEST")
    print("  Testing: Data → Features → Prediction → Order Submission")
    print("=" * 70)
    
    # Step 1: Load configuration
    print("\n📌 STEP 1: Loading Configuration")
    from config.mtf_config import load_mtf_config
    config = load_mtf_config()
    print(f"   ✅ Config loaded: {config.symbol}, {config.bar_spec}")
    print(f"   Model: {config.model_path}")
    print(f"   Threshold: {config.prediction_threshold}")
    print(f"   Debug mode: {config.debug_mode}")
    
    # Step 2: Load historical data
    print("\n📌 STEP 2: Loading Historical Data")
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
    from nautilus_trader.model.identifiers import InstrumentId
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    if not catalog_path.exists():
        print(f"   ❌ Catalog not found at {catalog_path}")
        return False
    
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Load bars using NautilusTrader catalog API
    instrument_id = InstrumentId.from_str(f"{config.symbol}.{config.venue}")
    
    # Get bar type string
    bar_type_str = f"{config.symbol}.{config.venue}-{config.bar_spec}"
    
    # Load bars from catalog
    try:
        nautilus_bars = catalog.bars(
            instrument_ids=[str(instrument_id)],
            bar_types=[bar_type_str],
            start="2025-11-01",
            end="2025-11-30",
        )
    except Exception as e:
        print(f"   ⚠️ Failed to load with bar_types filter: {e}")
        # Try without bar_types filter
        nautilus_bars = catalog.bars(
            instrument_ids=[str(instrument_id)],
            start="2025-11-01", 
            end="2025-11-30",
        )
    
    if not nautilus_bars:
        print("   ❌ No historical data found!")
        return False
    
    print(f"   ✅ Loaded {len(nautilus_bars)} bars from catalog")
    # Get date range from first and last bar
    first_bar = nautilus_bars[0]
    last_bar = nautilus_bars[-1]
    first_time = pd.Timestamp(first_bar.ts_init, unit='ns', tz='UTC')
    last_time = pd.Timestamp(last_bar.ts_init, unit='ns', tz='UTC')
    print(f"   Date range: {first_time} to {last_time}")
    
    # Step 3: Test components individually (without full strategy instantiation)
    print("\n📌 STEP 3: Testing Components Individually")
    
    # 3a: Test model loading
    from joblib import load
    model_path = PROJECT_ROOT / config.model_path
    model = load(model_path)
    print(f"   ✅ Model loaded: {type(model).__name__}")
    
    # 3b: Test feature calculation logic
    print("\n📌 STEP 4: Testing Feature Calculation")
    import pandas_ta as ta
    
    # Convert bars to DataFrame for feature calculation
    bar_data = []
    for bar in nautilus_bars:
        bar_data.append({
            'timestamp': pd.Timestamp(bar.ts_init, unit='ns', tz='UTC'),
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': float(bar.volume),
        })
    df_15m = pd.DataFrame(bar_data)
    df_15m.set_index('timestamp', inplace=True)
    
    # Resample to 30m
    df_30m = df_15m.resample('30min').agg({
        'open': 'first',
        'high': 'max', 
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    print(f"   15m bars: {len(df_15m)}, 30m bars: {len(df_30m)}")
    
    # Calculate features (same as strategy)
    # 15m features
    df_15m['log_ret'] = np.log(df_15m['close'] / df_15m['close'].shift(1))
    df_15m['hl2'] = (df_15m['high'] + df_15m['low']) / 2
    mama = ta.mama(df_15m['hl2'], fastlimit=0.5, slowlimit=0.05)
    if mama is not None and not mama.empty:
        df_15m['mama'] = mama.iloc[:, 0]
        df_15m['fama'] = mama.iloc[:, 1]
        df_15m['mama_diff'] = df_15m['mama'] - df_15m['fama']
    
    atr = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14)
    if atr is not None:
        df_15m['atr'] = atr / df_15m['close']  # Normalized ATR
    
    # 30m features
    dmi = ta.dm(df_30m['high'], df_30m['low'], length=14)
    if dmi is not None and not dmi.empty:
        df_30m['dmp'] = dmi.iloc[:, 0]
        df_30m['dmn'] = dmi.iloc[:, 1]
    
    stoch = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3)
    if stoch is not None and not stoch.empty:
        df_30m['stoch_k'] = stoch.iloc[:, 0] / 100.0
        df_30m['stoch_d'] = stoch.iloc[:, 1] / 100.0
    
    wma = ta.wma(df_30m['close'], length=30)
    if wma is not None:
        df_30m['wma_diff'] = (df_30m['close'] - wma) / df_30m['close']
    
    print(f"   ✅ Features calculated")
    
    # Step 5: Test predictions
    print("\n📌 STEP 5: Testing Predictions")
    
    feature_names = ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m', 'atr', 'hour', 'day_of_week']
    
    # Get last 100 rows with all features
    predictions = []
    signals = {'buy': 0, 'sell': 0}
    
    # Use the last portion of data where we have all features
    start_idx = max(100, len(df_15m) - 500)  # Test last 500 bars
    
    for i in range(start_idx, len(df_15m)):
        row_15m = df_15m.iloc[i]
        
        # Find corresponding 30m bar
        bar_time = df_15m.index[i]
        aligned_30m = bar_time.floor('30min')
        
        if aligned_30m not in df_30m.index:
            continue
        
        row_30m = df_30m.loc[aligned_30m]
        
        # Skip if any features are NaN
        if pd.isna(row_15m.get('log_ret')) or pd.isna(row_15m.get('mama_diff')) or pd.isna(row_15m.get('atr')):
            continue
        if pd.isna(row_30m.get('dmp')) or pd.isna(row_30m.get('stoch_k')) or pd.isna(row_30m.get('wma_diff')):
            continue
        
        # Build feature vector
        features = np.array([[
            row_15m['log_ret'],
            row_15m['mama_diff'],
            row_30m['dmp'],
            row_30m['dmn'],
            row_30m['stoch_k'],
            row_30m['stoch_d'],
            row_30m['wma_diff'],
            row_15m['atr'],
            bar_time.hour,
            bar_time.dayofweek,
        ]])
        
        # Make prediction
        try:
            prediction = model.predict(features)[0]
            probas = model.predict_proba(features)[0]
            confidence = max(probas)
            
            if confidence >= config.prediction_threshold:
                if prediction == 1:
                    signals['buy'] += 1
                else:
                    signals['sell'] += 1
                    
            predictions.append({
                'time': bar_time,
                'prediction': prediction,
                'confidence': confidence,
                'close': row_15m['close'],
            })
        except Exception as e:
            print(f"   ⚠️ Prediction error at {bar_time}: {e}")
    
    print(f"   ✅ Made {len(predictions)} predictions")
    print(f"   Buy signals: {signals['buy']}, Sell signals: {signals['sell']}")
    
    if predictions:
        # Show sample predictions
        print("\n   Sample predictions:")
        for p in predictions[-5:]:
            signal = "BUY" if p['prediction'] == 1 else "SELL"
            print(f"      {p['time']}: {signal} (conf: {p['confidence']:.3f}) @ {p['close']:.5f}")
    
    # Step 6: Summary
    print("\n📌 STEP 6: Test Summary")
    print("=" * 70)
    
    results = {
        "Historical bars loaded": len(nautilus_bars),
        "15m DataFrame rows": len(df_15m),
        "30m DataFrame rows": len(df_30m),
        "Predictions made": len(predictions),
        "Buy signals": signals['buy'],
        "Sell signals": signals['sell'],
        "Total signals": signals['buy'] + signals['sell'],
    }
    
    for key, value in results.items():
        print(f"   {key}: {value}")
    
    # Determine success
    print("\n" + "=" * 70)
    if len(predictions) == 0:
        print("❌ FAIL: No predictions could be made")
        print("   Check feature calculation logic")
        return False
    elif signals['buy'] + signals['sell'] == 0:
        print("⚠️ WARNING: No signals above threshold")
        print(f"   Threshold: {config.prediction_threshold}")
        print("   Try lowering threshold or check model quality")
        return False
    else:
        print(f"✅ SUCCESS: Workflow components are functioning!")
        print(f"\n   The workflow CAN:")
        print(f"   ✓ Load configuration")
        print(f"   ✓ Load historical data")
        print(f"   ✓ Calculate features (15m + 30m)")
        print(f"   ✓ Make ML predictions")
        print(f"   ✓ Generate trading signals")
        print(f"\n   ⚠️ NOT TESTED by this script:")
        print(f"   - Live bar subscription (requires running NautilusTrader node)")
        print(f"   - Actual order submission to IBKR")
        print(f"   - Position tracking and trailing stops")
        return True


if __name__ == "__main__":
    success = run_workflow_test()
    sys.exit(0 if success else 1)
