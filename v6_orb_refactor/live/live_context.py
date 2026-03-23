"""
LiveMarketContext - IBKR tick stream + historical bar wrapper.
Implements MarketContext interface for live trading.

Uses reqMktData for streaming ticks (velocity calculation) and
reqHistoricalData for Asian range calculation (covers full 6h window
even if the process started after range_start_hour).
"""
import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Callable
import logging

from ..core.interfaces import MarketContext
from ..core.market_event import RangeInfo, Tick, GapMetrics


class LiveMarketContext(MarketContext):
    """
    Deep module: Hides IBKR data subscription, tick buffering,
    historical bar fetching, and range calculation.
    """

    def __init__(self, ib, contract,
                 tick_buffer_minutes: int = 10,
                 on_tick_callback: Optional[Callable[[Tick], None]] = None,
                 price_decimals: int = 2,
                 state_dir: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        self.ib = ib
        self.contract = contract
        self.tick_buffer_minutes = tick_buffer_minutes
        self.on_tick_callback = on_tick_callback
        self._d = price_decimals
        self.logger = logger or logging.getLogger(__name__)

        # Rolling tick buffer for velocity calculation
        self.tick_buffer: deque = deque(maxlen=100000)

        # Cached daily range
        self.daily_range: Optional[RangeInfo] = None
        self.daily_range_date: Optional[object] = None

        # Streaming state
        self.ticker = None
        self._last_bid: Optional[float] = None
        self._last_ask: Optional[float] = None

        # Gap filter: rolling history (persists across days)
        self._gap_vol_history: deque = deque(maxlen=200)
        self._gap_range_history: deque = deque(maxlen=200)
        self._current_gap_metrics: Optional[GapMetrics] = None
        self._gap_metrics_date: Optional[object] = None
        self._gap_state_path: Optional[Path] = None
        if state_dir:
            self._gap_state_path = Path(state_dir) / "gap_rolling_history.json"
            self._load_gap_history()

        # Subscribe to market data
        self._subscribe_ticks()

    # ── Subscription ─────────────────────────────────────────────────

    def _subscribe_ticks(self):
        """Subscribe to IBKR streaming market data (reqMktData)."""
        self.logger.info(f"Subscribing to tick data for {self.contract.symbol}")
        self.ticker = self.ib.reqMktData(self.contract, '', False, False)
        self.ib.pendingTickersEvent += self._on_ticker_update

    def _on_ticker_update(self, tickers):
        """Called by ib_insync on every market data update."""
        for ticker in tickers:
            if not (ticker.contract
                    and ticker.contract.conId == self.contract.conId):
                continue

            bid = ticker.bid
            ask = ticker.ask

            # Skip invalid prices (nan or <= 0)
            if (not isinstance(bid, (int, float)) or math.isnan(bid)
                    or bid <= 0):
                continue
            if (not isinstance(ask, (int, float)) or math.isnan(ask)
                    or ask <= 0):
                continue

            # Only record if bid or ask actually changed
            if bid == self._last_bid and ask == self._last_ask:
                continue

            self._last_bid = bid
            self._last_ask = ask

            tick = Tick(
                timestamp=datetime.now(timezone.utc),
                bid=bid,
                ask=ask,
            )
            self.tick_buffer.append(tick)

            if self.on_tick_callback:
                self.on_tick_callback(tick)

    # ── MarketContext interface ──────────────────────────────────────

    def get_velocity(self, lookback_minutes: int,
                     current_time: datetime) -> float:
        """Tick velocity (ticks/min) over the lookback window."""
        cutoff = current_time - timedelta(minutes=lookback_minutes)
        count = sum(1 for t in self.tick_buffer if t.timestamp >= cutoff)
        return count / max(lookback_minutes, 0.01)

    def get_asian_range(self, start_hour: int, end_hour: int,
                        current_time: datetime) -> Optional[RangeInfo]:
        """Return cached range for today, or None."""
        if (self.daily_range
                and self.daily_range_date == current_time.date()):
            return self.daily_range
        return None

    def get_current_price(self, current_time: datetime) -> Optional[float]:
        """Return current mid price from streaming data."""
        if (self._last_bid is not None and self._last_ask is not None
                and self._last_bid > 0 and self._last_ask > 0):
            return (self._last_bid + self._last_ask) / 2
        return None

    def time_is_in_trade_window(self, current_time: datetime,
                                start_hour: int, end_hour: int) -> bool:
        return start_hour <= current_time.hour < end_hour

    def get_gap_metrics(self, current_time: datetime,
                        gap_start_hour: int, gap_end_hour: int,
                        vol_percentile: float, range_percentile: float,
                        rolling_days: int) -> Optional[GapMetrics]:
        """Return pre-computed gap metrics for today. None if unavailable."""
        if (self._current_gap_metrics is not None
                and self._gap_metrics_date == current_time.date()):
            return self._current_gap_metrics
        return None

    def inject_gap_data(self, date, gap_volatility: float,
                        gap_range: float, vol_pctl: float,
                        range_pctl: float, rolling_days: int):
        """Called by LiveRunner before the trade window opens.
        Computes rolling percentile thresholds from internal history."""
        vol_passes = True
        range_passes = True

        n = len(self._gap_vol_history)
        if n >= max(rolling_days // 2, 10):
            vol_window = list(self._gap_vol_history)[-rolling_days:]
            range_window = list(self._gap_range_history)[-rolling_days:]

            vol_idx = min(int(len(vol_window) * vol_pctl / 100), len(vol_window) - 1)
            range_idx = min(int(len(range_window) * range_pctl / 100), len(range_window) - 1)
            vol_threshold = sorted(vol_window)[vol_idx]
            range_threshold = sorted(range_window)[range_idx]

            vol_passes = gap_volatility >= vol_threshold
            range_passes = gap_range >= range_threshold
            self.logger.info(
                f"Gap thresholds: vol_thresh={vol_threshold:.6f}, "
                f"range_thresh={range_threshold:.3f} "
                f"(from {len(vol_window)} days)")

        self._current_gap_metrics = GapMetrics(
            gap_volatility=gap_volatility,
            gap_range=gap_range,
            vol_passes=vol_passes,
            range_passes=range_passes,
        )
        self._gap_metrics_date = date

        # Append AFTER computing thresholds (no lookahead)
        self._gap_vol_history.append(gap_volatility)
        self._gap_range_history.append(gap_range)

        self.logger.info(
            f"Gap metrics: vol={gap_volatility:.6f} "
            f"({'PASS' if vol_passes else 'FAIL'}), "
            f"range={gap_range:.3f} "
            f"({'PASS' if range_passes else 'FAIL'})")

        self._save_gap_history()

    def calculate_gap_metrics_from_ibkr(self, gap_start_hour: int,
                                         gap_end_hour: int,
                                         overnight_range: float) -> tuple:
        """Fetch IBKR 1-min bars for the gap period, compute volatility and range.
        Returns (gap_vol, gap_range). Called by Runner."""
        duration_hours = gap_end_hour - gap_start_hour
        if duration_hours <= 0:
            duration_hours += 24

        try:
            now = datetime.now(timezone.utc)
            gap_end_dt = now.replace(
                hour=gap_end_hour, minute=0, second=0, microsecond=0)

            bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime=gap_end_dt.strftime('%Y%m%d-%H:%M:%S'),
                durationStr=f'{duration_hours * 3600} S',
                barSizeSetting='1 min',
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=2,
            )
            self.ib.sleep(2)

            if not bars or len(bars) < 3:
                self.logger.warning("Not enough IBKR bars for gap metrics")
                return 0.0, 0.0

            gap_start = now.replace(
                hour=gap_start_hour, minute=0, second=0, microsecond=0)
            gap_end = gap_end_dt

            gap_bars = []
            for bar in bars:
                bar_dt = bar.date
                if hasattr(bar_dt, 'astimezone'):
                    bar_dt = bar_dt.astimezone(timezone.utc)
                elif bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                if gap_start <= bar_dt < gap_end:
                    gap_bars.append(bar)

            if len(gap_bars) < 3:
                return 0.0, 0.0

            # Compute gap volatility (std of log returns)
            closes = [b.close for b in gap_bars]
            log_returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0 and closes[i] > 0:
                    log_returns.append(math.log(closes[i] / closes[i - 1]))
            if len(log_returns) < 2:
                gap_vol = 0.0
            else:
                mean_r = sum(log_returns) / len(log_returns)
                var = sum((r - mean_r) ** 2 for r in log_returns) / (
                    len(log_returns) - 1)
                gap_vol = math.sqrt(var)

            # Compute gap range
            gap_high = max(b.high for b in gap_bars)
            gap_low = min(b.low for b in gap_bars)
            gap_range = ((gap_high - gap_low) / overnight_range
                         if overnight_range > 0 else 0.0)

            self.logger.info(
                f"Gap from IBKR bars: vol={gap_vol:.6f}, "
                f"range={gap_range:.3f} ({len(gap_bars)} bars)")
            return gap_vol, gap_range

        except Exception as e:
            self.logger.error(f"IBKR gap bar fetch failed: {e}")
            return 0.0, 0.0

    # ── Gap history persistence ────────────────────────────────────

    def _save_gap_history(self):
        """Persist rolling gap history to disk."""
        if not self._gap_state_path:
            return
        try:
            data = {
                "gap_vol_history": list(self._gap_vol_history),
                "gap_range_history": list(self._gap_range_history),
            }
            self._gap_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._gap_state_path.write_text(json.dumps(data))
        except Exception as e:
            self.logger.warning(f"Failed to save gap history: {e}")

    def _load_gap_history(self):
        """Load rolling gap history from disk on startup."""
        if not self._gap_state_path or not self._gap_state_path.exists():
            return
        try:
            data = json.loads(self._gap_state_path.read_text())
            for v in data.get("gap_vol_history", []):
                self._gap_vol_history.append(v)
            for v in data.get("gap_range_history", []):
                self._gap_range_history.append(v)
            self.logger.info(
                f"Loaded {len(self._gap_vol_history)} days of gap history "
                f"from {self._gap_state_path}")
        except Exception as e:
            self.logger.warning(f"Failed to load gap history: {e}")

    def backfill_gap_history(self, days: int = 70,
                             gap_start_hour: int = 6,
                             gap_end_hour: int = 8,
                             asian_start_hour: int = 0,
                             asian_end_hour: int = 6) -> int:
        """Backfill gap history from IBKR historical data.
        
        Fetches past N days of 1-min bars and computes gap metrics for each
        trading day. Populates the rolling history so the gap filter is
        immediately active instead of requiring a 30-day warmup.
        
        Args:
            days: Number of days to backfill (default 70 to get ~60 trading days)
            gap_start_hour: Gap period start (UTC)
            gap_end_hour: Gap period end (UTC)
            asian_start_hour: Asian range start (UTC)
            asian_end_hour: Asian range end (UTC)
            
        Returns:
            Number of trading days successfully backfilled
        """
        self.logger.info(f"Backfilling gap history from IBKR ({days} calendar days)...")
        
        try:
            # Fetch 1-min bars in 7-day chunks (IBKR practical limit from
            # ingest_historical.py) with 10s pacing between requests
            CHUNK_DAYS = 7
            PACING_SECS = 10
            
            all_bars = []
            end_dt = datetime.now(timezone.utc)
            n_chunks = (days + CHUNK_DAYS - 1) // CHUNK_DAYS
            
            for i in range(n_chunks):
                chunk_end = end_dt - timedelta(days=i * CHUNK_DAYS)
                
                chunk_bars = self.ib.reqHistoricalData(
                    self.contract,
                    endDateTime=chunk_end.strftime('%Y%m%d-%H:%M:%S'),
                    durationStr=f'{CHUNK_DAYS} D',
                    barSizeSetting='1 min',
                    whatToShow='MIDPOINT',
                    useRTH=False,
                    formatDate=2,
                )
                if chunk_bars:
                    all_bars.extend(chunk_bars)
                    self.logger.info(
                        f"  Chunk {i+1}/{n_chunks}: {len(chunk_bars)} bars "
                        f"(total: {len(all_bars)})")
                else:
                    self.logger.warning(f"  Chunk {i+1}/{n_chunks}: no bars")
                
                # IBKR pacing (10s between chunks, per ingest_historical.py)
                if i < n_chunks - 1:
                    self.ib.sleep(PACING_SECS)
            
            if not all_bars:
                self.logger.warning("No bars fetched during backfill")
                return 0
            
            self.logger.info(f"Fetched {len(all_bars)} 1-min bars total")
            
            # Group bars by date
            from collections import defaultdict
            daily_bars = defaultdict(list)
            for bar in all_bars:
                bar_dt = bar.date
                if hasattr(bar_dt, 'astimezone'):
                    bar_dt = bar_dt.astimezone(timezone.utc)
                elif bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                daily_bars[bar_dt.date()].append((bar_dt, bar))
            
            # Process each trading day chronologically
            backfilled = 0
            for date in sorted(daily_bars.keys()):
                # Skip weekends
                if date.weekday() >= 5:
                    continue
                
                day_entries = daily_bars[date]
                
                # Asian range bars
                asian_highs, asian_lows = [], []
                for dt, b in day_entries:
                    if asian_start_hour <= dt.hour < asian_end_hour:
                        asian_highs.append(b.high)
                        asian_lows.append(b.low)
                
                if len(asian_highs) < 10:
                    continue
                
                asian_range = max(asian_highs) - min(asian_lows)
                if asian_range <= 0:
                    continue
                
                # Gap period bars
                gap_closes, gap_highs, gap_lows = [], [], []
                for dt, b in day_entries:
                    if gap_start_hour <= dt.hour < gap_end_hour:
                        gap_closes.append(b.close)
                        gap_highs.append(b.high)
                        gap_lows.append(b.low)
                
                if len(gap_closes) < 3:
                    continue
                
                # Compute gap volatility (std of log returns)
                log_returns = []
                for i in range(1, len(gap_closes)):
                    if gap_closes[i-1] > 0 and gap_closes[i] > 0:
                        log_returns.append(
                            math.log(gap_closes[i] / gap_closes[i-1]))
                
                if len(log_returns) < 2:
                    continue
                
                mean_lr = sum(log_returns) / len(log_returns)
                variance = sum((r - mean_lr) ** 2 for r in log_returns) / (len(log_returns) - 1)
                gap_volatility = math.sqrt(variance)
                
                # Compute gap range
                gap_range = (max(gap_highs) - min(gap_lows)) / asian_range
                
                self._gap_vol_history.append(gap_volatility)
                self._gap_range_history.append(gap_range)
                backfilled += 1
            
            if backfilled > 0:
                self._save_gap_history()
                self.logger.info(
                    f"Backfilled {backfilled} trading days of gap history. "
                    f"Filter is now active.")
            else:
                self.logger.warning("No valid trading days found in backfill period")
            
            return backfilled
            
        except Exception as e:
            self.logger.error(f"Gap history backfill failed: {e}", exc_info=True)
            return 0

    # ── Range calculation ────────────────────────────────────────────

    def set_daily_range(self, range_info: RangeInfo, current_date):
        """Externally set the daily range (called by Runner)."""
        self.daily_range = range_info
        if hasattr(current_date, 'date'):
            self.daily_range_date = current_date.date()
        else:
            self.daily_range_date = current_date
        d = self._d
        self.logger.info(
            f"Daily range set: {range_info.low:.{d}f} - "
            f"{range_info.high:.{d}f} (size={range_info.size:.{d}f})")

    def calculate_range_from_ticks(self, start_hour: int,
                                    end_hour: int) -> Optional[RangeInfo]:
        """Calculate range from buffered tick history.
        Only works if process was running during the full range window."""
        now = datetime.now(timezone.utc)
        range_start = now.replace(
            hour=start_hour, minute=0, second=0, microsecond=0)
        range_end = now.replace(
            hour=end_hour, minute=0, second=0, microsecond=0)

        range_ticks = [t for t in self.tick_buffer
                       if range_start <= t.timestamp < range_end]

        if len(range_ticks) < 10:
            self.logger.warning(
                f"Only {len(range_ticks)} ticks in range window "
                f"{start_hour}-{end_hour} UTC")
            return None

        high = max(t.ask for t in range_ticks)
        low = min(t.bid for t in range_ticks)
        return RangeInfo(high=high, low=low,
                         start_time=range_start, end_time=range_end)

    def calculate_range_from_ibkr_bars(self, start_hour: int,
                                        end_hour: int) -> Optional[RangeInfo]:
        """Calculate range using IBKR historical bars (5-min).
        This is the primary method — works even if the process started
        after the range window opened (covers full 6h from IBKR history)."""
        duration_hours = end_hour - start_hour
        if duration_hours <= 0:
            duration_hours = 24 + duration_hours  # handle midnight wrap

        try:
            now = datetime.now(timezone.utc)
            range_end = now.replace(
                hour=end_hour, minute=0, second=0, microsecond=0)
            range_start = now.replace(
                hour=start_hour, minute=0, second=0, microsecond=0)

            bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime=range_end.strftime('%Y%m%d-%H:%M:%S'),
                durationStr=f'{duration_hours * 3600} S',
                barSizeSetting='5 mins',
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=2,  # UTC
            )
            self.ib.sleep(2)

            if not bars:
                self.logger.warning("No IBKR historical bars returned")
                return None

            # Filter bars within the range window
            range_bars = []
            for bar in bars:
                bar_dt = bar.date
                if hasattr(bar_dt, 'astimezone'):
                    bar_dt = bar_dt.astimezone(timezone.utc)
                elif bar_dt.tzinfo is None:
                    bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                if range_start <= bar_dt < range_end:
                    range_bars.append(bar)

            if not range_bars:
                self.logger.warning(
                    f"No bars in range window {start_hour}-{end_hour} UTC "
                    f"(got {len(bars)} total bars)")
                return None

            high = max(b.high for b in range_bars)
            low = min(b.low for b in range_bars)

            self.logger.info(
                f"Range from IBKR bars: {low:.{self._d}f} - {high:.{self._d}f} "
                f"({len(range_bars)} bars)")
            return RangeInfo(high=high, low=low,
                             start_time=range_start, end_time=range_end)

        except Exception as e:
            self.logger.error(f"IBKR historical bars failed: {e}")
            return None

    def calculate_daily_range(self, start_hour: int,
                               end_hour: int) -> Optional[RangeInfo]:
        """Calculate range using best available method.
        Tries IBKR historical bars first, falls back to tick buffer."""
        # Primary: IBKR historical bars (works even if process started late)
        rng = self.calculate_range_from_ibkr_bars(start_hour, end_hour)
        if rng:
            return rng

        # Fallback: tick buffer (only if process was running full window)
        self.logger.info("Falling back to tick buffer for range calculation")
        return self.calculate_range_from_ticks(start_hour, end_hour)

    # ── Per-minute tick counts (for velocity CSV logging) ────────────

    def get_tick_counts_per_minute(self, num_minutes: int = 5) -> list:
        """Return list of tick counts per minute for the last N minutes."""
        now = datetime.now(timezone.utc)
        counts = []
        for i in range(num_minutes, 0, -1):
            start = now - timedelta(minutes=i)
            end = now - timedelta(minutes=i - 1)
            count = sum(1 for t in self.tick_buffer
                        if start <= t.timestamp < end)
            counts.append(count)
        return counts

    # ── Cleanup ──────────────────────────────────────────────────────

    def disconnect(self):
        """Unsubscribe from market data."""
        self.logger.info("Disconnecting LiveMarketContext")
        try:
            self.ib.pendingTickersEvent -= self._on_ticker_update
        except Exception:
            pass
        if self.ticker:
            try:
                self.ib.cancelMktData(self.contract)
            except Exception:
                pass
