"""
Find the backtest results folder that achieved ~14k PnL.
"""
import pandas as pd
from pathlib import Path
import json
from datetime import datetime

def find_14k_backtest():
    """Search for backtest results with ~$14,203 PnL."""
    
    target_pnl = 14203.91
    tolerance = 100.0  # Allow ±$100 difference
    
    results_dir = Path("logs/backtest_results")
    if not results_dir.exists():
        print("ERROR: Backtest results directory not found")
        return None
    
    print("=" * 80)
    print("SEARCHING FOR 14K PNL BACKTEST RESULTS")
    print("=" * 80)
    print(f"Target PnL: ${target_pnl:,.2f} (±${tolerance:.2f})")
    print(f"\nSearching in: {results_dir}")
    print()
    
    candidates = []
    
    # Search all backtest folders
    folders = sorted([f for f in results_dir.iterdir() if f.is_dir() and f.name.startswith("EUR")], 
                     key=lambda x: x.stat().st_mtime, reverse=True)
    
    print(f"Found {len(folders)} backtest result folders")
    print("Scanning for matching PnL...\n")
    
    for folder in folders:
        # Check summary.json or positions.csv
        summary_file = folder / "summary.json"
        positions_file = folder / "positions.csv"
        
        pnl = None
        source = None
        
        # Try summary.json first
        if summary_file.exists():
            try:
                with open(summary_file, 'r') as f:
                    summary = json.load(f)
                    if 'total_pnl' in summary:
                        pnl = float(summary['total_pnl'])
                        source = "summary.json"
            except:
                pass
        
        # Try positions.csv if summary.json didn't work
        if pnl is None and positions_file.exists():
            try:
                df = pd.read_csv(positions_file)
                if 'realized_pnl' in df.columns:
                    # Extract numeric PnL
                    if df['realized_pnl'].dtype == 'object':
                        pnl_values = df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip()
                        pnl_values = pd.to_numeric(pnl_values, errors='coerce')
                    else:
                        pnl_values = df['realized_pnl']
                    pnl = pnl_values.sum()
                    source = "positions.csv"
            except Exception as e:
                pass
        
        if pnl is not None:
            diff = abs(pnl - target_pnl)
            if diff <= tolerance:
                candidates.append({
                    'folder': folder,
                    'pnl': pnl,
                    'diff': diff,
                    'source': source,
                    'mtime': datetime.fromtimestamp(folder.stat().st_mtime)
                })
                print(f"[MATCH] {folder.name}")
                print(f"  PnL: ${pnl:,.2f} (diff: ${diff:.2f})")
                print(f"  Source: {source}")
                print(f"  Modified: {candidates[-1]['mtime']}")
                print()
    
    if not candidates:
        print("No matching backtest results found.")
        print("\nTrying alternative search: Looking for optimization run folders...")
        
        # Check if there are optimization run folders
        opt_results_dir = Path("optimization/results")
        if opt_results_dir.exists():
            print(f"\nChecking optimization results directory...")
            # The JSON file we have shows run_id: 28
            # We might need to find the actual backtest folder that corresponds to this
    
    return candidates

def analyze_14k_folder(folder_path: Path):
    """Analyze a backtest results folder to extract all parameters."""
    
    print("=" * 80)
    print(f"ANALYZING BACKTEST FOLDER: {folder_path.name}")
    print("=" * 80)
    
    # Read .env file
    env_file = folder_path / ".env"
    env_params = {}
    if env_file.exists():
        print("\n1. PARAMETERS FROM .env FILE:")
        print("-" * 80)
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    env_params[key] = value
                    print(f"  {key}={value}")
    
    # Read summary.json if available
    summary_file = folder_path / "summary.json"
    summary_data = {}
    if summary_file.exists():
        print("\n2. PARAMETERS FROM summary.json:")
        print("-" * 80)
        try:
            with open(summary_file, 'r') as f:
                summary_data = json.load(f)
                print(json.dumps(summary_data, indent=2))
        except Exception as e:
            print(f"  Error reading summary.json: {e}")
    
    # Analyze positions.csv
    positions_file = folder_path / "positions.csv"
    if positions_file.exists():
        print("\n3. TRADE ANALYSIS:")
        print("-" * 80)
        try:
            df = pd.read_csv(positions_file)
            print(f"  Total trades: {len(df)}")
            
            # Extract PnL
            if 'realized_pnl' in df.columns:
                if df['realized_pnl'].dtype == 'object':
                    df['pnl_value'] = df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
                else:
                    df['pnl_value'] = df['realized_pnl'].astype(float)
                
                total_pnl = df['pnl_value'].sum()
                print(f"  Total PnL: ${total_pnl:,.2f}")
                print(f"  Winning trades: {len(df[df['pnl_value'] > 0])}")
                print(f"  Losing trades: {len(df[df['pnl_value'] < 0])}")
                
                if 'ts_opened' in df.columns:
                    df['ts_opened'] = pd.to_datetime(df['ts_opened'])
                    print(f"  First trade: {df['ts_opened'].min()}")
                    print(f"  Last trade: {df['ts_opened'].max()}")
        except Exception as e:
            print(f"  Error analyzing positions.csv: {e}")
    
    # Check for other report files
    print("\n4. AVAILABLE FILES:")
    print("-" * 80)
    for file in sorted(folder_path.iterdir()):
        if file.is_file():
            size = file.stat().st_size
            print(f"  {file.name} ({size:,} bytes)")
    
    return {
        'env_params': env_params,
        'summary': summary_data,
        'folder': folder_path
    }

if __name__ == "__main__":
    candidates = find_14k_backtest()
    
    if candidates:
        # Analyze the best match
        best_match = min(candidates, key=lambda x: x['diff'])
        print("\n" + "=" * 80)
        print(f"BEST MATCH: {best_match['folder'].name}")
        print("=" * 80)
        
        analysis = analyze_14k_folder(best_match['folder'])
        
        print("\n" + "=" * 80)
        print("NEXT STEPS:")
        print("=" * 80)
        print("1. Review the extracted parameters above")
        print("2. Cross-reference with optimization JSON")
        print("3. Reconstruct complete .env file")
        print("4. Test with current code")
    else:
        print("\nNo exact match found. Checking optimization run folders...")
        # Try to find by date or other means
