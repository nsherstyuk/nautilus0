import pandas as pd

df = pd.read_csv('logs/backtest_results/EUR-USD_20251116_171121/positions.csv')
df['pnl'] = df['realized_pnl'].str.replace(' USD','').astype(float)

print(f"Total PnL: ${df['pnl'].sum():.2f}")
print(f"Trades: {len(df)}")
print(f"Win Rate: {(df['pnl']>0).sum()/len(df)*100:.1f}%")
