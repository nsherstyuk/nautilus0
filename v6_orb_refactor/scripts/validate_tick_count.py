"""
Validates tick_count accuracy in 1-minute bar CSV files.
Checks for common quality issues that could affect velocity filter parity.
"""
import pandas as pd
import numpy as np
from pathlib import Path


def validate_tick_count(csv_path: str):
    """
    Analyzes tick_count column for quality issues.
    """
    print(f"\n{'='*60}")
    print(f"Validating: {Path(csv_path).name}")
    print(f"{'='*60}\n")
    
    df = pd.read_csv(csv_path)
    
    if 'tick_count' not in df.columns:
        print("ERROR: No 'tick_count' column found!")
        return False
    
    tick_counts = df['tick_count']
    
    # Basic statistics
    print("BASIC STATISTICS:")
    print(f"  Total bars: {len(df):,}")
    print(f"  Mean tick_count: {tick_counts.mean():.1f}")
    print(f"  Median tick_count: {tick_counts.median():.1f}")
    print(f"  Std dev: {tick_counts.std():.1f}")
    print(f"  Min: {tick_counts.min()}")
    print(f"  Max: {tick_counts.max()}")
    
    # Quality checks
    print("\nQUALITY CHECKS:")
    
    # Check for missing/zero tick counts
    missing = tick_counts.isna().sum()
    zeros = (tick_counts == 0).sum()
    print(f"  Missing values: {missing} ({100*missing/len(df):.2f}%)")
    print(f"  Zero tick_counts: {zeros} ({100*zeros/len(df):.2f}%)")
    
    if missing > 0 or zeros > len(df) * 0.01:  # More than 1% zeros is suspicious
        print("  WARNING: High proportion of missing/zero tick counts!")
        print("  This will cause velocity filter to behave differently in backtest vs live.")
    
    # Check for unrealistic values
    # XAUUSD typically has 100-500 ticks per minute during active hours
    # EURUSD typically has 50-300 ticks per minute
    very_low = (tick_counts < 10).sum()
    very_high = (tick_counts > 1000).sum()
    print(f"  Very low (<10 ticks): {very_low} ({100*very_low/len(df):.2f}%)")
    print(f"  Very high (>1000 ticks): {very_high} ({100*very_high/len(df):.2f}%)")
    
    # Percentile distribution
    print("\nPERCENTILE DISTRIBUTION:")
    for p in [10, 25, 50, 75, 90, 95, 99]:
        val = np.percentile(tick_counts.dropna(), p)
        print(f"  P{p:02d}: {val:.0f} ticks/min")
    
    # Check by hour (for time-of-day patterns)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        
        print("\nHOURLY AVERAGE TICK COUNT:")
        hourly_avg = df.groupby('hour')['tick_count'].mean()
        for hour, avg in hourly_avg.items():
            marker = " <-- ASIAN RANGE" if 0 <= hour <= 6 else ""
            marker = marker or (" <-- TRADE WINDOW" if 8 <= hour <= 16 else "")
            print(f"  Hour {hour:02d}: {avg:6.1f} ticks/min{marker}")
    
    # Check for suspiciously constant values (might indicate synthetic data)
    mode_count = (tick_counts == tick_counts.mode()[0]).sum()
    print(f"\nMOST COMMON VALUE:")
    print(f"  Value: {tick_counts.mode()[0]:.0f} appears {mode_count} times ({100*mode_count/len(df):.1f}%)")
    if mode_count > len(df) * 0.5:
        print("  WARNING: More than 50% of bars have same tick_count (synthetic data?)")
    
    # Final verdict
    print("\n" + "="*60)
    issues = []
    if missing > 0:
        issues.append("Missing tick_count values")
    if zeros > len(df) * 0.01:
        issues.append(f"High zero count ({100*zeros/len(df):.1f}%)")
    if very_low > len(df) * 0.1:
        issues.append(f"Many very low tick counts ({100*very_low/len(df):.1f}% <10)")
    if mode_count > len(df) * 0.5:
        issues.append("Suspiciously constant tick counts")
    
    if issues:
        print("VERDICT: ISSUES FOUND")
        for issue in issues:
            print(f"  - {issue}")
        print("\nPARITY RISK: MEDIUM-HIGH")
        print("Velocity filter may behave differently in backtest vs live.")
        return False
    else:
        print("VERDICT: TICK COUNT DATA LOOKS GOOD")
        print("\nPARITY RISK: LOW")
        print("Velocity filter should behave similarly in backtest and live.")
        return True


if __name__ == "__main__":
    import sys
    
    data_dir = Path(r"c:\nautilus0\data\1m_csv")
    
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
        validate_tick_count(csv_path)
    else:
        # Validate all CSV files in data directory
        csv_files = list(data_dir.glob("*.csv"))
        
        if not csv_files:
            print(f"No CSV files found in {data_dir}")
        else:
            results = {}
            for csv_file in csv_files:
                result = validate_tick_count(str(csv_file))
                results[csv_file.name] = result
            
            # Summary
            print(f"\n\n{'='*60}")
            print("VALIDATION SUMMARY")
            print(f"{'='*60}")
            for name, passed in results.items():
                status = "PASS" if passed else "FAIL"
                print(f"  {name:30s} {status}")
