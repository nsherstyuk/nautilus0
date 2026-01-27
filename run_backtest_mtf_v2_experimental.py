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
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_EXPERIMENTAL_{timestamp}"
    _setup_logging(output_dir)

    logger = logging.getLogger("mtf_v2_experimental")

    logger.info("=" * 80)
    logger.info("MTF V2 EXPERIMENTAL BACKTEST")
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
        strategy_path="strategies.experimental_strategy_v2:ExperimentalStrategyV2",
        config_path="strategies.experimental_strategy_v2:ExperimentalStrategyV2Config",
        config={
            "instrument_id": strategy_instrument_id,
            "bar_type": strategy_bar_type,
            "total_position_size": cfg.total_position_size,
            "trade_start_hour": cfg.trade_start_hour,
            "trade_end_hour": cfg.trade_end_hour,
            "order_id_tag": "V2-EXP",
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
