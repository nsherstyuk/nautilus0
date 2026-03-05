"""
Analyze bar-by-bar price action after entry to understand premature entry patterns.

This script loads 1-minute bar data and examines what happens in the first 15-30 bars
after entry for premature vs good entries.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
from datetime import timedelta

# Load the premature entry analysis results
ANALYSIS_PATH = Path("backtest_results/premature_entry_analysis.csv")
BAR_DATA_PATH = Path("data/historical/EUR-USD_EUR_USD_IDEALPRO_1_MINUTE_MID_EXTERNAL.csv")

def load_bar_data():
    """Load 1-minute bar data."""
    print("Loading 1-minute bar data...")
    bars = pd.read_csv(BAR_DATA_PATH)
    bars['timestamp'] = pd.to_datetime(bars['timestamp'], utc=True)
    bars = bars.set_index('timestamp')
    print(f"Loaded {len(bars)} bars")
    return bars

def analyze_post_entry_bars(trades_df, bars_df, n_bars=30):
    """
    For each trade, extract the next N bars after entry and analyze price action.
    """
    
    print(f"\nAnalyzing {n_bars} bars after entry for each trade...")
    
    results = []
    
    for idx, trade in trades_df.iterrows():
        entry_time = pd.to_datetime(trade['entry_time'], utc=True)
        entry_price = trade['entry_price']
        side = trade['side']
        category = trade['category']
        
        if pd.isna(entry_price) or pd.isna(entry_time):
            continue
        
        # Get bars after entry
        future_bars = bars_df[bars_df.index > entry_time].head(n_bars)
        
        if len(future_bars) < n_bars:
            continue
        
        # Calculate price movements relative to entry
        if side == 'LONG':
            # For LONG: positive = favorable, negative = adverse
            high_excursion = (future_bars['high'].max() - entry_price) * 10000
            low_excursion = (future_bars['low'].min() - entry_price) * 10000
            close_moves = (future_bars['close'] - entry_price) * 10000
        else:  # SHORT
            # For SHORT: positive = favorable, negative = adverse
            high_excursion = (entry_price - future_bars['low'].min()) * 10000
            low_excursion = (entry_price - future_bars['high'].max()) * 10000
            close_moves = (entry_price - future_bars['close']) * 10000
        
        # Find when max adverse excursion occurred
        adverse_excursion = low_excursion
        bars_to_adverse = close_moves.idxmin() if len(close_moves) > 0 else None
        
        # Calculate momentum indicators
        first_3_bars_avg = close_moves.iloc[:3].mean() if len(close_moves) >= 3 else np.nan
        first_5_bars_avg = close_moves.iloc[:5].mean() if len(close_moves) >= 5 else np.nan
        first_bar_move = close_moves.iloc[0] if len(close_moves) > 0 else np.nan
        
        # Count bars moving in favorable direction in first 5 bars
        favorable_bars = (close_moves.iloc[:5] > 0).sum() if len(close_moves) >= 5 else 0
        
        results.append({
            'entry_time': entry_time,
            'category': category,
            'side': side,
            'entry_price': entry_price,
            'max_favorable': high_excursion,
            'max_adverse': adverse_excursion,
            'first_bar_move': first_bar_move,
            'first_3_bars_avg': first_3_bars_avg,
            'first_5_bars_avg': first_5_bars_avg,
            'favorable_bars_in_5': favorable_bars,
            'pnl_sl12': trade['pnl_sl12'],
            'pnl_sl14': trade['pnl_sl14'],
        })
    
    return pd.DataFrame(results)

def compare_categories(analysis_df):
    """Compare bar-by-bar metrics across trade categories."""
    
    print("\n" + "=" * 80)
    print("BAR-BY-BAR ANALYSIS: PREMATURE vs GOOD ENTRIES")
    print("=" * 80)
    
    premature = analysis_df[analysis_df['category'] == 'PREMATURE']
    good = analysis_df[analysis_df['category'] == 'GOOD']
    bad = analysis_df[analysis_df['category'] == 'BAD']
    
    print(f"\nTrade counts:")
    print(f"  PREMATURE: {len(premature)}")
    print(f"  GOOD: {len(good)}")
    print(f"  BAD: {len(bad)}")
    
    if len(premature) == 0 or len(good) == 0:
        print("\nInsufficient data for comparison")
        return
    
    print("\n" + "-" * 80)
    print("IMMEDIATE PRICE ACTION (First Bar)")
    print("-" * 80)
    
    metrics = [
        ('first_bar_move', 'First bar move (pips)'),
        ('first_3_bars_avg', 'First 3 bars avg (pips)'),
        ('first_5_bars_avg', 'First 5 bars avg (pips)'),
        ('favorable_bars_in_5', 'Favorable bars in first 5'),
        ('max_adverse', 'Max adverse excursion (pips)'),
        ('max_favorable', 'Max favorable excursion (pips)'),
    ]
    
    print(f"\n{'Metric':<35} | {'Premature':>12} | {'Good':>12} | {'Difference':>12}")
    print("-" * 80)
    
    for col, label in metrics:
        prem_val = premature[col].mean()
        good_val = good[col].mean()
        diff = prem_val - good_val
        
        print(f"{label:<35} | {prem_val:>12.2f} | {good_val:>12.2f} | {diff:>+12.2f}")
    
    print("\n" + "-" * 80)
    print("KEY INSIGHTS")
    print("-" * 80)
    
    # Calculate statistical significance
    first_bar_prem = premature['first_bar_move'].mean()
    first_bar_good = good['first_bar_move'].mean()
    
    print(f"\n1. FIRST BAR MOVEMENT:")
    print(f"   - Premature entries: {first_bar_prem:+.2f} pips (moves AGAINST us)")
    print(f"   - Good entries: {first_bar_good:+.2f} pips (moves WITH us)")
    print(f"   - Difference: {abs(first_bar_prem - first_bar_good):.2f} pips")
    
    fav_bars_prem = premature['favorable_bars_in_5'].mean()
    fav_bars_good = good['favorable_bars_in_5'].mean()
    
    print(f"\n2. MOMENTUM CONSISTENCY (First 5 bars):")
    print(f"   - Premature entries: {fav_bars_prem:.1f} / 5 bars favorable")
    print(f"   - Good entries: {fav_bars_good:.1f} / 5 bars favorable")
    
    adverse_prem = premature['max_adverse'].mean()
    adverse_good = good['max_adverse'].mean()
    
    print(f"\n3. MAXIMUM ADVERSE EXCURSION:")
    print(f"   - Premature entries: {adverse_prem:.2f} pips")
    print(f"   - Good entries: {adverse_good:.2f} pips")
    print(f"   - Premature entries go {abs(adverse_prem - adverse_good):.2f} pips MORE against us")
    
    # Propose entry filter
    print("\n" + "=" * 80)
    print("PROPOSED ENTRY CONFIRMATION FILTER")
    print("=" * 80)
    
    # Find threshold that would filter out most premature entries
    threshold_candidates = np.arange(-2, 2, 0.5)
    
    print("\nTesting first-bar movement thresholds:")
    print(f"{'Threshold':<12} | {'Premature Filtered':>20} | {'Good Filtered':>15} | {'Net Benefit':>12}")
    print("-" * 80)
    
    for threshold in threshold_candidates:
        prem_filtered = (premature['first_bar_move'] < threshold).sum()
        good_filtered = (good['first_bar_move'] < threshold).sum()
        
        # Calculate net benefit (premature filtered - good filtered)
        prem_pct = prem_filtered / len(premature) * 100 if len(premature) > 0 else 0
        good_pct = good_filtered / len(good) * 100 if len(good) > 0 else 0
        
        print(f"{threshold:>+6.1f} pips | {prem_filtered:>3d} / {len(premature):>3d} ({prem_pct:>5.1f}%) | {good_filtered:>3d} / {len(good):>3d} ({good_pct:>4.1f}%) | {prem_pct - good_pct:>+6.1f}%")
    
    print("\n" + "-" * 80)
    print("RECOMMENDATION:")
    print("-" * 80)
    print("\nAdd entry confirmation: Wait for first 1-minute bar to close")
    print("Only enter if first bar moves favorably (or at least not significantly adverse)")
    print("\nExample filter:")
    print("  if prediction == LONG:")
    print("      wait_for_next_bar()")
    print("      if next_bar_close > entry_bar_close - 0.5*ATR:")
    print("          enter_trade()")
    
    return analysis_df

def main():
    """Main analysis function."""
    
    # Load data
    trades_df = pd.read_csv(ANALYSIS_PATH)
    bars_df = load_bar_data()
    
    # Analyze bar-by-bar price action
    analysis_df = analyze_post_entry_bars(trades_df, bars_df, n_bars=30)
    
    # Save detailed analysis
    output_path = Path("backtest_results/bar_by_bar_analysis.csv")
    analysis_df.to_csv(output_path, index=False)
    print(f"\nSaved bar-by-bar analysis to: {output_path}")
    
    # Compare categories
    compare_categories(analysis_df)
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
