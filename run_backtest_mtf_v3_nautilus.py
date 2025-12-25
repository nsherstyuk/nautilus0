"""
Nautilus Backtest Runner for HMTF V3 Strategy

Uses Nautilus BacktestEngine for proper fill simulation, commission modeling,
and order management. Replaces the manual PnL replay simulation.
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.modules import FXRolloverInterestModule
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import EUR, USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType, AssetClass
from nautilus_trader.model.identifiers import TraderId, Venue, InstrumentId, Symbol
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from strategies.ml_strategy_mtf_v3_hmtf import (
    MLSignalStrategyV3,
    MLSignalStrategyV3Config,
)


def load_config_from_env() -> dict:
    """Load V3 config from environment."""
    # Load .env.mtf_v3
    env_path = Path(".env.mtf_v3")
    if env_path.exists():
        load_dotenv(env_path, override=True)
    
    return {
        # Models
        "master_model_path": os.getenv("MTF3_MASTER_MODEL_PATH", "models/ml_model_mtf_backup.pkl"),
        "soldier_model_path": os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"),
        "soldier_feature_list_path": os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"),
        
        # HMTF parameters
        "master_threshold": float(os.getenv("MTF3_MASTER_PREDICTION_THRESHOLD", "0.70")),
        "master_threshold_mode": os.getenv("MTF3_MASTER_THRESHOLD_MODE", "abs"),
        "soldier_enabled": os.getenv("MTF3_SOLDIER_MODEL_ENABLED", "False").lower() == "true",
        "soldier_entry_threshold": float(os.getenv("MTF3_SOLDIER_ENTRY_THRESHOLD", "0.55")),
        "cooldown_minutes": int(os.getenv("MTF3_COOLDOWN_MINUTES", "30")),
        
        # Position sizing
        "use_dynamic_sizing": os.getenv("MTF3_USE_DYNAMIC_SIZING", "True").lower() == "true",
        "fixed_position_size": int(os.getenv("MTF3_FIXED_POSITION_SIZE", "50000")),
        "risk_per_trade_pct": float(os.getenv("MTF3_RISK_PER_TRADE_PCT", "1.0")),
        "min_position_size": int(os.getenv("MTF3_MIN_POSITION_SIZE", "1000")),
        "sl_atr_mult": float(os.getenv("MTF3_SL_ATR_MULT", "1.0")),
        "tp_atr_mult": float(os.getenv("MTF3_TP_ATR_MULT", "1.5")),
        
        # Session filters
        "trade_start_hour": int(os.getenv("MTF3_TRADE_START_HOUR", "0")),
        "trade_end_hour": int(os.getenv("MTF3_TRADE_END_HOUR", "23")),
        "config_timezone": os.getenv("MTF3_CONFIG_TIMEZONE", "UTC"),
        "excluded_hours_mode": os.getenv("MTF3_EXCLUDED_HOURS_MODE", "disabled"),
        "excluded_hours_monday": os.getenv("MTF3_EXCLUDED_HOURS_MONDAY", ""),
        "excluded_hours_tuesday": os.getenv("MTF3_EXCLUDED_HOURS_TUESDAY", ""),
        "excluded_hours_wednesday": os.getenv("MTF3_EXCLUDED_HOURS_WEDNESDAY", ""),
        "excluded_hours_thursday": os.getenv("MTF3_EXCLUDED_HOURS_THURSDAY", ""),
        "excluded_hours_friday": os.getenv("MTF3_EXCLUDED_HOURS_FRIDAY", ""),
        "excluded_hours_saturday": os.getenv("MTF3_EXCLUDED_HOURS_SATURDAY", ""),
        "excluded_hours_sunday": os.getenv("MTF3_EXCLUDED_HOURS_SUNDAY", ""),
        
        # Risk limits
        "min_atr": float(os.getenv("MTF3_MIN_ATR", "0.00010")),
        "max_atr": float(os.getenv("MTF3_MAX_ATR", "0.01000")),
        
        # Stall detection
        "stall_detection_enabled": os.getenv("MTF2_STALL_DETECTION_ENABLED", "False").lower() == "true",
        "stall_check_bars": int(os.getenv("MTF2_STALL_CHECK_BARS", "3")),
        "stall_min_profit_atr": float(os.getenv("MTF2_STALL_MIN_PROFIT_ATR", "0.1")),
        "stall_sl_atr": float(os.getenv("MTF2_STALL_SL_ATR", "0.6")),
        "neg_stall_enabled": os.getenv("MTF2_NEG_STALL_ENABLED", "false").lower() == "true",
        "neg_stall_check_bars": int(os.getenv("MTF2_NEG_STALL_CHECK_BARS", "3")),
        "neg_stall_max_profit_atr": float(os.getenv("MTF2_NEG_STALL_MAX_PROFIT_ATR", "0.0")),
        "neg_stall_trigger_loss_atr": float(os.getenv("MTF2_NEG_STALL_TRIGGER_LOSS_ATR", "0.9")),
    }


def main():
    """Run V3 HMTF backtest using Nautilus engine."""
    
    # Configuration
    instrument_id_str = "EUR/USD.IDEALPRO"
    venue = Venue("IDEALPRO")
    start_date = "2025-12-01"
    end_date = "2025-12-05"  # Just 5 days for testing
    starting_balance = 4_500.0  # Match replay starting equity
    
    # Load strategy config from env
    env_config = load_config_from_env()
    
    # Initialize backtest engine
    config = BacktestEngineConfig(
        trader_id=TraderId("BACKTESTER-001"),
        logging=LoggingConfig(log_level="INFO"),
    )
    
    engine = BacktestEngine(config=config)
    
    # Create IDEALPRO venue
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(starting_balance, USD)],
    )
    
    # Create EUR/USD instrument
    instrument_id = InstrumentId(symbol=Symbol("EUR/USD"), venue=venue)
    instrument = CurrencyPair(
        instrument_id=instrument_id,
        raw_symbol=Symbol("EUR/USD"),
        base_currency=EUR,
        quote_currency=USD,
        price_precision=5,
        size_precision=2,  # Match bar volume precision
        price_increment=Price.from_str("0.00001"),
        size_increment=Quantity.from_str("0.01"),
        lot_size=Quantity.from_int(1000),
        max_quantity=Quantity.from_int(1_000_000),
        min_quantity=Quantity.from_str("0.01"),
        margin_init=Decimal("0.03"),
        margin_maint=Decimal("0.03"),
        ts_event=0,
        ts_init=0,
    )
    
    engine.add_instrument(instrument)
    
    # Add commission model (IBKR-like)
    # $2.00 per round-turn for typical sizes
    # This is simplified - Nautilus has more sophisticated commission modules
    
    # Load data from catalog
    catalog = ParquetDataCatalog("./data/historical")
    
    # Note: Nautilus bar types use "-EXTERNAL" suffix for historical data
    bar_type_5m = BarType.from_str(f"{instrument_id_str}-5-MINUTE-MID-EXTERNAL")
    bar_type_15m = BarType.from_str(f"{instrument_id_str}-15-MINUTE-MID-EXTERNAL")
    
    # Load data and check if available
    print(f"Loading data from catalog: {catalog.path}")
    print(f"Bar types: {bar_type_5m}, {bar_type_15m}")
    print(f"Date range: {start_date} to {end_date}")
    
    try:
        bars_5m = catalog.bars([str(bar_type_5m)], start=start_date, end=end_date)
        bars_15m = catalog.bars([str(bar_type_15m)], start=start_date, end=end_date)
        
        print(f"Loaded {len(bars_5m)} 5m bars, {len(bars_15m)} 15m bars")
        
        if not bars_5m or not bars_15m:
            print("ERROR: No data found in catalog. Check:")
            print("  1. Catalog path: ./data/historical")
            print(f"  2. Instrument: {instrument_id_str}")
            print(f"  3. Date range: {start_date} to {end_date}")
            print("  4. Run: python data/ingest_historical.py to populate catalog")
            return 1
        
        engine.add_data(bars_5m)
        engine.add_data(bars_15m)
    except Exception as e:
        print(f"ERROR loading data: {e}")
        return 1
    
    # Configure strategy
    strategy_config = MLSignalStrategyV3Config(
        instrument_id=instrument_id_str,
        bar_type_5m=str(bar_type_5m),
        bar_type_15m=str(bar_type_15m),
        **env_config,
    )
    
    # Add strategy
    strategy = MLSignalStrategyV3(config=strategy_config)
    engine.add_strategy(strategy)
    
    # Run backtest
    print(f"\n{'='*80}")
    print(f"HMTF V3 NAUTILUS BACKTEST")
    print(f"{'='*80}")
    print(f"Instrument: {instrument_id_str}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Starting Balance: ${starting_balance:,.2f}")
    print(f"Master Model: {env_config['master_model_path']}")
    print(f"Soldier Enabled: {env_config['soldier_enabled']}")
    print(f"{'='*80}\n")
    
    engine.run()
    
    # Results
    account = engine.trader.generate_account_report(venue)
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print(account)
    
    fills = engine.trader.generate_order_fills_report()
    print("\n" + "="*80)
    print("ORDER FILLS")
    print("="*80)
    print(fills)
    
    positions = engine.trader.generate_positions_report()
    print("\n" + "="*80)
    print("POSITIONS")
    print("="*80)
    print(positions)
    
    # Export results
    output_dir = Path("backtest_results/MTF_V3_NAUTILUS") / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "account_report.txt", "w") as f:
        f.write(str(account))
    with open(output_dir / "fills_report.txt", "w") as f:
        f.write(str(fills))
    with open(output_dir / "positions_report.txt", "w") as f:
        f.write(str(positions))
    
    print(f"\nResults saved to: {output_dir}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
