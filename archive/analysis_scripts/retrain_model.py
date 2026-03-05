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
TRAINING_MONTHS = 12  # How many months of data to use
TRAIN_END_DATE = '2024-12-31'  # Train up to (but not including) this date
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
    
    # DEDUPLICATE: Drop duplicate timestamps (keep last)
    original_len = len(df)
    df = df.drop_duplicates(subset=['timestamp'], keep='last')
    if len(df) < original_len:
        print(f"Dropped {original_len - len(df)} duplicate bars.")
        
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

def create_labels(df, sl_mult=1.8, tp1_mult=1.4, forward_bars=60, atr_period=14):
    """
    SL/TP-aware directional labeling.

    Simulates a long entry at each bar's close price:
      - TP1 = close + atr * tp1_mult
      - SL  = close - atr * sl_mult

    Label = 1 if a forward bar's HIGH reaches TP1 before any forward bar's LOW
               reaches SL  (LONG trade would have been profitable).
    Label = 0 if a forward bar's LOW  reaches SL  before TP1 is reached
               (SHORT trade would have been profitable by symmetry).
    Bars where neither level is reached within forward_bars, or where both are
    hit on the same candle (ambiguous), are dropped.

    ATR uses a simple 14-period rolling mean of True Range, matching the live
    strategy exactly  (ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py).
    """
    print(f"Creating SL/TP-aware labels "
          f"(sl_mult={sl_mult}, tp1_mult={tp1_mult}, "
          f"forward_bars={forward_bars}, atr_period={atr_period})...")

    df = df.copy()

    # --- ATR (simple rolling mean of TR — matches live strategy) ---
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low']  - df['close'].shift(1)).abs(),
        ),
    )
    atr = tr.rolling(atr_period).mean()
    df['_atr'] = atr
    df = df.dropna(subset=['_atr'])

    c = df['close'].values
    h = df['high'].values
    lo = df['low'].values
    a = df['_atr'].values
    n = len(c)

    tp_level = c + a * tp1_mult   # LONG TP1
    sl_level = c - a * sl_mult    # LONG SL (== SHORT TP1)

    labels = np.full(n, -1, dtype=np.int8)   # -1 = unresolved

    for fwd in range(1, forward_bars + 1):
        unresolved = labels == -1
        if not unresolved.any():
            break
        idx = np.arange(n)
        valid = (idx + fwd) < n
        future_h = np.where(valid, h[np.minimum(idx + fwd, n - 1)], np.nan)
        future_l = np.where(valid, lo[np.minimum(idx + fwd, n - 1)], np.nan)

        tp_hit = unresolved & valid & (future_h >= tp_level)
        sl_hit = unresolved & valid & (future_l <= sl_level)

        labels[tp_hit & sl_hit]   = -2   # both on same bar → ambiguous, drop
        labels[tp_hit & ~sl_hit]  =  1   # TP reached first
        labels[sl_hit & ~tp_hit]  =  0   # SL reached first

    df['label'] = labels
    n_unresolved = int((labels == -1).sum())
    n_ambiguous  = int((labels == -2).sum())
    df = df[(df['label'] == 0) | (df['label'] == 1)].copy()
    df['label'] = df['label'].astype(int)

    print(f"Labels created (SL/TP-aware). "
          f"{len(df)} usable bars "
          f"({n_unresolved} unresolved/expired, {n_ambiguous} ambiguous dropped).")
    print(f"Class distribution:")
    print(df['label'].value_counts())
    print(f"LONG (TP1 first):  {df['label'].sum() / len(df) * 100:.1f}%")
    print(f"SHORT (SL first):  {(1 - df['label']).sum() / len(df) * 100:.1f}%")

    return df

def train_model(df):
    """Train Random Forest classifier."""
    print("\nPreparing training data...")
    
    # Feature columns (exclude target and helper columns)
    # _atr is a labeling helper; forward_high/forward_low kept for compat (no-op if absent)
    exclude_cols = {'label', 'forward_high', 'forward_low', '_atr',
                    'open', 'high', 'low', 'close', 'volume'}
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
    
    # Walk-forward cross-validation (3 folds)
    print("\nWalk-forward cross-validation (3 folds)...")
    tscv = TimeSeriesSplit(n_splits=3)
    cv_model = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=1.0,
        min_child_weight=20, gamma=0.1,
        random_state=42, n_jobs=-1, eval_metric='logloss',
    )
    cv_scores = cross_val_score(cv_model, X, y, cv=tscv, scoring='accuracy')
    print(f"Walk-forward CV accuracies: {[f'{s:.3f}' for s in cv_scores]}")
    print(f"Mean: {cv_scores.mean():.3f}  Std: {cv_scores.std():.3f}")

    # Train final model on full train split
    print("\nTraining final XGBoost (max_depth=4)...")
    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,           # reduced from 6 to close train/val gap
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        min_child_weight=20,
        gamma=0.1,
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
    df = create_labels(df, sl_mult=1.8, tp1_mult=1.4, forward_bars=60)
    
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
