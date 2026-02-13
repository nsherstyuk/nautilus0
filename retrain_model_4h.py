"""
Train 4H Higher Timeframe (HTF) confirmation model.

This model predicts the dominant trend direction over the next 1-2 days
using 4-hour bars. It is used as a directional filter for the primary
15-minute trading model.

Training data: 15m bars resampled to 4H
Labels: Symmetric directional (same approach as 15m model, but with
        forward_periods=6 = 24 hours lookahead on 4H bars)
"""
import pandas as pd
import numpy as np
from pathlib import Path
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix
from joblib import dump
import warnings
warnings.filterwarnings('ignore')

from strategies.feature_engineering_4h import compute_4h_features, FEATURE_COLUMNS_4H

# Configuration
TRAINING_MONTHS = 24
TRAIN_END_DATE = '2026-02-09'
MIN_SAMPLES = 500  # 4H bars: ~6 bars/day × 260 trading days ≈ 1560 bars for 12 months

# Forward lookahead for labeling (in 4H bars)
# 6 bars = 24 hours = captures the next-day trend direction
FORWARD_PERIODS = 6

PROJECT_ROOT = Path(__file__).parent


def load_15m_data(start_date, end_date):
    """Load 15m data from Parquet catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))

    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from Parquet catalog...")

    bars = catalog.bars(bar_types=[bar_type])

    if len(bars) == 0:
        raise ValueError(f"No data found for {bar_type}")

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
    df = df[(df.index >= start_date) & (df.index < end_date)]

    print(f"Loaded {len(df):,} 15m bars from {df.index.min()} to {df.index.max()}")
    return df


def resample_to_4h(df_15m):
    """Resample 15m bars to 4H bars."""
    df_4h = df_15m.resample("4h").agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()

    print(f"Resampled to {len(df_4h):,} 4H bars")
    return df_4h


def calculate_features(df_4h):
    """Calculate 4H features."""
    print("Calculating 4H features...")

    feats = compute_4h_features(df_4h)

    # Merge features back with OHLCV (needed for labeling)
    result = df_4h[["open", "high", "low", "close", "volume"]].copy()
    for col in feats.columns:
        result[col] = feats[col]

    result = result.dropna()

    print(f"4H features calculated: {len(FEATURE_COLUMNS_4H)} features, {len(result):,} bars remaining after dropna")
    return result


def create_labels(df, forward_periods=FORWARD_PERIODS):
    """
    Symmetric directional labeling for 4H bars.

    Label = 1 (LONG/bullish) if forward upside > forward downside
    Label = 0 (SHORT/bearish) if forward downside > forward upside
    Ties are dropped.
    """
    print(f"Creating directional labels (forward_periods={forward_periods}, "
          f"lookahead={forward_periods * 4} hours)...")

    df = df.copy()

    df['forward_high'] = df['high'].rolling(forward_periods).max().shift(-forward_periods)
    df['forward_low'] = df['low'].rolling(forward_periods).min().shift(-forward_periods)

    df = df.dropna(subset=['forward_high', 'forward_low'])

    upside = df['forward_high'] - df['close']
    downside = df['close'] - df['forward_low']

    df['label'] = (upside > downside).astype(int)

    ties = upside == downside
    n_ties = ties.sum()
    df = df[~ties].copy()

    print(f"Labels created. Class distribution:")
    print(df['label'].value_counts())
    print(f"LONG class: {df['label'].sum() / len(df) * 100:.1f}%")
    print(f"SHORT class: {(1 - df['label']).sum() / len(df) * 100:.1f}%")
    if n_ties > 0:
        print(f"Dropped {n_ties} tied bars")

    return df


def train_model(df):
    """Train XGBoost classifier for 4H trend prediction."""
    print("\nPreparing training data...")

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

    # Train model - slightly more regularized than 15m model due to fewer samples
    print("\nTraining XGBoost (4H HTF model)...")
    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.7,
        reg_alpha=0.2,
        reg_lambda=2.0,
        min_child_weight=30,
        gamma=0.2,
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss',
        early_stopping_rounds=30,
    )

    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    # Evaluate
    print("\n" + "=" * 80)
    print("4H HTF MODEL EVALUATION")
    print("=" * 80)

    train_score = model.score(X_train, y_train)
    val_score = model.score(X_val, y_val)

    print(f"\nTrain accuracy: {train_score:.4f}")
    print(f"Val accuracy:   {val_score:.4f}")

    y_pred = model.predict(X_val)
    y_pred_proba = model.predict_proba(X_val)[:, 1]

    print("\nClassification Report (Validation):")
    print(classification_report(y_val, y_pred, target_names=['SHORT/Bear', 'LONG/Bull']))

    print("\nConfusion Matrix:")
    print(confusion_matrix(y_val, y_pred))

    # Feature importance
    print("\nTop 15 Most Important Features:")
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print(feature_importance.head(15).to_string(index=False))

    # Test at different confidence thresholds
    print("\n" + "=" * 80)
    print("PERFORMANCE AT DIFFERENT CONFIDENCE THRESHOLDS")
    print("=" * 80)

    for threshold in [0.50, 0.55, 0.60, 0.65, 0.70]:
        # LONG predictions
        long_mask = y_pred_proba >= threshold
        if long_mask.sum() > 0:
            long_precision = (y_val[long_mask] == 1).sum() / long_mask.sum()
            long_coverage = long_mask.sum() / len(y_val)
            print(f"LONG  >= {threshold:.2f}: Precision={long_precision:.3f}, "
                  f"Coverage={long_coverage:.3f} ({long_mask.sum()} bars)")

        # SHORT predictions
        short_mask = y_pred_proba <= (1 - threshold)
        if short_mask.sum() > 0:
            short_precision = (y_val[short_mask] == 0).sum() / short_mask.sum()
            short_coverage = short_mask.sum() / len(y_val)
            print(f"SHORT <= {1-threshold:.2f}: Precision={short_precision:.3f}, "
                  f"Coverage={short_coverage:.3f} ({short_mask.sum()} bars)")

    # Directional agreement analysis
    print("\n" + "=" * 80)
    print("DIRECTIONAL AGREEMENT ANALYSIS")
    print("=" * 80)
    print("(How often does the 4H model correctly predict direction at various thresholds?)")

    for conf_threshold in [0.50, 0.55, 0.60]:
        bullish = y_pred_proba >= conf_threshold
        bearish = y_pred_proba <= (1 - conf_threshold)
        neutral = ~bullish & ~bearish

        if bullish.sum() > 0:
            bull_acc = (y_val[bullish] == 1).mean()
            print(f"  Bullish (>={conf_threshold:.2f}): {bullish.sum()} bars, accuracy={bull_acc:.3f}")
        if bearish.sum() > 0:
            bear_acc = (y_val[bearish] == 0).mean()
            print(f"  Bearish (<={1-conf_threshold:.2f}): {bearish.sum()} bars, accuracy={bear_acc:.3f}")
        if neutral.sum() > 0:
            print(f"  Neutral: {neutral.sum()} bars (no strong signal)")

    return model, feature_cols


def main():
    print("=" * 80)
    print("4H HTF CONFIRMATION MODEL TRAINING")
    print("=" * 80)

    train_end = pd.Timestamp(TRAIN_END_DATE).tz_localize('UTC')
    train_start = train_end - pd.DateOffset(months=TRAINING_MONTHS)

    print(f"\nTraining period: {train_start.strftime('%Y-%m-%d')} to {train_end.strftime('%Y-%m-%d')}")
    print(f"Duration: {TRAINING_MONTHS} months")

    # Load 15m data
    print("\n" + "-" * 80)
    df_15m = load_15m_data(train_start, train_end)

    # Resample to 4H
    print("\n" + "-" * 80)
    df_4h = resample_to_4h(df_15m)

    if len(df_4h) < MIN_SAMPLES:
        print(f"\nERROR: Not enough 4H bars! Got {len(df_4h)}, need at least {MIN_SAMPLES}")
        return

    # Calculate features
    print("\n" + "-" * 80)
    df_4h = calculate_features(df_4h)

    # Create labels
    print("\n" + "-" * 80)
    df_4h = create_labels(df_4h)

    # Train model
    print("\n" + "-" * 80)
    model, feature_cols = train_model(df_4h)

    # Save model
    print("\n" + "=" * 80)
    print("SAVING 4H HTF MODEL")
    print("=" * 80)

    model_path = PROJECT_ROOT / "models" / "ml_model_htf_4h_xgb.pkl"
    model_path.parent.mkdir(exist_ok=True)

    dump(model, model_path)
    print(f"4H HTF model saved to: {model_path}")

    # Save feature list
    feature_list_path = PROJECT_ROOT / "models" / "feature_list_4h.txt"
    with open(feature_list_path, 'w') as f:
        f.write('\n'.join(feature_cols))
    print(f"Feature list saved to: {feature_list_path}")

    print("\n" + "=" * 80)
    print("4H HTF MODEL TRAINING COMPLETE!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Run backtest with HTF confirmation: python run_backtest_mtf_v2_entry_confirmed_htf.py")
    print("2. Compare results with baseline (no HTF filter)")
    print("3. If improved, enable in .env.mtf_v2: MTF2_HTF_MODEL_PATH=models/ml_model_htf_4h_xgb.pkl")


if __name__ == "__main__":
    main()
