from __future__ import annotations

import logging
import logging.config
import os
import signal
import sys
import threading
import time
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patches import apply_ib_connection_patch

apply_ib_connection_patch()

from nautilus_trader.trading.config import StrategyFactory
from nautilus_trader.adapters.interactive_brokers.config import (
    IBMarketDataTypeEnum,
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveDataEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from config.ibkr_config import get_ibkr_config
from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from live.dashboard_ipc import CommandReader, append_jsonl, atomic_write_json, utc_now_iso
from live.ib_bar_streamer import IBBarStreamer

from ib_insync import MarketOrder

logger = logging.getLogger("live_v2_dashboard_having_live_limit_entry")


def _split_fx_symbol(symbol: str) -> tuple[str, str]:
    s = str(symbol).strip()
    if "/" in s:
        base, quote = s.split("/", 1)
        return base.strip().upper(), quote.strip().upper()
    if len(s) == 6:
        return s[:3].upper(), s[3:].upper()
    return s.upper(), ""


def _contract_matches_fx(contract, base: str, quote: str) -> bool:
    try:
        c_symbol = getattr(contract, "symbol", None)
        c_ccy = getattr(contract, "currency", None)
        if c_symbol and c_ccy:
            return str(c_symbol).upper() == base and str(c_ccy).upper() == quote
    except Exception:
        return False
    return False


def _cancel_ib_orders_for_symbol(ib, symbol: str) -> int:
    base, quote = _split_fx_symbol(symbol)
    if not base or not quote:
        return 0
    cancelled = 0
    try:
        for trade in ib.openTrades():
            if _contract_matches_fx(trade.contract, base, quote):
                try:
                    ib.cancelOrder(trade.order)
                    cancelled += 1
                except Exception:
                    pass
    except Exception:
        return 0
    return cancelled


def _flatten_ib_position_for_symbol(ib, symbol: str) -> int:
    base, quote = _split_fx_symbol(symbol)
    if not base or not quote:
        return 0

    flattened = 0
    try:
        for pos in ib.positions():
            if not _contract_matches_fx(pos.contract, base, quote):
                continue
            qty_dec = Decimal(str(getattr(pos, "position", 0) or 0))
            if qty_dec == 0:
                continue
            qty_abs = qty_dec.copy_abs()
            qty_int = int(qty_abs.to_integral_value(rounding=ROUND_FLOOR))
            if qty_int <= 0:
                logger.warning(
                    "IB position for %s is fractional (%s). Cannot place MARKET order with fractional totalQuantity; skipping.",
                    symbol,
                    str(qty_dec),
                )
                continue
            action = "SELL" if qty_dec > 0 else "BUY"
            order = MarketOrder(action, qty_int)
            ib.placeOrder(pos.contract, order)
            if qty_abs != Decimal(qty_int):
                logger.warning(
                    "Placed integer flatten for %s: qty=%s -> sent=%s (fractional remainder may remain)",
                    symbol,
                    str(qty_dec),
                    qty_int,
                )
            flattened += 1
    except Exception:
        return 0

    return flattened


class PortfolioFilter(logging.Filter):
    def filter(self, record):
        if "Portfolio" in record.name and "Updated AccountState" in record.getMessage():
            return False
        if any(x in record.name for x in ["Cache", "RiskEngine", "DataEngine"]):
            if "Updated" in record.getMessage():
                return False
        return True


def setup_logging(log_dir: Path, start_time: str) -> None:
    config_path = Path("config/logging.live.yaml")
    with config_path.open("r", encoding="utf-8") as stream:
        logging_config = yaml.safe_load(stream)

    log_dir.mkdir(parents=True, exist_ok=True)

    handler_mappings = {
        "file": "application.log",
        "live_file": "live_trading.log",
        "strategy_file": "strategy.log",
        "orders_file": "orders.log",
        "trades_file": "trades.log",
        "errors_file": "errors.log",
    }

    for handler_name, filename in handler_mappings.items():
        if handler_name in logging_config.get("handlers", {}):
            logging_config["handlers"][handler_name]["filename"] = str(log_dir / filename)

    logging.config.dictConfig(logging_config)

    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
            handler.addFilter(PortfolioFilter())

    console_log_file = log_dir / f"console_{start_time}.log"
    console_handler = logging.FileHandler(console_log_file, mode="w")
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)

    logging.getLogger("nautilus_trader.portfolio").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.cache").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.common").setLevel(logging.WARNING)
    logging.getLogger("nautilus_trader.execution").setLevel(logging.DEBUG)
    logging.getLogger("nautilus_trader.risk").setLevel(logging.WARNING)

    logging.getLogger("TRADER-V2-001.Portfolio").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.Cache").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.RiskEngine").setLevel(logging.WARNING)
    logging.getLogger("TRADER-V2-001.ExecEngine").setLevel(logging.DEBUG)
    logging.getLogger("TRADER-V2-001.DataEngine").setLevel(logging.WARNING)
    logging.getLogger("orders").setLevel(logging.DEBUG)

    log = logging.getLogger("live_v2_dashboard_having_live_limit_entry")
    log.info("Live dashboard logging configured. Logs directory: %s", log_dir)
    log.info("Console log (this run): %s", console_log_file)

    from utils.run_metadata import log_and_write_run_metadata

    log_and_write_run_metadata(
        log,
        output_dir=log_dir,
        run_kind="live",
        run_id=start_time,
        entrypoint=__file__,
        extra={"logger": "live_v2_dashboard_having_live_limit_entry", "log_dir": str(log_dir)},
    )


def _resolve_market_data_type(value: str) -> IBMarketDataTypeEnum:
    mapping = {
        "REALTIME": IBMarketDataTypeEnum.REALTIME,
        "DELAYED": IBMarketDataTypeEnum.DELAYED,
        "DELAYED_FROZEN": IBMarketDataTypeEnum.DELAYED_FROZEN,
    }
    return mapping.get(str(value).upper(), IBMarketDataTypeEnum.DELAYED_FROZEN)


class StrategyLogCaptureHandler(logging.Handler):
    def __init__(self, state: Dict[str, Any]):
        super().__init__(level=logging.INFO)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return

        if "[PREDICTION]" in msg:
            self.state["last_prediction_line"] = msg
            self.state["last_prediction_ts_wall_utc"] = utc_now_iso()

            try:
                parts = msg.replace("[PREDICTION]", "").strip().split(",")
                kv = {}
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        kv[k.strip()] = v.strip()
                self.state["last_pred"] = kv.get("pred")
                self.state["last_confidence"] = float(kv.get("conf")) if kv.get("conf") else None
                self.state["last_threshold"] = float(kv.get("thresh")) if kv.get("thresh") else None
            except Exception:
                pass

        if "[FILTERED]" in msg:
            self.state["last_decision_reason"] = msg
            self.state["last_decision_ts_wall_utc"] = utc_now_iso()

        if "[SIGNAL]" in msg:
            self.state["last_signal_line"] = msg
            self.state["last_signal_ts_wall_utc"] = utc_now_iso()

        if "Warmup complete" in msg:
            self.state["warmup_complete"] = True


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "y", "on"}


def main() -> int:
    live_config = load_mtf_v2_config()

    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = start_time

    log_dir = Path("logs/live_mtf")
    setup_logging(log_dir, start_time)

    logger.info("=" * 80)
    logger.info("MTF V2 LIVE TRADING (DASHBOARD ENABLED, HAVING_LIVE, LIMIT_ENTRY)")
    logger.info("=" * 80)
    print_mtf_v2_config(live_config)

    _ = get_ibkr_config()

    instrument_provider_config = InteractiveBrokersInstrumentProviderConfig(
        load_ids=frozenset([live_config.instrument]),
        min_expiry_days=10,
        build_futures_chain=False,
        build_options_chain=False,
    )

    market_data_type = _resolve_market_data_type(live_config.ib_market_data_type)

    data_client_config = InteractiveBrokersDataClientConfig(
        ibg_host=live_config.ib_host,
        ibg_port=live_config.ib_port,
        ibg_client_id=live_config.ib_client_id,
        use_regular_trading_hours=False,
        market_data_type=market_data_type,
        instrument_provider=instrument_provider_config,
    )

    exec_client_config = InteractiveBrokersExecClientConfig(
        ibg_host=live_config.ib_host,
        ibg_port=live_config.ib_port,
        ibg_client_id=live_config.ib_client_id + 1,
        account_id=live_config.ib_account,
        instrument_provider=instrument_provider_config,
        routing=RoutingConfig(default=True),
    )

    protection_grace_sec = float(os.getenv("MTF2_PROTECTION_GRACE_SEC", "15").split("#", 1)[0].strip() or "15")
    protection_require_open_orders = _env_bool("MTF2_PROTECTION_REQUIRE_OPEN_ORDERS", False)

    entry_limit_buffer_pips = float(os.getenv("MTF2_ENTRY_LIMIT_BUFFER_PIPS", "0.00010").split("#", 1)[0].strip() or "0.00010")
    entry_timeout_sec = float(os.getenv("MTF2_ENTRY_TIMEOUT_SEC", "60").split("#", 1)[0].strip() or "60")

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2_having_live_limit_entry:MLSignalStrategyV2HavingLiveLimitEntry",
        config_path="strategies.ml_strategy_mtf_v2_having_live_limit_entry:MLSignalStrategyV2HavingLiveLimitEntryConfig",
        config={
            "order_id_tag": "V2",
            "instrument_id": live_config.instrument,
            "bar_type": live_config.bar_type,
            "model_path": str(Path(live_config.model_path).resolve()),
            "total_position_size": live_config.total_position_size,
            "pos1_fraction": live_config.pos1_fraction,
            "pos2_fraction": live_config.pos2_fraction,
            "pos3_fraction": live_config.pos3_fraction,
            "sl_atr_mult": live_config.sl_atr_mult,
            "pos1_tp_atr_mult": live_config.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": live_config.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": live_config.pos3_tp_atr_mult,
            "trailing_activation_atr_mult": live_config.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": live_config.trailing_distance_atr_mult,
            "trade_start_hour": live_config.trade_start_hour,
            "trade_end_hour": live_config.trade_end_hour,
            "entry_cooldown_bars": live_config.entry_cooldown_bars,
            "prediction_threshold": live_config.prediction_threshold,
            "min_atr": live_config.min_atr,
            "max_atr": live_config.max_atr,
            "excluded_hours_mode": live_config.excluded_hours_mode,
            "config_timezone": live_config.config_timezone,
            "excluded_hours_monday": ",".join(map(str, live_config.excluded_hours_monday)),
            "excluded_hours_tuesday": ",".join(map(str, live_config.excluded_hours_tuesday)),
            "excluded_hours_wednesday": ",".join(map(str, live_config.excluded_hours_wednesday)),
            "excluded_hours_thursday": ",".join(map(str, live_config.excluded_hours_thursday)),
            "excluded_hours_friday": ",".join(map(str, live_config.excluded_hours_friday)),
            "excluded_hours_saturday": ",".join(map(str, live_config.excluded_hours_saturday)),
            "excluded_hours_sunday": ",".join(map(str, live_config.excluded_hours_sunday)),
            "max_positions": live_config.max_positions,
            "stall_detection_enabled": live_config.stall_detection_enabled,
            "stall_check_bars": live_config.stall_check_bars,
            "stall_min_profit_atr": live_config.stall_min_profit_atr,
            "stall_sl_atr": live_config.stall_sl_atr,
            "protection_grace_sec": protection_grace_sec,
            "protection_require_open_orders": protection_require_open_orders,
            "entry_limit_buffer_pips": entry_limit_buffer_pips,
            "entry_timeout_sec": entry_timeout_sec,
        },
    )

    log_dir = Path("logs/trader_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    node_config = TradingNodeConfig(
        trader_id="TRADER-V2-001",
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="DEBUG",
            log_directory=str(log_dir.resolve()),
            log_component_levels={
                "Portfolio": "WARNING",
                "Cache": "WARNING",
                "RiskEngine": "WARNING",
                "DataEngine": "WARNING",
                "ExecEngine": "DEBUG",
            },
        ),
        data_engine=LiveDataEngineConfig(
            time_bars_build_with_no_updates=True,
            time_bars_timestamp_on_close=True,
            validate_data_sequence=False,
        ),
        data_clients={"INTERACTIVE_BROKERS": data_client_config},
        exec_clients={"INTERACTIVE_BROKERS": exec_client_config},
        timeout_connection=60.0,
        timeout_reconciliation=30.0,
        timeout_portfolio=30.0,
        timeout_disconnection=10.0,
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory("INTERACTIVE_BROKERS", InteractiveBrokersLiveExecClientFactory)
    node.build()

    strategy_instance = StrategyFactory.create(strategy_config)
    node.trader.add_strategy(strategy_instance)

    ipc_dir = Path("logs/live_mtf")
    status_path = ipc_dir / "status.json"
    events_path = ipc_dir / "events.jsonl"
    commands_path = ipc_dir / "commands.jsonl"
    acks_path = ipc_dir / "command_acks.jsonl"

    state: Dict[str, Any] = {
        "run_id": run_id,
        "paused": False,
        "warmup_complete": False,
        "last_bar_time_utc": None,
        "last_bar_ts_wall_utc": None,
        "last_decision_reason": "",
        "last_pred": None,
        "last_confidence": None,
        "last_threshold": None,
        "guard": {
            "enabled": True,
            "grace_sec": float(protection_grace_sec),
            "require_open_orders": bool(protection_require_open_orders),
        },
        "entry": {
            "type": "LIMIT_MARKETABLE",
            "buffer_pips": float(entry_limit_buffer_pips),
            "timeout_sec": float(entry_timeout_sec),
        },
        "guard_triggered": False,
        "guard_last_reason": None,
        "guard_last_ts_wall_utc": None,
        "entry_cancel_triggered": False,
        "entry_cancel_last_reason": None,
        "entry_cancel_last_ts_wall_utc": None,
    }

    strat_logger = logging.getLogger("MLSignalStrategy_V2")
    strat_logger.addHandler(StrategyLogCaptureHandler(state))

    original_execute_entry = getattr(strategy_instance, "_execute_entry", None)

    def _execute_entry_wrapped(bar, atr_normalized, direction):
        if state.get("paused"):
            msg = "[PAUSE] New entry blocked (paused)"
            logging.getLogger("MLSignalStrategy_V2").info(msg)
            state["last_decision_reason"] = msg
            state["last_decision_ts_wall_utc"] = utc_now_iso()
            append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "ENTRY_BLOCKED", "reason": "paused"})
            return
        if original_execute_entry is None:
            return
        return original_execute_entry(bar, atr_normalized, direction)

    if original_execute_entry is not None:
        setattr(strategy_instance, "_execute_entry", _execute_entry_wrapped)

    bar_streamer = IBBarStreamer(
        host=live_config.ib_host,
        port=live_config.ib_port,
        client_id=live_config.ib_client_id + 2,
    )

    logger.info("Connecting ib_insync bar streamer...")
    if not bar_streamer.connect():
        logger.error("Failed to connect bar streamer")
        return 1

    bar_spec = live_config.bar_type.split("-", 1)[1]
    parts = bar_spec.split("-")
    step = int(parts[0])
    unit = parts[1].upper()

    if unit == "MINUTE":
        bar_size = f"{step} mins" if step > 1 else "1 min"
    elif unit == "HOUR":
        bar_size = f"{step} hour" if step == 1 else f"{step} hours"
    else:
        bar_size = f"{step} mins"

    price_type = parts[2].upper() if len(parts) > 2 else "MID"
    if price_type == "MID":
        what_to_show = "MIDPOINT"
    elif price_type == "BID":
        what_to_show = "BID"
    elif price_type == "ASK":
        what_to_show = "ASK"
    else:
        what_to_show = "TRADES"

    symbol = live_config.symbol
    logger.info("Subscribing to %s %s bars via ib_insync...", symbol, bar_size)

    def on_bar_callback(bar):
        try:
            bar_ts = datetime.fromtimestamp(int(bar.ts_init) / 1_000_000_000, tz=timezone.utc)
            state["last_bar_time_utc"] = bar_ts.isoformat()
            state["last_bar_ts_wall_utc"] = utc_now_iso()
            append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "BAR", "bar_time_utc": state["last_bar_time_utc"]})
        except Exception:
            pass
        return strategy_instance.on_bar(bar)

    success = bar_streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=bar_size,
        what_to_show=what_to_show,
        callback=on_bar_callback,
        use_rth=False,
        duration="2 D",
    )

    if not success:
        logger.error("Failed to subscribe to bars")
        bar_streamer.disconnect()
        return 1

    logger.info("Bar subscription active")

    node_thread = threading.Thread(target=node.run, daemon=True)
    node_thread.start()

    cmd_reader = CommandReader(commands_path)

    def write_status_snapshot() -> None:
        try:
            bar_age = bar_streamer.get_last_bar_age_seconds()
            status = {
                "ts_wall_utc": utc_now_iso(),
                "run_id": run_id,
                "mode": "LIVE",
                "paused": bool(state.get("paused")),
                "connection": {
                    "ib_connected": bool(bar_streamer.is_connected()),
                    "bar_age_sec": float(bar_age) if bar_age is not None else None,
                    "error_count": int(bar_streamer.get_error_count()),
                },
                "strategy": {
                    "symbol": str(live_config.symbol),
                    "bar_type": str(live_config.bar_type),
                    "warmup_complete": bool(state.get("warmup_complete")),
                    "buffer_15m_len": int(getattr(strategy_instance, "bars_buffer_15m", []).__len__()),
                    "buffer_30m_len": int(getattr(strategy_instance, "bars_buffer_30m", []).__len__()),
                    "last_bar_time_utc": state.get("last_bar_time_utc"),
                    "last_prediction": {
                        "pred": state.get("last_pred"),
                        "confidence": state.get("last_confidence"),
                        "threshold": state.get("last_threshold"),
                        "ts_wall_utc": state.get("last_prediction_ts_wall_utc"),
                    },
                    "last_decision_reason": state.get("last_decision_reason", ""),
                    "last_decision_ts_wall_utc": state.get("last_decision_ts_wall_utc"),
                    "guard": state.get("guard"),
                    "entry": state.get("entry"),
                    "guard_triggered": bool(state.get("guard_triggered")),
                    "guard_last_reason": state.get("guard_last_reason"),
                    "guard_last_ts_wall_utc": state.get("guard_last_ts_wall_utc"),
                    "entry_cancel_triggered": bool(state.get("entry_cancel_triggered")),
                    "entry_cancel_last_reason": state.get("entry_cancel_last_reason"),
                    "entry_cancel_last_ts_wall_utc": state.get("entry_cancel_last_ts_wall_utc"),
                },
            }
            atomic_write_json(status_path, status)
        except Exception as e:
            logger.warning("Failed to write status snapshot: %s", e)

    def cancel_all() -> None:
        strategy_instance.cancel_all_orders(strategy_instance.instrument_id)

        try:
            if bar_streamer.ib.isConnected():
                cancelled = _cancel_ib_orders_for_symbol(bar_streamer.ib, live_config.symbol)
                if cancelled:
                    logger.info("Cancelled %s IB open order(s) for %s via ib_insync fallback", cancelled, live_config.symbol)
        except Exception as e:
            logger.warning("ib_insync cancel fallback failed: %s", e)

    def flatten_now(source: str, reason: str) -> None:
        state["paused"] = True
        cancel_all()
        try:
            strategy_instance.close_all_positions(strategy_instance.instrument_id)
        except Exception:
            pass

        try:
            if bar_streamer.ib.isConnected():
                flattened = _flatten_ib_position_for_symbol(bar_streamer.ib, live_config.symbol)
                if flattened:
                    logger.info("Flattened %s IB position(s) for %s via ib_insync fallback", flattened, live_config.symbol)
        except Exception as e:
            logger.warning("ib_insync flatten fallback failed: %s", e)

        append_jsonl(
            events_path,
            {"ts_wall_utc": utc_now_iso(), "type": "FLATTEN", "source": source, "reason": str(reason)},
        )

    stop_requested = {"value": False}

    def _handle_sigint(signum, frame):
        stop_requested["value"] = True

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _handle_sigint)
    except Exception:
        pass

    logger.info("Dashboard-enabled live runner active. Press Ctrl+C to stop.")

    last_status_write = 0.0
    status_interval = 1.0
    last_guard_check = 0.0
    guard_check_interval = float(os.getenv("MTF2_PROTECTION_CHECK_INTERVAL_SEC", "1").split("#", 1)[0].strip() or "1")

    last_entry_cancel_check = 0.0
    entry_cancel_check_interval = float(os.getenv("MTF2_ENTRY_CANCEL_CHECK_INTERVAL_SEC", "1").split("#", 1)[0].strip() or "1")

    try:
        while not stop_requested["value"]:
            time.sleep(0.25)

            if bar_streamer.needs_reconnect():
                logger.info("Executing reconnection from main thread...")
                bar_streamer._reconnect()
                continue
            if bar_streamer.is_reconnecting():
                continue

            for cmd in cmd_reader.iter_new():
                cmd_upper = cmd.command.strip().upper()
                ok = True
                message = "OK"
                try:
                    if cmd_upper == "PAUSE":
                        state["paused"] = True
                        append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "PAUSE", "source": cmd.source})
                    elif cmd_upper == "RESUME":
                        state["paused"] = False
                        append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "RESUME", "source": cmd.source})
                    elif cmd_upper == "CANCEL_ALL":
                        cancel_all()
                        append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "CANCEL_ALL", "source": cmd.source})
                    elif cmd_upper == "FLATTEN":
                        flatten_now(source=cmd.source, reason="manual")
                    else:
                        ok = False
                        message = f"Unknown command: {cmd_upper}"
                except Exception as e:
                    ok = False
                    message = f"Exception: {e}"

                append_jsonl(
                    acks_path,
                    {
                        "ts_wall_utc": utc_now_iso(),
                        "cmd_id": cmd.cmd_id,
                        "command": cmd_upper,
                        "source": cmd.source,
                        "ok": bool(ok),
                        "message": message,
                    },
                )

            now = time.time()

            if now - last_entry_cancel_check >= entry_cancel_check_interval:
                last_entry_cancel_check = now
                reason = None
                try:
                    maybe_cancel = getattr(strategy_instance, "cancel_stale_entry_if_needed", None)
                    if callable(maybe_cancel):
                        reason = maybe_cancel(now_wall_ts=now)
                except Exception as e:
                    reason = f"EXCEPTION: {e}"

                if reason:
                    state["entry_cancel_triggered"] = True
                    state["entry_cancel_last_reason"] = str(reason)
                    state["entry_cancel_last_ts_wall_utc"] = utc_now_iso()
                    logger.warning("[ENTRY_CANCEL] %s", reason)
                    append_jsonl(events_path, {"ts_wall_utc": utc_now_iso(), "type": "ENTRY_CANCEL", "reason": str(reason)})

            if now - last_guard_check >= guard_check_interval:
                last_guard_check = now
                if state.get("guard", {}).get("enabled"):
                    reason = None
                    try:
                        get_reason = getattr(strategy_instance, "get_missing_protection_reason", None)
                        if callable(get_reason):
                            reason = get_reason(now_wall_ts=now)
                    except Exception as e:
                        reason = f"EXCEPTION: {e}"

                    if reason and not bool(state.get("guard_triggered")):
                        state["guard_triggered"] = True
                        state["guard_last_reason"] = str(reason)
                        state["guard_last_ts_wall_utc"] = utc_now_iso()
                        logger.error("[GUARD] Missing protection detected: %s", reason)
                        flatten_now(source="guard", reason=str(reason))
                    elif not reason and bool(state.get("guard_triggered")):
                        state["guard_triggered"] = False

            if now - last_status_write >= status_interval:
                last_status_write = now
                write_status_snapshot()

    finally:
        try:
            bar_streamer.disconnect()
        except Exception:
            pass

        try:
            node.stop()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
