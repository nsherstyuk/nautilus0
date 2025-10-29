"""Minimal IBKR connectivity smoke test.

This script attempts a simple IB API connection using the same environment
variables consumed by the live trading runner. It verifies the handshake by
waiting for `nextValidId` and `managedAccounts` callbacks. Any connection
errors are printed to stdout.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from typing import Optional

from dotenv import load_dotenv
from ibapi.client import EClient
from ibapi.wrapper import EWrapper


class _ConnectionError(Exception):
    """Raised when a connection could not be established."""


class TestApp(EWrapper, EClient):
    """Thin IB API client used to verify connectivity."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._next_valid_id_event = threading.Event()
        self._managed_accounts_event = threading.Event()
        self._last_error: Optional[str] = None

    # --- EWrapper overrides -------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802 (ibapi naming)
        print(f"[INFO] nextValidId received: {orderId}")
        self._next_valid_id_event.set()
        super().nextValidId(orderId)

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        print(f"[INFO] managedAccounts: {accountsList}")
        self._managed_accounts_event.set()
        super().managedAccounts(accountsList)

    def connectionClosed(self) -> None:
        print("[WARN] connectionClosed callback invoked")
        super().connectionClosed()

    def error(  # noqa: D401,N802
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        formatted = f"code={errorCode} reqId={reqId} message={errorString}"
        if advancedOrderRejectJson:
            formatted += f" details={advancedOrderRejectJson}"
        print(f"[ERROR] {formatted}")
        self._last_error = formatted
        if errorCode in {502, 504}:
            # Signal waiting threads so the test can exit quickly on socket issues.
            self._next_valid_id_event.set()
            self._managed_accounts_event.set()
        super().error(reqId, errorCode, errorString, advancedOrderRejectJson)

    # --- Public API ---------------------------------------------------------
    def run_async(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="ibapi-thread", daemon=True)
        thread.start()
        return thread

    def await_connection(self, timeout: float = 20.0, poll_interval: float = 1.0) -> None:
        """Wait for the IB API handshake to complete or raise on failure."""
        waited = 0.0
        while waited < timeout:
            if self._next_valid_id_event.is_set():
                break
            time.sleep(poll_interval)
            waited += poll_interval
            print(f"[DEBUG] Waiting for nextValidId... {waited:.0f}s elapsed")

        if not self._next_valid_id_event.is_set():
            raise _ConnectionError(
                "Timed out waiting for nextValidId. See IB API logs for details."
            )

        # `managedAccounts` is optional for market data only connections, so we
        # wait but do not fail the test if it never arrives. Still provide progress feedback.
        waited = 0.0
        while waited < timeout and not self._managed_accounts_event.is_set():
            time.sleep(poll_interval)
            waited += poll_interval
            print(f"[DEBUG] Waiting for managedAccounts... {waited:.0f}s elapsed")

    def get_last_error(self) -> Optional[str]:
        return self._last_error


def load_ib_env() -> tuple[str, int, int]:
    load_dotenv()
    host = os.getenv("IB_HOST")
    port = os.getenv("IB_PORT")
    client_id = os.getenv("IB_CLIENT_ID")

    missing = [
        name
        for name, value in [
            ("IB_HOST", host),
            ("IB_PORT", port),
            ("IB_CLIENT_ID", client_id),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
    try:
        port_int = int(port)
        client_id_int = int(client_id)
    except ValueError as exc:  # pragma: no cover - defensive
        raise RuntimeError("IB_PORT and IB_CLIENT_ID must be integers") from exc

    return host, port_int, client_id_int


def check_socket(host: str, port: int, timeout: float = 3.0) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            print(f"[INFO] TCP socket to {host}:{port} opened successfully.")
    except ConnectionRefusedError as exc:
        raise _ConnectionError(
            f"Socket connection refused at {host}:{port}. Confirm TWS/Gateway is running "
            "and listening on this port."
        ) from exc
    except TimeoutError as exc:
        raise _ConnectionError(
            f"Socket connection to {host}:{port} timed out after {timeout}s."
        ) from exc
    except OSError as exc:
        raise _ConnectionError(
            f"Failed to open TCP socket to {host}:{port}: {exc}"
        ) from exc


def main() -> int:
    try:
        host, port, client_id = load_ib_env()
    except Exception as exc:
        print(f"[FATAL] {exc}")
        return 1

    print(f"[INFO] Attempting IB API connection to {host}:{port} (client_id={client_id})")

    try:
        check_socket(host, port)
    except _ConnectionError as exc:
        print(f"[FATAL] {exc}")
        return 1

    app = TestApp(host=host, port=port, client_id=client_id)

    try:
        app.connect(host, port, client_id)
    except socket.error as exc:
        print(f"[FATAL] Failed to open socket: {exc}")
        return 1

    ib_thread = app.run_async()
    try:
        app.await_connection(timeout=20.0)
    except _ConnectionError as exc:
        print(f"[FATAL] {exc}")
        last_error = app.get_last_error()
        if last_error:
            print(f"[DETAIL] Last IB API error: {last_error}")
        return 1
    finally:
        # Give callbacks a moment to flush before disconnecting.
        time.sleep(2)
        app.disconnect()
        if ib_thread.is_alive():
            ib_thread.join(timeout=5)

    last_error = app.get_last_error()
    if last_error:
        print(f"[WARN] Connection succeeded but IB reported an error: {last_error}")
    print("[SUCCESS] IB API handshake completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
