#!/usr/bin/env python3
"""
Train an ML model for forex trading using historical data.
Implements feature engineering that matches the live strategy exactly.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def load_data(symbol: str = "EUR-USD", timeframe: str = "5_MINUTE") -> pd.DataFrame:
    """Load historical data from CSV."""
    data_path = PROJECT_ROOT / "data" / "historical" / f"{symbol}_{symbol.replace('-', '_')}_IDEALPRO_{timeframe}_MID_EXTERNAL.csv"
    df = pd.read_csv(data_path, parse_dates=['timestamp'])
    df.set_index('timestamp', inplace=True)
    return df

def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate features using pandas-ta.
    CRITICAL: This must match the live strategy's _calculate_features method exactly.
    """
    # Copy to avoid modifying original
    df = df.copy()
    
    # 1. Log Returns (scaled x100 to avoid tiny numbers)
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    # 2. RSI (14) - Normalized to 0-1
    df['rsi'] = ta.rsi(df['close'], length=14) / 100
    
    # 3. MACD (12, 26, 9) - Use histogram, normalize by price
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd[f'MACDh_12_26_9'] / df['close']
    
    # 4. Stochastic (14, 3, 3) - Already 0-100, normalize to 0-1
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    df['stoch_k'] = stoch[f'STOCHk_14_3_3'] / 100
    
    # 5. ADX (14) - Normalize to 0-1
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx[f'ADX_14'] / 100
    
    # 6. ATR (14) - Normalize by price
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    
    return df

def create_labels(df: pd.DataFrame, horizon: int = 12) -> pd.DataFrame:
    """
    Implement Triple Barrier Method using ATR for dynamic thresholds.
    
    Args:
        df: DataFrame with 'close' and 'atr' columns
        horizon: Number of bars to look ahead (vertical barrier)
    """
    df = df.copy()
    
    # ATR multiplier for upper/lower barriers
    BARRIER_MULT = 1.5
    
    # Initialize labels
    df['label'] = 0  # Default: no signal
    
    for i in range(len(df) - horizon):
        current_price = df['close'].iloc[i]
        current_atr = df['atr'].iloc[i] * df['close'].iloc[i]  # De-normalize ATR
        
        # Dynamic barriers based on ATR
        upper_barrier = current_price + (current_atr * BARRIER_MULT)
        lower_barrier = current_price - (current_atr * BARRIER_MULT)
        
        # Get future prices for next 'horizon' bars
        future_prices = df['close'].iloc[i+1:i+horizon+1]
        
        # Check which barrier is hit first
        upper_touch = future_prices >= upper_barrier
        lower_touch = future_prices <= lower_barrier
        
        if upper_touch.any() and (not lower_touch.any() or upper_touch.idxmax() < lower_touch.idxmax()):
            df['label'].iloc[i] = 1  # Buy signal
        elif lower_touch.any() and (not upper_touch.any() or lower_touch.idxmax() < upper_touch.idxmax()):
            df['label'].iloc[i] = -1  # Sell signal
            
    return df

def main():
    # 1. Load and prepare data
    df = load_data()  # Default EUR-USD M5
    
    # 2. Calculate features
    df = calculate_features(df)
    
    # 3. Create labels
    df = create_labels(df)
    
    # 4. Drop rows with NaN (caused by indicators)
    df.dropna(inplace=True)
    
    # 5. Prepare features and target
    feature_cols = ['log_ret', 'rsi', 'macd_hist', 'stoch_k', 'adx', 'atr']
    X = df[feature_cols]
    y = df['label']
    
    # 6. Train/Test split (use recent data for testing)
    split_idx = int(len(df) * 0.8)
    X_train = X[:split_idx]
    X_test = X[split_idx:]
    y_train = y[:split_idx]
    y_test = y[split_idx:]
    
    # 7. Train Random Forest
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        min_samples_leaf=20,  # Prevent overfitting
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # 8. Evaluate
    y_pred = model.predict(X_test)
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    # 9. Save model
    models_dir = PROJECT_ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    joblib.dump(model, models_dir / "strategy_model.joblib")
    print(f"\nModel saved to {models_dir / 'strategy_model.joblib'}")
    
    # 10. Feature importance
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    })
    print("\nFeature Importance:")
    print(importance.sort_values('importance', ascending=False))

if __name__ == "__main__":
    main()
