"""
IB Bar Streamer - Direct ib_insync-based bar streaming for live trading.

This module bypasses NautilusTrader's IBKR data client and uses ib_insync directly
to stream live bars. This ensures reliable bar delivery with keepUpToDate=True.

Usage:
    streamer = IBBarStreamer(host="127.0.0.1", port=7497, client_id=20)
    await streamer.connect()
    await streamer.subscribe_bars(
        symbol="EUR/USD",
        bar_size="15 mins",
        callback=strategy.on_bar
    )
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional, List
from dataclasses import dataclass

# Allow nested event loops (needed when reconnecting within NautilusTrader's event loop)
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # nest_asyncio not installed - reconnection may fail in nested event loop scenarios

from ib_insync import IB, Contract, Forex, BarData, BarDataList

from nautilus_trader.model.data import Bar, BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity

logger = logging.getLogger(__name__)


@dataclass
class BarSubscription:
    """Tracks a bar subscription."""
    symbol: str
    bar_type: BarType
    bars: Optional[BarDataList]
    callback: Callable
    last_bar_time: Optional[datetime] = None
    last_bar_received: Optional[datetime] = None  # Wall clock time of last bar
    bar_type_str: Optional[str] = None
    # Store params for re-subscription
    bar_size: str = "15 mins"
    what_to_show: str = "MIDPOINT"
    use_rth: bool = False
    duration: str = "2 D"


class IBBarStreamer:
    """
    Direct ib_insync-based bar streamer.
    
    Uses reqHistoricalData with keepUpToDate=True for reliable live bar streaming.
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 20,
        reconnect_attempts: int = 10,
        reconnect_delay: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.ib = IB()
        self._subscriptions: dict[str, BarSubscription] = {}
        self._running = False
        self._update_task: Optional[asyncio.Task] = None
        self._reconnecting = False
        self._connected = False
        self._error_count = 0
        self._last_error_time: Optional[datetime] = None
        self._reconnect_requested = False  # Flag for main loop to trigger reconnect
        
        # Register error handler
        self.ib.errorEvent += self._on_error

    @staticmethod
    def _subscription_key(symbol: str, bar_size: str, what_to_show: str, use_rth: bool) -> str:
        """Create a stable key for a bar subscription.

        IBKR allows multiple live bar streams per symbol (e.g., 5m + 15m). We must
        not key subscriptions by symbol alone, otherwise later subscriptions will
        overwrite earlier ones.
        """
        return f"{symbol}|{bar_size}|{what_to_show}|{int(bool(use_rth))}"
        
    def connect(self) -> bool:
        """Connect to TWS/Gateway (synchronous)."""
        try:
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=False,
            )
            self._connected = True
            self._error_count = 0
            logger.info(f"IBBarStreamer connected to {self.host}:{self.port} (client_id={self.client_id})")
            return True
        except Exception as e:
            self._connected = False
            logger.error(f"IBBarStreamer connection failed: {e}")
            return False
    
    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract):
        """Handle IB errors - detect disconnection and trigger reconnect."""
        now = datetime.now()
        
        # Critical errors that require reconnection
        critical_errors = {
            1100: "Connectivity between IBKR and TWS lost",
            10182: "Failed to request live updates (disconnected)",
            504: "Not connected",
            502: "Couldn't connect to TWS",
            2110: "Connectivity between TWS and server is broken",
        }
        
        # Recoverable warnings (logged but no action)
        warning_codes = {2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158}
        
        if errorCode in warning_codes:
            logger.debug(f"IB Warning {errorCode}: {errorString}")
            return
        
        if errorCode in critical_errors:
            self._error_count += 1
            self._last_error_time = now
            logger.error(f"[CRITICAL] IB Error {errorCode}: {critical_errors[errorCode]} - {errorString}")
            
            # Mark as disconnected
            self._connected = False
            
            # Trigger reconnection (in a thread-safe way)
            if not self._reconnecting and self._running:
                logger.info("Triggering auto-reconnect due to critical error...")
                self._schedule_reconnect()
        else:
            # Log other errors
            if errorCode not in (162,):  # 162 is historical data cancelled - expected on disconnect
                logger.warning(f"IB Error {errorCode} (reqId={reqId}): {errorString}")
    
    def _schedule_reconnect(self):
        """Schedule a reconnection attempt (will be executed by main loop)."""
        if self._reconnecting:
            return
        self._reconnect_requested = True
        logger.info("Reconnection scheduled - will execute on next main loop cycle")
    
    def _reconnect(self):
        """
        Attempt to reconnect and restore subscriptions.
        
        IMPORTANT: This must be called from the main thread to ensure
        ib_insync callbacks work correctly with the event loop.
        """
        import time
        
        if self._reconnecting:
            return False
        
        self._reconnecting = True
        self._reconnect_requested = False
        
        logger.info("=" * 60)
        logger.info("RECONNECTION PROCESS STARTED")
        logger.info("=" * 60)
        
        # Store subscription params before disconnect
        saved_subs = {}
        for sub_key, sub in self._subscriptions.items():
            saved_subs[sub_key] = {
                "symbol": sub.symbol,
                "bar_type_str": sub.bar_type_str,
                "bar_size": sub.bar_size,
                "what_to_show": sub.what_to_show,
                "callback": sub.callback,
                "use_rth": sub.use_rth,
                "duration": sub.duration,
            }
        logger.info(f"Saved {len(saved_subs)} subscription(s) for restoration")
        
        # Cancel existing subscriptions and disconnect cleanly
        try:
            for sub in self._subscriptions.values():
                if sub.bars:
                    try:
                        self.ib.cancelHistoricalData(sub.bars)
                    except:
                        pass
        except:
            pass
        
        try:
            if self.ib.isConnected():
                self.ib.disconnect()
        except:
            pass
        
        # Clear subscriptions
        self._subscriptions.clear()
        
        # Wait before reconnecting (IBKR may need time after reset)
        logger.info(f"Waiting {self.reconnect_delay}s before reconnection attempts...")
        time.sleep(self.reconnect_delay)
        
        # Attempt reconnection with exponential backoff
        for attempt in range(1, self.reconnect_attempts + 1):
            logger.info(f"Reconnection attempt {attempt}/{self.reconnect_attempts}...")
            
            try:
                self.ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id,
                    readonly=False,
                )
                
                # Verify connection
                if not self.ib.isConnected():
                    raise ConnectionError("Connect returned but isConnected=False")
                
                self._connected = True
                logger.info(f"Reconnected to {self.host}:{self.port}")
                
                # Wait for IB to stabilize
                logger.info("Waiting for IB to stabilize...")
                time.sleep(2)
                
                # Re-establish subscriptions
                for _sub_key, params in saved_subs.items():
                    logger.info(f"Re-subscribing to {params['symbol']} ({params['bar_size']})...")
                    success = self.subscribe_bars_sync(
                        symbol=params["symbol"],
                        bar_size=params["bar_size"],
                        what_to_show=params["what_to_show"],
                        callback=params["callback"],
                        use_rth=params["use_rth"],
                        duration=params["duration"],
                        is_resubscribe=True,  # Don't feed historical bars again
                        bar_type_str=params.get("bar_type_str"),
                    )
                    if success:
                        logger.info(f"Successfully re-subscribed to {params['symbol']} ({params['bar_size']})")
                    else:
                        logger.error(f"Failed to re-subscribe to {params['symbol']} ({params['bar_size']})")
                
                self._reconnecting = False
                self._error_count = 0
                logger.info("=" * 60)
                logger.info("RECONNECTION COMPLETE - All subscriptions restored")
                logger.info("=" * 60)
                return True
                
            except Exception as e:
                logger.error(f"Reconnection attempt {attempt} failed: {e}")
                # Exponential backoff: 5s, 10s, 20s, 40s...
                wait_time = self.reconnect_delay * (2 ** (attempt - 1))
                wait_time = min(wait_time, 120)  # Cap at 2 minutes
                logger.info(f"Waiting {wait_time}s before next attempt...")
                time.sleep(wait_time)
        
        logger.error("=" * 60)
        logger.error(f"RECONNECTION FAILED after {self.reconnect_attempts} attempts")
        logger.error("Manual restart may be required")
        logger.error("=" * 60)
        self._reconnecting = False
        return False
    
    def needs_reconnect(self) -> bool:
        """Check if reconnection has been requested."""
        return self._reconnect_requested and not self._reconnecting
    
    def disconnect(self):
        """Disconnect from TWS/Gateway."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
        for sub in self._subscriptions.values():
            if sub.bars:
                self.ib.cancelHistoricalData(sub.bars)
        self.ib.disconnect()
        logger.info("IBBarStreamer disconnected")
    
    def _create_contract(self, symbol: str) -> Contract:
        """Create IB contract from symbol."""
        # Handle forex pairs like "EUR/USD"
        if "/" in symbol:
            base, quote = symbol.split("/")
            return Forex(pair=f"{base}{quote}")
        else:
            # Assume stock
            from ib_insync import Stock
            return Stock(symbol, "SMART", "USD")
    
    def _ib_bar_to_nautilus(
        self,
        ib_bar: BarData,
        bar_type: BarType,
    ) -> Bar:
        """Convert ib_insync BarData to NautilusTrader Bar."""
        # Convert datetime to nanoseconds
        ts_event = int(ib_bar.date.timestamp() * 1_000_000_000)
        ts_init = ts_event  # Use bar's actual time for proper resampling
        
        return Bar(
            bar_type=bar_type,
            open=Price.from_str(str(ib_bar.open)),
            high=Price.from_str(str(ib_bar.high)),
            low=Price.from_str(str(ib_bar.low)),
            close=Price.from_str(str(ib_bar.close)),
            volume=Quantity.from_str(str(int(ib_bar.volume)) if ib_bar.volume >= 0 else "0"),
            ts_event=ts_event,
            ts_init=ts_init,
        )
    
    def subscribe_bars_sync(
        self,
        symbol: str,
        bar_size: str = "15 mins",
        what_to_show: str = "MIDPOINT",
        callback: Callable = None,
        use_rth: bool = False,
        duration: str = "2 D",
        is_resubscribe: bool = False,
        bar_type_str: Optional[str] = None,
    ) -> bool:
        """
        Subscribe to live bar updates (synchronous version for use with ib_insync).
        
        Args:
            symbol: Symbol like "EUR/USD" or "AAPL"
            bar_size: IB bar size like "15 mins", "1 hour", "1 day"
            what_to_show: "MIDPOINT", "TRADES", "BID", "ASK"
            callback: Function to call with each new bar (receives NautilusTrader Bar)
            use_rth: Use regular trading hours only
            duration: How much historical data to request initially
            is_resubscribe: If True, skip feeding historical bars (used during reconnect)
            bar_type_str: Optional BarType string to guarantee exact matching with StrategyConfig
            
        Returns:
            True if subscription successful
        """
        try:
            contract = self._create_contract(symbol)
            
            # Qualify the contract (synchronous)
            self.ib.qualifyContracts(contract)
            logger.info(f"Qualified contract: {contract}")
            
            # Create BarType for NautilusTrader.
            # IMPORTANT: if the caller provides `bar_type_str`, use it to guarantee exact
            # matching with StrategyConfig (avoids bar_type mismatch filtering in Strategy.on_bar).
            if bar_type_str:
                bar_type = BarType.from_str(bar_type_str)
            else:
                # Fallback: derive BarType from IB subscription params.
                # Parse bar_size like "15 mins" -> 15, MINUTE
                parts = bar_size.split()
                step = int(parts[0])
                unit = parts[1].upper()
                
                if unit in ("MIN", "MINS", "MINUTE", "MINUTES"):
                    aggregation = BarAggregation.MINUTE
                elif unit in ("HOUR", "HOURS"):
                    aggregation = BarAggregation.HOUR
                elif unit in ("DAY", "DAYS"):
                    aggregation = BarAggregation.DAY
                else:
                    aggregation = BarAggregation.MINUTE
                
                # Determine price type
                if what_to_show == "MIDPOINT":
                    price_type = PriceType.MID
                elif what_to_show == "BID":
                    price_type = PriceType.BID
                elif what_to_show == "ASK":
                    price_type = PriceType.ASK
                else:
                    price_type = PriceType.LAST
                
                # Create venue from symbol
                venue = Venue("IDEALPRO") if "/" in symbol else Venue("SMART")
                instrument_id = InstrumentId(Symbol(symbol), venue)
                bar_spec = BarSpecification(step, aggregation, price_type)
                bar_type = BarType(instrument_id, bar_spec, aggregation_source=1)  # EXTERNAL (1=EXTERNAL, 2=INTERNAL)
            
            # Request historical data with keepUpToDate=True
            bars = self.ib.reqHistoricalData(
                contract=contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                keepUpToDate=True,  # THIS IS THE KEY - live updates!
            )
            
            logger.info(f"Subscribed to {symbol} {bar_size} bars (keepUpToDate=True)")
            logger.info(f"Initial historical bars: {len(bars)}")
            
            # Store subscription with params for potential re-subscription
            subscription = BarSubscription(
                symbol=symbol,
                bar_type=bar_type,
                bars=bars,
                callback=callback,
                last_bar_time=(bars[-2].date if bars and len(bars) >= 2 else (bars[-1].date if bars else None)),
                last_bar_received=datetime.now() if bars else None,  # Initialize wall clock time
                bar_type_str=bar_type_str,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
                duration=duration,
            )
            sub_key = self._subscription_key(symbol, bar_size, what_to_show, use_rth)
            self._subscriptions[sub_key] = subscription
            
            # Set up bar update handler
            bars.updateEvent += lambda bars, hasNewBar: self._on_bar_update(
                sub_key, bars, hasNewBar
            )
            
            # Feed initial historical bars to callback for warmup (skip on resubscribe)
            if callback and bars and not is_resubscribe:
                logger.info(f"Feeding {len(bars)} historical bars for warmup...")
                for ib_bar in bars[:-1]:
                    nautilus_bar = self._ib_bar_to_nautilus(ib_bar, bar_type)
                    try:
                        callback(nautilus_bar)
                    except Exception as e:
                        logger.error(f"Error in bar callback: {e}")
                logger.info("Historical bars fed to strategy")
            elif is_resubscribe:
                logger.info(f"Resubscription complete - skipped {len(bars)} historical bars")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol} bars: {e}")
            return False

    def get_warmup_bars_sync(
        self,
        symbol: str,
        bar_size: str,
        what_to_show: str = "MIDPOINT",
        use_rth: bool = False,
    ) -> List[Bar]:
        """Return the initially downloaded historical bars (completed bars only) for a subscription.

        This is used by strategies that need to merge-sort warmup bars across multiple
        timeframes before processing, to avoid lookahead/stitching artifacts.

        Returns:
            List of NautilusTrader Bar objects, excluding the last (possibly in-progress) bar.
        """
        sub_key = self._subscription_key(symbol, bar_size, what_to_show, use_rth)
        sub = self._subscriptions.get(sub_key)
        if sub is None or sub.bars is None:
            return []
        if len(sub.bars) <= 1:
            return []
        out: List[Bar] = []
        for ib_bar in sub.bars[:-1]:
            out.append(self._ib_bar_to_nautilus(ib_bar, sub.bar_type))
        return out
    
    def _on_bar_update(self, sub_key: str, bars: BarDataList, has_new_bar: bool):
        """Handle bar updates from ib_insync."""
        if sub_key not in self._subscriptions:
            return
        
        sub = self._subscriptions[sub_key]
        
        if not bars:
            return
        
        # Check if this is a new bar or update to existing
        if has_new_bar:
            if len(bars) < 2:
                logger.warning(
                    f"[LIVE BAR] {sub.symbol} ({sub.bar_size}): hasNewBar=True but only {len(bars)} bar(s), skipping"
                )
                return
            
            completed_bar = bars[-2]
            
            logger.info(
                f"[LIVE BAR] {sub.symbol} ({sub.bar_size}): "
                f"time={completed_bar.date}, O={completed_bar.open}, H={completed_bar.high}, "
                f"L={completed_bar.low}, C={completed_bar.close}"
            )
            
            # Update last bar time
            sub.last_bar_time = completed_bar.date
            sub.last_bar_received = datetime.now()  # Wall clock time
            
            # Convert and send to callback
            if sub.callback:
                try:
                    nautilus_bar = self._ib_bar_to_nautilus(completed_bar, sub.bar_type)
                    sub.callback(nautilus_bar)
                except Exception as e:
                    logger.error(f"Error in bar callback: {e}")
        else:
            # Bar update (price changed but bar not complete)
            # Optionally log updates
            pass
    
    async def run_forever(self):
        """Run the event loop to receive bar updates."""
        self._running = True
        logger.info("IBBarStreamer running - waiting for bar updates...")
        
        while self._running:
            # ib_insync handles events internally, we just need to keep the loop alive
            await asyncio.sleep(0.1)
            self.ib.sleep(0)  # Process IB events
    
    def get_subscription_status(self) -> dict:
        """Get status of all subscriptions."""
        status = {}
        for sub_key, sub in self._subscriptions.items():
            status[sub_key] = {
                "symbol": sub.symbol,
                "bar_size": sub.bar_size,
                "what_to_show": sub.what_to_show,
                "use_rth": sub.use_rth,
                "bar_type": str(sub.bar_type),
                "last_bar_time": sub.last_bar_time.isoformat() if sub.last_bar_time else None,
                "bars_count": len(sub.bars) if sub.bars else 0,
            }
        return status
    
    def is_connected(self) -> bool:
        """Check if connected to IB."""
        return self._connected and self.ib.isConnected()
    
    def is_reconnecting(self) -> bool:
        """Check if currently reconnecting."""
        return self._reconnecting
    
    def get_error_count(self) -> int:
        """Get count of critical errors since last successful connection."""
        return self._error_count
    
    def check_health(self, max_bar_age_minutes: int = 20) -> bool:
        """
        Check if bar streaming is healthy.
        
        Returns True if healthy, False if reconnection is needed.
        Automatically triggers reconnection if unhealthy.
        
        Args:
            max_bar_age_minutes: Maximum allowed time since last bar (default 20 mins for 15-min bars)
        """
        now = datetime.now()
        
        # If already reconnecting, return False but don't trigger again
        if self._reconnecting:
            return False
        
        # Check if IB thinks it's connected
        try:
            ib_connected = self.ib.isConnected()
        except:
            ib_connected = False
        
        if not ib_connected:
            logger.warning("[HEALTH CHECK] IB connection lost - scheduling reconnect")
            self._connected = False
            self._schedule_reconnect()
            return False
        
        # Check if we're receiving bars (for each subscription)
        for sub_key, sub in self._subscriptions.items():
            if sub.last_bar_received:
                age = (now - sub.last_bar_received).total_seconds() / 60.0
                if age > max_bar_age_minutes:
                    logger.warning(
                        f"[HEALTH CHECK] No bars received for {sub.symbol} ({sub.bar_size}) in {age:.1f} minutes "
                        f"(max={max_bar_age_minutes}) - scheduling reconnect"
                    )
                    self._connected = False
                    self._schedule_reconnect()
                    return False
        
        return True
    
    def get_last_bar_age_seconds(self) -> Optional[float]:
        """Get age of last received bar in seconds."""
        if not self._subscriptions:
            return None
        
        oldest_age = None
        for sub in self._subscriptions.values():
            if sub.last_bar_received:
                age = (datetime.now() - sub.last_bar_received).total_seconds()
                if oldest_age is None or age > oldest_age:
                    oldest_age = age
        
        return oldest_age
    
    def check_for_new_bars(self):
        """Manually check for new bars (workaround for updateEvent not firing)."""
        for sub_key, sub in self._subscriptions.items():
            if not sub.bars:
                continue
            
            if len(sub.bars) < 2:
                continue
            
            completed_bar = sub.bars[-2]
            
            if sub.last_bar_time is None or completed_bar.date > sub.last_bar_time:
                logger.info(f"[MANUAL CHECK] New completed bar detected for {sub.symbol} ({sub.bar_size})!")
                self._on_bar_update(sub_key, sub.bars, has_new_bar=True)


async def test_bar_streamer():
    """Test the bar streamer."""
    logging.basicConfig(level=logging.INFO)
    
    streamer = IBBarStreamer(host="127.0.0.1", port=7497, client_id=25)
    
    if not await streamer.connect():
        print("Failed to connect")
        return
    
    def on_bar(bar):
        print(f"Received bar: {bar}")
    
    success = await streamer.subscribe_bars(
        symbol="EUR/USD",
        bar_size="15 mins",
        what_to_show="MIDPOINT",
        callback=on_bar,
    )
    
    if success:
        print("Subscription successful, waiting for bars...")
        try:
            await streamer.run_forever()
        except KeyboardInterrupt:
            print("Stopping...")
    
    streamer.disconnect()


if __name__ == "__main__":
    asyncio.run(test_bar_streamer())
