"""
Run MTF V2 backtest with Entry Confirmation and Directional MAMA Filter.

This version uses ml_strategy_mtf_v2_entry_confirmed_directional_mama.py
which implements direction-aware MAMA/FAMA filtering:
- LONG signals require MAMA > FAMA (bullish trend)
- SHORT signals require MAMA < FAMA (bearish trend)
"""

import os
import sys
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import pandas as pd

from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "config"))

from config.mtf_v2_config import load_mtf_v2_config
from utils.instruments import instrument_id_to_catalog_format, normalize_instrument_id, parse_fx_symbol
from utils.run_metadata import log_and_write_run_metadata

from run_backtest_mtf_v2_full import generate_reports
from run_backtest_mtf_v2_replay import _build_trades_from_positions, _setup_logging

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel
from nautilus_trader.backtest.modules import FXRolloverInterestModule
from nautilus_trader.config import BacktestEngineConfig, BacktestRunConfig, BacktestVenueConfig
from nautilus_trader.config import ImportableStrategyConfig, ImportableFillModelConfig, BacktestDataConfig
from nautilus_trader.backtest.node import BacktestNode

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default

def run_v2_entry_confirmed_backtest(
    symbol: str = "EUR/USD",
    venue: str = "IDEALPRO",
    start_date: str = "2025-01-01",
    end_date: str = "2025-12-31",
    use_cached: bool = True,
) -> tuple[Dict[str, Any], str]:
    """
    Run V2 backtest with entry confirmation logic.
    
    Args:
        symbol: Trading symbol (e.g., "EUR/USD")
        venue: Trading venue (e.g., "IDEALPRO")
        start_date: Backtest start date (YYYY-MM-DD)
        end_date: Backtest end date (YYYY-MM-DD)
        use_cached: Whether to use cached data
        
    Returns:
        Tuple of (backtest_results, results_directory_path)
    """
    
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)

    entry_confirmation_enabled = _env_bool("MTF2_ENTRY_CONFIRM_ENABLED", True)
    entry_confirmation_bars = _env_int("MTF2_ENTRY_CONFIRM_BARS", 2)
    entry_confirmation_threshold = _env_float("MTF2_ENTRY_CONFIRM_THRESHOLD", 0.2)
    entry_max_wait_bars = _env_int("MTF2_ENTRY_CONFIRM_MAX_WAIT_BARS", 5)

    print("=" * 80)
    print("MTF V2 REPLAY BACKTEST - DIRECTIONAL MAMA VERSION")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(f"Venue: {venue}")
    print(f"Period: {start_date} to {end_date}")
    print(
        f"Entry Confirmation: enabled={entry_confirmation_enabled} "
        f"bars={entry_confirmation_bars} "
        f"threshold={entry_confirmation_threshold} "
        f"max_wait={entry_max_wait_bars}"
    )
    print()
    
    # Load configuration
    config = load_mtf_v2_config()

    os.environ.setdefault("MTF2_REPLAY_MODE", "1")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_DIRECTIONAL_MAMA_{timestamp}"
    
    # Stamp run metadata
    log_and_write_run_metadata(
        None,  # No logger yet
        output_dir=output_dir,
        run_kind="backtest",
        run_id=timestamp,
        entrypoint=__file__,
        extra={
            "output_dir": str(output_dir),
            "env_file": ".env.mtf_v2",
            "symbol": config.symbol,
            "venue": config.venue,
            "backtest_start": config.backtest_start,
            "backtest_end": config.backtest_end,
        },
    )
    
    _setup_logging(output_dir)
    
    print(f"V2 Configuration:")
    print(f"  [OK] MAMA Filter: {config.meta_filter_mama_enabled}")
    print(f"  [OK] DMI Filter: {config.meta_filter_dmi_enabled}")
    print(f"  [OK] Default SL: {config.sl_atr_mult}x ATR")
    print(f"  [OK] Default TP: {config.pos1_tp_atr_mult}x ATR")
    print(f"  [OK] Position sizing: POS1={config.pos1_fraction:.0%}, POS2={config.pos2_fraction:.0%}")
    print()
    
    # Setup paths
    data_dir = Path(os.getenv("DATA_DIR", "data/historical"))
    model_path = Path(config.model_path)
    
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found at {model_path}")
    
    start_ns = dt_to_unix_nanos(pd.Timestamp(config.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(config.backtest_end, tz="UTC").to_pydatetime())

    strategy_instrument_id = f"{config.symbol}.{config.venue}"
    catalog_instrument_id = instrument_id_to_catalog_format(strategy_instrument_id)

    bar_spec = config.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    strategy_bar_type = f"{strategy_instrument_id}-{bar_spec}-EXTERNAL"
    
    # Configure fill model
    fill_model = ImportableFillModelConfig(
        fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
        config_path="nautilus_trader.config:FillModelConfig",
        config={
            "prob_fill_on_limit": 0.95,  # 95% fill probability
            "prob_fill_on_stop": 1.0,
            "prob_slippage": 0.4,  # 40% chance of slippage
        },
    )
    
    # Configure strategy
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2_entry_confirmed_directional_mama:MLSignalStrategyV2EntryConfirmed",
        config_path="strategies.ml_strategy_mtf_v2_entry_confirmed_directional_mama:MLSignalStrategyV2EntryConfirmedConfig",
        config={
            "instrument_id": strategy_instrument_id,
            "bar_type": strategy_bar_type,
            "model_path": str(model_path),
            "total_position_size": config.total_position_size,
            "pos1_fraction": config.pos1_fraction,
            "pos2_fraction": config.pos2_fraction,
            "pos3_fraction": config.pos3_fraction,
            "sl_atr_mult": config.sl_atr_mult,
            "pos1_tp_atr_mult": config.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": config.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": config.pos3_tp_atr_mult,
            "trailing_distance_atr_mult": config.trailing_distance_atr_mult,
            "prediction_threshold": config.prediction_threshold,
            "trade_start_hour": config.trade_start_hour,
            "trade_end_hour": config.trade_end_hour,
            "entry_cooldown_bars": config.entry_cooldown_bars,
            "min_atr": config.min_atr,
            "max_atr": config.max_atr,
            "excluded_hours_mode": config.excluded_hours_mode,
            "config_timezone": config.config_timezone,
            "excluded_hours_monday": config.excluded_hours_monday,
            "excluded_hours_tuesday": config.excluded_hours_tuesday,
            "excluded_hours_wednesday": config.excluded_hours_wednesday,
            "excluded_hours_thursday": config.excluded_hours_thursday,
            "excluded_hours_friday": config.excluded_hours_friday,
            "excluded_hours_saturday": config.excluded_hours_saturday,
            "excluded_hours_sunday": config.excluded_hours_sunday,
            # Entry confirmation settings
            "entry_confirmation_enabled": entry_confirmation_enabled,
            "entry_confirmation_bars": entry_confirmation_bars,
            "entry_confirmation_threshold": entry_confirmation_threshold,
            "entry_max_wait_bars": entry_max_wait_bars,
        },
    )
    
    # Configure venue
    base_currency = "USD"  # Default for forex pairs
    venue_config = BacktestVenueConfig(
        name=venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=base_currency,
        starting_balances=[f"{config.initial_balance} {base_currency}"],
        fill_model=fill_model,
        bar_execution=True,
        bar_adaptive_high_low_ordering=False,
    )
    
    # Configure data
    # Use bar_spec parameter like in the original V2 backtest
    data_config_15m = BacktestDataConfig(
        catalog_path=str(data_dir),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )
    
    data_config_1m = BacktestDataConfig(
        catalog_path=str(data_dir),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec="1-MINUTE-MID",
        start_time=start_ns,
        end_time=end_ns,
    )
    
    # Configure engine
    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )
    
    # Configure run
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config_15m, data_config_1m],  # Dual timeframe
        raise_exception=True,
        dispose_on_completion=False,
    )
    
    # Create and run backtest
    node = BacktestNode(configs=[run_config])
    node.build()
    
    try:
        result = node.run()

        engine = node.get_engine(run_config.id)
        orders_df = engine.trader.generate_orders_report()
        fills_df = engine.trader.generate_fills_report()
        positions_df = engine.trader.generate_positions_report()

        orders_report = orders_df.reset_index() if "client_order_id" not in orders_df.columns else orders_df
        fills_report = fills_df.reset_index() if "client_order_id" not in fills_df.columns else fills_df

        output_dir.mkdir(parents=True, exist_ok=True)
        orders_report.to_csv(output_dir / "orders.csv", index=False)
        fills_report.to_csv(output_dir / "fills.csv", index=False)
        positions_df.to_csv(output_dir / "positions.csv", index=False)

        try:
            order_tags_by_client_id = {}
            try:
                if "tags" in orders_df.columns:
                    order_tags_by_client_id = orders_df["tags"].to_dict()
            except Exception:
                order_tags_by_client_id = {}

            trades = _build_trades_from_positions(positions_df, config.config_timezone, order_tags_by_client_id)
            report_config = {
                "backtest_start": config.backtest_start,
                "backtest_end": config.backtest_end,
                "config_timezone": config.config_timezone,
            }
            generate_reports(trades, output_dir, report_config)

            replay_log_path = output_dir / "replay.log"
            if replay_log_path.exists():
                shutil.copy(replay_log_path, output_dir / "strategy_decisions.log")
        except Exception as e:
            logger.error(f"Failed to generate full report pack: {e}")

        # generate_reports(...) writes the detailed summary.txt. Only write a fallback
        # if the report pack failed to generate the summary.
        summary_path = output_dir / "summary.txt"
        if not summary_path.exists():
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write("Entry Confirmed V2 Backtest Results\n")
                f.write("=" * 50 + "\n")
                f.write(f"Period: {config.backtest_start} to {config.backtest_end}\n")
                f.write(f"Total Trades: {len(trades) if 'trades' in locals() else 0}\n")
        
        print()
        print("=" * 80)
        print("BACKTEST COMPLETED")
        print("=" * 80)
        results_dir = str(output_dir)
        print(f"Results saved to: {results_dir}")
        print()
        
        # Print summary
        if result and hasattr(result, 'stats'):
            stats = result.stats
            print("Performance Summary:")
            print(f"  Total PnL: ${stats.get('total_pnl', 0):,.2f}")
            print(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
            print(f"  Total Trades: {stats.get('total_trades', 0)}")
            print(f"  Sharpe Ratio: {stats.get('sharpe_ratio', 0):.2f}")
        
        print()
        print("Entry Confirmation Analysis:")
        print("  - Check logs/strategy_signals_v2_entry_confirmed.csv for signal details")
        print("  - Compare with original V2 results to measure improvement")
        
        return result, results_dir
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        raise
    finally:
        node.dispose()

def main():
    """Main function."""
    # Load configuration
    config = load_mtf_v2_config()
    
    # Run backtest
    result, results_dir = run_v2_entry_confirmed_backtest(
        symbol=config.symbol,
        venue=config.venue,
        start_date=config.backtest_start,
        end_date=config.backtest_end,
        use_cached=True,
    )
    
    print()
    print("=" * 80)
    print("V2 ENTRY CONFIRMED BACKTEST COMPLETED")
    print("=" * 80)
    print(f"Results: {results_dir}")
    print()
    print("Next steps:")
    print("1. Compare results with original V2 backtest")
    print("2. Check entry confirmation effectiveness in logs")
    print("3. If improved, update live trading to use entry confirmed version")

if __name__ == "__main__":
    main()
