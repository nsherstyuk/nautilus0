"""
Comprehensive test script for multi-timeframe features.
Runs all test scenarios and generates a detailed report.
"""
import os
import sys
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

def load_backtest_results(output_dir: Path) -> Optional[Dict[str, Any]]:
    """Load performance stats from backtest results."""
    stats_file = output_dir / "performance_stats.json"
    if not stats_file.exists():
        return None
    
    try:
        with open(stats_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading stats: {e}")
        return None

def extract_key_metrics(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key metrics from performance stats."""
    pnls = stats.get("pnls", {})
    general = stats.get("general", {})
    
    return {
        "total_pnl": pnls.get("PnL (total)", 0.0),
        "pnl_percentage": pnls.get("PnL% (total)", 0.0),
        "sharpe_ratio": general.get("Sharpe ratio", 0.0) or general.get("Sharpe Ratio (30-day)", 0.0),
        "win_rate": pnls.get("Win Rate", 0.0),
        "trade_count": general.get("Total trades", 0) or general.get("Total Trades", 0),
        "max_drawdown": general.get("Max drawdown", 0.0) or general.get("Max Drawdown%", 0.0),
        "profit_factor": general.get("Profit factor", 0.0) or pnls.get("Profit Factor", 0.0),
        "avg_winner": pnls.get("Avg Winner", 0.0),
        "avg_loser": pnls.get("Avg Loser", 0.0),
        "rejected_signals": stats.get("rejected_signals_count", 0),
    }

def run_backtest(env_vars: Dict[str, str], test_name: str) -> tuple[Optional[Path], Optional[str]]:
    """Run a backtest with specified environment variables."""
    print(f"\n{'='*60}")
    print(f"Running: {test_name}")
    print(f"{'='*60}")
    
    # Set environment variables
    env = os.environ.copy()
    env.update(env_vars)
    
    # Run backtest
    start_time = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=600  # 10 minute timeout
        )
        duration = time.time() - start_time
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            print(f"[ERROR] Backtest failed: {error_msg[-500:]}")
            return None, error_msg
        
        # Find output directory - check latest directory in results folder
        output_dir = None
        results_dir = Path("logs/backtest_results")
        if results_dir.exists():
            dirs = sorted([d for d in results_dir.iterdir() if d.is_dir()], 
                        key=lambda d: d.stat().st_mtime, reverse=True)
            if dirs:
                output_dir = dirs[0]
        
        # Also try parsing stdout for output directory
        if output_dir is None and result.stdout:
            output_lines = result.stdout.split('\n')
            for line in output_lines:
                if 'output directory' in line.lower() or 'results saved' in line.lower() or 'backtest_results' in line.lower():
                    # Try to extract path
                    parts = line.split()
                    for part in parts:
                        if 'logs/backtest_results' in part or 'backtest_results' in part:
                            candidate = Path(part.strip('.,;'))
                            if candidate.exists():
                                output_dir = candidate
                                break
                    if output_dir:
                        break
        
        if output_dir and output_dir.exists():
            print(f"[OK] Backtest completed in {duration:.1f}s")
            print(f"     Output: {output_dir}")
            return output_dir, None
        else:
            print(f"[WARN] Could not find output directory")
            return None, "Output directory not found"
            
    except subprocess.TimeoutExpired:
        return None, "Backtest timed out after 10 minutes"
    except Exception as e:
        return None, str(e)

def compare_results(baseline: Dict[str, Any], test: Dict[str, Any], test_name: str) -> Dict[str, Any]:
    """Compare test results with baseline."""
    comparison = {
        "test_name": test_name,
        "metrics": {}
    }
    
    for key in baseline.keys():
        baseline_val = baseline[key]
        test_val = test.get(key, 0)
        
        if baseline_val == 0:
            change_pct = 0.0 if test_val == 0 else float('inf')
        else:
            change_pct = ((test_val - baseline_val) / abs(baseline_val)) * 100
        
        comparison["metrics"][key] = {
            "baseline": baseline_val,
            "test": test_val,
            "change": test_val - baseline_val,
            "change_pct": change_pct
        }
    
    return comparison

def main():
    """Run all test scenarios."""
    print("="*60)
    print("MULTI-TIMEFRAME FEATURE TESTING")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {
        "baseline": None,
        "trend_filter": None,
        "entry_timing": None,
        "combined": None,
        "errors": []
    }
    
    # Base environment variables
    base_env = {
        "BACKTEST_SYMBOL": os.getenv("BACKTEST_SYMBOL", "EUR/USD"),
        "BACKTEST_START_DATE": os.getenv("BACKTEST_START_DATE", "2025-01-01"),
        "BACKTEST_END_DATE": os.getenv("BACKTEST_END_DATE", "2025-10-30"),
        "BACKTEST_BAR_SPEC": "15-MINUTE-MID-EXTERNAL",
        "BACKTEST_FAST_PERIOD": "42",
        "BACKTEST_SLOW_PERIOD": "270",
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS": "0.35",
        "BACKTEST_STOP_LOSS_PIPS": "35",
        "BACKTEST_TAKE_PROFIT_PIPS": "50",
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "22",
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "12",
        "STRATEGY_DMI_ENABLED": "true",
        "STRATEGY_DMI_PERIOD": "10",
        "STRATEGY_STOCH_ENABLED": "true",
        "STRATEGY_STOCH_PERIOD_K": "18",
        "STRATEGY_STOCH_PERIOD_D": "3",
        "STRATEGY_STOCH_BULLISH_THRESHOLD": "30",
        "STRATEGY_STOCH_BEARISH_THRESHOLD": "65",
    }
    
    # Test 1: Baseline (zero impact verification)
    print("\n" + "="*60)
    print("TEST 1: BASELINE (Zero Impact Verification)")
    print("="*60)
    baseline_env = base_env.copy()
    baseline_env.update({
        "BACKTEST_TREND_FILTER_ENABLED": "false",
        "BACKTEST_ENTRY_TIMING_ENABLED": "false",
    })
    
    output_dir, error = run_backtest(baseline_env, "Baseline (features disabled)")
    if error:
        results["errors"].append({"test": "baseline", "error": error})
        print(f"[ERROR] Baseline test failed: {error}")
    elif output_dir:
        stats = load_backtest_results(output_dir)
        if stats:
            results["baseline"] = {
                "output_dir": str(output_dir),
                "metrics": extract_key_metrics(stats),
                "stats": stats
            }
            print("[OK] Baseline test completed successfully")
        else:
            results["errors"].append({"test": "baseline", "error": "Could not load stats"})
    
    if not results["baseline"]:
        print("[ERROR] Cannot continue without baseline. Aborting.")
        return
    
    # Base environment variables
    base_env = {
        "BACKTEST_SYMBOL": os.getenv("BACKTEST_SYMBOL", "EUR/USD"),
        "BACKTEST_START_DATE": os.getenv("BACKTEST_START_DATE", "2025-01-01"),
        "BACKTEST_END_DATE": os.getenv("BACKTEST_END_DATE", "2025-10-30"),
        "BACKTEST_BAR_SPEC": "15-MINUTE-MID-EXTERNAL",
        "BACKTEST_FAST_PERIOD": "42",
        "BACKTEST_SLOW_PERIOD": "270",
        "STRATEGY_CROSSOVER_THRESHOLD_PIPS": "0.35",
        "BACKTEST_STOP_LOSS_PIPS": "35",
        "BACKTEST_TAKE_PROFIT_PIPS": "50",
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": "22",
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": "12",
        "STRATEGY_DMI_ENABLED": "true",
        "STRATEGY_DMI_PERIOD": "10",
        "STRATEGY_STOCH_ENABLED": "true",
        "STRATEGY_STOCH_PERIOD_K": "18",
        "STRATEGY_STOCH_PERIOD_D": "3",
        "STRATEGY_STOCH_BULLISH_THRESHOLD": "30",
        "STRATEGY_STOCH_BEARISH_THRESHOLD": "65",
    }
    
    # Test 1: Baseline (zero impact verification)
    print("\n" + "="*60)
    print("TEST 1: BASELINE (Zero Impact Verification)")
    print("="*60)
    baseline_env = base_env.copy()
    baseline_env.update({
        "BACKTEST_TREND_FILTER_ENABLED": "false",
        "BACKTEST_ENTRY_TIMING_ENABLED": "false",
    })
    
    output_dir, error = run_backtest(baseline_env, "Baseline (features disabled)")
    if error:
        results["errors"].append({"test": "baseline", "error": error})
        print(f"[ERROR] Baseline test failed: {error}")
    elif output_dir:
        stats = load_backtest_results(output_dir)
        if stats:
            results["baseline"] = {
                "output_dir": str(output_dir),
                "metrics": extract_key_metrics(stats),
                "stats": stats
            }
            print("[OK] Baseline test completed successfully")
        else:
            results["errors"].append({"test": "baseline", "error": "Could not load stats"})
    
    if not results["baseline"]:
        print("[ERROR] Cannot continue without baseline. Aborting.")
        return
    
    # Test 2: Trend Filter (using 1-DAY bars since 1-HOUR not available)
    print("\n" + "="*60)
    print("TEST 2: TREND FILTER ENABLED")
    print("="*60)
    trend_env = base_env.copy()
    trend_env.update({
        "BACKTEST_TREND_FILTER_ENABLED": "true",
        "BACKTEST_TREND_BAR_SPEC": "1-DAY-MID-EXTERNAL",  # Use available bar type
        "BACKTEST_TREND_FAST_PERIOD": "20",
        "BACKTEST_TREND_SLOW_PERIOD": "50",
        "BACKTEST_ENTRY_TIMING_ENABLED": "false",
    })
    
    output_dir, error = run_backtest(trend_env, "Trend Filter Enabled (1-DAY)")
    if error:
        results["errors"].append({"test": "trend_filter", "error": error})
        print(f"[ERROR] Trend filter test failed: {error}")
    elif output_dir:
        stats = load_backtest_results(output_dir)
        if stats:
            results["trend_filter"] = {
                "output_dir": str(output_dir),
                "metrics": extract_key_metrics(stats),
                "stats": stats
            }
            print("[OK] Trend filter test completed successfully")
        else:
            results["errors"].append({"test": "trend_filter", "error": "Could not load stats"})
    
    # Test 3: Entry Timing (using 2-MINUTE bars since 5-MINUTE not available)
    print("\n" + "="*60)
    print("TEST 3: ENTRY TIMING ENABLED")
    print("="*60)
    entry_env = base_env.copy()
    entry_env.update({
        "BACKTEST_TREND_FILTER_ENABLED": "false",
        "BACKTEST_ENTRY_TIMING_ENABLED": "true",
        "BACKTEST_ENTRY_TIMING_BAR_SPEC": "2-MINUTE-MID-EXTERNAL",  # Use available bar type
        "BACKTEST_ENTRY_TIMING_METHOD": "pullback",
        "BACKTEST_ENTRY_TIMING_TIMEOUT_BARS": "10",
    })
    
    output_dir, error = run_backtest(entry_env, "Entry Timing Enabled (2-MINUTE)")
    if error:
        results["errors"].append({"test": "entry_timing", "error": error})
        print(f"[ERROR] Entry timing test failed: {error}")
    elif output_dir:
        stats = load_backtest_results(output_dir)
        if stats:
            results["entry_timing"] = {
                "output_dir": str(output_dir),
                "metrics": extract_key_metrics(stats),
                "stats": stats
            }
            print("[OK] Entry timing test completed successfully")
        else:
            results["errors"].append({"test": "entry_timing", "error": "Could not load stats"})
    
    # Test 4: Combined (using available bar types)
    print("\n" + "="*60)
    print("TEST 4: COMBINED (Both Features Enabled)")
    print("="*60)
    combined_env = base_env.copy()
    combined_env.update({
        "BACKTEST_TREND_FILTER_ENABLED": "true",
        "BACKTEST_TREND_BAR_SPEC": "1-DAY-MID-EXTERNAL",  # Use available bar type
        "BACKTEST_TREND_FAST_PERIOD": "20",
        "BACKTEST_TREND_SLOW_PERIOD": "50",
        "BACKTEST_ENTRY_TIMING_ENABLED": "true",
        "BACKTEST_ENTRY_TIMING_BAR_SPEC": "2-MINUTE-MID-EXTERNAL",  # Use available bar type
        "BACKTEST_ENTRY_TIMING_METHOD": "pullback",
        "BACKTEST_ENTRY_TIMING_TIMEOUT_BARS": "10",
    })
    
    output_dir, error = run_backtest(combined_env, "Combined Features")
    if error:
        results["errors"].append({"test": "combined", "error": error})
        print(f"[ERROR] Combined test failed: {error}")
    elif output_dir:
        stats = load_backtest_results(output_dir)
        if stats:
            results["combined"] = {
                "output_dir": str(output_dir),
                "metrics": extract_key_metrics(stats),
                "stats": stats
            }
            print("[OK] Combined test completed successfully")
        else:
            results["errors"].append({"test": "combined", "error": "Could not load stats"})
    
    # Generate report
    print("\n" + "="*60)
    print("GENERATING REPORT")
    print("="*60)
    
    report_path = Path("logs/test_reports/multi_tf_test_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Generate comparison table
    print("\n" + "="*60)
    print("COMPARISON TABLE")
    print("="*60)
    
    if results["baseline"]:
        baseline_metrics = results["baseline"]["metrics"]
        print(f"\n{'Metric':<25} {'Baseline':<15} {'Trend Filter':<15} {'Entry Timing':<15} {'Combined':<15}")
        print("-" * 85)
        
        for metric in baseline_metrics.keys():
            baseline_val = baseline_metrics[metric]
            trend_val = results["trend_filter"]["metrics"][metric] if results["trend_filter"] else "N/A"
            entry_val = results["entry_timing"]["metrics"][metric] if results["entry_timing"] else "N/A"
            combined_val = results["combined"]["metrics"][metric] if results["combined"] else "N/A"
            
            print(f"{metric:<25} {baseline_val:<15.2f} {trend_val:<15} {entry_val:<15} {combined_val:<15}")
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Baseline: {'PASS' if results['baseline'] else 'FAIL'}")
    print(f"Trend Filter: {'PASS' if results['trend_filter'] else 'FAIL'}")
    print(f"Entry Timing: {'PASS' if results['entry_timing'] else 'FAIL'}")
    print(f"Combined: {'PASS' if results['combined'] else 'FAIL'}")
    
    if results["errors"]:
        print(f"\nErrors encountered: {len(results['errors'])}")
        for error in results["errors"]:
            print(f"  - {error['test']}: {error['error'][:100]}")
    
    print(f"\nReport saved to: {report_path}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()

