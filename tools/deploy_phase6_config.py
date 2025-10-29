#!/usr/bin/env python3
"""
Phase 6 Deployment Tool - Deploy optimized parameters to live trading configuration

Purpose
-------
Bridge Phase 6 optimization results to a live trading-ready .env file by mapping
typed Phase6Parameters to LIVE_* environment variables expected by live_config.py.
Also generate a human-readable deployment summary with expected performance and
important safety warnings.

Usage Examples
--------------
1) Select the top-ranked configuration and write default output files
   python tools/deploy_phase6_config.py --rank 1

2) Select a configuration by run ID
   python tools/deploy_phase6_config.py --run-id 12345

3) Preview configuration without writing files (dry run)
   python tools/deploy_phase6_config.py --rank 3 --dry-run

4) Customize output path and increase verbosity
   python tools/deploy_phase6_config.py --rank 2 --output .env.custom --verbose

5) List top N Phase 6 results and exit (default N=10)
   python tools/deploy_phase6_config.py --list --top 25

6) Overwrite existing output files without prompting
   python tools/deploy_phase6_config.py --rank 1 --force

Output
------
- .env-like file containing LIVE_* variables mapped from Phase 6 parameters
- A companion summary text file describing performance, parameters, risk, and next steps

Safety Notes
------------
- Always deploy to an IBKR paper trading account first (default paper port: 7497)
- Monitor live performance vs. backtest expectations and be prepared to halt
- Historical performance does not guarantee future results

Validation
----------
By default, the tool runs comprehensive validation checks before generating files:
- Symbol matching (Phase 6 optimized for EUR/USD only)
- Bar spec compatibility (15-minute primary, 2-minute DMI, 15-minute Stochastic)
- IBKR paper account verification (account ID must start with 'DU')
- Parameter range validation (all 14 parameters checked)
- Position sizing appropriateness (risk per trade vs account balance)
- Data feed availability (bar specs available in IBKR live feed)

Validation errors block deployment. Warnings allow proceeding with confirmation.
Use --skip-validation to bypass checks (not recommended).
Use --account-balance to enable position sizing validation.
"""

from __future__ import annotations

import sys
import os
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Ensure project root is importable (mirror tools/validate_phase6_oos.py pattern)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Project imports
from config.phase6_config_loader import (
    Phase6ConfigLoader,
    Phase6Parameters,
    Phase6PerformanceMetrics,
    Phase6Result,
)

from config.phase6_validator import (
    validate_phase6_for_live,
    print_validation_summary,
    ValidationResult,
    PHASE6_OPTIMIZED_SYMBOL as PHASE6_SYMBOL,
    PHASE6_OPTIMIZED_VENUE as PHASE6_VENUE,
    PHASE6_PRIMARY_BAR_SPEC as PHASE6_BAR_SPEC,
    PHASE6_DMI_BAR_SPEC as PHASE6_DMI_BAR_SPEC,
    PHASE6_STOCH_BAR_SPEC as PHASE6_STOCH_BAR_SPEC,
)
from config.ibkr_config import get_ibkr_config, IBKRConfig


# Constants
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / ".env.phase6"
PHASE6_STOCH_MAX_BARS_SINCE_CROSSING = 9
DEFAULT_TRADE_SIZE = 100000  # 1 standard lot for forex


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure console logging and return a logger.

    Parameters
    ----------
    verbose : bool
        Enable DEBUG-level output when True, INFO otherwise.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Remove any existing handlers (useful during repeated invocations)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def _format_money(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value*100.0:,.2f}%"


def format_performance_table(results: List[Phase6Result]) -> str:
    """Return a formatted ASCII table for the provided Phase 6 results.

    Columns: Rank, Run ID, Sharpe, Total PnL, Win Rate, Trades, Rejected Signals
    """
    headers = [
        ("Rank", 6),
        ("Run ID", 8),
        ("Sharpe", 8),
        ("Total PnL", 14),
        ("Win Rate", 12),
        ("Trades", 8),
        ("Rejected", 10),
    ]
    header_line = " ".join(f"{name:<{width}}" for name, width in headers)
    sep_line = "-" * len(header_line)

    rows: List[str] = []
    for r in results:
        rej = r.metrics.rejected_signals_count if r.metrics.rejected_signals_count is not None else 0
        row = " ".join(
            [
                f"{r.rank:<6}",
                f"{r.run_id:<8}",
                f"{r.metrics.sharpe_ratio:>8.4f}",
                f"{r.metrics.total_pnl:>14.2f}",
                f"{r.metrics.win_rate*100.0:>11.2f}%",
                f"{r.metrics.trade_count:>8}",
                f"{rej:>10}",
            ]
        )
        rows.append(row)

    return "\n".join([header_line, sep_line, *rows])


def generate_env_file_content(result: Phase6Result, include_comments: bool = True) -> str:
    """Generate .env file content from a Phase 6 result entry.

    Parameters
    ----------
    result : Phase6Result
        Selected Phase 6 result containing parameters and metrics.
    include_comments : bool
        When True, include explanatory comments for each section/parameter.

    Returns
    -------
    str
        Text content suitable for writing to a .env file.
    """
    params = result.parameters
    metrics = result.metrics
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: List[str] = []
    # Header block
    lines.append("# Phase 6 Optimized Configuration for Live Trading")
    lines.append(f"# Generated: {ts}")
    lines.append(f"# Rank: {result.rank}, Run ID: {result.run_id}")
    lines.append("# Expected Performance (backtest):")
    lines.append(f"#   Sharpe Ratio: {metrics.sharpe_ratio:.4f}")
    lines.append(f"#   Total PnL: {_format_money(metrics.total_pnl)}")
    lines.append(f"#   Win Rate: {metrics.win_rate*100.0:.2f}%")
    lines.append(f"#   Trade Count: {metrics.trade_count}")
    lines.append("#")
    lines.append("# WARNING: Always test on IBKR paper trading account first!")
    lines.append("# Paper trading port: 7497, Live trading port: 7496")
    lines.append("")

    # Phase 6 Optimized Configuration section
    lines.append("# Phase 6 Optimized Configuration")
    if include_comments:
        lines.append("# Trading symbol/venue and primary bar specification")
    lines.append(f"LIVE_SYMBOL={PHASE6_SYMBOL}")
    lines.append(f"LIVE_VENUE={PHASE6_VENUE}")
    lines.append(f"LIVE_BAR_SPEC={PHASE6_BAR_SPEC}")
    lines.append("")

    # Moving Average Parameters
    lines.append("# Moving Average Parameters")
    if include_comments:
        lines.append("# Fast/slow periods for the moving average crossover strategy")
    lines.append(f"LIVE_FAST_PERIOD={params.fast_period}")
    lines.append(f"LIVE_SLOW_PERIOD={params.slow_period}")
    lines.append("")

    # Risk Management Parameters
    lines.append("# Risk Management Parameters")
    if include_comments:
        lines.append("# Stop loss, take profit, and trailing stop settings (pips)")
    lines.append(f"LIVE_STOP_LOSS_PIPS={params.stop_loss_pips}")
    lines.append(f"LIVE_TAKE_PROFIT_PIPS={params.take_profit_pips}")
    lines.append(f"LIVE_TRAILING_STOP_ACTIVATION_PIPS={params.trailing_stop_activation_pips}")
    lines.append(f"LIVE_TRAILING_STOP_DISTANCE_PIPS={params.trailing_stop_distance_pips}")
    lines.append("")

    # Signal Filter Parameters
    lines.append("# Signal Filter Parameters")
    if include_comments:
        lines.append("# Minimum crossover threshold (pips) required to generate a signal")
    lines.append(f"LIVE_CROSSOVER_THRESHOLD_PIPS={params.crossover_threshold_pips}")
    lines.append("")

    # DMI Trend Filter Parameters
    lines.append("# DMI Trend Filter Parameters")
    if include_comments:
        lines.append("# Enable DMI, period length, and DMI timeframe bar spec")
    lines.append(f"LIVE_DMI_ENABLED={str(params.dmi_enabled).lower()}")
    lines.append(f"LIVE_DMI_PERIOD={params.dmi_period}")
    lines.append(f"LIVE_DMI_BAR_SPEC={PHASE6_DMI_BAR_SPEC}")
    lines.append("")

    # Stochastic Momentum Filter Parameters
    lines.append("# Stochastic Momentum Filter Parameters")
    if include_comments:
        lines.append("# Enable Stochastic and thresholds for bullish/bearish signals")
    lines.append(f"LIVE_STOCH_ENABLED={str(params.stoch_enabled).lower()}")
    lines.append(f"LIVE_STOCH_PERIOD_K={params.stoch_period_k}")
    lines.append(f"LIVE_STOCH_PERIOD_D={params.stoch_period_d}")
    lines.append(f"LIVE_STOCH_BULLISH_THRESHOLD={params.stoch_bullish_threshold}")
    lines.append(f"LIVE_STOCH_BEARISH_THRESHOLD={params.stoch_bearish_threshold}")
    lines.append(f"LIVE_STOCH_BAR_SPEC={PHASE6_STOCH_BAR_SPEC}")
    lines.append(f"LIVE_STOCH_MAX_BARS_SINCE_CROSSING={PHASE6_STOCH_MAX_BARS_SINCE_CROSSING}")
    lines.append("")

    # Position Management
    lines.append("# Position Management")
    if include_comments:
        lines.append("# Trade size (units), position limit enforcement, and reversal policy")
    lines.append(f"LIVE_TRADE_SIZE={DEFAULT_TRADE_SIZE}")
    lines.append("LIVE_ENFORCE_POSITION_LIMIT=true")
    lines.append("LIVE_ALLOW_POSITION_REVERSAL=false")
    lines.append("")

    # IBKR Connection (commented out; user must configure)
    lines.append("# IBKR Connection (configure as needed)")
    lines.append("# IBKR_HOST=127.0.0.1")
    lines.append("# IBKR_PORT=7497  # Paper trading port")
    lines.append("# IBKR_CLIENT_ID=1")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_deployment_summary(result: Phase6Result) -> str:
    """Generate a human-readable deployment summary document.

    Sections:
    - Deployment header with timestamp, rank, and run ID
    - Expected performance metrics
    - Strategy parameters (all 14 Phase 6 parameters)
    - Trading configuration and position sizing
    - Risk profile based on EUR/USD pip value
    - Important warnings and next steps
    """
    params = result.parameters
    m = result.metrics
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Risk profile calculation for EUR/USD
    # For pairs with USD as quote currency: pip value per 1 unit ≈ 0.0001 USD
    pip_value_usd_per_unit = 0.0001
    risk_per_trade = params.stop_loss_pips * DEFAULT_TRADE_SIZE * pip_value_usd_per_unit
    reward_per_trade = params.take_profit_pips * DEFAULT_TRADE_SIZE * pip_value_usd_per_unit
    rr_ratio = (reward_per_trade / risk_per_trade) if risk_per_trade > 0 else 0.0

    lines: List[str] = []
    lines.append("=" * 80)
    lines.append("PHASE 6 DEPLOYMENT SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Generated: {ts}")
    lines.append(f"Rank: {result.rank}")
    lines.append(f"Run ID: {result.run_id}")
    lines.append("")

    lines.append("EXPECTED PERFORMANCE (Historical Backtest)")
    lines.append("-" * 80)
    lines.append(f"Sharpe Ratio:        {m.sharpe_ratio:.4f}")
    lines.append(f"Total PnL:           {_format_money(m.total_pnl)}")
    lines.append(f"Win Rate:            {m.win_rate*100.0:.2f}%")
    lines.append(f"Trade Count:         {m.trade_count}")
    lines.append(f"Max Drawdown:        {_format_money(m.max_drawdown if m.max_drawdown is not None else 0.0)}")
    lines.append(f"Avg Winner:          {_format_money(m.avg_winner)}")
    lines.append(f"Avg Loser:           {_format_money(m.avg_loser)}")
    lines.append(f"Profit Factor:       {m.profit_factor if m.profit_factor is not None else 0.0:.2f}")
    lines.append(f"Expectancy:          {_format_money(m.expectancy)}")
    lines.append(f"Rejected Signals:    {m.rejected_signals_count if m.rejected_signals_count is not None else 0}")
    lines.append(f"Consecutive Losses:  {m.consecutive_losses if m.consecutive_losses is not None else 0}")
    lines.append("")

    lines.append("STRATEGY PARAMETERS")
    lines.append("-" * 80)
    lines.append(f"Fast Period:         {params.fast_period}")
    lines.append(f"Slow Period:         {params.slow_period}")
    lines.append(f"Crossover Threshold: {params.crossover_threshold_pips} pips")
    lines.append(f"Stop Loss:           {params.stop_loss_pips} pips")
    lines.append(f"Take Profit:         {params.take_profit_pips} pips")
    lines.append(f"Trail Activation:    {params.trailing_stop_activation_pips} pips")
    lines.append(f"Trail Distance:      {params.trailing_stop_distance_pips} pips")
    lines.append(f"DMI Enabled:         {params.dmi_enabled}")
    lines.append(f"DMI Period:          {params.dmi_period}")
    lines.append(f"Stoch Enabled:       {params.stoch_enabled}")
    lines.append(f"Stoch Period K:      {params.stoch_period_k}")
    lines.append(f"Stoch Period D:      {params.stoch_period_d}")
    lines.append(f"Stoch Bullish Th:    {params.stoch_bullish_threshold}")
    lines.append(f"Stoch Bearish Th:    {params.stoch_bearish_threshold}")
    lines.append("")

    lines.append("TRADING CONFIGURATION")
    lines.append("-" * 80)
    lines.append(f"Symbol:              {PHASE6_SYMBOL}")
    lines.append(f"Venue:               {PHASE6_VENUE}")
    lines.append(f"Bar Spec:            {PHASE6_BAR_SPEC}")
    lines.append(f"DMI Bar Spec:        {PHASE6_DMI_BAR_SPEC}")
    lines.append(f"Stoch Bar Spec:      {PHASE6_STOCH_BAR_SPEC}")
    lines.append(f"Trade Size:          {DEFAULT_TRADE_SIZE:,} units")
    lines.append("")

    lines.append("RISK PROFILE (Approximate)")
    lines.append("-" * 80)
    lines.append(f"Risk per trade:      {_format_money(risk_per_trade)}")
    lines.append(f"Reward per trade:    {_format_money(reward_per_trade)}")
    lines.append(f"Risk/Reward Ratio:   {rr_ratio:.2f}")
    lines.append("")

    lines.append("IMPORTANT WARNINGS")
    lines.append("-" * 80)
    lines.append("- This configuration is optimized for EUR/USD on 15-minute bars")
    lines.append("- Always deploy to IBKR paper trading account first (port 7497)")
    lines.append("- Monitor live performance vs backtest expectations")
    lines.append("- Phase 6 results are based on historical data and may not reflect future performance")
    lines.append("")

    lines.append("NEXT STEPS")
    lines.append("-" * 80)
    lines.append(f"- Copy generated .env file to .env")
    lines.append(f"- Verify IBKR paper trading connection (TWS/Gateway, port 7497)")
    lines.append(f"- Run live trading: python live/run_live.py")
    lines.append(f"- Monitor performance logs in logs/live/")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_env_file(content: str, output_path: Path, logger: logging.Logger) -> bool:
    """Write the .env file content to disk.

    Returns True on success, False otherwise. Logs errors and warnings.
    """
    try:
        if output_path.exists():
            logger.warning("Output file already exists and will be overwritten: %s", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info("Environment file written: %s", output_path)
        return True
    except OSError as exc:
        logger.error("Failed to write environment file '%s': %s", output_path, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error writing environment file '%s': %s", output_path, exc)
        return False


def write_summary_file(content: str, output_path: Path, logger: logging.Logger) -> bool:
    """Write the deployment summary to disk.

    Returns True on success, False otherwise.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info("Summary file written: %s", output_path)
        return True
    except OSError as exc:
        logger.error("Failed to write summary file '%s': %s", output_path, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error writing summary file '%s': %s", output_path, exc)
        return False


def print_results_table(loader: Phase6ConfigLoader, logger: logging.Logger, top_n: int) -> None:
    """Print a table of the top N Phase 6 results to the console."""
    top = loader.get_top_n(top_n)
    table = format_performance_table(top)
    print(f"\nPhase 6 Optimization Results (Top {top_n})")
    print(table)
    print("\nUse --rank N or --run-id ID to select a configuration for deployment")


def validate_rank(rank: Optional[int], loader: Phase6ConfigLoader, logger: logging.Logger) -> bool:
    """Validate that the rank is between 1 and 10 and exists in results."""
    if rank is None:
        logger.error("Rank must be provided when not using --list")
        return False
    try:
        rank_int = int(rank)
    except Exception:
        logger.error("Rank must be an integer between 1 and 10")
        return False
    if not (1 <= rank_int <= 10):
        logger.error("Rank must be between 1 and 10 inclusive")
        return False
    res = loader.get_by_rank(rank_int)
    if res is None:
        avail = [r.rank for r in loader.results]
        logger.error("Rank %s not found in results. Available ranks: %s", rank, avail)
        return False
    return True


def validate_run_id(run_id: Optional[int], loader: Phase6ConfigLoader, logger: logging.Logger) -> bool:
    """Validate that the run ID is a positive integer and exists in results."""
    if run_id is None:
        logger.error("Run ID must be provided when not using --list")
        return False
    try:
        run_id_int = int(run_id)
    except Exception:
        logger.error("Run ID must be an integer")
        return False
    if run_id_int <= 0:
        logger.error("Run ID must be positive")
        return False
    res = loader.get_by_run_id(run_id_int)
    if res is None:
        avail = [r.run_id for r in loader.results]
        logger.error("Run ID %s not found in results. Available run IDs: %s", run_id, avail)
        return False
    return True


def setup_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Deploy Phase 6 optimized parameters to live trading configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tools/deploy_phase6_config.py --rank 1\n"
            "  python tools/deploy_phase6_config.py --run-id 12345\n"
            "  python tools/deploy_phase6_config.py --rank 3 --output .env.custom --dry-run\n"
            "  python tools/deploy_phase6_config.py --list --top 25\n"
            "  python tools/deploy_phase6_config.py --rank 1 --force\n"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--rank",
        type=int,
        default=None,
        help="Rank of Phase 6 config to deploy (1-10). If omitted, displays results table.",
    )
    group.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Run ID of Phase 6 config to deploy. If omitted, displays results table.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_PATH),
        help="Output path for .env file (default: .env.phase6)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview configuration without writing files")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List top N Phase 6 results and exit (customize N with --top)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top results to display when listing (default: 10). Must be positive.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it exists without prompting",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--results-path",
        type=str,
        default=None,
        help="Custom path to Phase 6 results JSON file",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip Phase 6 validation checks (not recommended). Use only if you understand the risks.",
    )
    parser.add_argument(
        "--account-balance",
        type=float,
        default=None,
        help="Account balance in USD for position sizing validation (optional but recommended)",
    )
    return parser


def run_phase6_validation(
    result: Phase6Result, args: argparse.Namespace, logger: logging.Logger
) -> ValidationResult:
    """Run Phase 6 validation checks and return structured results.

    Attempts to load IBKR config for account validation but continues if unavailable.
    """
    params = result.parameters
    symbol = PHASE6_SYMBOL
    venue = PHASE6_VENUE
    bar_spec = PHASE6_BAR_SPEC
    dmi_bar_spec = PHASE6_DMI_BAR_SPEC
    stoch_bar_spec = PHASE6_STOCH_BAR_SPEC
    trade_size = DEFAULT_TRADE_SIZE

    ibkr_config: Optional[IBKRConfig]
    try:
        ibkr_config = get_ibkr_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to load IBKR configuration for validation: %s", exc)
        ibkr_config = None

    account_balance = getattr(args, "account_balance", None)

    validation_result = validate_phase6_for_live(
        params,
        symbol,
        venue,
        bar_spec,
        dmi_bar_spec,
        stoch_bar_spec,
        trade_size,
        ibkr_config,
        account_balance,
    )
    return validation_result


def main() -> int:
    """Orchestrate the deployment workflow from CLI arguments to file generation."""
    try:
        parser = setup_argument_parser()
        args = parser.parse_args()

        logger = setup_logging(args.verbose)
        logger.info("Starting Phase 6 deployment tool")

        # Load Phase 6 results
        results_path = Path(args.results_path) if args.results_path else None
        loader = Phase6ConfigLoader(results_path=results_path)

        # List mode or no selection provided: show table and exit
        if args.list or (args.rank is None and args.run_id is None):
            if args.top <= 0:
                logger.error("Top N must be positive")
                return 1
            try:
                print_results_table(loader, logger, args.top)
            except ValueError as exc:
                logger.error(str(exc))
                return 1
            return 0

        # Validate and load selected configuration by run-id or rank
        if args.run_id is not None:
            if not validate_run_id(args.run_id, loader, logger):
                return 1
            result = loader.get_by_run_id(int(args.run_id))
            if result is None:
                logger.error("Failed to load Phase 6 result for run_id %s", args.run_id)
                return 1
            logger.info(
                "Selected Phase 6 configuration by run_id: Run ID %s, Rank %s",
                result.run_id,
                result.rank,
            )
        else:
            if not validate_rank(args.rank, loader, logger):
                return 1
            result = loader.get_by_rank(int(args.rank))
            if result is None:
                logger.error("Failed to load Phase 6 result for rank %s", args.rank)
                return 1
            logger.info(
                "Selected Phase 6 configuration by rank: Rank %s, Run ID %s",
                result.rank,
                result.run_id,
            )

        # Run Phase 6 validation checks (unless --skip-validation)
        validation_result: Optional[ValidationResult] = None
        if not getattr(args, "skip_validation", False):
            logger.info("Running Phase 6 deployment validation checks...")
            validation_result = run_phase6_validation(result, args, logger)
            print_validation_summary(validation_result, logger)

            # Block deployment if validation errors present
            if not validation_result.is_valid:
                logger.error(
                    "Validation failed with %d errors. Deployment blocked.",
                    len(validation_result.errors),
                )
                logger.error(
                    "Fix the errors above or use --skip-validation to bypass (not recommended)."
                )
                return 1

            # Warn if validation warnings present (but allow proceeding)
            if validation_result.has_warnings():
                logger.warning(
                    "Validation passed with %d warnings. Review warnings above.",
                    len(validation_result.warnings),
                )
                if not args.dry_run and not args.force:
                    # In interactive mode, prompt user to confirm
                    try:
                        response = input("\nProceed with deployment despite warnings? [y/N]: ")
                        if response.lower() not in ["y", "yes"]:
                            logger.info("Deployment cancelled by user.")
                            return 0
                    except (EOFError, KeyboardInterrupt):
                        logger.info("\nDeployment cancelled by user.")
                        return 130

            logger.info("Validation passed. Proceeding with deployment.")
        else:
            logger.warning(
                "Validation checks skipped (--skip-validation). Proceeding without safety checks."
            )

        # Generate outputs
        env_content = generate_env_file_content(result, include_comments=True)
        summary_content = generate_deployment_summary(result)

        # Dry run: preview and exit
        if args.dry_run:
            print("\n=== DRY RUN MODE ===\n")
            print(".env file preview (first 50 lines):")
            env_lines = env_content.splitlines()
            preview = env_lines[:50]
            print("\n".join(preview))
            if len(env_lines) > 50:
                print("... (truncated)")
            print("\nDeployment Summary:\n")
            print(summary_content)
            # Show validation results in dry run when validation was performed
            if validation_result is not None:
                print("\nValidation Results:\n")
                print_validation_summary(validation_result)
            logger.info("Dry run complete. No files written.")
            return 0

        # Write files
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (PROJECT_ROOT / output_path).resolve()

        # Overwrite safeguard unless --force is provided
        if output_path.exists() and not args.force:
            logger.error(
                "Output file already exists: %s. Refusing to overwrite without --force.",
                output_path,
            )
            return 1

        ok_env = write_env_file(env_content, output_path, logger)
        summary_path = output_path.with_name(f"{output_path.name}_summary.txt")
        ok_sum = write_summary_file(summary_content, summary_path, logger)

        if not (ok_env and ok_sum):
            return 2

        # Console summary and next steps
        print(summary_content)
        print("Deployment configuration generated successfully!")
        print(f"Environment file: {output_path}")
        print(f"Summary file: {summary_path}")
        print(f"Next steps: Copy {output_path} to .env and run: python live/run_live.py")
        return 0

    except KeyboardInterrupt:
        logging.getLogger(__name__).warning("Deployment interrupted by user")
        return 130
    except ImportError as exc:
        logging.getLogger(__name__).error(
            "Import error: %s. Ensure validator module exists and is importable.", exc
        )
        return 1
    except (ValueError, FileNotFoundError) as exc:
        logging.getLogger(__name__).error(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error(f"Unexpected error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())


