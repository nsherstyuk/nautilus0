"""Analyze grid sweep results and generate report."""
import pandas as pd
import sys

# Load results
df = pd.read_csv('logs/focused_sweep/grid_results_summary.csv')

print("="*80)
print("ADAPTIVE STOPS PARAMETER SWEEP - RESULTS REPORT")
print("="*80)
print(f"\nTest Period: August 1 - October 31, 2024")
print(f"Total Parameter Combinations Tested: {len(df)}")
print(f"\n{'='*80}\n")

# Display key columns
key_cols = ['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult', 
            'trail_activation_atr_mult', 'trail_distance_atr_mult']

# Add PnL metrics if they exist
pnl_cols = [col for col in df.columns if 'pnls_' in col]
if pnl_cols:
    display_cols = key_cols + ['pnls_PnL (total)', 'pnls_Win Rate', 'pnls_Expectancy', 
                                'pnls_Max Winner', 'pnls_Avg Loser']
    display_cols = [col for col in display_cols if col in df.columns]
else:
    display_cols = key_cols

print("DETAILED RESULTS:")
print("-"*80)
result_df = df[display_cols].copy()

# Format numeric columns
if 'pnls_PnL (total)' in result_df.columns:
    result_df['Net PnL'] = result_df['pnls_PnL (total)'].apply(lambda x: f"${x:.2f}")
if 'pnls_Win Rate' in result_df.columns:
    result_df['Win %'] = result_df['pnls_Win Rate'].apply(lambda x: f"{x*100:.1f}%")
if 'pnls_Expectancy' in result_df.columns:
    result_df['Expect'] = result_df['pnls_Expectancy'].apply(lambda x: f"{x:.2f}")

# Select display columns
final_display = ['run_id', 'adaptive_stop_mode', 'sl_atr_mult', 'tp_atr_mult']
if 'Net PnL' in result_df.columns:
    final_display.extend(['Net PnL', 'Win %', 'Expect'])

print(result_df[final_display].to_string(index=False))

print(f"\n{'='*80}\n")
print("SUMMARY STATISTICS:")
print("-"*80)

if 'pnls_PnL (total)' in df.columns:
    print(f"Net PnL:")
    print(f"  Best:   ${df['pnls_PnL (total)'].max():,.2f}")
    print(f"  Worst:  ${df['pnls_PnL (total)'].min():,.2f}")
    print(f"  Avg:    ${df['pnls_PnL (total)'].mean():,.2f}")
    print(f"  Unique: {df['pnls_PnL (total)'].nunique()} different values\n")

if 'pnls_Win Rate' in df.columns:
    print(f"Win Rate:")
    print(f"  Best:   {df['pnls_Win Rate'].max()*100:.1f}%")
    print(f"  Worst:  {df['pnls_Win Rate'].min()*100:.1f}%")
    print(f"  Avg:    {df['pnls_Win Rate'].mean()*100:.1f}%\n")

if 'pnls_Expectancy' in df.columns:
    print(f"Expectancy:")
    print(f"  Best:   ${df['pnls_Expectancy'].max():.2f}")
    print(f"  Worst:  ${df['pnls_Expectancy'].min():.2f}")
    print(f"  Avg:    ${df['pnls_Expectancy'].mean():.2f}\n")

# Check if all results are identical
if 'pnls_PnL (total)' in df.columns:
    unique_pnls = df['pnls_PnL (total)'].nunique()
    if unique_pnls == 1:
        print("⚠️  WARNING: All runs produced IDENTICAL results!")
        print("This suggests:")
        print("  • Adaptive stop parameters may not be applied correctly")
        print("  • Strategy may be using fixed stops regardless of settings")
        print("  • Need to verify adaptive stops are actually being used\n")
    else:
        print(f"✓ Found {unique_pnls} unique result sets - parameters are having effect\n")

print("="*80)
print("\nFull results saved to: logs/focused_sweep/grid_results_summary.csv")
print("="*80)
