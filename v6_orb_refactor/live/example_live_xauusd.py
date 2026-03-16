"""
Complete example of V6 live trading setup for XAUUSD.
Demonstrates how to wire up all components for production trading.
"""
import logging
from pathlib import Path

from ib_insync import IB, Contract

from v6_orb_refactor.config.config import StrategyConfig
from v6_orb_refactor.live.live_context import LiveMarketContext
from v6_orb_refactor.live.ibkr_executor import IBKRExecutionEngine
from v6_orb_refactor.live.runner import LiveRunner


def create_xauusd_contract() -> Contract:
    """Create IBKR contract for XAUUSD (Gold vs USD)."""
    contract = Contract(
        symbol='XAUUSD',
        secType='CMDTY',
        exchange='SMART',
        currency='USD'
    )
    return contract


def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler('v6_live_xauusd.log'),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger('v6_live_xauusd')
    
    logger.info("="*60)
    logger.info("V6 LIVE TRADING - XAUUSD")
    logger.info("="*60)
    
    # XAUUSD ORB Configuration
    config = StrategyConfig(
        instrument="XAUUSD",
        range_start_hour=0,
        range_end_hour=6,
        trade_start_hour=8,
        trade_end_hour=16,
        skip_weekdays=[2],  # Skip Wednesday
        velocity_filter_enabled=True,
        velocity_lookback_minutes=3,
        velocity_threshold=168.0,  # P50 from research
        rr_ratio=2.5,
        min_range_size=1.0,
        max_range_size=15.0
    )
    
    logger.info(f"Config: Range {config.range_start_hour}-{config.range_end_hour} UTC")
    logger.info(f"        Trade {config.trade_start_hour}-{config.trade_end_hour} UTC")
    logger.info(f"        Velocity threshold: {config.velocity_threshold} ticks/min")
    logger.info(f"        RR ratio: {config.rr_ratio}")
    
    # Connect to IBKR
    logger.info("Connecting to IBKR...")
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=1)  # TWS paper trading
    logger.info("Connected to IBKR")
    
    # Create contract
    contract = create_xauusd_contract()
    
    # Instantiate deep modules
    logger.info("Initializing trading modules...")
    
    # Market context (handles tick subscription and velocity calculation)
    context = LiveMarketContext(
        ib=ib,
        contract=contract,
        tick_buffer_minutes=config.velocity_lookback_minutes + 5,
        logger=logger
    )
    
    # State file for persistence across restarts
    state_file = Path('v6_state') / 'xauusd_state.json'
    state_file.parent.mkdir(exist_ok=True)
    
    # Create runner first (needs ib for event loop)
    # Execution engine created with placeholder callback, wired below
    execution = IBKRExecutionEngine(
        ib=ib,
        contract=contract,
        quantity=1,  # 1 troy ounce
        on_fill_callback=lambda fill: None,  # Replaced below
        logger=logger
    )
    
    runner = LiveRunner(
        ib=ib,
        config=config,
        context=context,
        execution=execution,
        state_file=str(state_file),
        logger=logger
    )
    
    # Wire callbacks now that runner exists
    context.on_tick_callback = runner.on_tick_received
    execution.on_fill_callback = runner.on_fill_received
    
    logger.info("="*60)
    logger.info("Live trading initialized successfully")
    logger.info("Starting main loop (Ctrl+C to stop)")
    logger.info("="*60)
    
    # Run the main loop
    try:
        runner.run_polling_loop(poll_interval_seconds=2)
    finally:
        # run_polling_loop catches KeyboardInterrupt and calls _cleanup()
        # but ensure IBKR disconnect happens regardless
        if ib.isConnected():
            ib.disconnect()
            logger.info("Disconnected from IBKR")


if __name__ == "__main__":
    main()
