#!/usr/bin/env python3
"""
CRITICAL DISCOVERY: Previous optimizations assumed trailing stops were working!

From the .env and optimization files, I can see:
- TRAILING_STOP_ACTIVATION_PIPS=25 and TRAILING_STOP_DISTANCE_PIPS=20 were optimized
- Multiple optimization phases included trailing parameters (eurusd_regime_optimization.json, etc.)
- Current config has complex regime-based trailing multipliers
- Duration-based trailing was added and enabled

This means ALL previous optimizations were done under the assumption that trailing was functional,
but it was actually broken. The "optimal" parameters are likely completely wrong.

IMMEDIATE ACTIONS NEEDED:
1. Test current config with trailing DISABLED vs ENABLED
2. Re-run key optimization grids with actually working trailing
3. Re-validate the entire parameter set from scratch
"""

import json
from pathlib import Path
import subprocess
import shutil
from datetime import datetime

class ReOptimizationManager:
    def __init__(self):
        self.base_env = Path('.env')
        self.results_dir = Path('re_optimization_results')
        self.results_dir.mkdir(exist_ok=True)
        
    def backup_current_env(self):
        """Backup current .env as baseline"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = self.results_dir / f'.env.baseline_{timestamp}'
        shutil.copy(self.base_env, backup_path)
        print(f"✅ Backed up current .env to: {backup_path}")
        return backup_path
        
    def create_trailing_disabled_env(self):
        """Create .env with trailing completely disabled for comparison"""
        with open(self.base_env, 'r') as f:
            content = f.read()
        
        # Disable trailing by setting activation to a very high value
        # This effectively disables trailing without changing the strategy code
        disabled_content = content.replace(
            'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=25',
            'BACKTEST_TRAILING_STOP_ACTIVATION_PIPS=1000'  # Never activates
        )
        
        # Also disable duration-based trailing
        disabled_content = disabled_content.replace(
            'STRATEGY_TRAILING_DURATION_ENABLED=true',
            'STRATEGY_TRAILING_DURATION_ENABLED=false'
        )
        
        disabled_env_path = self.results_dir / '.env.trailing_disabled'
        with open(disabled_env_path, 'w') as f:
            f.write(disabled_content)
            
        print(f"✅ Created trailing-disabled config: {disabled_env_path}")
        return disabled_env_path
        
    def run_comparison_test(self):
        """Run trailing ON vs OFF comparison"""
        print("\n" + "="*60)
        print("PHASE 0: TRAILING ON vs OFF COMPARISON")
        print("="*60)
        
        # Backup current env
        baseline_backup = self.backup_current_env()
        
        # Create disabled version
        disabled_env = self.create_trailing_disabled_env()
        
        print("\n🔄 Running TRAILING DISABLED backtest...")
        # Copy disabled env to active .env
        shutil.copy(disabled_env, self.base_env)
        
        # Run backtest with trailing disabled
        result = subprocess.run(['python', 'backtest/run_backtest.py'], 
                              capture_output=True, text=True, cwd='.')
        
        if result.returncode == 0:
            print("✅ Trailing DISABLED backtest completed")
            # Move results to labeled folder
            latest_result = self.get_latest_result_folder()
            if latest_result:
                disabled_result_dir = self.results_dir / 'trailing_DISABLED'
                if disabled_result_dir.exists():
                    shutil.rmtree(disabled_result_dir)
                shutil.move(latest_result, disabled_result_dir)
                print(f"📁 Results saved to: {disabled_result_dir}")
        else:
            print(f"❌ Trailing DISABLED backtest failed: {result.stderr}")
            return False
            
        print("\n🔄 Running TRAILING ENABLED backtest...")
        # Restore original env (with trailing enabled)
        shutil.copy(baseline_backup, self.base_env)
        
        # Run backtest with trailing enabled
        result = subprocess.run(['python', 'backtest/run_backtest.py'], 
                              capture_output=True, text=True, cwd='.')
        
        if result.returncode == 0:
            print("✅ Trailing ENABLED backtest completed")
            # Move results to labeled folder
            latest_result = self.get_latest_result_folder()
            if latest_result:
                enabled_result_dir = self.results_dir / 'trailing_ENABLED'
                if enabled_result_dir.exists():
                    shutil.rmtree(enabled_result_dir)
                shutil.move(latest_result, enabled_result_dir)
                print(f"📁 Results saved to: {enabled_result_dir}")
        else:
            print(f"❌ Trailing ENABLED backtest failed: {result.stderr}")
            return False
            
        return True
        
    def analyze_comparison_results(self):
        """Analyze and compare the trailing ON vs OFF results"""
        disabled_dir = self.results_dir / 'trailing_DISABLED'
        enabled_dir = self.results_dir / 'trailing_ENABLED'
        
        if not (disabled_dir.exists() and enabled_dir.exists()):
            print("❌ Missing comparison results directories")
            return
            
        print("\n" + "="*60)
        print("COMPARISON ANALYSIS: TRAILING IMPACT")
        print("="*60)
        
        # Read performance stats from both runs
        try:
            with open(disabled_dir / 'performance_stats.json') as f:
                disabled_stats = json.load(f)
            with open(enabled_dir / 'performance_stats.json') as f:
                enabled_stats = json.load(f)
                
            print(f"\n📊 TRAILING DISABLED:")
            print(f"   Total PnL: ${disabled_stats.get('total_pnl', 'N/A')}")
            print(f"   Total Trades: {disabled_stats.get('total_trades', 'N/A')}")
            print(f"   Win Rate: {disabled_stats.get('win_rate', 'N/A')}")
            
            print(f"\n📊 TRAILING ENABLED:")
            print(f"   Total PnL: ${enabled_stats.get('total_pnl', 'N/A')}")
            print(f"   Total Trades: {enabled_stats.get('total_trades', 'N/A')}")
            print(f"   Win Rate: {enabled_stats.get('win_rate', 'N/A')}")
            
            # Calculate impact
            if 'total_pnl' in disabled_stats and 'total_pnl' in enabled_stats:
                pnl_diff = enabled_stats['total_pnl'] - disabled_stats['total_pnl']
                pnl_pct = (pnl_diff / abs(disabled_stats['total_pnl'])) * 100 if disabled_stats['total_pnl'] != 0 else float('inf')
                
                print(f"\n💡 TRAILING IMPACT:")
                print(f"   PnL Difference: ${pnl_diff:+.2f}")
                print(f"   Percentage Change: {pnl_pct:+.1f}%")
                
                if pnl_diff > 0:
                    print("✅ CONCLUSION: Trailing stops are BENEFICIAL - proceed with re-optimization")
                else:
                    print("❌ CONCLUSION: Trailing stops are HARMFUL - consider disabling or major parameter changes")
                    
        except Exception as e:
            print(f"❌ Error analyzing results: {e}")
            
    def get_latest_result_folder(self):
        """Get the most recent backtest result folder"""
        results_base = Path('logs/backtest_results')
        if not results_base.exists():
            return None
            
        folders = [f for f in results_base.iterdir() if f.is_dir() and f.name.startswith('EUR-USD_')]
        if not folders:
            return None
            
        return max(folders, key=lambda x: x.stat().st_mtime)
        
    def create_phase1_optimization_grid(self):
        """Create Phase 1 optimization grid: Core parameters with working trailing"""
        
        # Basic grid around current values but more conservative
        # Since trailing extends profitable trades, we might need tighter initial SL/TP
        phase1_grid = {
            "description": "Phase 1: Core SL/TP/Trailing re-optimization with WORKING trailing stops",
            "comment": "Conservative grid around current values. Trailing now functional may change optimal SL/TP.",
            
            # Core SL/TP - test tighter values since trailing can extend winners
            "BACKTEST_STOP_LOSS_PIPS": [15, 20, 25, 30],
            "BACKTEST_TAKE_PROFIT_PIPS": [50, 60, 70, 80, 90],
            
            # Trailing activation - when to start trailing (critical parameter)
            "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": [15, 20, 25, 30, 35],
            
            # Trailing distance - how tight to trail
            "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": [10, 15, 20, 25],
            
            # Disable complex features for now to isolate core trailing impact
            "STRATEGY_REGIME_DETECTION_ENABLED": [False],
            "STRATEGY_TRAILING_DURATION_ENABLED": [False],
            
            # Keep other successful features
            "BACKTEST_TIME_FILTER_ENABLED": [True],
            "STRATEGY_TIME_MULTIPLIER_ENABLED": [True]
        }
        
        # Total combinations: 4 * 5 * 5 * 4 = 400 combinations
        # At ~45 seconds per run = ~5 hours
        
        grid_path = self.results_dir / 'phase1_core_trailing_grid.json'
        with open(grid_path, 'w') as f:
            json.dump(phase1_grid, f, indent=2)
            
        print(f"✅ Created Phase 1 optimization grid: {grid_path}")
        print(f"   Total combinations: 400 (~5 hours)")
        return grid_path
        
    def run_full_phase0_analysis(self):
        """Execute the complete Phase 0 analysis"""
        print("🚀 Starting PHASE 0: Re-optimization Analysis")
        print("This will determine if we need to re-optimize everything or just trailing parameters")
        
        # Step 1: Run comparison
        if not self.run_comparison_test():
            print("❌ Comparison test failed - cannot proceed")
            return False
            
        # Step 2: Analyze results
        self.analyze_comparison_results()
        
        # Step 3: Create next phase grid
        self.create_phase1_optimization_grid()
        
        print("\n" + "="*60)
        print("PHASE 0 COMPLETE")
        print("="*60)
        print("✅ Trailing ON vs OFF comparison completed")
        print("📁 Results saved in: re_optimization_results/")
        print("📋 Next: Run Phase 1 grid optimization")
        print("   Command: python optimize_grid.py re_optimization_results/phase1_core_trailing_grid.json")
        
        return True

if __name__ == "__main__":
    manager = ReOptimizationManager()
    manager.run_full_phase0_analysis()