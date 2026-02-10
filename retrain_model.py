"""
Retrain ML model with recent data to address performance degradation.

Training period: Configurable (default: 12 months before October 2025)
Target: Predict profitable trading opportunities on EUR/USD 15-minute bars
"""
import pandas as pd
import numpy as np
from pathlib import Path
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
from joblib import dump
import warnings
warnings.filterwarnings('ignore')

from strategies.feature_engineering_v3 import compute_v3_features, FEATURE_COLUMNS_V3

# Configuration
TRAINING_MONTHS = 24  # How many months of data to use
TRAIN_END_DATE = '2026-02-09'  # Train up to (but not including) this date
MIN_SAMPLES = 10000  # Minimum samples needed for training

# Profit threshold for labeling (based on 2025 data analysis)
# 0.0007 = 0.07% = ~7 pips for EUR/USD
# Analysis showed: 33.9% positive class, 22.8 signals/day
# Previous: 0.0015 (0.15% / 16.5 pips) - only 10.8% positive class
PROFIT_THRESHOLD = 0.0007

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
    """Calculate V3 features with directional predictive power."""
    print("Calculating V3 features...")
    
    ohlcv = df[["open", "high", "low", "close", "volume"]].copy()
    feats = compute_v3_features(ohlcv)
    
    # Merge features back with OHLCV (needed for labeling)
    result = df[["open", "high", "low", "close", "volume"]].copy()
    for col in feats.columns:
        result[col] = feats[col]
    
    # Drop NaN values
    result = result.dropna()
    
    print(f"V3 features calculated: {len(FEATURE_COLUMNS_V3)} features, {len(result):,} bars remaining after dropna")
    
    return result

def create_labels(df, forward_periods=4, profit_threshold=0.0015):
    """
    Symmetric directional labeling.
    
    Label = 1 (LONG) if forward upside > forward downside
    Label = 0 (SHORT) if forward downside > forward upside
    Ties are dropped.
    
    profit_threshold is unused but kept for API compatibility.
    """
    print(f"Creating directional labels (forward_periods={forward_periods})...")
    
    df = df.copy()
    
    # Calculate forward price extremes
    df['forward_high'] = df['high'].rolling(forward_periods).max().shift(-forward_periods)
    df['forward_low'] = df['low'].rolling(forward_periods).min().shift(-forward_periods)
    
    # Remove rows where we can't calculate forward returns
    df = df.dropna(subset=['forward_high', 'forward_low'])
    
    # Symmetric directional: which way does price move more?
    upside = df['forward_high'] - df['close']
    downside = df['close'] - df['forward_low']
    
    # Label = 1 if upside > downside (LONG), 0 if downside > upside (SHORT)
    df['label'] = (upside > downside).astype(int)
    
    # Drop exact ties
    ties = upside == downside
    n_ties = ties.sum()
    df = df[~ties].copy()
    
    print(f"Labels created (symmetric directional). Class distribution:")
    print(df['label'].value_counts())
    print(f"LONG class: {df['label'].sum() / len(df) * 100:.1f}%")
    print(f"SHORT class: {(1 - df['label']).sum() / len(df) * 100:.1f}%")
    if n_ties > 0:
        print(f"Dropped {n_ties} tied bars")
    
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
    print("\nTraining XGBoost...")
    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,       # L1 regularization
        reg_lambda=1.0,      # L2 regularization
        min_child_weight=20,
        gamma=0.1,           # Min loss reduction for split
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss',
        early_stopping_rounds=30,
    )
    
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    
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
    print(classification_report(y_val, y_pred, target_names=['SHORT', 'LONG']))
    
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
    df = create_labels(df, forward_periods=4, profit_threshold=PROFIT_THRESHOLD)
    
    # Train model
    print("\n" + "-"*80)
    model, feature_cols = train_model(df)
    
    # Save model
    print("\n" + "="*80)
    print("SAVING MODEL")
    print("="*80)
    
    model_path = PROJECT_ROOT / "models" / "ml_model_mtf_v3_xgb.pkl"
    model_path.parent.mkdir(exist_ok=True)
    
    dump(model, model_path)
    print(f"New V3 model saved to: {model_path}")
    
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
