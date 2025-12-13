"""
Phase 1: Three-Period Validation Test
Establishes TRUE baseline with proper train/validation/forward split
"""
import os
import subprocess
import json
from pathlib import Path
import shutil

def update_env_dates(start, end):
    """Update backtest dates in .env"""
    env_path = Path(".env")
    content = env_path.read_text()
    
    # Update dates
    lines = []
    for line in content.split('\n'):
        if line.startswith('BACKTEST_START_DATE='):
            lines.append(f'BACKTEST_START_DATE={start}')
        elif line.startswith('BACKTEST_END_DATE='):
            lines.append(f'BACKTEST_END_DATE={end}')
        else:
            lines.append(line)
    
    env_path.write_text('\n'.join(lines))
    print(f"✓ Updated .env: {start} → {end}")

def run_backtest(period_name):
    """Run backtest and return results"""
    print(f"\n{'='*80}")
    print(f"Running: {period_name}")
    print('='*80)
    
    result = subprocess.run(
        ["python", "backtest/run_backtest.py"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"❌ Backtest failed: {result.stderr}")
        return None
    
    # Find most recent results folder
    results_dir = Path("logs/backtest_results")
    folders = sorted(results_dir.glob("EUR-USD_*"), key=lambda x: x.stat().st_mtime)
    latest = folders[-1] if folders else None
    
    if not latest:
        print("❌ No results folder found")
        return None
    
    # Read performance stats
    stats_file = latest / "performance_stats.json"
    if not stats_file.exists():
        print("❌ No performance_stats.json found")
        return None
    
    with open(stats_file, 'r') as f:
        stats = json.load(f)
    
    # Read positions for trade count
    positions_file = latest / "positions.csv"
    if positions_file.exists():
        import pandas as pd
        positions = pd.read_csv(positions_file)
        trade_count = len(positions)
    else:
        trade_count = 0
    
    return {
        'period': period_name,
        'folder': latest.name,
        'pnl': stats['pnls']['PnL (total)'],
        'trades': trade_count,
        'win_rate': stats['pnls']['Win Rate'],
        'expectancy': stats['pnls']['Expectancy']
    }

def main():
    print("""
================================================================================
                   Phase 1: Three-Period Baseline Validation
================================================================================

Configuration: Trailing 35/15 + Partial Closes + NO TIME FILTER

Testing strategy across three independent periods:
  - Discovery (2022-2023): Find what works
  - Validation (2024): Confirm it holds
  - Forward (2025): True out-of-sample test

This establishes your HONEST baseline before adding complexity.
""")
    
    periods = [
        ("Discovery (2022-2023)", "2022-01-01", "2023-12-31"),
        ("Validation (2024)", "2024-01-01", "2024-12-31"),
        ("Forward (2025)", "2025-01-01", "2025-10-30"),
    ]
    
    results = []
    
    for name, start, end in periods:
        # Update config
        update_env_dates(start, end)
        
        # Run backtest
        result = run_backtest(name)
        if result:
            results.append(result)
            print(f"\n✓ {name}: ${result['pnl']:,.2f} ({result['trades']} trades)")
        else:
            print(f"\n❌ {name}: FAILED")
    
    # Summary
    print("\n" + "="*80)
    print("BASELINE VALIDATION SUMMARY")
    print("="*80)
    print(f"{'Period':<25} {'PnL':<15} {'Trades':<10} {'Win%':<10} {'Expectancy':<12}")
    print("-"*80)
    
    for r in results:
        print(f"{r['period']:<25} ${r['pnl']:>12,.2f}  {r['trades']:>6}     "
              f"{r['win_rate']*100:>5.1f}%    ${r['expectancy']:>8.2f}")
    
    if len(results) == 3:
        total_pnl = sum(r['pnl'] for r in results)
        total_trades = sum(r['trades'] for r in results)
        print("-"*80)
        print(f"{'TOTAL':<25} ${total_pnl:>12,.2f}  {total_trades:>6}")
        
        # Stability check
        pnls = [r['pnl'] for r in results]
        avg_pnl = total_pnl / 3
        std_pnl = (sum((p - avg_pnl)**2 for p in pnls) / 3) ** 0.5
        cv = std_pnl / avg_pnl if avg_pnl != 0 else float('inf')
        
        print("\n" + "="*80)
        print("STABILITY ANALYSIS")
        print("="*80)
        print(f"Average PnL per period: ${avg_pnl:,.2f}")
        print(f"Standard deviation: ${std_pnl:,.2f}")
        print(f"Coefficient of variation: {cv:.2%}")
        
        if cv < 0.30:
            print("✅ STABLE: Configuration performs consistently across periods")
        elif cv < 0.50:
            print("⚠️  MODERATE: Some variation between periods")
        else:
            print("❌ UNSTABLE: High variation suggests overfitting or regime-dependent performance")
        
        # Forward test interpretation
        print("\n" + "="*80)
        print("FORWARD TEST (2025) INTERPRETATION")
        print("="*80)
        forward_pnl = results[2]['pnl']
        avg_historical = (results[0]['pnl'] + results[1]['pnl']) / 2
        
        if forward_pnl >= avg_historical * 0.8:
            print("✅ PASSED: Forward performance within 20% of historical average")
            print("   → This is your TRUE baseline")
        elif forward_pnl >= avg_historical * 0.5:
            print("⚠️  DEGRADED: Forward performance dropped 20-50%")
            print("   → Strategy may be regime-dependent")
        else:
            print("❌ FAILED: Forward performance dropped >50%")
            print("   → Configuration is likely overfit or broken")
    
    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("1. If baseline is stable: Move to Phase 2 (add minimal logging)")
    print("2. If baseline is unstable: Simplify further (remove partial closes)")
    print("3. Save this as your TRUE baseline before testing improvements")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
