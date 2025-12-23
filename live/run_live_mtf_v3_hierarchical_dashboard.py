from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_v3_config import load_mtf_v3_config
from live.hmtf_csv_logger import HmtfCsvLogger
from live.hmtf_engine import (
    BarEvent,
    BarEventRouter,
    DummyMasterModel,
    DummySoldierModel,
    FeatureStore,
    MultiTimeframeEngine,
    SyncGate,
    TradingStateMachine,
)
from live.ib_bar_streamer import IBBarStreamer

logger = logging.getLogger("live_mtf_v3_hierarchical")


def _load_env_file() -> None:
    env_file = PROJECT_ROOT / ".env.mtf_v3"
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _instrument_to_ib_symbol(instrument: str) -> str:
    # Expected format: "EUR/USD.IDEALPRO" -> "EUR/USD"
    s = str(instrument).strip()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _nt_bar_to_event(nt_bar, timeframe: str) -> BarEvent:
    # Nautilus Bar uses nanosecond ts_event; treat it as the bar close timestamp.
    end_time = datetime.fromtimestamp(nt_bar.ts_event / 1_000_000_000, tz=timezone.utc)
    return BarEvent(
        timeframe=timeframe,
        end_time_utc=end_time,
        o=float(nt_bar.open.as_double()),
        h=float(nt_bar.high.as_double()),
        l=float(nt_bar.low.as_double()),
        c=float(nt_bar.close.as_double()),
        v=float(nt_bar.volume.as_double()) if hasattr(nt_bar.volume, "as_double") else 0.0,
    )


async def main_async() -> int:
    _load_env_file()
    cfg = load_mtf_v3_config()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    symbol = _instrument_to_ib_symbol(cfg.instrument)

    dataset_logger = None
    if cfg.dataset_enabled:
        dataset_logger = HmtfCsvLogger(path=Path(cfg.dataset_path))

    store = FeatureStore()
    sync = SyncGate(store)
    sm = TradingStateMachine(cooldown_minutes=cfg.cooldown_minutes)

    engine = MultiTimeframeEngine(
        store=store,
        sync=sync,
        sm=sm,
        master_model=DummyMasterModel(),
        soldier_model=DummySoldierModel(),
        master_threshold=cfg.master_prediction_threshold,
        dataset_logger=dataset_logger,
    )
    router = BarEventRouter(engine)

    streamer = IBBarStreamer(
        host=cfg.ibkr_host,
        port=cfg.ibkr_port,
        client_id=cfg.ibkr_client_id,
    )

    stop_event = asyncio.Event()

    def _request_stop(_sig=None, _frame=None) -> None:
        try:
            logger.info("Stopping v3 runner...")
            streamer.disconnect()
        finally:
            stop_event.set()

    try:
        signal.signal(signal.SIGINT, _request_stop)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except Exception:
        pass

    if not streamer.connect():
        logger.error("IBBarStreamer connect failed")
        return 1

    ok_15m = streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=cfg.master_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
        duration=cfg.initial_duration,
        callback=lambda b: router.submit(_nt_bar_to_event(b, timeframe="15m")),
    )
    ok_5m = streamer.subscribe_bars_sync(
        symbol=symbol,
        bar_size=cfg.soldier_bar_size,
        what_to_show=cfg.what_to_show,
        use_rth=cfg.use_rth,
        duration=cfg.initial_duration,
        callback=lambda b: router.submit(_nt_bar_to_event(b, timeframe="5m")),
    )

    if not ok_15m or not ok_5m:
        logger.error("Failed to subscribe bars (15m_ok=%s, 5m_ok=%s)", ok_15m, ok_5m)
        streamer.disconnect()
        return 1

    logger.info(
        "MTF v3 runner started. symbol=%s 15m='%s' 5m='%s' dataset=%s",
        symbol,
        cfg.master_bar_size,
        cfg.soldier_bar_size,
        cfg.dataset_path if cfg.dataset_enabled else "disabled",
    )

    run_task = asyncio.create_task(streamer.run_forever())
    await stop_event.wait()

    try:
        await asyncio.wait_for(run_task, timeout=5.0)
    except Exception:
        pass

    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
