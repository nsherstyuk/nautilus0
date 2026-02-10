import os
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from joblib import load

from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config
from run_backtest_mtf_v2_full import (
    load_and_prepare_data,
    calculate_features,
    generate_reports,
    calculate_commission,
    utc_to_est,
)
from utils.run_metadata import log_and_write_run_metadata


def _get_bool(env_name: str, default: bool = False) -> bool:
    val = os.getenv(env_name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def load_dynamic_sizing_config_from_env() -> dict:
    return {
        "enabled": _get_bool("BT_DYNAMIC_SIZING_ENABLED", False),
        "use_risk_cap": _get_bool("BT_SIZING_USE_RISK_CAP", True),
        "starting_equity_usd": float(os.getenv("BT_STARTING_EQUITY_USD", "nan")),
        "lot_size_units": int(os.getenv("BT_LOT_SIZE_UNITS", "100000")),
        "margin_per_100k_usd": float(os.getenv("BT_MARGIN_PER_100K_USD", "3200")),
        "target_margin_usage": float(os.getenv("BT_TARGET_MARGIN_USAGE", "0.35")),
        "risk_per_trade_pct": float(os.getenv("BT_RISK_PER_TRADE_PCT", "0.015")),
        "min_lots": int(os.getenv("BT_MIN_LOTS", "1")),
        "max_lots": int(os.getenv("BT_MAX_LOTS", "100")),
    }


def _compute_position_size_dynamic(
    equity_usd: float,
    entry_price: float,
    stop_price: float,
    dyn: dict,
) -> tuple[int, int, dict]:
    lot_units = int(dyn["lot_size_units"])
    min_lots = int(dyn["min_lots"])
    max_lots = int(dyn["max_lots"])

    margin_per_100k = float(dyn["margin_per_100k_usd"])
    target_margin_usage = float(dyn["target_margin_usage"])

    risk_per_trade_pct = float(dyn["risk_per_trade_pct"])
    use_risk_cap = bool(dyn["use_risk_cap"])

    pip_size = 0.0001
    stop_pips = abs(entry_price - stop_price) / pip_size if pip_size > 0 else 0.0

    risk_per_100k_usd = stop_pips * 10.0

    max_lots_margin = 0
    if margin_per_100k > 0 and target_margin_usage > 0:
        max_lots_margin = int((equity_usd * target_margin_usage) // margin_per_100k)

    max_lots_risk = max_lots
    if use_risk_cap:
        risk_budget = equity_usd * risk_per_trade_pct
        if risk_per_100k_usd > 0:
            max_lots_risk = int(risk_budget // risk_per_100k_usd)
        else:
            max_lots_risk = max_lots

    lots = min(max_lots_margin, max_lots_risk)
    lots = max(min_lots, lots)
    lots = min(max_lots, lots)

    position_size_units = lots * lot_units

    meta = {
        "equity_usd": float(equity_usd),
        "stop_pips": float(stop_pips),
        "risk_per_100k_usd": float(risk_per_100k_usd),
        "max_lots_margin": int(max_lots_margin),
        "max_lots_risk": int(max_lots_risk),
    }

    return position_size_units, lots, meta


def simulate_2pos_strategy_dynamic_sizing(df, model, config: dict, dyn: dict, log_file=None) -> list:
    trades = []
    position = None

    base_position_size = int(config["position_size"])

    entry_cooldown_bars = int(config.get("entry_cooldown_bars", 0) or 0)
    cooldown_remaining_bars = 0

    if np.isfinite(dyn.get("starting_equity_usd", float("nan"))):
        equity = float(dyn["starting_equity_usd"])
    else:
        equity = float(config.get("initial_balance", 0.0))

    excluded_hours_mode = config.get("excluded_hours_mode", "simple")
    config_timezone = config.get("config_timezone", "UTC").upper()
    excluded_hours = {
        0: config.get("excluded_hours_monday", []),
        1: config.get("excluded_hours_tuesday", []),
        2: config.get("excluded_hours_wednesday", []),
        3: config.get("excluded_hours_thursday", []),
        4: config.get("excluded_hours_friday", []),
        5: config.get("excluded_hours_saturday", []),
        6: config.get("excluded_hours_sunday", []),
    }

    for idx, row in df.iterrows():
        if position is None and cooldown_remaining_bars > 0:
            cooldown_remaining_bars -= 1
            continue

        if position is not None:
            current_price = row["close"]
            atr_value = position["atr_value"]

            if position["side"] == "LONG":
                profit = current_price - position["entry"]
            else:
                profit = position["entry"] - current_price

            profit_atr = profit / atr_value

            position["bars_in_trade"] += 1
            if profit_atr > position["max_profit_atr"]:
                position["max_profit_atr"] = profit_atr

            if (
                config.get("stall_detection_enabled", False)
                and not position.get("pos1_closed", False)
                and not position.get("stall_sl_applied", False)
            ):
                stall_check_bars = config.get("stall_check_bars", 6)
                stall_min_profit_atr = config.get("stall_min_profit_atr", 0.2)
                stall_sl_atr = config.get("stall_sl_atr", 0.2)
                tp1_atr = config["pos1_tp_atr_mult"]

                if (
                    position["bars_in_trade"] >= stall_check_bars
                    and stall_min_profit_atr <= position["max_profit_atr"] < tp1_atr
                ):
                    new_sl_distance = atr_value * stall_sl_atr
                    if position["side"] == "LONG":
                        new_sl = position["entry"] + new_sl_distance
                        if new_sl > position["sl"]:
                            position["sl"] = new_sl
                            position["stall_sl_applied"] = True
                            if log_file:
                                log_file.write(
                                    f"{idx} | STALL detected: max={position['max_profit_atr']:.2f} ATR, SL tightened to {stall_sl_atr} ATR\n"
                                )
                    else:
                        new_sl = position["entry"] - new_sl_distance
                        if new_sl < position["sl"]:
                            position["sl"] = new_sl
                            position["stall_sl_applied"] = True
                            if log_file:
                                log_file.write(
                                    f"{idx} | STALL detected: max={position['max_profit_atr']:.2f} ATR, SL tightened to {stall_sl_atr} ATR\n"
                                )

            if (
                config.get("neg_stall_enabled", False)
                and not position.get("pos1_closed", False)
                and not position.get("neg_stall_triggered", False)
            ):
                neg_stall_check_bars = int(config.get("neg_stall_check_bars", 8))
                neg_stall_max_profit_atr = float(config.get("neg_stall_max_profit_atr", 0.0))
                neg_stall_trigger_loss_atr = float(config.get("neg_stall_trigger_loss_atr", 0.4))

                if (
                    position["bars_in_trade"] >= neg_stall_check_bars
                    and position["max_profit_atr"] <= neg_stall_max_profit_atr
                    and profit_atr <= -neg_stall_trigger_loss_atr
                ):
                    position["neg_stall_triggered"] = True

                    exit_price = current_price
                    if position["side"] == "LONG":
                        remaining_profit = exit_price - position["entry"]
                    else:
                        remaining_profit = position["entry"] - exit_price

                    remaining_pnl = remaining_profit * position["size"]
                    remaining_commission = calculate_commission(position["size"])
                    total_pnl = position.get("pos1_pnl", 0) + remaining_pnl - remaining_commission

                    equity_before = equity
                    equity = equity + total_pnl

                    trades.append(
                        {
                            "entry_time": position["entry_time"],
                            "exit_time": idx,
                            "side": position["side"],
                            "entry": position["entry"],
                            "exit": exit_price,
                            "pnl": total_pnl,
                            "exit_reason": "NEG_STALL",
                            "partial_closed": position.get("pos1_closed", False),
                            "entry_hour": position["entry_hour"],
                            "entry_weekday": position["entry_weekday"],
                            "duration_bars": 0,
                            "entry_month": position["entry_time"].strftime("%Y-%m"),
                            "position_size": position["initial_size"],
                            "lots": position.get("lots", None),
                            "equity_before": equity_before,
                            "equity_after": equity,
                        }
                    )

                    if log_file:
                        log_file.write(
                            f"{idx} | NEG_STALL exit: max={position['max_profit_atr']:.2f} ATR, curr={profit_atr:.2f} ATR, PnL=${total_pnl:.2f} | Equity=${equity:.2f}\n"
                        )

                    position = None
                    if entry_cooldown_bars > 0:
                        cooldown_remaining_bars = entry_cooldown_bars
                    continue

            if not position.get("pos1_closed", False):
                if profit_atr >= config["pos1_tp_atr_mult"]:
                    layer_size = position["initial_size"] * config["pos1_fraction"]
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)

                    position["pos1_closed"] = True
                    position["pos1_pnl"] = layer_pnl - layer_commission
                    position["size"] -= layer_size

                    position["sl"] = position["entry"] + (0.0001 if position["side"] == "LONG" else -0.0001)
                    position["trailing_active"] = True

                    if log_file:
                        log_file.write(
                            f"{idx} | POS1 TP hit, profit_atr={profit_atr:.2f}, SL->BE, trailing ON\n"
                        )

            if position.get("trailing_active", False):
                trail_distance = atr_value * config["trailing_distance_atr_mult"]

                if position["side"] == "LONG":
                    new_sl = current_price - trail_distance
                    if new_sl > position["sl"]:
                        position["sl"] = new_sl
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < position["sl"]:
                        position["sl"] = new_sl

            if (
                not position.get("pos2_closed", False)
                and position.get("pos1_closed", False)
                and position["size"] > 0
            ):
                if profit_atr >= config["pos2_tp_atr_mult"]:
                    layer_size = position["size"]
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)

                    total_pnl = position.get("pos1_pnl", 0) + layer_pnl - layer_commission

                    equity_before = equity
                    equity = equity + total_pnl

                    trades.append(
                        {
                            "entry_time": position["entry_time"],
                            "exit_time": idx,
                            "side": position["side"],
                            "entry": position["entry"],
                            "exit": current_price,
                            "pnl": total_pnl,
                            "exit_reason": "TP",
                            "partial_closed": True,
                            "entry_hour": position["entry_hour"],
                            "entry_weekday": position["entry_weekday"],
                            "duration_bars": 0,
                            "entry_month": position["entry_time"].strftime("%Y-%m"),
                            "position_size": position["initial_size"],
                            "lots": position.get("lots", None),
                            "equity_before": equity_before,
                            "equity_after": equity,
                        }
                    )

                    if log_file:
                        log_file.write(
                            f"{idx} | TRADE CLOSED {position['side']} TP PnL=${total_pnl:.2f} | Equity=${equity:.2f}\n"
                        )

                    position = None
                    if entry_cooldown_bars > 0:
                        cooldown_remaining_bars = entry_cooldown_bars
                    continue

            sl_hit = False
            exit_price = position["sl"]
            if position["side"] == "LONG":
                if row["low"] <= position["sl"]:
                    sl_hit = True
                    exit_price = position["sl"]
            else:
                if row["high"] >= position["sl"]:
                    sl_hit = True
                    exit_price = position["sl"]

            if sl_hit:
                if position["side"] == "LONG":
                    remaining_profit = exit_price - position["entry"]
                else:
                    remaining_profit = position["entry"] - exit_price

                remaining_pnl = remaining_profit * position["size"]
                remaining_commission = calculate_commission(position["size"])

                total_pnl = position.get("pos1_pnl", 0) + remaining_pnl - remaining_commission

                exit_type = "TRAILING_STOP" if position.get("trailing_active", False) else "SL"

                equity_before = equity
                equity = equity + total_pnl

                trades.append(
                    {
                        "entry_time": position["entry_time"],
                        "exit_time": idx,
                        "side": position["side"],
                        "entry": position["entry"],
                        "exit": exit_price,
                        "pnl": total_pnl,
                        "exit_reason": exit_type,
                        "partial_closed": position.get("pos1_closed", False),
                        "entry_hour": position["entry_hour"],
                        "entry_weekday": position["entry_weekday"],
                        "duration_bars": 0,
                        "entry_month": position["entry_time"].strftime("%Y-%m"),
                        "position_size": position["initial_size"],
                        "lots": position.get("lots", None),
                        "equity_before": equity_before,
                        "equity_after": equity,
                    }
                )

                if log_file:
                    log_file.write(
                        f"{idx} | TRADE CLOSED {position['side']} {exit_type} PnL=${total_pnl:.2f} | Equity=${equity:.2f}\n"
                    )

                position = None
                if entry_cooldown_bars > 0:
                    cooldown_remaining_bars = entry_cooldown_bars
                continue

            continue

        if config_timezone == "EST":
            current_hour, current_weekday = utc_to_est(idx)
        else:
            current_hour = idx.hour
            current_weekday = idx.weekday()

        utc_hour = idx.hour
        if not (config["trade_start_hour"] <= utc_hour < config["trade_end_hour"]):
            continue

        if excluded_hours_mode == "weekday":
            if current_hour in excluded_hours.get(current_weekday, []):
                continue

        try:
            features = np.array(
                [
                    row["log_ret"],
                    row["mama_diff"],
                    row["dmp_30m"],
                    row["dmn_30m"],
                    row["stoch_k_30m"],
                    row["stoch_d_30m"],
                    row["wma_diff_30m"],
                    row["atr"],
                    row["hour"],
                    row["day_of_week"],
                ]
            ).reshape(1, -1)

            if np.isnan(features).any():
                continue
        except Exception:
            continue

        atr = row["atr"]
        if atr < config["min_atr"] or atr > config["max_atr"]:
            continue

        probs = model.predict_proba(features)[0]
        prediction = model.predict(features)[0]
        confidence = float(probs[1] if prediction == 1 else probs[0])

        if confidence < config["prediction_threshold"]:
            continue

        entry_price = row["close"]
        atr_value = atr * entry_price

        if prediction == 1:
            sl = entry_price - (atr_value * config["sl_atr_mult"])
            side = "LONG"
        else:
            sl = entry_price + (atr_value * config["sl_atr_mult"])
            side = "SHORT"

        if dyn.get("enabled", False):
            position_size, lots, sizing_meta = _compute_position_size_dynamic(equity, entry_price, sl, dyn)
        else:
            position_size = base_position_size
            lots = None
            sizing_meta = None

        entry_commission = calculate_commission(position_size)

        position = {
            "entry_time": idx,
            "entry": entry_price,
            "side": side,
            "sl": sl,
            "initial_size": position_size,
            "size": position_size,
            "atr_value": atr_value,
            "trailing_active": False,
            "pos1_closed": False,
            "pos2_closed": False,
            "pos1_pnl": 0,
            "entry_commission": entry_commission,
            "entry_hour": current_hour,
            "entry_weekday": current_weekday,
            "bars_in_trade": 0,
            "max_profit_atr": 0,
            "stall_sl_applied": False,
            "neg_stall_triggered": False,
            "lots": lots,
            "sizing_meta": sizing_meta,
            "equity_at_entry": equity,
        }

        if log_file:
            if dyn.get("enabled", False):
                log_file.write(
                    f"{idx} | ENTRY {side} @ {entry_price:.5f} | SL={sl:.5f} | Conf={confidence:.3f} | Size={position_size} | Equity=${equity:.2f}\n"
                )
            else:
                log_file.write(
                    f"{idx} | ENTRY {side} @ {entry_price:.5f} | SL={sl:.5f} | Conf={confidence:.3f}\n"
                )

    return trades


def main():
    print("=" * 80)
    print("MTF V2 BACKTEST - FULL REPORTING (DYNAMIC SIZING VARIANT)")
    print("=" * 80)

    config = load_mtf_v2_config()
    print_mtf_v2_config(config)

    dyn = load_dynamic_sizing_config_from_env()

    neg_stall_enabled = _get_bool("MTF2_NEG_STALL_ENABLED", False)
    neg_stall_check_bars = int(os.getenv("MTF2_NEG_STALL_CHECK_BARS", "8"))
    neg_stall_max_profit_atr = float(os.getenv("MTF2_NEG_STALL_MAX_PROFIT_ATR", "0.0"))
    neg_stall_trigger_loss_atr = float(os.getenv("MTF2_NEG_STALL_TRIGGER_LOSS_ATR", "0.4"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_DYN_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
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

    print("\nLoading model...")
    model = load(PROJECT_ROOT / config.model_path)
    print(f"Model loaded from {config.model_path}")

    print(f"\nLoading data: {config.backtest_start} to {config.backtest_end}...")
    df = load_and_prepare_data(config.backtest_start, config.backtest_end)
    df = calculate_features(df)
    print(f"Data loaded: {len(df)} bars")

    sim_config = {
        "position_size": config.total_position_size,
        "pos1_fraction": config.pos1_fraction,
        "pos2_fraction": config.pos2_fraction,
        "sl_atr_mult": config.sl_atr_mult,
        "pos1_tp_atr_mult": config.pos1_tp_atr_mult,
        "pos2_tp_atr_mult": config.pos2_tp_atr_mult,
        "trailing_distance_atr_mult": config.trailing_distance_atr_mult,
        "prediction_threshold": config.prediction_threshold,
        "trade_start_hour": config.trade_start_hour,
        "trade_end_hour": config.trade_end_hour,
        "min_atr": config.min_atr,
        "max_atr": config.max_atr,
        "config_timezone": config.config_timezone,
        "excluded_hours_mode": config.excluded_hours_mode,
        "excluded_hours_monday": config.excluded_hours_monday,
        "excluded_hours_tuesday": config.excluded_hours_tuesday,
        "excluded_hours_wednesday": config.excluded_hours_wednesday,
        "excluded_hours_thursday": config.excluded_hours_thursday,
        "excluded_hours_friday": config.excluded_hours_friday,
        "excluded_hours_saturday": config.excluded_hours_saturday,
        "excluded_hours_sunday": config.excluded_hours_sunday,
        "entry_cooldown_bars": config.entry_cooldown_bars,
        "backtest_start": config.backtest_start,
        "backtest_end": config.backtest_end,
        "stall_detection_enabled": config.stall_detection_enabled,
        "stall_check_bars": config.stall_check_bars,
        "stall_min_profit_atr": config.stall_min_profit_atr,
        "stall_sl_atr": config.stall_sl_atr,
        "neg_stall_enabled": neg_stall_enabled,
        "neg_stall_check_bars": neg_stall_check_bars,
        "neg_stall_max_profit_atr": neg_stall_max_profit_atr,
        "neg_stall_trigger_loss_atr": neg_stall_trigger_loss_atr,
        "initial_balance": config.initial_balance,
    }

    print("\nRunning simulation...")
    log_file_path = output_dir / "strategy_decisions.log"
    with open(log_file_path, "w") as log_file:
        log_file.write(f"MTF V2 Backtest Log (Dynamic Sizing) - {timestamp}\n")
        log_file.write("=" * 80 + "\n\n")
        trades = simulate_2pos_strategy_dynamic_sizing(df, model, sim_config, dyn, log_file)

    print(f"Simulation complete: {len(trades)} trades")
    print("Saved: strategy_decisions.log")

    print("\nGenerating reports...")
    generate_reports(trades, output_dir, sim_config)

    print("\n" + "=" * 80)
    print(f"BACKTEST COMPLETE - Results saved to: {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
