import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from run_backtest_mtf_v2_full import generate_reports
from run_backtest_mtf_v2_replay import _build_trades_from_positions, _setup_logging
from utils.instruments import instrument_id_to_catalog_format, parse_fx_symbol
from utils.run_metadata import log_and_write_run_metadata

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


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)
    cfg = load_mtf_v2_config()

    os.environ.setdefault("MTF2_REPLAY_MODE", "1")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_RULE_EMAMA_DMI_STOCH_{timestamp}"
    
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
            "symbol": cfg.symbol,
            "venue": cfg.venue,
            "backtest_start": cfg.backtest_start,
            "backtest_end": cfg.backtest_end,
        },
    )
    
    _setup_logging(output_dir)

    logger = logging.getLogger("mtf_v2_rule_emama")

    logger.info("=" * 80)
    logger.info("MTF V2 RULE BACKTEST: EMAMA/MAMA + DMI(15/30) + STOCH(15)")
    logger.info("=" * 80)
    print_mtf_v2_config(cfg)

    start_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_end, tz="UTC").to_pydatetime())

    strategy_instrument_id = f"{cfg.symbol}.{cfg.venue}"
    catalog_instrument_id = instrument_id_to_catalog_format(strategy_instrument_id)

    bar_spec = cfg.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    strategy_bar_type = f"{strategy_instrument_id}-{bar_spec}-EXTERNAL"

    catalog_path = Path("data") / "historical"

    fill_model = ImportableFillModelConfig(
        fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
        config_path="nautilus_trader.backtest.config:FillModelConfig",
        config={
            "prob_fill_on_limit": 0.95,
            "prob_fill_on_stop": 1.0,
            "prob_slippage": 0.4,
            "random_seed": 42,
        },
    )

    is_fx = "/" in str(cfg.symbol)
    starting_balances = [f"{float(cfg.initial_balance):.2f} USD"]
    base_currency = "USD"
    if is_fx:
        base_currency = None
        try:
            base_ccy, _ = parse_fx_symbol(cfg.symbol)
            if base_ccy and base_ccy.upper() != "USD":
                starting_balances.append(f"{float(cfg.initial_balance):.2f} {base_ccy.upper()}")
        except Exception:
            pass

    venue_config = BacktestVenueConfig(
        name=cfg.venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=base_currency,
        starting_balances=starting_balances,
        fill_model=fill_model,
        bar_execution=True,
        bar_adaptive_high_low_ordering=False,
    )

    data_config_15m = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )

    data_config_1m = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec="1-MINUTE-MID",
        start_time=start_ns,
        end_time=end_ns,
    )

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.rule_emama_dmi_stoch_v2:RuleEmamaDmiStochV2",
        config_path="strategies.rule_emama_dmi_stoch_v2:RuleEmamaDmiStochV2Config",
        config={
            # Reuse the same sizing + ATR risk parameters from the v2 config loader.
            "order_id_tag": "V2-RULE",
            "instrument_id": strategy_instrument_id,
            "bar_type": strategy_bar_type,
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
            "prediction_threshold": cfg.prediction_threshold,
            "trade_start_hour": cfg.trade_start_hour,
            "trade_end_hour": cfg.trade_end_hour,
            "entry_cooldown_bars": cfg.entry_cooldown_bars,
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
            "stall_detection_enabled": cfg.stall_detection_enabled,
            "stall_check_bars": cfg.stall_check_bars,
            "stall_min_profit_atr": cfg.stall_min_profit_atr,
            "stall_sl_atr": cfg.stall_sl_atr,
            "meta_filter_mama_enabled": cfg.meta_filter_mama_enabled,
            "meta_filter_mama_min_diff": cfg.meta_filter_mama_min_diff,
            "meta_filter_dmi_enabled": cfg.meta_filter_dmi_enabled,
            "meta_filter_dmi_min_dmp": cfg.meta_filter_dmi_min_dmp,
            # Rule params (defaults match your screenshot-style EMAMA settings)
            "mama_fast": 0.30,
            "mama_slow": 0.05,
            "stoch_max_for_long": 80.0,
            "stoch_min_for_short": 20.0,
        },
    )

    engine_config = BacktestEngineConfig(strategies=[strategy_config])

    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config_15m, data_config_1m],
        raise_exception=True,
        dispose_on_completion=False,
    )

    node = BacktestNode(configs=[run_config])
    node.build()
    node.run()

    engine = node.get_engine(run_config.id)
    orders_df = engine.trader.generate_orders_report()
    fills_df = engine.trader.generate_fills_report()
    positions_df = engine.trader.generate_positions_report()

    orders_report = orders_df.reset_index() if "client_order_id" not in orders_df.columns else orders_df
    fills_report = fills_df.reset_index() if "client_order_id" not in fills_df.columns else fills_df

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

        trades = _build_trades_from_positions(positions_df, cfg.config_timezone, order_tags_by_client_id)
        report_config = {
            "backtest_start": cfg.backtest_start,
            "backtest_end": cfg.backtest_end,
            "config_timezone": cfg.config_timezone,
            "trade_start_hour": cfg.trade_start_hour,
            "trade_end_hour": cfg.trade_end_hour,
        }
        generate_reports(trades, output_dir, report_config)

        replay_log_path = output_dir / "replay.log"
        if replay_log_path.exists():
            shutil.copy(replay_log_path, output_dir / "strategy_decisions.log")
    except Exception:
        logger.exception("Failed to generate report pack")

    logger.info("Saved reports: %s", str(output_dir))
    logger.info("Orders: %s", len(orders_df))
    logger.info("Fills: %s", len(fills_df))
    logger.info("Positions: %s", len(positions_df))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
