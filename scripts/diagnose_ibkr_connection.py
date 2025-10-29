import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import datetime

sys.stdout.reconfigure(encoding='utf-8')

# Color constants for terminal output (ANSI escape codes)
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
GRAY = '\033[90m'
RESET = '\033[0m'

if not sys.stdout.isatty():
    GREEN = RED = YELLOW = CYAN = GRAY = RESET = ''

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DIAG_TIMEOUT_SECS = int(os.getenv("DIAG_TIMEOUT_SECS", "60"))

CHECK_PORT_SCRIPT = PROJECT_ROOT / "scripts" / "check_port.py"
HANDSHAKE_SCRIPT = PROJECT_ROOT / "scripts" / "test_ib_handshake.py"
IBAPI_CLIENT_SCRIPT = PROJECT_ROOT / "scripts" / "test_ibapi_client.py"

def check_env_variables():
    print(f"\n[1/5] {CYAN}Checking .env configuration...{RESET}")
    print("-" * 70)
    
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        print(f"{RED}✗ .env file not found in project root{RESET}")
        print(f"   Please create .env from .env.example or .env.phase6")
        return False, {}, ["Missing .env file"]
    
    load_dotenv(dotenv_path=env_file)
    
    required_vars = ["IB_HOST", "IB_PORT", "IB_CLIENT_ID"]
    optional_vars = ["IB_ACCOUNT_ID", "IB_MARKET_DATA_TYPE"]
    
    variables = {}
    issues = []
    
    for var in required_vars + optional_vars:
        value = os.getenv(var)
        variables[var] = value
        if var in required_vars and value is None:
            issues.append(f"Missing required variable: {var}")
    
    # Validate formats
    if variables.get("IB_PORT") is not None:
        try:
            port = int(variables["IB_PORT"])
            if not (1024 <= port <= 65535):
                issues.append(f"IB_PORT {variables['IB_PORT']} out of valid range (1024-65535)")
        except ValueError:
            issues.append(f"IB_PORT {variables['IB_PORT']} is not a valid integer")
    
    if variables.get("IB_CLIENT_ID") is not None:
        try:
            client_id = int(variables["IB_CLIENT_ID"])
            if client_id < 1:
                issues.append(f"IB_CLIENT_ID {variables['IB_CLIENT_ID']} must be a positive integer >= 1")
        except ValueError:
            issues.append(f"IB_CLIENT_ID {variables['IB_CLIENT_ID']} is not a valid integer")
    
    if not issues:
        print(f"{GREEN}✓ All required IBKR variables found and valid{RESET}")
        for var in required_vars:
            print(f"  - {var}={variables[var]}")
        for var in optional_vars:
            value = variables[var]
            if var == "IB_ACCOUNT_ID" and value:
                masked = value[:2] + "..." if len(value) > 2 else value
                print(f"  - {var}={masked}")
            else:
                print(f"  - {var}={value or 'Not set'}")
    else:
        print(f"{RED}✗ Issues with environment variables:{RESET}")
        for issue in issues:
            print(f"  - {issue}")
    
    success = len(issues) == 0
    return success, variables, issues

def run_diagnostic_script(script_path, step_number, step_name):
    print(f"\n[{step_number}/5] {CYAN}{step_name}...{RESET}")
    print("-" * 70)
    
    if not script_path.exists():
        error_msg = f"✗ Script not found: {script_path}"
        print(f"{RED}{error_msg}{RESET}")
        return False, error_msg
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=DIAG_TIMEOUT_SECS
        )
        
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"{RED}STDERR:{RESET}")
            print(result.stderr)
        
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output
        
    except subprocess.TimeoutExpired:
        error_msg = f"✗ Script timed out after {DIAG_TIMEOUT_SECS} seconds"
        print(f"{RED}{error_msg}{RESET}")
        return False, error_msg
    except Exception as e:
        error_msg = f"✗ Unexpected error running script: {str(e)}"
        print(f"{RED}{error_msg}{RESET}")
        return False, error_msg

def generate_summary_report(results):
    print("\n[5/5] Generating summary report...")
    print("=" * 70)
    print(f"{CYAN}IBKR CONNECTION DIAGNOSTIC SUMMARY{RESET}")
    print("=" * 70)
    print()
    
    print("Test Results:")
    test_names = {
        "env_check": "Environment Variables",
        "port_check": "Port Connectivity",
        "handshake_check": "IB API Handshake",
        "ibapi_check": "IBAPI Client"
    }
    
    passed_count = sum(1 for v in results.values() if v)
    failed_count = 4 - passed_count
    
    for key, success in results.items():
        symbol = f"{GREEN}✓{RESET}" if success else f"{RED}✗{RESET}"
        print(f"  [{symbol}] {test_names[key]}")
    
    print()
    
    if passed_count == 4:
        print(f"{GREEN}✓ ALL CHECKS PASSED - System ready for live trading{RESET}")
    else:
        print(f"{RED}✗ SOME CHECKS FAILED - Issues detected{RESET}")
        print(f"   Passed: {passed_count}/4, Failed: {failed_count}/4")
    
    print()
    print("=" * 70)

def provide_recommendations(results):
    print(f"\n{CYAN}Recommendations:{RESET}")
    print("-" * 70)
    
    env_failed = not results["env_check"]
    port_failed = not results["port_check"]
    handshake_failed = not results["handshake_check"]
    ibapi_failed = not results["ibapi_check"]
    
    if env_failed:
        print(f"{YELLOW}1. Fix .env configuration:{RESET}")
        print("   - Create or update .env file in project root")
        print("   - Add missing required variables:")
        print("     IB_HOST=127.0.0.1")
        print("     IB_PORT=7497  # or 4001 for live")
        print("     IB_CLIENT_ID=1  # unique positive integer")
        print("   - Optional: IB_ACCOUNT_ID=DU123456  # paper account")
        print("   - Optional: IB_MARKET_DATA_TYPE=DELAYED_FROZEN")
        print("   Then re-run this diagnostic")
        print()
    
    if port_failed:
        print(f"{YELLOW}1. Start IBKR TWS or IB Gateway:{RESET}")
        print("   - Launch TWS or IB Gateway application")
        print("   - Log into paper trading account (DU prefix)")
        print("   - Ensure it's running before proceeding")
        print()
    
    if not port_failed and handshake_failed:
        print(f"{YELLOW}1. Enable API in TWS:{RESET}")
        print("   - File → Global Configuration → API → Settings")
        print("   - Check 'Enable ActiveX and Socket Clients'")
        print("   - Verify Socket Port matches IB_PORT in .env")
        print("   - Add 127.0.0.1 to Trusted IPs")
        print("   - Click OK and restart TWS")
        print()
    
    if not handshake_failed and ibapi_failed:
        print(f"{YELLOW}1. Check client ID conflicts:{RESET}")
        print("   - Another application may be using the same client ID")
        print("   - Try changing IB_CLIENT_ID in .env to a different number")
        print("   - Common values: 1, 2, 10, 11")
        print()
    
    if all(results.values()):
        print(f"{GREEN}✓ System is ready for live trading!{RESET}")
        print()
        print("Next steps:")
        print("  1. Review your trading strategy configuration")
        print("  2. Verify .env.phase6 has optimal parameters")
        print("  3. Run: .\\live\\run_live_with_env.ps1")
        print("  4. Monitor logs for successful connection")
        print()
    
    print()
    print("-" * 70)
    print("For more help, see:")
    print("  - docs/LIVE_TRADING_SETUP_GUIDE.md")
    print("  - IB_CONNECTION_DIAGNOSIS.md")
    print("=" * 70)

def main():
    print("=" * 70)
    print(f"{CYAN}IBKR Connection Diagnostic Tool{RESET}")
    print("This script runs all diagnostic checks in sequence")
    print("=" * 70)
    print()
    
    results = {
        "env_check": False,
        "port_check": False,
        "handshake_check": False,
        "ibapi_check": False
    }
    details = {}
    
    # Step 1: Environment Variable Check
    success, variables, issues = check_env_variables()
    results["env_check"] = success
    details["env"] = {"variables": variables, "issues": issues}
    print()
    
    # Step 2: Port Connectivity Check
    port_success, port_output = run_diagnostic_script(CHECK_PORT_SCRIPT, 2, "Port Connectivity Test")
    results["port_check"] = port_success
    details["port"] = port_output
    if not port_success:
        print(f"{YELLOW}⚠ Subsequent tests may fail if TWS/Gateway is not running{RESET}")
    print()
    
    # Step 3: IB API Handshake Test
    handshake_success, handshake_output = run_diagnostic_script(HANDSHAKE_SCRIPT, 3, "IB API Handshake Test")
    results["handshake_check"] = handshake_success
    details["handshake"] = handshake_output
    print()
    
    # Step 4: IBAPI Client Test
    ibapi_success, ibapi_output = run_diagnostic_script(IBAPI_CLIENT_SCRIPT, 4, "IBAPI Client Test")
    results["ibapi_check"] = ibapi_success
    details["ibapi"] = ibapi_output
    print()
    
    # Step 5: Generate Summary and Recommendations
    generate_summary_report(results)
    provide_recommendations(results)
    
    # Save diagnostic log
    log_dir = PROJECT_ROOT / "diagnostics"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"ibkr_diagnosis_{timestamp}.txt"
    with open(log_file, 'w') as f:
        f.write("IBKR Connection Diagnostic Log\n")
        f.write("=" * 50 + "\n\n")
        for key, data in details.items():
            f.write(f"[{key.upper()}]\n")
            if key == "env":
                f.write("Variables:\n")
                for var, val in data["variables"].items():
                    if var == "IB_ACCOUNT_ID" and val:
                        masked_val = val[:2] + "..." if len(val) > 2 else val
                        f.write(f"  {var}={masked_val}\n")
                    else:
                        f.write(f"  {var}={val or 'Not set'}\n")
                f.write("Issues:\n")
                for issue in data["issues"]:
                    f.write(f"  - {issue}\n")
                if not data["issues"]:
                    f.write("  No issues\n")
            else:
                f.write(str(data) + "\n") # Convert dict to string for logging
            f.write("\n---\n")
        f.write(f"Overall Results: {dict((k, 'PASS' if v else 'FAIL') for k, v in results.items())}\n")
    
    print(f"{GREEN}✓ Diagnostic log saved to: {log_file}{RESET}")
    
    # Determine exit code
    exit_code = 0 if all(results.values()) else 1
    return exit_code

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{GRAY}User cancelled the diagnostic (Ctrl+C){RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {str(e)}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
