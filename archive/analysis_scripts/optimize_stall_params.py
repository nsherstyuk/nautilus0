"""
Optimize stall detection parameters.
Tests different combinations of min_profit and sl_atr.
Uses parallel processing for faster execution.
"""
import sys
import os
sys.path.insert(0, '.')
os.chdir(os.path.dirname(os.path.abspath(__file__)) or '.')

from dotenv import load_dotenv
load_dotenv('.env.mtf_v2')

import pandas as pd
import numpy as np
import joblib
import multiprocessing
from config.mtf_v2_config import load_mtf_v2_config
from run_backtest_mtf_v2_full import load_and_prepare_data, calculate_features, simulate_2pos_strategy

# Number of workers (use most of your cores, leave 2 free)
NUM_WORKERS = min(14, multiprocessing.cpu_count() - 2)

# Load config
config = load_mtf_v2_config()

# Load data once
print("Loading data...")
df = load_and_prepare_data(config.backtest_start, config.backtest_end)
df = calculate_features(df)
model = joblib.load(config.model_path)
print(f"Data loaded: {len(df)} bars")
print(f"Using {NUM_WORKERS} parallel workers")

# Base sim config
base_config = {
    'position_size': config.total_position_size,
    'pos1_fraction': config.pos1_fraction,
    'pos2_fraction': config.pos2_fraction,
    'sl_atr_mult': config.sl_atr_mult,
    'pos1_tp_atr_mult': config.pos1_tp_atr_mult,
    'pos2_tp_atr_mult': config.pos2_tp_atr_mult,
    'trailing_distance_atr_mult': config.trailing_distance_atr_mult,
    'prediction_threshold': config.prediction_threshold,
    'trade_start_hour': config.trade_start_hour,
    'trade_end_hour': config.trade_end_hour,
    'min_atr': config.min_atr,
    'max_atr': config.max_atr,
    'config_timezone': config.config_timezone,
    'excluded_hours_mode': config.excluded_hours_mode,
    'excluded_hours_monday': config.excluded_hours_monday,
    'excluded_hours_tuesday': config.excluded_hours_tuesday,
    'excluded_hours_wednesday': config.excluded_hours_wednesday,
    'excluded_hours_thursday': config.excluded_hours_thursday,
    'excluded_hours_friday': config.excluded_hours_friday,
    'excluded_hours_saturday': config.excluded_hours_saturday,
    'excluded_hours_sunday': config.excluded_hours_sunday,
    'backtest_start': config.backtest_start,
    'backtest_end': config.backtest_end,
    'stall_detection_enabled': True,
    'stall_check_bars': 6,
}

# Test combinations
results = []

# Also test with stall detection disabled as baseline
def calc_pnl(trades):
    return sum(t['pnl'] for t in trades)

def calc_wr(trades):
    if not trades:
        return 0
    return len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100

print("\n" + "="*70)
print("BASELINE: Stall Detection DISABLED")
print("="*70)

baseline_config = base_config.copy()
baseline_config['stall_detection_enabled'] = False
baseline_config['stall_min_profit_atr'] = 0.2
baseline_config['stall_sl_atr'] = 0.2

trades_baseline = simulate_2pos_strategy(df, model, baseline_config)
pnl_baseline = calc_pnl(trades_baseline)
print(f"Trades: {len(trades_baseline)}, PnL: ${pnl_baseline:,.2f}")
results.append({
    'check_bars': '-',
    'min_profit': '-',
    'sl_atr': '-',
    'enabled': False,
    'trades': len(trades_baseline),
    'pnl': pnl_baseline,
    'win_rate': calc_wr(trades_baseline),
    'pnl_vs_baseline': 0
})

# Test parameter combinations
print("\n" + "="*70)
print("TESTING STALL DETECTION PARAMETERS (PARALLEL)")
print("="*70)

# Build list of parameter combinations to test
param_combos = []
for check_bars in [4, 6, 8]:
    for min_profit in [0.1, 0.15, 0.2, 0.25, 0.3]:
        for sl_atr in [0.05, 0.1, 0.15, 0.2]:
            if sl_atr > min_profit:
                continue
            param_combos.append((check_bars, min_profit, sl_atr))

print(f"Testing {len(param_combos)} parameter combinations with {NUM_WORKERS} workers...")

def run_single_test(params, df_data, ml_model, sim_base_config, baseline_pnl):
    """Worker function for parallel execution."""
    check_bars, min_profit, sl_atr = params
    test_config = sim_base_config.copy()
    test_config['stall_check_bars'] = check_bars
    test_config['stall_min_profit_atr'] = min_profit
    test_config['stall_sl_atr'] = sl_atr
    
    trades = simulate_2pos_strategy(df_data, ml_model, test_config)
    pnl = sum(t['pnl'] for t in trades)
    wr = len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100 if trades else 0
    
    return {
        'check_bars': check_bars,
        'min_profit': min_profit,
        'sl_atr': sl_atr,
        'enabled': True,
        'trades': len(trades),
        'pnl': pnl,
        'win_rate': wr,
        'pnl_vs_baseline': pnl - baseline_pnl
    }

# Use joblib for parallel processing (handles memory efficiently)
from joblib import Parallel, delayed

parallel_results = Parallel(n_jobs=NUM_WORKERS, verbose=10)(
    delayed(run_single_test)(p, df, model, base_config, pnl_baseline) 
    for p in param_combos
)

for result in parallel_results:
    results.append(result)
    marker = " ***" if result['pnl'] > pnl_baseline else ""
    print(f"Bars={result['check_bars']}, Min={result['min_profit']}, SL={result['sl_atr']} -> PnL: ${result['pnl']:,.0f}, WR: {result['win_rate']:.1f}%{marker}")

# Summary
print("\n" + "="*70)
print("TOP 10 CONFIGURATIONS (by PnL)")
print("="*70)

results_df = pd.DataFrame(results)
results_df = results_df.sort_values('pnl', ascending=False)

print(f"\nBaseline (disabled): ${pnl_baseline:,.2f}\n")
print(results_df.head(10).to_string(index=False))

# Best config
best = results_df.iloc[0]
print(f"\n{'='*70}")
print(f"BEST CONFIG:")
print(f"  check_bars: {best.get('check_bars', 'N/A')}")
print(f"  min_profit: {best['min_profit']}")
print(f"  sl_atr: {best['sl_atr']}")
print(f"  PnL: ${best['pnl']:,.2f}")
print(f"  vs Baseline: +${best.get('pnl_vs_baseline', 0):,.2f}")
print(f"{'='*70}")
