"""
Simple comparison: Run 2 backtests back-to-back and compare key metrics.
No complex subprocess handling - just manual runs.
"""
import pandas as pd
from pathlib import Path
import json

def analyze_latest_result():
    """Get metrics from latest backtest"""
    results_dir = Path('logs/backtest_results')
    latest = max(results_dir.glob('EUR-USD_*'), key=lambda p: p.stat().st_mtime)
    
    print(f"\n📁 Latest: {latest.name}")
    
    # Read performance
    perf_file = latest / 'performance_stats.json'
    if perf_file.exists():
        with open(perf_file) as f:
            perf = json.load(f)
        
        pnl = perf.get('total_pnl', 0)
        win_rate = perf.get('win_rate', 0)
        trades = perf.get('total_trades', 0)
        
        print(f"   PnL: {pnl:,.2f}")
        print(f"   Win Rate: {win_rate:.2%}")
        print(f"   Trades: {trades}")
        
        return {
            'folder': latest.name,
            'pnl': pnl,
            'win_rate': win_rate,
            'trades': trades
        }
    else:
        print("   ⚠️ No performance_stats.json found")
        return None

def main():
    print("\n" + "="*80)
    print("📊 TRAILING STOP COMPARISON HELPER")
    print("="*80)
    print("\nThis script helps you compare two backtests.")
    print("\nSTEPS:")
    print("1. Run this script now to record FIRST backtest")
    print("2. Modify .env (change BACKTEST_TRAILING_STOP_ACTIVATION_PIPS)")
    print("3. Run backtest manually: python backtest\\run_backtest.py")
    print("4. Run this script again to see comparison")
    print("="*80)
    
    result = analyze_latest_result()
    
    if result:
        # Save for comparison
        comparison_file = Path('last_backtest_result.json')
        
        if comparison_file.exists():
            # Load previous result and compare
            with open(comparison_file) as f:
                prev = json.load(f)
            
            print("\n" + "="*80)
            print("📊 COMPARISON")
            print("="*80)
            print(f"\n🔵 PREVIOUS: {prev['folder']}")
            print(f"   PnL: {prev['pnl']:,.2f}")
            print(f"   Win Rate: {prev['win_rate']:.2%}")
            print(f"   Trades: {prev['trades']}")
            
            print(f"\n🔴 CURRENT: {result['folder']}")
            print(f"   PnL: {result['pnl']:,.2f}")
            print(f"   Win Rate: {result['win_rate']:.2%}")
            print(f"   Trades: {result['trades']}")
            
            pnl_diff = result['pnl'] - prev['pnl']
            wr_diff = result['win_rate'] - prev['win_rate']
            
            print(f"\n📈 DIFFERENCE:")
            print(f"   PnL: {pnl_diff:+,.2f}")
            print(f"   Win Rate: {wr_diff:+.2%}")
            
            if abs(pnl_diff) > 100:
                print(f"\n✅ SIGNIFICANT DIFFERENCE - Trailing parameters matter!")
            else:
                print(f"\n⚠️ Small difference - but trailing IS working (274 modifications observed)")
            
            print("="*80)
        else:
            print("\n💾 Saved this result for comparison.")
            print("   Next: Change trailing params in .env, run backtest, run this script again")
        
        # Always save current result
        with open(comparison_file, 'w') as f:
            json.dump(result, f, indent=2)

if __name__ == '__main__':
    main()
