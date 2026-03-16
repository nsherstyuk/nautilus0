"""
Analyze logged velocity data from continuous monitor.
Produces statistics and visualizations.
"""
import pandas as pd
import sys
from pathlib import Path


def analyze_velocity_log(csv_path: str):
    """Analyze velocity log CSV and print statistics."""
    
    print("="*70)
    print(f"VELOCITY LOG ANALYSIS")
    print("="*70)
    print(f"File: {csv_path}\n")
    
    # Load data
    df = pd.read_csv(csv_path)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
    
    # Basic stats
    print(f"BASIC STATISTICS")
    print("-"*70)
    print(f"Total records:      {len(df):,}")
    print(f"Start time (UTC):   {df['timestamp_utc'].min()}")
    print(f"End time (UTC):     {df['timestamp_utc'].max()}")
    duration = (df['timestamp_utc'].max() - df['timestamp_utc'].min()).total_seconds() / 3600
    print(f"Duration:           {duration:.1f} hours ({duration/24:.1f} days)")
    
    # Velocity statistics
    print(f"\nVELOCITY STATISTICS (ticks/min)")
    print("-"*70)
    for col in ['velocity_1m', 'velocity_3m', 'velocity_5m', 'velocity_10m']:
        vel = df[col].astype(float)
        print(f"{col:15s} Mean={vel.mean():6.1f}  Median={vel.median():6.1f}  "
              f"Min={vel.min():6.1f}  Max={vel.max():6.1f}")
    
    # Percentiles for 3-min velocity (strategy uses this)
    print(f"\n3-MIN VELOCITY PERCENTILES")
    print("-"*70)
    vel_3m = df['velocity_3m'].astype(float)
    for p in [10, 25, 50, 75, 90, 95, 99]:
        val = vel_3m.quantile(p/100)
        print(f"P{p:02d}: {val:6.1f} ticks/min")
    
    # Hour of day analysis
    print(f"\nHOURLY AVERAGE (3-min velocity)")
    print("-"*70)
    hourly = df.groupby('hour_utc')['velocity_3m'].apply(lambda x: x.astype(float).mean())
    
    for hour in range(24):
        if hour in hourly.index:
            avg = hourly[hour]
            
            # Mark important windows
            marker = ""
            if 0 <= hour <= 6:
                marker = " <-- ASIAN RANGE"
            elif 8 <= hour <= 16:
                marker = " <-- TRADE WINDOW (XAUUSD)"
            elif 13 <= hour <= 21:
                marker = " <-- TRADE WINDOW (EURUSD)"
                
            print(f"Hour {hour:02d}:00 UTC  {avg:6.1f} ticks/min{marker}")
        else:
            print(f"Hour {hour:02d}:00 UTC  (no data)")
    
    # Weekday analysis
    print(f"\nWEEKDAY AVERAGE (3-min velocity)")
    print("-"*70)
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_avg = df.groupby('weekday')['velocity_3m'].apply(lambda x: x.astype(float).mean())
    
    for day_num, day_name in enumerate(weekday_names):
        if day_num in weekday_avg.index:
            avg = weekday_avg[day_num]
            marker = " <-- SKIP (XAUUSD)" if day_num == 2 else ""
            print(f"{day_name:10s}  {avg:6.1f} ticks/min{marker}")
    
    # Threshold analysis
    print(f"\nTHRESHOLD ANALYSIS (3-min velocity)")
    print("-"*70)
    
    thresholds = {
        'XAUUSD': 168.0,
        'EURUSD': 50.0
    }
    
    for instrument, threshold in thresholds.items():
        above = (vel_3m >= threshold).sum()
        pct = 100 * above / len(vel_3m)
        print(f"{instrument:7s} threshold={threshold:5.0f}  Above: {above:5d} records ({pct:4.1f}%)")
    
    # Time above threshold by hour
    print(f"\nXAUUSD THRESHOLD (168) - % TIME ABOVE BY HOUR")
    print("-"*70)
    for hour in range(24):
        hour_data = df[df['hour_utc'] == hour]['velocity_3m'].astype(float)
        if len(hour_data) > 0:
            above_pct = 100 * (hour_data >= 168).sum() / len(hour_data)
            bar = '#' * int(above_pct / 2)
            print(f"Hour {hour:02d}:00  {above_pct:5.1f}%  {bar}")
    
    # Data quality checks
    print(f"\nDATA QUALITY")
    print("-"*70)
    zero_velocity = (vel_3m == 0).sum()
    print(f"Zero velocity:      {zero_velocity:,} records ({100*zero_velocity/len(df):.1f}%)")
    
    buffer_sizes = df['buffer_size'].astype(int)
    print(f"Avg buffer size:    {buffer_sizes.mean():,.0f} ticks")
    print(f"Min buffer size:    {buffer_sizes.min():,} ticks")
    
    small_buffer = (buffer_sizes < 100).sum()
    if small_buffer > 0:
        print(f"WARNING: {small_buffer} records with <100 ticks in buffer")
    
    # Export summary
    print(f"\nEXPORTING SUMMARY")
    print("-"*70)
    
    summary_path = Path(csv_path).parent / f"{Path(csv_path).stem}_summary.txt"
    
    with open(summary_path, 'w') as f:
        f.write(f"Velocity Log Summary\n")
        f.write(f"File: {csv_path}\n")
        f.write(f"Duration: {duration:.1f} hours\n")
        f.write(f"Records: {len(df):,}\n\n")
        
        f.write(f"3-min Velocity Stats:\n")
        f.write(f"  Mean: {vel_3m.mean():.1f}\n")
        f.write(f"  Median: {vel_3m.median():.1f}\n")
        f.write(f"  P50: {vel_3m.quantile(0.50):.1f}\n")
        f.write(f"  P75: {vel_3m.quantile(0.75):.1f}\n")
        f.write(f"  P95: {vel_3m.quantile(0.95):.1f}\n\n")
        
        f.write(f"XAUUSD Threshold (168):\n")
        above = (vel_3m >= 168).sum()
        f.write(f"  {100*above/len(vel_3m):.1f}% of time above threshold\n\n")
        
        f.write(f"EURUSD Threshold (50):\n")
        above = (vel_3m >= 50).sum()
        f.write(f"  {100*above/len(vel_3m):.1f}% of time above threshold\n")
    
    print(f"Summary exported to: {summary_path}")
    
    print("\n" + "="*70)
    print("ANALYSIS COMPLETE")
    print("="*70)


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_velocity_log.py <path_to_csv>")
        print("\nOr analyze latest file:")
        
        log_dir = Path('v6_velocity_logs')
        if log_dir.exists():
            csv_files = sorted(log_dir.glob('velocity_*.csv'), key=lambda x: x.stat().st_mtime, reverse=True)
            if csv_files:
                print(f"\nLatest: {csv_files[0]}")
                analyze_velocity_log(str(csv_files[0]))
            else:
                print("No velocity log files found")
        else:
            print(f"Log directory not found: {log_dir}")
    else:
        csv_path = sys.argv[1]
        analyze_velocity_log(csv_path)


if __name__ == "__main__":
    main()
