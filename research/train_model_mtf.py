#!/usr/bin/env python3
"""
Train ML model with Multi-Timeframe (MTF) features.

Timeframe Configuration:
- 15-minute: Price data, MAMA/FAMA, ATR
- 30-minute: DMI, Stochastic, WMA Difference

Features (10 total):
1. log_ret_15m: 15m price momentum
2. mama_diff_15m: 15m (MAMA - FAMA) / close (LazyBear, hl2 source)
3. dmp_30m: 30m DI+ (bullish pressure)
4. dmn_30m: 30m DI- (bearish pressure)
5. stoch_k_30m: 30m Stochastic K
6. stoch_d_30m: 30m Stochastic D
7. wma_diff_30m: 30m WMA(8) - WMA(23) percentage
8. atr_15m: 15m ATR (volatility)
9. hour: Time of day
10. day_of_week: Day of week
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    classification_report, confusion_matrix,
    accuracy_score, f1_score
)
from sklearn.model_selection import train_test_split
import joblib
import matplotlib.pyplot as plt

# Project setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

# Setup logging
def setup_logging() -> logging.Logger:
    """Configure logging."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("ml_training_mtf")
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_dir / f"training_mtf_{datetime.now():%Y%m%d_%H%M%S}.log")
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()


def load_data(
    symbol: str,
    timeframe: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Load historical data from Parquet catalog.
    If 30_MINUTE doesn't exist, resample from 15_MINUTE.
    
    Args:
        symbol: Trading pair (e.g., "EUR-USD")
        timeframe: "15_MINUTE" or "30_MINUTE"
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    # If 30-minute data requested, resample from 15-minute
    if timeframe == "30_MINUTE":
        logger.info("Loading 15-minute data and resampling to 30-minute...")
        df_15m = load_data(symbol, "15_MINUTE", start_date, end_date)
        
        # Resample to 30-minute
        df = df_15m.resample('30min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        logger.info(f"Resampled to {len(df)} 30-minute bars")
        return df
    
    # Load from Parquet catalog
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # EUR-USD in catalog is stored as EURUSD.IDEALPRO
    instrument_id = "EURUSD.IDEALPRO"
    bar_type = f"{instrument_id}-{timeframe.replace('_', '-')}-MID-EXTERNAL"
    
    logger.info(f"Loading {bar_type} from Parquet catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type} in catalog")
    
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
    
    logger.info(f"Loaded {len(df)} bars for {symbol} {timeframe}")
    
    # Filter date range
    if start_date:
        start_ts = pd.Timestamp(start_date).tz_localize('UTC')
        df = df[df.index >= start_ts]
    
    if end_date:
        end_ts = pd.Timestamp(end_date).tz_localize('UTC')
        df = df[df.index <= end_ts]
    
    if len(df) == 0:
        raise ValueError(f"No data found for {symbol} {timeframe} in specified date range")
    
    logger.info(f"Loaded {len(df)} bars for {symbol} {timeframe}")
    return df


def calculate_features_15m(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate 15-minute features: MAMA, ATR, price momentum.
    Uses hl2 (high+low)/2 as source for MAMA (LazyBear implementation).
    """
    df = df.copy()
    
    # 1. Log Returns (scaled x100)
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    # 2. Calculate hl2 (LazyBear uses this as source)
    df['hl2'] = (df['high'] + df['low']) / 2
    
    # 3. Ehlers MAMA using hl2 source
    mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
    if mama_fama is not None:
        col_mama = mama_fama.columns[0]
        col_fama = mama_fama.columns[1]
        df['mama'] = mama_fama[col_mama]
        df['fama'] = mama_fama[col_fama]
        # Normalized difference (trend strength & direction)
        df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    # 4. ATR (14) - Normalized
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    
    # 5. Time Features
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    return df


def calculate_features_30m(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate 30-minute features: DMI, Stochastic, WMA Difference.
    """
    df = df.copy()
    
    # 1. DMI (14-period)
    dmi = ta.adx(df['high'], df['low'], df['close'], length=14)
    if dmi is not None:
        df['dmp'] = dmi['DMP_14'] / 100.0
        df['dmn'] = dmi['DMN_14'] / 100.0
    
    # 2. Stochastic (14, 3, 3)
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df['stoch_k'] = stoch['STOCHk_14_3_3'] / 100.0
        df['stoch_d'] = stoch['STOCHd_14_3_3'] / 100.0
    
    # 3. Ehlers WMA Difference (from PineScript)
    # shortMa = WMA(close, 8)
    # longMa = WMA(close, 23)
    # mad = 100 * (shortMa - longMa) / longMa
    wma_short = ta.wma(df['close'], length=8)
    wma_long = ta.wma(df['close'], length=23)
    
    if wma_short is not None and wma_long is not None:
        # Percentage difference
        df['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
    
    return df


def merge_mtf_data(df_15m: pd.DataFrame, df_30m: pd.DataFrame) -> pd.DataFrame:
    """
    Merge 15-minute and 30-minute data.
    30-minute indicators are forward-filled to align with 15-minute bars.
    
    This ensures no lookahead bias: each 15m bar uses the most recent 30m indicator value.
    """
    logger.info("Merging 15m and 30m data...")
    
    # Select only the features we need from each timeframe
    df_15m_features = df_15m[['close', 'log_ret', 'mama_diff', 'atr', 'hour', 'day_of_week']].copy()
    df_30m_features = df_30m[['dmp', 'dmn', 'stoch_k', 'stoch_d', 'wma_diff']].copy()
    
    # Rename 30m columns to indicate timeframe
    df_30m_features.columns = [f'{col}_30m' for col in df_30m_features.columns]
    
    # Merge using forward-fill (asof merge)
    # This aligns 30m indicators to 15m bars without lookahead bias
    merged = pd.merge_asof(
        df_15m_features,
        df_30m_features,
        left_index=True,
        right_index=True,
        direction='backward'  # Use most recent 30m value
    )
    
    logger.info(f"Merged data shape: {merged.shape}")
    logger.info(f"Columns: {merged.columns.tolist()}")
    
    return merged


def create_labels(
    df: pd.DataFrame,
    horizon: int = 12,  # 12 x 15min = 3 hours
    atr_multiplier: float = 1.5
) -> pd.DataFrame:
    """
    Triple Barrier Method using ATR for dynamic thresholds.
    """
    df = df.copy()
    
    df.loc[:, 'label'] = 0
    df.loc[:, 'barrier_hit'] = 'none'
    
    timestamps = df.index.tolist()
    
    for i in range(len(df) - horizon):
        current_price = df['close'].iloc[i]
        current_atr = df['atr'].iloc[i] * df['close'].iloc[i]  # De-normalize
        current_time = timestamps[i]
        
        # Dynamic barriers
        upper_barrier = current_price + (current_atr * atr_multiplier)
        lower_barrier = current_price - (current_atr * atr_multiplier)
        
        # Future prices
        future_slice = slice(i + 1, i + horizon + 1)
        future_prices = df['close'].iloc[future_slice]
        
        # Check barriers
        upper_touch = future_prices >= upper_barrier
        lower_touch = future_prices <= lower_barrier
        
        if upper_touch.any() and (not lower_touch.any() or upper_touch.idxmax() < lower_touch.idxmax()):
            df.loc[current_time, 'label'] = 1  # Buy
            df.loc[current_time, 'barrier_hit'] = 'upper'
        elif lower_touch.any() and (not upper_touch.any() or lower_touch.idxmax() < upper_touch.idxmax()):
            df.loc[current_time, 'label'] = -1  # Sell
            df.loc[current_time, 'barrier_hit'] = 'lower'
    
    return df


def prepare_training_data(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, list]:
    """
    Prepare features and labels for training.
    
    Feature order (10 total):
    1. log_ret
    2. mama_diff
    3. dmp_30m
    4. dmn_30m
    5. stoch_k_30m
    6. stoch_d_30m
    7. wma_diff_30m
    8. atr
    9. hour
    10. day_of_week
    """
    feature_columns = [
        'log_ret',
        'mama_diff',
        'dmp_30m',
        'dmn_30m',
        'stoch_k_30m',
        'stoch_d_30m',
        'wma_diff_30m',
        'atr',
        'hour',
        'day_of_week'
    ]
    
    # Remove rows with NaN (from indicator calculation)
    df_clean = df.dropna(subset=feature_columns + ['label'])
    
    # Remove neutral labels (keep only buy/sell signals)
    df_signals = df_clean[df_clean['label'] != 0].copy()
    
    # Convert sell (-1) to 0 for binary classification
    df_signals['label_binary'] = (df_signals['label'] == 1).astype(int)
    
    X = df_signals[feature_columns].values
    y = df_signals['label_binary'].values
    
    logger.info(f"Training samples: {len(X)}")
    logger.info(f"Buy signals: {(y == 1).sum()}")
    logger.info(f"Sell signals: {(y == 0).sum()}")
    
    return X, y, feature_columns


def train_model(X_train, y_train, X_test, y_test, feature_names):
    """Train HistGradientBoostingClassifier."""
    logger.info("Training model...")
    
    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=6,
        min_samples_leaf=20,
        l2_regularization=1.0,
        class_weight='balanced',
        random_state=42,
        verbose=1
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test)
    
    logger.info(f"Train accuracy: {train_score:.4f}")
    logger.info(f"Test accuracy: {test_score:.4f}")
    
    # Predictions
    y_pred = model.predict(X_test)
    
    logger.info("\nClassification Report:")
    logger.info("\n" + classification_report(y_test, y_pred, target_names=['Sell', 'Buy']))
    
    logger.info("\nConfusion Matrix:")
    logger.info("\n" + str(confusion_matrix(y_test, y_pred)))
    
    # Feature importance (HistGradientBoosting doesn't have feature_importances_)
    # Use permutation importance instead
    logger.info("\nCalculating permutation importance...")
    perm_importance = permutation_importance(model, X_test, y_test, n_repeats=10, random_state=42)
    
    logger.info("\nFeature Importances (Permutation):")
    for name, importance in zip(feature_names, perm_importance.importances_mean):
        logger.info(f"{name:20s}: {importance:.4f}")
    
    return model


def main():
    """Main training pipeline."""
    logger.info("="*80)
    logger.info("MTF ML MODEL TRAINING")
    logger.info("="*80)
    
    # Configuration
    symbol = "EUR-USD"
    train_start = "2024-01-01"  # Focus on recent 2 years
    train_end = "2025-11-28"     # Include ALL 2025 data (including November)
    
    # Step 1: Load 15-minute data
    logger.info("\n--- Loading 15-minute data ---")
    df_15m = load_data(symbol, "15_MINUTE", train_start, train_end)
    
    # Step 2: Load 30-minute data
    logger.info("\n--- Loading 30-minute data ---")
    df_30m = load_data(symbol, "30_MINUTE", train_start, train_end)
    
    # Step 3: Calculate features
    logger.info("\n--- Calculating 15m features ---")
    df_15m = calculate_features_15m(df_15m)
    
    logger.info("\n--- Calculating 30m features ---")
    df_30m = calculate_features_30m(df_30m)
    
    # Step 4: Merge timeframes
    logger.info("\n--- Merging timeframes ---")
    df_merged = merge_mtf_data(df_15m, df_30m)
    
    # Step 5: Create labels
    logger.info("\n--- Creating labels ---")
    df_labeled = create_labels(df_merged, horizon=12, atr_multiplier=1.5)
    
    # Step 6: Prepare training data
    logger.info("\n--- Preparing training data ---")
    X, y, feature_names = prepare_training_data(df_labeled)
    
    # Step 7: Train/test split (80/20, time-based)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    logger.info(f"\nTrain set: {len(X_train)} samples")
    logger.info(f"Test set: {len(X_test)} samples")
    
    # Step 8: Train model
    logger.info("\n--- Training model ---")
    model = train_model(X_train, y_train, X_test, y_test, feature_names)
    
    # Step 9: Save model
    model_path = MODELS_DIR / "ml_model_mtf.pkl"
    joblib.dump(model, model_path)
    logger.info(f"\nModel saved to: {model_path}")
    
    # Save feature names
    feature_path = MODELS_DIR / "feature_names_mtf.txt"
    with open(feature_path, 'w') as f:
        f.write('\n'.join(feature_names))
    logger.info(f"Feature names saved to: {feature_path}")
    
    logger.info("\n" + "="*80)
    logger.info("TRAINING COMPLETE")
    logger.info("="*80)


if __name__ == "__main__":
    main()
