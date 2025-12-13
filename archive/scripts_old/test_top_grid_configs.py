"""Test top configs from grid for negative months."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from optimize_2pos_sim import (
    load_and_prepare_data, calculate_features, simulate_2pos_strategy, 
    analyze_results
)
from joblib import load

# Load model and data
print("Loading model and data...")
model = load(PROJECT_ROOT / "models" / "ml_model_mtf.pkl")
df = load_and_prepare_data("2024-01-01", "2024-10-31")
df = calculate_features(df)
print(f"Data ready: {len(df)} bars")

# Top configs from grid (highest PnL)
configs = [
    # Top PnL from grid (SL=1.2)
    {"name": "85_15_TP1.0_1.5_SL1.2_TR0.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 1.0, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.2, "trailing_distance_atr": 0.4},
    {"name": "85_15_TP0.75_1.5_SL1.2_TR0.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.2, "trailing_distance_atr": 0.4},
    {"name": "85_15_TP0.9_1.5_SL1.2_TR0.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.9, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.2, "trailing_distance_atr": 0.4},
    {"name": "80_20_TP1.0_1.5_SL1.2_TR0.4", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 1.0, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.2, "trailing_distance_atr": 0.4},
    # Top from grid with lower neg days (SL=0.8)
    {"name": "85_15_TP0.6_1.5_SL0.8_TR0.6", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 0.8, "trailing_distance_atr": 0.6},
    {"name": "85_15_TP0.6_1.5_SL0.8_TR0.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 0.8, "trailing_distance_atr": 0.4},
    # Configs with high WR and 0 neg months (from targeted test)
    {"name": "85_15_TP0.6_1.5_SL1.4_TR0.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.4},
    {"name": "85_15_TP0.75_1.75_SL1.4_TR0.5", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    {"name": "80_20_TP0.6_1.5_SL1.6_TR0.5", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.6, "trailing_distance_atr": 0.5},
]

base = {
    'position_size': 100000,
    'prediction_threshold': 0.55,
    'trade_start_hour': 7,
    'trade_end_hour': 20,
    'min_atr': 0.0003,
    'max_atr': 0.005,
}

results = []
print(f"\nTesting {len(configs)} configs...\n")
print(f"{'Config':40} | {'PnL':>10} | {'WR':>6} | {'Sharpe':>6} | {'NegDays':>7} | {'NegMo':>5} | {'WorstMo':>9}")
print("-" * 100)

for cfg in configs:
    full_cfg = {**base, **cfg}
    trades = simulate_2pos_strategy(df, model, full_cfg)
    result = analyze_results(trades, cfg['name'])
    results.append(result)
    
    print(f"{cfg['name']:40} | ${result['total_pnl']:>8,.0f} | {result['win_rate']:>5.1%} | "
          f"{result['sharpe']:>6.2f} | {result['neg_days']:>7} | {result['neg_months']:>5} | ${result['worst_month']:>8,.0f}")

# Sort by priority
import pandas as pd
df_results = pd.DataFrame(results)
df_results = df_results.sort_values(['neg_months', 'neg_days', 'total_pnl'], ascending=[True, True, False])

print("\n" + "=" * 100)
print("RANKED BY YOUR PRIORITY (0 neg months -> low neg days -> high PnL)")
print("=" * 100)
for i, row in df_results.iterrows():
    marker = "*" if row['neg_months'] == 0 else " "
    print(f"{marker} {row['config']:40} | ${row['total_pnl']:>8,.0f} | {row['win_rate']:>5.1%} | "
          f"{row['sharpe']:>6.2f} | {row['neg_days']:>7} | {row['neg_months']:>5} | ${row['worst_month']:>8,.0f}")
