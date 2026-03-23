"""
SharedConnection - IBKR connection wrapper with reconnection and heartbeat.

Handles: connect, reconnect with exponential backoff, heartbeat detection,
contract qualification, and sleep proxy.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ib_insync import IB, Contract


class SharedConnection:
    """
    Deep module: Hides connection lifecycle, reconnection logic,
    and heartbeat management from all consumers.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4002,
                 client_id: int = 60, max_retries: int = 10,
                 base_backoff_sec: int = 5, max_backoff_sec: int = 300,
                 heartbeat_interval_sec: int = 30,
                 connect_timeout_sec: int = 20,
                 logger: Optional[logging.Logger] = None):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.connect_timeout_sec = connect_timeout_sec
        self.logger = logger or logging.getLogger(__name__)

        self.ib = IB()
        self.contract: Optional[Contract] = None
        self._last_heartbeat: float = 0.0
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self.ib.isConnected()

    def connect(self) -> bool:
        """Connect to IBKR with retries and exponential backoff."""
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(
                    f"Connecting to IBKR {self.host}:{self.port} "
                    f"(clientId={self.client_id}, attempt {attempt})")
                self.ib.connect(
                    self.host, self.port, clientId=self.client_id,
                    timeout=self.connect_timeout_sec, readonly=False)
                self._connected = True
                self._last_heartbeat = time.time()
                self.logger.info("IBKR connected")
                return True
            except Exception as e:
                backoff = min(
                    self.base_backoff_sec * (2 ** (attempt - 1)),
                    self.max_backoff_sec)
                self.logger.warning(
                    f"Connection attempt {attempt} failed: {e} "
                    f"(retry in {backoff}s)")
                time.sleep(backoff)

        self.logger.error(
            f"Failed to connect after {self.max_retries} attempts")
        return False

    def ensure_connected(self) -> bool:
        """Check connection and reconnect if needed."""
        if self.ib.isConnected():
            self._connected = True
            return True

        self.logger.warning("Connection lost — attempting reconnect")
        self._connected = False
        try:
            self.ib.disconnect()
        except Exception:
            pass
        return self.connect()

    def heartbeat(self) -> bool:
        """Periodic heartbeat check. Call from main loop.
        Returns True if connection is alive."""
        now = time.time()
        if now - self._last_heartbeat < self.heartbeat_interval_sec:
            return self.connected

        self._last_heartbeat = now
        if not self.ib.isConnected():
            self.logger.warning("Heartbeat: connection dead")
            return self.ensure_connected()

        # Lightweight keep-alive: pump events
        try:
            self.ib.sleep(0)
        except Exception as e:
            self.logger.warning(f"Heartbeat pump failed: {e}")
            return self.ensure_connected()
        return True

    def qualify_contract(self, symbol: str, sec_type: str = "CMDTY",
                         exchange: str = "SMART",
                         currency: str = "USD") -> Optional[Contract]:
        """Qualify and cache a contract."""
        contract = Contract(
            symbol=symbol, secType=sec_type,
            exchange=exchange, currency=currency)
        try:
            qualified = self.ib.qualifyContracts(contract)
            if qualified:
                self.contract = qualified[0]
                self.logger.info(
                    f"Contract qualified: {self.contract.symbol} "
                    f"conId={self.contract.conId}")
                return self.contract
            else:
                self.logger.error(f"Contract not qualified: {symbol}")
                return None
        except Exception as e:
            self.logger.error(f"Contract qualification failed: {e}")
            return None

    def sleep(self, seconds: float):
        """Proxy for ib.sleep — pumps IB events."""
        self.ib.sleep(seconds)

    def disconnect(self):
        """Clean disconnect."""
        try:
            if self.ib.isConnected():
                self.ib.disconnect()
                self.logger.info("IBKR disconnected")
        except Exception as e:
            self.logger.warning(f"Disconnect error: {e}")
        self._connected = False
