"""Test using actual ibapi.client.EClient (mimics NautilusTrader approach)."""
import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from ibapi.client import EClient
from ibapi.wrapper import EWrapper


class TestWrapper(EWrapper):
    def __init__(self):
        super().__init__()
        self.connected = False
        self.next_valid_id = None
        self.managed_accounts = None
        self.errors = []
        
    def connectAck(self):
        print(f"[CALLBACK] connectAck()")
        super().connectAck()
        
    def nextValidId(self, orderId: int):
        print(f"[CALLBACK] nextValidId({orderId})")
        self.next_valid_id = orderId
        self.connected = True
        
    def managedAccounts(self, accountsList: str):
        print(f"[CALLBACK] managedAccounts({accountsList})")
        self.managed_accounts = accountsList
        
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        msg = f"[ERROR] reqId={reqId} code={errorCode} msg={errorString}"
        print(msg)
        self.errors.append((errorCode, errorString))
        
    def connectionClosed(self):
        print(f"[CALLBACK] connectionClosed()")
        self.connected = False


class TestApp(TestWrapper, EClient):
    def __init__(self):
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._thread = None
        
    def run_thread(self):
        """Run message loop in background thread."""
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        
    def wait_for_connection(self, timeout=15):
        """Wait for connection to be established."""
        start = time.time()
        while time.time() - start < timeout:
            if self.connected and self.next_valid_id is not None:
                return True
            time.sleep(0.5)
        return False


def main():
    load_dotenv()
    
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "7497"))
    client_id = int(os.getenv("IB_CLIENT_ID", "10"))
    
    print("=" * 70)
    print("Testing ibapi.client.EClient (NautilusTrader uses this)")
    print("=" * 70)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Client ID: {client_id}")
    print("=" * 70)
    
    app = TestApp()
    
    print(f"\n[1/4] Connecting to TWS...")
    try:
        app.connect(host, port, client_id)
        print(f"      ✓ connect() called successfully")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        return 1
        
    print(f"\n[2/4] Starting message processing thread...")
    app.run_thread()
    print(f"      ✓ Thread started")
    
    print(f"\n[3/4] Waiting for connection handshake (15s timeout)...")
    print(f"      Expecting callbacks: nextValidId, managedAccounts")
    
    success = app.wait_for_connection(timeout=15)
    
    print(f"\n[4/4] Results:")
    print(f"      Connected: {app.connected}")
    print(f"      Next Valid ID: {app.next_valid_id}")
    print(f"      Managed Accounts: {app.managed_accounts}")
    print(f"      Errors: {len(app.errors)}")
    
    if app.errors:
        print(f"\n      Error details:")
        for code, msg in app.errors:
            print(f"        [{code}] {msg}")
    
    time.sleep(2)  # Let any pending messages arrive
    app.disconnect()
    
    print("\n" + "=" * 70)
    if success and app.next_valid_id is not None:
        print("✓ SUCCESS - ibapi.client.EClient works correctly!")
        print("=" * 70)
        print("\nIf this works but NautilusTrader doesn't, the issue is in")
        print("NautilusTrader's adapter wrapper, not TWS or ibapi.")
        print("\nTry running live trading with client_id=1 instead of 10:")
        print("  Set in .env: IB_CLIENT_ID=1")
        return 0
    else:
        print("✗ FAILED - ibapi.client.EClient could not connect")
        print("=" * 70)
        if app.errors:
            for code, msg in app.errors:
                if code in [502, 504]:
                    print("\nError 502/504 indicates TWS rejected the connection.")
                    print("Check TWS API settings again.")
        else:
            print("\nNo error callbacks received - connection timed out.")
            print("This suggests TWS is not responding to API messages.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
