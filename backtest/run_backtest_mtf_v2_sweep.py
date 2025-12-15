import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pandas_ta as ta
from joblib import load
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_v2_config import load_mtf_v2_config


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def load_and_prepare_data(bar_type: str, start_date: str, end_date: str) -> pd.DataFrame:
    catalog_path = os.environ.get("CATALOG_PATH", str(PROJECT_ROOT / "data" / "historical"))
    catalog = ParquetDataCatalog(catalog_path)

    bars = catalog.bars(bar_types=[bar_type])
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for bar_type={bar_type}")

    df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(b.ts_init, unit="ns", tz="UTC") for b in bars],
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
        }
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    df = df[start_date:end_date]
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["hl2"] = (df["high"] + df["low"]) / 2
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1)) * 100

    mama_fama = ta.mama(df["hl2"], fast=0.5, slow=0.05)
    df["mama"] = mama_fama.iloc[:, 0]
    df["fama"] = mama_fama.iloc[:, 1]
    df["mama_diff"] = (df["mama"] - df["fama"]) / df["close"]

    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14) / df["close"]
    df["hour"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek

    df_30m = (
        df.resample("30min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )

    dmi_30m = ta.adx(df_30m["high"], df_30m["low"], df_30m["close"], length=14)
    df_30m["dmp"] = dmi_30m.iloc[:, 1] / 100.0
    df_30m["dmn"] = dmi_30m.iloc[:, 2] / 100.0

    stoch_30m = ta.stoch(df_30m["high"], df_30m["low"], df_30m["close"], k=14, d=3, smooth_k=3)
    df_30m["stoch_k"] = stoch_30m.iloc[:, 0] / 100.0
    df_30m["stoch_d"] = stoch_30m.iloc[:, 1] / 100.0

    wma_short = ta.wma(df_30m["close"], length=8)
    wma_long = ta.wma(df_30m["close"], length=23)
    df_30m["wma_diff"] = 100 * (wma_short - wma_long) / wma_long

    df_30m_renamed = df_30m[["dmp", "dmn", "stoch_k", "stoch_d", "wma_diff"]].copy()
    df_30m_renamed.columns = ["dmp_30m", "dmn_30m", "stoch_k_30m", "stoch_d_30m", "wma_diff_30m"]

    df = df.join(df_30m_renamed, how="left").ffill().dropna()
    return df


def calculate_commission(position_size: float) -> float:
    return max(1.00, float(position_size) * 0.00002)


def _utc_to_est_fallback(utc_timestamp: pd.Timestamp) -> tuple[int, int]:
    est_hour = utc_timestamp.hour - 5
    est_weekday = utc_timestamp.weekday()
    if est_hour < 0:
        est_hour += 24
        est_weekday = (est_weekday - 1) % 7
    return est_hour, est_weekday


def utc_to_est(utc_timestamp: pd.Timestamp) -> tuple[int, int]:
    try:
        import zoneinfo

        eastern = zoneinfo.ZoneInfo("America/New_York")
        eastern_dt = utc_timestamp.to_pydatetime().astimezone(eastern)
        return int(eastern_dt.hour), int(eastern_dt.weekday())
    except Exception:
        return _utc_to_est_fallback(utc_timestamp)


def simulate_2pos_strategy(df: pd.DataFrame, model: Any, config: Dict[str, Any], log_file: Optional[Any] = None) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    position: Optional[Dict[str, Any]] = None
    position_size = float(config["position_size"])

    excluded_hours_mode = str(config.get("excluded_hours_mode", "simple"))
    config_timezone = str(config.get("config_timezone", "UTC")).upper()
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
        if position is not None:
            current_price = float(row["close"])
            atr_value = float(position["atr_value"])

            profit = current_price - float(position["entry"]) if position["side"] == "LONG" else float(position["entry"]) - current_price
            profit_atr = profit / atr_value if atr_value != 0 else 0.0

            position["bars_in_trade"] += 1
            if profit_atr > position["max_profit_atr"]:
                position["max_profit_atr"] = profit_atr

            if (
                bool(config.get("stall_detection_enabled", False))
                and not position.get("pos1_closed", False)
                and not position.get("stall_sl_applied", False)
            ):
                stall_check_bars = int(config.get("stall_check_bars", 6))
                stall_min_profit_atr = _safe_float(config.get("stall_min_profit_atr", 0.2), 0.2)
                stall_sl_atr = _safe_float(config.get("stall_sl_atr", 0.2), 0.2)
                tp1_atr = _safe_float(config.get("pos1_tp_atr_mult", 0.6), 0.6)

                if position["bars_in_trade"] >= stall_check_bars and stall_min_profit_atr <= position["max_profit_atr"] < tp1_atr:
                    new_sl_distance = atr_value * stall_sl_atr
                    if position["side"] == "LONG":
                        new_sl = float(position["entry"]) + new_sl_distance
                        if new_sl > float(position["sl"]):
                            position["sl"] = new_sl
                            position["stall_sl_applied"] = True
                            if log_file:
                                log_file.write(f"{idx} | STALL detected, SL tightened to {stall_sl_atr} ATR\n")
                    else:
                        new_sl = float(position["entry"]) - new_sl_distance
                        if new_sl < float(position["sl"]):
                            position["sl"] = new_sl
                            position["stall_sl_applied"] = True
                            if log_file:
                                log_file.write(f"{idx} | STALL detected, SL tightened to {stall_sl_atr} ATR\n")

            if not position.get("pos1_closed", False):
                if profit_atr >= _safe_float(config.get("pos1_tp_atr_mult", 0.6), 0.6):
                    layer_size = float(position["initial_size"]) * _safe_float(config.get("pos1_fraction", 0.85), 0.85)
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)

                    position["pos1_closed"] = True
                    position["pos1_pnl"] = layer_pnl - layer_commission
                    position["size"] -= layer_size

                    position["sl"] = float(position["entry"]) + (0.0001 if position["side"] == "LONG" else -0.0001)
                    position["trailing_active"] = True

                    if log_file:
                        log_file.write(f"{idx} | POS1 TP hit, SL moved to BE, trailing ON\n")

            if position.get("trailing_active", False):
                trail_distance = atr_value * _safe_float(config.get("trailing_distance_atr_mult", 0.4), 0.4)
                if position["side"] == "LONG":
                    new_sl = current_price - trail_distance
                    if new_sl > float(position["sl"]):
                        position["sl"] = new_sl
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < float(position["sl"]):
                        position["sl"] = new_sl

            if not position.get("pos2_closed", False) and position.get("pos1_closed", False) and float(position["size"]) > 0:
                if profit_atr >= _safe_float(config.get("pos2_tp_atr_mult", 1.5), 1.5):
                    layer_size = float(position["size"])
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)
                    total_pnl = float(position.get("pos1_pnl", 0.0)) + layer_pnl - layer_commission

                    trades.append(
                        {
                            "entry_time": position["entry_time"],
                            "exit_time": idx,
                            "side": position["side"],
                            "entry": float(position["entry"]),
                            "exit": current_price,
                            "pnl": total_pnl,
                            "exit_reason": "TP",
                            "partial_closed": True,
                            "entry_hour": int(position["entry_hour"]),
                            "entry_weekday": int(position["entry_weekday"]),
                            "duration_bars": int(position.get("bars_in_trade", 0)),
                            "entry_month": position["entry_time"].strftime("%Y-%m"),
                        }
                    )
                    position = None
                    continue

            sl_hit = False
            exit_price = float(position["sl"])
            if position["side"] == "LONG":
                if float(row["low"]) <= float(position["sl"]):
                    sl_hit = True
                    exit_price = float(position["sl"])
            else:
                if float(row["high"]) >= float(position["sl"]):
                    sl_hit = True
                    exit_price = float(position["sl"])

            if sl_hit:
                remaining_profit = exit_price - float(position["entry"]) if position["side"] == "LONG" else float(position["entry"]) - exit_price
                remaining_pnl = remaining_profit * float(position["size"])
                remaining_commission = calculate_commission(float(position["size"]))
                total_pnl = float(position.get("pos1_pnl", 0.0)) + remaining_pnl - remaining_commission

                exit_type = "TRAILING_STOP" if position.get("trailing_active", False) else "SL"
                trades.append(
                    {
                        "entry_time": position["entry_time"],
                        "exit_time": idx,
                        "side": position["side"],
                        "entry": float(position["entry"]),
                        "exit": exit_price,
                        "pnl": total_pnl,
                        "exit_reason": exit_type,
                        "partial_closed": bool(position.get("pos1_closed", False)),
                        "entry_hour": int(position["entry_hour"]),
                        "entry_weekday": int(position["entry_weekday"]),
                        "duration_bars": int(position.get("bars_in_trade", 0)),
                        "entry_month": position["entry_time"].strftime("%Y-%m"),
                    }
                )
                position = None
                continue

            continue

        if config_timezone == "EST":
            current_hour, current_weekday = utc_to_est(idx)
        else:
            current_hour = int(idx.hour)
            current_weekday = int(idx.weekday())

        utc_hour = int(idx.hour)
        if not (int(config["trade_start_hour"]) <= utc_hour < int(config["trade_end_hour"])):
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

        atr = float(row["atr"])
        if atr < float(config["min_atr"]) or atr > float(config["max_atr"]):
            continue

        probs = model.predict_proba(features)[0]
        prediction = int(model.predict(features)[0])
        confidence = float(probs[1] if prediction == 1 else probs[0])
        if confidence < float(config["prediction_threshold"]):
            continue

        entry_price = float(row["close"])
        atr_value = atr * entry_price

        if prediction == 1:
            sl = entry_price - (atr_value * float(config["sl_atr_mult"]))
            side = "LONG"
        else:
            sl = entry_price + (atr_value * float(config["sl_atr_mult"]))
            side = "SHORT"

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
            "pos1_pnl": 0.0,
            "entry_commission": calculate_commission(position_size),
            "entry_hour": current_hour,
            "entry_weekday": current_weekday,
            "bars_in_trade": 0,
            "max_profit_atr": 0.0,
            "stall_sl_applied": False,
        }

        if log_file:
            log_file.write(f"{idx} | ENTRY {side} @ {entry_price:.5f} | SL={sl:.5f} | Conf={confidence:.3f}\n")

    return trades


def compute_performance_stats(trades: List[Dict[str, Any]], starting_capital: float) -> Dict[str, Any]:
    if not trades:
        pnls = {
            "PnL (total)": 0.0,
            "PnL% (total)": 0.0,
            "Max Winner": 0.0,
            "Avg Winner": 0.0,
            "Max Loser": 0.0,
            "Avg Loser": 0.0,
            "Expectancy": 0.0,
            "Win Rate": 0.0,
        }
        general = {"Total trades": 0, "Sharpe ratio": 0.0, "Profit factor": 0.0, "Max drawdown": 0.0}
        return {"pnls": pnls, "general": general, "rejected_signals_count": 0}

    df = pd.DataFrame(trades).copy()
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df = df.sort_values("exit_time")

    total_pnl = float(df["pnl"].sum())
    total_trades = int(len(df))

    wins = df[df["pnl"] > 0.0]
    losses = df[df["pnl"] < 0.0]

    win_rate = float(len(wins) / total_trades * 100.0) if total_trades else 0.0
    max_winner = float(wins["pnl"].max()) if not wins.empty else 0.0
    avg_winner = float(wins["pnl"].mean()) if not wins.empty else 0.0
    max_loser = float(losses["pnl"].min()) if not losses.empty else 0.0
    avg_loser = float(losses["pnl"].mean()) if not losses.empty else 0.0
    expectancy = float(df["pnl"].mean()) if total_trades else 0.0

    sum_wins = float(wins["pnl"].sum()) if not wins.empty else 0.0
    sum_losses = float(losses["pnl"].sum()) if not losses.empty else 0.0
    profit_factor = (sum_wins / abs(sum_losses)) if sum_losses != 0.0 else (float("inf") if sum_wins > 0 else 0.0)

    equity = float(starting_capital)
    peak = float(starting_capital)
    max_dd = 0.0
    for pnl in df["pnl"].tolist():
        equity += float(pnl)
        if equity > peak:
            peak = equity
        dd = (peak - equity)
        if dd > max_dd:
            max_dd = dd

    df["date"] = df["exit_time"].dt.date
    daily_pnl = df.groupby("date")["pnl"].sum()
    sharpe = 0.0
    if len(daily_pnl) >= 2 and float(daily_pnl.std()) > 0:
        sharpe = float((daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252))

    pnls = {
        "PnL (total)": total_pnl,
        "PnL% (total)": (total_pnl / float(starting_capital) * 100.0) if starting_capital else 0.0,
        "Max Winner": max_winner,
        "Avg Winner": avg_winner,
        "Max Loser": max_loser,
        "Avg Loser": avg_loser,
        "Expectancy": expectancy,
        "Win Rate": win_rate,
    }

    general = {
        "Total trades": total_trades,
        "Sharpe ratio": sharpe,
        "Profit factor": profit_factor,
        "Max drawdown": max_dd,
    }

    return {"pnls": pnls, "general": general, "rejected_signals_count": 0}


def main() -> int:
    config = load_mtf_v2_config()

    run_id = os.environ.get("GRID_RUN_ID", "")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_root = Path(os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "backtest_results")))
    output_root.mkdir(parents=True, exist_ok=True)

    tag = f"MTF_V2_GRID_{timestamp}"
    if run_id:
        tag = f"{tag}_run{run_id}"

    output_dir = output_root / tag
    output_dir.mkdir(parents=True, exist_ok=True)

    log_file_path = output_dir / "strategy_decisions.log"

    model = load(PROJECT_ROOT / config.model_path)

    bar_type = str(config.bar_type).replace("/", "")
    df = load_and_prepare_data(bar_type, config.backtest_start, config.backtest_end)
    df = calculate_features(df)

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
        "stall_detection_enabled": config.stall_detection_enabled,
        "stall_check_bars": config.stall_check_bars,
        "stall_min_profit_atr": config.stall_min_profit_atr,
        "stall_sl_atr": config.stall_sl_atr,
    }

    with open(log_file_path, "w", encoding="utf-8") as log_file:
        trades = simulate_2pos_strategy(df, model, sim_config, log_file)

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df.to_csv(output_dir / "trades.csv", index=False)

        positions_df = trades_df[["entry_time", "exit_time", "pnl"]].copy()
        positions_df.rename(columns={"entry_time": "ts_opened", "exit_time": "ts_closed", "pnl": "realized_pnl_usd"}, inplace=True)
        positions_df["ts_opened"] = pd.to_datetime(positions_df["ts_opened"], utc=True)
        positions_df["ts_closed"] = pd.to_datetime(positions_df["ts_closed"], utc=True)
        positions_df.to_csv(output_dir / "positions.csv", index=False)
    else:
        pd.DataFrame(columns=["ts_opened", "ts_closed", "realized_pnl_usd"]).to_csv(output_dir / "positions.csv", index=False)

    stats = compute_performance_stats(trades, starting_capital=float(config.initial_balance))
    with open(output_dir / "performance_stats.json", "w", encoding="utf-8") as f:
        import json

        json.dump(stats, f, indent=2)

    print(f"Results written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
