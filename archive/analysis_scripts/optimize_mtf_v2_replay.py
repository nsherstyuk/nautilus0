"""
MTF V2 Parameter Optimization using Backtest Replay (Most Accurate).

Uses the actual NautilusTrader backtest engine with replay for maximum accuracy.
Optimizes parameters with composite scoring that balances:
- Total PnL
- Win Rate
- Max Drawdown (risk)
- Sharpe Ratio
- Negative days/months

SINGLE POSITION MODE (100% POS1)

Parameters optimized:
- MTF2_SL_ATR_MULT (Stop Loss)
- MTF2_POS1_TP_ATR_MULT (Take Profit)
- MTF2_TRAILING_DISTANCE_ATR_MULT (Trailing stop)
- MTF2_PREDICTION_THRESHOLD (Entry confidence)
"""

import os
import sys
import shutil
import logging
from pathlib import Path
from datetime import datetime
import itertools
import subprocess

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from dotenv import load_dotenv


def generate_parameter_grid(quick_mode=False):
    """Generate parameter combinations to test - SINGLE POSITION MODE."""
    
    # Focused grid: ~30 configurations
    # Focus on reasonable ranges based on previous optimization results
    sl_values = [0.8, 1.0, 1.2, 1.6]
    tp_values = [0.6, 0.8, 1.0, 1.2, 1.5]
    trailing_values = [0.4, 0.5]
    threshold_values = [0.65, 0.68]
    
    configs = []
    
    for sl, tp, trail, thresh in itertools.product(
        sl_values, tp_values, trailing_values, threshold_values
    ):
        # Skip if SL/TP ratio is not in reasonable range (0.6 to 1.5)
        sl_tp_ratio = sl / tp
        if sl_tp_ratio < 0.6 or sl_tp_ratio > 1.5:
            continue
        
        # Skip very tight SL with very small TP (too aggressive)
        if sl <= 0.8 and tp <= 0.6:
            continue
        
        # Skip very wide SL with very large TP (too passive)
        if sl >= 1.6 and tp >= 1.5:
            continue
        
        config = {
            'name': f"SL{sl}_TP{tp}_TR{trail}_TH{thresh}",
            'MTF2_SL_ATR_MULT': sl,
            'MTF2_POS1_TP_ATR_MULT': tp,
            'MTF2_POS2_TP_ATR_MULT': tp,  # Same as POS1 (not used in single mode)
            'MTF2_POS1_FRACTION': 1.0,  # 100% single position
            'MTF2_POS2_FRACTION': 0.0,
            'MTF2_POS3_FRACTION': 0.0,
            'MTF2_TRAILING_DISTANCE_ATR_MULT': trail,
            'MTF2_PREDICTION_THRESHOLD': thresh,
        }
        configs.append(config)
    
    return configs


def run_backtest_with_params(params, backtest_start, backtest_end, output_base_dir, replay_speed="4x"):
    """Run a single backtest with given parameters."""
    
    # Create temporary .env file with these parameters
    env_path = PROJECT_ROOT / '.env.mtf_v2'
    env_backup = PROJECT_ROOT / '.env.mtf_v2.backup'
    
    # Backup original .env
    if env_path.exists():
        shutil.copy(env_path, env_backup)
    
    try:
        # Load original .env
        load_dotenv(env_path)
        
        # Update with optimization parameters
        env_vars = {}
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
        
        # Override with optimization params
        for key, value in params.items():
            if key != 'name':
                env_vars[key] = str(value)
        
        # Override backtest dates and replay speed
        env_vars['MTF2_BACKTEST_START'] = backtest_start
        env_vars['MTF2_BACKTEST_END'] = backtest_end
        env_vars['MTF2_REPLAY_SPEED'] = replay_speed
        
        # Write temporary .env
        with open(env_path, 'w') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
        
        # Run backtest
        result = subprocess.run(
            [sys.executable, 'run_backtest_mtf_v2_replay.py'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',  # Ignore Unicode decode errors
            timeout=1800  # 30 minute timeout per backtest
        )
        
        if result.returncode != 0:
            print(f"ERROR: Backtest failed for {params['name']}")
            print(result.stderr)
            return None
        
        # Find the latest backtest result folder
        backtest_results = PROJECT_ROOT / 'backtest_results'
        latest_folder = max(
            [d for d in backtest_results.iterdir() if d.is_dir() and d.name.startswith('MTF_V2_REPLAY_')],
            key=lambda x: x.stat().st_mtime
        )
        
        # Rename to include config name
        new_name = f"OPT_{params['name']}_{latest_folder.name.split('_')[-1]}"
        new_path = output_base_dir / new_name
        shutil.move(str(latest_folder), str(new_path))
        
        return new_path
        
    finally:
        # Restore original .env
        if env_backup.exists():
            shutil.move(env_backup, env_path)


def analyze_backtest_results(result_folder):
    """Extract metrics from backtest results."""
    
    # Read trades
    trades_path = result_folder / 'trades.csv'
    if not trades_path.exists():
        return None
    
    trades = pd.read_csv(trades_path)
    
    if len(trades) == 0:
        return None
    
    # Basic metrics
    total_pnl = trades['pnl'].sum()
    num_trades = len(trades)
    win_rate = (trades['pnl'] > 0).mean()
    
    # Calculate drawdown
    trades['exit_time'] = pd.to_datetime(trades['exit_time'])
    trades_valid = trades[trades['exit_time'].notna()].copy()
    trades_sorted = trades_valid.sort_values('exit_time').reset_index(drop=True)
    
    trades_sorted['cumulative_pnl'] = trades_sorted['pnl'].cumsum()
    trades_sorted['running_max'] = trades_sorted['cumulative_pnl'].cummax()
    trades_sorted['drawdown'] = trades_sorted['cumulative_pnl'] - trades_sorted['running_max']
    
    max_drawdown = trades_sorted['drawdown'].min()
    max_drawdown_pct = abs(max_drawdown / trades_sorted['running_max'].max() * 100) if trades_sorted['running_max'].max() > 0 else 0
    
    # Calculate Sharpe ratio (simplified)
    if len(trades) > 1:
        returns = trades['pnl']
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    else:
        sharpe = 0
    
    # Negative days/months
    trades_sorted['date'] = trades_sorted['exit_time'].dt.date
    trades_sorted['month'] = trades_sorted['exit_time'].dt.to_period('M')
    
    daily_pnl = trades_sorted.groupby('date')['pnl'].sum()
    monthly_pnl = trades_sorted.groupby('month')['pnl'].sum()
    
    neg_days = (daily_pnl < 0).sum()
    neg_months = (monthly_pnl < 0).sum()
    total_days = len(daily_pnl)
    total_months = len(monthly_pnl)
    
    return {
        'total_pnl': total_pnl,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'sharpe': sharpe,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'neg_days': neg_days,
        'neg_months': neg_months,
        'total_days': total_days,
        'total_months': total_months,
    }


def calculate_composite_score(metrics, weights=None):
    """
    Calculate composite score with customizable weights.
    
    Default weights:
    - pnl_weight: 0.25 (profitability)
    - win_rate_weight: 0.15 (consistency)
    - drawdown_weight: 0.30 (risk - most important)
    - sharpe_weight: 0.15 (risk-adjusted returns)
    - neg_months_weight: 0.15 (psychological sustainability)
    """
    
    if weights is None:
        weights = {
            'pnl': 0.25,
            'win_rate': 0.15,
            'drawdown': 0.30,  # Most important - lower drawdown is better
            'sharpe': 0.15,
            'neg_months': 0.15,
        }
    
    # Normalize metrics (0-1 scale)
    # For drawdown: lower is better, so invert
    drawdown_score = 1.0 / (1.0 + abs(metrics['max_drawdown_pct']) / 10.0)  # Normalize around 10% DD
    
    # For negative months: 0 is best
    neg_months_score = 1.0 / (1.0 + metrics['neg_months'])
    
    # PnL: normalize to positive scale
    pnl_score = max(0, metrics['total_pnl'] / 50000.0)  # Normalize around $50k
    pnl_score = min(1.0, pnl_score)  # Cap at 1.0
    
    # Win rate: already 0-1
    wr_score = metrics['win_rate']
    
    # Sharpe: normalize around 2.0
    sharpe_score = min(1.0, max(0, metrics['sharpe'] / 5.0))
    
    # Weighted composite
    score = (
        weights['pnl'] * pnl_score +
        weights['win_rate'] * wr_score +
        weights['drawdown'] * drawdown_score +
        weights['sharpe'] * sharpe_score +
        weights['neg_months'] * neg_months_score
    )
    
    return score


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MTF V2 Parameter Optimization (Replay-Based)")
    parser.add_argument("--start", type=str, default="2025-01-01", help="Backtest start date")
    parser.add_argument("--end", type=str, default=None, help="Backtest end date (default: latest 2025 data)")
    parser.add_argument("--speed", type=str, default="8x", help="Replay speed (1x, 2x, 4x, 8x, 16x)")
    parser.add_argument("--output", type=str, default="optimization_results", help="Output folder name")
    args = parser.parse_args()
    
    # Auto-detect latest 2025 data if end date not specified
    if args.end is None:
        from nautilus_trader.persistence.catalog import ParquetDataCatalog
        catalog = ParquetDataCatalog(str(PROJECT_ROOT / 'data' / 'historical'))
        bars = catalog.bars(bar_types=['EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL'])
        timestamps = [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in bars]
        df_ts = pd.DataFrame({'ts': timestamps})
        df_2025 = df_ts[df_ts['ts'].dt.year == 2025]
        if len(df_2025) > 0:
            args.end = df_2025['ts'].max().strftime('%Y-%m-%d')
        else:
            args.end = "2025-12-31"
    
    print("=" * 80)
    print("MTF V2 PARAMETER OPTIMIZATION (Backtest Replay)")
    print("=" * 80)
    print(f"Period: {args.start} to {args.end}")
    print(f"Replay Speed: {args.speed}")
    print()
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / 'optimization_results' / f"{args.output}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate parameter grid
    configs = generate_parameter_grid()
    print(f"Testing {len(configs)} parameter combinations...")
    # At 8x speed: ~3-5 minutes per backtest (full year of data)
    print(f"Estimated time: {len(configs) * 3} - {len(configs) * 5} minutes (~{len(configs) * 4 / 60:.1f} hours)")
    print()
    
    # Run optimizations
    results = []
    
    for i, config in enumerate(configs, 1):
        print(f"[{i}/{len(configs)}] Testing {config['name']}...")
        
        try:
            result_folder = run_backtest_with_params(
                config, 
                args.start, 
                args.end, 
                output_dir,
                replay_speed=args.speed
            )
            
            if result_folder is None:
                print("  FAILED - Skipping")
                continue
            
            metrics = analyze_backtest_results(result_folder)
            
            if metrics is None:
                print("  FAILED - No trades")
                continue
            
            # Calculate composite score
            score = calculate_composite_score(metrics)
            
            result = {
                'config': config['name'],
                'folder': result_folder.name,
                **config,
                **metrics,
                'score': score,
            }
            results.append(result)
            
            print(f"  PnL: ${metrics['total_pnl']:,.0f} | WR: {metrics['win_rate']:.1%} | "
                  f"DD: {metrics['max_drawdown_pct']:.1f}% | Score: {score:.3f}")
            
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
    
    if len(results) == 0:
        print("\nNo successful backtests!")
        return
    
    # Analyze results
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('score', ascending=False)
    
    # Save full results
    results_csv = output_dir / 'optimization_results.csv'
    df_results.to_csv(results_csv, index=False)
    print(f"\nFull results saved to: {results_csv}")
    
    # Print top results
    print("\n" + "=" * 80)
    print("TOP 10 CONFIGURATIONS (by composite score)")
    print("=" * 80)
    
    display_cols = ['config', 'total_pnl', 'win_rate', 'max_drawdown_pct', 'sharpe', 'neg_months', 'score']
    top10 = df_results[display_cols].head(10).copy()
    top10['total_pnl'] = top10['total_pnl'].apply(lambda x: f"${x:,.0f}")
    top10['win_rate'] = top10['win_rate'].apply(lambda x: f"{x:.1%}")
    top10['max_drawdown_pct'] = top10['max_drawdown_pct'].apply(lambda x: f"{x:.1f}%")
    top10['sharpe'] = top10['sharpe'].apply(lambda x: f"{x:.2f}")
    top10['score'] = top10['score'].apply(lambda x: f"{x:.3f}")
    
    print(top10.to_string(index=False))
    
    # Best configuration
    print("\n" + "=" * 80)
    print("BEST CONFIGURATION")
    print("=" * 80)
    best = df_results.iloc[0]
    print(f"Config: {best['config']}")
    print(f"Folder: {best['folder']}")
    print()
    print(f"Parameters:")
    print(f"  SL ATR Mult: {best['MTF2_SL_ATR_MULT']}")
    print(f"  TP ATR Mult: {best['MTF2_POS1_TP_ATR_MULT']}")
    print(f"  Trailing Distance: {best['MTF2_TRAILING_DISTANCE_ATR_MULT']}")
    print(f"  Prediction Threshold: {best['MTF2_PREDICTION_THRESHOLD']}")
    print(f"  Position Mode: Single (100%)")
    print()
    print(f"Performance:")
    print(f"  Total PnL: ${best['total_pnl']:,.2f}")
    print(f"  Win Rate: {best['win_rate']:.1%}")
    print(f"  Max Drawdown: ${best['max_drawdown']:,.2f} ({best['max_drawdown_pct']:.1f}%)")
    print(f"  Sharpe Ratio: {best['sharpe']:.2f}")
    print(f"  Trades: {best['num_trades']}")
    print(f"  Negative Days: {best['neg_days']}/{best['total_days']}")
    print(f"  Negative Months: {best['neg_months']}/{best['total_months']}")
    print(f"  Composite Score: {best['score']:.3f}")
    
    print("\n" + "=" * 80)
    print(f"All results saved to: {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
