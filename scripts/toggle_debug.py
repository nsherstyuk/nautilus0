#!/usr/bin/env python3
"""
Quick toggle for DEBUG logging in live runner.

Usage:
    python scripts/toggle_debug.py on   # Enable DEBUG console logging
    python scripts/toggle_debug.py off  # Disable DEBUG (back to INFO)
"""

import sys
from pathlib import Path

# Path to the live runner
RUNNER_FILE = Path(__file__).parent.parent / "live" / "run_live_mtf_v2_entry_confirmed_v2.py"

def toggle_debug(enable: bool):
    """Toggle debug logging in the live runner."""
    if not RUNNER_FILE.exists():
        print(f"ERROR: Runner file not found at {RUNNER_FILE}")
        return False
    
    # Read the file
    content = RUNNER_FILE.read_text()
    
    # Find and replace the log_level line
    old_line = '            log_level="INFO",  # Console: INFO level to reduce IBKR protocol noise'
    if enable:
        new_line = '            log_level="DEBUG",  # Console: DEBUG level to see warmup and signal details'
        print("Enabling DEBUG console logging...")
    else:
        new_line = '            log_level="INFO",  # Console: INFO level to reduce IBKR protocol noise'
        print("Disabling DEBUG console logging (back to INFO)...")
    
    if old_line not in content:
        print("ERROR: Could not find the log_level line to replace")
        return False
    
    # Replace the line
    updated_content = content.replace(old_line, new_line)
    RUNNER_FILE.write_text(updated_content)
    
    print(f"Updated {RUNNER_FILE.name}")
    if enable:
        print("Now restart the live runner to see DEBUG messages in console.")
        print("Use 'python scripts/toggle_debug.py off' to disable when done.")
    else:
        print("Now restart the live runner for cleaner console output.")
    
    return True

def main():
    if len(sys.argv) != 2:
        print("Usage: python toggle_debug.py [on|off]")
        sys.exit(1)
    
    arg = sys.argv[1].lower()
    if arg == "on":
        toggle_debug(True)
    elif arg == "off":
        toggle_debug(False)
    else:
        print("ERROR: Invalid argument. Use 'on' or 'off'")
        sys.exit(1)

if __name__ == "__main__":
    main()
