"""
Check why all regime optimization results are identical.
This suggests regime detection might not be working properly.
"""
import pandas as pd
from pathlib import Path

# Load results
csv_file = Path("optimization/results/regime_detection_focused_results.csv")
df = pd.read_csv(csv_file)

completed = df[df['status'] == 'completed'].copy()

print("=" * 80)
print("INVESTIGATING IDENTICAL RESULTS ISSUE")
print("=" * 80)

# Check if all results are truly identical
unique_pnl = completed['total_pnl'].unique()
unique_sharpe = completed['sharpe_ratio'].unique()
unique_trades = completed['trade_count'].unique()

print(f"\nUnique PnL values: {len(unique_pnl)}")
print(f"Unique Sharpe values: {len(unique_sharpe)}")
print(f"Unique trade counts: {len(unique_trades)}")

if len(unique_pnl) == 1:
    print("\n" + "!" * 80)
    print("PROBLEM: All results have IDENTICAL PnL!")
    print("!" * 80)
    print(f"\nAll runs produced: ${unique_pnl[0]:,.2f}")
    print(f"All runs have: {unique_trades[0]} trades")
    print(f"All runs have: {unique_sharpe[0]:.6f} Sharpe ratio")
    
    print("\nThis suggests:")
    print("  1. Regime detection is NOT being applied (all trades use same TP/SL)")
    print("  2. OR all trades are hitting the same regime (unlikely)")
    print("  3. OR there's a bug in how regime parameters are passed to backtest")
    
    # Check if parameters are actually different
    print("\n" + "=" * 80)
    print("CHECKING IF PARAMETERS ARE DIFFERENT")
    print("=" * 80)
    
    param_cols = ['regime_adx_trending_threshold', 'regime_adx_ranging_threshold',
                  'regime_tp_multiplier_trending', 'regime_tp_multiplier_ranging']
    
    for col in param_cols:
        unique_vals = completed[col].unique()
        print(f"{col}: {len(unique_vals)} unique values - {sorted(unique_vals)}")
    
    # Check a sample backtest folder to see actual TP/SL values
    print("\n" + "=" * 80)
    print("CHECKING ACTUAL BACKTEST RESULTS")
    print("=" * 80)
    
    # Get output directory from first run
    sample_run = completed.iloc[0]
    output_dir = Path(sample_run['output_directory'])
    
    if output_dir.exists():
        positions_file = output_dir / "positions.csv"
        if positions_file.exists():
            pos_df = pd.read_csv(positions_file)
            print(f"\nSample run folder: {output_dir.name}")
            print(f"Total trades: {len(pos_df)}")
            
            # Calculate actual TP/SL from trades
            if 'avg_px_open' in pos_df.columns and 'avg_px_close' in pos_df.columns:
                pos_df['entry_price'] = pos_df['avg_px_open'].astype(float)
                pos_df['exit_price'] = pos_df['avg_px_close'].astype(float)
                pos_df['price_diff'] = pos_df['exit_price'] - pos_df['entry_price']
                pos_df['price_diff_pips'] = pos_df.apply(
                    lambda row: row['price_diff'] * 10000 if row['entry'] == 'BUY' else -row['price_diff'] * 10000,
                    axis=1
                )
                
                # Check TP values (winning trades)
                tp_values = pos_df[pos_df['realized_pnl'].str.contains('-', na=False) == False]['price_diff_pips'].abs()
                if len(tp_values) > 0:
                    print(f"\nTake Profit Values (from winning trades):")
                    print(f"  Min: {tp_values.min():.1f} pips")
                    print(f"  Max: {tp_values.max():.1f} pips")
                    print(f"  Mean: {tp_values.mean():.1f} pips")
                    print(f"  Std: {tp_values.std():.1f} pips")
                    
                    if tp_values.std() < 1.0:
                        print("\n  [WARNING] TP values are very consistent!")
                        print("  This suggests regime detection is NOT adjusting TP!")
                    else:
                        print("\n  [OK] TP values vary - regime detection may be working")
                
                # Check SL values (losing trades)
                sl_values = pos_df[pos_df['realized_pnl'].str.contains('-', na=False) == True]['price_diff_pips'].abs()
                if len(sl_values) > 0:
                    print(f"\nStop Loss Values (from losing trades):")
                    print(f"  Min: {sl_values.min():.1f} pips")
                    print(f"  Max: {sl_values.max():.1f} pips")
                    print(f"  Mean: {sl_values.mean():.1f} pips")
                    print(f"  Std: {sl_values.std():.1f} pips")
        else:
            print(f"Positions file not found: {positions_file}")
    else:
        print(f"Output directory not found: {output_dir}")


