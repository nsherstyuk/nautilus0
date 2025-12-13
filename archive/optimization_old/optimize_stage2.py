"""
Stage 2: Parameter Optimization for Best Layer Configuration

Winner from Stage 1: 75/15/10 @ 2.0 ATR / 0.5 ATR

Now optimize:
- Stop Loss: 1.2, 1.5, 1.8 ATR
- Take Profit: 3, 5, 6, 8 ATR (user specified)
- Trailing Activation: 2.5, 3.0, 4.0 ATR
- Trailing Distance: 0.5, 0.8, 1.0 ATR

Total: 3 x 4 x 3 x 3 = 108 tests
ETA: ~2 hours
"""
import subprocess
import pandas as pd
from pathlib import Path
import time
import sys

print("="*80)
print("STAGE 2: PARAMETER OPTIMIZATION")
print("="*80)

# Best configuration from Stage 1
best_layer = {
    'name': '75/15/10',
    'sizes': (0.75, 0.15, 0.10),
    'first_trigger': 2.0,
    'second_trigger': 0.5
}

print(f"\nOptimizing for: {best_layer['name']}")
print(f"  First trigger: {best_layer['first_trigger']} ATR")
print(f"  Second trigger: {best_layer['second_trigger']} ATR")

# Parameter grid
sl_options = [1.2, 1.5, 1.8]
tp_options = [3.0, 5.0, 6.0, 8.0]  # User specified
trailing_activation_options = [2.5, 3.0, 4.0]
trailing_distance_options = [0.5, 0.8, 1.0]

total_tests = len(sl_options) * len(tp_options) * len(trailing_activation_options) * len(trailing_distance_options)

print(f"\nParameter Grid:")
print(f"  SL: {sl_options}")
print(f"  TP: {tp_options}")
print(f"  Trailing Activation: {trailing_activation_options}")
print(f"  Trailing Distance: {trailing_distance_options}")
print(f"\nTotal tests: {total_tests}")

# Backup .env.mtf
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    original_env = f.read()

backup_file = Path('.env.mtf.backup_stage2')
with open(backup_file, 'w') as f:
    f.write(original_env)

print(f"\nBacked up .env.mtf to {backup_file}")

def modify_env(params):
    """Modify .env.mtf with given parameters."""
    lines = original_env.split('\n')
    new_lines = []
    
    for line in lines:
        if line.startswith('MTF_MULTI_LAYER_ENABLED='):
            new_lines.append('MTF_MULTI_LAYER_ENABLED=true')
        elif line.startswith('MTF_MULTI_LAYER_COUNT='):
            new_lines.append('MTF_MULTI_LAYER_COUNT=3')
        elif line.startswith('MTF_MULTI_LAYER_SIZES='):
            sizes_str = f"{best_layer['sizes'][0]},{best_layer['sizes'][1]},{best_layer['sizes'][2]}"
            new_lines.append(f'MTF_MULTI_LAYER_SIZES={sizes_str}')
        elif line.startswith('MTF_MULTI_LAYER_TRIGGERS='):
            triggers_str = f"{best_layer['first_trigger']},{best_layer['second_trigger']},final"
            new_lines.append(f'MTF_MULTI_LAYER_TRIGGERS={triggers_str}')
        elif line.startswith('MTF_SL_ATR_MULT='):
            new_lines.append(f'MTF_SL_ATR_MULT={params["sl_atr"]}')
        elif line.startswith('MTF_TP_ATR_MULT='):
            new_lines.append(f'MTF_TP_ATR_MULT={params["tp_atr"]}')
        elif line.startswith('MTF_TRAILING_ACTIVATION_ATR_MULT='):
            new_lines.append(f'MTF_TRAILING_ACTIVATION_ATR_MULT={params["trailing_activation"]}')
        elif line.startswith('MTF_TRAILING_DISTANCE_ATR_MULT='):
            new_lines.append(f'MTF_TRAILING_DISTANCE_ATR_MULT={params["trailing_distance"]}')
        else:
            new_lines.append(line)
    
    with open(env_file, 'w') as f:
        f.write('\n'.join(new_lines))

def run_backtest():
    """Run backtest via subprocess."""
    result = subprocess.run(
        [sys.executable, 'run_mtf_backtest_multi_layer.py'],
        capture_output=True,
        text=True,
        timeout=120
    )
    return result

def extract_results():
    """Extract results from latest backtest."""
    backtest_dirs = sorted(Path('logs/backtest_results').glob('MTF_ML_*'))
    if not backtest_dirs:
        return None
    
    latest_dir = backtest_dirs[-1]
    trades_file = latest_dir / 'trades.csv'
    
    if not trades_file.exists():
        return None
    
    df = pd.read_csv(trades_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    total_pnl = df['pnl'].sum()
    total_trades = len(df)
    win_rate = (df['pnl'] > 0).sum() / len(df) * 100
    
    df_2025 = df[df['entry_time'].dt.year == 2025]
    pnl_2025 = df_2025['pnl'].sum()
    
    df_oct_nov = df[(df['entry_month'] == '2025-10') | (df['entry_month'] == '2025-11')]
    pnl_oct_nov = df_oct_nov['pnl'].sum()
    
    monthly_pnl = df.groupby('entry_month')['pnl'].sum()
    negative_months = (monthly_pnl < 0).sum()
    
    df_sorted = df.sort_values('exit_time')
    df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
    running_max = df_sorted['cumulative_pnl'].cummax()
    drawdown = df_sorted['cumulative_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
    daily_pnl = df.groupby('exit_date')['pnl'].sum()
    negative_days = (daily_pnl < 0).sum()
    pct_negative_days = negative_days / len(daily_pnl) * 100
    
    return {
        'total_pnl': total_pnl,
        'pnl_2025': pnl_2025,
        'pnl_oct_nov': pnl_oct_nov,
        'trades': total_trades,
        'win_rate': win_rate,
        'negative_months': negative_months,
        'max_drawdown': max_drawdown,
        'negative_days_pct': pct_negative_days
    }

# Run optimization
print(f"\n{'='*80}")
print("RUNNING STAGE 2 OPTIMIZATION")
print(f"{'='*80}\n")

stage2_results = []
test_num = 0

for sl in sl_options:
    for tp in tp_options:
        for trail_act in trailing_activation_options:
            for trail_dist in trailing_distance_options:
                test_num += 1
                
                config_name = f"SL{sl}_TP{tp}_TA{trail_act}_TD{trail_dist}"
                
                print(f"[{test_num}/{total_tests}] {config_name}")
                
                params = {
                    'sl_atr': sl,
                    'tp_atr': tp,
                    'trailing_activation': trail_act,
                    'trailing_distance': trail_dist
                }
                
                modify_env(params)
                
                start_time = time.time()
                result = run_backtest()
                elapsed = time.time() - start_time
                
                if result.returncode != 0:
                    print(f"  FAILED ({elapsed:.1f}s)\n")
                    continue
                
                metrics = extract_results()
                if not metrics:
                    print(f"  NO RESULTS ({elapsed:.1f}s)\n")
                    continue
                
                print(f"  P&L: ${metrics['total_pnl']:,.0f}, Oct-Nov: ${metrics['pnl_oct_nov']:,.0f}, Neg Months: {metrics['negative_months']} ({elapsed:.1f}s)\n")
                
                stage2_results.append({
                    'config_name': config_name,
                    'sl_atr': sl,
                    'tp_atr': tp,
                    'trailing_activation': trail_act,
                    'trailing_distance': trail_dist,
                    **metrics
                })

# Restore original
with open(env_file, 'w') as f:
    f.write(original_env)

# Save results
stage2_df = pd.DataFrame(stage2_results)
stage2_file = Path('stage2_results.csv')
stage2_df.to_csv(stage2_file, index=False)

print(f"\n{'='*80}")
print("STAGE 2 COMPLETE")
print(f"{'='*80}\n")
print(f"Results saved to: {stage2_file}")
print(f"Successful tests: {len(stage2_results)}/{total_tests}")

# Find best configuration
stage2_df['smoothness_score'] = stage2_df['negative_months'] * 1000 + abs(stage2_df['max_drawdown'])
stage2_df['pnl_score'] = (stage2_df['total_pnl'] - stage2_df['total_pnl'].min()) / (stage2_df['total_pnl'].max() - stage2_df['total_pnl'].min())
stage2_df['smooth_score'] = 1 - ((stage2_df['smoothness_score'] - stage2_df['smoothness_score'].min()) / (stage2_df['smoothness_score'].max() - stage2_df['smoothness_score'].min()))
stage2_df['balanced_score'] = stage2_df['pnl_score'] * 0.6 + stage2_df['smooth_score'] * 0.4

best = stage2_df.loc[stage2_df['balanced_score'].idxmax()]

print(f"\nBEST OVERALL CONFIGURATION:")
print(f"  Layer: {best_layer['name']}")
print(f"  First Trigger: {best_layer['first_trigger']} ATR")
print(f"  Second Trigger: {best_layer['second_trigger']} ATR")
print(f"  SL: {best['sl_atr']} ATR")
print(f"  TP: {best['tp_atr']} ATR")
print(f"  Trailing Activation: {best['trailing_activation']} ATR")
print(f"  Trailing Distance: {best['trailing_distance']} ATR")
print(f"\nPerformance:")
print(f"  Total P&L: ${best['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best['pnl_2025']:,.0f}")
print(f"  Oct-Nov 2025: ${best['pnl_oct_nov']:,.0f}")
print(f"  Negative Months: {int(best['negative_months'])}")
print(f"  Max Drawdown: ${best['max_drawdown']:,.0f}")
print(f"  Negative Days: {best['negative_days_pct']:.1f}%")

print(f"\n{'='*80}")
print("TOP 5 BY TOTAL P&L")
print(f"{'='*80}\n")
top_pnl = stage2_df.nlargest(5, 'total_pnl')
print(top_pnl[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print(f"\n{'='*80}")
print("TOP 5 BY SMOOTHNESS")
print(f"{'='*80}\n")
top_smooth = stage2_df.nsmallest(5, 'smoothness_score')
print(top_smooth[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))
