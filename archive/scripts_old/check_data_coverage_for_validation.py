"""
Verify data coverage and identify gaps for PnL improvement analysis.

This script checks what historical data we have and what we need to download
for the train/validation/forward test plan.

Required periods:
- Discovery: 2022-01-01 → 2023-12-31 (2 years)
- Validation: 2024-01-01 → 2024-12-31 (1 year)  
- Forward: 2025-01-01 → 2025-10-30 (10 months)
"""

import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

def check_data_coverage():
    """Check what data exists and what's missing."""
    
    catalog_path = Path("data/historical")
    if not catalog_path.exists():
        print(f"❌ Catalog path does not exist: {catalog_path}")
        return
    
    try:
        catalog = ParquetDataCatalog(str(catalog_path))
        
        # Get instrument info
        instruments = catalog.instruments()
        if not instruments:
            print("❌ No instruments found in catalog")
            return
            
        print(f"\n{'='*80}")
        print(f"HISTORICAL DATA COVERAGE CHECK")
        print(f"{'='*80}\n")
        
        for instrument in instruments:
            print(f"Instrument: {instrument.id}")
            print(f"-" * 80)
            
            # Try to get bar data
            try:
                bars = catalog.bars(instrument_ids=[str(instrument.id)])
                
                # bars() returns a list, not a DataFrame
                if not bars or len(bars) == 0:
                    print("  ❌ No bar data found\n")
                    continue
                
                # Convert list of bars to DataFrame for analysis
                bar_data_dict = {}
                for bar in bars:
                    bar_type = bar.bar_type
                    if bar_type not in bar_data_dict:
                        bar_data_dict[bar_type] = []
                    bar_data_dict[bar_type].append({
                        'timestamp': pd.Timestamp(bar.ts_init, unit='ns'),
                        'open': bar.open.as_double(),
                        'high': bar.high.as_double(),
                        'low': bar.low.as_double(),
                        'close': bar.close.as_double(),
                        'volume': bar.volume.as_double(),
                    })
                
                # Group by bar type
                for bar_type, bar_list in bar_data_dict.items():
                    if not bar_list:
                        continue
                    
                    bar_df = pd.DataFrame(bar_list)
                    bar_df.set_index('timestamp', inplace=True)
                    bar_df.sort_index(inplace=True)
                    
                    if bar_df.empty:
                        continue
                        
                    start_date = bar_df.index.min()
                    end_date = bar_df.index.max()
                    num_bars = len(bar_df)
                    
                    print(f"\n  Bar Type: {bar_type}")
                    print(f"    Start: {start_date}")
                    print(f"    End:   {end_date}")
                    print(f"    Bars:  {num_bars:,}")
                    
                    # Check coverage for required periods
                    required_periods = {
                        'Discovery (2022-2023)': ('2022-01-01', '2023-12-31'),
                        'Validation (2024)': ('2024-01-01', '2024-12-31'),
                        'Forward (2025)': ('2025-01-01', '2025-10-30'),
                    }
                    
                    print(f"\n    Coverage Analysis:")
                    for period_name, (period_start, period_end) in required_periods.items():
                        period_start_dt = pd.Timestamp(period_start)
                        period_end_dt = pd.Timestamp(period_end)
                        
                        # Check if we have data for this period
                        period_data = bar_df[
                            (bar_df.index >= period_start_dt) & 
                            (bar_df.index <= period_end_dt)
                        ]
                        
                        if len(period_data) > 0:
                            coverage_start = period_data.index.min()
                            coverage_end = period_data.index.max()
                            coverage_pct = (len(period_data) / 
                                          ((period_end_dt - period_start_dt).days * 24 * 4)) * 100  # Rough estimate for 15-min bars
                            
                            if coverage_start <= period_start_dt and coverage_end >= period_end_dt:
                                status = "✅ COMPLETE"
                            else:
                                status = "⚠️  PARTIAL"
                                
                            print(f"      {period_name:25} {status} ({len(period_data):,} bars)")
                        else:
                            print(f"      {period_name:25} ❌ MISSING - Need to download")
                    
            except Exception as e:
                print(f"  ❌ Error reading bar data: {e}\n")
                continue
        
        print(f"\n{'='*80}")
        print("RECOMMENDATIONS:")
        print(f"{'='*80}\n")
        print("If any periods show MISSING or PARTIAL:")
        print("1. Update DATA_START_DATE and DATA_END_DATE in .env")
        print("2. Ensure IB Gateway/TWS is running")
        print("3. Run: python data/ingest_historical.py")
        print("4. The script will automatically chunk large date ranges")
        print("   (15-minute bars: 60-day chunks with overlap)")
        print("\n")
        
    except Exception as e:
        print(f"❌ Error accessing catalog: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_data_coverage()
