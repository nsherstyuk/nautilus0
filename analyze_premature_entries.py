"""
Analyze premature entry patterns by comparing SL=1.2 vs SL=1.4 backtest results.

Goal: Identify trades that failed with tight SL but would have succeeded with wider SL,
then analyze what features/patterns distinguish these premature entries.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# Paths to backtest results
SL_14_PATH = Path("backtest_results/MTF_V2_REPLAY_20260103_204423mr25-sl1.4tp0.6")
SL_12_PATH = Path("backtest_results/MTF_V2_REPLAY_20260103_205633mr25sl1.2tp0.6nostall")

def load_trades(path: Path) -> pd.DataFrame:
    """Load trades.csv with proper parsing."""
    trades = pd.read_csv(path / "trades.csv")
    
    # Parse timestamps
    if 'entry_time' in trades.columns:
        trades['entry_time'] = pd.to_datetime(trades['entry_time'])
        trades['entry_hour'] = trades['entry_time'].dt.hour
        trades['entry_weekday'] = trades['entry_time'].dt.day_name()
    
    if 'exit_time' in trades.columns:
        trades['exit_time'] = pd.to_datetime(trades['exit_time'])
    
    return trades

def load_positions(path: Path) -> pd.DataFrame:
    """Load positions.csv with proper parsing."""
    positions = pd.read_csv(path / "positions.csv")
    
    if 'ts_opened' in positions.columns:
        positions['ts_opened'] = pd.to_datetime(positions['ts_opened'])
    if 'ts_closed' in positions.columns:
        positions['ts_closed'] = pd.to_datetime(positions['ts_closed'])
    
    return positions

def compare_backtests():
    """Compare SL=1.2 vs SL=1.4 results."""
    
    print("=" * 80)
    print("PREMATURE ENTRY ANALYSIS: SL=1.2 vs SL=1.4")
    print("=" * 80)
    print()
    
    # Load data
    print("Loading backtest data...")
    trades_14 = load_trades(SL_14_PATH)
    trades_12 = load_trades(SL_12_PATH)
    
    print(f"SL=1.4: {len(trades_14)} trades")
    print(f"SL=1.2: {len(trades_12)} trades")
    print()
    
    # Summary statistics
    print("=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)
    
    def print_stats(df, label):
        total_pnl = df['pnl'].sum() if 'pnl' in df.columns else 0
        wins = len(df[df['exit_reason'] == 'TP']) if 'exit_reason' in df.columns else 0
        losses = len(df[df['exit_reason'] == 'SL']) if 'exit_reason' in df.columns else 0
        win_rate = wins / len(df) * 100 if len(df) > 0 else 0
        
        print(f"\n{label}:")
        print(f"  Total PnL: ${total_pnl:,.2f}")
        print(f"  Wins: {wins} | Losses: {losses}")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg Win: ${df[df['exit_reason']=='TP']['pnl'].mean():.2f}" if wins > 0 else "  Avg Win: N/A")
        print(f"  Avg Loss: ${df[df['exit_reason']=='SL']['pnl'].mean():.2f}" if losses > 0 else "  Avg Loss: N/A")
    
    print_stats(trades_14, "SL=1.4")
    print_stats(trades_12, "SL=1.2")
    
    # Identify premature entries
    print()
    print("=" * 80)
    print("PREMATURE ENTRY IDENTIFICATION")
    print("=" * 80)
    
    # Match trades by entry time (within 1 minute tolerance)
    matched_trades = []
    
    for idx_12, trade_12 in trades_12.iterrows():
        if 'entry_time' not in trade_12 or pd.isna(trade_12['entry_time']):
            continue
            
        # Find corresponding trade in SL=1.4 backtest
        time_diff = abs(trades_14['entry_time'] - trade_12['entry_time'])
        closest_idx = time_diff.idxmin()
        
        if time_diff[closest_idx] < pd.Timedelta(minutes=1):
            trade_14 = trades_14.loc[closest_idx]
            
            matched_trades.append({
                'entry_time': trade_12['entry_time'],
                'exit_time_sl12': trade_12.get('exit_time'),
                'exit_time_sl14': trade_14.get('exit_time'),
                'entry_hour': trade_12.get('entry_hour', trade_12['entry_time'].hour),
                'entry_weekday': trade_12.get('entry_weekday', trade_12['entry_time'].day_name()),
                'side': trade_12.get('side', 'UNKNOWN'),
                'entry_price': trade_12.get('entry', np.nan),
                'exit_price_sl12': trade_12.get('exit', np.nan),
                'exit_price_sl14': trade_14.get('exit', np.nan),
                'result_sl12': trade_12.get('exit_reason', 'UNKNOWN'),
                'result_sl14': trade_14.get('exit_reason', 'UNKNOWN'),
                'pnl_sl12': trade_12.get('pnl', 0),
                'pnl_sl14': trade_14.get('pnl', 0),
                'duration_bars_sl12': trade_12.get('duration_bars', 0),
                'duration_bars_sl14': trade_14.get('duration_bars', 0),
            })
    
    matched_df = pd.DataFrame(matched_trades)
    print(f"\nMatched {len(matched_df)} trades between both backtests")
    
    # Categorize trades
    matched_df['category'] = 'OTHER'
    
    # Premature entries: Lost with SL=1.2 but won with SL=1.4
    premature_mask = (matched_df['result_sl12'] == 'SL') & (matched_df['result_sl14'] == 'TP')
    matched_df.loc[premature_mask, 'category'] = 'PREMATURE'
    
    # Good entries: Won with both
    good_mask = (matched_df['result_sl12'] == 'TP') & (matched_df['result_sl14'] == 'TP')
    matched_df.loc[good_mask, 'category'] = 'GOOD'
    
    # Bad entries: Lost with both
    bad_mask = (matched_df['result_sl12'] == 'SL') & (matched_df['result_sl14'] == 'SL')
    matched_df.loc[bad_mask, 'category'] = 'BAD'
    
    # Improved entries: Lost with SL=1.2, still lost with SL=1.4 but smaller loss
    improved_mask = (matched_df['result_sl12'] == 'SL') & (matched_df['result_sl14'] == 'SL') & (matched_df['pnl_sl14'] > matched_df['pnl_sl12'])
    matched_df.loc[improved_mask, 'category'] = 'IMPROVED'
    
    print(f"\nTrade Categories:")
    print(f"  PREMATURE (SL=1.2 loss → SL=1.4 win): {premature_mask.sum()} trades")
    print(f"  GOOD (won with both): {good_mask.sum()} trades")
    print(f"  BAD (lost with both): {bad_mask.sum()} trades")
    print(f"  IMPROVED (smaller loss with SL=1.4): {improved_mask.sum()} trades")
    
    # Calculate impact
    premature_pnl_loss = matched_df[premature_mask]['pnl_sl12'].sum()
    premature_pnl_gain = matched_df[premature_mask]['pnl_sl14'].sum()
    premature_impact = premature_pnl_gain - premature_pnl_loss
    
    print(f"\nPremature Entry Impact:")
    print(f"  Lost with SL=1.2: ${premature_pnl_loss:,.2f}")
    print(f"  Won with SL=1.4: ${premature_pnl_gain:,.2f}")
    print(f"  Net Impact: ${premature_impact:,.2f}")
    
    # Save matched trades
    output_path = Path("backtest_results/premature_entry_analysis.csv")
    matched_df.to_csv(output_path, index=False)
    print(f"\nSaved matched trades to: {output_path}")
    
    return matched_df

def analyze_features(matched_df: pd.DataFrame):
    """Analyze price action patterns for different trade categories."""
    
    print()
    print("=" * 80)
    print("PRICE ACTION ANALYSIS")
    print("=" * 80)
    
    premature = matched_df[matched_df['category'] == 'PREMATURE']
    good = matched_df[matched_df['category'] == 'GOOD']
    bad = matched_df[matched_df['category'] == 'BAD']
    
    if len(premature) == 0:
        print("\nNo premature entries found!")
        return
    
    print(f"\nComparing trade categories:")
    print(f"  PREMATURE: {len(premature)} trades (SL=1.2 loss → SL=1.4 win)")
    print(f"  GOOD: {len(good)} trades (won with both)")
    print(f"  BAD: {len(bad)} trades (lost with both)")
    print()
    
    # Analyze price excursion for premature entries
    print("PREMATURE ENTRY CHARACTERISTICS:")
    print("-" * 80)
    
    for idx, trade in premature.iterrows():
        entry = trade['entry_price']
        exit_sl12 = trade['exit_price_sl12']
        exit_sl14 = trade['exit_price_sl14']
        side = trade['side']
        
        # Calculate excursion (how far against us before winning)
        if side == 'LONG':
            adverse_move = (exit_sl12 - entry) * 10000  # pips
            favorable_move = (exit_sl14 - entry) * 10000
        else:  # SHORT
            adverse_move = (entry - exit_sl12) * 10000
            favorable_move = (entry - exit_sl14) * 10000
        
        print(f"  {trade['entry_time']} | {side:5s} | Adverse: {adverse_move:+6.1f} pips | Final: {favorable_move:+6.1f} pips | PnL: ${trade['pnl_sl12']:+6.1f} → ${trade['pnl_sl14']:+6.1f}")
    
    # Calculate average excursions
    print()
    print("AVERAGE PRICE MOVEMENTS:")
    print("-" * 80)
    
    def calc_excursions(df):
        excursions = []
        for idx, trade in df.iterrows():
            entry = trade['entry_price']
            exit_price = trade['exit_price_sl12']
            side = trade['side']
            
            if pd.notna(entry) and pd.notna(exit_price):
                if side == 'LONG':
                    move = (exit_price - entry) * 10000
                else:
                    move = (entry - exit_price) * 10000
                excursions.append(move)
        return excursions
    
    prem_excursions = calc_excursions(premature)
    good_excursions = calc_excursions(good)
    bad_excursions = calc_excursions(bad)
    
    if prem_excursions:
        print(f"  PREMATURE avg adverse move: {np.mean(prem_excursions):.2f} pips (std: {np.std(prem_excursions):.2f})")
    if good_excursions:
        print(f"  GOOD avg move: {np.mean(good_excursions):.2f} pips (std: {np.std(good_excursions):.2f})")
    if bad_excursions:
        print(f"  BAD avg adverse move: {np.mean(bad_excursions):.2f} pips (std: {np.std(bad_excursions):.2f})")

def analyze_by_hour_weekday(matched_df: pd.DataFrame):
    """Analyze premature entries by hour and weekday."""
    
    print()
    print("=" * 80)
    print("TEMPORAL ANALYSIS")
    print("=" * 80)
    
    premature = matched_df[matched_df['category'] == 'PREMATURE']
    
    if len(premature) == 0:
        return
    
    # By hour
    print("\nPremature Entries by Hour:")
    hour_counts = premature['entry_hour'].value_counts().sort_index()
    for hour, count in hour_counts.items():
        total_hour = len(matched_df[matched_df['entry_hour'] == hour])
        pct = count / total_hour * 100 if total_hour > 0 else 0
        print(f"  Hour {hour:2d}: {count:3d} premature / {total_hour:3d} total ({pct:5.1f}%)")
    
    # By weekday
    print("\nPremature Entries by Weekday:")
    weekday_counts = premature['entry_weekday'].value_counts()
    for weekday, count in weekday_counts.items():
        total_weekday = len(matched_df[matched_df['entry_weekday'] == weekday])
        pct = count / total_weekday * 100 if total_weekday > 0 else 0
        print(f"  {weekday:10s}: {count:3d} premature / {total_weekday:3d} total ({pct:5.1f}%)")

def main():
    """Main analysis function."""
    
    # Compare backtests and identify premature entries
    matched_df = compare_backtests()
    
    # Analyze features
    analyze_features(matched_df)
    
    # Temporal analysis
    analyze_by_hour_weekday(matched_df)
    
    print()
    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Review premature_entry_analysis.csv for detailed trade data")
    print("2. Review feature_comparison.csv for feature differences")
    print("3. Identify features with largest differences between premature vs good entries")
    print("4. Consider adding new features or entry confirmation logic")

if __name__ == "__main__":
    main()
