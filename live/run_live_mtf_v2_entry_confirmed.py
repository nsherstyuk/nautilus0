"""
Run MTF V2 live trading with Entry Confirmation logic.

This is a copy of run_live_mtf_v2.py that uses the new
ml_strategy_mtf_v2_entry_confirmed.py strategy with entry confirmation logic.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "config"))

from config.mtf_v2_config import load_mtf_v2_config
from utils.instruments import normalize_instrument_id, parse_fx_symbol

from live.ib_bar_streamer import IBBarStreamer
from live.ib_order_executor import IBOrderExecutor
from live.risk_manager import RiskManager
from live.position_monitor import PositionMonitor

from nautilus_trader.adapters.betfair.providers import BetfairInstrumentProvider
from nautilus_trader.adapters.betfair.factories import BetfairLiveDataClientFactory
from nautilus_trader.adapters.betfair.config import BetfairInstrumentProviderConfig
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataClientConfig,
    ExecClientConfig,
    TradingNodeConfig,
)
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.enums import OmsType
from nautilus_trader.persistence.external.core import process_files, process_file
from nautilus_trader.persistence.external.readers import CSVReader
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.core.uuid import UUID4

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LiveTradingNodeV2EntryConfirmed:
    """
    Live trading node for V2 strategy with entry confirmation.
    """
    
    def __init__(self, config):
        self.config = config
        self.node = None
        self.bar_streamer = None
        self.order_executor = None
        self.risk_manager = None
        self.position_monitor = None
        
    async def initialize(self):
        """Initialize the live trading node."""
        
        print("=" * 80)
        print("LIVE TRADING - MTF V2 ENTRY CONFIRMED")
        print("=" * 80)
        print(f"Symbol: {self.config.symbol}")
        print(f"Venue: {self.config.venue}")
        print(f"Entry Confirmation: ENABLED")
        print()
        
        # Load configuration
        config = load_mtf_v2_config()
        
        print(f"V2 Configuration:")
        print(f"  [OK] MAMA Filter: {config.meta_filter_mama_enabled}")
        print(f"  [OK] DMI Filter: {config.meta_filter_dmi_enabled}")
        print(f"  [OK] Default SL: {config.sl_atr_mult}x ATR")
        print(f"  [OK] Default TP: {config.pos1_tp_atr_mult}x ATR")
        print(f"  [OK] Position sizing: POS1={config.pos1_fraction:.0%}, POS2={config.pos2_fraction:.0%}")
        print()
        
        # Setup paths
        model_path = Path(config.model_path)
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at {model_path}")
        
        # Normalize symbol and instrument ID
        normalized_symbol = normalize_instrument_id(self.config.symbol, self.config.venue)
        fx_symbol = parse_fx_symbol(self.config.symbol)
        
        # Define bar type
        bar_type = f"{normalized_symbol}-15-MINUTE-MID-EXTERNAL"
        
        # Configure strategy
        strategy_config = ImportableStrategyConfig(
            strategy_path="strategies.ml_strategy_mtf_v2_entry_confirmed:MLSignalStrategyV2EntryConfirmed",
            config_path="strategies.ml_strategy_mtf_v2_entry_confirmed:MLSignalStrategyV2EntryConfirmedConfig",
            config={
                "instrument_id": normalized_symbol,
                "bar_type": bar_type,
                "model_path": str(model_path),
                "total_position_size": config.total_position_size,
                "pos1_fraction": config.pos1_fraction,
                "pos2_fraction": config.pos2_fraction,
                "pos3_fraction": config.pos3_fraction,
                "sl_atr_mult": config.sl_atr_mult,
                "pos1_tp_atr_mult": config.pos1_tp_atr_mult,
                "pos2_tp_atr_mult": config.pos2_tp_atr_mult,
                "pos3_tp_atr_mult": config.pos3_tp_atr_mult,
                "trailing_distance_atr_mult": config.trailing_distance_atr_mult,
                # Entry confirmation settings
                "entry_confirmation_enabled": True,
                "entry_confirmation_bars": 2,
                "entry_confirmation_threshold": 0.2,  # 0.2 ATR favorable movement
                "entry_max_wait_bars": 5,
            },
        )
        
        # Initialize components
        self.bar_streamer = IBBarStreamer(
            symbol=self.config.symbol,
            venue=self.config.venue,
            bar_type=bar_type,
        )
        
        self.order_executor = IBOrderExecutor(
            venue=self.config.venue,
        )
        
        self.risk_manager = RiskManager(
            max_positions=len(["POS1", "POS2"]) if config.pos2_fraction > 0 else 1,
            max_position_size=config.total_position_size,
        )
        
        self.position_monitor = PositionMonitor()
        
        # Configure trading node
        node_config = TradingNodeConfig(
            trader_id="LIVE_TRADER_V2_ENTRY_CONFIRMED",
            strategies=[strategy_config],
            data_clients={
                self.config.venue: LiveDataClientConfig(
                    client_cls="live.ib_bar_streamer:IBBarStreamer",
                    config={
                        "symbol": self.config.symbol,
                        "venue": self.config.venue,
                        "bar_type": bar_type,
                    },
                ),
            },
            exec_clients={
                self.config.venue: ExecClientConfig(
                    client_cls="live.ib_order_executor:IBOrderExecutor",
                    config={
                        "venue": self.config.venue,
                    },
                ),
            },
            timeout_connection=30.0,
            timeout_disconnection=10.0,
            timeout_reconnection=5.0,
            timeout_submit_order=2.0,
            timeout_modify_order=2.0,
            timeout_cancel_order=2.0,
        )
        
        # Create and configure node
        self.node = TradingNode(config=node_config)
        
        # Add custom components
        self.node.trader.add_strategy(self.bar_streamer)
        self.node.trader.add_executor(self.order_executor)
        self.node.trader.add_component(self.risk_manager)
        self.node.trader.add_component(self.position_monitor)
        
        print("Live trading node initialized with entry confirmation")
        
    async def start(self):
        """Start live trading."""
        
        print("\nStarting live trading...")
        print("Press Ctrl+C to stop\n")
        
        # Start the node
        await self.node.start()
        
        print("Live trading started with entry confirmation enabled")
        print("Monitoring for entry confirmation signals...")
        
    async def stop(self):
        """Stop live trading."""
        
        print("\nStopping live trading...")
        
        if self.node:
            await self.node.stop()
        
        print("Live trading stopped")
        
    async def run(self):
        """Run the live trading loop."""
        
        try:
            await self.initialize()
            await self.start()
            
            # Run until interrupted
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print("\nReceived interrupt signal")
        except Exception as e:
            logger.error(f"Live trading error: {e}")
        finally:
            await self.stop()

async def main():
    """Main function."""
    
    # Load configuration
    config = load_mtf_v2_config()
    
    # Create and run live trading node
    trading_node = LiveTradingNodeV2EntryConfirmed(config)
    await trading_node.run()

if __name__ == "__main__":
    asyncio.run(main())
