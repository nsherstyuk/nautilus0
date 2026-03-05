#!/usr/bin/env python3
"""
Analyze different training window sizes using rolling window validation.
Tests both 2-month and 3-month training windows to determine optimal size.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score, f1_score
import matplotlib.pyplot as plt

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "analysis_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Setup logging
def setup_logging() -> logging.Logger:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("window_analysis")
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_dir / f"window_analysis_{datetime.now():%Y%m%d_%H%M%S}.log")
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

def load_data(symbol: str = "EUR-USD") -> pd.DataFrame:
    """Load and prepare the full dataset."""
    data_path = PROJECT_ROOT / "data" / "historical" / f"{symbol}_{symbol.replace('-', '_')}_IDEALPRO_5_MINUTE_MID_EXTERNAL.csv"
    df = pd.read_csv(data_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df

def filter_trading_session(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for trading session hours."""
    # Convert times to datetime.time
    start_time = datetime.strptime("02:00", "%H:%M").time()
    end_time = datetime.strptime("16:00", "%H:%M").time()
    
    # Session filter
    mask = (df.index.time >= start_time) & (df.index.time <= end_time)
    
    # Exclude illiquid hours
    hour_mask = ~df.index.hour.isin([0, 1])
    mask = mask & hour_mask
    
    return df[mask].copy()

def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate technical indicators."""
    df = df.copy()
    
    # 1. Log Returns
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    # 2. RSI
    df['rsi'] = ta.rsi(df['close'], length=14) / 100
    
    # 3. MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd[f'MACDh_12_26_9'] / df['close']
    
    # 4. Stochastic
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    df['stoch_k'] = stoch[f'STOCHk_14_3_3'] / 100
    
    # 5. ADX
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx[f'ADX_14'] / 100
    
    # 6. ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    
    return df

def create_labels(df: pd.DataFrame, horizon: int = 12) -> pd.DataFrame:
    """Create labels using Triple Barrier Method."""
    df = df.copy()
    df.loc[:, 'label'] = 0
    df.loc[:, 'barrier_hit'] = 'none'
    df.loc[:, 'bars_to_exit'] = -1
    
    timestamps = df.index.tolist()
    
    for i in range(len(df) - horizon):
        current_time = timestamps[i]
        current_price = df['close'].iloc[i]
        current_atr = df['atr'].iloc[i] * df['close'].iloc[i]
        
        # Dynamic barriers (1.5 * ATR)
        upper_barrier = current_price + (current_atr * 1.5)
        lower_barrier = current_price - (current_atr * 1.5)
        
        # Get future prices
        future_slice = slice(i + 1, i + horizon + 1)
        future_prices = df['close'].iloc[future_slice]
        future_times = timestamps[i + 1:i + horizon + 1]
        
        upper_touch = future_prices >= upper_barrier
        lower_touch = future_prices <= lower_barrier
        
        if upper_touch.any() and (not lower_touch.any() or 
            (upper_touch.idxmax() < lower_touch.idxmax() if lower_touch.any() else True)):
            df.loc[current_time, 'label'] = 1
            df.loc[current_time, 'barrier_hit'] = 'upper'
            exit_time = future_prices[upper_touch].index[0]
            df.loc[current_time, 'bars_to_exit'] = future_times.index(exit_time)
            
        elif lower_touch.any() and (not upper_touch.any() or
            (lower_touch.idxmax() < upper_touch.idxmax() if upper_touch.any() else True)):
            df.loc[current_time, 'label'] = -1
            df.loc[current_time, 'barrier_hit'] = 'lower'
            exit_time = future_prices[lower_touch].index[0]
            df.loc[current_time, 'bars_to_exit'] = future_times.index(exit_time)
            
        else:
            df.loc[current_time, 'barrier_hit'] = 'vertical'
            df.loc[current_time, 'bars_to_exit'] = horizon
            
    return df

def train_and_evaluate(
    train_data: pd.DataFrame,
    valid_data: pd.DataFrame,
    feature_cols: List[str]
) -> Dict[str, Any]:
    """Train model and evaluate on validation data."""
    # Prepare features
    X_train = train_data[feature_cols].values
    y_train = train_data['label'].values
    
    X_valid = valid_data[feature_cols].values
    y_valid = valid_data['label'].values
    
    # Train model
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=5,
        min_samples_leaf=20,
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # Get predictions
    y_pred = model.predict(X_valid)
    
    # Calculate metrics
    metrics = {
        'accuracy': accuracy_score(y_valid, y_pred),
        'f1_weighted': f1_score(y_valid, y_pred, average='weighted'),
        'train_samples': len(train_data),
        'valid_samples': len(valid_data),
        'train_period': f"{train_data.index[0]} to {train_data.index[-1]}",
        'valid_period': f"{valid_data.index[0]} to {valid_data.index[-1]}",
        'class_distribution': {
            'train': {
                'buy': (y_train == 1).mean(),
                'sell': (y_train == -1).mean(),
                'neutral': (y_train == 0).mean()
            },
            'valid': {
                'buy': (y_valid == 1).mean(),
                'sell': (y_valid == -1).mean(),
                'neutral': (y_valid == 0).mean()
            }
        }
    }
    
    return metrics

def analyze_window_size(
    df: pd.DataFrame,
    window_months: int,
    feature_cols: List[str]
) -> List[Dict[str, Any]]:
    """Analyze performance using rolling windows of specified size."""
    results = []
    
    # Calculate window size in days
    train_days = window_months * 30
    valid_days = window_months * 30
    
    # Get unique months in the dataset
    months = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq='M'
    )
    
    for i in range(0, len(months) - window_months * 2):
        # Training period
        train_start = months[i]
        train_end = months[i + window_months]
        
        # Validation period
        valid_start = train_end
        valid_end = months[i + window_months * 2]
        
        # Get data for each period
        train_data = df[train_start:train_end]
        valid_data = df[valid_start:valid_end]
        
        # Skip if not enough data
        if len(train_data) < 1000 or len(valid_data) < 1000:
            continue
            
        # Train and evaluate
        metrics = train_and_evaluate(train_data, valid_data, feature_cols)
        metrics['window_size'] = window_months
        
        results.append(metrics)
        
        logger.info(f"\nWindow {i+1}:")
        logger.info(f"Training: {train_start.date()} to {train_end.date()}")
        logger.info(f"Validation: {valid_start.date()} to {valid_end.date()}")
        logger.info(f"Accuracy: {metrics['accuracy']:.3f}")
        logger.info(f"F1 Score: {metrics['f1_weighted']:.3f}")
    
    return results

def plot_window_comparison(results_2m: List[Dict], results_3m: List[Dict]) -> None:
    """Plot performance comparison between 2-month and 3-month windows."""
    # Extract metrics
    acc_2m = [r['accuracy'] for r in results_2m]
    acc_3m = [r['accuracy'] for r in results_3m]
    f1_2m = [r['f1_weighted'] for r in results_2m]
    f1_3m = [r['f1_weighted'] for r in results_3m]
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot accuracy
    ax1.plot(acc_2m, label='2-month window', marker='o')
    ax1.plot(acc_3m, label='3-month window', marker='s')
    ax1.set_title('Accuracy Over Time')
    ax1.set_xlabel('Window Number')
    ax1.set_ylabel('Accuracy')
    ax1.legend()
    ax1.grid(True)
    
    # Plot F1 score
    ax2.plot(f1_2m, label='2-month window', marker='o')
    ax2.plot(f1_3m, label='3-month window', marker='s')
    ax2.set_title('F1 Score Over Time')
    ax2.set_xlabel('Window Number')
    ax2.set_ylabel('F1 Score')
    ax2.legend()
    ax2.grid(True)
    
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / 'window_comparison.png')
    plt.close()
    
    # Print summary statistics
    logger.info("\nSummary Statistics:")
    logger.info("2-Month Windows:")
    logger.info(f"  Avg Accuracy: {np.mean(acc_2m):.3f} ± {np.std(acc_2m):.3f}")
    logger.info(f"  Avg F1 Score: {np.mean(f1_2m):.3f} ± {np.std(f1_2m):.3f}")
    logger.info("\n3-Month Windows:")
    logger.info(f"  Avg Accuracy: {np.mean(acc_3m):.3f} ± {np.std(acc_3m):.3f}")
    logger.info(f"  Avg F1 Score: {np.mean(f1_3m):.3f} ± {np.std(f1_3m):.3f}")

def main():
    try:
        # 1. Load and prepare data
        logger.info("Loading data...")
        df = load_data()
        
        # 2. Filter trading sessions
        df = filter_trading_session(df)
        
        # 3. Calculate features
        df = calculate_features(df)
        
        # 4. Create labels
        df = create_labels(df)
        
        # 5. Drop NaN values
        feature_cols = ['log_ret', 'rsi', 'macd_hist', 'stoch_k', 'adx', 'atr']
        df = df.dropna(subset=feature_cols + ['label'])
        
        # 6. Analyze both window sizes
        logger.info("\nAnalyzing 2-month windows...")
        results_2m = analyze_window_size(df, window_months=2, feature_cols=feature_cols)
        
        logger.info("\nAnalyzing 3-month windows...")
        results_3m = analyze_window_size(df, window_months=3, feature_cols=feature_cols)
        
        # 7. Plot comparison
        plot_window_comparison(results_2m, results_3m)
        
        # 8. Save detailed results
        results = {
            'two_month_windows': results_2m,
            'three_month_windows': results_3m
        }
        
        import json
        with open(RESULTS_DIR / 'window_analysis.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        logger.info(f"\nAnalysis complete. Results saved to {RESULTS_DIR}")
        
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
