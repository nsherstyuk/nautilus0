"""
MTF V4 Replay Backtest with Dynamic SL/TP

This script runs backtests for the V4 strategy with dynamic stop loss
and take profit based on trading hour analysis.

Completely separate from V2 - safe for experimentation.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.modules import FXRolloverInterestModule
from nautilus_trader.config import BacktestVenueConfig, BacktestDataConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

# Import V4 components
v4_path = Path(__file__).parent.parent
sys.path.append(str(v4_path))
from strategies.ml_strategy_mtf_v4 import MLSignalStrategyV4
from config.mtf_v4_config import load_mtf_v4_config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("V4_Backtest")

def load_v4_config():
    """Load V4 configuration from environment."""
    
    # Load V4 config
    config = load_mtf_v4_config()
    
    # Create strategy config
    strategy_config = {
        "instrument_id": "EUR/USD.IDEALPRO",
        "bar_type": "EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    }
    
    return config, strategy_config

def create_v4_strategy(strategy_config):
    """Create V4 strategy instance."""
    from nautilus_trader.config import StrategyConfig
    
    config = StrategyConfig(
        instrument_id=strategy_config["instrument_id"],
        bar_type=strategy_config["bar_type"]
    )
    
    return MLSignalStrategyV4(config)

def run_v4_backtest():
    """Run V4 backtest with dynamic SL/TP."""
    
    logger.info("Starting MTF V4 Backtest with Dynamic SL/TP...")
    
    # Load configuration
    v4_config, strategy_config = load_v4_config()
    
    # Setup data catalog
    data_dir = Path(os.getenv("DATA_DIR", "data/historical"))
    catalog = ParquetDataCatalog(str(data_dir))
    
    # Create instrument
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD", Venue("IDEALPRO"))
    
    # Create bar type
    bar_type = BarType(
        instrument_id=instrument.id,
        bar_spec=BarSpecification(
            step=15,
            aggregation=BarAggregation.MINUTE,
            price_type=PriceType.MID
        ),
        quote_type=PriceType.MID
    )
    
    # Setup backtest engine
    engine_config = BacktestEngineConfig(
        trader_id="BACKTESTER-V4",
        venue_configs=[BacktestVenueConfig(name="IDEALPRO", oms_type="HEDGING", account_type="MARGIN", base_currency=USD)],
        data_configs=[BacktestDataConfig(
            catalog_path=str(data_dir),
            instrument_id=instrument.id,
            start_time=v4_config.backtest_start,
            end_time=v4_config.backtest_end
        )],
        initial_balance=Money(v4_config.initial_balance, USD)
    )
    
    engine = BacktestEngine(config=engine_config)
    
    # Add strategy
    strategy = create_v4_strategy(strategy_config)
    engine.add_strategy(strategy)
    
    # Add modules
    engine.add_module(FXRolloverInterestModule())
    
    # Run backtest
    logger.info(f"Running V4 backtest from {v4_config.backtest_start} to {v4_config.backtest_end}")
    result = engine.run()
    
    # Generate results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path("v4/backtest_results") / f"MTF_V4_REPLAY_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Save results
    engine.save_results(str(results_dir))
    
    # Generate V4-specific analysis
    generate_v4_analysis(results_dir, result)
    
    logger.info(f"V4 backtest completed. Results saved to: {results_dir}")
    
    return result, results_dir

def generate_v4_analysis(results_dir, result):
    """Generate V4-specific analysis with dynamic SL/TP performance."""
    
    logger.info("Generating V4 analysis...")
    
    # Create analysis report
    report_file = results_dir / "v4_analysis_report.txt"
    
    with open(report_file, 'w') as f:
        f.write("MTF V4 Backtest Analysis - Dynamic SL/TP\n")
        f.write("=" * 50 + "\n\n")
        
        f.write("V4 Features:\n")
        f.write("- Dynamic SL by hour (1.0x to 1.6x ATR)\n")
        f.write("- Dynamic TP by hour (0.5x to 0.8x ATR)\n")
        f.write("- Weekday performance adjustments\n")
        f.write("- Separate from V2 (no impact on live trading)\n\n")
        
        f.write("Performance Summary:\n")
        f.write(f"Total P&L: ${result.total_pnl:.2f}\n")
        f.write(f"Win Rate: {result.win_rate:.1%}\n")
        f.write(f"Max Drawdown: ${result.max_drawdown:.2f}\n")
        f.write(f"Sharpe Ratio: {result.sharpe_ratio:.2f}\n")
        f.write(f"Total Trades: {result.total_trades}\n\n")
        
        f.write("Dynamic SL/TP Impact:\n")
        f.write("- Analysis of hour-based performance\n")
        f.write("- Comparison with static V2 parameters\n")
        f.write("- Recommendations for optimization\n")
    
    logger.info(f"V4 analysis saved to: {report_file}")

def compare_v4_vs_v2():
    """Compare V4 dynamic results with V2 static results."""
    
    logger.info("Comparing V4 vs V2 performance...")
    
    # Find latest V2 and V4 results
    v2_results = find_latest_results("backtest_results", "MTF_V2_REPLAY")
    v4_results = find_latest_results("v4/backtest_results", "MTF_V4_REPLAY")
    
    if not v2_results or not v4_results:
        logger.error("Could not find both V2 and V4 results for comparison")
        return
    
    # Load and compare results
    comparison = generate_comparison_report(v2_results, v4_results)
    
    # Save comparison
    comparison_file = Path("v4/backtest_results/v4_vs_v2_comparison.txt")
    with open(comparison_file, 'w') as f:
        f.write(comparison)
    
    logger.info(f"Comparison saved to: {comparison_file}")

def find_latest_results(base_dir, pattern):
    """Find the latest backtest results directory."""
    
    base_path = Path(base_dir)
    if not base_path.exists():
        return None
    
    matching_dirs = [d for d in base_path.iterdir() if d.is_dir() and pattern in d.name]
    
    if not matching_dirs:
        return None
    
    return max(matching_dirs, key=lambda x: x.stat().st_mtime)

def generate_comparison_report(v2_path, v4_path):
    """Generate comparison report between V2 and V4."""
    
    report = []
    report.append("V2 vs V4 Performance Comparison")
    report.append("=" * 40)
    report.append("")
    
    # Load summary files
    v2_summary = v2_path / "summary.txt"
    v4_summary = v4_path / "summary.txt"
    
    if v2_summary.exists() and v4_summary.exists():
        v2_content = v2_summary.read_text()
        v4_content = v4_summary.read_text()
        
        report.append("V2 (Static SL/TP):")
        report.append("-" * 20)
        report.append(v2_content)
        report.append("")
        
        report.append("V4 (Dynamic SL/TP):")
        report.append("-" * 20)
        report.append(v4_content)
        report.append("")
        
        report.append("Key Differences:")
        report.append("-" * 15)
        report.append("- V4 uses hour-based dynamic SL/TP")
        report.append("- V4 includes weekday adjustments")
        report.append("- V4 maintains separate config from V2")
    
    return "\n".join(report)

if __name__ == "__main__":
    print("MTF V4 Backtest with Dynamic SL/TP")
    print("=" * 50)
    
    # Run V4 backtest
    result, results_dir = run_v4_backtest()
    
    # Compare with V2 if available
    compare_v4_vs_v2()
    
    print("\nV4 Backtest Complete!")
    print(f"Results: {results_dir}")
    print("\nV4 Features:")
    print("- Dynamic SL by hour (1.0x to 1.6x ATR)")
    print("- Dynamic TP by hour (0.5x to 0.8x ATR)")
    print("- Weekday performance adjustments")
    print("- Separate from V2 (safe experimentation)")
