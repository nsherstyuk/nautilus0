"""
Simple Stall Optimization - Directly调用 working replay script

This script runs optimization by:
1. Temporarily modifying environment variables for stall parameters
2. Calling the working run_backtest_mtf_v2_replay.py directly
3. Parsing results from the summary file
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


def run_single_test(stall_enabled, check_bars, min_profit_atr, sl_atr, iteration_name):
    """Run a single test by calling the working replay script."""
    
    print(f"\n{'='*80}")
    print(f"Running: {iteration_name}")
    print(f"  Stall Enabled: {stall_enabled}")
    if stall_enabled:
        print(f"  Check Bars: {check_bars}")
        print(f"  Min Profit ATR: {min_profit_atr}")
        print(f"  SL ATR: {sl_atr}")
    print(f"{'='*80}")
    
    # Create temporary env file with modified stall parameters
    env_file = PROJECT_ROOT / ".env.mtf_v2"
    temp_env_file = PROJECT_ROOT / ".env.mtf_v2_temp"
    
    # Copy original env file
    shutil.copy2(env_file, temp_env_file)
    
    try:
        # Modify stall parameters in temp env file
        set_key(temp_env_file, "MTF2_STALL_DETECTION_ENABLED", str(stall_enabled).lower())
        set_key(temp_env_file, "MTF2_STALL_CHECK_BARS", str(check_bars))
        set_key(temp_env_file, "MTF2_STALL_MIN_PROFIT_ATR", str(min_profit_atr))
        set_key(temp_env_file, "MTF2_STALL_SL_ATR", str(sl_atr))
        
        # Run the working replay script with temp env
        cmd = [
            sys.executable, 
            "run_backtest_mtf_v2_replay.py"
        ]
        
        env = os.environ.copy()
        env_file_str = str(temp_env_file)
        
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
                print(f"  stdout: {result.stdout[-500:]}")
                print(f"  stderr: {result.stderr[-500:]}")
                return None
            
            # Parse results from the latest backtest results
            results_dir = PROJECT_ROOT / "backtest_results"
            if not results_dir.exists():
                print(f"  ERROR: No backtest_results directory found")
                return None
            
            # Find the most recent MTF_V2_REPLAY result
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
                    'stall_enabled': stall_enabled,
                    'check_bars': check_bars if stall_enabled else None,
                    'min_profit_atr': min_profit_atr if stall_enabled else None,
                    'sl_atr': sl_atr if stall_enabled else None,
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
    print("POSITIVE STALL DETECTION OPTIMIZATION - SIMPLE APPROACH")
    print("="*80)
    print("\nUsing the working run_backtest_mtf_v2_replay.py directly.")
    print("Modifies environment variables temporarily for each test.\n")
    
    # Define parameter grid
    param_grid = {
        'check_bars': [2, 4, 6],
        'min_profit_atr': [0.1, 0.15, 0.2, 0.3],
        'sl_atr': [0.05, 0.1, 0.15, 0.2],
    }
    
    # Generate combinations
    combinations = []
    for check_bars in param_grid['check_bars']:
        for min_profit in param_grid['min_profit_atr']:
            for sl_atr in param_grid['sl_atr']:
                if sl_atr >= min_profit:
                    continue
                combinations.append((check_bars, min_profit, sl_atr))
    
    print(f"Total parameter combinations: {len(combinations) + 1}")
    print(f"Estimated time: {(len(combinations) + 1) * 20} minutes (~20 min per test)\n")
    
    input("Press Enter to start optimization...")
    
    results = []
    
    # Baseline test
    print("\n" + "="*80)
    print("BASELINE TEST (Stall Detection DISABLED)")
    print("="*80)
    
    baseline_result = run_single_test(
        stall_enabled=False,
        check_bars=6,
        min_profit_atr=0.2,
        sl_atr=0.2,
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
    for idx, (check_bars, min_profit, sl_atr) in enumerate(combinations, 1):
        iteration_name = f"Test_{idx:02d}"
        
        result = run_single_test(
            stall_enabled=True,
            check_bars=check_bars,
            min_profit_atr=min_profit,
            sl_atr=sl_atr,
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
    print("OPTIMIZATION RESULTS")
    print("="*80)
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('weighted_score', ascending=False)
    
    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = PROJECT_ROOT / f"stall_optimization_results_{timestamp}.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Display top 10
    print("\nTOP 10 CONFIGURATIONS (by Weighted Score):")
    print("-" * 80)
    
    display_cols = ['iteration', 'stall_enabled', 'check_bars', 'min_profit_atr', 
                    'sl_atr', 'total_trades', 'pnl', 'win_rate', 'max_drawdown', 'weighted_score']
    print(results_df[display_cols].head(10).to_string(index=False))
    
    # Best configuration
    best = results_df.iloc[0]
    baseline = results_df[results_df['iteration'] == 'BASELINE'].iloc[0]
    
    print("\n" + "="*80)
    print("BEST CONFIGURATION:")
    print("="*80)
    print(f"Iteration: {best['iteration']}")
    print(f"Stall Enabled: {best['stall_enabled']}")
    if best['stall_enabled']:
        print(f"Check Bars: {best['check_bars']}")
        print(f"Min Profit ATR: {best['min_profit_atr']}")
        print(f"SL ATR: {best['sl_atr']}")
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
    
    if best['weighted_score'] > baseline['weighted_score']:
        print("\n*** STALL DETECTION IMPROVES RESULTS ***")
        print("\nRecommended .env.mtf_v2 settings:")
        print(f"MTF2_STALL_DETECTION_ENABLED=true")
        print(f"MTF2_STALL_CHECK_BARS={int(best['check_bars'])}")
        print(f"MTF2_STALL_MIN_PROFIT_ATR={best['min_profit_atr']}")
        print(f"MTF2_STALL_SL_ATR={best['sl_atr']}")
    else:
        print("\n*** BASELINE IS BETTER - KEEP STALL DETECTION DISABLED ***")
    
    print("="*80)


if __name__ == "__main__":
    main()
