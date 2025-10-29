import os
import sys
from pathlib import Path
from dotenv import load_dotenv, dotenv_values
import argparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_PHASE6_FILE = PROJECT_ROOT / ".env.phase6"
REQUIRED_VARS = ["IB_HOST", "IB_PORT", "IB_CLIENT_ID", "IB_ACCOUNT_ID", "IB_MARKET_DATA_TYPE"]

def validate_source_env():
    print("[1/4] Validating source .env file...")
    try:
        if not ENV_FILE.exists():
            print("     ✗ .env file not found")
            sys.exit(1)
        print("     ✓ Found .env file")
        
        load_dotenv(dotenv_path=str(ENV_FILE), override=True)
        
        ibkr_config = {}
        missing_vars = []
        for var in REQUIRED_VARS:
            value = os.getenv(var)
            if value is None or value.strip() == "":
                missing_vars.append(var)
            else:
                ibkr_config[var] = value
        
        if missing_vars:
            print("     ✗ Missing or empty variables:")
            for var in missing_vars:
                print(f"       - {var}")
            sys.exit(1)
        
        print("     ✓ All required IBKR variables present:")
        for var, value in ibkr_config.items():
            print(f"       - {var}={value}")
        
        return ibkr_config
    except Exception as e:
        print(f"     ✗ Error validating .env: {e}")
        sys.exit(1)

def check_target_file():
    print("[2/4] Checking target .env.phase6 file...")
    try:
        if not ENV_PHASE6_FILE.exists():
            print("     ✗ .env.phase6 file not found")
            sys.exit(1)
        
        target_vars = dotenv_values(ENV_PHASE6_FILE)
        present_vars = {k: v for k, v in target_vars.items() if k in REQUIRED_VARS}
        
        num_present = len(present_vars)
        print("     ✓ Found .env.phase6 file")
        print(f"     ℹ {num_present}/{len(REQUIRED_VARS)} required IBKR settings present")
        if 0 < num_present < len(REQUIRED_VARS):
            print("     ℹ Partial IBKR configuration detected")
        elif num_present == len(REQUIRED_VARS):
            print("     ℹ Full IBKR configuration detected")
        
        return present_vars
    except Exception as e:
        print(f"     ✗ Error checking .env.phase6: {e}")
        sys.exit(1)

def append_ibkr_settings(ibkr_config, keys_to_add, keys_to_update):
    updated = False
    try:
        with open(ENV_PHASE6_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        updated_lines = lines[:]
        
        # Update differing settings in place
        for key in keys_to_update:
            for i in range(len(updated_lines)):
                orig_line = updated_lines[i]
                stripped = orig_line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    parts = stripped.split('=', 1)
                    if len(parts) == 2 and parts[0].strip() == key:
                        updated_lines[i] = f"{key}={ibkr_config[key]}\n"
                        updated = True
                        break
        
        # Append missing settings under the IBKR section
        if keys_to_add:
            updated = True
            section_line = -1
            for i, line in enumerate(updated_lines):
                if '# IBKR Connection Settings' in line.strip():
                    section_line = i
                    break
            if section_line == -1:
                updated_lines.append("# IBKR Connection Settings\n")
                insert_pos = len(updated_lines) - 1
            else:
                insert_pos = section_line + 1
                while insert_pos < len(updated_lines):
                    l = updated_lines[insert_pos].strip()
                    if l.startswith('#') or not l or any(f"{v}=" in l for v in REQUIRED_VARS):
                        insert_pos += 1
                    else:
                        break
            for key in keys_to_add:
                var_line = f"{key}={ibkr_config[key]}\n"
                updated_lines.insert(insert_pos, var_line)
                insert_pos += 1
        
        if updated:
            with open(ENV_PHASE6_FILE, 'w', encoding='utf-8') as f:
                f.writelines(updated_lines)
            print("     ✓ IBKR settings updated/appended")
            return True
        return False
    except Exception as e:
        print(f"     ✗ Failed to update/append settings: {e}")
        sys.exit(1)

def verify_settings_added(ibkr_config):
    print("[3/4] Verifying settings...")
    try:
        target_vars = dotenv_values(ENV_PHASE6_FILE)
        all_good = True
        for var in REQUIRED_VARS:
            actual = target_vars.get(var)
            expected = ibkr_config[var]
            if actual is None or actual != expected:
                print(f"     ✗ {var} not present or incorrect (expected '{expected}')")
                all_good = False
            else:
                print(f"     ✓ {var}='{expected}'")
        if all_good:
            print("     ✓ All settings verified correctly")
        return all_good
    except Exception as e:
        print(f"     ✗ Verification error: {e}")
        return False

def display_summary(ibkr_config, changes_made):
    print("\n[4/4] Summary")
    print("=" * 60)
    if changes_made:
        print("✓ IBKR settings successfully added/updated to .env.phase6")
    else:
        print("ℹ .env.phase6 already contains correct IBKR settings")
    print("=" * 60)
    
    print("Settings:")
    for key, value in ibkr_config.items():
        print(f"  {key}={value}")
    
    print("\nNext steps:")
    print("  1. Review .env.phase6 to verify settings")
    print("  2. Run: python scripts/diagnose_ibkr_connection.py")
    print("  3. Run: python live/run_live.py")
    
    if not changes_made:
        print("\nNo changes needed. Settings are already configured.")
    print("=" * 60)

def update_env_phase6():
    print("IBKR Settings Update for .env.phase6")
    print("=" * 60)
    
    parser = argparse.ArgumentParser(description='Update .env.phase6 with IBKR settings')
    parser.add_argument('--force', action='store_true', help='Force update of differing settings')
    args = parser.parse_args()
    
    ibkr_config = validate_source_env()
    present_vars = check_target_file()
    
    missing = [var for var in REQUIRED_VARS if var not in present_vars]
    differing = [var for var in present_vars if present_vars[var] != ibkr_config[var]]
    
    changes_made = False
    if missing or differing:
        if differing and not args.force:
            print("     ⚠ Some IBKR settings differ:")
            for var in differing:
                print(f"       - {var}: '{present_vars[var]}' != '{ibkr_config[var]}'")
            print("     Use --force to update them.")
            sys.exit(1)
        
        print("     Updating/adding IBKR settings...")
        keys_to_update = differing if args.force else []
        keys_to_add = missing
        changes_made = append_ibkr_settings(ibkr_config, keys_to_add, keys_to_update)
    else:
        print("     ℹ All settings present and correct")
    
    verify_success = verify_settings_added(ibkr_config)
    if not verify_success:
        print("✗ Validation failed")
        sys.exit(1)
    
    display_summary(ibkr_config, changes_made)
    sys.exit(0)

if __name__ == "__main__":
    try:
        update_env_phase6()
    except KeyboardInterrupt:
        print("\n✗ Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)
