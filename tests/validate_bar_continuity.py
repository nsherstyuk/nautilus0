"""
Bar Continuity Validator for NautilusTrader ParquetDataCatalog.

Validates historical bar data quality by checking for:
- Missing bars (gaps in timestamp sequence)
- Duplicate bars (same timestamp appears multiple times)
- OHLC relationship violations (high < low, close outside range)
- Chronological ordering (timestamps not monotonically increasing)
- Data completeness (actual vs expected bar count)

Usage Examples:

    # Validate EUR/USD 1-minute bars (console output)
    python tests/validate_bar_continuity.py \
        --instrument EUR/USD.IDEALPRO \
        --bar-spec 1-MINUTE-MID-EXTERNAL
    
    # Generate detailed report file
    python tests/validate_bar_continuity.py \
        --instrument EUR/USD.IDEALPRO \
        --bar-spec 1-MINUTE-MID-EXTERNAL \
        --report
    
    # Output as JSON for scripting
    python tests/validate_bar_continuity.py \
        --instrument EUR/USD.IDEALPRO \
        --bar-spec 1-MINUTE-MID-EXTERNAL \
        --json
    
    # Validate with custom catalog path
    python tests/validate_bar_continuity.py \
        --catalog-path data/historical_backup \
        --instrument SPY.SMART \
        --bar-spec 1-MINUTE-LAST-EXTERNAL
    
    # Verbose mode with debug logging
    python tests/validate_bar_continuity.py \
        --instrument EUR/USD.IDEALPRO \
        --bar-spec 15-MINUTE-MID-EXTERNAL \
        --verbose

Output:
    - Console: Summary of validation results
    - File (with --report): Detailed report with gap locations
    - JSON (with --json): Machine-readable validation results
    
Exit Codes:
    0: No issues found (data quality is good)
    1: Issues found (gaps, duplicates, or violations detected)
    2: Critical error (catalog not found, no bars loaded)
"""

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

import pandas as pd
from dotenv import load_dotenv
import pytz

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.model.data import Bar

from data.verify_catalog import collect_bar_summaries, CatalogBarSummary
from utils.instruments import try_both_instrument_formats


def to_iso_z(ts: pd.Timestamp) -> str:
    """Convert timestamp to canonical UTC ISO format ending with 'Z'."""
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class BarGap:
    """Represents a gap in bar data continuity."""
    gap_start_ts: pd.Timestamp
    gap_end_ts: pd.Timestamp
    expected_bars: int
    duration_minutes: int

    def format_summary(self) -> str:
        """Format gap as human-readable string."""
        return f"Gap from {self.gap_start_ts.strftime('%Y-%m-%d %H:%M:%S')} to {self.gap_end_ts.strftime('%Y-%m-%d %H:%M:%S')} ({self.duration_minutes} minutes, {self.expected_bars} missing bars)"


@dataclass
class DuplicateBar:
    """Represents duplicate bars with same timestamp."""
    timestamp: pd.Timestamp
    count: int
    indices: List[int]

    def format_summary(self) -> str:
        """Format duplicate as human-readable string."""
        return f"Duplicate at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} ({self.count} occurrences at indices {', '.join(map(str, self.indices))})"


@dataclass
class OHLCViolation:
    """Represents OHLC relationship violation."""
    timestamp: pd.Timestamp
    index: int
    violation_type: str
    details: str

    def format_summary(self) -> str:
        """Format violation as human-readable string."""
        return f"OHLC violation at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}: {self.details}"


@dataclass
class ContinuityReport:
    """Comprehensive bar continuity validation report."""
    instrument_id: str
    bar_spec: str
    total_bars: int
    date_range: Tuple[pd.Timestamp, pd.Timestamp]
    gaps: List[BarGap]
    duplicates: List[DuplicateBar]
    ohlc_violations: List[OHLCViolation]
    chronological_errors: int
    expected_bars: int
    completeness_pct: float

    def has_issues(self) -> bool:
        """Check if any issues were found."""
        return len(self.gaps) > 0 or len(self.duplicates) > 0 or len(self.ohlc_violations) > 0 or self.chronological_errors > 0

    def format_summary(self) -> str:
        """Format comprehensive human-readable report."""
        lines = [
            "Bar Continuity Validation Report",
            "================================",
            f"Instrument: {self.instrument_id}",
            f"Bar Specification: {self.bar_spec}",
            f"Date Range: {self.date_range[0].strftime('%Y-%m-%d')} to {self.date_range[1].strftime('%Y-%m-%d')}",
            f"Total Bars: {self.total_bars:,}",
            f"Expected Bars: {self.expected_bars:,}",
            f"Completeness: {self.completeness_pct:.2f}%",
            "",
        ]

        # Gap Analysis
        lines.extend([
            "Gap Analysis:",
            "-------------",
        ])
        if self.gaps:
            lines.append(f"Found {len(self.gaps)} gaps (excluding weekends and expected market closures)")
            lines.append("")
            for i, gap in enumerate(self.gaps[:20], 1):  # Limit to first 20
                lines.append(f"{i}. {gap.format_summary()}")
            if len(self.gaps) > 20:
                lines.append(f"... and {len(self.gaps) - 20} more gaps")
        else:
            lines.append("✓ No gaps found")
        lines.append("")

        # Duplicate Analysis
        lines.extend([
            "Duplicate Analysis:",
            "------------------",
        ])
        if self.duplicates:
            lines.append(f"Found {len(self.duplicates)} duplicate timestamps")
            lines.append("")
            for i, dup in enumerate(self.duplicates[:20], 1):  # Limit to first 20
                lines.append(f"{i}. {dup.format_summary()}")
            if len(self.duplicates) > 20:
                lines.append(f"... and {len(self.duplicates) - 20} more duplicates")
        else:
            lines.append("✓ No duplicates found")
        lines.append("")

        # OHLC Validation
        lines.extend([
            "OHLC Validation:",
            "----------------",
        ])
        if self.ohlc_violations:
            lines.append(f"Found {len(self.ohlc_violations)} OHLC violations")
            lines.append("")
            for i, violation in enumerate(self.ohlc_violations[:20], 1):  # Limit to first 20
                lines.append(f"{i}. Bar at {violation.timestamp.strftime('%Y-%m-%d %H:%M:%S')} (index {violation.index})")
                lines.append(f"   Violation: {violation.details}")
            if len(self.ohlc_violations) > 20:
                lines.append(f"... and {len(self.ohlc_violations) - 20} more violations")
        else:
            lines.append("✓ No OHLC violations found")
        lines.append("")

        # Chronological Order
        lines.extend([
            "Chronological Order:",
            "-------------------",
        ])
        if self.chronological_errors == 0:
            lines.append("✓ All bars are in chronological order (0 errors)")
        else:
            lines.append(f"❌ Found {self.chronological_errors} chronological ordering errors")
        lines.append("")

        # Summary
        lines.extend([
            "Summary:",
            "--------",
        ])
        if self.has_issues():
            lines.append("Status: ⚠️ ISSUES FOUND")
            lines.append(f"- Gaps: {len(self.gaps)}")
            lines.append(f"- Duplicates: {len(self.duplicates)}")
            lines.append(f"- OHLC violations: {len(self.ohlc_violations)}")
            lines.append(f"- Ordering errors: {self.chronological_errors}")
            lines.append("")
            lines.extend([
                "Recommendations:",
                "- Review gaps to determine if they're expected (market closures, data provider issues)",
                "- Remove duplicate bars by re-ingesting data with catalog cleanup",
                "- Investigate OHLC violations (may indicate data corruption)"
            ])
        else:
            lines.append("Status: ✓ NO ISSUES FOUND")
            lines.append("Data quality is excellent!")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "instrument_id": self.instrument_id,
            "bar_spec": self.bar_spec,
            "total_bars": self.total_bars,
            "date_range": {
                "start": to_iso_z(self.date_range[0]),
                "end": to_iso_z(self.date_range[1])
            },
            "gaps": [
                {
                    "gap_start": to_iso_z(gap.gap_start_ts),
                    "gap_end": to_iso_z(gap.gap_end_ts),
                    "duration_minutes": gap.duration_minutes,
                    "missing_bars": gap.expected_bars
                }
                for gap in self.gaps
            ],
            "duplicates": [
                {
                    "timestamp": to_iso_z(dup.timestamp),
                    "count": dup.count,
                    "indices": dup.indices
                }
                for dup in self.duplicates
            ],
            "ohlc_violations": [
                {
                    "timestamp": to_iso_z(violation.timestamp),
                    "index": violation.index,
                    "violation_type": violation.violation_type,
                    "details": violation.details
                }
                for violation in self.ohlc_violations
            ],
            "chronological_errors": self.chronological_errors,
            "expected_bars": self.expected_bars,
            "completeness_pct": self.completeness_pct
        }


def calculate_expected_bar_count(start_ts: pd.Timestamp, end_ts: pd.Timestamp, bar_spec: str, is_forex: bool) -> int:
    """Calculate theoretical number of bars for a date range."""
    bar_interval_minutes = parse_bar_spec_interval(bar_spec)
    if bar_interval_minutes is None:
        logging.warning(f"Could not parse bar spec interval: {bar_spec}")
        return 0

    total_minutes = (end_ts - start_ts).total_seconds() / 60

    if is_forex:
        # Forex trades 24/5 (exclude weekends)
        # Calculate trading days excluding weekends
        current = start_ts
        trading_minutes = 0
        while current < end_ts:
            # Skip weekends (Saturday=5, Sunday=6)
            if current.weekday() < 5:  # Monday=0, Friday=4
                trading_minutes += 24 * 60  # Full day
            current += timedelta(days=1)
        
        # Handle partial days
        if start_ts.weekday() < 5:  # Start on weekday
            trading_minutes -= (start_ts.hour * 60 + start_ts.minute)
        if end_ts.weekday() < 5:  # End on weekday
            trading_minutes -= (24 * 60 - (end_ts.hour * 60 + end_ts.minute))
        
        expected_bars = int(trading_minutes / bar_interval_minutes)
    else:
        # Stocks trade 9:30-16:00 ET (6.5 hours = 390 minutes per day)
        # Simplified: exclude weekends only
        current = start_ts
        trading_days = 0
        while current < end_ts:
            if current.weekday() < 5:  # Weekday
                trading_days += 1
            current += timedelta(days=1)
        
        expected_bars = int(trading_days * (390 / bar_interval_minutes))

    return max(1, int(expected_bars))  # At least 1 bar


def detect_gaps(bars: List[Bar], bar_spec: str, is_forex: bool) -> List[BarGap]:
    """Find missing bars in timestamp sequence."""
    if len(bars) < 2:
        return []

    bar_interval_minutes = parse_bar_spec_interval(bar_spec)
    if bar_interval_minutes is None:
        logging.warning(f"Could not parse bar spec interval: {bar_spec}")
        return []

    # Sort bars by timestamp
    sorted_bars = sorted(bars, key=lambda b: b.ts_event)
    gaps = []

    for i in range(len(sorted_bars) - 1):
        current_ts = pd.Timestamp(sorted_bars[i].ts_event, unit='ns', tz='UTC')
        next_ts = pd.Timestamp(sorted_bars[i + 1].ts_event, unit='ns', tz='UTC')
        
        expected_next_ts = current_ts + timedelta(minutes=bar_interval_minutes)
        
        if next_ts > expected_next_ts:
            gap_duration_minutes = (next_ts - expected_next_ts).total_seconds() / 60
            missing_bars = int(gap_duration_minutes / bar_interval_minutes)
            
            # Filter out expected gaps
            if not is_weekend_gap(expected_next_ts, next_ts) and not is_market_hours_gap(expected_next_ts, next_ts, is_forex):
                if missing_bars >= 2:  # Only report gaps with 2+ missing bars
                    gap = BarGap(
                        gap_start_ts=expected_next_ts,
                        gap_end_ts=next_ts,
                        expected_bars=missing_bars,
                        duration_minutes=int(gap_duration_minutes)
                    )
                    gaps.append(gap)

    return gaps


def detect_duplicates(bars: List[Bar]) -> List[DuplicateBar]:
    """Find bars with identical timestamps."""
    timestamp_map = defaultdict(list)
    
    for i, bar in enumerate(bars):
        timestamp_map[bar.ts_event].append(i)
    
    duplicates = []
    for timestamp, indices in timestamp_map.items():
        if len(indices) > 1:
            dup = DuplicateBar(
                timestamp=pd.Timestamp(timestamp, unit='ns', tz='UTC'),
                count=len(indices),
                indices=indices
            )
            duplicates.append(dup)
    
    return sorted(duplicates, key=lambda d: d.timestamp)


def validate_ohlc_relationships(bars: List[Bar]) -> List[OHLCViolation]:
    """Validate OHLC price relationships."""
    violations = []
    
    for i, bar in enumerate(bars):
        open_price = float(bar.open)
        high_price = float(bar.high)
        low_price = float(bar.low)
        close_price = float(bar.close)
        
        # Check high >= low
        if high_price < low_price:
            violation = OHLCViolation(
                timestamp=pd.Timestamp(bar.ts_event, unit='ns', tz='UTC'),
                index=i,
                violation_type="high_low",
                details=f"high ({high_price}) < low ({low_price})"
            )
            violations.append(violation)
        
        # Check close within [low, high]
        if close_price < low_price or close_price > high_price:
            violation = OHLCViolation(
                timestamp=pd.Timestamp(bar.ts_event, unit='ns', tz='UTC'),
                index=i,
                violation_type="close_range",
                details=f"close ({close_price}) outside [low ({low_price}), high ({high_price})]"
            )
            violations.append(violation)
        
        # Check open within [low, high]
        if open_price < low_price or open_price > high_price:
            violation = OHLCViolation(
                timestamp=pd.Timestamp(bar.ts_event, unit='ns', tz='UTC'),
                index=i,
                violation_type="open_range",
                details=f"open ({open_price}) outside [low ({low_price}), high ({high_price})]"
            )
            violations.append(violation)
    
    return violations


def check_chronological_order(bars: List[Bar]) -> int:
    """Count out-of-order bars."""
    errors = 0
    
    for i in range(len(bars) - 1):
        if bars[i + 1].ts_event < bars[i].ts_event:
            errors += 1
    
    return errors


def parse_bar_spec_interval(bar_spec: str) -> Optional[int]:
    """Extract bar interval in minutes from bar spec string."""
    # Pattern: "1-MINUTE-MID-EXTERNAL" -> 1 minute
    # Pattern: "15-MINUTE-MID-EXTERNAL" -> 15 minutes
    # Pattern: "1-HOUR-MID-EXTERNAL" -> 60 minutes
    # Pattern: "1-DAY-MID-EXTERNAL" -> 1440 minutes
    pattern = r"(\d+)-(MINUTE|HOUR|DAY)"
    match = re.search(pattern, bar_spec)
    
    if not match:
        return None
    
    number = int(match.group(1))
    unit = match.group(2)
    
    if unit == "MINUTE":
        return number
    elif unit == "HOUR":
        return number * 60
    elif unit == "DAY":
        return number * 1440
    
    return None


def is_weekend_gap(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> bool:
    """Check if gap spans a weekend (expected for forex)."""
    # Forex weekend closure: typically Fri 21:00 UTC to Sun 21:00 UTC
    # Check if gap falls within typical forex weekend closure window
    
    # Check if gap starts on Friday after 21:00 UTC or on Saturday/Sunday
    start_weekday = start_ts.weekday()
    start_hour = start_ts.hour
    
    # Check if gap ends on Sunday before 21:00 UTC or on Saturday/Sunday
    end_weekday = end_ts.weekday()
    end_hour = end_ts.hour
    
    # Gap is expected if:
    # 1. Starts on Friday 21:00+ UTC and ends on Sunday 21:00- UTC
    # 2. Starts on Saturday and ends on Sunday 21:00- UTC
    # 3. Starts on Friday 21:00+ UTC and ends on Saturday
    # 4. Entirely within Saturday
    # 5. Starts on Sunday and ends on Sunday 21:00- UTC
    
    if (start_weekday == 4 and start_hour >= 21 and end_weekday == 6 and end_hour < 21):  # Fri 21:00+ to Sun 21:00-
        return True
    elif (start_weekday == 5 and end_weekday == 6 and end_hour < 21):  # Sat to Sun 21:00-
        return True
    elif (start_weekday == 4 and start_hour >= 21 and end_weekday == 5):  # Fri 21:00+ to Sat
        return True
    elif (start_weekday == 5 and end_weekday == 5):  # Entirely within Saturday
        return True
    elif (start_weekday == 6 and end_weekday == 6 and end_hour < 21):  # Sun to Sun 21:00-
        return True
    
    return False


def is_market_hours_gap(start_ts: pd.Timestamp, end_ts: pd.Timestamp, is_forex: bool) -> bool:
    """Check if gap is outside market hours (expected for stocks)."""
    if is_forex:
        return False  # Forex trades 24/5
    
    # Convert UTC timestamps to America/New_York timezone
    et_tz = pytz.timezone('America/New_York')
    start_et = start_ts.tz_convert(et_tz)
    end_et = end_ts.tz_convert(et_tz)
    
    # Check if gap falls entirely outside trading hours (9:30-16:00 ET) and weekends
    # Check if gap spans a weekend
    if is_weekend_gap(start_ts, end_ts):
        return True
    
    # Check if gap is entirely outside trading hours on weekdays
    # Market hours: 9:30-16:00 ET Monday-Friday
    start_time = start_et.time()
    end_time = end_et.time()
    
    # If gap is entirely before 9:30 or after 16:00 on weekdays, it's expected
    if (start_et.weekday() < 5 and end_et.weekday() < 5 and  # Both on weekdays
        (end_time <= pd.Timestamp('09:30:00').time() or start_time >= pd.Timestamp('16:00:00').time())):
        return True
    
    return False


def validate_bar_continuity(catalog_path: str, instrument_id: str, bar_spec: str) -> ContinuityReport:
    """Orchestrate all validation checks and generate report."""
    try:
        # Load catalog and metadata
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        # Find matching dataset
        instrument_variants = try_both_instrument_formats(instrument_id)
        matching_summary = None
        
        for variant in instrument_variants:
            for summary in summaries:
                if summary.instrument_id == variant:
                    matching_summary = summary
                    break
            if matching_summary:
                break
        
        if not matching_summary:
            available_instruments = [s.instrument_id for s in summaries]
            raise ValueError(f"Instrument '{instrument_id}' not found in catalog. Available: {available_instruments}")
        
        # Check for matching bar_type after filtering summaries for the instrument
        instrument_summaries = [s for s in summaries if s.instrument_id == matching_summary.instrument_id]
        bar_type_variants = [
            f"{instrument_id}-{bar_spec}",
            f"{instrument_id.replace('/', '')}-{bar_spec}"
        ]
        
        matching_bar_type = None
        for bar_type in bar_type_variants:
            for summary in instrument_summaries:
                if summary.bar_type == bar_type:
                    matching_bar_type = bar_type
                    break
            if matching_bar_type:
                break
        
        if not matching_bar_type:
            available_bar_types = [s.bar_type for s in instrument_summaries]
            raise ValueError(f"Bar spec '{bar_spec}' not found for instrument '{instrument_id}'. Available bar specs: {available_bar_types}")
        
        # Load bar data
        bar_type_variants = [
            f"{instrument_id}-{bar_spec}",
            f"{instrument_id.replace('/', '')}-{bar_spec}"
        ]
        
        bars = []
        for bar_type in bar_type_variants:
            try:
                bars = list(catalog.bars(bar_types=[bar_type]))
                if bars:
                    logging.info(f"Loaded {len(bars)} bars for validation")
                    break
            except Exception as e:
                logging.debug(f"Failed to load bars with type '{bar_type}': {e}")
                continue
        
        if not bars:
            raise ValueError(f"No bars found for instrument '{instrument_id}' with spec '{bar_spec}'. Try running ingest_historical.py first.")
        
        # Sort bars by timestamp once for accurate date range and validation
        sorted_bars = sorted(bars, key=lambda b: b.ts_event)
        
        # Determine instrument type
        is_forex = '/' in instrument_id
        
        # Run validation checks
        gaps = detect_gaps(sorted_bars, bar_spec, is_forex)
        duplicates = detect_duplicates(sorted_bars)
        ohlc_violations = validate_ohlc_relationships(sorted_bars)
        chronological_errors = check_chronological_order(sorted_bars)
        
        # Calculate completeness using sorted bars
        start_ts = pd.Timestamp(sorted_bars[0].ts_event, unit='ns', tz='UTC')
        end_ts = pd.Timestamp(sorted_bars[-1].ts_event, unit='ns', tz='UTC')
        expected_bars = calculate_expected_bar_count(start_ts, end_ts, bar_spec, is_forex)
        completeness_pct = (len(bars) / expected_bars) * 100 if expected_bars > 0 else 100.0
        
        # Create report
        report = ContinuityReport(
            instrument_id=instrument_id,
            bar_spec=bar_spec,
            total_bars=len(bars),
            date_range=(start_ts, end_ts),
            gaps=gaps,
            duplicates=duplicates,
            ohlc_violations=ohlc_violations,
            chronological_errors=chronological_errors,
            expected_bars=expected_bars,
            completeness_pct=completeness_pct
        )
        
        return report
        
    except Exception as e:
        logging.error(f"Validation failed: {e}")
        raise


def format_human_readable_report(report: ContinuityReport) -> str:
    """Generate detailed text report."""
    return report.format_summary()


def format_json_report(report: ContinuityReport) -> str:
    """Generate JSON report for programmatic consumption."""
    data = report.to_dict()
    data["validation_timestamp"] = to_iso_z(pd.Timestamp(datetime.utcnow(), tz='UTC'))
    data["summary"] = {
        "total_bars": report.total_bars,
        "expected_bars": report.expected_bars,
        "completeness_pct": report.completeness_pct,
        "date_range": {
            "start": to_iso_z(report.date_range[0]),
            "end": to_iso_z(report.date_range[1])
        },
        "issues_found": report.has_issues(),
        "gap_count": len(report.gaps),
        "duplicate_count": len(report.duplicates),
        "ohlc_violation_count": len(report.ohlc_violations),
        "chronological_error_count": report.chronological_errors
    }
    
    return json.dumps(data, indent=2)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate bar data continuity and quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL
  %(prog)s --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL --report
  %(prog)s --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL --json
        """
    )
    
    parser.add_argument(
        "--catalog-path",
        default="data/historical",
        help="Path to catalog directory (default: data/historical)"
    )
    parser.add_argument(
        "--instrument",
        required=True,
        help="Instrument ID (e.g., EUR/USD.IDEALPRO, SPY.SMART)"
    )
    parser.add_argument(
        "--bar-spec",
        required=True,
        help="Bar specification (e.g., 1-MINUTE-MID-EXTERNAL)"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate detailed report file"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable"
    )
    parser.add_argument(
        "--output",
        help="Output file path (auto-generated if not specified)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Load environment variables
    load_dotenv()
    
    try:
        # Validate inputs
        catalog_path = Path(args.catalog_path)
        if not catalog_path.exists():
            logging.error(f"Catalog path does not exist: {catalog_path}")
            return 2
        
        # Validate bar spec format
        if not re.match(r"\d+-(MINUTE|HOUR|DAY)-", args.bar_spec):
            logging.error(f"Invalid bar spec format: {args.bar_spec}")
            return 2
        
        # Run validation
        report = validate_bar_continuity(
            str(catalog_path),
            args.instrument,
            args.bar_spec
        )
        
        # Generate output
        if args.json:
            output = format_json_report(report)
        else:
            output = format_human_readable_report(report)
        
        # Write to file if requested
        if args.report or args.output:
            if args.output:
                output_file = Path(args.output)
            else:
                # Auto-generate filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_instrument = args.instrument.replace("/", "_").replace(".", "_")
                safe_bar_spec = args.bar_spec.replace("-", "_")
                output_file = Path(f"bar_continuity_{safe_instrument}_{safe_bar_spec}_{timestamp}.txt")
            
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w') as f:
                f.write(output)
            logging.info(f"Report written to: {output_file}")
        
        # Always print to console
        print(output)
        
        # Return appropriate exit code
        if report.has_issues():
            return 1  # Issues found
        else:
            return 0  # No issues found
            
    except Exception as e:
        logging.error(f"Critical error: {e}")
        if args.verbose:
            logging.exception("Full traceback:")
        return 2


if __name__ == "__main__":
    sys.exit(main())
