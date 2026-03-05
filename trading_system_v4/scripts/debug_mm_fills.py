"""Debug single-day MM sim to verify fill logic."""
import logging
import os
os.environ["TQDM_DISABLE"] = "1"
logging.getLogger("tick_vault").setLevel(logging.WARNING)

from datetime import datetime
from tick_vault import read_tick_data
import numpy as np

ticks = read_tick_data("EURUSD", datetime(2024, 6, 3), datetime(2024, 6, 4))
print(f"Ticks: {len(ticks)}")

asks = ticks["ask"].values
bids = ticks["bid"].values
mids = (asks + bids) / 2.0
spreads = asks - bids

print(f"Spread: min={spreads.min()*10000:.2f}p median={np.median(spreads)*10000:.2f}p max={spreads.max()*10000:.2f}p")
print(f"Mid range: {mids.min():.5f} - {mids.max():.5f} = {(mids.max()-mids.min())*10000:.1f} pips")

# For 2-pip half-spread: bid = mid - 0.0002, ask = mid + 0.0002
# Our bid fills when market drops 2 pips from where we placed it
# On next tick: if bids[i+1] <= pending_bid = mids[i] - 0.0002
# That means: mids[i+1] - spread/2 <= mids[i] - 0.0002
# i.e., mids[i+1] <= mids[i] - 0.0002 + spread/2 ≈ mids[i] - 0.00019

# How often does mid move >= 2 pips between consecutive ticks?
mid_diffs = np.diff(mids)
print(f"\nTick-to-tick mid changes (pips):")
print(f"  Mean: {np.mean(np.abs(mid_diffs))*10000:.4f}p")
print(f"  Max:  {np.max(np.abs(mid_diffs))*10000:.2f}p")
print(f"  |diff| > 0.5 pip: {(np.abs(mid_diffs) > 0.00005).sum()} / {len(mid_diffs)}")
print(f"  |diff| > 1.0 pip: {(np.abs(mid_diffs) > 0.0001).sum()} / {len(mid_diffs)}")
print(f"  |diff| > 2.0 pip: {(np.abs(mid_diffs) > 0.0002).sum()} / {len(mid_diffs)}")

# The issue: with half_spread=2 pips, we need mid to move 2 pips between ticks
# That NEVER happens in normal conditions (moves are 0.01 pips per tick)
# We need to track cumulative: place a quote, and see if over MANY ticks it gets reached

# How about if we keep the quote resting until it fills or we cancel?
# Over a 10-minute window, how far does mid move?
print(f"\nRolling max deviation from a point:")
for window in [100, 500, 1000, 5000]:
    if window >= len(mids):
        continue
    max_devs = []
    for start in range(0, len(mids) - window, window):
        chunk = mids[start:start + window]
        dev = max(chunk.max() - chunk[0], chunk[0] - chunk.min())
        max_devs.append(dev)
    max_devs = np.array(max_devs) * 10000
    print(f"  {window} ticks: mean_dev={max_devs.mean():.2f}p, median={np.median(max_devs):.2f}p, "
          f">2p: {(max_devs > 2).mean()*100:.1f}%, >1p: {(max_devs > 1).mean()*100:.1f}%")

# Conclusion about quote placement strategy
print("\n--- IMPLICATION ---")
print("Single-tick fills at 2.0 pip half-spread are impossible (mid moves ~0.01 pips/tick)")
print("Need to keep quotes RESTING across many ticks until price reaches them")
print("A proper simulation must track open orders that persist until filled or cancelled")
