"""
Comprehensive Multi-Layer Exit Strategy Optimization

Stage 1: Test layer configurations with expanded options
Stage 2: Optimize parameters for best layer configuration

Key Changes:
- TP fixed at 8.0 ATR (safety net only, not exit strategy)
- Trailing stop is primary exit for runner
- Added runner-focused layer configs (50/15/35, 40/30/30)
- Commission tracking included
"""
import subprocess
import pandas as pd
from pathlib import Path
import time

print("="*80)
print("COMPREHENSIVE MULTI-LAYER EXIT OPTIMIZATION")
print("="*80)

# Stage 1: Layer Configuration Testing
print("\n" + "="*80)
print("STAGE 1: LAYER CONFIGURATION TESTING")
print("="*80)

layer_configs = [
    # Conservative (lock in most early)
    {'name': '70/20/10', 'sizes': (0.70, 0.20, 0.10), 'desc': 'Very Conservative'},
    {'name': '75/15/10', 'sizes': (0.75, 0.15, 0.10), 'desc': 'Ultra Conservative'},
    
    # Balanced
    {'name': '60/25/15', 'sizes': (0.60, 0.25, 0.15), 'desc': 'Conservative Balanced'},
    {'name': '50/25/25', 'sizes': (0.50, 0.25, 0.25), 'desc': 'Equal Split'},
    {'name': '50/30/20', 'sizes': (0.50, 0.30, 0.20), 'desc': 'Moderate Balanced'},
    
    # Runner-focused (let more ride)
    {'name': '50/15/35', 'sizes': (0.50, 0.15, 0.35), 'desc': 'Big Runner'},
    {'name': '40/30/30', 'sizes': (0.40, 0.30, 0.30), 'desc': 'Aggressive Runner'},
]

first_partial_triggers = [2.0, 2.5, 3.0]
second_partial_triggers = [0.0, 0.5]

print(f"\nLayer Configurations: {len(layer_configs)}")
for cfg in layer_configs:
    print(f"  {cfg['name']} - {cfg['desc']}")

print(f"\nFirst Partial Triggers: {first_partial_triggers}")
print(f"Second Partial Triggers: {second_partial_triggers}")

total_stage1 = len(layer_configs) * len(first_partial_triggers) * len(second_partial_triggers)
print(f"\nTotal Stage 1 combinations: {total_stage1}")

# Backup .env.mtf
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    original_env = f.read()

backup_file = Path('.env.mtf.backup_comprehensive')
with open(backup_file, 'w') as f:
    f.write(original_env)

print(f"\n✅ Backed up .env.mtf to {backup_file}")

# Stage 1 Results
stage1_results = []

print(f"\n{'='*80}")
print("RUNNING STAGE 1 TESTS...")
print(f"{'='*80}\n")

test_num = 0
for layer_cfg in layer_configs:
    for first_trigger in first_partial_triggers:
        for second_trigger in second_partial_triggers:
            test_num += 1
            
            config_name = f"{layer_cfg['name']}_T{first_trigger}_T2_{second_trigger}"
            
            print(f"[{test_num}/{total_stage1}] Testing: {config_name}")
            print(f"  Sizes: {layer_cfg['name']}")
            print(f"  First: {first_trigger} ATR, Second: {second_trigger} ATR")
            
            # Modify .env.mtf
            lines = original_env.split('\n')
            new_lines = []
            
            for line in lines:
                if line.startswith('MTF_MULTI_LAYER_ENABLED='):
                    new_lines.append('MTF_MULTI_LAYER_ENABLED=true')
                elif line.startswith('MTF_MULTI_LAYER_COUNT='):
                    new_lines.append('MTF_MULTI_LAYER_COUNT=3')
                elif line.startswith('MTF_MULTI_LAYER_SIZES='):
                    sizes_str = f"{layer_cfg['sizes'][0]},{layer_cfg['sizes'][1]},{layer_cfg['sizes'][2]}"
                    new_lines.append(f'MTF_MULTI_LAYER_SIZES={sizes_str}')
                elif line.startswith('MTF_MULTI_LAYER_TRIGGERS='):
                    triggers_str = f"{first_trigger},{second_trigger},final"
                    new_lines.append(f'MTF_MULTI_LAYER_TRIGGERS={triggers_str}')
                elif line.startswith('MTF_TP_ATR_MULT='):
                    new_lines.append('MTF_TP_ATR_MULT=8.0')  # Fixed TP
                else:
                    new_lines.append(line)
            
            with open(env_file, 'w') as f:
                f.write('\n'.join(new_lines))
            
            # Run backtest
            start_time = time.time()
            result = subprocess.run(
                ['python', 'run_mtf_backtest_multi_layer.py'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            elapsed = time.time() - start_time
            
            if result.returncode != 0:
                print(f"  ❌ Failed ({elapsed:.1f}s)")
                continue
            
            # Find latest backtest results
            backtest_dirs = sorted(Path('logs/backtest_results').glob('MTF_ML_*'))
            if not backtest_dirs:
                print(f"  ❌ No results found")
                continue
            
            latest_dir = backtest_dirs[-1]
            trades_file = latest_dir / 'trades.csv'
            
            if not trades_file.exists():
                print(f"  ❌ Trades file missing")
                continue
            
            # Analyze results
            df = pd.read_csv(trades_file)
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            
            total_pnl = df['pnl'].sum()
            total_trades = len(df)
            win_rate = (df['pnl'] > 0).sum() / len(df) * 100
            
            # 2025 metrics
            df_2025 = df[df['entry_time'].dt.year == 2025]
            pnl_2025 = df_2025['pnl'].sum()
            
            # Oct-Nov 2025
            df_oct_nov = df[(df['entry_month'] == '2025-10') | (df['entry_month'] == '2025-11')]
            pnl_oct_nov = df_oct_nov['pnl'].sum()
            
            # Negative months
            monthly_pnl = df.groupby('entry_month')['pnl'].sum()
            negative_months = (monthly_pnl < 0).sum()
            
            # Drawdown
            df_sorted = df.sort_values('exit_time')
            df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
            running_max = df_sorted['cumulative_pnl'].cummax()
            drawdown = df_sorted['cumulative_pnl'] - running_max
            max_drawdown = drawdown.min()
            
            # Daily metrics
            df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
            daily_pnl = df.groupby('exit_date')['pnl'].sum()
            negative_days = (daily_pnl < 0).sum()
            pct_negative_days = negative_days / len(daily_pnl) * 100
            
            print(f"  ✅ Complete ({elapsed:.1f}s)")
            print(f"     Total P&L: ${total_pnl:,.0f}")
            print(f"     2025 P&L: ${pnl_2025:,.0f}")
            print(f"     Oct-Nov: ${pnl_oct_nov:,.0f}")
            print(f"     Neg Months: {negative_months}, Neg Days: {pct_negative_days:.1f}%")
            print(f"     Max DD: ${max_drawdown:,.0f}\n")
            
            stage1_results.append({
                'config_name': config_name,
                'layer_config': layer_cfg['name'],
                'layer_desc': layer_cfg['desc'],
                'first_trigger': first_trigger,
                'second_trigger': second_trigger,
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
with open(env_file, 'w') as f:
    f.write(original_env)

print(f"\n✅ Restored original .env.mtf")

# Save Stage 1 results
stage1_df = pd.DataFrame(stage1_results)
stage1_file = Path('stage1_layer_optimization.csv')
stage1_df.to_csv(stage1_file, index=False)

print(f"\n{'='*80}")
print("STAGE 1 COMPLETE")
print(f"{'='*80}")
print(f"\nResults saved to: {stage1_file}")
print(f"Configurations tested: {len(stage1_results)}")

# Display top results
print(f"\n{'='*80}")
print("TOP 5 BY TOTAL P&L")
print(f"{'='*80}\n")

top_pnl = stage1_df.nlargest(5, 'total_pnl')
print(top_pnl[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print(f"\n{'='*80}")
print("TOP 5 BY SMOOTHNESS (Fewest Negative Months)")
print(f"{'='*80}\n")

stage1_df['smoothness_score'] = stage1_df['negative_months'] * 1000 + abs(stage1_df['max_drawdown'])
top_smooth = stage1_df.nsmallest(5, 'smoothness_score')
print(top_smooth[['config_name', 'total_pnl', 'pnl_oct_nov', 'negative_months', 'max_drawdown']].to_string(index=False))

print(f"\n{'='*80}")
print("RECOMMENDATION FOR STAGE 2")
print(f"{'='*80}\n")

# Find best balanced configuration
stage1_df['pnl_score'] = (stage1_df['total_pnl'] - stage1_df['total_pnl'].min()) / (stage1_df['total_pnl'].max() - stage1_df['total_pnl'].min())
stage1_df['smooth_score'] = 1 - ((stage1_df['smoothness_score'] - stage1_df['smoothness_score'].min()) / (stage1_df['smoothness_score'].max() - stage1_df['smoothness_score'].min()))
stage1_df['balanced_score'] = stage1_df['pnl_score'] * 0.6 + stage1_df['smooth_score'] * 0.4

best = stage1_df.loc[stage1_df['balanced_score'].idxmax()]

print(f"Best balanced configuration:")
print(f"  Config: {best['config_name']}")
print(f"  Layer: {best['layer_config']} ({best['layer_desc']})")
print(f"  First trigger: {best['first_trigger']} ATR")
print(f"  Second trigger: {best['second_trigger']} ATR")
print(f"\nPerformance:")
print(f"  Total P&L: ${best['total_pnl']:,.0f}")
print(f"  2025 P&L: ${best['pnl_2025']:,.0f}")
print(f"  Oct-Nov 2025: ${best['pnl_oct_nov']:,.0f}")
print(f"  Negative months: {int(best['negative_months'])}")
print(f"  Max drawdown: ${best['max_drawdown']:,.0f}")
print(f"  Negative days: {best['negative_days_pct']:.1f}%")

print(f"\n{'='*80}")
print("NEXT STEPS")
print(f"{'='*80}\n")

print("Stage 2 will optimize these parameters for the winning configuration:")
print("  - Stop Loss: 1.2, 1.5, 1.8 ATR")
print("  - Trailing Activation: 2.5, 3.0, 4.0 ATR")
print("  - Trailing Distance: 0.5, 0.8, 1.0 ATR")
print("  - TP: Fixed at 8.0 ATR (safety net)")
print("\nTotal Stage 2 combinations: 3 × 3 × 3 = 27 tests")
print("\nRun 'python optimize_stage2.py' to continue")
