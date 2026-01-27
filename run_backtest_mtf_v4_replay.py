"""
MTF V4 Replay Backtest - Multi-Timeframe with Dynamic SL/TP

This script runs the same multi-timeframe replay backtest as V2 but with
V4's dynamic stop loss and take profit based on trading hour analysis.

Features:
- 15-minute and 1-minute bar data (same as V2)
- Dynamic SL by hour (1.0x to 1.6x ATR)
- Dynamic TP by hour (0.5x to 0.8x ATR)
- Weekday performance adjustments
- Separate from V2 - safe for experimentation
"""

import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    ImportableFillModelConfig,
)
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar

# Import V4 components
v4_path = PROJECT_ROOT / "v4"
sys.path.insert(0, str(v4_path))
sys.path.insert(0, str(v4_path / "config"))
sys.path.insert(0, str(v4_path / "strategies"))

from mtf_v4_config import load_mtf_v4_config
from ml_strategy_mtf_v4 import MLSignalStrategyV4

# Import V2 utilities for reporting
from run_backtest_mtf_v2_full import generate_reports, utc_to_est
from utils.instruments import normalize_instrument_id, parse_fx_symbol


_MONEY_RE = re.compile(r"(-?\d+(?:\d+)?)")

def _parse_money_to_float(value: object) -> float:
    if value is None:
        return 0.0
    match = _MONEY_RE.search(str(value))
    return float(match.group(1)) if match else 0.0

def _extract_order_suffix(order_id: object) -> int | None:
    if order_id is None:
        return None
    text = str(order_id)
    if "-" not in text:
        return None
    tail = text.rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None

def _extract_order_prefix(order_id: object) -> str | None:
    if order_id is None:
        return None
    text = str(order_id)
    if "-" not in text:
        return None
    return text.rsplit("-", 1)[0]

def run_v4_mtf_replay_backtest(
    start_date: str,
    end_date: str,
    venue: str = "IDEALPRO",
    symbol: str = "EUR/USD",
    use_cached: bool = True,
):
    """
    Run V4 MTF replay backtest with dynamic SL/TP.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format  
        venue: Trading venue (default: IDEALPRO)
        symbol: Trading symbol (default: EUR/USD)
        use_cached: Whether to use cached data (default: True)
    """
    
    print("=" * 80)
    print("MTF V4 REPLAY BACKTEST - Dynamic SL/TP")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(f"Venue: {venue}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Timeframes: 15-minute (decision) + 1-minute (execution)")
    print()
    
    # Load V4 configuration
    print("Loading V4 configuration...")
    config = load_mtf_v4_config()
    
    print(f"V4 Dynamic Features:")
    print(f"  ✅ Dynamic SL: {config.dynamic_sl_enabled} (1.0x to 1.6x ATR)")
    print(f"  ✅ Dynamic TP: {config.dynamic_tp_enabled} (0.5x to 0.8x ATR)")
    print(f"  ✅ Weekday adjustment: {config.weekday_adjustment_enabled}")
    print(f"  ✅ Default SL: {config.default_sl_atr_mult}x ATR")
    print(f"  ✅ Default TP: {config.default_pos1_tp_atr_mult}x ATR")
    print()
    
    # Setup paths
    data_dir = Path(os.getenv("DATA_DIR", "data/historical"))
    model_path = Path(config.model_file)  # Use model from config
    
    if not model_path.exists():
        raise FileNotFoundError(f"V4 model not found at {model_path}")
    
    # Normalize symbol and instrument ID
    normalized_symbol = normalize_instrument_id(symbol, venue)
    fx_symbol = parse_fx_symbol(symbol)
    
    # Define bar types (same as V2)
    bar_15min = f"{normalized_symbol}-15-MINUTE-MID-EXTERNAL"
    bar_1min = f"{normalized_symbol}-1-MINUTE-MID-EXTERNAL"
    
    # Configure fill model (same as V2)
    fill_model = ImportableFillModelConfig(
        fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
        config_path="nautilus_trader.backtest.config:FillModelConfig",
        config={
            "prob_fill_on_limit": 0.95,  # 95% fill probability (more realistic)
            "prob_fill_on_stop": 1.0,
            "prob_slippage": 0.4,  # 40% chance of slippage
        },
    )
    
    # Setup backtest configuration
    backtest_dir = Path("v4/backtest_results") / f"MTF_V4_REPLAY_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backtest_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Results directory: {backtest_dir}")
    
    # Configure strategy
    strategy_config = ImportableStrategyConfig(
        strategy_path="ml_strategy_mtf_v4:MLSignalStrategyV4",
        config_path="ml_strategy_mtf_v4:MLSignalStrategyV4Config",
        config={
            "instrument_id": normalized_symbol,
            "bar_type": bar_15min,  # Decision timeframe
            "model_path": str(model_path),
            "mtf_config": {
                "decision_timeframe": "15m",
                "execution_timeframe": "1m",
                "decision_bar_type": bar_15min,
                "execution_bar_type": bar_1min,
            },
        },
    )
    
    # Configure venue (same as V2)
    venue_config = BacktestVenueConfig(
        name=venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=[f"{config.initial_balance} USD"],
        fill_model=fill_model,
        bar_execution=True,
        bar_adaptive_high_low_ordering=False,
    )
    
    # Configure data (dual timeframe like V2)
    data_config_15m = BacktestDataConfig(
        catalog_path=str(data_dir),
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=normalized_symbol,
        start_time=start_date,
        end_time=end_date,
    )
    
    data_config_1m = BacktestDataConfig(
        catalog_path=str(data_dir),
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=normalized_symbol,
        start_time=start_date,
        end_time=end_date,
    )
    
    # Configure backtest engine (V2 style)
    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )
    
    # Run configuration
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config_15m, data_config_1m],  # Dual timeframe
        raise_exception=True,
        dispose_on_completion=False,
    )
    
    # Create and run backtest
    print("Starting V4 backtest...")
    print("(This may take a few minutes...)")
    
    node = BacktestNode(configs=[run_config])
    node.build()
    
    try:
        # Run the backtest
        result = node.run()
        
        print("✅ V4 backtest completed!")
        print(f"Total P&L: ${result.total_pnl:,.2f}")
        print(f"Win rate: {result.win_rate:.1%}")
        print(f"Total trades: {result.total_trades}")
        print()
        
        # Generate results
        print("Generating V4 results...")
        
        # Copy environment file
        shutil.copy2(
            v4_path / ".env.mtf_v4",
            backtest_dir / ".env.mtf_v4"
        )
        
        # Generate trading reports (same as V2)
        generate_reports(
            result=result,
            output_dir=backtest_dir,
            symbol=symbol,
            venue=venue,
            start_date=start_date,
            end_date=end_date,
            config_summary="V4 Dynamic SL/TP Strategy"
        )
        
        # Generate V4-specific analysis
        generate_v4_analysis(backtest_dir, result, config)
        
        print(f"✅ V4 results saved to: {backtest_dir}")
        return result, backtest_dir
        
    except Exception as e:
        print(f"❌ V4 backtest failed: {e}")
        raise
    finally:
        node.dispose()

def generate_v4_analysis(results_dir: Path, result, config):
    """Generate V4-specific analysis with dynamic SL/TP insights."""
    
    print("Generating V4 dynamic SL/TP analysis...")
    
    # Create V4 analysis report
    analysis_file = results_dir / "v4_dynamic_analysis.txt"
    
    with open(analysis_file, 'w') as f:
        f.write("MTF V4 DYNAMIC SL/TP ANALYSIS\n")
        f.write("=" * 50 + "\n\n")
        
        f.write("V4 STRATEGY FEATURES:\n")
        f.write("-" * 20 + "\n")
        f.write(f"Dynamic SL enabled: {config.dynamic_sl_enabled}\n")
        f.write(f"Dynamic TP enabled: {config.dynamic_tp_enabled}\n")
        f.write(f"Weekday adjustment: {config.weekday_adjustment_enabled}\n")
        f.write(f"Default SL multiplier: {config.default_sl_atr_mult}x ATR\n")
        f.write(f"Default TP multiplier: {config.default_pos1_tp_atr_mult}x ATR\n\n")
        
        f.write("DYNAMIC PARAMETERS:\n")
        f.write("-" * 20 + "\n")
        f.write("High fade hours (20-22, 17-19): SL=1.4-1.6x ATR\n")
        f.write("Low fade hours (0-7, 11-15): SL=1.0x ATR\n")
        f.write("High performance hours (15-17): TP=0.8x ATR\n")
        f.write("Low performance hours (14, 6): TP=0.5x ATR\n\n")
        
        f.write("PERFORMANCE SUMMARY:\n")
        f.write("-" * 20 + "\n")
        f.write(f"Total P&L: ${result.total_pnl:,.2f}\n")
        f.write(f"Win Rate: {result.win_rate:.1%}\n")
        f.write(f"Max Drawdown: ${result.max_drawdown:,.2f}\n")
        f.write(f"Sharpe Ratio: {result.sharpe_ratio:.2f}\n")
        f.write(f"Total Trades: {result.total_trades}\n\n")
        
        f.write("V4 vs V2 COMPARISON:\n")
        f.write("-" * 25 + "\n")
        f.write("V4 Improvements Expected:\n")
        f.write("- 15% risk reduction in low fade hours\n")
        f.write("- 25% better fade trade capture\n")
        f.write("- 10% profit boost in high performance hours\n")
        f.write("- Dynamic adaptation to market conditions\n\n")
        
        f.write("NEXT STEPS:\n")
        f.write("-" * 15 + "\n")
        f.write("1. Compare with V2 results in ../backtest_results/\n")
        f.write("2. Analyze hour-by-hour performance\n")
        f.write("3. Fine-tune dynamic parameters if needed\n")
        f.write("4. Consider live deployment after validation\n")
    
    print(f"✅ V4 analysis saved to: {analysis_file}")

def main():
    """Main function to run V4 MTF replay backtest."""
    
    # Load environment
    load_dotenv("v4/.env.mtf_v4")
    
    # Get configuration
    config = load_mtf_v4_config()
    
    # Run backtest
    result, results_dir = run_v4_mtf_replay_backtest(
        start_date=config.backtest_start,
        end_date=config.backtest_end,
        venue="IDEALPRO",
        symbol="EUR/USD",
        use_cached=True,
    )
    
    print("\n" + "=" * 80)
    print("🎉 V4 MTF REPLAY BACKTEST COMPLETE!")
    print("=" * 80)
    print(f"Results: {results_dir}")
    print()
    print("V4 Dynamic SL/TP Features:")
    print("✅ Hour-based SL adjustment (1.0x to 1.6x ATR)")
    print("✅ Hour-based TP adjustment (0.5x to 0.8x ATR)")
    print("✅ Weekday performance adjustments")
    print("✅ Multi-timeframe (15m + 1m) analysis")
    print("✅ Completely separate from V2")
    print()
    print("Next Steps:")
    print("1. Review V4 results and compare with V2")
    print("2. Analyze dynamic parameter effectiveness")
    print("3. Fine-tune parameters based on results")

if __name__ == "__main__":
    main()
