"""Quick check: what multi-pair data do we have?"""
import pandas as pd
import glob

for pair in ['EURUSD', 'GBPUSD', 'USDCHF']:
    files = glob.glob(f'data/historical/data/bar/{pair}.IDEALPRO-15-MINUTE-MID-EXTERNAL/*.parquet')
    if files:
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs).sort_index()
        ts_col = 'ts_init' if 'ts_init' in df.columns else df.columns[0]
        print(f"{pair}: {len(df)} bars, cols={list(df.columns)}")
        print(f"  head: {df.head(1).to_string()}")
        print(f"  tail: {df.tail(1).to_string()}")
        print()
    else:
        print(f"{pair}: no files")
