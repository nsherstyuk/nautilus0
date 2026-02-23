"""
Adapter to connect NautilusTrader live data stream to the v4 ML pipeline.
"""
# Pseudocode: Replace with actual NautilusTrader imports and usage
# from nautilus_trader.live.data_client import DataClient
# from nautilus_trader.data.aggregation import BarAggregator


# NOTE: This implementation assumes the presence of NautilusTrader's Python API.
# Replace the below imports with actual NautilusTrader modules in your environment.
import threading
import time

class NautilusDataAdapter:
    """
    Adapter to stream live bars from NautilusTrader to the ML pipeline.
    Handles subscription, reconnection, and bar conversion.
    """
    def __init__(self, symbol, venue, bar_size, dedup_window=100):
        self.symbol = symbol
        self.venue = venue
        self.bar_size = bar_size
        self._running = False
        self._dedup_cache = []  # List of (timestamp, symbol)
        self._dedup_window = dedup_window
        # self.client = DataClient(...)
        # self.aggregator = BarAggregator(...)

    def subscribe(self, on_bar_callback):
        """
        Subscribe to live bars and call on_bar_callback(bar_dict) for each new bar.
        This method starts a background thread for streaming.
        Deduplicates bars by (timestamp, symbol).
        """
        self._running = True
        def stream_loop():
            while self._running:
                try:
                    # Replace this with actual NautilusTrader streaming logic
                    # for bar in self.client.stream_bars(self.symbol, self.venue, self.bar_size):
                    #     bar_dict = self._convert_bar(bar)
                    #     if not self._is_duplicate(bar_dict):
                    #         on_bar_callback(bar_dict)
                    #     if not self._running:
                    #         break
                    # --- MOCKUP: Emit a fake bar every 5 seconds ---
                    bar = {
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'symbol': self.symbol,
                        'open': 1.1000,
                        'high': 1.1010,
                        'low': 1.0990,
                        'close': 1.1005,
                        'volume': 1000,
                    }
                    if not self._is_duplicate(bar):
                        on_bar_callback(bar)
                    time.sleep(5)
                except Exception as e:
                    print(f"[NautilusDataAdapter] Streaming error: {e}. Retrying in 10s...")
                    time.sleep(10)
        t = threading.Thread(target=stream_loop, daemon=True)
        t.start()

    def _is_duplicate(self, bar):
        key = (bar.get('timestamp'), bar.get('symbol'))
        if key in self._dedup_cache:
            return True
        self._dedup_cache.append(key)
        if len(self._dedup_cache) > self._dedup_window:
            self._dedup_cache.pop(0)
        return False

    def stop(self):
        """Stop the live data stream."""
        self._running = False

    def _convert_bar(self, bar):
        """
        Convert NautilusTrader bar object to dict for ML pipeline.
        """
        # Example for real bar object:
        # return {
        #     'timestamp': bar.timestamp.isoformat(),
        #     'symbol': bar.symbol,
        #     'open': bar.open,
        #     'high': bar.high,
        #     'low': bar.low,
        #     'close': bar.close,
        #     'volume': bar.volume,
        # }
        return bar
