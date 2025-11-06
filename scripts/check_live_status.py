"""
Check status of live trading script and IBKR connection.
"""
import sys
from pathlib import Path
import subprocess
import socket
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

def check_port(host: str, port: int) -> bool:
    """Check if IBKR port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def check_live_process() -> dict:
    """Check if live trading process is running."""
    try:
        # Try to find Python processes that might be running live trading
        result = subprocess.run(
            ["powershell", "-Command", 
             "Get-Process python -ErrorAction SilentlyContinue | "
             "Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize"],
            capture_output=True,
            text=True,
            timeout=5
        )
        processes = result.stdout
        return {"running": "python" in processes.lower(), "details": processes}
    except:
        return {"running": False, "details": "Could not check processes"}

def check_live_logs(log_dir: Path) -> dict:
    """Check recent live trading logs for connection status."""
    log_file = log_dir / "live_trading.log"
    if not log_file.exists():
        return {"exists": False, "status": "No log file found"}
    
    try:
        # Read last 100 lines
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent_lines = lines[-100:] if len(lines) > 100 else lines
        
        # Look for connection status
        connection_info = {
            "connected": False,
            "last_message": recent_lines[-1].strip() if recent_lines else "",
            "connection_logs": []
        }
        
        for line in recent_lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ["connected", "connection", "ibkr", "interactive brokers"]):
                connection_info["connection_logs"].append(line.strip())
                if "connected" in line_lower and "error" not in line_lower:
                    connection_info["connected"] = True
        
        return {"exists": True, "status": connection_info}
    except Exception as e:
        return {"exists": True, "status": f"Error reading log: {e}"}

def main():
    print("=" * 80)
    print("LIVE TRADING STATUS CHECK")
    print("=" * 80)
    print()
    
    # Check IBKR port
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "7497"))
    port_open = check_port(host, port)
    
    print(f"1. IBKR TWS/Gateway Port ({host}:{port}):")
    if port_open:
        print(f"   [OK] Port is OPEN - TWS/Gateway is running")
    else:
        print(f"   [FAIL] Port is CLOSED - TWS/Gateway may not be running")
    print()
    
    # Check Python processes
    print("2. Python Processes:")
    process_info = check_live_process()
    if process_info["running"]:
        print(f"   [OK] Python processes found:")
        print(process_info["details"])
    else:
        print(f"   [!] No Python processes found or couldn't check")
    print()
    
    # Check logs
    log_dir = Path("logs/live")
    print(f"3. Live Trading Logs ({log_dir}):")
    log_info = check_live_logs(log_dir)
    if log_info["exists"]:
        status = log_info["status"]
        if isinstance(status, dict):
            print(f"   [OK] Log file exists")
            print(f"   Last message: {status['last_message'][:100]}")
            if status["connection_logs"]:
                print(f"   Connection-related logs (last 5):")
                for log in status["connection_logs"][-5:]:
                    print(f"     - {log[:80]}")
            if status["connected"]:
                print(f"   [OK] Connection logs show 'Connected' status")
            else:
                print(f"   [!] No 'Connected' status found in recent logs")
        else:
            print(f"   [!] {status}")
    else:
        print(f"   [FAIL] No log file found - script may not be running")
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_ok = port_open and log_info["exists"]
    
    if all_ok:
        print("[OK] TWS/Gateway appears to be running and accessible")
        print("[OK] Live trading logs are being written")
        if isinstance(log_info["status"], dict) and log_info["status"].get("connected"):
            print("[OK] Connection status: CONNECTED (based on logs)")
        else:
            print("[!] Connection status: UNKNOWN (check logs for connection messages)")
    else:
        if not port_open:
            print("[FAIL] TWS/Gateway port is not accessible")
            print("       → Start TWS or IB Gateway")
        if not log_info["exists"]:
            print("[FAIL] Live trading script may not be running")
            print("       → Start with: python live/run_live.py")
    
    print()
    print("To see live logs in real-time:")
    print("  Get-Content logs\\live\\live_trading.log -Tail 50 -Wait")
    print()
    print("To check detailed connection status:")
    print("  Get-Content logs\\live\\live_trading.log | Select-String -Pattern 'Connected|IBKR' | Select-Object -Last 10")

if __name__ == "__main__":
    main()

