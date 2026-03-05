#!/usr/bin/env python3
"""
Train a Machine Learning model for forex trading.
Implements feature engineering that matches the live strategy exactly.

Key Components:
1. Feature Engineering using pandas-ta (matches live strategy)
2. Dynamic Triple Barrier Labeling with ATR-based thresholds
3. Random Forest training with proper validation
"""
import logging
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

import numpy as np
import pandas as pd
import pandas_ta as ta  # Exact same library as strategy
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_curve, auc, precision_recall_curve,
    accuracy_score, f1_score
)
from sklearn.model_selection import train_test_split, TimeSeriesSplit, cross_val_score
from sklearn.model_selection import RandomizedSearchCV
from scipy.stats import randint, uniform
import joblib
import matplotlib.pyplot as plt

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

# Setup logging
def setup_logging() -> logging.Logger:
    """Configure logging with both file and console output."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("ml_training")
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_dir / f"training_{datetime.now():%Y%m%d_%H%M%S}.log")
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

def load_m5_data(
    symbol: str = "EUR-USD",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Load 5-minute historical data for training.
    Matches the format used in live trading.
    
    Args:
        symbol: Trading pair (e.g., "EUR-USD")
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    data_path = PROJECT_ROOT / "data" / "historical" / f"{symbol}_{symbol.replace('-', '_')}_IDEALPRO_5_MINUTE_MID_EXTERNAL.csv"
    
    if not data_path.exists():
        raise FileNotFoundError(f"No data file found at {data_path}")
        
    # Load data
    df = pd.read_csv(data_path)
    # Force UTC to ensure consistent DatetimeIndex
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    
    # Ensure index is sorted
    df.sort_index(inplace=True)
    
    # Filter date range
    if start_date:
        # Convert start_date to UTC for comparison
        start_ts = pd.Timestamp(start_date).tz_localize('UTC')
        df = df[df.index >= start_ts]
        
    if end_date:
        # Convert end_date to UTC for comparison
        end_ts = pd.Timestamp(end_date).tz_localize('UTC')
        df = df[df.index <= end_ts]
        
    if len(df) == 0:
        raise ValueError(f"No data found for {symbol} in specified date range")
        
    # Basic data quality checks
    if df['close'].isnull().any():
        logger.warning("Found NULL values in close prices!")
    if (df['high'] < df['low']).any():
        logger.error("Data integrity error: high < low!")
        
    logger.info(f"Loaded {len(df)} bars for {symbol}")
    return df

def filter_trading_session(
    df: pd.DataFrame,
    session_start: str = "02:00",  # London pre-session
    session_end: str = "16:00",    # NY close
    excluded_hours: Optional[list[int]] = None
) -> pd.DataFrame:
    """Filter for specific trading sessions."""
    # Convert times to datetime.time
    start_time = datetime.strptime(session_start, "%H:%M").time()
    end_time = datetime.strptime(session_end, "%H:%M").time()
    
    # Session filter
    mask = (df.index.time >= start_time) & (df.index.time <= end_time)
    
    # Exclude specific hours
    if excluded_hours:
        hour_mask = ~df.index.hour.isin(excluded_hours)
        mask = mask & hour_mask
    
    filtered_df = df[mask].copy()
    logger.info(f"Filtered {len(df) - len(filtered_df)} bars outside trading session")
    return filtered_df

def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate features using pandas-ta with Ehlers MAMA, DMI, and Stochastic.
    CRITICAL: This must match the live strategy's _calculate_features method exactly.
    """
    df = df.copy()
    
    # 1. Log Returns (scaled x100)
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    # 2. Ehlers MAMA (MESA Adaptive Moving Average)
    # fast=0.5, slow=0.05 per LazyBear's PineScript defaults
    mama_fama = ta.mama(df['close'], fast=0.5, slow=0.05)
    # pandas-ta naming convention: MAMA_0.5_0.05, FAMA_0.5_0.05
    # We use column access by position or name. Let's verify names usually.
    # But to be safe with version differences, we can rename if needed or access carefully.
    # ta.mama returns a DataFrame.
    if mama_fama is not None:
        col_mama = mama_fama.columns[0]
        col_fama = mama_fama.columns[1]
        df['mama'] = mama_fama[col_mama]
        df['fama'] = mama_fama[col_fama]
        # Feature: Normalized Difference (Trend Strength & Direction)
        df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    # 3. DMI (ADX, DI+, DI-)
    # length=14 is standard
    dmi = ta.adx(df['high'], df['low'], df['close'], length=14)
    if dmi is not None:
        # ADX_14, DMP_14, DMN_14
        df['adx'] = dmi['ADX_14'] / 100.0
        df['dmp'] = dmi['DMP_14'] / 100.0
        df['dmn'] = dmi['DMN_14'] / 100.0
        
    # 4. Stochastic (14, 3, 3)
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df['stoch_k'] = stoch['STOCHk_14_3_3'] / 100.0
        df['stoch_d'] = stoch['STOCHd_14_3_3'] / 100.0
    
    # 5. ATR (14) - Normalized
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    
    # 6. Time Features
    # Hour of day (0-23)
    df['hour'] = df.index.hour
    # Day of week (0-6, Monday=0)
    df['day_of_week'] = df.index.dayofweek
    
    return df

def create_labels(
    df: pd.DataFrame,
    horizon: int = 12,  # 1 hour (12 x 5min bars)
    atr_multiplier: float = 1.5
) -> pd.DataFrame:
    """
    Implement Triple Barrier Method using ATR for dynamic thresholds.
    
    Args:
        df: DataFrame with 'close' and 'atr' columns
        horizon: Number of bars to look ahead
        atr_multiplier: ATR multiplier for barriers
    """
    # Create a copy to avoid SettingWithCopyWarning
    df = df.copy()
    
    # Initialize labels and metadata
    df.loc[:, 'label'] = 0  # Default: no signal
    df.loc[:, 'barrier_hit'] = 'none'  # Track which barrier was hit
    df.loc[:, 'bars_to_exit'] = -1    # Track how many bars until exit
    
    # Get all timestamps for bar counting
    timestamps = df.index.tolist()
    
    for i in range(len(df) - horizon):
        current_price = df['close'].iloc[i]
        current_atr = df['atr'].iloc[i] * df['close'].iloc[i]  # De-normalize ATR
        current_time = timestamps[i]
        
        # Dynamic barriers based on ATR
        upper_barrier = current_price + (current_atr * atr_multiplier)
        lower_barrier = current_price - (current_atr * atr_multiplier)
        
        # Get future prices for next 'horizon' bars
        future_slice = slice(i + 1, i + horizon + 1)
        future_prices = df['close'].iloc[future_slice]
        future_times = timestamps[i + 1:i + horizon + 1]
        
        # Check which barrier is hit first
        upper_touch = future_prices >= upper_barrier
        lower_touch = future_prices <= lower_barrier
        
        if upper_touch.any() and (not lower_touch.any() or upper_touch.idxmax() < lower_touch.idxmax()):
            # Buy signal
            df.loc[current_time, 'label'] = 1
            df.loc[current_time, 'barrier_hit'] = 'upper'
            # Count bars until exit
            exit_time = future_prices[upper_touch].index[0]
            bars_to_exit = future_times.index(exit_time)
            df.loc[current_time, 'bars_to_exit'] = bars_to_exit
            
        elif lower_touch.any() and (not upper_touch.any() or lower_touch.idxmax() < upper_touch.idxmax()):
            # Sell signal
            df.loc[current_time, 'label'] = -1
            df.loc[current_time, 'barrier_hit'] = 'lower'
            # Count bars until exit
            exit_time = future_prices[lower_touch].index[0]
            bars_to_exit = future_times.index(exit_time)
            df.loc[current_time, 'bars_to_exit'] = bars_to_exit
        else:
            # No barrier hit (vertical barrier)
            df.loc[current_time, 'barrier_hit'] = 'vertical'
            df.loc[current_time, 'bars_to_exit'] = horizon
            
    return df

def analyze_label_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze the distribution of labels and barriers."""
    stats = {
        'total_samples': len(df),
        'buy_signals': (df['label'] == 1).sum(),
        'sell_signals': (df['label'] == -1).sum(),
        'neutral': (df['label'] == 0).sum(),
        'barrier_distribution': df['barrier_hit'].value_counts().to_dict(),
        'avg_bars_to_exit': df[df['bars_to_exit'] >= 0]['bars_to_exit'].mean()
    }
    
    # Calculate percentages
    total = len(df)
    stats['buy_pct'] = stats['buy_signals'] / total * 100
    stats['sell_pct'] = stats['sell_signals'] / total * 100
    stats['neutral_pct'] = stats['neutral'] / total * 100
    
    return stats

def plot_model_metrics(
    model: HistGradientBoostingClassifier,
    X_test: np.ndarray,
    y_test: np.ndarray,
    output_dir: Path
) -> None:
    """Generate and save model performance plots."""
    # 1. ROC Curve
    y_pred_proba = model.predict_proba(X_test)
    
    plt.figure(figsize=(10, 6))
    for i, label in enumerate(['neutral', 'buy', 'sell']):
        fpr, tpr, _ = roc_curve(y_test == i, y_pred_proba[:, i])
        plt.plot(fpr, tpr, label=f'{label} (AUC = {auc(fpr, tpr):.2f})')
    
    plt.plot([0, 1], [0, 1], 'k--')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curves')
    plt.legend()
    plt.savefig(output_dir / 'roc_curves.png')
    plt.close()
    
    # 2. Precision-Recall Curve
    plt.figure(figsize=(10, 6))
    for i, label in enumerate(['neutral', 'buy', 'sell']):
        precision, recall, _ = precision_recall_curve(y_test == i, y_pred_proba[:, i])
        plt.plot(recall, precision, label=f'{label}')
    
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title('Precision-Recall Curves')
    plt.legend()
    plt.savefig(output_dir / 'precision_recall_curves.png')
    plt.close()
    
    # 3. Feature Importance (using Permutation Importance for HGB)
    feature_cols = ['log_ret', 'mama_diff', 'adx', 'dmp', 'dmn', 'stoch_k', 'stoch_d', 'atr', 'hour', 'day_of_week']
    
    # Calculate permutation importance
    result = permutation_importance(model, X_test, y_test, n_repeats=10, random_state=42, n_jobs=-1)
    
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': result.importances_mean
    }).sort_values('importance', ascending=True)
    
    plt.figure(figsize=(10, 6))
    importance.plot(kind='barh', x='feature', y='importance')
    plt.title('Feature Importance (Permutation)')
    plt.tight_layout()
    plt.savefig(output_dir / 'feature_importance.png')
    plt.close()

def evaluate_period(model: HistGradientBoostingClassifier, X: np.ndarray, y: np.ndarray, period_name: str) -> None:
    """Evaluate model performance on a specific period."""
    y_pred = model.predict(X)
    y_pred_proba = model.predict_proba(X)
    
    # Classification report
    logger.info(f"\n{period_name} Period Classification Report:")
    logger.info("\n" + classification_report(y, y_pred))
    
    # Class-wise probabilities
    class_probs = {
        'sell': y_pred_proba[:, 0].mean(),
        'neutral': y_pred_proba[:, 1].mean(),
        'buy': y_pred_proba[:, 2].mean()
    }
    logger.info(f"\n{period_name} Average Prediction Probabilities:")
    for cls, prob in class_probs.items():
        logger.info(f"  {cls}: {prob:.3f}")
    
    # Confusion matrix
    cm = confusion_matrix(y, y_pred)
    logger.info(f"\n{period_name} Confusion Matrix:")
    logger.info("\n" + str(cm))

def main():
    try:
        # 1. Load and prepare data (2023-2024 as specified in brief)
        logger.info("Loading 2023-2024 training data...")
        train_df = load_m5_data(
            start_date="2023-01-01",
            end_date="2024-12-31"
        )
        
        # 2. Load validation data (2025-05-01 to 2025-10-30)
        logger.info("Loading validation data...")
        valid_df = load_m5_data(
            start_date="2025-05-01",
            end_date="2025-10-30"
        )
        
        # 2. Filter trading sessions for both datasets
        logger.info("Filtering trading sessions...")
        train_df = filter_trading_session(train_df, excluded_hours=[0, 1])
        valid_df = filter_trading_session(valid_df, excluded_hours=[0, 1])
        
        # 3. Calculate features for both datasets
        train_df = calculate_features(train_df)
        valid_df = calculate_features(valid_df)
        
        # 4. Create labels for both datasets
        train_df = create_labels(train_df)
        valid_df = create_labels(valid_df)
        
        # 5. Analyze label distributions
        train_stats = analyze_label_distribution(train_df)
        valid_stats = analyze_label_distribution(valid_df)
        
        logger.info("Training Data Distribution:")
        for k, v in train_stats.items():
            logger.info(f"  {k}: {v}")
            
        logger.info("\nValidation Data Distribution:")
        for k, v in valid_stats.items():
            logger.info(f"  {k}: {v}")
        
        # 6. Prepare features and targets
        feature_cols = ['log_ret', 'mama_diff', 'adx', 'dmp', 'dmn', 'stoch_k', 'stoch_d', 'atr', 'hour', 'day_of_week']
        
        # Training data
        train_df = train_df.dropna(subset=feature_cols + ['label'])
        X_train = train_df[feature_cols].values
        y_train = train_df['label'].values
        
        # Validation data
        valid_df = valid_df.dropna(subset=feature_cols + ['label'])
        X_valid = valid_df[feature_cols].values
        y_valid = valid_df['label'].values
        
        # 7. Define parameter search space for HistGradientBoostingClassifier
        param_dist = {
            'learning_rate': uniform(0.01, 0.1),   # Step size shrinking
            'max_iter': randint(100, 500),         # Number of trees
            'max_leaf_nodes': randint(15, 63),     # Max leaves per tree
            'min_samples_leaf': randint(20, 100),  # Regularization
            'l2_regularization': uniform(0.0, 10.0), # L2 regularization
            'max_bins': randint(50, 255)           # Binning for speed/generalization
        }
        
        # 8. Train with RandomizedSearchCV (on training data only)
        logger.info("Starting RandomizedSearchCV with HistGradientBoostingClassifier...")
        base_model = HistGradientBoostingClassifier(random_state=42, class_weight='balanced')
        search = RandomizedSearchCV(
            base_model,
            param_distributions=param_dist,
            n_iter=20,
            cv=TimeSeriesSplit(n_splits=5),
            scoring='f1_weighted',
            n_jobs=-1,
            verbose=2,
            random_state=42
        )
        
        search.fit(X_train, y_train)
        
        # Log best parameters
        logger.info("Best parameters found:")
        for param, value in search.best_params_.items():
            logger.info(f"  {param}: {value}")
        logger.info(f"Best cross-validation score: {search.best_score_:.3f}")
        
        # Get the best model
        model = search.best_estimator_
        
        # 9. Evaluate on both periods
        logger.info("\nEvaluating model performance...")
        evaluate_period(model, X_train, y_train, "Training")
        evaluate_period(model, X_valid, y_valid, "Validation")
        
        # 10. Generate plots using validation data
        plot_model_metrics(model, X_valid, y_valid, MODELS_DIR)
        
        # 11. Save model and metadata
        model_path = MODELS_DIR / "strategy_model.joblib"
        joblib.dump(model, model_path)
        
        # Save training metadata
        def convert_to_serializable(obj):
            """Convert numpy/pandas types to Python native types."""
            if isinstance(obj, (np.int8, np.int16, np.int32, np.int64,
                              np.uint8, np.uint16, np.uint32, np.uint64)):
                return int(obj)
            elif isinstance(obj, (np.float16, np.float32, np.float64)):
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {key: convert_to_serializable(value) for key, value in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_serializable(x) for x in obj]
            return obj

        metadata = {
            'training_date': datetime.now().isoformat(),
            'training_period': {
                'start': train_df.index[0].isoformat(),
                'end': train_df.index[-1].isoformat(),
                'n_samples': len(train_df)
            },
            'validation_period': {
                'start': valid_df.index[0].isoformat(),
                'end': valid_df.index[-1].isoformat(),
                'n_samples': len(valid_df)
            },
            'feature_columns': feature_cols,
            'model_params': convert_to_serializable(model.get_params()),
            'training_distribution': convert_to_serializable(train_stats),
            'validation_distribution': convert_to_serializable(valid_stats),
            'performance': {
                'best_cv_score': float(search.best_score_),
                'training_metrics': {
                    'accuracy': float(accuracy_score(y_train, model.predict(X_train))),
                    'f1_weighted': float(f1_score(y_train, model.predict(X_train), average='weighted'))
                },
                'validation_metrics': {
                    'accuracy': float(accuracy_score(y_valid, model.predict(X_valid))),
                    'f1_weighted': float(f1_score(y_valid, model.predict(X_valid), average='weighted'))
                }
            }
        }
        
        with open(MODELS_DIR / "model_metadata.json", "w") as f:
            import json
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Training complete. Model and metadata saved to {MODELS_DIR}")
        
    except Exception as e:
        logger.error(f"Training failed: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
