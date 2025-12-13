"""Quick test to find configs with 0 negative months."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from optimize_2pos_sim import (
    load_and_prepare_data, calculate_features, simulate_2pos_strategy, 
    analyze_results
)
from joblib import load
import pandas as pd

# Load model and data
print("Loading model and data...")
model = load(PROJECT_ROOT / "models" / "ml_model_mtf.pkl")
df = load_and_prepare_data("2024-01-01", "2024-10-31")
df = calculate_features(df)
print(f"Data ready: {len(df)} bars")

# Test promising configs based on what we know works
configs = [
    # From quick run - these had 64 neg days, need to check months
    {"name": "80_20_TP0.75_1.75_SL1.4", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    {"name": "80_20_TP0.75_1.75_SL1.6", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.6, "trailing_distance_atr": 0.5},
    {"name": "75_25_TP0.75_1.75_SL1.4", "pos1_fraction": 0.75, "pos2_fraction": 0.25, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    {"name": "75_25_TP0.75_1.75_SL1.6", "pos1_fraction": 0.75, "pos2_fraction": 0.25, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.6, "trailing_distance_atr": 0.5},
    # Try higher SL for fewer losses
    {"name": "80_20_TP0.6_1.5_SL1.4", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.4},
    {"name": "80_20_TP0.6_1.5_SL1.6", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.6, "trailing_distance_atr": 0.4},
    # Match current V2 3-pos style
    {"name": "80_20_TP0.9_1.75_SL1.4", "pos1_fraction": 0.80, "pos2_fraction": 0.20, "pos1_tp_atr": 0.9, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    {"name": "75_25_TP0.9_1.75_SL1.4", "pos1_fraction": 0.75, "pos2_fraction": 0.25, "pos1_tp_atr": 0.9, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    # Higher WR configs
    {"name": "85_15_TP0.75_1.75_SL1.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.75, "pos2_tp_atr": 1.75, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.5},
    {"name": "85_15_TP0.6_1.5_SL1.4", "pos1_fraction": 0.85, "pos2_fraction": 0.15, "pos1_tp_atr": 0.6, "pos2_tp_atr": 1.5, "sl_atr_mult": 1.4, "trailing_distance_atr": 0.4},
]

# Base settings
base = {
    'position_size': 100000,
    'prediction_threshold': 0.55,
    'trade_start_hour': 7,
    'trade_end_hour': 20,
    'min_atr': 0.0003,
    'max_atr': 0.005,
}

results = []
print(f"\nTesting {len(configs)} targeted configs for negative months...\n")

for cfg in configs:
    full_cfg = {**base, **cfg}
    trades = simulate_2pos_strategy(df, model, full_cfg)
    result = analyze_results(trades, cfg['name'])
    results.append(result)
    
    print(f"{cfg['name']:30} | PnL: ${result['total_pnl']:>8,.0f} | WR: {result['win_rate']:>5.1%} | "
          f"Sharpe: {result['sharpe']:>5.2f} | NegDays: {result['neg_days']:>3} | NegMo: {result['neg_months']}")

# Sort by priority: neg_months, then neg_days, then pnl
df_results = pd.DataFrame(results)
df_results = df_results.sort_values(['neg_months', 'neg_days', 'total_pnl'], ascending=[True, True, False])

print("\n" + "=" * 80)
print("RANKED BY YOUR PRIORITY (0 neg months → low neg days → high PnL)")
print("=" * 80)
for i, row in df_results.iterrows():
    marker = "★" if row['neg_months'] == 0 else " "
    print(f"{marker} {row['config']:30} | PnL: ${row['total_pnl']:>8,.0f} | WR: {row['win_rate']:>5.1%} | "
          f"Sharpe: {row['sharpe']:>5.2f} | NegDays: {row['neg_days']:>3} | NegMo: {row['neg_months']} | "
          f"WorstMo: ${row['worst_month']:>7,.0f}")
