"""Quick port connectivity check for IB TWS/Gateway."""
import socket
import sys
from dotenv import load_dotenv
import os

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

host = os.getenv("IB_HOST", "127.0.0.1")
port = int(os.getenv("IB_PORT", "7497"))

print(f"Checking if {host}:{port} is reachable...")
print(f"(This is the port configured for IB API connections)")
print("-" * 60)

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    result = sock.connect_ex((host, port))
    sock.close()
    
    if result == 0:
        print(f"✓ Port {port} is OPEN and accepting connections")
        print(f"\nThis means TWS/Gateway is running and listening.")
        print(f"If IB API still fails, check:")
        print(f"  1. TWS: File → Global Configuration → API → Settings")
        print(f"     - 'Enable ActiveX and Socket Clients' must be checked")
        print(f"     - 'Socket Port' should show {port}")
        print(f"     - 'Trusted IPs' should include 127.0.0.1")
        print(f"  2. Ensure no other application is using client ID 10 or 11")
        sys.exit(0)
    else:
        print(f"✗ Port {port} is CLOSED (connection refused)")
        print(f"\nPossible causes:")
        print(f"  1. TWS or IB Gateway is NOT running")
        print(f"  2. TWS is running but using a different port")
        print(f"  3. TWS API is disabled")
        print(f"\nAction required:")
        print(f"  → Launch TWS or IB Gateway")
        print(f"  → In TWS: File → Global Configuration → API → Settings")
        print(f"  → Verify 'Socket Port' is {port}")
        print(f"  → Check 'Enable ActiveX and Socket Clients'")
        sys.exit(1)
        
except socket.timeout:
    print(f"✗ Connection to {host}:{port} TIMED OUT")
    print(f"\nThis usually means:")
    print(f"  - A firewall is blocking the connection")
    print(f"  - The host {host} is unreachable")
    sys.exit(1)
    
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    sys.exit(1)
