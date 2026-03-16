import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Optional
import logging

from ib_insync import IB

from ..config.config import StrategyConfig
from ..core.interfaces import ExecutionEngine, MarketContext
from ..core.market_event import Fill, RangeInfo, Tick
from ..strategy.orb_strategy import ORBStrategy

class LiveRunner:
    """
    Orchestrates live execution.
    Handles the async polling rhythm, state persistence to JSON, and coordinates deep modules.
    """
    def __init__(
        self, 
        ib: IB,
        config: StrategyConfig, 
        context: MarketContext, 
        execution: ExecutionEngine, 
        state_file: str,
        logger: Optional[logging.Logger] = None
    ):
        self.ib = ib
        self.config = config
        self.context = context
        self.execution = execution
        self.strategy = ORBStrategy(config, logger=logger)
        self.state_file = Path(state_file)
        self.logger = logger or logging.getLogger(__name__)
        
        # Track if we've calculated today's range
        self.range_calculated_today = False
        self.last_date = None
        
        self._load_state()

    def _load_state(self):
        """Transparently loads strategy state on startup."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    snapshot = json.load(f)
                    
                # Only restore if it's the same trade date
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if snapshot.get("trade_date") == today_str:
                    self.strategy.restore_state(snapshot)
                    print(f"Restored strategy state: {self.strategy.state}")
            except Exception as e:
                print(f"Error loading state: {e}")

    def _save_state(self):
        """Transparently saves strategy state after each tick."""
        snapshot = self.strategy.get_state_snapshot()
        snapshot["trade_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Write atomically
        temp_file = self.state_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(snapshot, f)
        os.replace(temp_file, self.state_file)

    def on_tick_received(self, tick: Tick):
        """
        Callback from LiveMarketContext when a new tick arrives.
        """
        # Strategy processes the tick
        self.strategy.on_tick(tick, self.context, self.execution)
        
        # Save state transparently (Strategy doesn't know this happens)
        self._save_state()

    def on_fill_received(self, fill: Fill):
        """
        Callback from IBKRExecutionEngine when an order fills.
        """
        self.strategy.on_fill(fill, self.context, self.execution)
        self._save_state()
        
    def run_polling_loop(self, poll_interval_seconds: int = 2):
        """
        Main polling loop for live trading.
        
        Responsibilities:
        1. Check if new day started -> reset strategy state
        2. Check if range calculation time -> calculate and cache daily range
        3. Sleep and let tick callbacks handle the rest
        
        Args:
            poll_interval_seconds: How often to check for daily reset/range calc
        """
        self.logger.info("Starting live trading loop")
        
        try:
            while True:
                now = datetime.now(timezone.utc)
                current_date = now.date()
                
                # Daily reset at start of range period
                if self.last_date != current_date:
                    self.logger.info(f"New trading day: {current_date}")
                    self._reset_daily_state()
                    self.last_date = current_date
                    
                # Calculate range at end of range window
                if not self.range_calculated_today and now.hour == self.config.range_end_hour:
                    self._calculate_and_set_range(now.replace(tzinfo=None))
                    
                # CRITICAL: use ib.sleep() so ib_insync event loop processes
                # tick callbacks. time.sleep() would block all IBKR events.
                self.ib.sleep(poll_interval_seconds)
                
        except KeyboardInterrupt:
            self.logger.info("Live trading stopped by user")
            self._cleanup()
        except Exception as e:
            self.logger.error(f"Fatal error in live loop: {e}", exc_info=True)
            self._cleanup()
            raise
            
    def _reset_daily_state(self):
        """
        Reset strategy state for new trading day.
        Called at start of new day.
        """
        from ..strategy.orb_strategy import StrategyState
        
        self.logger.info("Resetting strategy state for new day")
        
        # Cancel any resting orders
        self.execution.cancel_orb_brackets()
        
        # Close any open positions (safety)
        if self.execution.position != 0:
            self.logger.warning("Position still open at daily reset - closing at market")
            self.execution.close_at_market()
            
        # Reset strategy
        self.strategy.state = StrategyState.IDLE
        self.strategy.range = None
        
        # Reset range calculation flag
        self.range_calculated_today = False
        
        self._save_state()
        
    def _calculate_and_set_range(self, current_time: datetime):
        """
        Calculate Asian range from live tick history and cache it.
        Called once per day at range_end_hour.
        """
        self.logger.info(f"Calculating Asian range ({self.config.range_start_hour}-{self.config.range_end_hour} UTC)")
        
        # Use LiveMarketContext method to calculate from buffered ticks
        range_info = self.context.calculate_range_from_history(
            self.config.range_start_hour,
            self.config.range_end_hour
        )
        
        if range_info:
            # Validate range
            if range_info.is_valid(self.config.min_range_size, self.config.max_range_size):
                self.context.set_daily_range(range_info, current_time)
                self.logger.info(f"Valid range calculated: {range_info.low:.4f} - {range_info.high:.4f} (size: {range_info.high - range_info.low:.4f})")
            else:
                self.logger.warning(f"Range invalid (size: {range_info.high - range_info.low:.4f}), strategy will skip today")
                
        else:
            self.logger.warning("Could not calculate range from tick history (insufficient data)")
            
        self.range_calculated_today = True
        
    def _cleanup(self):
        """
        Cleanup before shutdown.
        """
        self.logger.info("Cleaning up LiveRunner")
        
        # Save final state
        self._save_state()
        
        # Cancel all orders
        self.execution.cancel_orb_brackets()
        
        # Disconnect market context if it has cleanup
        if hasattr(self.context, 'disconnect'):
            self.context.disconnect()
