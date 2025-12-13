"""
Simple IBKR connection test using raw socket.
This bypasses NautilusTrader to test if TWS API is actually responding.
"""
import socket
import struct
import time

def test_raw_connection(host='127.0.0.1', port=7497, client_id=999):
    """Test raw socket connection to TWS/Gateway."""
    print(f"Testing connection to {host}:{port} with client_id={client_id}")
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        
        # Connect
        print(f"  [1/4] Connecting to {host}:{port}...")
        sock.connect((host, port))
        print(f"  ✓ Socket connected")
        
        # Send API version (TWS expects this first)
        print(f"  [2/4] Sending API version...")
        version_prefix = "API\0"
        min_version = "v100..176"  # Typical range for IB API v176
        
        # Format: "API\0" + "v{min}..{max}\0"
        msg = f"{version_prefix}{min_version}\0".encode('utf-8')
        sock.sendall(msg)
        print(f"  ✓ Sent version info: {msg}")
        
        # Receive server version
        print(f"  [3/4] Waiting for server version...")
        response = sock.recv(4096)
        
        if response:
            print(f"  ✓ Received {len(response)} bytes from TWS:")
            print(f"    Raw: {response[:100]}")
            print(f"    Decoded: {response.decode('utf-8', errors='replace')[:200]}")
            print("\n✅ SUCCESS: TWS API is responding!")
            return True
        else:
            print(f"  ✗ No response from TWS")
            print("\n❌ FAILURE: TWS not responding to version handshake")
            return False
            
    except socket.timeout:
        print(f"  ✗ Connection timeout after 10 seconds")
        print("\n❌ FAILURE: TWS not responding (timeout)")
        return False
        
    except ConnectionRefusedError:
        print(f"  ✗ Connection refused")
        print("\n❌ FAILURE: Nothing listening on port {port}")
        print("   → Check if TWS/Gateway is running")
        print("   → Verify port number in TWS API settings")
        return False
        
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        print(f"\n❌ FAILURE: {e}")
        return False
        
    finally:
        try:
            sock.close()
        except:
            pass

def check_port_listening(host='127.0.0.1', port=7497):
    """Quick check if port is listening."""
    print(f"\nChecking if port {port} is listening...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"  ✓ Port {port} is open and listening")
            return True
        else:
            print(f"  ✗ Port {port} is not accessible (error code: {result})")
            return False
    except Exception as e:
        print(f"  ✗ Error checking port: {e}")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("INTERACTIVE BROKERS TWS/GATEWAY CONNECTION TEST")
    print("=" * 70)
    
    # Test different client IDs to check for conflicts
    test_configs = [
        (7497, 999),   # Paper trading port, unique ID
        (7497, 17),    # Paper trading port, your current data client ID
        (7497, 18),    # Paper trading port, your current exec client ID
        (7496, 999),   # Live trading port (in case you're using this)
    ]
    
    for port, client_id in test_configs:
        print(f"\n{'=' * 70}")
        print(f"TEST: Port {port}, Client ID {client_id}")
        print(f"{'=' * 70}")
        
        # First check if port is listening
        if not check_port_listening(port=port):
            print(f"  → Skipping detailed test (port not listening)")
            continue
        
        # Try raw connection
        time.sleep(1)  # Brief delay between tests
        success = test_raw_connection(port=port, client_id=client_id)
        
        if success:
            print(f"\n✅ DIAGNOSIS: TWS API is working on port {port}!")
            print("   → The issue is in NautilusTrader's connection logic")
            print("   → NOT a TWS configuration problem")
            break
    else:
        print("\n" + "=" * 70)
        print("❌ FINAL DIAGNOSIS: TWS API is NOT responding on any port")
        print("=" * 70)
        print("\nPossible causes:")
        print("  1. TWS 'Enable ActiveX and Socket Clients' is NOT enabled")
        print("  2. TWS needs to be restarted after enabling API")
        print("  3. Wrong TWS mode (need Paper Trading for port 7497)")
        print("  4. Firewall blocking localhost connections")
        print("\nRequired TWS settings:")
        print("  File → Global Configuration → API → Settings")
        print("  ☑ Enable ActiveX and Socket Clients")
        print("  ☐ Read-Only API (should be UNCHECKED)")
        print("  Socket port: 7497 (for paper trading)")
        print("\n  Then RESTART TWS for changes to take effect!")
