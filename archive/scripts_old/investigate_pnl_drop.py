"""
Investigate why PnL dropped after the fix.
Compare trade counts and understand the logic flow.
"""
import pandas as pd
from pathlib import Path

# Compare two backtest results
old_result = Path("logs/backtest_results/EUR-USD_20251109_222723")
new_result = Path("logs/backtest_results/EUR-USD_20251109_233716")

print("=" * 80)
print("COMPARING BACKTEST RESULTS")
print("=" * 80)

# Read positions
old_positions = pd.read_csv(old_result / "positions.csv")
new_positions = pd.read_csv(new_result / "positions.csv")

print(f"\nOLD BACKTEST (before fix):")
print(f"  Total Trades: {len(old_positions)}")
print(f"  Total PnL: ${old_positions['realized_pnl'].str.replace(' USD', '').str.replace('USD', '').str.strip().astype(float).sum():.2f}")

print(f"\nNEW BACKTEST (after fix):")
print(f"  Total Trades: {len(new_positions)}")
print(f"  Total PnL: ${new_positions['realized_pnl'].str.replace(' USD', '').str.replace('USD', '').str.strip().astype(float).sum():.2f}")

# Read rejected signals
old_rejected = pd.read_csv(old_result / "rejected_signals.csv")
new_rejected = pd.read_csv(new_result / "rejected_signals.csv")

print(f"\nREJECTED SIGNALS:")
print(f"  Old: {len(old_rejected)}")
print(f"  New: {len(new_rejected)}")

# Check rejection reasons
print(f"\nOLD REJECTION REASONS:")
print(old_rejected['rejection_reason'].value_counts().head(10))

print(f"\nNEW REJECTION REASONS:")
print(new_rejected['rejection_reason'].value_counts().head(10))

# Check if threshold filter is rejecting more
old_threshold_rejects = len(old_rejected[old_rejected['rejection_reason'].str.contains('threshold', case=False, na=False)])
new_threshold_rejects = len(new_rejected[new_rejected['rejection_reason'].str.contains('threshold', case=False, na=False)])

print(f"\nTHRESHOLD FILTER REJECTIONS:")
print(f"  Old: {old_threshold_rejects}")
print(f"  New: {new_threshold_rejects}")

