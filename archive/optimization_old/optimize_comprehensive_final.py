"""
Comprehensive Multi-Layer Exit Strategy Optimization - FINAL VERSION

Optimizes:
- Layer configurations (7 options)
- First partial trigger (3 options)
- Second partial trigger (2 options)
- Stop Loss (3 options)
- Take Profit (4 options) - NOW INCLUDED!
- Trailing activation (3 options)
- Trailing distance (3 options)

Stage 1: Layer + Trigger combinations (42 tests)
Stage 2: Full parameter optimization for best layer (108 tests)
Total: ~150 tests, ~2.5 hours

Commissions included, no emojis, subprocess-safe.
"""
import subprocess
import pandas as pd
from pathlib import Path
import time
import sys

print("="*80)
print("COMPREHENSIVE MULTI-LAYER OPTIMIZATION - FINAL")
print("="*80)

# Configuration
layer_configs = [
    {'name': '70/20/10', 'sizes': (0.70, 0.20, 0.10), 'desc': 'Very Conservative'},
    {'name': '75/15/10', 'sizes': (0.75, 0.15, 0.10), 'desc': 'Ultra Conservative'},
    {'name': '60/25/15', 'sizes': (0.60, 0.25, 0.15), 'desc': 'Conservative Balanced'},
    {'name': '50/25/25', 'sizes': (0.50, 0.25, 0.25), 'desc': 'Equal Split'},
    {'name': '50/30/20', 'sizes': (0.50, 0.30, 0.20), 'desc': 'Moderate Balanced'},
    {'name': '50/15/35', 'sizes': (0.50, 0.15, 0.35), 'desc': 'Big Runner'},
    {'name': '40/30/30', 'sizes': (0.40, 0.30, 0.30), 'desc': 'Aggressive Runner'},
]

first_partial_triggers = [2.0, 2.5, 3.0]
second_partial_triggers = [0.0, 0.5]

# Stage 2 parameters (will be tested for best layer config)
sl_options = [1.2, 1.5, 1.8]
tp_options = [6.0, 8.0, 10.0, 12.0]  # TP NOW INCLUDED IN OPTIMIZATION!
trailing_activation_options = [2.5, 3.0, 4.0]
trailing_distance_options = [0.5, 0.8, 1.0]

print(f"\nStage 1: Layer Configuration Testing")
print(f"  Layer configs: {len(layer_configs)}")
print(f"  First triggers: {first_partial_triggers}")
print(f"  Second triggers: {second_partial_triggers}")
print(f"  Total Stage 1: {len(layer_configs) * len(first_partial_triggers) * len(second_partial_triggers)} tests")

print(f"\nStage 2: Parameter Optimization")
print(f"  SL options: {sl_options}")
print(f"  TP options: {tp_options}")
print(f"  Trailing activation: {trailing_activation_options}")
print(f"  Trailing distance: {trailing_distance_options}")
print(f"  Total Stage 2: {len(sl_options) * len(tp_options) * len(trailing_activation_options) * len(trailing_distance_options)} tests")

# Backup .env.mtf
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    original_env = f.read()

backup_file = Path('.env.mtf.backup_final')
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
            if 'layer_sizes' in params:
                sizes_str = f"{params['layer_sizes'][0]},{params['layer_sizes'][1]},{params['layer_sizes'][2]}"
                new_lines.append(f'MTF_MULTI_LAYER_SIZES={sizes_str}')
            else:
                new_lines.append(line)
        elif line.startswith('MTF_MULTI_LAYER_TRIGGERS='):
            if 'first_trigger' in params and 'second_trigger' in params:
                triggers_str = f"{params['first_trigger']},{params['second_trigger']},final"
                new_lines.append(f'MTF_MULTI_LAYER_TRIGGERS={triggers_str}')
            else:
                new_lines.append(line)
        elif line.startswith('MTF_SL_ATR_MULT='):
            if 'sl_atr' in params:
                new_lines.append(f'MTF_SL_ATR_MULT={params["sl_atr"]}')
            else:
                new_lines.append(line)
        elif line.startswith('MTF_TP_ATR_MULT='):
            if 'tp_atr' in params:
                new_lines.append(f'MTF_TP_ATR_MULT={params["tp_atr"]}')
            else:
                new_lines.append(line)
        elif line.startswith('MTF_TRAILING_ACTIVATION_ATR_MULT='):
            if 'trailing_activation' in params:
                new_lines.append(f'MTF_TRAILING_ACTIVATION_ATR_MULT={params["trailing_activation"]}')
            else:
                new_lines.append(line)
        elif line.startswith('MTF_TRAILING_DISTANCE_ATR_MULT='):
            if 'trailing_distance' in params:
                new_lines.append(f'MTF_TRAILING_DISTANCE_ATR_MULT={params["trailing_distance"]}')
            else:
                new_lines.append(line)
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

# STAGE 1: Layer Configuration Testing
print(f"\n{'='*80}")
print("STAGE 1: LAYER CONFIGURATION TESTING")
print(f"{'='*80}\n")

stage1_results = []
test_num = 0
total_stage1 = len(layer_configs) * len(first_partial_triggers) * len(second_partial_triggers)

for layer_cfg in layer_configs:
    for first_trigger in first_partial_triggers:
        for second_trigger in second_partial_triggers:
            test_num += 1
            
            config_name = f"{layer_cfg['name']}_T{first_trigger}_T2_{second_trigger}"
            
            print(f"[{test_num}/{total_stage1}] {config_name}")
            
            params = {
                'layer_sizes': layer_cfg['sizes'],
                'first_trigger': first_trigger,
                'second_trigger': second_trigger,
                'tp_atr': 8.0  # Default for Stage 1
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
            
            stage1_results.append({
                'config_name': config_name,
                'layer_config': layer_cfg['name'],
                'first_trigger': first_trigger,
                'second_trigger': second_trigger,
                **metrics
            })

# Restore original
with open(env_file, 'w') as f:
    f.write(original_env)

# Save Stage 1 results
stage1_df = pd.DataFrame(stage1_results)
stage1_file = Path('stage1_results.csv')
stage1_df.to_csv(stage1_file, index=False)

print(f"\n{'='*80}")
print("STAGE 1 COMPLETE")
print(f"{'='*80}\n")
print(f"Results saved to: {stage1_file}")
print(f"Successful tests: {len(stage1_results)}/{total_stage1}")

# Find best configuration
stage1_df['smoothness_score'] = stage1_df['negative_months'] * 1000 + abs(stage1_df['max_drawdown'])
stage1_df['pnl_score'] = (stage1_df['total_pnl'] - stage1_df['total_pnl'].min()) / (stage1_df['total_pnl'].max() - stage1_df['total_pnl'].min())
stage1_df['smooth_score'] = 1 - ((stage1_df['smoothness_score'] - stage1_df['smoothness_score'].min()) / (stage1_df['smoothness_score'].max() - stage1_df['smoothness_score'].min()))
stage1_df['balanced_score'] = stage1_df['pnl_score'] * 0.6 + stage1_df['smooth_score'] * 0.4

best = stage1_df.loc[stage1_df['balanced_score'].idxmax()]

print(f"\nBest Stage 1 Configuration:")
print(f"  {best['config_name']}")
print(f"  Total P&L: ${best['total_pnl']:,.0f}")
print(f"  Negative Months: {int(best['negative_months'])}")
print(f"  Max Drawdown: ${best['max_drawdown']:,.0f}")

print(f"\n{'='*80}")
print(f"STAGE 2: PARAMETER OPTIMIZATION FOR {best['layer_config']}")
print(f"{'='*80}\n")

# Continue with Stage 2...
print("Stage 2 will optimize SL, TP, Trailing Activation, and Trailing Distance")
print(f"Total tests: {len(sl_options) * len(tp_options) * len(trailing_activation_options) * len(trailing_distance_options)}")
print("\nRun 'python optimize_stage2.py' to continue with Stage 2")
