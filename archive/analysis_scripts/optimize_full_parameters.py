"""
Full Parameter Optimization - Stall + SL/TP + Trailing

This script runs comprehensive optimization combining:
1. Best stall detection parameters from first round
2. Stop Loss and Take Profit multipliers
3. Trailing stop parameters

Uses the working run_backtest_mtf_v2_replay.py directly.
"""

import os
import sys
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv, set_key
import tempfile
import shutil

PROJECT_ROOT = Path(__file__).parent

def _parse_money(value):
    """Parse money string to float."""
    import re
    if pd.isna(value):
        return 0.0
    match = re.search(r"(-?\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else 0.0


def calculate_weighted_score(pnl, win_rate, max_drawdown, total_trades):
    """Calculate weighted score: 40% PnL, 30% WinRate, 30% Drawdown penalty."""
    if total_trades == 0:
        return -999999
    
    pnl_score = (pnl / 10000) * 100
    wr_score = (win_rate - 50) * 2
    dd_penalty = (abs(max_drawdown) / 1000) * 100
    
    score = (pnl_score * 0.4) + (wr_score * 0.3) - (dd_penalty * 0.3)
    return score


def run_single_test(stall_check_bars, stall_min_profit, stall_sl_atr, 
                   sl_atr_mult, pos1_tp_atr_mult, pos2_tp_atr_mult, 
                   trailing_distance_atr_mult, iteration_name):
    """Run a single test by calling the working replay script."""
    
    print(f"\n{'='*80}")
    print(f"Running: {iteration_name}")
    print(f"  Stall: Check={stall_check_bars}, MinProfit={stall_min_profit}, SL={stall_sl_atr}")
    print(f"  Risk: SL={sl_atr_mult}x, TP1={pos1_tp_atr_mult}x, TP2={pos2_tp_atr_mult}x")
    print(f"  Trail: {trailing_distance_atr_mult}x")
    print(f"{'='*80}")
    
    # Create temporary env file with modified parameters
    env_file = PROJECT_ROOT / ".env.mtf_v2"
    temp_env_file = PROJECT_ROOT / ".env.mtf_v2_temp"
    
    # Copy original env file
    shutil.copy2(env_file, temp_env_file)
    
    try:
        # Modify parameters in temp env file
        set_key(temp_env_file, "MTF2_STALL_DETECTION_ENABLED", "true")
        set_key(temp_env_file, "MTF2_STALL_CHECK_BARS", str(stall_check_bars))
        set_key(temp_env_file, "MTF2_STALL_MIN_PROFIT_ATR", str(stall_min_profit))
        set_key(temp_env_file, "MTF2_STALL_SL_ATR", str(stall_sl_atr))
        
        set_key(temp_env_file, "MTF2_SL_ATR_MULT", str(sl_atr_mult))
        set_key(temp_env_file, "MTF2_POS1_TP_ATR_MULT", str(pos1_tp_atr_mult))
        set_key(temp_env_file, "MTF2_POS2_TP_ATR_MULT", str(pos2_tp_atr_mult))
        set_key(temp_env_file, "MTF2_TRAILING_DISTANCE_ATR_MULT", str(trailing_distance_atr_mult))
        
        # Run the working replay script with temp env
        cmd = [
            sys.executable, 
            "run_backtest_mtf_v2_replay.py"
        ]
        
        # Temporarily rename files to use our temp config
        original_env = env_file
        temp_env_backup = original_env.with_suffix('.backup')
        
        # Backup original and use temp
        if original_env.exists():
            shutil.move(original_env, temp_env_backup)
        shutil.move(temp_env_file, original_env)
        
        try:
            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode != 0:
                print(f"  ERROR: Replay script failed")
                return None
            
            # Parse results from the latest backtest results
            results_dir = PROJECT_ROOT / "backtest_results"
            replay_dirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.startswith("MTF_V2_REPLAY")]
            if not replay_dirs:
                print(f"  ERROR: No replay backtest results found")
                return None
            
            latest_dir = max(replay_dirs, key=lambda x: x.stat().st_mtime)
            summary_file = latest_dir / "summary.txt"
            
            if not summary_file.exists():
                print(f"  ERROR: No summary.txt found in {latest_dir}")
                return None
            
            # Parse summary file
            with open(summary_file, 'r') as f:
                content = f.read()
            
            # Extract metrics
            metrics = {}
            lines = content.split('\n')
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    metrics[key.strip()] = value.strip()
            
            # Parse key metrics
            try:
                total_pnl = _parse_money(metrics.get('Total P&L', '0'))
                win_rate = float(metrics.get('Win Rate', '0').replace('%', ''))
                max_drawdown = _parse_money(metrics.get('Max Drawdown', '0'))
                total_trades = int(metrics.get('Total Trades', '0'))
                
                if total_trades == 0:
                    print("  Result: No trades")
                    return None
                
                # Calculate weighted score
                score = calculate_weighted_score(total_pnl, win_rate, max_drawdown, total_trades)
                
                result = {
                    'iteration': iteration_name,
                    'stall_check_bars': stall_check_bars,
                    'stall_min_profit': stall_min_profit,
                    'stall_sl_atr': stall_sl_atr,
                    'sl_atr_mult': sl_atr_mult,
                    'pos1_tp_atr_mult': pos1_tp_atr_mult,
                    'pos2_tp_atr_mult': pos2_tp_atr_mult,
                    'trailing_distance_atr_mult': trailing_distance_atr_mult,
                    'total_trades': total_trades,
                    'pnl': total_pnl,
                    'win_rate': win_rate,
                    'max_drawdown': max_drawdown,
                    'weighted_score': score,
                }
                
                print(f"  Trades: {total_trades}, P&L: ${total_pnl:,.2f}, WR: {win_rate:.1f}%, DD: ${max_drawdown:,.2f}")
                print(f"  Weighted Score: {score:.2f}")
                
                return result
                
            except (ValueError, KeyError) as e:
                print(f"  ERROR: Failed to parse metrics: {e}")
                return None
        
        finally:
            # Restore original env file
            if original_env.exists():
                shutil.move(original_env, temp_env_file)
            if temp_env_backup.exists():
                shutil.move(temp_env_backup, original_env)
    
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    print("\n" + "="*80)
    print("FULL PARAMETER OPTIMIZATION - STALL + SL/TP + TRAILING")
    print("="*80)
    print("\nThis optimizes the complete parameter set:")
    print("1. Best stall detection parameters")
    print("2. Stop Loss and Take Profit multipliers") 
    print("3. Trailing stop distance")
    print("\nUsing the working run_backtest_mtf_v2_replay.py directly.\n")
    
    # Best stall parameters from first round optimization results
    BEST_STALL_CHECK_BARS = 2
    BEST_STALL_MIN_PROFIT = 0.3
    BEST_STALL_SL_ATR = 0.05
    
    # Parameter grids for optimization
    param_grid = {
        'sl_atr_mult': [1.0, 1.2, 1.4, 1.6],
        'pos1_tp_atr_mult': [0.4, 0.6, 0.8, 1.0],
        'pos2_tp_atr_mult': [1.0, 1.5, 2.0, 2.5],
        'trailing_distance_atr_mult': [0.2, 0.3, 0.4, 0.5],
    }
    
    # Generate all combinations
    combinations = []
    for sl in param_grid['sl_atr_mult']:
        for tp1 in param_grid['pos1_tp_atr_mult']:
            for tp2 in param_grid['pos2_tp_atr_mult']:
                for trail in param_grid['trailing_distance_atr_mult']:
                    combinations.append((sl, tp1, tp2, trail))
    
    print(f"Best stall parameters from first optimization: Check={BEST_STALL_CHECK_BARS}, MinProfit={BEST_STALL_MIN_PROFIT}, SL={BEST_STALL_SL_ATR}")
    print(f"First optimization result: Score 7.10 vs baseline 6.10 (+1.00 improvement)")
    print(f"Total parameter combinations: {len(combinations)}")
    print(f"Estimated time: {len(combinations) * 20} minutes (~20 min per test)\n")
    
    input("Press Enter to start optimization...")
    
    results = []
    
    # Baseline test (current settings)
    print("\n" + "="*80)
    print("BASELINE TEST (Current Settings)")
    print("="*80)
    
    baseline_result = run_single_test(
        stall_check_bars=BEST_STALL_CHECK_BARS,
        stall_min_profit=BEST_STALL_MIN_PROFIT,
        stall_sl_atr=BEST_STALL_SL_ATR,
        sl_atr_mult=1.4,  # Current from .env.mtf_v2
        pos1_tp_atr_mult=0.6,  # Current from .env.mtf_v2
        pos2_tp_atr_mult=1.5,  # Current from .env.mtf_v2
        trailing_distance_atr_mult=0.4,  # Current from .env.mtf_v2
        iteration_name="BASELINE"
    )
    
    if baseline_result:
        results.append(baseline_result)
        baseline_score = baseline_result['weighted_score']
        baseline_pnl = baseline_result['pnl']
        print(f"\nBaseline Score: {baseline_score:.2f}")
    else:
        print("\nERROR: Baseline test failed!")
        return
    
    # Test all combinations
    for idx, (sl, tp1, tp2, trail) in enumerate(combinations, 1):
        iteration_name = f"Test_{idx:02d}"
        
        result = run_single_test(
            stall_check_bars=BEST_STALL_CHECK_BARS,
            stall_min_profit=BEST_STALL_MIN_PROFIT,
            stall_sl_atr=BEST_STALL_SL_ATR,
            sl_atr_mult=sl,
            pos1_tp_atr_mult=tp1,
            pos2_tp_atr_mult=tp2,
            trailing_distance_atr_mult=trail,
            iteration_name=iteration_name
        )
        
        if result:
            results.append(result)
            improvement = result['weighted_score'] - baseline_score
            pnl_diff = result['pnl'] - baseline_pnl
            marker = " *** BETTER" if improvement > 0 else ""
            print(f"  Score vs Baseline: {improvement:+.2f} (P&L: ${pnl_diff:+,.2f}){marker}")
    
    # Save and display results
    print("\n" + "="*80)
    print("FULL OPTIMIZATION RESULTS")
    print("="*80)
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('weighted_score', ascending=False)
    
    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = PROJECT_ROOT / f"full_optimization_results_{timestamp}.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Display top 10
    print("\nTOP 10 CONFIGURATIONS (by Weighted Score):")
    print("-" * 80)
    
    display_cols = ['iteration', 'sl_atr_mult', 'pos1_tp_atr_mult', 'pos2_tp_atr_mult', 
                    'trailing_distance_atr_mult', 'total_trades', 'pnl', 'win_rate', 
                    'max_drawdown', 'weighted_score']
    print(results_df[display_cols].head(10).to_string(index=False))
    
    # Best configuration
    best = results_df.iloc[0]
    baseline = results_df[results_df['iteration'] == 'BASELINE'].iloc[0]
    
    print("\n" + "="*80)
    print("BEST FULL CONFIGURATION:")
    print("="*80)
    print(f"Iteration: {best['iteration']}")
    print(f"Stall: Check={BEST_STALL_CHECK_BARS}, MinProfit={BEST_STALL_MIN_PROFIT}, SL={BEST_STALL_SL_ATR}")
    print(f"Stop Loss: {best['sl_atr_mult']}x ATR")
    print(f"Take Profit 1: {best['pos1_tp_atr_mult']}x ATR")
    print(f"Take Profit 2: {best['pos2_tp_atr_mult']}x ATR")
    print(f"Trailing Distance: {best['trailing_distance_atr_mult']}x ATR")
    print(f"\nMetrics:")
    print(f"  Total Trades: {best['total_trades']}")
    print(f"  P&L: ${best['pnl']:,.2f}")
    print(f"  Win Rate: {best['win_rate']:.1f}%")
    print(f"  Max Drawdown: ${best['max_drawdown']:,.2f}")
    print(f"  Weighted Score: {best['weighted_score']:.2f}")
    
    print(f"\nVS BASELINE:")
    print(f"  P&L Difference: ${best['pnl'] - baseline['pnl']:+,.2f}")
    print(f"  Win Rate Difference: {best['win_rate'] - baseline['win_rate']:+.1f}%")
    print(f"  Drawdown Difference: ${best['max_drawdown'] - baseline['max_drawdown']:+,.2f}")
    print(f"  Score Improvement: {best['weighted_score'] - baseline['weighted_score']:+.2f}")
    
    print(f"\n*** RECOMMENDED .env.mtf_v2 SETTINGS ***")
    print(f"MTF2_STALL_DETECTION_ENABLED=true")
    print(f"MTF2_STALL_CHECK_BARS={BEST_STALL_CHECK_BARS}")
    print(f"MTF2_STALL_MIN_PROFIT_ATR={BEST_STALL_MIN_PROFIT}")
    print(f"MTF2_STALL_SL_ATR={BEST_STALL_SL_ATR}")
    print(f"MTF2_SL_ATR_MULT={best['sl_atr_mult']}")
    print(f"MTF2_POS1_TP_ATR_MULT={best['pos1_tp_atr_mult']}")
    print(f"MTF2_POS2_TP_ATR_MULT={best['pos2_tp_atr_mult']}")
    print(f"MTF2_TRAILING_DISTANCE_ATR_MULT={best['trailing_distance_atr_mult']}")
    print("="*80)


if __name__ == "__main__":
    main()
