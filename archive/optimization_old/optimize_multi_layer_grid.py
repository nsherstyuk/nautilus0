"""
Grid optimization for Conservative multi-layer exit strategy.

Tests combinations of:
1. First partial close trigger (ATR multiples)
2. Layer size distributions
3. Second layer trigger (breakeven or small profit)
4. Move SL to breakeven after first layer

Goal: Find optimal conservative setup that maximizes smoothness while
maintaining acceptable total P&L.
"""
import subprocess
import pandas as pd
from pathlib import Path
from itertools import product
import json

print("="*80)
print("MULTI-LAYER CONSERVATIVE STRATEGY GRID OPTIMIZATION")
print("="*80)

# Define grid parameters
grid_params = {
    'first_trigger': [2.0, 2.5, 3.0],  # ATR multiples for first partial
    'layer_sizes': [
        (0.60, 0.25, 0.15),  # 60/25/15
        (0.70, 0.20, 0.10),  # 70/20/10 (current conservative)
        (0.75, 0.15, 0.10),  # 75/15/10 (very conservative)
    ],
    'second_trigger': [0.0, 0.5, 1.0],  # Breakeven, 0.5 ATR, 1.0 ATR
    'move_sl_to_be': [True, False]
}

# Calculate total combinations
total_combinations = (
    len(grid_params['first_trigger']) *
    len(grid_params['layer_sizes']) *
    len(grid_params['second_trigger']) *
    len(grid_params['move_sl_to_be'])
)

print(f"\nGrid Parameters:")
print(f"  First trigger: {grid_params['first_trigger']}")
print(f"  Layer sizes: {[f'{int(s[0]*100)}/{int(s[1]*100)}/{int(s[2]*100)}' for s in grid_params['layer_sizes']]}")
print(f"  Second trigger: {grid_params['second_trigger']}")
print(f"  Move SL to BE: {grid_params['move_sl_to_be']}")
print(f"\nTotal combinations: {total_combinations}")

# Backup original .env.mtf
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    original_env = f.read()

backup_file = Path('.env.mtf.backup_grid')
with open(backup_file, 'w') as f:
    f.write(original_env)

print(f"✅ Backed up .env.mtf to {backup_file}")

# Run grid search
results = []
combination_num = 0

for first_trigger, layer_sizes, second_trigger, move_sl in product(
    grid_params['first_trigger'],
    grid_params['layer_sizes'],
    grid_params['second_trigger'],
    grid_params['move_sl_to_be']
):
    combination_num += 1
    
    # Create config name
    size_str = f"{int(layer_sizes[0]*100)}/{int(layer_sizes[1]*100)}/{int(layer_sizes[2]*100)}"
    config_name = f"T{first_trigger}_S{size_str}_T2_{second_trigger}_BE{int(move_sl)}"
    
    print(f"\n{'='*80}")
    print(f"[{combination_num}/{total_combinations}] Testing: {config_name}")
    print(f"{'='*80}")
    print(f"  First trigger: {first_trigger} ATR")
    print(f"  Sizes: {size_str}")
    print(f"  Second trigger: {second_trigger} ATR")
    print(f"  Move SL to BE: {move_sl}")
    
    # Modify .env.mtf
    lines = original_env.split('\n')
    new_lines = []
    
    for line in lines:
        if line.startswith('MTF_MULTI_LAYER_ENABLED='):
            new_lines.append('MTF_MULTI_LAYER_ENABLED=true')
        elif line.startswith('MTF_MULTI_LAYER_COUNT='):
            new_lines.append('MTF_MULTI_LAYER_COUNT=3')
        elif line.startswith('MTF_MULTI_LAYER_SIZES='):
            sizes_str = f"{layer_sizes[0]},{layer_sizes[1]},{layer_sizes[2]}"
            new_lines.append(f'MTF_MULTI_LAYER_SIZES={sizes_str}')
        elif line.startswith('MTF_MULTI_LAYER_TRIGGERS='):
            triggers_str = f"{first_trigger},{second_trigger},final"
            new_lines.append(f'MTF_MULTI_LAYER_TRIGGERS={triggers_str}')
        elif line.startswith('MTF_MULTI_LAYER_MOVE_SL_TO_BE='):
            new_lines.append(f'MTF_MULTI_LAYER_MOVE_SL_TO_BE={str(move_sl).lower()}')
        else:
            new_lines.append(line)
    
    # Write config
    with open(env_file, 'w') as f:
        f.write('\n'.join(new_lines))
    
    # Run backtest
    print("  Running backtest...")
    result = subprocess.run(
        ['python', 'run_mtf_backtest_multi_layer.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"  ❌ Failed: {result.stderr[:200]}")
        continue
    
    # Parse results from the latest backtest
    # Find most recent backtest directory
    backtest_dirs = sorted(Path('logs/backtest_results').glob('MTF_ML_*'))
    if not backtest_dirs:
        print("  ❌ No backtest results found")
        continue
    
    latest_dir = backtest_dirs[-1]
    trades_file = latest_dir / 'trades.csv'
    
    if not trades_file.exists():
        print("  ❌ Trades file not found")
        continue
    
    # Load and analyze trades
    df = pd.read_csv(trades_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    
    # Overall metrics
    total_pnl = df['pnl'].sum()
    total_trades = len(df)
    win_rate = (df['pnl'] > 0).sum() / len(df) * 100
    
    # 2025 only metrics
    df_2025 = df[df['entry_time'].dt.year == 2025]
    pnl_2025 = df_2025['pnl'].sum()
    
    # Oct-Nov 2025 metrics
    df_oct_nov = df[(df['entry_month'] == '2025-10') | (df['entry_month'] == '2025-11')]
    pnl_oct_nov = df_oct_nov['pnl'].sum()
    
    # Negative months
    monthly_pnl = df.groupby('entry_month')['pnl'].sum()
    negative_months = (monthly_pnl < 0).sum()
    
    # Drawdown
    df = df.sort_values('exit_time')
    df['cumulative_pnl'] = df['pnl'].cumsum()
    running_max = df['cumulative_pnl'].cummax()
    drawdown = df['cumulative_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    # Daily negative periods
    df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
    daily_pnl = df.groupby('exit_date')['pnl'].sum()
    negative_days = (daily_pnl < 0).sum()
    pct_negative_days = negative_days / len(daily_pnl) * 100
    
    print(f"  ✅ Complete")
    print(f"     Total P&L: ${total_pnl:,.2f}")
    print(f"     2025 P&L: ${pnl_2025:,.2f}")
    print(f"     Oct-Nov 2025: ${pnl_oct_nov:,.2f}")
    print(f"     Negative months: {negative_months}")
    print(f"     Max drawdown: ${max_drawdown:,.2f}")
    print(f"     Negative days: {pct_negative_days:.1f}%")
    
    # Store results
    results.append({
        'config_name': config_name,
        'first_trigger': first_trigger,
        'layer_sizes': size_str,
        'second_trigger': second_trigger,
        'move_sl_to_be': move_sl,
        'total_pnl': total_pnl,
        'pnl_2025': pnl_2025,
        'pnl_oct_nov': pnl_oct_nov,
        'trades': total_trades,
        'win_rate': win_rate,
        'negative_months': negative_months,
        'max_drawdown': max_drawdown,
        'negative_days_pct': pct_negative_days
    })

# Restore original config
with open(backup_file, 'r') as f:
    original_content = f.read()

with open(env_file, 'w') as f:
    f.write(original_content)

print(f"\n✅ Restored original .env.mtf")

# Save results
results_df = pd.DataFrame(results)
results_file = Path('multi_layer_grid_results.csv')
results_df.to_csv(results_file, index=False)

print(f"\n{'='*80}")
print("GRID OPTIMIZATION COMPLETE")
print(f"{'='*80}")

print(f"\nResults saved to: {results_file}")
print(f"Total configurations tested: {len(results)}")

# Display top results
print(f"\n{'='*80}")
print("TOP 10 BY TOTAL P&L")
print(f"{'='*80}")

top_pnl = results_df.nlargest(10, 'total_pnl')
print(top_pnl[['config_name', 'total_pnl', 'pnl_2025', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print(f"\n{'='*80}")
print("TOP 10 BY SMOOTHNESS (Fewest Negative Months + Smallest Drawdown)")
print(f"{'='*80}")

# Create smoothness score (lower is better)
results_df['smoothness_score'] = results_df['negative_months'] * 1000 + abs(results_df['max_drawdown'])
top_smooth = results_df.nsmallest(10, 'smoothness_score')
print(top_smooth[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown', 'negative_days_pct']].to_string(index=False))

print(f"\n{'='*80}")
print("BEST BALANCED (High P&L + Good Smoothness)")
print(f"{'='*80}")

# Normalize metrics for scoring
results_df['pnl_score'] = (results_df['total_pnl'] - results_df['total_pnl'].min()) / (results_df['total_pnl'].max() - results_df['total_pnl'].min())
results_df['smooth_score'] = 1 - ((results_df['smoothness_score'] - results_df['smoothness_score'].min()) / (results_df['smoothness_score'].max() - results_df['smoothness_score'].min()))
results_df['balanced_score'] = results_df['pnl_score'] * 0.6 + results_df['smooth_score'] * 0.4

top_balanced = results_df.nlargest(10, 'balanced_score')
print(top_balanced[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown', 'balanced_score']].to_string(index=False))

print(f"\n{'='*80}")
print("RECOMMENDATION")
print(f"{'='*80}")

best = results_df.loc[results_df['balanced_score'].idxmax()]

print(f"\nBest balanced configuration:")
print(f"  Config: {best['config_name']}")
print(f"  First trigger: {best['first_trigger']} ATR")
print(f"  Layer sizes: {best['layer_sizes']}")
print(f"  Second trigger: {best['second_trigger']} ATR")
print(f"  Move SL to BE: {best['move_sl_to_be']}")
print(f"\nPerformance:")
print(f"  Total P&L: ${best['total_pnl']:,.2f}")
print(f"  2025 P&L: ${best['pnl_2025']:,.2f}")
print(f"  Oct-Nov 2025: ${best['pnl_oct_nov']:,.2f}")
print(f"  Negative months: {int(best['negative_months'])}")
print(f"  Max drawdown: ${best['max_drawdown']:,.2f}")
print(f"  Negative days: {best['negative_days_pct']:.1f}%")

print(f"\nTo use this configuration:")
print(f"  MTF_MULTI_LAYER_ENABLED=true")
print(f"  MTF_MULTI_LAYER_SIZES={best['layer_sizes'].replace('/', ',')}")
print(f"  MTF_MULTI_LAYER_TRIGGERS={best['first_trigger']},{best['second_trigger']},final")
print(f"  MTF_MULTI_LAYER_MOVE_SL_TO_BE={str(best['move_sl_to_be']).lower()}")
