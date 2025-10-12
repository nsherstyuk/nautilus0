#!/usr/bin/env python3
"""
Catalog cleanup utility for removing overlapping data.

This script helps resolve Parquet catalog conflicts by removing
overlapping datasets that prevent new data ingestion.
"""

import sys
from pathlib import Path
import shutil
import logging

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.verify_catalog import collect_bar_summaries
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from utils.instruments import (
    try_both_instrument_formats,
    instrument_id_to_catalog_format,
    catalog_format_to_instrument_id,
)

# Module-level logger
logger = None

def setup_logging():
    """Setup basic logging for the cleanup script."""
    global logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    return logger


def calculate_directory_size(directory: Path) -> int:
    """Calculate total size of all files in a directory tree.
    
    Args:
        directory: Path to directory
        
    Returns:
        Total size in bytes
    """
    total_size = 0
    try:
        for item in directory.rglob('*'):
            if item.is_file():
                total_size += item.stat().st_size
    except Exception as e:
        if logger:
            logger.warning(f"Error calculating size for {directory}: {e}")
    return total_size

def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string like "1.23 MB" or "456.78 KB"
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def list_catalog_datasets(catalog_path: str, instrument_filter: str = None, bar_spec_filter: str = None) -> bool:
    """List all datasets in the catalog with details.
    
    Args:
        catalog_path: Path to the catalog directory
        instrument_filter: Optional instrument ID filter (supports both slashed/no-slash)
        bar_spec_filter: Optional bar specification filter (e.g., "1-MINUTE-MID-EXTERNAL")
        
    Returns:
        True if successful, False otherwise
    """
    catalog_dir = Path(catalog_path)
    
    if not catalog_dir.exists():
        logger.error(f"Catalog directory does not exist: {catalog_dir}")
        return False
    
    try:
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        if not summaries:
            logger.info("No datasets found in catalog.")
            return True
        
        # Apply instrument filter if specified
        if instrument_filter:
            # Try both slashed and no-slash formats
            format_variants = try_both_instrument_formats(instrument_filter)
            # Enhanced matching with normalized form
            summaries = [
                s for s in summaries 
                if s.instrument_id in format_variants or 
                   any(s.instrument_id.endswith(variant.split('.')[-1]) for variant in format_variants)
            ]
            if not summaries:
                logger.info(f"No datasets found for instrument {instrument_filter}")
                return True
        
        # Apply bar spec filter if specified - use exact match
        if bar_spec_filter:
            summaries = [
                s for s in summaries 
                if s.bar_type.endswith(bar_spec_filter)
            ]
            if not summaries:
                logger.info(f"No datasets found matching bar spec {bar_spec_filter}")
                return True
        
        # Group by instrument for organized display
        instruments = {}
        for summary in summaries:
            inst_id = summary.instrument_id
            if inst_id not in instruments:
                instruments[inst_id] = []
            instruments[inst_id].append(summary)
        
        # Display results
        logger.info(f"\nFound {len(summaries)} dataset(s) in catalog:")
        logger.info("=" * 80)
        
        total_bars = 0
        total_size = 0
        
        # Cache directory sizes to avoid double scanning
        size_cache = {}
        
        for inst_id, datasets in sorted(instruments.items()):
            logger.info(f"\nInstrument: {inst_id}")
            logger.info("-" * 80)
            
            for dataset in datasets:
                bar_type_str = dataset.bar_type
                dataset_path = catalog_dir / "data" / "bar" / bar_type_str
                
                # Calculate dataset size (use cache to avoid double scanning)
                dataset_size = 0
                if dataset_path.exists():
                    if bar_type_str not in size_cache:
                        size_cache[bar_type_str] = calculate_directory_size(dataset_path)
                    dataset_size = size_cache[bar_type_str]
                    total_size += dataset_size
                
                total_bars += dataset.bar_count
                
                # Format date range
                date_range = "N/A"
                if dataset.start_ts and dataset.end_ts:
                    date_range = f"{dataset.start_ts.date()} to {dataset.end_ts.date()}"
                
                logger.info(
                    f"  Bar Type: {bar_type_str}\n"
                    f"    Bars: {dataset.bar_count:,}\n"
                    f"    Date Range: {date_range}\n"
                    f"    Disk Size: {format_size(dataset_size)}\n"
                    f"    Path: {dataset_path}"
                )
        
        logger.info("\n" + "=" * 80)
        logger.info(f"Total: {len(summaries)} dataset(s), {total_bars:,} bars, {format_size(total_size)} disk space")
        
        return True
        
    except Exception as e:
        logger.error(f"Error listing catalog datasets: {e}")
        return False


def delete_dataset(
    catalog_path: str, 
    instrument_id: str, 
    bar_spec: str, 
    dry_run: bool = True
) -> bool:
    """Delete a specific dataset by instrument ID and bar specification.
    
    Args:
        catalog_path: Path to the catalog directory
        instrument_id: Instrument ID (supports both slashed/no-slash formats)
        bar_spec: Bar specification (e.g., "1-MINUTE-MID-EXTERNAL")
        dry_run: If True, only show what would be deleted
        
    Returns:
        True if successful, False otherwise
    """
    catalog_dir = Path(catalog_path)
    
    if not catalog_dir.exists():
        logger.error(f"Catalog directory does not exist: {catalog_dir}")
        return False
    
    try:
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        if not summaries:
            logger.info("No datasets found in catalog.")
            return True
        
        # Try both format variants for instrument ID
        format_variants = try_both_instrument_formats(instrument_id)
        
        # Find matching datasets with exact bar spec match
        matching_datasets = [
            s for s in summaries 
            if s.instrument_id in format_variants and s.bar_type.endswith(bar_spec)
        ]
        
        if not matching_datasets:
            logger.warning(
                f"No datasets found matching instrument={instrument_id} and bar_spec={bar_spec}\n"
                f"Tried format variants: {format_variants}"
            )
            return False
        
        # Delete matching datasets
        deleted_count = 0
        total_size_freed = 0
        
        # Cache sizes to avoid double scanning
        size_cache = {}
        
        for dataset in matching_datasets:
            bar_type_str = dataset.bar_type
            dataset_path = catalog_dir / "data" / "bar" / bar_type_str
            
            if not dataset_path.exists():
                logger.warning(f"Dataset path does not exist: {dataset_path}")
                continue
            
            # Calculate size before deletion (use cache)
            if bar_type_str not in size_cache:
                size_cache[bar_type_str] = calculate_directory_size(dataset_path)
            dataset_size = size_cache[bar_type_str]
            total_size_freed += dataset_size
            
            if dry_run:
                logger.info(f"[DRY RUN] Would delete: {dataset_path}")
                logger.info(
                    f"  - {dataset.bar_count:,} bars from {dataset.start_ts.date() if dataset.start_ts else 'N/A'} "
                    f"to {dataset.end_ts.date() if dataset.end_ts else 'N/A'}\n"
                    f"  - Disk space: {format_size(dataset_size)}"
                )
            else:
                try:
                    shutil.rmtree(dataset_path)
                    logger.info(f"Deleted: {dataset_path}")
                    logger.info(
                        f"  - {dataset.bar_count:,} bars from {dataset.start_ts.date() if dataset.start_ts else 'N/A'} "
                        f"to {dataset.end_ts.date() if dataset.end_ts else 'N/A'}\n"
                        f"  - Freed disk space: {format_size(dataset_size)}"
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {dataset_path}: {e}")
        
        if dry_run:
            logger.info(
                f"\n[DRY RUN] Would delete {len(matching_datasets)} dataset(s), "
                f"freeing {format_size(total_size_freed)}\n"
                f"Run without --dry-run to execute deletion"
            )
        else:
            logger.info(
                f"\nSuccessfully deleted {deleted_count}/{len(matching_datasets)} dataset(s), "
                f"freed {format_size(total_size_freed)}"
            )
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting dataset: {e}")
        return False


def delete_all(catalog_path: str, confirm: bool = False, dry_run: bool = True) -> bool:
    """Delete all datasets in the catalog.
    
    Args:
        catalog_path: Path to the catalog directory
        confirm: If True, skip interactive confirmation prompt
        dry_run: If True, only show what would be deleted
        
    Returns:
        True if successful, False otherwise
    """
    catalog_dir = Path(catalog_path)
    
    if not catalog_dir.exists():
        logger.error(f"Catalog directory does not exist: {catalog_dir}")
        return False
    
    try:
        catalog = ParquetDataCatalog(catalog_path)
        summaries = collect_bar_summaries(catalog)
        
        if not summaries:
            logger.info("No datasets found in catalog.")
            return True
        
        # Calculate total impact with optimized size calculation
        total_bars = sum(s.bar_count for s in summaries)
        total_size = 0
        size_cache = {}
        
        for summary in summaries:
            dataset_path = catalog_dir / "data" / "bar" / summary.bar_type
            if dataset_path.exists():
                if summary.bar_type not in size_cache:
                    size_cache[summary.bar_type] = calculate_directory_size(dataset_path)
                total_size += size_cache[summary.bar_type]
        
        # Show what will be deleted
        logger.warning(f"\n{'=' * 80}")
        logger.warning("WARNING: This will delete ALL catalog data!")
        logger.warning(f"{'=' * 80}")
        logger.warning(f"Datasets to delete: {len(summaries)}")
        logger.warning(f"Total bars: {total_bars:,}")
        logger.warning(f"Total disk space: {format_size(total_size)}")
        logger.warning(f"{'=' * 80}\n")
        
        # Interactive confirmation if not provided via flag
        if not dry_run and not confirm:
            response = input("Are you sure you want to delete ALL catalog data? (yes/no): ")
            if response.lower() != "yes":
                logger.info("Deletion cancelled by user.")
                return False
        
        # Delete all datasets
        deleted_count = 0
        total_size_freed = 0
        
        for summary in summaries:
            bar_type_str = summary.bar_type
            dataset_path = catalog_dir / "data" / "bar" / bar_type_str
            
            if not dataset_path.exists():
                continue
            
            # Use cached size to avoid double scanning
            dataset_size = size_cache.get(bar_type_str, 0)
            total_size_freed += dataset_size
            
            if dry_run:
                logger.info(f"[DRY RUN] Would delete: {bar_type_str} ({format_size(dataset_size)})")
            else:
                try:
                    shutil.rmtree(dataset_path)
                    logger.info(f"Deleted: {bar_type_str} ({format_size(dataset_size)})")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {dataset_path}: {e}")
        
        if dry_run:
            logger.info(
                f"\n[DRY RUN] Would delete {len(summaries)} dataset(s), "
                f"freeing {format_size(total_size_freed)}\n"
                f"Run with --delete-all --confirm (without --dry-run) to execute deletion"
            )
        else:
            logger.info(
                f"\nSuccessfully deleted {deleted_count}/{len(summaries)} dataset(s), "
                f"freed {format_size(total_size_freed)}"
            )
        
        return True
        
    except Exception as e:
        logger.error(f"Error during delete-all operation: {e}")
        return False


def main():
    """Main function to handle command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Manage NautilusTrader ParquetDataCatalog datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all datasets
  python data/cleanup_catalog.py --list
  
  # List datasets for specific instrument
  python data/cleanup_catalog.py --list --instrument EUR/USD.IDEALPRO
  
  # List datasets for specific bar spec
  python data/cleanup_catalog.py --list --bar-spec 1-MINUTE-MID-EXTERNAL
  
  # Delete specific dataset (dry-run)
  python data/cleanup_catalog.py --delete --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL
  
  # Delete specific dataset (execute)
  python data/cleanup_catalog.py --delete --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL --execute
  
  # Delete all datasets (dry-run)
  python data/cleanup_catalog.py --delete-all
  
  # Delete all datasets (execute with confirmation)
  python data/cleanup_catalog.py --delete-all --confirm --execute
        """
    )
    
    parser.add_argument(
        "--catalog-path", 
        default="data/historical", 
        help="Path to the catalog directory (default: data/historical)"
    )
    
    # Action flags (mutually exclusive)
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--list", 
        action="store_true", 
        help="List all datasets in the catalog"
    )
    action_group.add_argument(
        "--delete", 
        action="store_true", 
        help="Delete specific dataset (requires --instrument and --bar-spec)"
    )
    action_group.add_argument(
        "--delete-all", 
        action="store_true", 
        help="Delete all datasets in the catalog (requires --confirm for execution)"
    )
    
    # Filter arguments
    parser.add_argument(
        "--instrument", 
        help="Instrument ID filter (e.g., EUR/USD.IDEALPRO or EURUSD.IDEALPRO)"
    )
    parser.add_argument(
        "--bar-spec", 
        help="Bar specification filter (e.g., 1-MINUTE-MID-EXTERNAL)"
    )
    
    # Execution control
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        default=True,
        help="Preview deletions without executing (default: true)"
    )
    parser.add_argument(
        "--execute", 
        action="store_true", 
        help="Actually perform deletions (overrides --dry-run)"
    )
    parser.add_argument(
        "--confirm", 
        action="store_true", 
        help="Skip interactive confirmation prompt for --delete-all"
    )
    
    args = parser.parse_args()
    
    # Setup logging once in main
    setup_logging()
    
    # Determine dry-run mode (--execute overrides --dry-run)
    dry_run = args.dry_run and not args.execute
    
    # Log effective mode for clarity
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    logger.info(f"Running in {mode} mode")
    
    # Execute requested action
    if args.list:
        # List action (read-only, ignores dry-run)
        success = list_catalog_datasets(
            catalog_path=args.catalog_path,
            instrument_filter=args.instrument,
            bar_spec_filter=args.bar_spec
        )
    
    elif args.delete:
        # Delete specific dataset
        if not args.instrument or not args.bar_spec:
            logger.error("--delete requires both --instrument and --bar-spec arguments")
            logger.info("Example: --delete --instrument EUR/USD.IDEALPRO --bar-spec 1-MINUTE-MID-EXTERNAL")
            return 1
        
        success = delete_dataset(
            catalog_path=args.catalog_path,
            instrument_id=args.instrument,
            bar_spec=args.bar_spec,
            dry_run=dry_run
        )
    
    elif args.delete_all:
        # Delete all datasets
        success = delete_all(
            catalog_path=args.catalog_path,
            confirm=args.confirm,
            dry_run=dry_run
        )
    
    else:
        logger.error("No action specified. Use --list, --delete, or --delete-all")
        return 1
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
