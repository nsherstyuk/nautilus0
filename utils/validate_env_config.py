#!/usr/bin/env python3
"""
.env Configuration Validation and Auto-Fix Utility

This script validates .env configuration files for common errors and optionally
auto-fixes correctable issues. It checks symbol formats, date ranges, parameter
relationships, and catalog data availability.

Usage:
    python utils/validate_env_config.py                    # Validate only
    python utils/validate_env_config.py --fix             # Validate and auto-fix
    python utils/validate_env_config.py --fix --check-data # Also check catalog
    python utils/validate_env_config.py --json            # JSON output
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import dotenv_values, load_dotenv

# Local imports
try:
    from data.verify_catalog import collect_bar_summaries, ParquetDataCatalog
    from utils.instruments import try_both_instrument_formats
except ImportError as e:
    # Handle case where modules might not be available
    logging.warning(f"Could not import local modules: {e}")
    collect_bar_summaries = None
    ParquetDataCatalog = None
    try_both_instrument_formats = None

# Constants
ENV_FILE_DEFAULT = ".env"
ENV_EXAMPLE_FILE = ".env.example"
BACKUP_SUFFIX = ".backup"
MAX_BACKUPS = 5

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION FUNCTIONS (Read-Only)
# ============================================================================

def validate_symbol_format(symbol: str, var_name: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Check if symbol uses correct format (forex with /, stocks without).
    
    Args:
        symbol: The symbol to validate
        var_name: The variable name for error messages
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    if not symbol or symbol.strip() == "":
        return (False, "ERROR", f"{var_name} is empty or missing", None)
    
    symbol = symbol.strip()
    
    # Check for invalid combinations
    if "-" in symbol and "/" in symbol:
        return (False, "ERROR", f"{var_name} has both slash and hyphen: {symbol}", None)
    
    # Check for likely forex with wrong separator
    if "-" in symbol and "/" not in symbol:
        # Likely forex with wrong separator
        suggested = symbol.replace("-", "/")
        return (False, "ERROR", f"{var_name} uses hyphen instead of slash: {symbol}", suggested)
    
    # Valid format
    return (True, "PASS", f"{var_name} format valid: {symbol}", None)


def validate_date_format(date_str: str, var_name: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Check if date matches YYYY-MM-DD format and is valid calendar date.
    
    Args:
        date_str: The date string to validate
        var_name: The variable name for error messages
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    if not date_str or date_str.strip() == "":
        return (False, "ERROR", f"{var_name} is missing", None)
    
    date_str = date_str.strip()
    
    try:
        # Try to parse the date
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
        return (True, "PASS", f"{var_name} format valid: {date_str}", None)
    except ValueError:
        return (False, "ERROR", f"{var_name} must be YYYY-MM-DD format, got: {date_str}", None)


def validate_date_ordering(start_date: str, end_date: str, prefix: str) -> Tuple[bool, str, str, Optional[Tuple[str, str]]]:
    """
    Check if end date is after start date.
    
    Args:
        start_date: Start date string
        end_date: End date string  
        prefix: Prefix for error messages (e.g., "BACKTEST", "DATA")
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        if end_dt <= start_dt:
            # Dates are reversed
            return (False, "ERROR", f"{prefix} end date ({end_date}) is before start date ({start_date})", (end_date, start_date))
        
        # Check for unusual date ranges
        days_diff = (end_dt - start_dt).days
        if days_diff < 7:
            return (True, "WARNING", f"{prefix} date range is very short ({days_diff} days)", None)
        elif days_diff > 365:
            return (True, "WARNING", f"{prefix} date range is very long ({days_diff} days), may cause IBKR timeouts", None)
        
        return (True, "PASS", f"{prefix} date ordering valid (end > start)", None)
        
    except ValueError as e:
        return (False, "ERROR", f"{prefix} date parsing error: {e}", None)


def validate_symbol_consistency(data_symbols: str, backtest_symbol: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Check if DATA_SYMBOLS includes BACKTEST_SYMBOL.
    
    Args:
        data_symbols: Comma-separated list of data symbols
        backtest_symbol: The backtest symbol to check for
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    if not data_symbols or data_symbols.strip() == "":
        return (False, "WARNING", "DATA_SYMBOLS not set, will default to SPY", backtest_symbol)
    
    # Parse comma-separated symbols
    symbols = [s.strip() for s in data_symbols.split(",") if s.strip()]
    
    if backtest_symbol not in symbols:
        # Append BACKTEST_SYMBOL to existing DATA_SYMBOLS
        suggested_fix = f"{data_symbols},{backtest_symbol}" if data_symbols.strip() else backtest_symbol
        return (False, "WARNING", f"DATA_SYMBOLS ({data_symbols}) does not include BACKTEST_SYMBOL ({backtest_symbol})", suggested_fix)
    
    return (True, "PASS", "Symbol consistency valid", None)


def validate_ma_periods(fast: int, slow: int) -> Tuple[bool, str, str, Optional[str]]:
    """
    Check if fast period < slow period.
    
    Args:
        fast: Fast MA period
        slow: Slow MA period
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    if fast >= slow:
        return (False, "ERROR", f"BACKTEST_FAST_PERIOD ({fast}) must be less than BACKTEST_SLOW_PERIOD ({slow})", None)
    
    if slow - fast < 10:
        return (True, "WARNING", f"MA periods are very close (fast={fast}, slow={slow}), may generate many signals", None)
    
    return (True, "PASS", f"MA periods valid (fast={fast} < slow={slow})", None)


def validate_sl_tp_relationship(sl: int, tp: int) -> Tuple[bool, str, str, Optional[str]]:
    """
    Check if take profit > stop loss.
    
    Args:
        sl: Stop loss pips
        tp: Take profit pips
        
    Returns:
        (is_valid, severity, message, suggested_fix)
    """
    if tp <= sl:
        return (False, "ERROR", f"BACKTEST_TAKE_PROFIT_PIPS ({tp}) must be greater than BACKTEST_STOP_LOSS_PIPS ({sl})", None)
    
    ratio = tp / sl
    if ratio < 1.5:
        return (True, "WARNING", f"Risk/reward ratio ({ratio:.2f}) is low, consider increasing TP or decreasing SL", None)
    
    return (True, "PASS", f"SL/TP relationship valid (tp={tp} > sl={sl}, ratio={ratio:.2f})", None)


def validate_catalog_data(catalog_path: str, symbol: str, bar_spec: str, start_date: str, end_date: str, 
                         dmi_enabled: bool, stoch_enabled: bool) -> List[Tuple[bool, str, str, Optional[str]]]:
    """
    Check if catalog has required bar data (only with --check-data flag).
    
    Args:
        catalog_path: Path to catalog directory
        symbol: Symbol to check (e.g., "EUR/USD")
        bar_spec: Primary bar specification
        start_date: Backtest start date
        end_date: Backtest end date
        dmi_enabled: Whether DMI indicator is enabled
        stoch_enabled: Whether Stochastic indicator is enabled
        
    Returns:
        List of validation results for each bar spec
    """
    results = []
    
    if not ParquetDataCatalog or not collect_bar_summaries:
        results.append((True, "WARNING", "Catalog validation modules not available; install NautilusTrader to enable --check-data.", None))
        return results
    
    # Check if catalog directory exists
    if not os.path.exists(catalog_path):
        results.append((False, "ERROR", f"Catalog directory not found at {catalog_path}. Run: python data/ingest_historical.py", None))
        return results
    
    try:
        # Load catalog
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        # Get instrument ID variants
        if try_both_instrument_formats:
            instrument_variants = try_both_instrument_formats(symbol)
        else:
            # Fallback: assume IDEALPRO for forex
            instrument_variants = [f"{symbol}.IDEALPRO"]
        
        # Build required bar types for each variant
        required_bar_types = set()
        for instrument_id in instrument_variants:
            required_bar_types.add(f"{instrument_id}-{bar_spec}")
            if dmi_enabled:
                required_bar_types.add(f"{instrument_id}-2-MINUTE-MID-EXTERNAL")
            if stoch_enabled:
                required_bar_types.add(f"{instrument_id}-15-MINUTE-MID-EXTERNAL")
        
        # Check each required bar type
        found_bar_types = set()
        for bar_type in required_bar_types:
            found = False
            bar_count = 0
            
            for summary in summaries:
                if summary.bar_type == bar_type:
                    found = True
                    bar_count = summary.bar_count
                    found_bar_types.add(bar_type)
                    break
            
            if not found:
                results.append((False, "ERROR", f"Bar type not found: {bar_type}", None))
            elif bar_count == 0:
                results.append((False, "ERROR", f"Bar type has no bars: {bar_type}", None))
            else:
                results.append((True, "PASS", f"Found bar type ({bar_count} bars): {bar_type}", None))
        
        # Check date coverage
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            coverage_ok = True
            for summary in summaries:
                if summary.bar_type in found_bar_types:
                    if summary.start_ts > start_dt or summary.end_ts < end_dt:
                        coverage_ok = False
                        results.append((False, "WARNING", 
                                      f"Data coverage incomplete for {summary.bar_type}: "
                                      f"{summary.start_ts.date()} to {summary.end_ts.date()}", None))
                        break
            
            if coverage_ok:
                results.append((True, "PASS", f"Data covers backtest range ({start_date} to {end_date})", None))
                
        except ValueError as e:
            results.append((False, "ERROR", f"Date parsing error: {e}", None))
            
    except Exception as e:
        results.append((False, "ERROR", f"Catalog validation failed: {e}", None))
    
    return results


# ============================================================================
# FIX FUNCTIONS (Write Operations)
# ============================================================================

def backup_env_file(env_file: Path) -> Path:
    """
    Create timestamped backup before modifications.
    
    Args:
        env_file: Path to .env file
        
    Returns:
        Path to backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = env_file.with_name(f"{env_file.name}{BACKUP_SUFFIX}.{timestamp}")
    
    # Create backup
    shutil.copy2(env_file, backup_path)
    logger.info(f"Created backup: {backup_path}")
    
    # Cleanup old backups
    backup_dir = env_file.parent
    backup_files = list(backup_dir.glob(f"{env_file.name}{BACKUP_SUFFIX}.*"))
    backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    # Keep only the last MAX_BACKUPS
    for old_backup in backup_files[MAX_BACKUPS:]:
        old_backup.unlink()
        logger.debug(f"Removed old backup: {old_backup}")
    
    return backup_path


def load_env_file(env_file: Path) -> List[str]:
    """
    Load .env file preserving formatting and comments.
    
    Args:
        env_file: Path to .env file
        
    Returns:
        List of lines from the file
    """
    return env_file.read_text().splitlines()


def save_env_file(env_file: Path, lines: List[str]) -> None:
    """
    Write modified lines back to .env file.
    
    Args:
        env_file: Path to .env file
        lines: Modified lines to write
    """
    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"
    env_file.write_text(content)


def fix_env_variable(lines: List[str], var_name: str, new_value: str) -> Tuple[List[str], bool]:
    """
    Update or add environment variable in .env file.
    
    Args:
        lines: List of lines from .env file
        var_name: Variable name to update
        new_value: New value to set
        
    Returns:
        (modified_lines, was_modified)
    """
    modified_lines = lines.copy()
    was_modified = False
    
    # Pattern to match the variable assignment
    pattern = re.compile(rf"^{re.escape(var_name)}=(.*)$")
    
    for i, line in enumerate(modified_lines):
        match = pattern.match(line)
        if match:
            # Found the variable, update it
            old_value = match.group(1)
            # Preserve any inline comment with original spacing
            if "#" in old_value:
                comment_part = old_value.split("#", 1)[1]
                # Reconstruct the line using the original separator and comment
                modified_lines[i] = f"{var_name}={new_value}#{comment_part}"
            else:
                modified_lines[i] = f"{var_name}={new_value}"
            was_modified = True
            break
    
    if not was_modified:
        # Variable not found, add it at the end
        modified_lines.append(f"{var_name}={new_value}")
        was_modified = True
    
    return modified_lines, was_modified


def apply_fixes(env_file: Path, fixes: List[Dict[str, Any]]) -> int:
    """
    Apply all auto-fixes to .env file.
    
    Args:
        env_file: Path to .env file
        fixes: List of fixes to apply
        
    Returns:
        Number of fixes applied
    """
    if not fixes:
        return 0
    
    try:
        # Create backup
        backup_path = backup_env_file(env_file)
        
        # Load file
        lines = load_env_file(env_file)
        
        # Apply each fix
        fixes_applied = 0
        for fix in fixes:
            var_name = fix["var_name"]
            new_value = fix["new_value"]
            
            lines, was_modified = fix_env_variable(lines, var_name, new_value)
            if was_modified:
                fixes_applied += 1
                logger.info(f"Fixed {var_name}={new_value}")
        
        # Save file
        save_env_file(env_file, lines)
        
        logger.info(f"Applied {fixes_applied} fixes, backup saved to {backup_path}")
        return fixes_applied
        
    except Exception as e:
        logger.error(f"Failed to apply fixes: {e}")
        return 0


# ============================================================================
# CLI INTERFACE
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate and optionally fix .env configuration files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python utils/validate_env_config.py                    # Validate only
  python utils/validate_env_config.py --fix             # Validate and auto-fix
  python utils/validate_env_config.py --fix --check-data # Also check catalog
  python utils/validate_env_config.py --json            # JSON output
        """
    )
    
    parser.add_argument(
        "--env-file",
        default=ENV_FILE_DEFAULT,
        help=f"Path to .env file (default: {ENV_FILE_DEFAULT})"
    )
    
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Enable auto-fix mode for correctable issues"
    )
    
    parser.add_argument(
        "--check-data",
        action="store_true", 
        help="Verify catalog data availability"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable format"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser.parse_args()


def run_validation(env_file: Path, check_data: bool) -> Tuple[List[Tuple], List[Dict], List[Tuple]]:
    """
    Run all validation checks.
    
    Args:
        env_file: Path to .env file
        check_data: Whether to check catalog data
        
    Returns:
        (validation_results, fixable_issues, catalog_results)
    """
    results = []
    fixable_issues = []
    catalog_results = []
    
    try:
        # Load environment variables
        env = dotenv_values(env_file)
        
        # Validate required variables exist
        required_vars = ["BACKTEST_SYMBOL", "BACKTEST_START_DATE", "BACKTEST_END_DATE"]
        for var in required_vars:
            if var not in env or not env[var]:
                results.append((False, "ERROR", f"{var} is missing", None))
        
        # Symbol format validation
        if "BACKTEST_SYMBOL" in env and env["BACKTEST_SYMBOL"]:
            is_valid, severity, message, suggested_fix = validate_symbol_format(env["BACKTEST_SYMBOL"], "BACKTEST_SYMBOL")
            results.append((is_valid, severity, message, suggested_fix))
            if suggested_fix:
                fixable_issues.append({"var_name": "BACKTEST_SYMBOL", "new_value": suggested_fix})
        
        # DATA_SYMBOLS format validation (if present)
        if "DATA_SYMBOLS" in env and env["DATA_SYMBOLS"]:
            # Split comma-separated symbols and validate each
            symbols = [s.strip() for s in env["DATA_SYMBOLS"].split(",") if s.strip()]
            invalid_symbols = []
            fixed_symbols = []
            
            for symbol in symbols:
                is_valid, severity, message, suggested_fix = validate_symbol_format(symbol, f"DATA_SYMBOLS[{symbol}]")
                if not is_valid:
                    invalid_symbols.append(symbol)
                    if suggested_fix:
                        fixed_symbols.append(suggested_fix)
                    else:
                        fixed_symbols.append(symbol)  # Keep original if no fix available
                else:
                    fixed_symbols.append(symbol)
            
            if invalid_symbols:
                if args.fix:
                    # Only replace hyphens with slashes for offending entries
                    new_value = ",".join(fixed_symbols)
                    results.append((True, "FIXED", f"DATA_SYMBOLS fixed: {', '.join(invalid_symbols)} -> {', '.join(fixed_symbols)}", None))
                    fixable_issues.append({"var_name": "DATA_SYMBOLS", "new_value": new_value})
                else:
                    results.append((False, "ERROR", f"DATA_SYMBOLS contains invalid symbols: {', '.join(invalid_symbols)}", ",".join(fixed_symbols)))
            else:
                results.append((True, "PASS", f"DATA_SYMBOLS format valid: {env['DATA_SYMBOLS']}", None))
        
        # Date format validation
        for date_var in ["BACKTEST_START_DATE", "BACKTEST_END_DATE", "DATA_START_DATE", "DATA_END_DATE"]:
            if date_var in env and env[date_var]:
                is_valid, severity, message, suggested_fix = validate_date_format(env[date_var], date_var)
                results.append((is_valid, severity, message, suggested_fix))
        
        # Date ordering validation
        if "BACKTEST_START_DATE" in env and "BACKTEST_END_DATE" in env and env["BACKTEST_START_DATE"] and env["BACKTEST_END_DATE"]:
            is_valid, severity, message, suggested_fix = validate_date_ordering(
                env["BACKTEST_START_DATE"], env["BACKTEST_END_DATE"], "BACKTEST"
            )
            results.append((is_valid, severity, message, suggested_fix))
            if suggested_fix and isinstance(suggested_fix, tuple):
                # Swap the dates
                fixable_issues.append({"var_name": "BACKTEST_START_DATE", "new_value": suggested_fix[0]})
                fixable_issues.append({"var_name": "BACKTEST_END_DATE", "new_value": suggested_fix[1]})
        
        if "DATA_START_DATE" in env and "DATA_END_DATE" in env and env["DATA_START_DATE"] and env["DATA_END_DATE"]:
            is_valid, severity, message, suggested_fix = validate_date_ordering(
                env["DATA_START_DATE"], env["DATA_END_DATE"], "DATA"
            )
            results.append((is_valid, severity, message, suggested_fix))
            if suggested_fix and isinstance(suggested_fix, tuple):
                fixable_issues.append({"var_name": "DATA_START_DATE", "new_value": suggested_fix[0]})
                fixable_issues.append({"var_name": "DATA_END_DATE", "new_value": suggested_fix[1]})
        
        # Symbol consistency validation
        if "BACKTEST_SYMBOL" in env and env["BACKTEST_SYMBOL"]:
            is_valid, severity, message, suggested_fix = validate_symbol_consistency(
                env.get("DATA_SYMBOLS", ""), env["BACKTEST_SYMBOL"]
            )
            results.append((is_valid, severity, message, suggested_fix))
            if suggested_fix:
                fixable_issues.append({"var_name": "DATA_SYMBOLS", "new_value": suggested_fix})
        
        # MA periods validation
        try:
            fast_period = int(env.get("BACKTEST_FAST_PERIOD", 10))
            slow_period = int(env.get("BACKTEST_SLOW_PERIOD", 20))
            is_valid, severity, message, suggested_fix = validate_ma_periods(fast_period, slow_period)
            results.append((is_valid, severity, message, suggested_fix))
        except (ValueError, TypeError):
            results.append((False, "ERROR", "Invalid MA period values", None))
        
        # SL/TP relationship validation
        try:
            sl_pips = int(env.get("BACKTEST_STOP_LOSS_PIPS", 25))
            tp_pips = int(env.get("BACKTEST_TAKE_PROFIT_PIPS", 50))
            is_valid, severity, message, suggested_fix = validate_sl_tp_relationship(sl_pips, tp_pips)
            results.append((is_valid, severity, message, suggested_fix))
        except (ValueError, TypeError):
            results.append((False, "ERROR", "Invalid SL/TP values", None))
        
        # Catalog data validation (if requested)
        if check_data:
            catalog_path = env.get("CATALOG_PATH", "data/historical")
            symbol = env.get("BACKTEST_SYMBOL", "")
            bar_spec = env.get("BACKTEST_BAR_SPEC", "1-MINUTE-MID-EXTERNAL")
            start_date = env.get("BACKTEST_START_DATE", "")
            end_date = env.get("BACKTEST_END_DATE", "")
            dmi_enabled = env.get("BACKTEST_DMI_ENABLED", "false").lower() == "true"
            stoch_enabled = env.get("BACKTEST_STOCH_ENABLED", "false").lower() == "true"
            
            catalog_results = validate_catalog_data(
                catalog_path, symbol, bar_spec, start_date, end_date, dmi_enabled, stoch_enabled
            )
            results.extend(catalog_results)
        
    except Exception as e:
        results.append((False, "ERROR", f"Validation failed: {e}", None))
    
    return results, fixable_issues, catalog_results


def format_validation_report(results: List[Tuple], fixes_applied: int) -> str:
    """
    Generate human-readable validation report.
    
    Args:
        results: List of validation results
        fixes_applied: Number of fixes applied
        
    Returns:
        Formatted report string
    """
    lines = []
    lines.append(".env Configuration Validation Report")
    lines.append("=" * 40)
    lines.append("")
    
    # Count results by severity
    counts = {"PASS": 0, "WARNING": 0, "ERROR": 0, "FIXED": 0}
    
    # Track variables that were changed
    changed_variables = []
    
    for is_valid, severity, message, suggested_fix in results:
        if severity == "PASS":
            lines.append(f"✅ PASS: {message}")
            counts["PASS"] += 1
        elif severity == "WARNING":
            lines.append(f"⚠️  WARNING: {message}")
            counts["WARNING"] += 1
        elif severity == "ERROR":
            lines.append(f"❌ ERROR: {message}")
            counts["ERROR"] += 1
        elif severity == "FIXED":
            lines.append(f"🔧 FIXED: {message}")
            counts["FIXED"] += 1
            # Extract variable name from message for tracking
            if "fixed:" in message.lower():
                var_name = message.split(":")[0].strip()
                if var_name not in changed_variables:
                    changed_variables.append(var_name)
        
        # Show suggested fix if available and not applied
        if suggested_fix and severity != "FIXED":
            lines.append(f"   💡 Suggested fix: {suggested_fix}")
    
    lines.append("")
    lines.append("Summary:")
    lines.append(f"  ✅ Passed: {counts['PASS']}")
    lines.append(f"  ⚠️  Warnings: {counts['WARNING']}")
    lines.append(f"  ❌ Errors: {counts['ERROR']}")
    if fixes_applied > 0:
        lines.append(f"  🔧 Auto-fixed: {fixes_applied}")
    
    # Add section for variables changed in this run
    if changed_variables:
        lines.append("")
        lines.append("Variables Changed in This Run:")
        for var in changed_variables:
            lines.append(f"  🔧 {var}")
    
    # Overall status
    if counts["ERROR"] > 0:
        lines.append("")
        lines.append("Status: ❌ Errors must be fixed before backtesting")
    elif counts["WARNING"] > 0:
        lines.append("")
        lines.append("Status: ⚠️  Ready for backtesting (with warnings)")
    else:
        lines.append("")
        lines.append("Status: ✅ Ready for backtesting")
    
    return "\n".join(lines)


def format_json_report(results: List[Tuple], catalog_results: List[Tuple], fixes_applied: int) -> str:
    """
    Generate JSON validation report.
    
    Args:
        results: List of validation results
        catalog_results: List of catalog validation results
        fixes_applied: Number of fixes applied
        
    Returns:
        JSON report string
    """
    # Count results by severity
    counts = {"PASS": 0, "WARNING": 0, "ERROR": 0, "FIXED": 0}
    
    checks = []
    for is_valid, severity, message, suggested_fix in results:
        check = {
            "status": severity,
            "message": message
        }
        if suggested_fix:
            check["suggested_fix"] = suggested_fix
        checks.append(check)
        counts[severity] += 1
    
    # Build report
    report = {
        "timestamp": datetime.now().isoformat() + "Z",
        "checks": checks,
        "summary": {
            "total_checks": len(results),
            "passed": counts["PASS"],
            "warnings": counts["WARNING"],
            "errors": counts["ERROR"],
            "fixed": fixes_applied,
            "ready_for_backtest": counts["ERROR"] == 0
        }
    }
    
    # Add catalog check results if available
    if catalog_results:
        catalog_checks = []
        for is_valid, severity, message, suggested_fix in catalog_results:
            catalog_checks.append({
                "status": severity,
                "message": message
            })
        
        report["catalog_check"] = {
            "enabled": True,
            "checks": catalog_checks
        }
    
    return json.dumps(report, indent=2)


def main() -> int:
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    env_file = Path(args.env_file)
    
    # Check if .env file exists
    if not env_file.exists():
        print(f"❌ ERROR: .env file not found at {env_file}")
        if Path(ENV_EXAMPLE_FILE).exists():
            print(f"💡 Suggestion: Copy from example: cp {ENV_EXAMPLE_FILE} {env_file}")
        else:
            print("💡 Suggestion: Create a .env file with your configuration")
        return 2
    
    # Run validation
    results, fixable_issues, catalog_results = run_validation(env_file, args.check_data)
    
    # Apply fixes if requested
    fixes_applied = 0
    if args.fix and fixable_issues:
        fixes_applied = apply_fixes(env_file, fixable_issues)
        
        # Re-run validation to confirm fixes
        if fixes_applied > 0:
            results, _, catalog_results = run_validation(env_file, args.check_data)
    
    # Generate and display report
    if args.json:
        report = format_json_report(results, catalog_results, fixes_applied)
        print(report)
    else:
        report = format_validation_report(results, fixes_applied)
        print(report)
    
    # Return appropriate exit code
    error_count = sum(1 for _, severity, _, _ in results if severity == "ERROR")
    if error_count > 0:
        return 1  # Errors found
    else:
        return 0  # Success


if __name__ == "__main__":
    sys.exit(main())
