import pandas as pd
import numpy as np
import os

# Path to the trades file
TRADES_FILE = r"C:\nautilus0\backtest_results\MTF_V3_BACKTEST_REPLAY_20251224_203504\trades.csv"

def analyze_trades():
    if not os.path.exists(TRADES_FILE):
        print(f"File not found: {TRADES_FILE}")
        return

    df = pd.read_csv(TRADES_FILE)
    
    # Convert timestamps
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df['duration'] = df['exit_time'] - df['entry_time']
    df['duration_minutes'] = df['duration'].dt.total_seconds() / 60.0

    # Calculate SL distance in ATR
    df['sl_dist_atr'] = abs(df['entry_price'] - df['sl_price']) / df['atr_15m']
    
    # Classify exits
    def classify_exit(row):
        if row['reason'] == 'SL':
            if row['sl_dist_atr'] < 0.8: # Threshold to distinguish Stall (0.6) from Normal SL (1.0)
                return 'Stall SL'
            else:
                return 'Normal SL'
        return row['reason']

    df['exit_type'] = df.apply(classify_exit, axis=1)

    print("--- SL Distance Distribution (SL Exits) ---")
    print(df[df['reason'] == 'SL']['sl_dist_atr'].describe())
    print("\n")

    print("--- Size Analysis ---")
    print(f"Max Size: {df['size_units'].max()}")
    print("\n")

    print("--- Exit Type Analysis ---")
    stats = df.groupby('exit_type').agg({
        'pnl_net': ['count', 'mean', 'sum'],
        'duration_minutes': 'mean',
        'sl_dist_atr': 'mean'
    })
    print(stats)
    print("\n")

    print("--- Losing Trades Analysis ---")
    losers = df[df['pnl_net'] < 0].copy()
    loser_stats = losers.groupby('exit_type').agg({
        'pnl_net': ['count', 'mean', 'sum'],
        'duration_minutes': ['mean', 'max', 'min'],
        'sl_dist_atr': 'mean'
    })
    print(loser_stats)
    print("\n")

    print("--- Potential for Negative Stall ---")
    # Look for Normal SL losses that took a long time
    long_losers = losers[
        (losers['exit_type'] == 'Normal SL') & 
        (losers['duration_minutes'] > 60) # e.g., more than 1 hour
    ]
    
    print(f"Number of 'Normal SL' losses > 60 mins: {len(long_losers)}")
    if len(long_losers) > 0:
        print(long_losers[['entry_time', 'duration_minutes', 'pnl_net', 'sl_dist_atr']].describe())
        print("\nSample long duration Normal SL losses:")
        print(long_losers[['entry_time', 'duration_minutes', 'pnl_net']].head())

    # Check if Stall SL is actually saving money
    stall_sl_trades = df[df['exit_type'] == 'Stall SL']
    if len(stall_sl_trades) > 0:
        print("\n--- Stall SL Effectiveness ---")
        print(f"Stall SL Trades: {len(stall_sl_trades)}")
        print(f"Avg PnL: {stall_sl_trades['pnl_net'].mean():.2f}")
        print(f"Win Rate: {(stall_sl_trades['pnl_net'] > 0).mean():.2%}")
        # Compare with Normal SL avg loss
        normal_sl_loss = df[(df['exit_type'] == 'Normal SL') & (df['pnl_net'] < 0)]['pnl_net'].mean()
        print(f"Avg Normal SL Loss: {normal_sl_loss:.2f}")
        
        stall_loss = stall_sl_trades[stall_sl_trades['pnl_net'] < 0]['pnl_net'].mean()
        print(f"Avg Stall SL Loss: {stall_loss:.2f}")
        
        if stall_loss > normal_sl_loss:
             print("Observation: Stall SL losses are smaller than Normal SL losses (Good).")
        else:
             print("Observation: Stall SL losses are NOT smaller (Unexpected).")

if __name__ == "__main__":
    analyze_trades()
