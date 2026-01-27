"""
Debug version of backtest to show progress and identify where it stops.
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta as ta
from joblib import load
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from config.mtf_v2_config import load_mtf_v2_config

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

def load_and_prepare_data(start_date: str, end_date: str) -> pd.DataFrame:
    """Load 15-minute bar data from catalog."""
    catalog = ParquetDataCatalog(str(PROJECT_ROOT / "data" / "historical"))
    
    # Load 15-minute bars specifically
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type}...")
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type}")
    
    df = pd.DataFrame({
        'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in bars],
        'open': [float(b.open) for b in bars],
        'high': [float(b.high) for b in bars],
        'low': [float(b.low) for b in bars],
        'close': [float(b.close) for b in bars],
        'volume': [float(b.volume) for b in bars],
    })
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter to date range
    df = df[start_date:end_date]
    return df

def calculate_features_debug(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate MTF features with debug output."""
    print("Calculating features...")
    
    # 15m features
    df['hl2'] = (df['high'] + df['low']) / 2
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    print("Calculating MAMA...")
    try:
        mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
        df['mama'] = mama_fama.iloc[:, 0]
        df['fama'] = mama_fama.iloc[:, 1]
        df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
        print("MAMA calculated successfully")
    except Exception as e:
        print(f"MAMA failed: {e}")
        return None
    
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    # Resample to 30m
    print("Resampling to 30m...")
    df_30m = df.resample('30T').agg({
        'open': 'first',
        'high': 'max', 
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    print(f"30m DataFrame shape: {df_30m.shape}")
    
    # 30m features
    print("Calculating 30m indicators...")
    
    try:
        print("Calculating DMI...")
        dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
        df_30m['dmp_30m'] = dmi_30m.iloc[:, 1] / 100.0
        df_30m['dmn_30m'] = dmi_30m.iloc[:, 2] / 100.0
        print("DMI calculated successfully")
    except Exception as e:
        print(f"DMI failed: {e}")
        return None
    
    try:
        print("Calculating Stochastic...")
        stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
        df_30m['stoch_k_30m'] = stoch_30m.iloc[:, 0] / 100.0
        df_30m['stoch_d_30m'] = stoch_30m.iloc[:, 1] / 100.0
        print("Stochastic calculated successfully")
    except Exception as e:
        print(f"Stochastic failed: {e}")
        return None
    
    try:
        print("Calculating WMA...")
        wma_short = ta.wma(df_30m['close'], length=8)
        wma_long = ta.wma(df_30m['close'], length=23)
        df_30m['wma_diff_30m'] = 100 * (wma_short - wma_long) / wma_long
        print("WMA calculated successfully")
    except Exception as e:
        print(f"WMA failed: {e}")
        return None
    
    # Join back to 15m
    df_30m_renamed = df_30m[['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']]
    df_30m_renamed.columns = ['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']
    df = df.join(df_30m_renamed, how='left')
    df = df.ffill()
    df = df.dropna()
    
    print(f"Final DataFrame shape after feature calculation: {df.shape}")
    return df

def main():
    """Debug the backtest progress."""
    print("=" * 80)
    print("DEBUG BACKTEST - PROGRESS TRACKING")
    print("=" * 80)
    
    # Load config
    config = load_mtf_v2_config()
    
    # Load data
    print(f"Loading data: {config.backtest_start} to {config.backtest_end}...")
    df = load_and_prepare_data(config.backtest_start, config.backtest_end)
    print(f"Data loaded: {len(df)} bars")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    
    # Calculate features
    df_features = calculate_features_debug(df)
    
    if df_features is None:
        print("Feature calculation failed!")
        return
    
    print(f"Features calculated successfully. Final shape: {df_features.shape}")
    print(f"Date range after feature calculation: {df_features.index.min()} to {df_features.index.max()}")
    
    # Check for gaps in the final data
    print("\nChecking for gaps in final data...")
    df_features['time_diff'] = df_features.index.to_series().diff()
    gaps = df_features[df_features['time_diff'] > pd.Timedelta('16 minutes')]
    print(f"Number of gaps (>15min): {len(gaps)}")
    
    if len(gaps) > 0:
        print("Gaps found:")
        for idx, row in gaps.head(5).iterrows():
            print(f"  Gap at {idx}: {row['time_diff']}")
    
    print("\nDebug complete!")

if __name__ == "__main__":
    main()
