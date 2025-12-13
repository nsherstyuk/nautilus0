"""
Analyze optimal rolling window length based on market regime changes.

Key Questions:
1. How many distinct market regimes exist in a year?
2. How long does each regime last?
3. What's the optimal training window length?
4. Does mixing regimes in training hurt or help?
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
from scipy import stats

print("="*80)
print("MARKET REGIME ANALYSIS FOR OPTIMAL WINDOW LENGTH")
print("="*80)

print("""
THEORETICAL FRAMEWORK
=====================

The Regime Problem:
-------------------
If we train on data from MULTIPLE regimes, the model learns:
- ✅ Patterns from Regime A
- ✅ Patterns from Regime B
- ❌ But gets confused when to use which!

Example:
- Jan-Mar 2025: Low volatility regime (tight ranges)
- Apr-Jun 2025: High volatility regime (big trends)
- If we train on Jan-Jun, model learns BOTH
- But in July, which regime are we in?

The Window Length Trade-off:
-----------------------------
SHORT WINDOW (3-4 months):
✅ Captures single regime (more focused)
✅ Adapts quickly to regime changes
❌ Less training data (higher variance)
❌ Might overfit to recent noise

LONG WINDOW (12+ months):
✅ More training data (lower variance)
✅ Learns multiple market conditions
❌ Mixes different regimes (confusion)
❌ Slow to adapt to new regimes

MEDIUM WINDOW (6 months):
⚖️  Balance between data and focus
⚖️  Current rolling window approach

KNOWN FOREX MARKET REGIMES
===========================

1. CENTRAL BANK POLICY REGIMES (12-24 months)
   - Hiking cycle (raising rates)
   - Cutting cycle (lowering rates)
   - Hold/pause cycle
   
   Example: Fed hiked Mar 2022 - Jul 2023 (16 months)
            Then paused Jul 2023 - Sep 2024 (14 months)
            Started cutting Sep 2024

2. VOLATILITY REGIMES (3-6 months)
   - High volatility (crisis, uncertainty)
   - Low volatility (calm, range-bound)
   - Transitions between them
   
   Typical duration: 3-6 months per regime

3. SEASONAL REGIMES (Fixed calendar)
   - Q1: Post-holiday positioning
   - Q2: Active trading (best liquidity)
   - Q3: Summer doldrums (low volume)
   - Q4: Year-end flows, tax considerations
   
   Duration: 3 months (quarterly)

4. TREND REGIMES (Variable)
   - Strong trend (directional)
   - Range-bound (choppy)
   - Transition (breakout/breakdown)
   
   Duration: Highly variable (weeks to months)

HYPOTHESIS: EUR/USD likely has 3-4 major regimes per year
""")

# Load backtest data
results_dir = Path("logs/backtest_results/MTF_ML_20251128_202046")
trades_df = pd.read_csv(results_dir / "trades.csv")
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])

print("\n" + "="*80)
print("EMPIRICAL REGIME DETECTION - 2025 DATA")
print("="*80)

# Calculate monthly statistics to detect regime changes
monthly_stats = trades_df.groupby('entry_month').agg({
    'pnl': ['count', 'sum', 'mean', 'std', lambda x: (x > 0).sum() / len(x) * 100],
    'duration_bars': 'mean',
    'exit_reason': lambda x: (x == 'SL').sum() / len(x) * 100
}).round(2)

monthly_stats.columns = ['Trades', 'Total P&L', 'Avg P&L', 'PnL Std', 'Win Rate %', 'Avg Duration', 'SL Rate %']

print("\nMonthly Statistics (Regime Indicators):")
print(monthly_stats)

# Detect regime changes using multiple indicators
print("\n" + "-"*80)
print("REGIME CHANGE DETECTION")
print("-"*80)

# Normalize metrics for comparison
from sklearn.preprocessing import StandardScaler

metrics = monthly_stats[['Avg P&L', 'Win Rate %', 'SL Rate %', 'Avg Duration']].copy()
scaler = StandardScaler()
metrics_scaled = pd.DataFrame(
    scaler.fit_transform(metrics),
    index=metrics.index,
    columns=metrics.columns
)

# Calculate month-to-month changes
metrics_diff = metrics_scaled.diff()

print("\nMonth-to-month changes (standardized):")
print(metrics_diff)

# Identify significant regime changes (large changes in multiple metrics)
regime_change_score = metrics_diff.abs().sum(axis=1)

print("\n" + "-"*80)
print("REGIME CHANGE SCORE (Higher = Bigger Change)")
print("-"*80)
print(regime_change_score.sort_values(ascending=False))

# Identify regime boundaries
threshold = regime_change_score.mean() + regime_change_score.std()
regime_changes = regime_change_score[regime_change_score > threshold]

print(f"\nSignificant regime changes detected (score > {threshold:.2f}):")
for month, score in regime_changes.items():
    print(f"  {month}: {score:.2f}")

# Cluster months into regimes
print("\n" + "="*80)
print("REGIME CLUSTERING")
print("="*80)

from sklearn.cluster import KMeans

# Try different numbers of regimes
for n_regimes in [2, 3, 4, 5]:
    kmeans = KMeans(n_clusters=n_regimes, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(metrics_scaled)
    
    print(f"\n{n_regimes} Regimes:")
    regime_df = pd.DataFrame({
        'Month': metrics.index,
        'Regime': clusters,
        'Avg P&L': metrics['Avg P&L'].values,
        'Win Rate': metrics['Win Rate %'].values
    })
    
    for regime_id in range(n_regimes):
        regime_months = regime_df[regime_df['Regime'] == regime_id]['Month'].tolist()
        avg_pnl = regime_df[regime_df['Regime'] == regime_id]['Avg P&L'].mean()
        avg_wr = regime_df[regime_df['Regime'] == regime_id]['Win Rate'].mean()
        print(f"  Regime {regime_id}: {regime_months}")
        print(f"    Avg P&L: ${avg_pnl:.2f}, Win Rate: {avg_wr:.1f}%")

# Calculate silhouette score to find optimal number of regimes
from sklearn.metrics import silhouette_score

print("\n" + "-"*80)
print("OPTIMAL NUMBER OF REGIMES (Silhouette Score)")
print("-"*80)

silhouette_scores = {}
for n_regimes in range(2, 7):
    kmeans = KMeans(n_clusters=n_regimes, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(metrics_scaled)
    score = silhouette_score(metrics_scaled, clusters)
    silhouette_scores[n_regimes] = score
    print(f"{n_regimes} regimes: {score:.3f}")

best_n_regimes = max(silhouette_scores, key=silhouette_scores.get)
print(f"\n✅ Optimal number of regimes: {best_n_regimes}")

# Analyze regime duration
print("\n" + "="*80)
print("OPTIMAL WINDOW LENGTH RECOMMENDATION")
print("="*80)

print(f"""
Based on 2025 data analysis:

1. DETECTED REGIMES: {best_n_regimes}
   - This suggests EUR/USD has {best_n_regimes} distinct behavioral patterns in 2025

2. REGIME DURATION:
   - With {best_n_regimes} regimes over 11 months
   - Average regime duration: {11 / best_n_regimes:.1f} months

3. WINDOW LENGTH IMPLICATIONS:

   If regimes last ~{11 / best_n_regimes:.1f} months:
   
   OPTION A: Single-Regime Window ({int(11 / best_n_regimes)} months)
   ✅ Trains on pure regime (no mixing)
   ✅ Most focused learning
   ❌ Limited data
   ❌ Requires frequent retraining
   
   OPTION B: Two-Regime Window ({int(11 / best_n_regimes * 2)} months)
   ✅ More training data
   ⚖️  Learns 2 regimes (might help generalization)
   ❌ Some regime confusion
   
   OPTION C: Current 6-Month Window
   ⚖️  Balanced approach
   {'✅ Captures ~2 regimes' if best_n_regimes >= 2 else '⚠️  Might span too many regimes'}
   
   OPTION D: Seasonal Window (3 months = 1 quarter)
   ✅ Aligns with quarterly patterns
   ✅ Pure seasonal learning
   ❌ Very limited data
   ❌ High variance

4. RECOMMENDATION:

   Based on {best_n_regimes} regimes detected:
""")

if best_n_regimes == 2:
    print("""
   ✅ Use 5-6 month windows (captures 1 regime cleanly)
   - 2 regimes/year means each lasts ~6 months
   - 6-month window = single regime training
   - Current approach is OPTIMAL
   """)
elif best_n_regimes == 3:
    print("""
   ✅ Use 3-4 month windows (captures 1 regime)
   - 3 regimes/year means each lasts ~4 months
   - 4-month window = single regime training
   - Current 6-month window spans 1.5 regimes (not ideal)
   - RECOMMENDATION: Reduce to 4 months
   """)
elif best_n_regimes == 4:
    print("""
   ✅ Use 3 month windows (quarterly, captures 1 regime)
   - 4 regimes/year means each lasts ~3 months
   - 3-month window = single regime training
   - Aligns with seasonal quarters
   - Current 6-month window spans 2 regimes (mixing problem!)
   - RECOMMENDATION: Reduce to 3 months (quarterly)
   """)
else:
    print(f"""
   ⚠️  {best_n_regimes} regimes detected (unusual)
   - Regime duration: ~{11/best_n_regimes:.1f} months
   - Consider {int(11/best_n_regimes)}-month windows
   """)

print("\n" + "="*80)
print("TESTING DIFFERENT WINDOW LENGTHS")
print("="*80)

print("""
To find the OPTIMAL window length empirically:

1. Create rolling windows of different lengths:
   - 3 months (quarterly)
   - 4 months
   - 6 months (current)
   - 9 months
   - 12 months (annual)

2. For each window length:
   - Train models on that window
   - Test on next month
   - Calculate average performance

3. Compare:
   - Which window length has best test performance?
   - Which adapts fastest to regime changes?
   - Which has most stable predictions?

4. The winner = optimal window length for EUR/USD

Would you like me to create this test?
""")

print("\n" + "="*80)
print("THE REGIME MIXING PROBLEM")
print("="*80)

print("""
Your concern about mixing regimes is CRITICAL:

Example Scenario:
-----------------
Suppose we have 2 regimes in 2025:

Regime A (Jan-Jun): Low volatility, range-bound
- Best strategy: Mean reversion, tight stops
- Win rate: 50%, Avg win: $200

Regime B (Jul-Nov): High volatility, trending  
- Best strategy: Trend following, wide stops
- Win rate: 40%, Avg win: $400

If we train on 6 months (Jan-Jun):
✅ Model learns Regime A perfectly
❌ Model fails in Regime B (Jul-Nov)
   Result: Your Q4 degradation!

If we train on 12 months (Jan-Dec):
⚖️  Model learns BOTH regimes
❌ But doesn't know WHICH to apply
❌ Averages the strategies (suboptimal for both)

SOLUTION:
---------
1. DETECT current regime
2. USE model trained on that regime only
3. SWITCH models when regime changes

This is why seasonal/monthly switching might work:
- If regimes align with calendar periods
- We can switch models predictably
""")

print("\n" + "="*80)
print("ACTIONABLE NEXT STEPS")
print("="*80)

print("""
1. IMMEDIATE (This Week):
   - Test 3-month vs 6-month vs 12-month window performance
   - Identify which length performs best on 2025 data
   
2. SHORT TERM (This Month):
   - Implement regime detection algorithm
   - Create regime-specific models
   - Test regime-switching strategy
   
3. LONG TERM (Next Quarter):
   - Build adaptive window length system
   - Automatically adjust window based on detected regime stability
   - Deploy with regime monitoring

Which would you like to pursue first?
""")
