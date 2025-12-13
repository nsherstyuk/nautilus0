"""
Trading System Verification
Analyzes code flow and identifies potential issues for both live and backtest
"""
import ast
import re
from pathlib import Path
from typing import List, Dict, Tuple

class SystemVerifier:
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.info = []
        
    def add_issue(self, category: str, file: str, line: int, message: str):
        self.issues.append({
            'category': category,
            'file': file,
            'line': line,
            'severity': 'ERROR',
            'message': message
        })
    
    def add_warning(self, category: str, file: str, line: int, message: str):
        self.warnings.append({
            'category': category,
            'file': file,
            'line': line,
            'severity': 'WARNING',
            'message': message
        })
    
    def add_info(self, category: str, message: str):
        self.info.append({
            'category': category,
            'message': message
        })
    
    def verify_strategy_file(self, filepath: Path):
        """Verify strategy implementation"""
        print(f"\n[1/5] Analyzing strategy: {filepath.name}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Check for stale state flags
        if '_entry_order_pending' in content:
            for i, line in enumerate(lines, 1):
                if '_entry_order_pending' in line and '=' in line:
                    self.add_warning('State Management', str(filepath), i,
                                   'Uses _entry_order_pending flag - prefer cache.orders_open()')
        
        # Check for proper logging
        prediction_logged = False
        filter_logged = False
        order_logged = False
        
        for i, line in enumerate(lines, 1):
            if '[PREDICTION]' in line and '_py_logger' in line:
                prediction_logged = True
            if '[FILTERED]' in line and '_py_logger' in line:
                filter_logged = True
            if '[ORDER]' in line and '_py_logger' in line:
                order_logged = True
        
        if not prediction_logged:
            self.add_warning('Logging', str(filepath), 0, 'Predictions may not be logged to file')
        if not filter_logged:
            self.add_warning('Logging', str(filepath), 0, 'Filter decisions may not be logged to file')
        if not order_logged:
            self.add_warning('Logging', str(filepath), 0, 'Order submissions may not be logged to file')
        
        # Check for proper instrument access
        if 'self.instrument = self.cache.instrument' in content:
            self.add_info('Strategy', 'Uses cache for instrument lookup - GOOD')
        
        # Check for position checks
        if 'cache.positions_open' in content:
            self.add_info('Strategy', 'Checks open positions before trading - GOOD')
        
        if 'cache.orders_open' in content:
            self.add_info('Strategy', 'Checks open orders before trading - GOOD')
    
    def verify_live_runner(self, filepath: Path):
        """Verify live trading runner"""
        print(f"\n[2/5] Analyzing live runner: {filepath.name}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Check for node.run() call
        node_run_found = False
        for i, line in enumerate(lines, 1):
            if ('node.run()' in line or 'node.run_async()' in line or 
                ('target=node.run' in line and 'Thread' in line)):
                node_run_found = True
                if 'Thread' in line:
                    self.add_info('Execution', f'Node started in thread at line {i} - GOOD')
                else:
                    self.add_info('Execution', f'Node started at line {i}')
                break
        
        if not node_run_found:
            self.add_issue('Execution', str(filepath), 0,
                         'node.run() not found - orders will not execute!')
        
        # Check for instrument loading delay
        if 'time.sleep' in content:
            for i, line in enumerate(lines, 1):
                if 'time.sleep' in line and 'instrument' in lines[max(0, i-5):i+5]:
                    match = re.search(r'time\.sleep\((\d+)\)', line)
                    if match:
                        delay = int(match.group(1))
                        if delay < 3:
                            self.add_warning('Timing', str(filepath), i,
                                          f'Instrument load delay ({delay}s) may be too short')
                        else:
                            self.add_info('Timing', f'Instrument load delay: {delay}s - GOOD')
        
        # Check for event loop conflicts
        if 'ib.sleep' in content or 'ib_insync.sleep' in content:
            for i, line in enumerate(lines, 1):
                if '.sleep(' in line and 'ib' in line:
                    self.add_issue('Event Loop', str(filepath), i,
                                 'ib_insync.sleep() conflicts with asyncio - use time.sleep()')
        
        # Check for proper exception handling
        if 'except KeyboardInterrupt' in content:
            self.add_info('Error Handling', 'KeyboardInterrupt handled - GOOD')
        
        if 'finally:' in content and 'dispose()' in content:
            self.add_info('Cleanup', 'Node disposal in finally block - GOOD')
    
    def verify_bar_streamer(self, filepath: Path):
        """Verify bar streaming implementation"""
        print(f"\n[3/5] Analyzing bar streamer: {filepath.name}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Check aggregation source
        for i, line in enumerate(lines, 1):
            if 'aggregation_source' in line:
                if 'aggregation_source=1' in line or 'EXTERNAL' in line:
                    self.add_info('Bar Config', 'Uses EXTERNAL aggregation - GOOD')
                elif 'aggregation_source=2' in line or 'INTERNAL' in line:
                    self.add_warning('Bar Config', str(filepath), i,
                                   'Uses INTERNAL aggregation - may cause warmup issues')
        
        # Check timestamp handling
        ts_init_correct = False
        for i, line in enumerate(lines, 1):
            if 'ts_init' in line and 'ts_event' in line and '=' in line:
                if 'datetime.now()' not in line:
                    ts_init_correct = True
                    self.add_info('Timestamps', 'ts_init uses bar timestamp - GOOD')
                else:
                    self.add_issue('Timestamps', str(filepath), i,
                                 'ts_init uses datetime.now() - breaks resampling!')
        
        if not ts_init_correct:
            self.add_warning('Timestamps', str(filepath), 0,
                           'Could not verify ts_init timestamp handling')
    
    def verify_config_files(self):
        """Verify configuration files"""
        print(f"\n[4/5] Analyzing configuration files")
        
        # Check live config
        live_config = Path('config/live_config.yaml')
        if live_config.exists():
            with open(live_config, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if 'bar_spec: "15-MINUTE' in content:
                self.add_info('Config', 'Bar spec: 15-MINUTE - GOOD')
            
            if 'symbol: EUR/USD' in content:
                self.add_info('Config', 'Symbol: EUR/USD - GOOD')
            
            if 'venue: IDEALPRO' in content:
                self.add_info('Config', 'Venue: IDEALPRO - GOOD')
        else:
            self.add_warning('Config', 'config/live_config.yaml', 0, 'File not found')
        
        # Check IBKR config
        ibkr_config = Path('config/ibkr_config.yaml')
        if ibkr_config.exists():
            with open(ibkr_config, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if 'port: 7497' in content:
                self.add_info('Config', 'IBKR port: 7497 (paper trading) - GOOD')
            elif 'port: 7496' in content:
                self.add_warning('Config', 'config/ibkr_config.yaml', 0,
                               'Port 7496 is LIVE trading - ensure this is intentional!')
        else:
            self.add_warning('Config', 'config/ibkr_config.yaml', 0, 'File not found')
    
    def verify_signal_flow(self):
        """Verify complete signal flow"""
        print(f"\n[5/5] Verifying signal flow")
        
        flow_steps = [
            ('Bar Reception', 'ib_bar_streamer.py', '_on_bar_update'),
            ('Bar Conversion', 'ib_bar_streamer.py', '_ib_bar_to_nautilus'),
            ('Strategy Callback', 'ib_bar_streamer.py', 'callback(nautilus_bar)'),
            ('Feature Calculation', 'ml_strategy_mtf.py', '_calculate_features'),
            ('Prediction', 'ml_strategy_mtf.py', 'model.predict'),
            ('Filter Checks', 'ml_strategy_mtf.py', 'confidence <'),
            ('Order Creation', 'ml_strategy_mtf.py', 'order_factory.bracket'),
            ('Order Submission', 'ml_strategy_mtf.py', 'submit_order_list'),
        ]
        
        for step_name, filename, pattern in flow_steps:
            filepath = Path('live') / filename if 'ib_bar' in filename else Path('strategies') / filename
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                if pattern in content:
                    self.add_info('Signal Flow', f'{step_name}: FOUND in {filename}')
                else:
                    self.add_warning('Signal Flow', str(filepath), 0,
                                   f'{step_name}: Pattern "{pattern}" not found')
    
    def verify_backtest_files(self):
        """Verify backtest implementation"""
        print(f"\n[2/5] Analyzing backtest runner")
        
        # Find backtest files - prioritize multi_layer version
        backtest_file = None
        priority_files = [
            Path('run_mtf_backtest_multi_layer.py'),
            Path('run_ml_backtest_mtf.py'),
            Path('run_backtest_period.py'),
        ]
        
        for filepath in priority_files:
            if filepath.exists():
                backtest_file = filepath
                break
        
        if not backtest_file:
            # Fallback to any backtest file
            backtest_files = []
            for pattern in ['backtest/run_backtest*.py', 'run_backtest*.py', 'backtests/backtest_*.py']:
                backtest_files.extend(Path('.').glob(pattern))
            
            if not backtest_files:
                self.add_warning('Backtest', './', 0, 'No backtest files found')
                return
            
            backtest_file = max(backtest_files, key=lambda p: p.stat().st_mtime)
        
        self.add_info('Backtest', f'Analyzing: {backtest_file.name}')
        
        with open(backtest_file, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Check for data loading
        if 'ParquetDataCatalog' in content or 'read_parquet' in content:
            self.add_info('Data Loading', 'Uses Parquet data catalog - GOOD')
        else:
            self.add_warning('Data Loading', str(backtest_file), 0,
                           'Data loading method unclear')
        
        # Check for bar aggregation
        if 'BarAggregator' in content or 'TimeBarAggregator' in content:
            self.add_info('Bar Aggregation', 'Uses bar aggregator - GOOD')
        
        # Check for strategy instantiation
        if 'MLSignalStrategy' in content:
            self.add_info('Strategy', 'MLSignalStrategy found - GOOD')
        else:
            self.add_warning('Strategy', str(backtest_file), 0,
                           'Strategy instantiation not found')
        
        # Check for engine/node run
        if 'engine.run()' in content or 'node.run(' in content:
            self.add_info('Execution', 'Backtest execution found - GOOD')
        else:
            self.add_issue('Execution', str(backtest_file), 0,
                         'engine.run() or node.run() not found - backtest will not execute!')
        
        # Check for results analysis
        if 'PortfolioAnalyzer' in content or 'get_stats' in content:
            self.add_info('Analysis', 'Results analysis found - GOOD')
        
        # Verify backtest signal flow
        print(f"\n[3/5] Verifying backtest signal flow")
        
        flow_steps = [
            ('Data Config', 'BacktestDataConfig'),
            ('Strategy Config', 'MLSignalStrategyConfig'),
            ('Strategy Init', 'MLSignalStrategy'),
            ('Feature Calculation', '_calculate_features'),
            ('Prediction', 'model.predict'),
            ('Order Creation', 'order_factory'),
            ('Node Execution', 'node.run('),
            ('Results Analysis', 'cache.positions'),
        ]
        
        strategy_content = ''
        strategy_file = Path('strategies/ml_strategy_mtf.py')
        if strategy_file.exists():
            with open(strategy_file, 'r', encoding='utf-8') as f:
                strategy_content = f.read()
        
        for step_name, pattern in flow_steps:
            if pattern in content or pattern in strategy_content:
                self.add_info('Backtest Flow', f'{step_name}: FOUND')
            else:
                self.add_warning('Backtest Flow', str(backtest_file), 0,
                               f'{step_name}: Pattern "{pattern}" not found')
        
        # Check for common backtest issues
        print(f"\n[4/5] Checking for common backtest issues")
        
        # Check for look-ahead bias
        if 'shift(' in content or 'iloc[' in content:
            self.add_warning('Look-ahead Bias', str(backtest_file), 0,
                           'Manual data shifting detected - verify no look-ahead bias')
        
        # Check for proper warmup
        if 'warmup' in content.lower() or 'feature_warmup_bars' in content:
            self.add_info('Warmup', 'Warmup configuration found - GOOD')
        else:
            self.add_warning('Warmup', str(backtest_file), 0,
                           'No warmup configuration found')
        
        # Check for commission/slippage
        if 'commission' in content.lower() or 'slippage' in content.lower():
            self.add_info('Realism', 'Commission/slippage configured - GOOD')
        else:
            self.add_warning('Realism', str(backtest_file), 0,
                           'No commission/slippage found - results may be unrealistic')
        
        print(f"\n[5/5] Verifying data consistency")
        
        # Check for data files
        data_dir = Path('data')
        if data_dir.exists():
            parquet_files = list(data_dir.glob('**/*.parquet'))
            if parquet_files:
                self.add_info('Data', f'Found {len(parquet_files)} parquet file(s)')
            else:
                self.add_warning('Data', 'data/', 0, 'No parquet files found')
        else:
            self.add_warning('Data', 'data/', 0, 'Data directory not found')
    
    def generate_report(self):
        """Generate verification report"""
        print("\n" + "="*80)
        print(" LIVE TRADING SYSTEM VERIFICATION REPORT")
        print("="*80)
        
        # Summary
        print(f"\nSUMMARY:")
        print(f"  Errors:   {len(self.issues)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Info:     {len(self.info)}")
        
        # Critical Issues
        if self.issues:
            print("\n" + "="*80)
            print("CRITICAL ISSUES (MUST FIX):")
            print("="*80)
            for issue in self.issues:
                print(f"\n[{issue['severity']}] {issue['category']}")
                print(f"  File: {issue['file']}")
                if issue['line'] > 0:
                    print(f"  Line: {issue['line']}")
                print(f"  Issue: {issue['message']}")
        
        # Warnings
        if self.warnings:
            print("\n" + "="*80)
            print("WARNINGS (SHOULD REVIEW):")
            print("="*80)
            for warning in self.warnings:
                print(f"\n[{warning['severity']}] {warning['category']}")
                print(f"  File: {warning['file']}")
                if warning['line'] > 0:
                    print(f"  Line: {warning['line']}")
                print(f"  Issue: {warning['message']}")
        
        # Good Practices Found
        if self.info:
            print("\n" + "="*80)
            print("VERIFIED COMPONENTS:")
            print("="*80)
            categories = {}
            for item in self.info:
                cat = item['category']
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(item['message'])
            
            for cat, messages in categories.items():
                print(f"\n{cat}:")
                for msg in messages:
                    print(f"  - {msg}")
        
        # Recommendations
        print("\n" + "="*80)
        print("RECOMMENDATIONS:")
        print("="*80)
        
        if len(self.issues) == 0 and len(self.warnings) == 0:
            print("\n  All checks passed! System appears ready for live trading.")
        else:
            print("\n  1. Fix all CRITICAL ISSUES before running live")
            print("  2. Review and address WARNINGS")
            print("  3. Test with paper trading account first")
            print("  4. Monitor logs closely for first few hours")
        
        print("\n" + "="*80)
        
        # Return status
        return len(self.issues) == 0

def main():
    import sys
    
    # Check if backtest mode requested
    mode = 'live'
    if len(sys.argv) > 1 and sys.argv[1] == '--backtest':
        mode = 'backtest'
    
    verifier = SystemVerifier()
    
    print("="*80)
    if mode == 'live':
        print(" LIVE TRADING SYSTEM VERIFICATION")
    else:
        print(" BACKTEST SYSTEM VERIFICATION")
    print("="*80)
    print(f"\nAnalyzing {mode} codebase for potential issues...")
    
    # Verify key files
    strategy_file = Path('strategies/ml_strategy_mtf.py')
    if strategy_file.exists():
        verifier.verify_strategy_file(strategy_file)
    else:
        verifier.add_issue('File Missing', 'strategies/ml_strategy_mtf.py', 0,
                         'Strategy file not found!')
    
    if mode == 'live':
        live_runner = Path('live/run_live_mtf_ibinsync.py')
        if live_runner.exists():
            verifier.verify_live_runner(live_runner)
        else:
            verifier.add_issue('File Missing', 'live/run_live_mtf_ibinsync.py', 0,
                             'Live runner file not found!')
        
        bar_streamer = Path('live/ib_bar_streamer.py')
        if bar_streamer.exists():
            verifier.verify_bar_streamer(bar_streamer)
        else:
            verifier.add_issue('File Missing', 'live/ib_bar_streamer.py', 0,
                             'Bar streamer file not found!')
        
        verifier.verify_config_files()
        verifier.verify_signal_flow()
    else:
        # Backtest verification
        verifier.verify_backtest_files()
    
    # Generate report
    success = verifier.generate_report()
    
    return 0 if success else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
