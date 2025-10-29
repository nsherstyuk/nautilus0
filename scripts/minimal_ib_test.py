"""
Minimal IBKR connection test - completely independent of NautilusTrader.

This script verifies that a basic IB API connection handshake can succeed
using the ibapi-python library. If this works, it proves TWS is configured
correctly and the issue is in NautilusTrader's adapter.
"""
import os
import sys
import time
import threading
from typing import Optional

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

try:
    from dotenv import load_dotenv
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
except ImportError as e:
    print(f"ERROR: Required package not installed: {e}")
    print("\nInstall with: pip install python-dotenv ibapi")
    sys.exit(1)


class MinimalIBApp(EWrapper, EClient):
    """Minimal IB API client with only essential callbacks."""
    
    def __init__(self):
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        
        self.connection_established = False
        self.next_valid_id_received = False
        self.managed_accounts = None
        self.server_version = None
        self.connection_time = None
        self.errors = []
        self.lock = threading.Lock()
        
    # ===== WRAPPER CALLBACKS =====
    
    def connectAck(self):
        """Called when TCP connection is acknowledged."""
        with self.lock:
            print("[CALLBACK] ✓ connectAck() - TCP connection acknowledged")
            super().connectAck()
    
    def nextValidId(self, orderId: int):
        """Called after successful handshake - this confirms connection is ready."""
        with self.lock:
            print(f"[CALLBACK] ✓ nextValidId({orderId}) - Connection handshake complete!")
            self.next_valid_id_received = True
            self.connection_established = True
            super().nextValidId(orderId)
    
    def managedAccounts(self, accountsList: str):
        """Called with list of managed accounts."""
        with self.lock:
            print(f"[CALLBACK] ✓ managedAccounts: {accountsList}")
            self.managed_accounts = accountsList
            super().managedAccounts(accountsList)
    
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """Called when errors occur."""
        with self.lock:
            error_msg = f"[ERROR] Code={errorCode}, ReqId={reqId}, Message={errorString}"
            print(error_msg)
            self.errors.append((errorCode, errorString))
            
            # Critical connection errors
            if errorCode in [502, 504, 1100, 1300]:
                print(f"       ⚠ CRITICAL: Connection error detected")
            
            super().error(reqId, errorCode, errorString, advancedOrderRejectJson)
    
    def connectionClosed(self):
        """Called when connection is closed."""
        with self.lock:
            print("[CALLBACK] ✗ connectionClosed() - Connection terminated")
            self.connection_established = False
            super().connectionClosed()
    
    # ===== HELPER METHODS =====
    
    def is_connected(self) -> bool:
        """Check if connection is established and ready."""
        with self.lock:
            return self.connection_established and self.next_valid_id_received
    
    def get_status(self) -> dict:
        """Get current connection status."""
        with self.lock:
            return {
                'connected': self.connection_established,
                'next_valid_id_received': self.next_valid_id_received,
                'managed_accounts': self.managed_accounts,
                'errors_count': len(self.errors),
                'errors': self.errors[-5:] if self.errors else []  # Last 5 errors
            }


def run_connection_test(host: str, port: int, client_id: int, timeout: float = 15.0) -> int:
    """
    Run a connection test to IBKR.
    
    Returns:
        0 if connection succeeds
        1 if connection fails
    """
    print("=" * 70)
    print("MINIMAL IBKR CONNECTION TEST")
    print("=" * 70)
    print(f"Host:      {host}")
    print(f"Port:      {port}")
    print(f"Client ID: {client_id}")
    print(f"Timeout:   {timeout}s")
    print("=" * 70)
    print()
    
    # Create app instance
    app = MinimalIBApp()
    
    # Step 1: Connect
    print("[1/4] Initiating connection to TWS...")
    try:
        app.connect(host, port, client_id)
        print("      ✓ connect() method called successfully")
    except Exception as e:
        print(f"      ✗ FAILED: {e}")
        return 1
    
    # Step 2: Start message processing thread
    print("\n[2/4] Starting IB API message processing thread...")
    api_thread = threading.Thread(target=app.run, name="IB-API-Thread", daemon=True)
    api_thread.start()
    print("      ✓ Thread started")
    
    # Step 3: Wait for connection
    print(f"\n[3/4] Waiting for connection handshake (max {timeout}s)...")
    print("      Expecting callbacks: connectAck() -> nextValidId() -> managedAccounts()")
    print()
    
    start_time = time.time()
    last_status_time = start_time
    
    while time.time() - start_time < timeout:
        # Check if connected
        if app.is_connected():
            elapsed = time.time() - start_time
            print(f"\n      ✓ Connection established in {elapsed:.1f}s")
            break
        
        # Print status update every 3 seconds
        if time.time() - last_status_time >= 3:
            elapsed = time.time() - start_time
            status = app.get_status()
            print(f"      [{elapsed:.0f}s] Waiting... (connected={status['connected']}, "
                  f"nextValidId={status['next_valid_id_received']})")
            last_status_time = time.time()
        
        time.sleep(0.5)
    
    # Step 4: Check final status
    print("\n[4/4] Connection test results:")
    print("-" * 70)
    
    status = app.get_status()
    
    print(f"Connected:             {status['connected']}")
    print(f"NextValidId Received:  {status['next_valid_id_received']}")
    print(f"Managed Accounts:      {status['managed_accounts'] or 'None'}")
    print(f"Errors:                {status['errors_count']}")
    
    if status['errors']:
        print("\nRecent errors:")
        for code, msg in status['errors']:
            print(f"  [{code}] {msg}")
    
    print("-" * 70)
    
    # Disconnect
    print("\nDisconnecting...")
    app.disconnect()
    
    # Give thread time to finish
    if api_thread.is_alive():
        api_thread.join(timeout=2)
    
    # Final verdict
    print("\n" + "=" * 70)
    if app.is_connected() or status['next_valid_id_received']:
        print("✓ SUCCESS - IBKR connection handshake completed!")
        print("=" * 70)
        print("\nYour TWS/Gateway configuration is correct.")
        print("The IB API is working properly.")
        print("\nIf NautilusTrader still fails, the issue is in the NautilusTrader adapter,")
        print("not in your TWS configuration or network setup.")
        return_code = 0
    else:
        print("✗ FAILED - Could not establish connection")
        print("=" * 70)
        
        if status['errors']:
            print("\nDiagnosis based on errors:")
            for code, msg in status['errors']:
                if code == 502:
                    print("  → Error 502: TWS could not establish connection")
                    print("    Check: Is TWS fully started and logged in?")
                elif code == 504:
                    print("  → Error 504: Not connected")
                    print("    Check: API settings enabled? Correct port?")
                elif code == 1100:
                    print("  → Error 1100: Connectivity lost")
        else:
            print("\nNo errors received - connection timed out silently.")
            print("\nPossible causes:")
            print("  1. TWS API is not enabled")
            print("     → File → Global Configuration → API → Settings")
            print("     → Check: 'Enable ActiveX and Socket Clients'")
            print("\n  2. Firewall blocking connection")
            print("\n  3. Wrong port number (check TWS shows 7497)")
        
        return_code = 1
    
    print("\n")
    return return_code


def main() -> int:
    """Main entry point."""
    # Load environment variables
    load_dotenv()
    
    # Get connection parameters
    host = os.getenv("IB_HOST", "127.0.0.1")
    port_str = os.getenv("IB_PORT", "7497")
    client_id_str = os.getenv("IB_CLIENT_ID", "1")
    
    try:
        port = int(port_str)
        client_id = int(client_id_str)
    except ValueError:
        print(f"ERROR: Invalid port or client_id in .env file")
        print(f"  IB_PORT={port_str}")
        print(f"  IB_CLIENT_ID={client_id_str}")
        return 1
    
    # Run test
    return run_connection_test(host, port, client_id, timeout=15.0)


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit_code = 130
    
    sys.exit(exit_code)
