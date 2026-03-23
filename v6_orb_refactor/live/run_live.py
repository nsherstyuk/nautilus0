"""
V6 ORB Live Trading Entry Point.

Usage:
    python -m v6_orb_refactor.live.run_live
    python -m v6_orb_refactor.live.run_live --dry-run
    python -m v6_orb_refactor.live.run_live --port 4001 --instrument XAUUSD
    python -m v6_orb_refactor.live.run_live --config path/to/config.yaml
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ib_insync import Contract

from ..config.config import load_live_config
from ..strategy.orb_strategy import ORBStrategy
from .connection import SharedConnection
from .ibkr_executor import IBKRExecutionEngine
from .live_context import LiveMarketContext
from .runner import LiveRunner
from .guardrails import Guardrails


def setup_logging(log_file: str, level: str = "INFO") -> logging.Logger:
    """Configure logging to both file and console."""
    logger = logging.getLogger("v6_orb")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    try:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        logger.warning(f"Could not create log file {log_file}: {e}")

    return logger


def main():
    parser = argparse.ArgumentParser(
        description="V6 ORB Session Breakout - Live Trading")
    parser.add_argument("--dry-run", action="store_true",
                        help="Connect to IBKR for data but do not place orders")
    parser.add_argument("--port", type=int, default=None,
                        help="Override IBKR port (4001=live, 4002=paper)")
    parser.add_argument("--client-id", type=int, default=None,
                        help="Override IBKR client ID")
    parser.add_argument("--instrument", type=str, default="XAUUSD",
                        help="Instrument to trade (default: XAUUSD)")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config.yaml")
    args = parser.parse_args()

    # Load config
    cfg = load_live_config(yaml_path=args.config, instrument=args.instrument)

    if args.port is not None:
        cfg.ibkr.port = args.port
    if args.client_id is not None:
        cfg.ibkr.client_id = args.client_id
    if args.dry_run:
        cfg.dry_run = True

    # Setup logging
    log = setup_logging(cfg.paths.live_log)
    scfg = cfg.strategy

    # Banner
    print("=" * 65)
    print("  V6 ORB Session Breakout")
    print(f"  Mode: {'DRY RUN' if cfg.dry_run else 'LIVE'}")
    print(f"  IBKR: {cfg.ibkr.host}:{cfg.ibkr.port} "
          f"(clientId={cfg.ibkr.client_id})")
    print(f"  Instrument: {scfg.instrument}")
    print(f"  Range: {scfg.range_start_hour}-{scfg.range_end_hour} UTC")
    print(f"  Trade: {scfg.trade_start_hour}-{scfg.trade_end_hour} UTC")
    print(f"  RR={scfg.rr_ratio} | Qty={scfg.qty} | "
          f"BE={scfg.be_hours}h+{scfg.be_offset}")
    vel_str = (f"Vel={scfg.velocity_threshold}ticks/"
               f"{scfg.velocity_lookback_minutes+1}min"
               if scfg.velocity_filter_enabled else "Vel=off")
    print(f"  {vel_str} | MaxPending={scfg.max_pending_hours}h | "
          f"TimeExit={scfg.time_exit_minutes}min")
    print(f"  State: {cfg.paths.state_dir}")
    print(f"  Logs:  {cfg.paths.log_dir}")
    print("=" * 65)

    if not cfg.dry_run:
        print("\n  WARNING: LIVE MODE -- real orders will be placed!")
        print("  Press Ctrl+C to abort.\n")

    # Connect to IBKR
    conn = SharedConnection(
        host=cfg.ibkr.host, port=cfg.ibkr.port,
        client_id=cfg.ibkr.client_id,
        max_retries=cfg.ibkr.max_retries,
        base_backoff_sec=cfg.ibkr.base_backoff_sec,
        max_backoff_sec=cfg.ibkr.max_backoff_sec,
        heartbeat_interval_sec=cfg.ibkr.heartbeat_interval_sec,
        connect_timeout_sec=cfg.ibkr.connect_timeout_sec,
        logger=log,
    )

    if not conn.connect():
        log.error("Could not connect to IBKR after retries")
        sys.exit(1)

    # Qualify contract
    contract = conn.qualify_contract(
        symbol=cfg.ibkr.symbol, sec_type=cfg.ibkr.sec_type,
        exchange=cfg.ibkr.exchange, currency=cfg.ibkr.currency)

    if not contract:
        log.error(f"Cannot qualify contract: {cfg.ibkr.symbol}")
        conn.disconnect()
        sys.exit(1)

    # Create strategy
    strategy = ORBStrategy(config=scfg, logger=log)

    # Create market context
    context = LiveMarketContext(
        ib=conn.ib, contract=contract,
        tick_buffer_minutes=scfg.velocity_lookback_minutes + 2,
        price_decimals=scfg.price_decimals,
        state_dir=str(cfg.paths.state_dir),
        logger=log,
    )

    # Backfill gap history if needed
    if scfg.gap_filter_enabled:
        n_history = len(context._gap_vol_history)
        min_required = max(scfg.gap_rolling_days // 2, 10)
        if n_history < min_required:
            log.info(
                f"Gap filter enabled but only {n_history} days in history "
                f"(need {min_required}). Triggering backfill...")
            backfilled = context.backfill_gap_history(
                days=80,
                gap_start_hour=scfg.gap_start_hour,
                gap_end_hour=scfg.gap_end_hour,
                asian_start_hour=scfg.range_start_hour,
                asian_end_hour=scfg.range_end_hour,
            )
            if backfilled >= min_required:
                log.info(f"✓ Gap filter ready with {backfilled} days of history")
            else:
                log.warning(
                    f"⚠ Backfill incomplete ({backfilled} days). "
                    f"Gap filter will pass everything for {min_required - backfilled} more days.")
        else:
            log.info(f"Gap filter ready with {n_history} days of history")

    # Create execution engine
    def on_fill(fill):
        runner.on_fill(fill)

    execution = IBKRExecutionEngine(
        ib=conn.ib, contract=contract, quantity=scfg.qty,
        on_fill_callback=on_fill,
        trade_end_hour=scfg.trade_end_hour,
        price_decimals=scfg.price_decimals,
        dry_run=cfg.dry_run,
        logger=log,
    )

    # Create guardrails
    guardrails = Guardrails(
        daily_loss_limit_usd=cfg.guardrails.daily_loss_limit_usd,
        max_positions=cfg.guardrails.max_positions_per_instrument,
        cancel_orphaned_orders=cfg.guardrails.cancel_orphaned_orders,
        close_orphaned_positions=cfg.guardrails.close_orphaned_positions,
        logger=log,
    )

    # Startup scan
    guardrails.on_startup(conn.ib, contract, scfg.instrument)

    # Create runner
    runner = LiveRunner(
        strategy=strategy, context=context, execution=execution,
        connection=conn, config=cfg,
        guardrails=guardrails, logger=log,
    )

    # Start
    log.info(f"V6 ORB ready | {scfg.instrument} | "
             f"{'DRY RUN' if cfg.dry_run else 'LIVE'}")
    runner.start()


if __name__ == "__main__":
    main()
