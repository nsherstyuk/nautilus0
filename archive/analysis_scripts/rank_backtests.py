import os
import re
import pandas as pd
from datetime import datetime

RESULTS_DIR = r"C:\nautilus0\backtest_results"
START_DATE = datetime(2026, 1, 18)

def parse_summary(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Initialize defaults
    data = {
        'pnl': 0.0,
        'winrate': 0.0,
        'zero_trade_days': 0,
        'drawdown_pct': 0.0
    }
    
    # Extract Total P&L
    pnl_match = re.search(r"Total P&L: \$([\d,.-]+)", content)
    if pnl_match:
        data['pnl'] = float(pnl_match.group(1).replace(',', ''))
    
    # Extract Win Rate
    wr_match = re.search(r"Win Rate: ([\d.]+)%", content)
    if wr_match:
        data['winrate'] = float(wr_match.group(1))
    
    # Extract Zero Trade Days
    ztd_match = re.search(r"Zero Trade Days: (\d+)", content)
    if ztd_match:
        data['zero_trade_days'] = int(ztd_match.group(1))
    
    # Extract Max Drawdown Percent
    # Format: Max Drawdown: $-646.01 (-24.7%)
    dd_match = re.search(r"Max Drawdown:.*?\(?(-?[\d.]+)%\)?", content)
    if dd_match:
        data['drawdown_pct'] = abs(float(dd_match.group(1)))
    
    return data

results = []

def parse_env(file_path):
    params = {}
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            for line in f:
                if '=' in line:
                    key, val = line.strip().split('=', 1)
                    # Only keep interesting params
                    if any(x in key for x in ['MTF2_SL_ATR_MULT', 'MTF2_POS1_TP_ATR_MULT', 'MTF2_MA_THRESHOLD', 'MTF2_DMI_FILTER', 'MTF2_ENTRY_CONFIRM']):
                        params[key] = val
    return params

for folder in os.listdir(RESULTS_DIR):
    folder_path = os.path.join(RESULTS_DIR, folder)
    if not os.path.isdir(folder_path):
        continue
    
    # Extract date from folder name: MTF_V2_ENTRY_CONFIRMED_20260123_110808
    match = re.search(r"(\d{8})_(\d{6})", folder)
    if match:
        date_str = match.group(1)
        folder_date = datetime.strptime(date_str, "%Y%m%d")
        
        if folder_date >= START_DATE:
            summary_path = os.path.join(folder_path, "summary.txt")
            env_path = os.path.join(folder_path, ".env.mtf_v2")
            if os.path.exists(summary_path):
                try:
                    stats = parse_summary(summary_path)
                    stats['folder'] = folder
                    stats['date'] = folder_date
                    
                    # Add params
                    params = parse_env(env_path)
                    stats.update(params)
                    
                    results.append(stats)
                except Exception as e:
                    print(f"Error parsing {folder}: {e}")

df = pd.DataFrame(results)

if not df.empty:
    # Ensure all expected columns exist
    for col in ['drawdown_pct', 'pnl', 'winrate', 'zero_trade_days']:
        if col not in df.columns:
            df[col] = 0.0
            
    df['drawdown_pct'] = df['drawdown_pct'].apply(lambda x: max(float(x), 0.1))
    
    # Calculate combined score
    df['combined_score'] = (df['pnl'].astype(float) * (df['winrate'].astype(float) / 100.0)) / df['drawdown_pct'].astype(float)
    
    # Sort by combined score descending
    df = df.sort_values(by='combined_score', ascending=False)
    
    # Print nice table
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    # Select columns to display
    display_cols = ['folder', 'pnl', 'winrate', 'zero_trade_days', 'drawdown_pct', 'combined_score']
    # Add some param cols if they exist
    param_cols = [c for c in df.columns if any(x in c for x in ['MTF2_SL_ATR_MULT', 'MTF2_POS1_TP_ATR_MULT', 'MA_THRESHOLD'])]
    display_cols.extend(param_cols)
    
    print(df[display_cols].to_string(index=False))
else:
    print("No recent backtests found.")

