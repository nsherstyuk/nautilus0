"""
Automated Multi-Timeframe Optimization Runner
Runs optimization steps automatically and generates a report.
"""
import sys
import os
import subprocess
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def load_env_vars():
    """Load environment variables from .env file."""
    env_vars = {}
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

def run_optimization(config_file, output_file, workers=15):
    """Run grid search optimization."""
    print(f"\n{'='*80}")
    print(f"Running optimization: {config_file.name}")
    print(f"{'='*80}\n")
    
    env = load_env_vars()
    env.update(os.environ)
    
    cmd = [
        sys.executable,
        "optimization/grid_search.py",
        "--config", str(config_file),
        "--objective", "sharpe_ratio",
        "--workers", str(workers),
        "--output", str(output_file),
        "--no-resume"
    ]
    
    result = subprocess.run(cmd, env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ERROR: Optimization failed!")
        print(result.stderr)
        return False
    
    print("Optimization completed successfully!")
    return True

def analyze_results(csv_file):
    """Analyze optimization results."""
    if not csv_file.exists():
        return None
    
    df = pd.read_csv(csv_file)
    df = df[df['status'] == 'completed'].copy()
    
    if len(df) == 0:
        return None
    
    analysis = {
        'total_runs': len(df),
        'best_overall': None,
        'by_timeframe': {}
    }
    
    # Best overall
    best_idx = df['sharpe_ratio'].idxmax()
    analysis['best_overall'] = {
        'sharpe': df.loc[best_idx, 'sharpe_ratio'],
        'pnl': df.loc[best_idx, 'total_pnl'],
        'win_rate': df.loc[best_idx, 'win_rate'],
        'trades': int(df.loc[best_idx, 'trade_count']),
        'bar_spec': df.loc[best_idx, 'bar_spec'] if 'bar_spec' in df.columns else 'N/A',
        'fast_period': df.loc[best_idx, 'fast_period'] if 'fast_period' in df.columns else 'N/A',
        'slow_period': df.loc[best_idx, 'slow_period'] if 'slow_period' in df.columns else 'N/A',
        'stop_loss': df.loc[best_idx, 'stop_loss_pips'] if 'stop_loss_pips' in df.columns else 'N/A',
        'take_profit': df.loc[best_idx, 'take_profit_pips'] if 'take_profit_pips' in df.columns else 'N/A',
    }
    
    # By timeframe if bar_spec exists
    if 'bar_spec' in df.columns:
        for timeframe in df['bar_spec'].unique():
            tf_df = df[df['bar_spec'] == timeframe]
            best_tf_idx = tf_df['sharpe_ratio'].idxmax()
            analysis['by_timeframe'][timeframe] = {
                'sharpe': tf_df.loc[best_tf_idx, 'sharpe_ratio'],
                'pnl': tf_df.loc[best_tf_idx, 'total_pnl'],
                'win_rate': tf_df.loc[best_tf_idx, 'win_rate'],
                'trades': int(tf_df.loc[best_tf_idx, 'trade_count']),
                'configs_tested': len(tf_df),
                'avg_sharpe': tf_df['sharpe_ratio'].mean(),
            }
    
    return analysis

def generate_report(focused_analysis, comprehensive_analysis=None):
    """Generate optimization report."""
    baseline_sharpe = 0.481
    baseline_pnl = 10859.43
    
    report = []
    report.append("="*100)
    report.append("MULTI-TIMEFRAME OPTIMIZATION REPORT")
    report.append("="*100)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("BASELINE (Phase 6 - 15-MINUTE):")
    report.append(f"  Sharpe Ratio: {baseline_sharpe:.3f}")
    report.append(f"  Total PnL: ${baseline_pnl:,.2f}")
    report.append("")
    
    if focused_analysis:
        report.append("="*100)
        report.append("FOCUSED OPTIMIZATION RESULTS (20 combinations)")
        report.append("="*100)
        report.append("")
        
        best = focused_analysis['best_overall']
        report.append(f"Best Overall Result:")
        report.append(f"  Sharpe Ratio: {best['sharpe']:.3f} ({'+' if best['sharpe'] > baseline_sharpe else ''}{best['sharpe'] - baseline_sharpe:+.3f} vs baseline)")
        report.append(f"  Total PnL: ${best['pnl']:,.2f} ({'+' if best['pnl'] > baseline_pnl else ''}{best['pnl'] - baseline_pnl:+,.2f} vs baseline)")
        report.append(f"  Win Rate: {best['win_rate']*100:.1f}%")
        report.append(f"  Trade Count: {best['trades']}")
        report.append(f"  Timeframe: {best['bar_spec']}")
        report.append(f"  MA: fast={best['fast_period']}, slow={best['slow_period']}")
        report.append(f"  Risk: SL={best['stop_loss']}, TP={best['take_profit']}")
        report.append("")
        
        if focused_analysis['by_timeframe']:
            report.append("Performance by Timeframe:")
            sorted_tf = sorted(focused_analysis['by_timeframe'].items(), 
                             key=lambda x: x[1]['sharpe'], reverse=True)
            for tf, stats in sorted_tf:
                improvement = stats['sharpe'] - baseline_sharpe
                report.append(f"  {tf}:")
                report.append(f"    Sharpe: {stats['sharpe']:.3f} ({'+' if improvement > 0 else ''}{improvement:+.3f})")
                report.append(f"    PnL: ${stats['pnl']:,.2f}")
                report.append(f"    Win Rate: {stats['win_rate']*100:.1f}%")
                report.append(f"    Configs tested: {stats['configs_tested']}")
            report.append("")
    
    if comprehensive_analysis:
        report.append("="*100)
        report.append("COMPREHENSIVE OPTIMIZATION RESULTS (216 combinations)")
        report.append("="*100)
        report.append("")
        
        best = comprehensive_analysis['best_overall']
        report.append(f"Best Overall Result:")
        report.append(f"  Sharpe Ratio: {best['sharpe']:.3f} ({'+' if best['sharpe'] > baseline_sharpe else ''}{best['sharpe'] - baseline_sharpe:+.3f} vs baseline)")
        report.append(f"  Total PnL: ${best['pnl']:,.2f} ({'+' if best['pnl'] > baseline_pnl else ''}{best['pnl'] - baseline_pnl:+,.2f} vs baseline)")
        report.append(f"  Timeframe: {best['bar_spec']}")
        report.append(f"  Parameters: fast={best['fast_period']}, slow={best['slow_period']}, SL={best['stop_loss']}, TP={best['take_profit']}")
        report.append("")
    
    # Recommendations
    report.append("="*100)
    report.append("RECOMMENDATIONS")
    report.append("="*100)
    report.append("")
    
    if focused_analysis:
        best = focused_analysis['best_overall']
        if best['sharpe'] > baseline_sharpe:
            report.append(f"✓ BETTER CONFIGURATION FOUND!")
            report.append(f"  Best timeframe: {best['bar_spec']}")
            report.append(f"  Improvement: Sharpe {best['sharpe'] - baseline_sharpe:+.3f} ({((best['sharpe']/baseline_sharpe - 1)*100):+.1f}%)")
            report.append(f"  PnL improvement: ${best['pnl'] - baseline_pnl:+,.2f}")
            report.append("")
            report.append("Recommended Configuration:")
            report.append(f"  BACKTEST_BAR_SPEC={best['bar_spec']}")
            report.append(f"  BACKTEST_FAST_PERIOD={best['fast_period']}")
            report.append(f"  BACKTEST_SLOW_PERIOD={best['slow_period']}")
            report.append(f"  BACKTEST_STOP_LOSS_PIPS={best['stop_loss']}")
            report.append(f"  BACKTEST_TAKE_PROFIT_PIPS={best['take_profit']}")
        else:
            report.append("No better configuration found than baseline (15-MINUTE).")
            report.append("Current baseline remains optimal.")
    else:
        report.append("No results available for analysis.")
    
    report.append("")
    report.append("="*100)
    
    return "\n".join(report)

def main():
    import os
    
    print("="*100)
    print("AUTOMATED MULTI-TIMEFRAME OPTIMIZATION")
    print("="*100)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Step 1: Run focused optimization
    print("STEP 1: Running focused multi-timeframe optimization...")
    focused_config = Path("optimization/configs/multi_timeframe_focused.yaml")
    focused_output = Path("optimization/results/multi_timeframe_focused_results.csv")
    
    if not run_optimization(focused_config, focused_output, workers=15):
        print("ERROR: Focused optimization failed. Aborting.")
        return 1
    
    # Step 2: Analyze focused results
    print("\nSTEP 2: Analyzing focused optimization results...")
    focused_analysis = analyze_results(focused_output)
    
    if not focused_analysis:
        print("ERROR: No results to analyze. Aborting.")
        return 1
    
    best_sharpe = focused_analysis['best_overall']['sharpe']
    baseline_sharpe = 0.481
    
    print(f"Best Sharpe found: {best_sharpe:.3f} (baseline: {baseline_sharpe:.3f})")
    
    # Step 3: Run extended optimization to explore more parameter combinations
    comprehensive_analysis = None
    print(f"\nSTEP 3: Running extended optimization with wider parameter ranges...")
    extended_config = Path("optimization/configs/multi_timeframe_extended.yaml")
    extended_output = Path("optimization/results/multi_timeframe_extended_results.csv")
    
    if run_optimization(extended_config, extended_output, workers=15):
        comprehensive_analysis = analyze_results(extended_output)
    
    # Step 4: Generate report
    print("\nSTEP 4: Generating optimization report...")
    report = generate_report(focused_analysis, comprehensive_analysis)
    
    # Save report
    report_file = Path("optimization/results/MULTI_TIMEFRAME_OPTIMIZATION_REPORT.md")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(report)
    print(f"\nReport saved to: {report_file}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

