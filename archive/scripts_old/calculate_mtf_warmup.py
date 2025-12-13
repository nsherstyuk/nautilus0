#!/usr/bin/env python3
"""Calculate exact warmup requirements for MTF ML strategy."""

print("="*80)
print("MTF ML STRATEGY - WARMUP CALCULATION")
print("="*80)

# Indicators used in MTF strategy
indicators = {
    "15m timeframe": {
        "Log Returns": 1,  # shift(1)
        "MAMA/FAMA": 50,  # MAMA needs ~50 bars to stabilize
        "ATR(14)": 14,
    },
    "30m timeframe": {
        "DMI/ADX(14)": 14,
        "Stochastic(14,3,3)": 14 + 3,  # k=14, smooth_k=3
        "WMA(8)": 8,
        "WMA(23)": 23,  # LONGEST indicator
    }
}

print("\n📊 Indicator Periods:")
print("-"*80)
for timeframe, inds in indicators.items():
    print(f"\n{timeframe}:")
    for name, period in inds.items():
        print(f"  {name:<20} {period:>3} bars")

# Calculate required bars
print("\n" + "="*80)
print("WARMUP REQUIREMENTS")
print("="*80)

# For 15m timeframe
max_15m = max(indicators["15m timeframe"].values())
print(f"\n15m timeframe:")
print(f"  Longest indicator: MAMA (~50 bars)")
print(f"  Required 15m bars: {max_15m}")
print(f"  Time needed: {max_15m * 15} minutes = {max_15m * 15 / 60:.1f} hours")

# For 30m timeframe (need 2x as many 15m bars)
max_30m = max(indicators["30m timeframe"].values())
required_15m_for_30m = max_30m * 2  # Need 2x 15m bars to create 30m bars
print(f"\n30m timeframe:")
print(f"  Longest indicator: WMA(23)")
print(f"  Required 30m bars: {max_30m}")
print(f"  Required 15m bars: {required_15m_for_30m} (2× for 30m aggregation)")
print(f"  Time needed: {required_15m_for_30m * 15} minutes = {required_15m_for_30m * 15 / 60:.1f} hours")

# Total requirement
total_15m_bars = max(max_15m, required_15m_for_30m)
total_hours = total_15m_bars * 15 / 60
total_days = total_hours / 24

print("\n" + "="*80)
print("TOTAL WARMUP REQUIREMENT")
print("="*80)
print(f"\nMinimum 15m bars needed: {total_15m_bars}")
print(f"Time required: {total_15m_bars * 15} minutes = {total_hours:.1f} hours = {total_days:.1f} days")

# Add safety margin
safety_margin = 1.5
recommended_bars = int(total_15m_bars * safety_margin)
recommended_hours = recommended_bars * 15 / 60
recommended_days = recommended_hours / 24

print(f"\n⚠️  With 50% safety margin:")
print(f"Recommended 15m bars: {recommended_bars}")
print(f"Time required: {recommended_bars * 15} minutes = {recommended_hours:.1f} hours = {recommended_days:.1f} days")

# Current setting
current_setting = 100
current_hours = current_setting * 15 / 60
current_days = current_hours / 24

print("\n" + "="*80)
print("CURRENT SETTING")
print("="*80)
print(f"\nCurrent warmup bars: {current_setting}")
print(f"Time covered: {current_setting * 15} minutes = {current_hours:.1f} hours = {current_days:.1f} days")

if current_setting >= recommended_bars:
    print(f"\n✅ Current setting ({current_setting} bars) is SUFFICIENT")
    print(f"   Covers {current_setting - total_15m_bars} extra bars beyond minimum")
else:
    print(f"\n⚠️  Current setting ({current_setting} bars) may be INSUFFICIENT")
    print(f"   Short by {recommended_bars - current_setting} bars")
    print(f"\n💡 RECOMMENDATION: Increase to {recommended_bars} bars")

print("\n" + "="*80)
print("BACKFILL PERFORMANCE")
print("="*80)
print(f"\nWith IBKR backfill:")
print(f"  Download {current_setting} bars from IBKR")
print(f"  Feed to strategy immediately")
print(f"  Warmup time: ~30-60 seconds (download time)")
print(f"  Trading starts: IMMEDIATELY after backfill")
print(f"\nWithout backfill (natural warmup):")
print(f"  Wait for {current_setting} live bars")
print(f"  Warmup time: {current_hours:.1f} hours = {current_days:.1f} days")
print(f"  Trading starts: After {current_days:.1f} days")

print("\n" + "="*80)
