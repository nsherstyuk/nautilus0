"""MTF V3 Configuration Loader (Hierarchical 15m -> 5m).

Loads settings from .env.mtf_v3.

Design goals:
- Keep MTF3_* variables separate so v3 can run alongside v2.
- Keep .env.mtf_v3 as a superset (generic IBKR/backtest + MTF3 + appended MTF2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class MTFV3Config:
    # IBKR
    ibkr_host: str
    ibkr_port: int
    ibkr_client_id: int
    ibkr_account: str
    ibkr_gateway: bool
    ibkr_market_data_type: str

    # Instrument / streaming
    instrument: str
    master_bar_size: str
    soldier_bar_size: str
    what_to_show: str
    use_rth: bool
    initial_duration: str

    # Master permission
    master_prediction_threshold: float
    master_threshold_mode: str

    # State machine
    cooldown_minutes: int

    # Risk/exits (per spec)
    tp_atr_mult: float
    sl_atr_mult: float
    risk_per_trade_pct: float

    # Dataset
    dataset_enabled: bool
    dataset_path: str

    # Models
    master_model_path: str
    soldier_model_path: str
    feature_list_path: str
    soldier_model_enabled: bool

    # Training knobs
    train_sample_weight_mode: str
    train_optimize_for: str

    # Router buffering (quarter-hour ordering / stitching correctness)
    router_max_hold_seconds: float


def load_mtf_v3_config(env_file: Optional[str] = None) -> MTFV3Config:
    if env_file is None:
        project_root = Path(__file__).resolve().parent.parent
        env_file = project_root / ".env.mtf_v3"

    load_dotenv(env_file, override=False)

    return MTFV3Config(
        ibkr_host=os.getenv("MTF3_IBKR_HOST", "127.0.0.1"),
        ibkr_port=int(os.getenv("MTF3_IBKR_PORT", "7497")),
        ibkr_client_id=int(os.getenv("MTF3_IBKR_CLIENT_ID", "28")),
        ibkr_account=os.getenv("MTF3_IBKR_ACCOUNT", ""),
        ibkr_gateway=os.getenv("MTF3_IBKR_GATEWAY", "False").lower() == "true",
        ibkr_market_data_type=os.getenv("MTF3_IBKR_MARKET_DATA_TYPE", "DELAYED_FROZEN"),

        instrument=os.getenv("MTF3_INSTRUMENT", "EUR/USD.IDEALPRO"),
        master_bar_size=os.getenv("MTF3_MASTER_BAR_SIZE", "15 mins"),
        soldier_bar_size=os.getenv("MTF3_SOLDIER_BAR_SIZE", "5 mins"),
        what_to_show=os.getenv("MTF3_WHAT_TO_SHOW", "MIDPOINT"),
        use_rth=os.getenv("MTF3_USE_RTH", "False").lower() == "true",
        initial_duration=os.getenv("MTF3_INITIAL_DURATION", "2 D"),

        master_prediction_threshold=float(os.getenv("MTF3_MASTER_PREDICTION_THRESHOLD", "0.70")),
        master_threshold_mode=os.getenv("MTF3_MASTER_THRESHOLD_MODE", "abs"),

        cooldown_minutes=int(os.getenv("MTF3_COOLDOWN_MINUTES", "30")),

        tp_atr_mult=float(os.getenv("MTF3_TP_ATR_MULT", "0.6")),
        sl_atr_mult=float(os.getenv("MTF3_SL_ATR_MULT", "1.4")),
        risk_per_trade_pct=float(os.getenv("MTF3_RISK_PER_TRADE_PCT", "0.01")),

        dataset_enabled=os.getenv("MTF3_DATASET_ENABLED", "True").lower() == "true",
        dataset_path=os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv"),

        master_model_path=os.getenv("MTF3_MASTER_MODEL_PATH", "models/master_15m_model.pkl"),
        soldier_model_path=os.getenv("MTF3_SOLDIER_MODEL_PATH", "models/soldier_5m_xgb.pkl"),
        feature_list_path=os.getenv("MTF3_FEATURE_LIST_PATH", "models/soldier_5m_feature_names.txt"),
        soldier_model_enabled=os.getenv("MTF3_SOLDIER_MODEL_ENABLED", "False").lower() == "true",

        train_sample_weight_mode=os.getenv("MTF3_TRAIN_SAMPLE_WEIGHT_MODE", "abs_master"),
        train_optimize_for=os.getenv("MTF3_TRAIN_OPTIMIZE_FOR", "precision"),

        router_max_hold_seconds=float(os.getenv("MTF3_ROUTER_MAX_HOLD_SECONDS", "420")),
    )
