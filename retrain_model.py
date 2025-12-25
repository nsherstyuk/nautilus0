"""
Retrain ML model with recent data to address performance degradation.

Training period: Configurable (default: 12 months before October 2025)
Target: Predict profitable trading opportunities on EUR/USD 15-minute bars
"""
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
from joblib import dump
import warnings
warnings.filterwarnings('ignore')

# Configuration
TRAINING_MONTHS = 24  # How many months of data to use
TRAIN_END_DATE = '2026-01-01'  # Train up to (but not including) this date
MIN_SAMPLES = 10000  # Minimum samples needed for training

PROJECT_ROOT = Path(__file__).parent

def load_data_from_catalog(start_date, end_date):
    """Load data from Parquet catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from Parquet catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise ValueError(f"No data found for {bar_type}")
    
    # Convert to DataFrame
    df = pd.DataFrame({
        'timestamp': [bar.ts_init for bar in bars],
        'open': [float(bar.open) for bar in bars],
        'high': [float(bar.high) for bar in bars],
        'low': [float(bar.low) for bar in bars],
        'close': [float(bar.close) for bar in bars],
        'volume': [float(bar.volume) for bar in bars],
    })
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ns', utc=True)
    df = df.set_index('timestamp').sort_index()
    
    # Filter date range
    df = df[(df.index >= start_date) & (df.index < end_date)]
    
    print(f"Loaded {len(df):,} bars from {df.index.min()} to {df.index.max()}")
    
    return df

def calculate_features(df):
    """Calculate technical indicators and features (same as backtest)."""
    print("Calculating features...")
    
    # Price changes
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
    
    # Moving averages
    for period in [10, 20, 50]:
        df[f'sma_{period}'] = df['close'].rolling(period).mean()
        df[f'price_to_sma_{period}'] = df['close'] / df[f'sma_{period}']
    
    # Exponential moving averages
    for period in [12, 26]:
        df[f'ema_{period}'] = df['close'].ewm(span=period).mean()
    
    # MACD
    df['macd'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_diff'] = df['macd'] - df['macd_signal']
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
    df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    # ATR (Average True Range)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['tr'].rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close']
    
    # Volatility
    df['volatility'] = df['returns'].rolling(20).std()
    
    # Volume features
    df['volume_sma'] = df['volume'].rolling(20).mean()
    # Handle division by zero if volume is 0
    df['volume_ratio'] = np.where(df['volume_sma'] > 0, df['volume'] / df['volume_sma'], 0.0)
    
    # Price momentum
    for period in [5, 10, 20]:
        df[f'momentum_{period}'] = df['close'] - df['close'].shift(period)
        df[f'roc_{period}'] = df['close'].pct_change(period)
    
    # Candle patterns
    df['body'] = abs(df['close'] - df['open'])
    df['upper_shadow'] = df['high'] - np.maximum(df['open'], df['close'])
    df['lower_shadow'] = np.minimum(df['open'], df['close']) - df['low']
    df['body_to_range'] = df['body'] / (df['high'] - df['low'])
    
    # Time features
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    df['is_london_session'] = ((df['hour'] >= 8) & (df['hour'] < 16)).astype(int)
    df['is_ny_session'] = ((df['hour'] >= 13) & (df['hour'] < 21)).astype(int)
    df['is_overlap'] = ((df['hour'] >= 13) & (df['hour'] < 16)).astype(int)
    
    # Drop NaN values
    df = df.dropna()
    
    print(f"Features calculated. {len(df):,} bars remaining after dropna")
    
    return df

def create_labels(df, forward_periods=4, profit_threshold=0.0015):
    """
    Create labels for classification.
    
    Label = 1 (BUY) if price goes up by profit_threshold within forward_periods
    Label = 0 (SELL/HOLD) otherwise
    """
    print(f"Creating labels (forward_periods={forward_periods}, threshold={profit_threshold})...")
    
    df = df.copy()
    
    # Calculate forward returns
    df['forward_high'] = df['high'].rolling(forward_periods).max().shift(-forward_periods)
    df['forward_low'] = df['low'].rolling(forward_periods).min().shift(-forward_periods)
    
    # Label: 1 if profitable long opportunity, 0 otherwise
    df['label'] = ((df['forward_high'] - df['close']) / df['close'] >= profit_threshold).astype(int)
    
    # Remove rows where we can't calculate forward returns
    df = df.dropna(subset=['forward_high', 'forward_low', 'label'])
    
    print(f"Labels created. Class distribution:")
    print(df['label'].value_counts())
    print(f"Positive class: {df['label'].sum() / len(df) * 100:.1f}%")
    
    return df

def train_model(df):
    """Train Random Forest classifier."""
    print("\nPreparing training data...")
    
    # Feature columns (exclude target and helper columns)
    exclude_cols = ['label', 'forward_high', 'forward_low', 'open', 'high', 'low', 'close', 'volume']
    feature_cols = [col for col in df.columns if col not in exclude_cols]
    
    X = df[feature_cols]
    y = df['label']
    
    print(f"Features: {len(feature_cols)}")
    print(f"Samples: {len(X):,}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    
    # Train/validation split (time-based)
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
    
    print(f"\nTrain: {len(X_train):,} samples ({df.index[0]} to {df.index[split_idx-1]})")
    print(f"Val:   {len(X_val):,} samples ({df.index[split_idx]} to {df.index[-1]})")
    
    # Train model
    print("\nTraining Random Forest...")
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=50,
        min_samples_leaf=20,
        max_features='sqrt',
        random_state=42,
        n_jobs=-1,
        class_weight='balanced'
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    print("\n" + "="*80)
    print("MODEL EVALUATION")
    print("="*80)
    
    train_score = model.score(X_train, y_train)
    val_score = model.score(X_val, y_val)
    
    print(f"\nTrain accuracy: {train_score:.4f}")
    print(f"Val accuracy:   {val_score:.4f}")
    
    # Predictions
    y_pred = model.predict(X_val)
    y_pred_proba = model.predict_proba(X_val)[:, 1]
    
    print("\nClassification Report (Validation):")
    print(classification_report(y_val, y_pred, target_names=['HOLD', 'BUY']))
    
    print("\nConfusion Matrix:")
    print(confusion_matrix(y_val, y_pred))
    
    # Feature importance
    print("\nTop 20 Most Important Features:")
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    print(feature_importance.head(20).to_string(index=False))
    
    # Test at different confidence thresholds
    print("\n" + "="*80)
    print("PERFORMANCE AT DIFFERENT CONFIDENCE THRESHOLDS")
    print("="*80)
    
    for threshold in [0.50, 0.55, 0.60, 0.65, 0.70]:
        pred_at_threshold = (y_pred_proba >= threshold).astype(int)
        if pred_at_threshold.sum() > 0:
            precision = (y_val[pred_at_threshold == 1] == 1).sum() / pred_at_threshold.sum()
            coverage = pred_at_threshold.sum() / len(y_val)
            print(f"Threshold {threshold:.2f}: Precision={precision:.3f}, Coverage={coverage:.3f} ({pred_at_threshold.sum()} trades)")
    
    return model, feature_cols

def main():
    print("="*80)
    print("MODEL RETRAINING SCRIPT")
    print("="*80)
    
    # Calculate training period
    train_end = pd.Timestamp(TRAIN_END_DATE).tz_localize('UTC')
    train_start = train_end - pd.DateOffset(months=TRAINING_MONTHS)
    
    print(f"\nTraining period: {train_start.strftime('%Y-%m-%d')} to {train_end.strftime('%Y-%m-%d')}")
    print(f"Duration: {TRAINING_MONTHS} months")
    
    # Load data
    print("\n" + "-"*80)
    df = load_data_from_catalog(train_start, train_end)
    
    if len(df) < MIN_SAMPLES:
        print(f"\n❌ ERROR: Not enough data! Got {len(df)} samples, need at least {MIN_SAMPLES}")
        print("Try increasing TRAINING_MONTHS or check data availability")
        return
    
    # Calculate features
    print("\n" + "-"*80)
    df = calculate_features(df)
    
    # Create labels
    print("\n" + "-"*80)
    df = create_labels(df)
    
    # Train model
    print("\n" + "-"*80)
    model, feature_cols = train_model(df)
    
    # Save model
    print("\n" + "="*80)
    print("SAVING MODEL")
    print("="*80)
    
    model_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    model_path.parent.mkdir(exist_ok=True)
    
    # Backup old model
    if model_path.exists():
        backup_path = PROJECT_ROOT / "models" / "ml_model_mtf_backup.pkl"
        import shutil
        shutil.copy(model_path, backup_path)
        print(f"✅ Old model backed up to: {backup_path}")
    
    dump(model, model_path)
    print(f"✅ New model saved to: {model_path}")
    
    # Save feature list for reference
    feature_list_path = PROJECT_ROOT / "models" / "feature_list.txt"
    with open(feature_list_path, 'w') as f:
        f.write('\n'.join(feature_cols))
    print(f"✅ Feature list saved to: {feature_list_path}")
    
    print("\n" + "="*80)
    print("RETRAINING COMPLETE!")
    print("="*80)
    print("\nNext steps:")
    print("1. Run backtest with new model: python run_mtf_backtest_detailed.py")
    print("2. Compare performance with old model")
    print("3. If satisfied, deploy to live trading")

if __name__ == "__main__":
    main()
