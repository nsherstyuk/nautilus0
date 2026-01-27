
import logging
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.backtest.config import BacktestRunConfig, BacktestEngineConfig, BacktestVenueConfig, BacktestDataConfig, ImportableFillModelConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.core.datetime import dt_to_unix_nanos

from config.mtf_v2_config import load_mtf_v2_config

# Enable logging
logging.basicConfig(
    level=logging.DEBUG,
    filename="debug_opt.log",
    filemode="w",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("nautilus_trader").setLevel(logging.INFO)
logging.getLogger("strategies.ml_strategy_mtf_v2").setLevel(logging.DEBUG)

def run_debug():
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)
    cfg = load_mtf_v2_config()
    
    print(f"Config: {cfg.symbol} {cfg.venue} {cfg.backtest_start} to {cfg.backtest_end}")
    
    catalog_path = Path("data") / "historical"
    
    # Fix Instrument ID to match data on disk (EURUSD vs EUR/USD)
    cfg_symbol = cfg.symbol.replace("/", "")
    catalog_instrument_id = f"{cfg_symbol}.{cfg.venue}"
    
    bar_spec = cfg.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    catalog_bar_type = f"{catalog_instrument_id}-{bar_spec}-EXTERNAL"
    
    strategy_config_dict = {
        "instrument_id": catalog_instrument_id,
        "bar_type": catalog_bar_type,
        "model_path": str((PROJECT_ROOT / cfg.model_path).resolve()),
        "total_position_size": cfg.total_position_size,
        "pos1_fraction": cfg.pos1_fraction,
        "pos2_fraction": cfg.pos2_fraction,
        "pos3_fraction": cfg.pos3_fraction,
        "sl_atr_mult": cfg.sl_atr_mult,
        "pos1_tp_atr_mult": cfg.pos1_tp_atr_mult,
        "pos2_tp_atr_mult": cfg.pos2_tp_atr_mult,
        "pos3_tp_atr_mult": cfg.pos3_tp_atr_mult,
        "trailing_activation_atr_mult": cfg.trailing_activation_atr_mult,
        "trailing_distance_atr_mult": cfg.trailing_distance_atr_mult,
        "trade_start_hour": cfg.trade_start_hour,
        "trade_end_hour": cfg.trade_end_hour,
        "entry_cooldown_bars": cfg.entry_cooldown_bars,
        "prediction_threshold": cfg.prediction_threshold,
        "min_atr": cfg.min_atr,
        "max_atr": cfg.max_atr,
        "excluded_hours_mode": cfg.excluded_hours_mode,
        "config_timezone": cfg.config_timezone,
        "excluded_hours_monday": ",".join(map(str, cfg.excluded_hours_monday)),
        "excluded_hours_tuesday": ",".join(map(str, cfg.excluded_hours_tuesday)),
        "excluded_hours_wednesday": ",".join(map(str, cfg.excluded_hours_wednesday)),
        "excluded_hours_thursday": ",".join(map(str, cfg.excluded_hours_thursday)),
        "excluded_hours_friday": ",".join(map(str, cfg.excluded_hours_friday)),
        "excluded_hours_saturday": ",".join(map(str, cfg.excluded_hours_saturday)),
        "excluded_hours_sunday": ",".join(map(str, cfg.excluded_hours_sunday)),
        "max_positions": cfg.max_positions,
        "stall_detection_enabled": False,
        "meta_filter_mama_enabled": cfg.meta_filter_mama_enabled,
        "meta_filter_mama_min_diff": cfg.meta_filter_mama_min_diff,
        "meta_filter_dmi_enabled": cfg.meta_filter_dmi_enabled,
        "meta_filter_dmi_min_dmp": cfg.meta_filter_dmi_min_dmp,
    }

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2",
        config_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2Config",
        config=strategy_config_dict,
    )

    venue_config = BacktestVenueConfig(
        name=cfg.venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=None,
        starting_balances=[f"{float(cfg.initial_balance):.2f} USD"],
        fill_model=ImportableFillModelConfig(
            fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
            config_path="nautilus_trader.backtest.config:FillModelConfig",
            config={"prob_fill_on_limit": 0.95, "prob_fill_on_stop": 1.0, "prob_slippage": 0.4},
        ),
    )

    start_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_end, tz="UTC").to_pydatetime())

    data_config = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )

    run_config = BacktestRunConfig(
        engine=BacktestEngineConfig(strategies=[strategy_config]),
        venues=[venue_config],
        data=[data_config],
    )

    node = BacktestNode(configs=[run_config])
    print("Running backtest...")
    node.run()
    
    engine = node.get_engine(run_config.id)
    positions = engine.trader.generate_positions_report()
    print(f"Positions: {len(positions)}")
    if len(positions) == 0:
        print("No positions! Check logs.")

if __name__ == "__main__":
    run_debug()
