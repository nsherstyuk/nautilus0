"""Runtime patch to override NautilusTrader IB connection mixin."""

from __future__ import annotations

import importlib


def apply_ib_connection_patch() -> None:
    """Monkey-patch Nautilus IB connection methods with our shielded versions.

    This works regardless of import order by importing the original module and
    replacing specific methods on the class.
    """
    # Import original and patched modules
    orig_mod = importlib.import_module(
        "nautilus_trader.adapters.interactive_brokers.client.connection"
    )
    patched_mod = importlib.import_module(
        "patches.nautilus_trader.adapters.interactive_brokers.client.connection"
    )

    # Replace critical methods to avoid premature cancellation
    orig_cls = orig_mod.InteractiveBrokersClientConnectionMixin
    patched_cls = patched_mod.InteractiveBrokersClientConnectionMixin

    orig_cls._connect = patched_cls._connect
    orig_cls._connect_socket = patched_cls._connect_socket
    orig_cls._send_version_info = patched_cls._send_version_info
    orig_cls._receive_server_info = patched_cls._receive_server_info
