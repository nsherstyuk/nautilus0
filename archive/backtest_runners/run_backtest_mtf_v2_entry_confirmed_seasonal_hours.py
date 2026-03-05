"""
Run MTF V2 backtest with Entry Confirmation + Seasonal Hour×Weekday Exclusions.

This backtest runner adds seasonal hour×weekday pair exclusions to the entry
confirmed strategy. It's a separate file so you can choose between the baseline
(run_backtest_mtf_v2_entry_confirmed.py) and seasonal filtering approach.

Environment variables for seasonal filtering:
- MTF2_SEASONAL_HOUR_EXCLUSIONS_ENABLED: 1/0 to enable/disable
- MTF2_DJF_EXCLUDED_HOUR_WEEKDAY_PAIRS: e.g., "16-1,16-3,16-5,14-3,14-5"
- MTF2_MAM_EXCLUDED_HOUR_WEEKDAY_PAIRS: e.g., "11-2,15-3"
- MTF2_JJA_EXCLUDED_HOUR_WEEKDAY_PAIRS: e.g., "17-1,17-3,17-4,16-3,16-5"
- MTF2_SON_EXCLUDED_HOUR_WEEKDAY_PAIRS: e.g., "14-1,14-2,14-3,14-5"

Format: "hour-weekday" pairs comma-separated, where:
  hour = 0-23 (EST)
  weekday = 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
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


def run_v2_entry_confirmed_seasonal_backtest(
    symbol: str = "EUR/USD",
    venue: str = "IDEALPRO",
    start_date: str = "2025-01-01",
    end_date: str = "2025-12-31",
    use_cached: bool = True,
) -> tuple[Dict[str, Any], str]:
    """
    Run V2 backtest with entry confirmation + seasonal hour×weekday exclusions.
    
    Args:
        symbol: Trading symbol (e.g., "EUR/USD")
        venue: Venue name
        start_date: Backtest start date (YYYY-MM-DD)
        end_date: Backtest end date (YYYY-MM-DD)
        use_cached: Use cached catalog data
        
    Returns:
        Tuple of (results dict, run_folder path)
    """
    # Load environment
    env_path = PROJECT_ROOT / ".env.mtf_v2"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        logger.info(f"Loaded .env from {env_path}")
    
    # Setup logging
    _setup_logging()
    
    # Load config
    cfg = load_mtf_v2_config()
    
    # Override dates from parameters
    cfg.backtest_start = start_date
    cfg.backtest_end = end_date
    
    logger.info("=" * 80)
    logger.info("MTF V2 Entry Confirmed + Seasonal Hour×Weekday Backtest")
    logger.info("=" * 80)
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Venue: {venue}")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info(f"Seasonal Hour Exclusions: {cfg.seasonal_hour_exclusions_enabled}")
    
    if cfg.seasonal_hour_exclusions_enabled:
        logger.info("Seasonal Hour×Weekday Pairs:")
        for season in ["DJF", "MAM", "JJA", "SON"]:
            pairs = getattr(cfg, f"{season.lower()}_excluded_hour_weekday_pairs", [])
            if pairs:
                logger.info(f"  {season}: {pairs}")
    
    # Normalize symbol
    instrument_id_str = normalize_instrument_id(symbol, venue)
    logger.info(f"Normalized Instrument ID: {instrument_id_str}")
    
    # Setup output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_folder_name = f"MTF_V2_SEASONAL_{timestamp}"
    run_folder = PROJECT_ROOT / "backtest_results" / run_folder_name
    run_folder.mkdir(parents=True, exist_ok=True)
    logger.info(f"Results folder: {run_folder}")
    
    # Stamp run metadata
    log_and_write_run_metadata(
        logger,
        output_dir=run_folder,
        run_kind="backtest",
        run_id=timestamp,
        entrypoint=__file__,
        extra={
            "output_dir": str(run_folder),
            "env_file": ".env.mtf_v2",
            "symbol": symbol,
            "venue": venue,
            "backtest_start": start_date,
            "backtest_end": end_date,
        },
    )
    
    # Save .env snapshot
    if env_path.exists():
        shutil.copy(env_path, run_folder / ".env.mtf_v2")
    
    # Build engine config
    engine_config = BacktestEngineConfig(
        strategies=[
            ImportableStrategyConfig(
                strategy_path="strategies.ml_strategy_mtf_v2_entry_confirmed:MLStrategyMTFv2EntryConfirmed",
                config_path="strategies.ml_strategy_mtf_v2_entry_confirmed:MLStrategyMTFv2EntryConfirmedConfig",
                config={
                    "instrument_id": instrument_id_str,
                    "bar_type_15m": f"{instrument_id_str}-15-MINUTE-MID-EXTERNAL",
                    "bar_type_1h": f"{instrument_id_str}-1-HOUR-MID-EXTERNAL",
                    "bar_type_4h": f"{instrument_id_str}-4-HOUR-MID-EXTERNAL",
                    "bar_type_1m": f"{instrument_id_str}-1-MINUTE-MID-EXTERNAL",
                    "model_path_15m": cfg.model_path_15m,
                    "model_path_1h": cfg.model_path_1h,
                    "model_path_4h": cfg.model_path_4h,
                    "entry_threshold_15m": cfg.entry_threshold_15m,
                    "entry_threshold_1h": cfg.entry_threshold_1h,
                    "entry_threshold_4h": cfg.entry_threshold_4h,
                    "base_order_size": cfg.base_order_size,
                    "atr_period": cfg.atr_period,
                    "atr_sl_mult": cfg.atr_sl_mult,
                    "atr_tp1_mult": cfg.atr_tp1_mult,
                    "atr_tp2_mult": cfg.atr_tp2_mult,
                    "partial_exit_pct": cfg.partial_exit_pct,
                    "excluded_hours_mode": cfg.excluded_hours_mode,
                    "excluded_hours": cfg.excluded_hours,
                    "trade_start_hour": cfg.trade_start_hour,
                    "trade_end_hour": cfg.trade_end_hour,
                    "max_daily_trades": cfg.max_daily_trades,
                    "confidence_sl_enabled": cfg.confidence_sl_enabled,
                    "confidence_sl_tiers": cfg.confidence_sl_tiers,
                    "confidence_sl_interpolate": cfg.confidence_sl_interpolate,
                    "confidence_sl_round": cfg.confidence_sl_round,
                    # NEW: Seasonal hour×weekday exclusions
                    "seasonal_hour_exclusions_enabled": cfg.seasonal_hour_exclusions_enabled,
                    "djf_excluded_hour_weekday_pairs": cfg.djf_excluded_hour_weekday_pairs,
                    "mam_excluded_hour_weekday_pairs": cfg.mam_excluded_hour_weekday_pairs,
                    "jja_excluded_hour_weekday_pairs": cfg.jja_excluded_hour_weekday_pairs,
                    "son_excluded_hour_weekday_pairs": cfg.son_excluded_hour_weekday_pairs,
                },
            )
        ],
        venues=[
            BacktestVenueConfig(
                name=venue,
                venue_type="ECN",
                oms_type="NETTING",
                account_type="MARGIN",
                base_currency="USD",
                starting_balances=["1000000 USD"],
                fill_model=ImportableFillModelConfig(
                    path="nautilus_trader.backtest.models:FillModel",
                ),
                modules=[
                    ImportableFillModelConfig(
                        path="nautilus_trader.backtest.modules:FXRolloverInterestModule",
                        config={
                            "rate_data": {},
                        },
                    ),
                ],
            )
        ],
    )
    
    # Build data config
    catalog_format = instrument_id_to_catalog_format(instrument_id_str)
    
    data_config = BacktestDataConfig(
        catalog_path=str(PROJECT_ROOT / "data" / "historical"),
        data_cls="nautilus_trader.model.data:Bar",
        client_id=f"{venue}.EXTERNAL",
        catalog_bar_specs=[
            f"{catalog_format}-1-MINUTE-MID",
            f"{catalog_format}-15-MINUTE-MID",
            f"{catalog_format}-1-HOUR-MID",
            f"{catalog_format}-4-HOUR-MID",
        ],
        start_time=start_date,
        end_time=end_date,
        use_rust=True,
    )
    
    # Build run config
    run_config = BacktestRunConfig(
        engine=engine_config,
        data=[data_config],
        venues=[
            BacktestVenueConfig(
                name=venue,
                venue_type="ECN",
                oms_type="NETTING",
                account_type="MARGIN",
                base_currency="USD",
                starting_balances=["1000000 USD"],
            )
        ],
    )
    
    # Run backtest
    logger.info("Starting backtest...")
    node = BacktestNode(configs=[run_config])
    results = node.run()
    logger.info("Backtest complete")
    
    # Generate reports
    logger.info("Generating reports...")
    engine = node.get_engines()[0]
    
    generate_reports(
        engine=engine,
        run_config=run_config,
        output_dir=run_folder,
        start_date=start_date,
        end_date=end_date,
    )
    
    logger.info(f"Results saved to: {run_folder}")
    logger.info("=" * 80)
    
    return results, str(run_folder)


if __name__ == "__main__":
    # Read env vars for overrides
    symbol = os.getenv("MTF2_SYMBOL", "EUR/USD")
    venue = os.getenv("MTF2_VENUE", "IDEALPRO")
    start = os.getenv("MTF2_BACKTEST_START", "2025-01-01")
    end = os.getenv("MTF2_BACKTEST_END", "2025-12-31")
    
    run_v2_entry_confirmed_seasonal_backtest(
        symbol=symbol,
        venue=venue,
        start_date=start,
        end_date=end,
        use_cached=True,
    )
