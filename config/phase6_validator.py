"""
Phase 6 Live Deployment Validator
=================================

Purpose
-------
Pre-deployment validation to ensure Phase 6 parameters are safe and appropriate
for live trading. This module performs comprehensive checks covering:

- Symbol matching (EUR/USD on IDEALPRO)
- Bar spec compatibility (primary timeframe, DMI, Stochastic)
- IBKR account type (paper vs live)
- Parameter ranges (guardrails for the 14 Phase 6 parameters)
- Position sizing (risk per trade vs account balance)
- Data feed availability (common IBKR timeframes)

Design
------
Validation does not raise exceptions during normal operation; instead it returns
structured results with errors (blocking) and warnings (non-blocking). Callers
decide whether to proceed, prompt for confirmation, or abort based on the
results.

Usage
-----
Example integration in a deployment workflow:

    from config.phase6_validator import (
        validate_phase6_for_live,
        print_validation_summary,
    )
    from config.phase6_config_loader import Phase6Result
    from config.ibkr_config import get_ibkr_config

    result: Phase6Result = ...  # loaded elsewhere
    ibkr_cfg = None
    try:
        ibkr_cfg = get_ibkr_config()
    except Exception:
        ibkr_cfg = None

    validation = validate_phase6_for_live(
        params=result.parameters,
        symbol="EUR/USD",
        venue="IDEALPRO",
        bar_spec="15-MINUTE-MID-EXTERNAL",
        dmi_bar_spec="2-MINUTE-MID-EXTERNAL",
        stoch_bar_spec="15-MINUTE-MID-EXTERNAL",
        trade_size=100000,
        ibkr_config=ibkr_cfg,
        account_balance=50000.0,
    )
    print_validation_summary(validation)

If validation contains errors, deployment should be blocked. Warnings may be
acceptable with explicit user confirmation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from config.phase6_config_loader import Phase6Parameters, Phase6PerformanceMetrics  # noqa: F401
from config.ibkr_config import IBKRConfig


# Phase 6 optimization constraints
PHASE6_OPTIMIZED_SYMBOL = "EUR/USD"
PHASE6_OPTIMIZED_VENUE = "IDEALPRO"
PHASE6_PRIMARY_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
PHASE6_DMI_BAR_SPEC = "2-MINUTE-MID-EXTERNAL"
PHASE6_STOCH_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
PAPER_ACCOUNT_PREFIX = "DU"

# Reasonable parameter ranges for live trading
MIN_FAST_PERIOD = 5
MAX_FAST_PERIOD = 100
MIN_SLOW_PERIOD = 20
MAX_SLOW_PERIOD = 500
MIN_STOP_LOSS_PIPS = 5
MAX_STOP_LOSS_PIPS = 200
MIN_TAKE_PROFIT_PIPS = 10
MAX_TAKE_PROFIT_PIPS = 500
MIN_TRAILING_ACTIVATION_PIPS = 5
MAX_TRAILING_ACTIVATION_PIPS = 200
MIN_TRAILING_DISTANCE_PIPS = 3
MAX_TRAILING_DISTANCE_PIPS = 100
MIN_CROSSOVER_THRESHOLD_PIPS = 0.0
MAX_CROSSOVER_THRESHOLD_PIPS = 10.0
MIN_DMI_PERIOD = 5
MAX_DMI_PERIOD = 50
MIN_STOCH_PERIOD = 5
MAX_STOCH_PERIOD = 50
MIN_STOCH_THRESHOLD = 0
MAX_STOCH_THRESHOLD = 100

# Position sizing limits
MIN_TRADE_SIZE = 1000  # 0.01 lot
MAX_TRADE_SIZE = 10000000  # 100 lots
RECOMMENDED_MAX_RISK_PER_TRADE_PCT = 0.02  # 2%


@dataclass
class ValidationResult:
    """Collect validation results for Phase 6 live deployment.

    Attributes
    ----------
    is_valid : bool
        True when no errors have been recorded; False otherwise.
    errors : List[str]
        Blocking issues that should prevent deployment.
    warnings : List[str]
        Non-blocking issues that should be reviewed before proceeding.
    info_messages : List[str]
        Informational notes produced during validation.
    """

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info_messages: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.info_messages.append(message)

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def has_errors(self) -> bool:
        return not self.is_valid or len(self.errors) > 0

    def get_summary(self) -> str:
        parts: List[str] = ["=== Phase 6 Deployment Validation ==="]
        if self.errors:
            parts.append("ERRORS (deployment blocked):")
            parts.extend([f"  ❌ {e}" for e in self.errors])
        if self.warnings:
            parts.append("WARNINGS (review recommended):")
            parts.extend([f"  ⚠️  {w}" for w in self.warnings])
        if self.info_messages:
            parts.append("INFO:")
            parts.extend([f"  ℹ️  {i}" for i in self.info_messages])
        footer = (
            f"✅ Validation PASSED (with {len(self.warnings)} warnings)"
            if self.is_valid
            else f"❌ Validation FAILED ({len(self.errors)} errors)"
        )
        parts.append(footer)
        return "\n".join(parts)


def _extract_timeframe(bar_spec: str) -> str:
    """Extract timeframe token (e.g., '15-MINUTE') from a bar spec string.

    Bar specs are expected like '15-MINUTE-MID-EXTERNAL'. This function is
    robust to minor variations; it splits on '-' and returns '<first>-<second>'.
    """
    if not bar_spec:
        return ""
    parts = bar_spec.upper().split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return bar_spec.upper()


def validate_symbol_match(symbol: str, venue: str, result: ValidationResult) -> None:
    """Validate that deployment symbol/venue match Phase 6 optimization.

    Parameters
    ----------
    symbol : str
        The deployment symbol, expected 'EUR/USD'.
    venue : str
        The trading venue, expected 'IDEALPRO'.
    result : ValidationResult
        Collector for validation findings.
    """
    sym_u = (symbol or "").upper()
    ven_u = (venue or "").upper()

    if sym_u != PHASE6_OPTIMIZED_SYMBOL:
        result.add_error(
            f"Phase 6 parameters were optimized for EUR/USD only. Deploying to {symbol} may produce unexpected results. Consider running out-of-sample validation first."
        )
    if ven_u != PHASE6_OPTIMIZED_VENUE:
        result.add_warning(
            f"Phase 6 was optimized for IDEALPRO venue. Using {venue} may have different execution characteristics."
        )
    result.add_info(f"Symbol validation: {symbol} on {venue}")


def validate_bar_spec_compatibility(
    bar_spec: str,
    dmi_bar_spec: str,
    stoch_bar_spec: str,
    result: ValidationResult,
) -> None:
    """Validate bar specifications vs Phase 6 optimization assumptions.

    - Primary timeframe should be 15-MINUTE
    - DMI timeframe should be 2-MINUTE
    - Stochastic timeframe should be 15-MINUTE
    - Forex pricing should use MID (not LAST)
    """
    tf_primary = _extract_timeframe(bar_spec)
    tf_dmi = _extract_timeframe(dmi_bar_spec)
    tf_stoch = _extract_timeframe(stoch_bar_spec)

    if tf_primary != "15-MINUTE":
        result.add_warning(
            f"Phase 6 was optimized on 15-minute bars. Using {bar_spec} may affect performance. Consider running out-of-sample validation."
        )
    if tf_dmi != "2-MINUTE":
        result.add_warning(
            f"Phase 6 DMI was optimized on 2-minute bars. Using {dmi_bar_spec} may affect indicator behavior."
        )
    if tf_stoch != "15-MINUTE":
        result.add_warning(
            f"Phase 6 Stochastic was optimized on 15-minute bars. Using {stoch_bar_spec} may affect indicator behavior."
        )

    # Enforce MID pricing for forex
    for spec_label, spec_value in (
        ("Primary", bar_spec),
        ("DMI", dmi_bar_spec),
        ("Stochastic", stoch_bar_spec),
    ):
        spec_u = (spec_value or "").upper()
        if "LAST" in spec_u:
            result.add_error(
                f"Forex instruments should use MID pricing, not LAST. {spec_label} bar spec: {spec_value}"
            )

    result.add_info(
        f"Bar spec validation: Primary={bar_spec}, DMI={dmi_bar_spec}, Stoch={stoch_bar_spec}"
    )


def validate_ibkr_paper_account(ibkr_config: Optional[IBKRConfig], result: ValidationResult) -> None:
    """Validate IBKR account appears to be a paper trading account.

    When configuration is missing or incomplete, produce warnings instead of
    blocking errors, except when a non-paper account is detected.
    """
    if ibkr_config is None:
        result.add_warning(
            "IBKR configuration not provided. Cannot verify paper trading account. Ensure you're using a paper account (DU prefix)."
        )
        return

    account_id = getattr(ibkr_config, "account_id", None) or ""
    if not account_id:
        result.add_warning(
            "IBKR account_id not configured. Cannot verify paper trading account. Ensure you're using a paper account (DU prefix)."
        )
    else:
        if not str(account_id).startswith(PAPER_ACCOUNT_PREFIX):
            result.add_error(
                f"IBKR account '{account_id}' does not appear to be a paper trading account (should start with 'DU'). Phase 6 deployment should ALWAYS be tested on paper first."
            )
        else:
            result.add_info(f"IBKR paper account verified: {account_id}")

    port = getattr(ibkr_config, "port", None)
    if isinstance(port, int) and port not in (7497, 4002):
        result.add_warning(
            f"IBKR port {port} is not a standard paper trading port (7497 for TWS, 4002 for Gateway). Verify you're connected to paper trading."
        )


def validate_parameter_ranges(params: Phase6Parameters, result: ValidationResult) -> None:
    """Validate Phase 6 parameters against reasonable live trading ranges.

    Includes moving averages, risk management, signal filters, DMI, and
    Stochastic parameters.
    """
    prev_err = len(result.errors)
    prev_warn = len(result.warnings)

    # Moving Average Parameters
    if not (MIN_FAST_PERIOD <= params.fast_period <= MAX_FAST_PERIOD):
        result.add_error(
            f"Fast period {params.fast_period} is outside reasonable range [{MIN_FAST_PERIOD}, {MAX_FAST_PERIOD}]"
        )
    if not (MIN_SLOW_PERIOD <= params.slow_period <= MAX_SLOW_PERIOD):
        result.add_error(
            f"Slow period {params.slow_period} is outside reasonable range [{MIN_SLOW_PERIOD}, {MAX_SLOW_PERIOD}]"
        )
    if params.fast_period >= params.slow_period:
        result.add_error("Fast period must be less than slow period")

    # Risk Management Parameters
    if not (MIN_STOP_LOSS_PIPS <= params.stop_loss_pips <= MAX_STOP_LOSS_PIPS):
        result.add_error(
            f"Stop loss {params.stop_loss_pips} pips is outside reasonable range [{MIN_STOP_LOSS_PIPS}, {MAX_STOP_LOSS_PIPS}]"
        )
    if not (MIN_TAKE_PROFIT_PIPS <= params.take_profit_pips <= MAX_TAKE_PROFIT_PIPS):
        result.add_error(
            f"Take profit {params.take_profit_pips} pips is outside reasonable range [{MIN_TAKE_PROFIT_PIPS}, {MAX_TAKE_PROFIT_PIPS}]"
        )
    if params.take_profit_pips <= params.stop_loss_pips:
        result.add_error("Take profit must be greater than stop loss")
    if not (MIN_TRAILING_ACTIVATION_PIPS <= params.trailing_stop_activation_pips <= MAX_TRAILING_ACTIVATION_PIPS):
        result.add_error(
            f"Trailing stop activation {params.trailing_stop_activation_pips} pips is outside reasonable range"
        )
    if not (MIN_TRAILING_DISTANCE_PIPS <= params.trailing_stop_distance_pips <= MAX_TRAILING_DISTANCE_PIPS):
        result.add_error(
            f"Trailing stop distance {params.trailing_stop_distance_pips} pips is outside reasonable range"
        )
    if params.trailing_stop_activation_pips <= params.trailing_stop_distance_pips:
        result.add_error("Trailing stop activation must be greater than trailing stop distance")
    if params.trailing_stop_activation_pips > params.take_profit_pips:
        result.add_warning(
            f"Trailing stop activation ({params.trailing_stop_activation_pips} pips) exceeds take profit ({params.take_profit_pips} pips). Trailing stop may never activate."
        )

    # Signal Filter Parameters
    if not (
        MIN_CROSSOVER_THRESHOLD_PIPS <= params.crossover_threshold_pips <= MAX_CROSSOVER_THRESHOLD_PIPS
    ):
        result.add_error(
            f"Crossover threshold {params.crossover_threshold_pips} pips is outside reasonable range"
        )
    if params.crossover_threshold_pips > params.stop_loss_pips:
        result.add_warning(
            f"Crossover threshold ({params.crossover_threshold_pips} pips) exceeds stop loss ({params.stop_loss_pips} pips). This may generate very few signals."
        )

    # DMI Parameters
    if params.dmi_enabled:
        if not (MIN_DMI_PERIOD <= params.dmi_period <= MAX_DMI_PERIOD):
            result.add_error(
                f"DMI period {params.dmi_period} is outside reasonable range [{MIN_DMI_PERIOD}, {MAX_DMI_PERIOD}]"
            )

    # Stochastic Parameters
    if params.stoch_enabled:
        if not (MIN_STOCH_PERIOD <= params.stoch_period_k <= MAX_STOCH_PERIOD):
            result.add_error(
                f"Stochastic period K {params.stoch_period_k} is outside reasonable range"
            )
        if not (MIN_STOCH_PERIOD <= params.stoch_period_d <= MAX_STOCH_PERIOD):
            result.add_error(
                f"Stochastic period D {params.stoch_period_d} is outside reasonable range"
            )
        if not (MIN_STOCH_THRESHOLD <= params.stoch_bullish_threshold <= MAX_STOCH_THRESHOLD):
            result.add_error(
                f"Stochastic bullish threshold {params.stoch_bullish_threshold} is outside valid range [0, 100]"
            )
        if not (MIN_STOCH_THRESHOLD <= params.stoch_bearish_threshold <= MAX_STOCH_THRESHOLD):
            result.add_error(
                f"Stochastic bearish threshold {params.stoch_bearish_threshold} is outside valid range [0, 100]"
            )
        if params.stoch_bullish_threshold >= params.stoch_bearish_threshold:
            result.add_error("Stochastic bullish threshold must be less than bearish threshold")
        if (params.stoch_bearish_threshold - params.stoch_bullish_threshold) < 20:
            result.add_warning(
                f"Stochastic threshold range is narrow ({params.stoch_bearish_threshold - params.stoch_bullish_threshold}). This may generate frequent signals."
            )

    # Completion info
    err_diff = len(result.errors) - prev_err
    warn_diff = len(result.warnings) - prev_warn
    result.add_info(
        f"Parameter range validation completed: {err_diff} errors, {warn_diff} warnings"
    )


def validate_position_sizing(
    trade_size: int,
    stop_loss_pips: int,
    account_balance: Optional[float],
    result: ValidationResult,
) -> None:
    """Validate position size and risk relative to account balance.

    For EUR/USD, approximate pip value per unit is 0.0001 USD.
    """
    if not (MIN_TRADE_SIZE <= trade_size <= MAX_TRADE_SIZE):
        result.add_error(
            f"Trade size {trade_size} is outside reasonable range [{MIN_TRADE_SIZE}, {MAX_TRADE_SIZE}]"
        )

    risk_usd = float(trade_size) * float(stop_loss_pips) * 0.0001
    result.add_info(
        f"Risk per trade: ${risk_usd:.2f} (based on {stop_loss_pips} pip stop loss and {trade_size} units)"
    )

    if account_balance is None:
        result.add_warning(
            "Account balance not provided. Cannot validate risk percentage. Ensure position size is appropriate for your account."
        )
    else:
        if account_balance > 0:
            risk_pct = risk_usd / float(account_balance)
            if risk_pct > RECOMMENDED_MAX_RISK_PER_TRADE_PCT:
                result.add_warning(
                    f"Risk per trade ({risk_pct*100:.2f}%) exceeds recommended maximum ({RECOMMENDED_MAX_RISK_PER_TRADE_PCT*100:.1f}%). Consider reducing position size."
                )
            result.add_info(
                f"Risk per trade: {risk_pct*100:.2f}% of account balance (${account_balance:,.2f})"
            )
        else:
            result.add_warning(
                "Account balance provided is non-positive; skipping risk percentage validation."
            )

    if trade_size < 10000:
        result.add_warning(
            f"Trade size {trade_size} is less than 0.1 lot (10,000 units). Verify this is intentional for testing."
        )
    if trade_size > 1000000:
        result.add_warning(
            f"Trade size {trade_size} exceeds 10 lots (1,000,000 units). This is a large position size. Verify this is intentional."
        )


def validate_data_feed_availability(
    bar_spec: str,
    dmi_bar_spec: str,
    stoch_bar_spec: str,
    result: ValidationResult,
) -> None:
    """Heuristically validate that requested timeframes are common in IBKR live feed.

    This check is non-blocking and serves as guidance; actual availability
    depends on subscription and instrument.
    """
    common_fxs = [
        "1-MINUTE",
        "2-MINUTE",
        "3-MINUTE",
        "5-MINUTE",
        "10-MINUTE",
        "15-MINUTE",
        "30-MINUTE",
        "1-HOUR",
        "2-HOUR",
        "4-HOUR",
        "1-DAY",
    ]

    tf_primary = _extract_timeframe(bar_spec)
    tf_dmi = _extract_timeframe(dmi_bar_spec)
    tf_stoch = _extract_timeframe(stoch_bar_spec)

    if tf_primary not in common_fxs:
        result.add_warning(
            f"Primary bar spec '{bar_spec}' may not be available in IBKR live feed. Common timeframes: 1-MINUTE, 5-MINUTE, 15-MINUTE, 1-HOUR, 1-DAY."
        )
    if tf_dmi not in common_fxs:
        result.add_warning(
            f"DMI bar spec '{dmi_bar_spec}' may not be available in IBKR live feed."
        )
    if tf_stoch not in common_fxs:
        result.add_warning(
            f"Stochastic bar spec '{stoch_bar_spec}' may not be available in IBKR live feed."
        )
    result.add_info("Data feed availability check completed")


def validate_phase6_for_live(
    params: Phase6Parameters,
    symbol: str,
    venue: str,
    bar_spec: str,
    dmi_bar_spec: str,
    stoch_bar_spec: str,
    trade_size: int,
    ibkr_config: Optional[IBKRConfig] = None,
    account_balance: Optional[float] = None,
) -> ValidationResult:
    """Run all Phase 6 validation checks and return structured results.

    Parameters
    ----------
    params : Phase6Parameters
        The Phase 6 parameters to validate.
    symbol : str
        Trading symbol (e.g., 'EUR/USD').
    venue : str
        Trading venue (e.g., 'IDEALPRO').
    bar_spec : str
        Primary bar specification.
    dmi_bar_spec : str
        DMI indicator bar specification.
    stoch_bar_spec : str
        Stochastic indicator bar specification.
    trade_size : int
        Position size in units.
    ibkr_config : Optional[IBKRConfig]
        IBKR configuration for account validation.
    account_balance : Optional[float]
        Account balance for position sizing validation.

    Returns
    -------
    ValidationResult
        Structured validation results with errors, warnings, and info messages.
    """
    result = ValidationResult()
    result.add_info("Starting Phase 6 live deployment validation")

    validate_symbol_match(symbol, venue, result)
    validate_bar_spec_compatibility(bar_spec, dmi_bar_spec, stoch_bar_spec, result)
    validate_ibkr_paper_account(ibkr_config, result)
    validate_parameter_ranges(params, result)
    validate_position_sizing(trade_size, params.stop_loss_pips, account_balance, result)
    validate_data_feed_availability(bar_spec, dmi_bar_spec, stoch_bar_spec, result)

    result.add_info(
        f"Validation completed: {len(result.errors)} errors, {len(result.warnings)} warnings"
    )
    return result


def print_validation_summary(result: ValidationResult, logger: Optional[logging.Logger] = None) -> None:
    """Print a formatted validation summary and optionally log messages.

    Parameters
    ----------
    result : ValidationResult
        Validation results to display.
    logger : Optional[logging.Logger]
        If provided, messages are also emitted to the logger.
    """
    print("=== Phase 6 Deployment Validation ===")
    if result.errors:
        print("ERRORS (deployment blocked):")
        for e in result.errors:
            print(f"  ❌ {e}")
    if result.warnings:
        print("WARNINGS (review recommended):")
        for w in result.warnings:
            print(f"  ⚠️  {w}")
    if result.info_messages:
        print("INFO:")
        for i in result.info_messages:
            print(f"  ℹ️  {i}")
    if result.is_valid:
        print(f"✅ Validation PASSED (with {len(result.warnings)} warnings)")
    else:
        print(f"❌ Validation FAILED ({len(result.errors)} errors)")

    if logger is not None:
        for e in result.errors:
            logger.error(e)
        for w in result.warnings:
            logger.warning(w)
        for i in result.info_messages:
            logger.info(i)


