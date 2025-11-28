#!/usr/bin/env python3
"""
PHASE 1: Verify MTF Indicator Calculations
Compare our Python calculations against TradingView values.

This script will:
1. Load 15m and 30m data
2. Calculate all indicators
3. Display recent values for manual verification against TradingView
"""
import pandas as pd
import pandas_ta as ta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def load_15m_data():
    """Load 15-minute data."""
    data_path = PROJECT_ROOT / "data" / "historical" / "EUR-USD_EUR_USD_IDEALPRO_15_MINUTE_MID_EXTERNAL.csv"
    df = pd.read_csv(data_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df.tail(500)  # Last 500 bars for verification

def create_30m_data(df_15m):
    """Resample 15m to 30m."""
    df_30m = df_15m.resample('30T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    return df_30m

def calculate_15m_indicators(df):
    """Calculate 15m indicators: MAMA (hl2 source), ATR."""
    df = df.copy()
    
    # hl2 source (LazyBear uses this)
    df['hl2'] = (df['high'] + df['low']) / 2
    
    # MAMA using hl2
    mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
    if mama_fama is not None:
        df['mama'] = mama_fama.iloc[:, 0]
        df['fama'] = mama_fama.iloc[:, 1]
        df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['atr_norm'] = df['atr'] / df['close']
    
    return df

def calculate_30m_indicators(df):
    """Calculate 30m indicators: DMI, Stochastic, WMA Difference."""
    df = df.copy()
    
    # DMI
    dmi = ta.adx(df['high'], df['low'], df['close'], length=14)
    if dmi is not None:
        df['adx'] = dmi['ADX_14']
        df['dmp'] = dmi['DMP_14']
        df['dmn'] = dmi['DMN_14']
    
    # Stochastic
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df['stoch_k'] = stoch['STOCHk_14_3_3']
        df['stoch_d'] = stoch['STOCHd_14_3_3']
    
    # WMA Difference (Ehlers)
    wma_short = ta.wma(df['close'], length=8)
    wma_long = ta.wma(df['close'], length=23)
    if wma_short is not None and wma_long is not None:
        df['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
    
    return df

def main():
    print("="*80)
    print("PHASE 1: MTF INDICATOR VERIFICATION")
    print("="*80)
    
    # Load data
    print("\n1. Loading 15-minute data...")
    df_15m = load_15m_data()
    print(f"   Loaded {len(df_15m)} bars")
    print(f"   Date range: {df_15m.index[0]} to {df_15m.index[-1]}")
    
    print("\n2. Creating 30-minute data...")
    df_30m = create_30m_data(df_15m)
    print(f"   Created {len(df_30m)} bars")
    
    # Calculate indicators
    print("\n3. Calculating 15m indicators (MAMA with hl2, ATR)...")
    df_15m = calculate_15m_indicators(df_15m)
    
    print("\n4. Calculating 30m indicators (DMI, Stoch, WMA Diff)...")
    df_30m = calculate_30m_indicators(df_30m)
    
    # Convert to UTC-5 (EST) for display
    df_15m_est = df_15m.copy()
    df_15m_est.index = df_15m_est.index.tz_convert('US/Eastern')
    
    df_30m_est = df_30m.copy()
    df_30m_est.index = df_30m_est.index.tz_convert('US/Eastern')
    
    # Display results
    print("\n" + "="*80)
    print("15-MINUTE INDICATORS (Last 10 bars) - Times in UTC-5 (EST)")
    print("="*80)
    cols_15m = ['close', 'hl2', 'mama', 'fama', 'mama_diff', 'atr', 'atr_norm']
    print(df_15m_est[cols_15m].tail(10).to_string())
    
    print("\n" + "="*80)
    print("30-MINUTE INDICATORS (Last 10 bars) - Times in UTC-5 (EST)")
    print("="*80)
    cols_30m = ['close', 'dmp', 'dmn', 'adx', 'stoch_k', 'stoch_d', 'wma_diff']
    print(df_30m_est[cols_30m].tail(10).to_string())
    
    print("\n" + "="*80)
    print("VERIFICATION INSTRUCTIONS")
    print("="*80)
    print("""
1. Open your TradingView chart with EUR/USD 15-minute
2. Compare the LAST values above with your chart indicators:
   
   15m Indicators:
   - MAMA (red line on chart)
   - FAMA (green line on chart)
   - ATR (bottom panel)
   
   30m Indicators:
   - DMI: DI+ (dmp), DI- (dmn), ADX
   - Stochastic: K (stoch_k), D (stoch_d)
   - WMA Diff: Ehlers MA Difference value
   
3. If values match (within 0.1%), indicators are correct!
4. If values differ significantly, we need to adjust the calculation.

Note: Small differences are expected due to:
- Different data sources (IB vs TradingView)
- Rounding differences
- Indicator warm-up period

IMPORTANT: Check the MOST RECENT bar values (last row in tables above)
""")
    
    print("\n" + "="*80)
    print("PHASE 1A-1B: COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Verify values match your TradingView chart")
    print("2. If OK, proceed to Phase 1C-1D (MTF data merging)")
    print("3. Then Phase 2 (model training)")

if __name__ == "__main__":
    main()
