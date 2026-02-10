"""
Code version tracking utility for backtest runs.

This module provides functions to capture and record the code version
used for each backtest run, including git commit info and file checksums.
"""

import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional


def get_git_info() -> Dict[str, str]:
    """Get git repository information."""
    try:
        # Get current commit hash
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        
        # Get current branch
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        
        # Check if there are uncommitted changes
        status = subprocess.check_output(
            ['git', 'status', '--porcelain'],
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        
        has_changes = len(status) > 0
        
        # Get last commit message
        commit_msg = subprocess.check_output(
            ['git', 'log', '-1', '--pretty=%B'],
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        
        # Get last commit date
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--pretty=%ci'],
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        
        return {
            'commit_hash': commit_hash[:12],
            'commit_hash_full': commit_hash,
            'branch': branch,
            'has_uncommitted_changes': has_changes,
            'commit_message': commit_msg,
            'commit_date': commit_date,
            'git_available': True
        }
    except Exception as e:
        return {
            'git_available': False,
            'error': str(e)
        }


def get_file_checksum(filepath: Path) -> str:
    """Calculate MD5 checksum of a file."""
    try:
        md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()[:12]
    except Exception:
        return "N/A"


def get_code_version_info(strategy_file: Optional[Path] = None, 
                          backtest_script: Optional[Path] = None) -> Dict[str, any]:
    """
    Get comprehensive code version information.
    
    Args:
        strategy_file: Path to the strategy file used
        backtest_script: Path to the backtest script used
        
    Returns:
        Dictionary with version information
    """
    info = {
        'timestamp': datetime.now().isoformat(),
        'git': get_git_info(),
        'files': {}
    }
    
    # Add file checksums for key files
    if strategy_file and strategy_file.exists():
        info['files']['strategy'] = {
            'path': str(strategy_file),
            'checksum': get_file_checksum(strategy_file)
        }
    
    if backtest_script and backtest_script.exists():
        info['files']['backtest_script'] = {
            'path': str(backtest_script),
            'checksum': get_file_checksum(backtest_script)
        }
    
    # Add checksums for other critical files
    project_root = Path(__file__).parent.parent
    
    critical_files = [
        project_root / 'config' / 'mtf_v2_config.py',
        project_root / 'run_backtest_mtf_v2_full.py',
    ]
    
    for filepath in critical_files:
        if filepath.exists():
            key = filepath.stem
            info['files'][key] = {
                'path': str(filepath.relative_to(project_root)),
                'checksum': get_file_checksum(filepath)
            }
    
    return info


def write_version_info(output_dir: Path, strategy_file: Optional[Path] = None,
                       backtest_script: Optional[Path] = None) -> None:
    """
    Write version information to the backtest results folder.
    
    Args:
        output_dir: Path to the backtest results directory
        strategy_file: Path to the strategy file used
        backtest_script: Path to the backtest script used
    """
    version_info = get_code_version_info(strategy_file, backtest_script)
    
    output_file = output_dir / 'code_version.txt'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("CODE VERSION INFORMATION\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Generated: {version_info['timestamp']}\n\n")
        
        # Git information
        git_info = version_info['git']
        f.write("GIT REPOSITORY:\n")
        f.write("-" * 80 + "\n")
        
        if git_info.get('git_available'):
            f.write(f"Commit Hash: {git_info['commit_hash']} (full: {git_info['commit_hash_full']})\n")
            f.write(f"Branch: {git_info['branch']}\n")
            f.write(f"Uncommitted Changes: {'YES' if git_info['has_uncommitted_changes'] else 'NO'}\n")
            f.write(f"Last Commit Date: {git_info['commit_date']}\n")
            f.write(f"Last Commit Message:\n  {git_info['commit_message']}\n")
        else:
            f.write(f"Git not available: {git_info.get('error', 'Unknown error')}\n")
        
        f.write("\n")
        
        # File checksums
        f.write("FILE CHECKSUMS (MD5):\n")
        f.write("-" * 80 + "\n")
        
        for file_key, file_info in version_info['files'].items():
            f.write(f"{file_key}:\n")
            f.write(f"  Path: {file_info['path']}\n")
            f.write(f"  Checksum: {file_info['checksum']}\n")
        
        f.write("\n")
        f.write("=" * 80 + "\n")
        f.write("NOTE: This file records the code version used for this backtest run.\n")
        f.write("Use this information to reproduce results or identify code changes.\n")
        f.write("=" * 80 + "\n")
    
    print(f"Code version info saved to: {output_file}")
