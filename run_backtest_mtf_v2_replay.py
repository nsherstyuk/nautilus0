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

from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from run_backtest_mtf_v2_full import generate_reports, utc_to_est
from utils.instruments import normalize_instrument_id, parse_fx_symbol


_MONEY_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


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
    return int(tail) if tail.isdigit() else None


def _infer_exit_reason(opening_order_id: object, closing_order_id: object, closing_tags: object = None) -> str:
    if closing_tags is not None:
        tags_text = str(closing_tags).upper()
        if "NEG_STALL" in tags_text:
            return "NEG_STALL"
    o = _extract_order_suffix(opening_order_id)
    c = _extract_order_suffix(closing_order_id)
    if o is None or c is None:
        return "EXIT"
    if c == o + 1:
        return "SL"
    if c == o + 2:
        return "TP"
    return "EXIT"


def _build_trades_from_positions(
    positions_df: pd.DataFrame,
    config_timezone: str,
    order_tags_by_client_id: dict[str, object] | None = None,
) -> list[dict]:
    trades: list[dict] = []
    tz = (config_timezone or "UTC").upper()

    for _, row in positions_df.iterrows():
        ts_opened = row.get("ts_opened")
        ts_closed = row.get("ts_closed")

        if ts_opened is None or ts_closed is None or str(ts_closed).strip() == "":
            continue

        entry_time = pd.Timestamp(ts_opened)
        exit_time = pd.Timestamp(ts_closed)

        entry_px = float(row.get("avg_px_open", 0.0) or 0.0)
        exit_px = float(row.get("avg_px_close", 0.0) or 0.0)

        pnl = _parse_money_to_float(row.get("realized_pnl"))

        entry_action = str(row.get("entry", "")).upper()
        side = "LONG" if entry_action == "BUY" else "SHORT" if entry_action == "SELL" else entry_action

        if tz == "EST":
            entry_hour, entry_weekday = utc_to_est(entry_time.to_pydatetime())
        else:
            entry_hour = int(entry_time.hour)
            entry_weekday = int(entry_time.weekday())

        opening_order_id = row.get("opening_order_id")
        closing_order_id = row.get("closing_order_id")
        closing_tags = None
        if order_tags_by_client_id is not None and closing_order_id is not None:
            closing_tags = order_tags_by_client_id.get(str(closing_order_id))
        exit_reason = _infer_exit_reason(opening_order_id, closing_order_id, closing_tags)

        trades.append(
            {
                "entry_time": entry_time,
                "exit_time": exit_time,
                "side": side,
                "entry": entry_px,
                "exit": exit_px,
                "pnl": pnl,
                "exit_reason": exit_reason,
                "partial_closed": False,
                "entry_hour": entry_hour,
                "entry_weekday": entry_weekday,
                "duration_bars": 0,
                "entry_month": entry_time.strftime("%Y-%m"),
            }
        )

    return trades


def _setup_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(output_dir / "replay.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)

    cfg = load_mtf_v2_config()

    os.environ.setdefault("MTF2_REPLAY_MODE", "1")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_REPLAY_{timestamp}"
    _setup_logging(output_dir)

    logger = logging.getLogger("mtf_v2_replay")

    logger.info("=" * 80)
    logger.info("MTF V2 REPLAY BACKTEST (NAUTILUS BACKTEST NODE)")
    logger.info("=" * 80)
    logger.info(
        "NEG_STALL env: enabled=%s check_bars=%s max_profit_atr=%s trigger_loss_atr=%s",
        os.getenv("MTF2_NEG_STALL_ENABLED"),
        os.getenv("MTF2_NEG_STALL_CHECK_BARS"),
        os.getenv("MTF2_NEG_STALL_MAX_PROFIT_ATR"),
        os.getenv("MTF2_NEG_STALL_TRIGGER_LOSS_ATR"),
    )
    print_mtf_v2_config(cfg)

    start_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_end, tz="UTC").to_pydatetime())

    slashed_instrument_id = normalize_instrument_id(cfg.symbol, cfg.venue)
    catalog_instrument_id = slashed_instrument_id

    # Nautilus BacktestDataConfig (when data_cls is Bar) appends "-EXTERNAL" itself when
    # constructing the catalog filter expression. Our env config uses bar specs like
    # "15-MINUTE-MID-EXTERNAL" (live-style), so we must strip the trailing suffix here.
    bar_spec = cfg.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    catalog_bar_type = f"{catalog_instrument_id}-{bar_spec}-EXTERNAL"

    catalog_path = Path("data") / "historical"

    logger.info(
        "Replay config: catalog_path=%s instrument_id=%s bar_type=%s start=%s end=%s",
        str(catalog_path),
        catalog_instrument_id,
        catalog_bar_type,
        cfg.backtest_start,
        cfg.backtest_end,
    )

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2",
        config_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2Config",
        config={
            "order_id_tag": "V2",
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
            "stall_detection_enabled": cfg.stall_detection_enabled,
            "stall_check_bars": cfg.stall_check_bars,
            "stall_min_profit_atr": cfg.stall_min_profit_atr,
            "stall_sl_atr": cfg.stall_sl_atr,
        },
    )

    fill_model = ImportableFillModelConfig(
        fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
        config_path="nautilus_trader.backtest.config:FillModelConfig",
        config={
            "prob_fill_on_limit": 1.0,
            "prob_fill_on_stop": 1.0,
            "prob_slippage": 0.0,
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

    data_config = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )

    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )

    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config],
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
        }
        generate_reports(trades, output_dir, report_config)

        replay_log_path = output_dir / "replay.log"
        if replay_log_path.exists():
            shutil.copy(replay_log_path, output_dir / "strategy_decisions.log")
    except Exception:
        logger.exception("Failed to generate full report pack")

    logger.info("Saved reports: %s", str(output_dir))
    logger.info("Orders: %s", len(orders_df))
    logger.info("Fills: %s", len(fills_df))
    logger.info("Positions: %s", len(positions_df))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
