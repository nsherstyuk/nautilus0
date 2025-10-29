"""Diagnostic test for IB API handshake with detailed logging."""
import socket
import struct
import sys
import os
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

host = os.getenv("IB_HOST", "127.0.0.1")
port = int(os.getenv("IB_PORT", "7497"))
client_id = int(os.getenv("IB_CLIENT_ID", "10"))

print(f"IB API Handshake Test")
print(f"=" * 60)
print(f"Host: {host}")
print(f"Port: {port}")
print(f"Client ID: {client_id}")
print(f"=" * 60)

try:
    # Step 1: Create socket
    print("\n[1/5] Creating socket...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    print("      ✓ Socket created")
    
    # Step 2: Connect
    print(f"\n[2/5] Connecting to {host}:{port}...")
    sock.connect((host, port))
    print("      ✓ TCP connection established")
    
    # Step 3: Send API version handshake
    # IB API expects: "API\0" + "v<MIN_VER>..<MAX_VER>"
    # Using IB API v100+ protocol
    print(f"\n[3/5] Sending API version handshake...")
    api_prefix = b"API\0"
    # Standard IB API version range (compatible with most versions)
    version_msg = "v100..176"
    
    # Build message in IB format: 4-byte length prefix + message
    msg_bytes = version_msg.encode('utf-8')
    msg_length = struct.pack('>I', len(msg_bytes))
    full_msg = api_prefix + msg_length + msg_bytes
    
    print(f"      Sending: {api_prefix!r} + length={len(msg_bytes)} + {version_msg!r}")
    sock.sendall(full_msg)
    print("      ✓ Version handshake sent")
    
    # Step 4: Wait for server response
    print(f"\n[4/5] Waiting for server version response...")
    print("      (TWS should respond with its version and connection time)")
    
    # Read response - should get server version
    sock.settimeout(5)
    try:
        # Read 4-byte length prefix
        length_data = sock.recv(4)
        if not length_data:
            print("      ✗ Server closed connection immediately after handshake")
            print("\n" + "=" * 60)
            print("DIAGNOSIS: TWS rejected the connection")
            print("=" * 60)
            print("\nMost likely causes:")
            print("  1. API access is NOT enabled in TWS")
            print("     → File → Global Configuration → API → Settings")
            print("     → Check 'Enable ActiveX and Socket Clients'")
            print("\n  2. 127.0.0.1 is not in Trusted IPs")
            print("     → Add 127.0.0.1 to the trusted IPs list")
            print("\n  3. 'Read-Only API' is enabled (blocks connections)")
            print("     → Uncheck 'Read-Only API' if present")
            sys.exit(1)
            
        msg_length = struct.unpack('>I', length_data)[0]
        print(f"      Received response length: {msg_length} bytes")
        
        # Read the actual message
        response = sock.recv(msg_length)
        print(f"      Received data: {response!r}")
        
        # Parse response (should be fields separated by null bytes)
        fields = response.decode('utf-8').split('\0')
        print(f"      Parsed fields: {fields}")
        
        if len(fields) >= 2:
            server_version = fields[0]
            conn_time = fields[1]
            print(f"\n      ✓ Server version: {server_version}")
            print(f"      ✓ Connection time: {conn_time}")
            print(f"\n[5/5] Handshake SUCCESS!")
            print("\n" + "=" * 60)
            print("✓ IB API handshake completed successfully!")
            print("=" * 60)
            print("\nTWS is responding correctly to API requests.")
            print("The connection issue must be in the NautilusTrader adapter.")
            print("\nNext steps:")
            print("  1. Check if client IDs 10 and 11 are already in use")
            print("  2. Review TWS API logs for additional errors")
            print("  3. Try using a different client ID in .env")
        else:
            print(f"      ✗ Unexpected response format: {fields}")
            
    except socket.timeout:
        print("      ✗ TIMEOUT waiting for server response")
        print("\n" + "=" * 60)
        print("DIAGNOSIS: TWS not responding to API handshake")
        print("=" * 60)
        print("\nThis indicates:")
        print("  → TWS is listening but not responding to API requests")
        print("  → API may be disabled or misconfigured")
        print("\nAction required:")
        print("  1. Open TWS")
        print("  2. Go to: File → Global Configuration → API → Settings")
        print("  3. Ensure 'Enable ActiveX and Socket Clients' is CHECKED")
        print("  4. Click 'OK' and restart TWS")
        sys.exit(1)
        
except ConnectionRefusedError:
    print(f"      ✗ Connection refused at {host}:{port}")
    print("\nTWS/Gateway is not running or not listening on this port")
    sys.exit(1)
    
except Exception as e:
    print(f"\n      ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
    
finally:
    try:
        sock.close()
    except:
        pass
