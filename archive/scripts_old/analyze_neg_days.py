#!/usr/bin/env python3
"""Analyze negative days for top configurations."""
import pandas as pd
from run_mtf_backtest_multi_layer import load_and_prepare_data, calculate_features, simulate_strategy
from config.mtf_config import load_mtf_config
from joblib import load
import copy
import io, sys

# Top configurations to analyze (from optimization results)
configs_to_test = [
    # (L1_trigger, L2_trigger, L1_size, L2_size, name)
    (1.1, 1.75, 0.7, 0.25, "#1: Best PnL $37,793"),
    (1.0, 1.75, 0.7, 0.25, "#2: PnL $35,185, Best Sharpe"),
    (0.9, 1.75, 0.7, 0.25, "#3: PnL $31,268"),
    (0.9, 1.75, 0.7, 0.2, "#4: PnL $29,450"),
    (0.9, 2.0, 0.7, 0.25, "#5: PnL $28,489"),
    # Also test some 1-neg-month configs with higher PnL
    (1.1, 1.75, 0.7, 0.2, "#6: PnL $35,917, 1 neg month"),
    (1.0, 1.75, 0.7, 0.2, "#7: PnL $33,411, 1 neg month"),
    (1.1, 2.0, 0.7, 0.25, "#8: PnL $35,020, 1 neg month"),
]

# Load base config and data
print("Loading data...")
base_config = load_mtf_config()
df = load_and_prepare_data(base_config)
df = calculate_features(df)
model = load(base_config.model_path)

print("\n" + "=" * 90)
print("DETAILED ANALYSIS: TOP CONFIGURATIONS")
print("=" * 90)

results = []

for l1_trigger, l2_trigger, l1_size, l2_size, name in configs_to_test:
    # Create modified config
    config = copy.deepcopy(base_config)
    config.multi_layer_enabled = True
    config.multi_layer_count = 3
    config.multi_layer_triggers = [l1_trigger, l2_trigger, "final"]
    config.multi_layer_sizes = [l1_size, l2_size, 1.0 - l1_size - l2_size]
    config.multi_layer_move_sl_to_be = True
    config.sl_atr_mult = 1.4
    config.trailing_activation_atr_mult = l1_trigger
    
    # Run backtest
    trades = simulate_strategy(df, config, model, logger=None)
    df_trades = pd.DataFrame(trades)
    
    # Calculate daily PnL
    df_trades['exit_date'] = pd.to_datetime(df_trades['exit_time']).dt.date
    daily_pnl = df_trades.groupby('exit_date')['pnl'].sum()
    
    # Calculate monthly PnL
    df_trades['exit_month'] = pd.to_datetime(df_trades['exit_time']).dt.to_period('M')
    monthly_pnl = df_trades.groupby('exit_month')['pnl'].sum()
    
    # Metrics
    total_pnl = df_trades['pnl'].sum()
    total_trades = len(df_trades)
    win_rate = (df_trades['pnl'] > 0).mean() * 100
    neg_months = (monthly_pnl < 0).sum()
    neg_days = (daily_pnl < 0).sum()
    total_days = len(daily_pnl)
    worst_day = daily_pnl.min()
    worst_month = monthly_pnl.min()
    
    results.append({
        'name': name,
        'l1_trigger': l1_trigger,
        'l2_trigger': l2_trigger,
        'l1_size': l1_size,
        'l2_size': l2_size,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'trades': total_trades,
        'neg_months': neg_months,
        'neg_days': neg_days,
        'total_days': total_days,
        'worst_day': worst_day,
        'worst_month': worst_month,
    })
    
    print(f"\n{name}")
    print(f"  Config: L1={l1_trigger}x/{l1_size*100:.0f}%, L2={l2_trigger}x/{l2_size*100:.0f}%")
    print(f"  PnL: ${total_pnl:,.0f} | Win Rate: {win_rate:.1f}% | Trades: {total_trades}")
    print(f"  Negative months: {neg_months} | Negative days: {neg_days}/{total_days} ({neg_days/total_days*100:.1f}%)")
    print(f"  Worst day: ${worst_day:,.0f} | Worst month: ${worst_month:,.0f}")

# Summary table
print("\n" + "=" * 90)
print("SUMMARY TABLE (sorted by negative days)")
print("=" * 90)
print(f"{'Config':<30} {'PnL':>12} {'NegM':>6} {'NegDays':>10} {'Worst Day':>12} {'Worst Month':>12}")
print("-" * 90)

results_sorted = sorted(results, key=lambda x: (x['neg_months'], x['neg_days']))
for r in results_sorted:
    print(f"{r['name']:<30} ${r['total_pnl']:>10,.0f} {r['neg_months']:>6} {r['neg_days']:>10} ${r['worst_day']:>10,.0f} ${r['worst_month']:>10,.0f}")

# Best recommendation
print("\n" + "=" * 90)
print("RECOMMENDATION")
print("=" * 90)
best_zero_neg = [r for r in results if r['neg_months'] == 0]
if best_zero_neg:
    best = min(best_zero_neg, key=lambda x: x['neg_days'])
    print(f"Best with 0 negative months AND fewest negative days: {best['name']}")
    print(f"  L1: {best['l1_trigger']}x ATR -> {best['l1_size']*100:.0f}%")
    print(f"  L2: {best['l2_trigger']}x ATR -> {best['l2_size']*100:.0f}%")
    print(f"  PnL: ${best['total_pnl']:,.0f}")
    print(f"  Negative days: {best['neg_days']}")
