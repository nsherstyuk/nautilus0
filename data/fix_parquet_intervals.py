#!/usr/bin/env python3
"""
Fix Parquet interval conflicts by cleaning and re-ingesting data.

This script addresses the "Intervals are not disjoint" error by:
1. Cleaning existing overlapping Parquet data
2. Re-ingesting data with improved deduplication
3. Validating the final result

Usage:
    python data/fix_parquet_intervals.py --symbol EUR/USD
    python data/fix_parquet_intervals.py --symbol EUR/USD --clean-only
    python data/fix_parquet_intervals.py --all-symbols
"""

import asyncio
import datetime
import logging
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.cleanup_catalog import delete_all, list_catalog_datasets, delete_dataset
from data.ingest_historical import main as ingest_main
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from data.verify_catalog import collect_bar_summaries

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_catalog_data(catalog_path: str, symbol: str = None) -> bool:
    """
    Clean existing catalog data to remove interval conflicts.
    
    Args:
        catalog_path: Path to catalog directory
        symbol: Specific symbol to clean (if None, clean all)
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Cleaning catalog data at {catalog_path}")
    
    try:
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        if not summaries:
            logger.info("No existing data found to clean")
            return True
        
        # Filter by symbol if specified and delete only those datasets
        if symbol:
            # Narrow summaries to the instrument(s) matching symbol
            symbol_variants = [symbol, symbol.replace('/', '')]
            filtered = [
                s for s in summaries 
                if any(s.instrument_id.endswith(variant.split('.')[-1]) for variant in symbol_variants)
            ]
            if not filtered:
                logger.info(f"No data found for symbol {symbol}")
                return True

            deleted = 0
            for s in filtered:
                # bar_type string looks like "EURUSD.IDEALPRO-1-MINUTE-MID-EXTERNAL"; extract bar spec after instrument id
                try:
                    bar_spec = s.bar_type.split(f"{s.instrument_id}-", 1)[-1]
                except Exception:
                    # Fallback: last three/four segments as spec
                    parts = s.bar_type.split('-')
                    bar_spec = '-'.join(parts[-3:]) if len(parts) >= 3 else s.bar_type
                ok = delete_dataset(
                    catalog_path=catalog_path,
                    instrument_id=s.instrument_id,
                    bar_spec=bar_spec,
                    dry_run=False,
                )
                if ok:
                    deleted += 1
            logger.info(f"Deleted {deleted}/{len(filtered)} dataset(s) for symbol {symbol}")
            return deleted == len(filtered)

        # No symbol specified: delete all datasets as before
        logger.info(f"Found {len(summaries)} dataset(s) to clean (no symbol provided)")
        success = delete_all(
            catalog_path=catalog_path,
            confirm=True,
            dry_run=False,
        )
        if success:
            logger.info("Successfully cleaned entire catalog data")
        else:
            logger.error("Failed to clean entire catalog data")
        return success
        
    except Exception as e:
        logger.error(f"Error cleaning catalog data: {e}")
        return False


def validate_catalog_intervals(catalog_path: str) -> bool:
    """
    Validate that catalog has no interval conflicts.
    
    Args:
        catalog_path: Path to catalog directory
        
    Returns:
        True if valid, False if conflicts found
    """
    logger.info("Validating catalog intervals...")
    
    try:
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        if not summaries:
            logger.info("No data in catalog to validate")
            return True
        
        # Check for overlapping intervals within each bar type
        bar_types = {}
        for summary in summaries:
            bar_type = summary.bar_type
            if bar_type not in bar_types:
                bar_types[bar_type] = []
            bar_types[bar_type].append(summary)
        
        conflicts_found = False
        for bar_type, type_summaries in bar_types.items():
            if len(type_summaries) > 1:
                # Sort by start time
                type_summaries.sort(key=lambda x: x.start_ts or 0)
                
                # Check for overlaps
                for i in range(len(type_summaries) - 1):
                    current = type_summaries[i]
                    next_summary = type_summaries[i + 1]
                    
                    if current.end_ts and next_summary.start_ts and current.end_ts >= next_summary.start_ts:
                        logger.error(f"Interval conflict in {bar_type}: {current.start_ts} to {current.end_ts} overlaps with {next_summary.start_ts} to {next_summary.end_ts}")
                        conflicts_found = True
        
        if not conflicts_found:
            logger.info("No interval conflicts found - catalog is valid")
        else:
            logger.error("Interval conflicts detected - catalog needs cleaning")
            
        return not conflicts_found
        
    except Exception as e:
        logger.error(f"Error validating catalog: {e}")
        return False


async def re_ingest_data(symbol: str) -> bool:
    """
    Re-ingest data for a specific symbol.
    
    Args:
        symbol: Symbol to re-ingest
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Re-ingesting data for {symbol}")
    
    try:
        # Set environment variables for the symbol
        os.environ["DATA_SYMBOLS"] = symbol
        
        # Run the ingestion process; pass empty argv to avoid parsing global argv from this script
        result = await ingest_main([])
        
        if result == 0:
            logger.info(f"Successfully re-ingested data for {symbol}")
            return True
        else:
            logger.error(f"Failed to re-ingest data for {symbol}")
            return False
            
    except Exception as e:
        logger.error(f"Error re-ingesting data for {symbol}: {e}")
        return False


def main():
    """Main function to handle command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix Parquet interval conflicts by cleaning and re-ingesting data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix specific symbol
  python data/fix_parquet_intervals.py --symbol EUR/USD
  
  # Clean only (don't re-ingest)
  python data/fix_parquet_intervals.py --symbol EUR/USD --clean-only
  
  # Fix all symbols
  python data/fix_parquet_intervals.py --all-symbols
  
  # Validate catalog only
  python data/fix_parquet_intervals.py --validate-only
        """
    )
    
    parser.add_argument(
        "--catalog-path",
        default="data/historical",
        help="Path to catalog directory (default: data/historical)"
    )
    
    parser.add_argument(
        "--symbol",
        help="Specific symbol to fix (e.g., EUR/USD)"
    )
    
    parser.add_argument(
        "--all-symbols",
        action="store_true",
        help="Fix all symbols in the catalog"
    )
    
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean existing data, don't re-ingest"
    )
    
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate catalog intervals, don't clean or re-ingest"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.symbol and not args.all_symbols and not args.validate_only:
        logger.error("Must specify --symbol, --all-symbols, or --validate-only")
        return 1
    
    if args.symbol and args.all_symbols:
        logger.error("Cannot specify both --symbol and --all-symbols")
        return 1
    
    catalog_path = args.catalog_path
    
    # Validate catalog path exists
    if not Path(catalog_path).exists():
        logger.error(f"Catalog path does not exist: {catalog_path}")
        return 1
    
    # Step 1: Validate current state
    logger.info("Step 1: Validating current catalog state...")
    is_valid = validate_catalog_intervals(catalog_path)
    
    if args.validate_only:
        return 0 if is_valid else 1
    
    if is_valid:
        logger.info("Catalog is already valid - no action needed")
        return 0
    
    # Step 2: Clean existing data
    logger.info("Step 2: Cleaning existing data...")
    if args.symbol:
        success = clean_catalog_data(catalog_path, args.symbol)
    else:
        success = clean_catalog_data(catalog_path)
    
    if not success:
        logger.error("Failed to clean catalog data")
        return 1
    
    if args.clean_only:
        logger.info("Clean-only mode: skipping re-ingestion")
        return 0
    
    # Step 3: Re-ingest data
    logger.info("Step 3: Re-ingesting data...")
    
    if args.symbol:
        # Re-ingest specific symbol
        success = asyncio.run(re_ingest_data(args.symbol))
        if not success:
            logger.error(f"Failed to re-ingest {args.symbol}")
            return 1
    else:
        # Re-ingest all symbols
        symbols_str = os.getenv("DATA_SYMBOLS", "EUR/USD")
        symbols = [s.strip() for s in symbols_str.split(",")]
        
        for symbol in symbols:
            success = asyncio.run(re_ingest_data(symbol))
            if not success:
                logger.error(f"Failed to re-ingest {symbol}")
                return 1
    
    # Step 4: Final validation
    logger.info("Step 4: Final validation...")
    is_valid = validate_catalog_intervals(catalog_path)
    
    if is_valid:
        logger.info("✅ Successfully fixed Parquet interval conflicts!")
        return 0
    else:
        logger.error("❌ Interval conflicts still exist after fix attempt")
        return 1


if __name__ == "__main__":
    sys.exit(main())
