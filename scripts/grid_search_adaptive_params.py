import os
import subprocess
import shutil
import datetime
import pandas as pd

# Define the grid of parameters to test
grid = [
    {'MTF2_HIGH_CONFIDENCE_BYPASS_THRESHOLD': str(val), 'MTF2_VOLATILITY_HIGH_THRESHOLD': str(vol), 'MTF2_ENTRY_CONFIRM_THRESHOLD': str(thresh)}
    for val in [0.75, 0.85]
    for vol in [0.0025, 0.0035]
    for thresh in [0.18, 0.22]
]

# Base environment file
ENV_FILE = '.env.mtf_v2'
BACKUP_ENV_FILE = '.env.mtf_v2_backup'

# Results directory
RESULTS_DIR = f'grid_search_results_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
os.makedirs(RESULTS_DIR, exist_ok=True)

# Function to update .env.mtf_v2 file with current grid parameters
def update_env_file(params):
    # Backup original .env file if not already backed up
    if not os.path.exists(BACKUP_ENV_FILE):
        shutil.copy(ENV_FILE, BACKUP_ENV_FILE)
    
    # Read original content
    with open(BACKUP_ENV_FILE, 'r') as f:
        lines = f.readlines()
    
    # Update specific parameters
    for key, value in params.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(key + '='):
                lines[i] = f'{key}={value}\n'
                found = True
        if not found:
            lines.append(f'{key}={value}\n')
    
    # Write updated content to .env file
    with open(ENV_FILE, 'w') as f:
        f.writelines(lines)

# Function to run backtest and extract results
def run_backtest(run_id):
    print(f'Running backtest {run_id}...')
    try:
        result = subprocess.run(['C:\\Users\\nsher\\AppData\\Local\\Programs\\Python\\Python313\\python.exe', 'run_backtest_mtf_v2_entry_confirmed_adaptive.py'], 
                                cwd='c:\\nautilus0', 
                                capture_output=True, text=True, encoding='utf-8', errors='ignore')
        
        # Parse output to extract results directory
        output_lines = result.stdout.splitlines() if result.stdout else []
        results_dir = None
        for line in output_lines:
            if 'Results saved to:' in line:
                results_dir = line.split('Results saved to: ')[1].strip()
                break
        
        if results_dir:
            # Copy summary file to our results directory
            summary_file = os.path.join(results_dir, 'summary.txt')
            if os.path.exists(summary_file):
                dest_file = os.path.join(RESULTS_DIR, f'summary_{run_id}.txt')
                shutil.copy(summary_file, dest_file)
                return dest_file
    except Exception as e:
        print(f'Error running backtest {run_id}: {e}')
    return None

# Store results
results = []

# Run grid search
for i, params in enumerate(grid):
    run_id = f'run_{i+1:02d}_HCB{params["MTF2_HIGH_CONFIDENCE_BYPASS_THRESHOLD"]}_VHT{params["MTF2_VOLATILITY_HIGH_THRESHOLD"]}_ECT{params["MTF2_ENTRY_CONFIRM_THRESHOLD"]}'
    print(f'=== Starting {run_id} ===')
    print(f'Parameters: {params}')
    update_env_file(params)
    summary_file = run_backtest(run_id)
    if summary_file:
        # Extract key metrics from summary file
        try:
            with open(summary_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                total_pnl = None
                win_rate = None
                total_trades = None
                for line in content.splitlines():
                    if 'Total P&L:' in line:
                        total_pnl = float(line.split('$')[1].replace(',', ''))
                    elif 'Win Rate:' in line:
                        win_rate = float(line.split('Win Rate: ')[1].replace('%', ''))
                    elif 'Total Trades:' in line:
                        total_trades = int(line.split('Total Trades: ')[1].replace(',', ''))
                if total_pnl is not None and win_rate is not None and total_trades is not None:
                    results.append({
                        'Run ID': run_id,
                        'High Confidence Bypass': float(params['MTF2_HIGH_CONFIDENCE_BYPASS_THRESHOLD']),
                        'Volatility High Threshold': float(params['MTF2_VOLATILITY_HIGH_THRESHOLD']),
                        'Entry Confirm Threshold': float(params['MTF2_ENTRY_CONFIRM_THRESHOLD']),
                        'Total P&L': total_pnl,
                        'Win Rate (%)': win_rate,
                        'Total Trades': total_trades
                    })
        except Exception as e:
            print(f'Error processing summary for {run_id}: {e}')
    print(f'=== Completed {run_id} ===\n')

# Restore original .env file
if os.path.exists(BACKUP_ENV_FILE):
    shutil.copy(BACKUP_ENV_FILE, ENV_FILE)
    os.remove(BACKUP_ENV_FILE)

# Save results to CSV
results_df = pd.DataFrame(results)
results_df.to_csv(os.path.join(RESULTS_DIR, 'grid_search_summary.csv'), index=False)

print(f'Grid search completed. Results saved to {RESULTS_DIR}/grid_search_summary.csv')
