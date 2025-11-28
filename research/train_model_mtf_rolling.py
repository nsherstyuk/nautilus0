"""
Rolling Window (Walk-Forward) ML Model Training for MTF Strategy.

This script implements walk-forward validation by training multiple models
on rolling windows of historical data. Each model is trained on N months
and tested on the following month, simulating real-world deployment.

Benefits:
- More realistic performance estimation
- Tests model adaptability to changing market conditions
- Reduces overfitting risk
- Shows if model degrades over time

Usage:
    python research/train_model_mtf_rolling.py

Output:
    - Multiple models saved to models/rolling/
    - Aggregated performance metrics
    - Per-window performance breakdown
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from joblib import dump
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, confusion_matrix
import logging

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from research.train_model_mtf import (
    calculate_features_15m,
    calculate_features_30m,
    merge_mtf_data,
    create_labels,
    prepare_training_data
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_data_for_period(symbol: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Load data from Parquet catalog for specific period."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Handle 30-minute resampling
    if timeframe == "30_MINUTE":
        df_15m = load_data_for_period(symbol, "15_MINUTE", start_date, end_date)
        df = df_15m.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        return df
    
    # Load from catalog
    instrument_id = "EURUSD.IDEALPRO"
    bar_type = f"{instrument_id}-{timeframe.replace('_', '-')}-MID-EXTERNAL"
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type}")
    
    # Convert to DataFrame
    data = {
        'timestamp': [pd.Timestamp(bar.ts_init, unit='ns', tz='UTC') for bar in bars],
        'open': [float(bar.open) for bar in bars],
        'high': [float(bar.high) for bar in bars],
        'low': [float(bar.low) for bar in bars],
        'close': [float(bar.close) for bar in bars],
        'volume': [int(bar.volume) for bar in bars]
    }
    
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter date range
    start_ts = pd.Timestamp(start_date).tz_localize('UTC')
    end_ts = pd.Timestamp(end_date).tz_localize('UTC')
    df = df[(df.index >= start_ts) & (df.index <= end_ts)]
    
    return df


def train_single_window(
    symbol: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    window_id: int
) -> dict:
    """Train and evaluate model for a single rolling window."""
    
    logger.info(f"\n{'='*80}")
    logger.info(f"WINDOW {window_id}")
    logger.info(f"Train: {train_start} to {train_end}")
    logger.info(f"Test:  {test_start} to {test_end}")
    logger.info(f"{'='*80}")
    
    # Load training data
    logger.info("Loading training data...")
    df_15m_train = load_data_for_period(symbol, "15_MINUTE", train_start, train_end)
    df_30m_train = load_data_for_period(symbol, "30_MINUTE", train_start, train_end)
    
    # Calculate features
    df_15m_train = calculate_features_15m(df_15m_train)
    df_30m_train = calculate_features_30m(df_30m_train)
    
    # Merge and create labels
    df_train = merge_mtf_data(df_15m_train, df_30m_train)
    df_train = create_labels(df_train, horizon=12, atr_multiplier=1.5)
    
    # Prepare training data
    X_train, y_train, feature_names = prepare_training_data(df_train)
    
    logger.info(f"Training samples: {len(X_train)}")
    logger.info(f"Buy signals: {sum(y_train == 1)}")
    logger.info(f"Sell signals: {sum(y_train == 0)}")
    
    # Train model
    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.1,
        max_depth=5,
        min_samples_leaf=20,
        random_state=42,
        verbose=0
    )
    
    model.fit(X_train, y_train)
    train_acc = model.score(X_train, y_train)
    logger.info(f"Train accuracy: {train_acc:.4f}")
    
    # Load test data
    logger.info("Loading test data...")
    df_15m_test = load_data_for_period(symbol, "15_MINUTE", test_start, test_end)
    df_30m_test = load_data_for_period(symbol, "30_MINUTE", test_start, test_end)
    
    # Calculate features
    df_15m_test = calculate_features_15m(df_15m_test)
    df_30m_test = calculate_features_30m(df_30m_test)
    
    # Merge and create labels
    df_test = merge_mtf_data(df_15m_test, df_30m_test)
    df_test = create_labels(df_test, horizon=12, atr_multiplier=1.5)
    
    # Prepare test data
    X_test, y_test, _ = prepare_training_data(df_test)
    
    logger.info(f"Test samples: {len(X_test)}")
    
    # Evaluate
    test_acc = model.score(X_test, y_test)
    y_pred = model.predict(X_test)
    
    logger.info(f"Test accuracy: {test_acc:.4f}")
    logger.info("\nClassification Report:")
    logger.info("\n" + classification_report(y_test, y_pred, target_names=['Sell', 'Buy']))
    
    # Save model
    models_dir = PROJECT_ROOT / "models" / "rolling"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = models_dir / f"ml_model_mtf_window_{window_id:02d}.pkl"
    dump(model, model_path)
    logger.info(f"Model saved: {model_path}")
    
    return {
        'window_id': window_id,
        'train_start': train_start,
        'train_end': train_end,
        'test_start': test_start,
        'test_end': test_end,
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'train_accuracy': train_acc,
        'test_accuracy': test_acc,
        'model_path': str(model_path)
    }


def main():
    """Run rolling window training."""
    logger.info("="*80)
    logger.info("ROLLING WINDOW (WALK-FORWARD) ML MODEL TRAINING")
    logger.info("="*80)
    
    # Configuration
    symbol = "EUR-USD"
    train_window_months = 6  # Train on 6 months
    test_window_months = 1   # Test on 1 month
    
    # Date range: 2024-01-01 to 2025-11-28
    start_date = pd.Timestamp("2024-01-01")
    end_date = pd.Timestamp("2025-11-28")
    
    # Calculate number of windows
    total_months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    num_windows = total_months - train_window_months
    
    logger.info(f"\nConfiguration:")
    logger.info(f"  Symbol: {symbol}")
    logger.info(f"  Train window: {train_window_months} months")
    logger.info(f"  Test window: {test_window_months} month")
    logger.info(f"  Date range: {start_date.date()} to {end_date.date()}")
    logger.info(f"  Number of windows: {num_windows}")
    
    # Train each window
    results = []
    
    for i in range(num_windows):
        # Calculate dates for this window
        train_start = start_date + pd.DateOffset(months=i)
        train_end = train_start + pd.DateOffset(months=train_window_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_window_months) - pd.Timedelta(days=1)
        
        # Ensure we don't go past end_date
        if test_end > end_date:
            test_end = end_date
        
        try:
            result = train_single_window(
                symbol=symbol,
                train_start=train_start.strftime("%Y-%m-%d"),
                train_end=train_end.strftime("%Y-%m-%d"),
                test_start=test_start.strftime("%Y-%m-%d"),
                test_end=test_end.strftime("%Y-%m-%d"),
                window_id=i + 1
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Error in window {i+1}: {e}")
            continue
    
    # Save results summary
    df_results = pd.DataFrame(results)
    results_path = PROJECT_ROOT / "models" / "rolling" / "rolling_window_results.csv"
    df_results.to_csv(results_path, index=False)
    
    # Print summary
    logger.info("\n" + "="*80)
    logger.info("ROLLING WINDOW SUMMARY")
    logger.info("="*80)
    logger.info(f"\nTotal windows: {len(results)}")
    logger.info(f"Average train accuracy: {df_results['train_accuracy'].mean():.4f}")
    logger.info(f"Average test accuracy: {df_results['test_accuracy'].mean():.4f}")
    logger.info(f"Test accuracy std: {df_results['test_accuracy'].std():.4f}")
    logger.info(f"Min test accuracy: {df_results['test_accuracy'].min():.4f}")
    logger.info(f"Max test accuracy: {df_results['test_accuracy'].max():.4f}")
    
    logger.info(f"\nResults saved to: {results_path}")
    logger.info("\n" + "="*80)
    logger.info("ROLLING WINDOW TRAINING COMPLETE")
    logger.info("="*80)


if __name__ == "__main__":
    main()
