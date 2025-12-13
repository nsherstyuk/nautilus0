"""
Compare key position split configurations using full V2 backtest.

Tests:
1. Single position (baseline)
2. Two-position split (best from simple sim)
3. Three-position split (current)
"""

import subprocess
import sys
from pathlib import Path


def run_backtest_with_config(num_positions: int, sizes: tuple, tps: tuple):
    """Run backtest with specific configuration."""
    
    # Create temporary env file
    env_content = f"""# Temporary config for position split test
MTF_INSTRUMENT=EUR/USD
MTF_VENUE=IDEALPRO  
MTF_BAR_SPEC=15-MINUTE-MID-EXTERNAL
MTF_MODEL_PATH=models/ml_model_mtf.pkl
MTF_TOTAL_POSITION_SIZE=100000
MTF_PREDICTION_THRESHOLD=0.55
MTF_TRADE_START_HOUR=7
MTF_TRADE_END_HOUR=20
MTF_MIN_ATR=0.0003
MTF_MAX_ATR=0.005

# Position config
MTF_POS1_FRACTION={sizes[0]}
MTF_POS2_FRACTION={sizes[1] if len(sizes) > 1 else 0}
MTF_POS3_FRACTION={sizes[2] if len(sizes) > 2 else 0}
MTF_POS1_TP_ATR_MULT={tps[0]}
MTF_POS2_TP_ATR_MULT={tps[1] if len(tps) > 1 else 999}
MTF_POS3_TP_ATR_MULT={tps[2] if len(tps) > 2 else 999}
MTF_SL_ATR_MULT=1.4
MTF_TRAILING_ACTIVATION_ATR_MULT=0.9
MTF_TRAILING_DISTANCE_ATR_MULT=0.5
"""
    
    return env_content


def main():
    print("=" * 80)
    print("POSITION SPLIT COMPARISON - FULL BACKTEST")
    print("=" * 80)
    
    # Configs to test
    configs = [
        # (name, num_positions, sizes, tps)
        ("1-POS: 100% @ TP=2.0x", 1, (1.0,), (2.0,)),
        ("1-POS: 100% @ TP=1.75x", 1, (1.0,), (1.75,)),
        ("2-POS: 65/35 @ TP=1.0/2.0x", 2, (0.65, 0.35), (1.0, 2.0)),
        ("2-POS: 70/30 @ TP=0.9/1.75x", 2, (0.70, 0.30), (0.9, 1.75)),
        ("2-POS: 75/25 @ TP=0.9/2.0x", 2, (0.75, 0.25), (0.9, 2.0)),
        ("3-POS: 70/25/5 @ TP=0.9/1.75/1.75x (CURRENT)", 3, (0.70, 0.25, 0.05), (0.9, 1.75, 1.75)),
        ("3-POS: 70/20/10 @ TP=0.9/1.75/1.75x", 3, (0.70, 0.20, 0.10), (0.9, 1.75, 1.75)),
    ]
    
    print("\nConfigs to test:")
    for name, num, sizes, tps in configs:
        print(f"  - {name}")
    
    print("\nTo run these tests, use the V2 backtest runner with modified configs.")
    print("The key question: Does SL->BE adjustment make multi-position better?")
    
    # Generate config files
    output_dir = Path("config/split_tests")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for name, num, sizes, tps in configs:
        safe_name = name.replace(" ", "_").replace(":", "").replace("/", "-").replace("@", "at")
        env_content = run_backtest_with_config(num, sizes, tps)
        
        config_file = output_dir / f".env.{safe_name}"
        config_file.write_text(env_content)
        print(f"Created: {config_file}")
    
    print(f"\nConfig files saved to: {output_dir}")
    print("\nRun backtests with:")
    print("  python run_backtest_mtf_v2.py --config config/split_tests/.env.<name>")


if __name__ == "__main__":
    main()
