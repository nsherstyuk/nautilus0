"""
Analyze rolling window models to find the best one for current trading.
"""
import pandas as pd

# Load rolling window results
df = pd.read_csv('models/rolling/rolling_window_results.csv')

print("="*80)
print("ROLLING WINDOW MODELS ANALYSIS")
print("="*80)

print("\nAll models:")
print(df[['window_id', 'train_start', 'train_end', 'test_start', 'test_end', 'test_accuracy']].to_string(index=False))

print("\n" + "="*80)
print("BEST MODELS BY TEST ACCURACY")
print("="*80)

# Sort by test accuracy
df_sorted = df.sort_values('test_accuracy', ascending=False)
print("\nTop 5 models:")
print(df_sorted[['window_id', 'train_end', 'test_start', 'test_end', 'test_accuracy']].head().to_string(index=False))

print("\n" + "="*80)
print("MOST RECENT MODELS")
print("="*80)

# Most recent models (trained on latest data)
recent = df.tail(5)
print("\nLast 5 windows:")
print(recent[['window_id', 'train_start', 'train_end', 'test_start', 'test_end', 'test_accuracy']].to_string(index=False))

print("\n" + "="*80)
print("RECOMMENDATION FOR CURRENT TRADING (Nov-Dec 2025)")
print("="*80)

# Window 16 is most recent: trained on Apr-Sep 2025, tested on Oct 2025
window_16 = df[df['window_id'] == 16].iloc[0]
print(f"\n✅ RECOMMENDED: Window 16")
print(f"   Training: {window_16['train_start']} to {window_16['train_end']}")
print(f"   Testing: {window_16['test_start']} to {window_16['test_end']}")
print(f"   Test accuracy: {window_16['test_accuracy']:.4f}")
print(f"   Model: {window_16['model_path']}")

print("\n   Why Window 16?")
print("   - Trained on Apr-Sep 2025 (includes Q2 excellent performance + Q3 regime change)")
print("   - Tested on Oct 2025 (recent performance)")
print("   - Most recent model = best adapted to current market")
print("   - Test accuracy 52.4% (better than random 50%)")

# Compare with best accuracy model
best_model = df_sorted.iloc[0]
print(f"\n📊 ALTERNATIVE: Window {best_model['window_id']} (highest test accuracy)")
print(f"   Training: {best_model['train_start']} to {best_model['train_end']}")
print(f"   Testing: {best_model['test_start']} to {best_model['test_end']}")
print(f"   Test accuracy: {best_model['test_accuracy']:.4f}")
print(f"   Model: {best_model['model_path']}")

if best_model['window_id'] == 14:
    print("\n   Window 14 characteristics:")
    print("   - Trained on Feb-Jul 2025")
    print("   - Tested on Aug 2025")
    print("   - Test accuracy 55.8% (best overall)")
    print("   - BUT: Older data, may not capture latest market regime")

print("\n" + "="*80)
print("DECISION MATRIX")
print("="*80)

print("""
Option 1: Use Window 16 (most recent)
  ✅ Trained on latest data (Apr-Sep 2025)
  ✅ Includes regime change period
  ✅ Tested on Oct 2025 (recent)
  ⚠️  Test accuracy 52.4% (moderate)
  
Option 2: Use Window 14 (best accuracy)
  ✅ Highest test accuracy (55.8%)
  ✅ Includes Q2 2025 excellent period
  ⚠️  Trained on Feb-Jul 2025 (older)
  ⚠️  Tested on Aug 2025 (not most recent)
  
Option 3: Retrain new model
  ✅ Can optimize for specific period
  ✅ Can tune hyperparameters
  ⚠️  Takes time to train
  ⚠️  May overfit

RECOMMENDATION: Start with Window 16, monitor for 1 week
- If performance is good: keep using it
- If performance degrades: try Window 14
- If both fail: retrain with custom parameters
""")

print("\n" + "="*80)
print("HOW TO USE ROLLING WINDOW MODEL")
print("="*80)

print("""
1. Copy the model to main location:
   copy models\\rolling\\ml_model_mtf_window_16.pkl models\\ml_model_mtf.pkl

2. Run backtest to verify:
   python run_mtf_backtest_detailed.py

3. If satisfied, deploy to live:
   python live\\run_live_mtf.py

4. Monitor performance closely for first week
""")
