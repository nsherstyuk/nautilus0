"""
Cleanup utility for Phase 2 coarse grid search failed results.

This script removes failed optimization artifacts from a Phase 2 run that
encountered Unicode encoding errors. After cleanup, Phase 2 should be re-run
with the --no-resume flag to force a fresh start with the encoding fix.

Files Removed:
  - optimization/checkpoints/phase2_coarse_grid_checkpoint.csv
  - optimization/results/phase2_coarse_grid_results.csv
  - optimization/results/phase2_coarse_grid_results_top_10.json
  - optimization/results/phase2_coarse_grid_results_summary.json

Usage:
  python optimization/cleanup_phase2_failed_results.py [--dry-run] [--verbose]

Exit Codes:
  0: Success (files deleted or already clean)
  1: Error during cleanup
"""

__version__ = "1.0.0"
# Author: AI Assistant
# Date: 2025-01-09

import sys
import logging
import argparse
from pathlib import Path
from typing import List, Tuple

# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent

FILES_TO_DELETE = [
    # Checkpoint file
    (PROJECT_ROOT / "optimization" / "checkpoints" / "phase2_coarse_grid_checkpoint.csv",
     "Phase 2 checkpoint file"),
    
    # Results files (correct naming with .csv extension)
    (PROJECT_ROOT / "optimization" / "results" / "phase2_coarse_grid_results.csv",
     "Phase 2 results CSV (correct naming)"),
    (PROJECT_ROOT / "optimization" / "results" / "phase2_coarse_grid_results_top_10.json",
     "Phase 2 top 10 results JSON (correct naming)"),
    (PROJECT_ROOT / "optimization" / "results" / "phase2_coarse_grid_results_summary.json",
     "Phase 2 summary JSON (correct naming)"),
]

RERUN_INSTRUCTIONS = """
# Run Phase 2 coarse grid search with encoding fix
# IMPORTANT: Use --no-resume to force fresh start
python optimization/grid_search.py `
  --config optimization/configs/phase2_coarse_grid.yaml `
  --objective sharpe_ratio `
  --workers 8 `
  --output optimization/results/phase2_coarse_grid_results.csv `
  --no-resume `
  --verbose
"""


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration with appropriate level and format."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(handler)
    
    return logger


def get_file_size_str(file_path: Path) -> str:
    """Get human-readable file size string."""
    try:
        if not file_path.exists():
            return "N/A"
        
        size_bytes = file_path.stat().st_size
        
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
    except OSError:
        return "Error reading size"


def delete_files(dry_run: bool, logger: logging.Logger) -> Tuple[int, int]:
    """Delete all target files and return (deleted_count, skipped_count)."""
    deleted_count = 0
    skipped_count = 0
    
    logger.info("🧹 Starting Phase 2 cleanup...")
    logger.info("=" * 60)
    
    for file_path, description in FILES_TO_DELETE:
        if file_path.exists():
            file_size = get_file_size_str(file_path)
            logger.info(f"Found: {description}")
            logger.debug(f"  Path: {file_path}")
            logger.info(f"  Size: {file_size}")
            
            if not dry_run:
                try:
                    file_path.unlink(missing_ok=True)
                    # Verify deletion
                    if not file_path.exists():
                        logger.info(f"✅ Deleted: {description}")
                        deleted_count += 1
                    else:
                        logger.error(f"❌ Failed to delete: {description}")
                        # Continue with other files even if one fails
                except OSError as e:
                    logger.error(f"❌ Permission error deleting {description}: {e}")
                    # Continue with other files
            else:
                logger.info(f"[DRY RUN] Would delete: {description}")
                deleted_count += 1  # Count for reporting
        else:
            logger.info(f"⏭️  Skipped (not found): {description} - likely already cleaned")
            skipped_count += 1
    
    logger.info("=" * 60)
    return deleted_count, skipped_count


def print_summary(deleted_count: int, skipped_count: int, dry_run: bool, logger: logging.Logger) -> None:
    """Print cleanup summary and re-run instructions."""
    total_files = len(FILES_TO_DELETE)
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("CLEANUP SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total files checked: {total_files}")
    
    if dry_run:
        logger.info(f"Files to delete: {deleted_count} ✅")
    else:
        logger.info(f"Files deleted: {deleted_count} ✅")
    
    logger.info(f"Files skipped (not found): {skipped_count} ⏭️")
    
    if deleted_count == 0 and skipped_count == total_files:
        logger.info("")
        logger.info("⚠️  All files already cleaned. No action needed.")
        logger.info("Phase 2 results directory is clean.")
    elif deleted_count > 0:
        if dry_run:
            logger.info("")
            logger.info("ℹ️  This was a dry run. No files were actually deleted.")
            logger.info("Run without --dry-run to perform actual cleanup.")
        else:
            logger.info("")
            logger.info("✅ Cleanup completed successfully!")
            logger.info("Phase 2 failed results have been removed.")
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("NEXT STEPS: RE-RUN PHASE 2 WITH ENCODING FIX")
    logger.info("=" * 60)
    logger.info("The Unicode encoding error has been fixed in grid_search.py.")
    logger.info("You can now re-run Phase 2 with the following command:")
    logger.info("")
    print(RERUN_INSTRUCTIONS)
    logger.info("")
    logger.info("Important: Use --no-resume flag to force a fresh start!")
    logger.info("")
    logger.info("Expected behavior after fix:")
    logger.info("  ✅ Each backtest takes 30-60 seconds (not 2-3s)")
    logger.info("  ✅ Success rate > 80% (some timeouts are normal)")
    logger.info("  ✅ No Unicode encoding errors in logs")
    logger.info("  ✅ Results files contain actual metrics")
    logger.info("=" * 60)


def main() -> int:
    """Main function to orchestrate cleanup workflow."""
    try:
        # Parse command-line arguments
        parser = argparse.ArgumentParser(
            description="Cleanup failed Phase 2 optimization results"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting"
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Enable verbose logging (DEBUG level)"
        )
        args = parser.parse_args()
        
        # Setup logging
        logger = setup_logging(args.verbose)
        
        # Log script start
        logger.info("🚀 Phase 2 Cleanup Utility")
        logger.info(f"Version: {__version__}")
        if args.dry_run:
            logger.info("Mode: DRY RUN (no files will be deleted)")
        else:
            logger.info("Mode: CLEANUP (files will be deleted)")
        
        # Verify PROJECT_ROOT exists
        if not PROJECT_ROOT.exists():
            logger.error(f"❌ Project root not found: {PROJECT_ROOT}")
            return 1
        
        # Execute cleanup
        deleted_count, skipped_count = delete_files(args.dry_run, logger)
        
        # Print summary
        print_summary(deleted_count, skipped_count, args.dry_run, logger)
        
        # Determine exit code
        if deleted_count > 0 or skipped_count == len(FILES_TO_DELETE):
            return 0  # Success
        else:
            return 1  # Error or unexpected state
            
    except KeyboardInterrupt:
        logger = logging.getLogger(__name__)
        logger.warning("⚠️  Cleanup interrupted by user")
        return 130
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
