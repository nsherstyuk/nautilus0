"""
Train seasonal models with different window lengths to test seasonal hypothesis.

Models to train:
1. Q4 Model: Sep-Oct-Nov-Dec 2024 (4 months)
2. Oct-Nov Model: Oct-Nov 2024 (2 months)

Then backtest on 2025 to compare performance.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, confusion_matrix
from joblib import dump
import sys

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

def load_data_from_catalog(start_date, end_date):
    """Load data from Parquet catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from {start_date} to {end_date}...")
    
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
    """Calculate MTF features (same as backtest)."""
    import pandas_ta as ta
    
    print("Calculating features...")
    
    # 15m features
    df['hl2'] = (df['high'] + df['low']) / 2
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
    df['mama'] = mama_fama.iloc[:, 0]
    df['fama'] = mama_fama.iloc[:, 1]
    df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    # Resample to 30m
    df_30m = df.resample('30min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # 30m indicators
    dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
    df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
    df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0
    
    stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
    df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
    df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0
    
    wma_short = ta.wma(df_30m['close'], length=8)
    wma_long = ta.wma(df_30m['close'], length=23)
    df_30m['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
    
    # Merge
    df_30m_renamed = df_30m[['dmp', 'dmn', 'stoch_k', 'stoch_d', 'wma_diff']].copy()
    df_30m_renamed.columns = ['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']
    df = df.join(df_30m_renamed, how='left')
    df = df.ffill()
    df = df.dropna()
    
    print(f"Features calculated. {len(df):,} bars remaining after dropna")
    
    return df

def create_labels(df, forward_periods=4, profit_threshold=0.0015):
    """Create labels for classification."""
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

def train_model(df, model_name):
    """Train HistGradientBoosting classifier."""
    print(f"\n{'='*80}")
    print(f"TRAINING: {model_name}")
    print(f"{'='*80}")
    
    # Feature columns - MUST match backtest exactly!
    feature_cols = [
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
    
    X = df[feature_cols]
    y = df['label']
    
    print(f"Features: {len(feature_cols)}")
    print(f"Samples: {len(X):,}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    
    # Train/validation split (80/20)
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
    
    print(f"\nTrain: {len(X_train):,} samples")
    print(f"Val:   {len(X_val):,} samples")
    
    # Train model (same parameters as current model)
    print("\nTraining HistGradientBoostingClassifier...")
    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=6,
        l2_regularization=1.0,
        random_state=42,
        class_weight='balanced',
        verbose=0
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    train_score = model.score(X_train, y_train)
    val_score = model.score(X_val, y_val)
    
    print(f"\nTrain accuracy: {train_score:.4f}")
    print(f"Val accuracy:   {val_score:.4f}")
    
    # Predictions
    y_pred = model.predict(X_val)
    
    print("\nClassification Report (Validation):")
    print(classification_report(y_val, y_pred, target_names=['HOLD', 'BUY']))
    
    return model, feature_cols

def main():
    print("="*80)
    print("SEASONAL MODEL TRAINING")
    print("="*80)
    
    models_to_train = [
        {
            'name': 'Q4_Model',
            'start': '2024-09-01',
            'end': '2025-01-01',
            'description': 'Sep-Oct-Nov-Dec 2024 (4 months)',
            'output': 'models/ml_model_mtf_q4_2024.pkl'
        },
        {
            'name': 'Oct_Nov_Model',
            'start': '2024-10-01',
            'end': '2024-12-01',
            'description': 'Oct-Nov 2024 (2 months)',
            'output': 'models/ml_model_mtf_oct_nov_2024.pkl'
        }
    ]
    
    for model_config in models_to_train:
        print(f"\n{'='*80}")
        print(f"MODEL: {model_config['name']}")
        print(f"Training Period: {model_config['description']}")
        print(f"{'='*80}")
        
        # Load data
        df = load_data_from_catalog(model_config['start'], model_config['end'])
        
        # Calculate features
        df = calculate_features(df)
        
        # Create labels
        df = create_labels(df)
        
        # Train model
        model, feature_cols = train_model(df, model_config['name'])
        
        # Save model
        output_path = PROJECT_ROOT / model_config['output']
        output_path.parent.mkdir(exist_ok=True)
        dump(model, output_path)
        print(f"\n✅ Model saved to: {output_path}")
        
        # Save feature list
        feature_list_path = output_path.parent / f"{model_config['name']}_features.txt"
        with open(feature_list_path, 'w') as f:
            f.write('\n'.join(feature_cols))
        print(f"✅ Feature list saved to: {feature_list_path}")
    
    print("\n" + "="*80)
    print("TRAINING COMPLETE!")
    print("="*80)
    print("\nNext step: Run backtest comparison")
    print("Command: python test_seasonal_models.py")

if __name__ == "__main__":
    main()
