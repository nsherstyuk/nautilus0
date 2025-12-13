#!/usr/bin/env python3
"""
Grid optimizer for multi-layer exit parameters.

Optimizes:
- Layer 1 trigger (ATR mult) - when to close first portion
- Layer 2 trigger (ATR mult) - when to close second portion (also trailing activation)
- Layer 1 size (fraction) - how much to close at layer 1
- Layer 2 size (fraction) - how much to close at layer 2
- SL multiplier (ATR mult) - stop loss distance

Goal: Maximize PnL with no negative months.
"""
import sys
from pathlib import Path
from datetime import datetime
from itertools import product
import warnings

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from joblib import load
from dataclasses import dataclass
from typing import List, Tuple, Optional
import copy

# Import from existing backtest
from run_mtf_backtest_multi_layer import (
    load_and_prepare_data,
    calculate_features,
    simulate_strategy,
    analyze_by_month
)
from config.mtf_config import load_mtf_config

warnings.filterwarnings('ignore')


@dataclass
class OptimizationResult:
    """Holds results for one parameter combination."""
    layer1_trigger: float
    layer2_trigger: float
    layer1_size: float
    layer2_size: float
    sl_mult: float
    total_pnl: float
    total_trades: int
    win_rate: float
    negative_months: int
    monthly_pnls: List[float]
    worst_month: float
    best_month: float
    sharpe_approx: float


def run_backtest_with_params(
    df: pd.DataFrame,
    model,
    base_config,
    layer1_trigger: float,
    layer2_trigger: float,
    layer1_size: float,
    layer2_size: float,
    sl_mult: float
) -> OptimizationResult:
    """Run backtest with specific parameter values."""
    
    # Create modified config
    config = copy.deepcopy(base_config)
    
    # Update multi-layer settings
    config.multi_layer_enabled = True
    config.multi_layer_count = 3
    config.multi_layer_triggers = [layer1_trigger, layer2_trigger, "final"]
    config.multi_layer_sizes = [layer1_size, layer2_size, 1.0 - layer1_size - layer2_size]
    config.multi_layer_move_sl_to_be = True
    
    # Update SL
    config.sl_atr_mult = sl_mult
    
    # Trailing activation = layer1 trigger (first partial close triggers trailing)
    config.trailing_activation_atr_mult = layer1_trigger
    
    # Run simulation
    trades = simulate_strategy(df, config, model, logger=None)
    
    if not trades:
        return OptimizationResult(
            layer1_trigger=layer1_trigger,
            layer2_trigger=layer2_trigger,
            layer1_size=layer1_size,
            layer2_size=layer2_size,
            sl_mult=sl_mult,
            total_pnl=0,
            total_trades=0,
            win_rate=0,
            negative_months=12,
            monthly_pnls=[],
            worst_month=0,
            best_month=0,
            sharpe_approx=0
        )
    
    df_trades = pd.DataFrame(trades)
    
    # Calculate metrics
    total_pnl = df_trades['pnl'].sum()
    total_trades = len(df_trades)
    win_rate = (df_trades['pnl'] > 0).mean() * 100
    
    # Monthly analysis (suppress prints)
    import io
    import sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    df_month = analyze_by_month(df_trades)
    sys.stdout = old_stdout
    
    monthly_pnls = df_month['total_pnl'].tolist() if not df_month.empty else []
    negative_months = sum(1 for p in monthly_pnls if p < 0)
    worst_month = min(monthly_pnls) if monthly_pnls else 0
    best_month = max(monthly_pnls) if monthly_pnls else 0
    
    # Approximate Sharpe (monthly)
    if monthly_pnls and len(monthly_pnls) > 1:
        avg_monthly = np.mean(monthly_pnls)
        std_monthly = np.std(monthly_pnls)
        sharpe_approx = (avg_monthly / std_monthly * np.sqrt(12)) if std_monthly > 0 else 0
    else:
        sharpe_approx = 0
    
    return OptimizationResult(
        layer1_trigger=layer1_trigger,
        layer2_trigger=layer2_trigger,
        layer1_size=layer1_size,
        layer2_size=layer2_size,
        sl_mult=sl_mult,
        total_pnl=total_pnl,
        total_trades=total_trades,
        win_rate=win_rate,
        negative_months=negative_months,
        monthly_pnls=monthly_pnls,
        worst_month=worst_month,
        best_month=best_month,
        sharpe_approx=sharpe_approx
    )


def main():
    print("=" * 70)
    print("MULTI-LAYER EXIT PARAMETER OPTIMIZER")
    print("=" * 70)
    print()
    
    # Load base config
    print("Loading base configuration...")
    base_config = load_mtf_config()
    
    # Load data
    print("Loading market data...")
    df = load_and_prepare_data(base_config)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    
    # Calculate features
    print("Calculating features...")
    df = calculate_features(df)
    print(f"Features calculated. Final dataset: {len(df)} bars")
    
    # Load model
    model_path = Path(base_config.model_path)
    print(f"Loading model from {model_path}...")
    model = load(model_path)
    
    # Define parameter grid (EXTENDED search ~40 combos, ~1.5 hours)
    # Focus on promising regions from initial search
    test_configs = []
    
    # Layer 1 triggers - focus around best (0.75-1.0)
    l1_triggers = [0.6, 0.75, 0.9, 1.0, 1.1]
    
    # Layer 2 triggers - focus around best (2.0-2.5)
    l2_triggers = [1.75, 2.0, 2.25, 2.5, 2.75]
    
    # Size combinations - focus on 70/20/10 region (best from initial)
    size_combos = [
        (0.7, 0.2),    # 70/20/10 - best from initial
        (0.7, 0.25),   # 70/25/5
    ]
    
    # SL fixed at best value
    sl_mults = [1.4]
    
    # Build combinations
    for l1 in l1_triggers:
        for l2 in l2_triggers:
            if l2 <= l1:  # L2 must be higher than L1
                continue
            for l1_size, l2_size in size_combos:
                for sl in sl_mults:
                    test_configs.append((l1, l2, l1_size, l2_size, sl))
    
    total_combos = len(test_configs)
    print(f"\nTotal parameter combinations: {total_combos}")
    print(f"Estimated time: ~{total_combos * 2.5:.0f} minutes")
    print()
    
    # Run optimization
    results: List[OptimizationResult] = []
    import time
    
    for combo_count, (l1_trigger, l2_trigger, l1_size, l2_size, sl_mult) in enumerate(test_configs, 1):
        start_time = time.time()
        print(f"[{combo_count}/{total_combos}] L1={l1_trigger}x/{l1_size*100:.0f}%, "
              f"L2={l2_trigger}x/{l2_size*100:.0f}%, SL={sl_mult}x ... ", end="", flush=True)
        
        result = run_backtest_with_params(
            df, model, base_config,
            layer1_trigger=l1_trigger,
            layer2_trigger=l2_trigger,
            layer1_size=l1_size,
            layer2_size=l2_size,
            sl_mult=sl_mult
        )
        results.append(result)
        elapsed = time.time() - start_time
        print(f"PnL: ${result.total_pnl:,.0f}, NegM: {result.negative_months} ({elapsed:.1f}s)", flush=True)
    
    print(f"\nCompleted {len(results)} backtests")
    print()
    
    # Filter and sort results
    print("=" * 70)
    print("TOP 10 RESULTS (BY PNL, NO NEGATIVE MONTHS)")
    print("=" * 70)
    
    # First: no negative months, sorted by PnL
    no_neg_results = [r for r in results if r.negative_months == 0]
    no_neg_results.sort(key=lambda x: x.total_pnl, reverse=True)
    
    if no_neg_results:
        print(f"\nFound {len(no_neg_results)} combinations with NO negative months:\n")
        for i, r in enumerate(no_neg_results[:10], 1):
            layer3_size = 1.0 - r.layer1_size - r.layer2_size
            print(f"{i:2}. PnL: ${r.total_pnl:,.0f} | Win: {r.win_rate:.1f}% | Trades: {r.total_trades}")
            print(f"    L1: {r.layer1_trigger}x ATR -> {r.layer1_size*100:.0f}%")
            print(f"    L2: {r.layer2_trigger}x ATR -> {r.layer2_size*100:.0f}%")
            print(f"    L3: final -> {layer3_size*100:.0f}%")
            print(f"    SL: {r.sl_mult}x ATR")
            print(f"    Months: worst=${r.worst_month:,.0f}, best=${r.best_month:,.0f}, Sharpe~{r.sharpe_approx:.2f}")
            print()
    else:
        print("\nNo combinations found with zero negative months.")
        print("Showing top 10 by PnL with minimum negative months:\n")
        
        # Sort by (negative_months, -total_pnl)
        results.sort(key=lambda x: (x.negative_months, -x.total_pnl))
        
        for i, r in enumerate(results[:10], 1):
            layer3_size = 1.0 - r.layer1_size - r.layer2_size
            print(f"{i:2}. PnL: ${r.total_pnl:,.0f} | Neg Months: {r.negative_months} | Win: {r.win_rate:.1f}%")
            print(f"    L1: {r.layer1_trigger}x ATR -> {r.layer1_size*100:.0f}%")
            print(f"    L2: {r.layer2_trigger}x ATR -> {r.layer2_size*100:.0f}%")
            print(f"    L3: final -> {layer3_size*100:.0f}%")
            print(f"    SL: {r.sl_mult}x ATR")
            print(f"    Worst month: ${r.worst_month:,.0f}")
            print()
    
    # Show best by Sharpe
    print("=" * 70)
    print("TOP 5 BY SHARPE RATIO (WITH <= 1 NEGATIVE MONTH)")
    print("=" * 70)
    
    low_neg_results = [r for r in results if r.negative_months <= 1]
    low_neg_results.sort(key=lambda x: x.sharpe_approx, reverse=True)
    
    for i, r in enumerate(low_neg_results[:5], 1):
        layer3_size = 1.0 - r.layer1_size - r.layer2_size
        print(f"{i}. Sharpe: {r.sharpe_approx:.2f} | PnL: ${r.total_pnl:,.0f} | Neg: {r.negative_months}")
        print(f"   L1: {r.layer1_trigger}x/{r.layer1_size*100:.0f}%, L2: {r.layer2_trigger}x/{r.layer2_size*100:.0f}%, SL: {r.sl_mult}x")
        print()
    
    # Save results to CSV
    output_dir = Path("optimization_results")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    results_data = []
    for r in results:
        results_data.append({
            'layer1_trigger': r.layer1_trigger,
            'layer2_trigger': r.layer2_trigger,
            'layer1_size': r.layer1_size,
            'layer2_size': r.layer2_size,
            'layer3_size': 1.0 - r.layer1_size - r.layer2_size,
            'sl_mult': r.sl_mult,
            'total_pnl': r.total_pnl,
            'total_trades': r.total_trades,
            'win_rate': r.win_rate,
            'negative_months': r.negative_months,
            'worst_month': r.worst_month,
            'best_month': r.best_month,
            'sharpe_approx': r.sharpe_approx
        })
    
    df_results = pd.DataFrame(results_data)
    csv_path = output_dir / f"multilayer_optimization_{timestamp}.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\nResults saved to: {csv_path}")
    
    # Print recommended config
    if no_neg_results:
        best = no_neg_results[0]
        print("\n" + "=" * 70)
        print("RECOMMENDED .env.mtf SETTINGS (Best PnL, No Negative Months)")
        print("=" * 70)
        layer3_size = 1.0 - best.layer1_size - best.layer2_size
        print(f"""
MTF_MULTI_LAYER_ENABLED=true
MTF_MULTI_LAYER_COUNT=3
MTF_MULTI_LAYER_SIZES={best.layer1_size},{best.layer2_size},{layer3_size:.2f}
MTF_MULTI_LAYER_TRIGGERS={best.layer1_trigger},{best.layer2_trigger},final
MTF_MULTI_LAYER_MOVE_SL_TO_BE=true
MTF_SL_ATR_MULT={best.sl_mult}
MTF_TRAILING_ACTIVATION_ATR_MULT={best.layer1_trigger}
""")
        print(f"Expected PnL: ${best.total_pnl:,.0f}")
        print(f"Win Rate: {best.win_rate:.1f}%")
        print(f"Trades: {best.total_trades}")


if __name__ == "__main__":
    main()
