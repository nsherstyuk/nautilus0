"""
Analyze the trained ML model's feature importance and performance.
"""
import joblib
import json
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 8)

# Load model and metadata
model_path = Path(__file__).parent.parent / "models" / "strategy_model.joblib"
metadata_path = Path(__file__).parent.parent / "models" / "model_metadata.json"

print("=" * 80)
print("ML MODEL ANALYSIS")
print("=" * 80)

# Load model
model = joblib.load(model_path)
print(f"\n✓ Loaded model from: {model_path}")
print(f"  Model type: {type(model).__name__}")

# Load metadata
with open(metadata_path, 'r') as f:
    metadata = json.load(f)

print(f"\n✓ Loaded metadata from: {metadata_path}")

# Display training info
print("\n" + "=" * 80)
print("TRAINING INFORMATION")
print("=" * 80)
print(f"Training period:   {metadata['training_period']['start']} to {metadata['training_period']['end']}")
print(f"Validation period: {metadata['validation_period']['start']} to {metadata['validation_period']['end']}")
if 'bar_spec' in metadata:
    print(f"Bar specification: {metadata['bar_spec']}")
if 'session_start' in metadata:
    print(f"Trading session:   {metadata['session_start']} to {metadata['session_end']}")
if 'excluded_hours' in metadata:
    print(f"Excluded hours:    {metadata['excluded_hours']}")

# Display model performance
print("\n" + "=" * 80)
print("MODEL PERFORMANCE")
print("=" * 80)
train_acc = metadata['performance']['training_metrics']['accuracy']
val_acc = metadata['performance']['validation_metrics']['accuracy']
train_f1 = metadata['performance']['training_metrics']['f1_weighted']
val_f1 = metadata['performance']['validation_metrics']['f1_weighted']
cv_score = metadata['performance']['best_cv_score']

print(f"Training accuracy:   {train_acc:.2%}")
print(f"Training F1 score:   {train_f1:.2%}")
print(f"Validation accuracy: {val_acc:.2%}")
print(f"Validation F1 score: {val_f1:.2%}")
print(f"Best CV score:       {cv_score:.2%}")
print(f"Training samples:    {metadata['training_period']['n_samples']:,}")
print(f"Validation samples:  {metadata['validation_period']['n_samples']:,}")
print(f"\n⚠️  OVERFITTING DETECTED: {train_acc - val_acc:.1%} accuracy drop from training to validation")

# Feature importance
print("\n" + "=" * 80)
print("FEATURE IMPORTANCE")
print("=" * 80)

feature_names = metadata['feature_columns']
if hasattr(model, 'feature_importances_'):
    importances = model.feature_importances_
    
    # Create DataFrame
    importance_df = pd.DataFrame({
        'Feature': feature_names,
        'Importance': importances
    }).sort_values('Importance', ascending=False)
    
    print("\nFeature Importance Ranking:")
    print("-" * 50)
    for idx, row in importance_df.iterrows():
        bar = '█' * int(row['Importance'] * 100)
        print(f"{row['Feature']:15s} {row['Importance']:6.2%} {bar}")
    
    # Plot feature importance
    plt.figure(figsize=(10, 6))
    plt.barh(importance_df['Feature'], importance_df['Importance'])
    plt.xlabel('Importance')
    plt.title('Feature Importance in ML Trading Model')
    plt.tight_layout()
    
    output_path = Path(__file__).parent.parent / "backtest_results" / "feature_importance.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Feature importance plot saved to: {output_path}")
else:
    print("\nModel does not have feature_importances_ attribute")
    print("This is expected for some model types (e.g., SVM, Neural Networks)")

# Class distribution
print("\n" + "=" * 80)
print("CLASS DISTRIBUTION")
print("=" * 80)
print("\nTarget classes:")
print("  -1: Short signal (price expected to go down)")
print("   0: No trade signal (neutral)")
print("   1: Long signal (price expected to go up)")

if 'training_distribution' in metadata:
    dist = metadata['training_distribution']
    print("\nTraining set distribution:")
    print(f"  Long signals (1):   {dist['buy_signals']:>6,} samples ({dist['buy_pct']:5.1f}%)")
    print(f"  Short signals (-1): {dist['sell_signals']:>6,} samples ({dist['sell_pct']:5.1f}%)")
    print(f"  Neutral (0):        {dist['neutral']:>6,} samples ({dist['neutral_pct']:5.1f}%)")
    print(f"  Average bars to exit: {dist['avg_bars_to_exit']:.1f}")
    
if 'validation_distribution' in metadata:
    dist = metadata['validation_distribution']
    print("\nValidation set distribution:")
    print(f"  Long signals (1):   {dist['buy_signals']:>6,} samples ({dist['buy_pct']:5.1f}%)")
    print(f"  Short signals (-1): {dist['sell_signals']:>6,} samples ({dist['sell_pct']:5.1f}%)")
    print(f"  Neutral (0):        {dist['neutral']:>6,} samples ({dist['neutral_pct']:5.1f}%)")
    print(f"  Average bars to exit: {dist['avg_bars_to_exit']:.1f}")

# Model parameters
print("\n" + "=" * 80)
print("MODEL PARAMETERS")
print("=" * 80)
if 'model_params' in metadata:
    for key, value in metadata['model_params'].items():
        print(f"  {key}: {value}")

# Prediction confidence analysis
print("\n" + "=" * 80)
print("PREDICTION CONFIDENCE ANALYSIS")
print("=" * 80)
print("\nNote: With 37.9% validation accuracy and low confidence predictions,")
print("the model is struggling to find clear patterns in the data.")
print("\nPossible reasons:")
print("  1. Market regime changed between training (2023-2024) and validation (2025)")
print("  2. Features may not capture enough signal")
print("  3. 5-minute timeframe may be too noisy")
print("  4. Class imbalance (if one class dominates)")
print("  5. Model may be underfitting or overfitting")

print("\n" + "=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)
print("\n1. Feature Engineering:")
print("   - Add volume-based indicators")
print("   - Include time-of-day features")
print("   - Add volatility regime indicators")
print("   - Consider price action patterns")

print("\n2. Model Improvements:")
print("   - Try ensemble methods (XGBoost, LightGBM)")
print("   - Experiment with different lookback periods")
print("   - Use cross-validation for better generalization")
print("   - Consider LSTM/GRU for sequence modeling")

print("\n3. Data Quality:")
print("   - Check for data leakage")
print("   - Verify feature scaling")
print("   - Analyze feature correlations")
print("   - Remove redundant features")

print("\n4. Trading Strategy:")
print("   - Lower prediction threshold (0.40-0.45)")
print("   - Add additional filters (trend, volatility)")
print("   - Use ensemble of multiple models")
print("   - Consider longer timeframes (15m, 1h)")

print("\n" + "=" * 80)
