#!/usr/bin/env python3
"""
Compare feature DataFrame snapshots between live and replay to identify divergence.

Usage:
    python scripts/compare_feature_snapshots.py
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys


def compare_dataframes(live_df: pd.DataFrame, replay_df: pd.DataFrame, name: str) -> dict:
    """Compare two DataFrames and report differences."""
    results = {
        'name': name,
        'live_rows': len(live_df),
        'replay_rows': len(replay_df),
        'common_rows': 0,
        'divergent_columns': [],
        'first_divergence': None,
    }
    
    # Find common timestamps
    common_index = live_df.index.intersection(replay_df.index)
    results['common_rows'] = len(common_index)
    
    if len(common_index) == 0:
        print(f"\n{name}: NO COMMON TIMESTAMPS")
        print(f"  Live range: {live_df.index[0]} to {live_df.index[-1]}")
        print(f"  Replay range: {replay_df.index[0]} to {replay_df.index[-1]}")
        return results
    
    # Check each column for divergence
    common_cols = set(live_df.columns) & set(replay_df.columns)
    
    for col in sorted(common_cols):
        live_vals = live_df.loc[common_index, col]
        replay_vals = replay_df.loc[common_index, col]
        
        # Skip NaN comparison
        valid_mask = ~(pd.isna(live_vals) | pd.isna(replay_vals))
        if not valid_mask.any():
            continue
        
        # Check if values match (allowing for floating point tolerance)
        if live_vals.dtype in [np.float64, np.float32]:
            matches = np.allclose(live_vals[valid_mask], replay_vals[valid_mask], rtol=1e-9, atol=1e-12)
        else:
            matches = (live_vals[valid_mask] == replay_vals[valid_mask]).all()
        
        if not matches:
            # Find first divergence
            diff_mask = ~np.isclose(live_vals[valid_mask], replay_vals[valid_mask], rtol=1e-9, atol=1e-12) if live_vals.dtype in [np.float64, np.float32] else (live_vals[valid_mask] != replay_vals[valid_mask])
            first_diff_idx = diff_mask.index[diff_mask][0] if diff_mask.any() else None
            
            if first_diff_idx is not None:
                live_val = live_vals.loc[first_diff_idx]
                replay_val = replay_vals.loc[first_diff_idx]
                diff = abs(live_val - replay_val) if isinstance(live_val, (int, float)) else 'N/A'
                
                results['divergent_columns'].append({
                    'column': col,
                    'first_timestamp': first_diff_idx,
                    'live_value': live_val,
                    'replay_value': replay_val,
                    'difference': diff,
                })
                
                if results['first_divergence'] is None:
                    results['first_divergence'] = {
                        'column': col,
                        'timestamp': first_diff_idx,
                    }
    
    return results


def main():
    snapshot_dir = Path("parity_snapshots")
    
    if not snapshot_dir.exists():
        print(f"Error: {snapshot_dir} does not exist")
        print("Run parity diagnostic backtest and live trading first.")
        sys.exit(1)
    
    # Find latest snapshots
    live_15m = sorted(snapshot_dir.glob("features_15m_live_*.csv"))
    live_30m = sorted(snapshot_dir.glob("features_30m_live_*.csv"))
    replay_15m = sorted(snapshot_dir.glob("features_15m_replay_*.csv"))
    replay_30m = sorted(snapshot_dir.glob("features_30m_replay_*.csv"))
    
    if not replay_15m or not replay_30m:
        print("Error: No replay snapshots found. Run diagnostic backtest first.")
        sys.exit(1)
    
    print("="*80)
    print("Feature Snapshot Comparison")
    print("="*80)
    print()
    
    # Compare 15m features
    if live_15m and replay_15m:
        print(f"Loading 15m features...")
        print(f"  Live:   {live_15m[-1]}")
        print(f"  Replay: {replay_15m[-1]}")
        
        live_df_15m = pd.read_csv(live_15m[-1], index_col=0, parse_dates=True)
        replay_df_15m = pd.read_csv(replay_15m[-1], index_col=0, parse_dates=True)
        
        results_15m = compare_dataframes(live_df_15m, replay_df_15m, "15m Features")
        
        print(f"\n15m Features Comparison:")
        print(f"  Live rows: {results_15m['live_rows']}")
        print(f"  Replay rows: {results_15m['replay_rows']}")
        print(f"  Common rows: {results_15m['common_rows']}")
        print(f"  Divergent columns: {len(results_15m['divergent_columns'])}")
        
        if results_15m['first_divergence']:
            fd = results_15m['first_divergence']
            print(f"\n  FIRST DIVERGENCE:")
            print(f"    Column: {fd['column']}")
            print(f"    Timestamp: {fd['timestamp']}")
        
        if results_15m['divergent_columns']:
            print(f"\n  Top 10 Divergent Columns:")
            for i, div in enumerate(results_15m['divergent_columns'][:10], 1):
                print(f"    {i}. {div['column']}")
                print(f"       First diff @ {div['first_timestamp']}")
                print(f"       Live={div['live_value']} Replay={div['replay_value']} Δ={div['difference']}")
    else:
        print("No live 15m snapshots found (expected if running backtest-only)")
    
    # Compare 30m features
    print()
    if live_30m and replay_30m:
        print(f"Loading 30m features...")
        print(f"  Live:   {live_30m[-1]}")
        print(f"  Replay: {replay_30m[-1]}")
        
        live_df_30m = pd.read_csv(live_30m[-1], index_col=0, parse_dates=True)
        replay_df_30m = pd.read_csv(replay_30m[-1], index_col=0, parse_dates=True)
        
        results_30m = compare_dataframes(live_df_30m, replay_df_30m, "30m Features")
        
        print(f"\n30m Features Comparison:")
        print(f"  Live rows: {results_30m['live_rows']}")
        print(f"  Replay rows: {results_30m['replay_rows']}")
        print(f"  Common rows: {results_30m['common_rows']}")
        print(f"  Divergent columns: {len(results_30m['divergent_columns'])}")
        
        if results_30m['first_divergence']:
            fd = results_30m['first_divergence']
            print(f"\n  FIRST DIVERGENCE:")
            print(f"    Column: {fd['column']}")
            print(f"    Timestamp: {fd['timestamp']}")
        
        if results_30m['divergent_columns']:
            print(f"\n  Top 10 Divergent Columns:")
            for i, div in enumerate(results_30m['divergent_columns'][:10], 1):
                print(f"    {i}. {div['column']}")
                print(f"       First diff @ {div['first_timestamp']}")
                print(f"       Live={div['live_value']} Replay={div['replay_value']} Δ={div['difference']}")
    else:
        print("No live 30m snapshots found (expected if running backtest-only)")
    
    # Compare bar delivery counts
    print()
    print("="*80)
    print("Bar Delivery Analysis")
    print("="*80)
    
    delivery_files = sorted(snapshot_dir.glob("bar_delivery_*.csv"))
    for dfile in delivery_files:
        print(f"\n{dfile.stem}:")
        df = pd.read_csv(dfile)
        total = len(df)
        single = (df['delivery_count'] == 1).sum()
        double = (df['delivery_count'] == 2).sum()
        triple_plus = (df['delivery_count'] >= 3).sum()
        
        print(f"  Total bars: {total}")
        print(f"  Single delivery: {single} ({100*single/total:.1f}%)")
        print(f"  Double delivery: {double} ({100*double/total:.1f}%)")
        print(f"  Triple+ delivery: {triple_plus} ({100*triple_plus/total:.1f}%)")
        
        if double > 0 or triple_plus > 0:
            print(f"  Examples of multi-delivery:")
            multi = df[df['delivery_count'] > 1].head(5)
            for _, row in multi.iterrows():
                ts = pd.Timestamp(row['timestamp_ns'], unit='ns', tz='UTC')
                print(f"    {ts}: {row['delivery_count']} times")


if __name__ == '__main__':
    main()
