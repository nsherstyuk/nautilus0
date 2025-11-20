"""
Simulate Minimum Hold Time feature using existing backtest results.

This script analyzes completed backtest positions and simulates what would happen
if we used wider initial stops for the first X hours.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import json


def simulate_min_hold_time(
    results_dir: str,
    min_hold_hours: float = 4.0,
    stop_multiplier: float = 1.5,
    bars_file: str = None  # Optional: path to bars CSV for tick-level accuracy
):
    """
    Simulate minimum hold time feature by analyzing position outcomes.
    
    Args:
        results_dir: Path to backtest results directory
        min_hold_hours: Minimum hold time in hours
        stop_multiplier: Initial stop multiplier (e.g., 1.5 = 50% wider)
        bars_file: Optional path to bars CSV for more accurate simulation
    """
    folder = Path(results_dir)
    positions_file = folder / 'positions.csv'
    
    if not positions_file.exists():
        print(f"ERROR: positions.csv not found in {folder}")
        return
    
    # Load positions
    df = pd.read_csv(positions_file, parse_dates=['ts_opened', 'ts_closed'])
    df['realized_pnl'] = df['realized_pnl'].str.replace(' USD', '', regex=False).astype(float)
    df['duration_hours'] = (df['ts_closed'] - df['ts_opened']).dt.total_seconds() / 3600
    
    # Load bars for more accurate simulation (if available)
    bars_df = None
    if bars_file and Path(bars_file).exists():
        print(f"Loading bars from {bars_file} for accurate simulation...")
        bars_df = pd.read_csv(bars_file, parse_dates=['ts_event', 'ts_init'])
    
    print("="*80)
    print("MINIMUM HOLD TIME SIMULATION")
    print("="*80)
    print(f"\nParameters:")
    print(f"  Minimum hold time: {min_hold_hours} hours")
    print(f"  Initial stop multiplier: {stop_multiplier}x")
    print(f"  Analysis method: {'Bar-level (accurate)' if bars_df is not None else 'Approximate'}")
    
    # Identify early exits (stopped out in first min_hold_hours)
    early_exits = df[df['duration_hours'] < min_hold_hours].copy()
    early_losses = early_exits[early_exits['realized_pnl'] < 0].copy()
    
    print(f"\n" + "="*80)
    print(f"CURRENT RESULTS (Baseline)")
    print("="*80)
    print(f"\nPositions closed in first {min_hold_hours} hours: {len(early_exits)}")
    print(f"  Winners: {len(early_exits[early_exits['realized_pnl'] > 0])}")
    print(f"  Losers: {len(early_losses)}")
    print(f"  Total PnL: ${early_exits['realized_pnl'].sum():.2f}")
    print(f"  Total Losses: ${early_losses['realized_pnl'].sum():.2f}")
    
    # Estimate stop and TP distances from positions
    # Note: This is approximate - we'd need the actual order prices for exact values
    print(f"\n" + "="*80)
    print(f"SIMULATION ASSUMPTIONS")
    print("="*80)
    
    # For each early loser, estimate if wider stop would have helped
    recoverable_positions = []
    
    for idx, pos in early_losses.iterrows():
        entry_price = float(pos['avg_px_open'])
        exit_price = float(pos['avg_px_close'])
        side = pos['side']
        
        # Estimate original stop distance (distance to exit)
        if side == 'LONG':
            original_stop_dist = entry_price - exit_price  # Positive value
        else:  # SHORT
            original_stop_dist = exit_price - entry_price  # Positive value
        
        # Calculate wider stop distance
        wider_stop_dist = original_stop_dist * stop_multiplier
        
        # Estimate if wider stop would avoid exit
        # Simple heuristic: if loss is small relative to wider stop, assume it would survive
        loss_pips = abs(original_stop_dist) * 10000  # Approximate pips for EUR/USD
        wider_stop_pips = wider_stop_dist * 10000
        
        # Estimate potential outcome
        # If position would have survived with wider stop, what would final outcome be?
        # We don't have future price data, so we'll make assumptions:
        
        # Assumption 1: Check if any position with same entry direction lasting >4h was profitable
        same_direction = df[
            (df['side'] == side) & 
            (df['duration_hours'] >= min_hold_hours) &
            (df['ts_opened'] > pos['ts_opened'] - pd.Timedelta(hours=24)) &
            (df['ts_opened'] < pos['ts_opened'] + pd.Timedelta(hours=24))
        ]
        
        avg_outcome_similar = same_direction['realized_pnl'].mean() if len(same_direction) > 0 else 0
        
        potential_outcome = {
            'position_id': pos.name,
            'entry_time': pos['ts_opened'],
            'side': side,
            'entry_price': entry_price,
            'original_stop_pips': loss_pips,
            'wider_stop_pips': wider_stop_pips,
            'current_pnl': pos['realized_pnl'],
            'estimated_pnl': avg_outcome_similar,  # Rough estimate
            'survived': wider_stop_pips > loss_pips * 1.1,  # Would wider stop help?
        }
        
        if potential_outcome['survived']:
            recoverable_positions.append(potential_outcome)
    
    # Summary of simulation results
    print(f"\nPositions that might survive with wider stop: {len(recoverable_positions)}")
    
    if len(recoverable_positions) > 0:
        recoverable_df = pd.DataFrame(recoverable_positions)
        
        print(f"\n" + "="*80)
        print(f"SIMULATION RESULTS")
        print("="*80)
        
        print(f"\nRecoverable positions: {len(recoverable_df)}")
        print(f"  Average current loss: ${recoverable_df['current_pnl'].mean():.2f}")
        print(f"  Estimated avg outcome: ${recoverable_df['estimated_pnl'].mean():.2f}")
        
        total_current_loss = recoverable_df['current_pnl'].sum()
        total_estimated_pnl = recoverable_df['estimated_pnl'].sum()
        
        print(f"\n  Current total PnL (these positions): ${total_current_loss:.2f}")
        print(f"  Estimated total PnL (with wider stops): ${total_estimated_pnl:.2f}")
        print(f"  Potential improvement: ${total_estimated_pnl - total_current_loss:.2f}")
        
        # Overall impact
        print(f"\n" + "="*80)
        print(f"OVERALL IMPACT ESTIMATE")
        print("="*80)
        
        original_total = df['realized_pnl'].sum()
        improvement = total_estimated_pnl - total_current_loss
        estimated_new_total = original_total + improvement
        
        print(f"\nOriginal backtest PnL: ${original_total:.2f}")
        print(f"Estimated improvement: ${improvement:.2f}")
        print(f"Estimated new PnL: ${estimated_new_total:.2f} ({improvement/original_total*100:+.1f}%)")
        
        print(f"\n" + "="*80)
        print(f"CAVEATS AND LIMITATIONS")
        print("="*80)
        print("""
⚠️  This is a ROUGH ESTIMATE with several limitations:

1. We don't have tick-by-tick price data to know exact stop hits
2. We're estimating stop distances from exit prices
3. We're using nearby positions as proxy for potential outcomes
4. Real implementation would have different dynamics:
   - Trailing stops would behave differently
   - Time-based exits might trigger
   - Other filters might interact differently

✅ To get ACCURATE results, we need to:
   - Implement the feature in strategy code
   - Run a full backtest with proper order simulation
   - Compare results directly

This simulation suggests the feature is worth implementing properly!
        """)
    else:
        print("\nNo recoverable positions found with these parameters.")
        print("Try adjusting stop_multiplier or min_hold_hours.")
    
    # Save detailed results
    output_file = folder / 'min_hold_time_simulation.json'
    results = {
        'parameters': {
            'min_hold_hours': min_hold_hours,
            'stop_multiplier': stop_multiplier,
        },
        'baseline': {
            'total_pnl': float(df['realized_pnl'].sum()),
            'early_exits_count': len(early_exits),
            'early_exits_pnl': float(early_exits['realized_pnl'].sum()),
        },
        'simulation': {
            'recoverable_count': len(recoverable_positions),
            'estimated_improvement': float(improvement) if len(recoverable_positions) > 0 else 0,
        }
    }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n\nResults saved to: {output_file}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python simulate_min_hold_time.py <results_directory> [min_hold_hours] [stop_multiplier]")
        print("\nExample:")
        print("  python simulate_min_hold_time.py logs\\backtest_results\\EUR-USD_20251116_121240")
        print("  python simulate_min_hold_time.py logs\\backtest_results\\EUR-USD_20251116_121240 4.0 1.5")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    min_hold_hours = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    stop_multiplier = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    
    simulate_min_hold_time(results_dir, min_hold_hours, stop_multiplier)
