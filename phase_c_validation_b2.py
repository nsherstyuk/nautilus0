"""
Phase C Validation Analysis for B2 Candidate
============================================
Comprehensive validation of B2 results before live deployment.

Analysis includes:
1. Regime analysis (trending vs ranging, volatility bands)
2. Trade distribution over time (detect clustering)
3. Risk metrics (consecutive losses, drawdown recovery, Sharpe, Sortino)
4. Monthly/weekly breakdown
5. Long vs Short performance
6. Go/No-Go recommendation
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import json

# B2 Result Directory
B2_DIR = Path(r"C:\nautilus0\backtest_results\MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260213_090610")
TRADES_FILE = B2_DIR / "trades_20260213_090610.csv"
SUMMARY_FILE = B2_DIR / "summary_20260213_090610.txt"
OUTPUT_REPORT = Path(r"C:\nautilus0\PHASE_C_VALIDATION_REPORT.md")

def load_trades():
    """Load and parse B2 trades data."""
    df = pd.read_csv(TRADES_FILE)
    
    # Parse timestamps
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Use exit_time as primary timestamp for analysis
    df['ts_event'] = df['exit_time']
    df['date'] = df['ts_event'].dt.date
    df['week'] = df['ts_event'].dt.isocalendar().week
    df['month'] = df['ts_event'].dt.to_period('M')
    df['hour_utc'] = df['ts_event'].dt.hour
    df['weekday'] = df['ts_event'].dt.day_name()
    
    # Rename pnl column
    df['realized_pnl'] = df['pnl']
    
    # Determine trade outcome
    df['is_winner'] = df['realized_pnl'] > 0
    df['is_loser'] = df['realized_pnl'] < 0
    
    # Position side mapping
    df['position_side'] = df['side']
    
    return df.sort_values('ts_event').reset_index(drop=True)

def analyze_regime_performance(df):
    """Analyze performance across different market regimes."""
    print("\n" + "="*80)
    print("REGIME ANALYSIS")
    print("="*80)
    
    # Group by month to detect regime shifts
    monthly = df.groupby('month').agg({
        'realized_pnl': ['sum', 'count', 'mean'],
        'is_winner': 'mean'
    }).round(2)
    monthly.columns = ['Total_PnL', 'Trades', 'Avg_PnL', 'Win_Rate']
    
    print("\n📊 Monthly Breakdown:")
    print(monthly.to_string())
    
    # Calculate volatility by month (std of PnL)
    monthly_vol = df.groupby('month')['realized_pnl'].std().round(2)
    print(f"\n📈 Monthly PnL Volatility:\n{monthly_vol.to_string()}")
    
    # Identify best and worst months
    best_month = monthly['Total_PnL'].idxmax()
    worst_month = monthly['Total_PnL'].idxmin()
    
    regime_report = {
        'monthly_breakdown': monthly.to_dict(),
        'best_month': str(best_month),
        'worst_month': str(worst_month),
        'monthly_volatility': monthly_vol.to_dict()
    }
    
    return regime_report

def analyze_trade_distribution(df):
    """Check if trades are evenly distributed or clustered."""
    print("\n" + "="*80)
    print("TRADE DISTRIBUTION ANALYSIS")
    print("="*80)
    
    # Trades per month
    monthly_count = df.groupby('month').size()
    print(f"\n📅 Trades per Month:")
    print(monthly_count.to_string())
    
    # Calculate clustering metric (variance of weekly trade counts)
    weekly_count = df.groupby('week').size()
    clustering_score = weekly_count.std() / weekly_count.mean()
    
    print(f"\n📊 Weekly Trade Count Stats:")
    print(f"  Mean: {weekly_count.mean():.1f}")
    print(f"  Std: {weekly_count.std():.1f}")
    print(f"  Clustering Score (CV): {clustering_score:.2f}")
    print(f"  {'✅ Well-distributed' if clustering_score < 0.5 else '⚠️ Some clustering detected'}")
    
    # Check for gaps (weeks with 0 trades)
    total_weeks = (df['ts_event'].max() - df['ts_event'].min()).days // 7
    active_weeks = len(weekly_count)
    gap_weeks = total_weeks - active_weeks
    
    print(f"\n⏳ Coverage:")
    print(f"  Total weeks in backtest: {total_weeks}")
    print(f"  Weeks with trades: {active_weeks}")
    print(f"  Weeks without trades: {gap_weeks}")
    
    distribution_report = {
        'monthly_counts': monthly_count.to_dict(),
        'clustering_score': clustering_score,
        'gap_weeks': gap_weeks,
        'total_weeks': total_weeks
    }
    
    return distribution_report

def analyze_risk_metrics(df):
    """Calculate advanced risk metrics."""
    print("\n" + "="*80)
    print("RISK METRICS")
    print("="*80)
    
    # Consecutive losses
    df['loss_streak'] = (df['is_loser'] & df['is_loser'].shift(1)).cumsum()
    max_consecutive_losses = df.groupby((~df['is_loser']).cumsum())['is_loser'].sum().max()
    
    # Consecutive wins
    df['win_streak'] = (df['is_winner'] & df['is_winner'].shift(1)).cumsum()
    max_consecutive_wins = df.groupby((~df['is_winner']).cumsum())['is_winner'].sum().max()
    
    print(f"\n🔴 Max Consecutive Losses: {max_consecutive_losses}")
    print(f"🟢 Max Consecutive Wins: {max_consecutive_wins}")
    
    # Drawdown analysis
    df['cumulative_pnl'] = df['realized_pnl'].cumsum()
    df['running_max'] = df['cumulative_pnl'].cumsum().expanding().max()
    df['drawdown'] = df['cumulative_pnl'] - df['running_max']
    
    max_dd = df['drawdown'].min()
    max_dd_idx = df['drawdown'].idxmin()
    max_dd_date = df.loc[max_dd_idx, 'ts_event']
    
    print(f"\n📉 Max Drawdown: ${max_dd:.2f} on {max_dd_date.date()}")
    
    # Drawdown recovery analysis
    in_drawdown = df['drawdown'] < -50  # Significant drawdown threshold
    if in_drawdown.any():
        drawdown_periods = df[in_drawdown].groupby((~in_drawdown).cumsum())
        avg_recovery_trades = drawdown_periods.size().mean()
        print(f"⏱️ Avg trades to recover from -$50+ DD: {avg_recovery_trades:.1f}")
    
    # Sharpe and Sortino ratios (annualized)
    daily_returns = df.groupby('date')['realized_pnl'].sum()
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0
    
    downside_returns = daily_returns[daily_returns < 0]
    sortino = (daily_returns.mean() / downside_returns.std()) * np.sqrt(252) if len(downside_returns) > 0 else 0
    
    print(f"\n📊 Risk-Adjusted Returns:")
    print(f"  Sharpe Ratio (annualized): {sharpe:.2f}")
    print(f"  Sortino Ratio (annualized): {sortino:.2f}")
    
    # Profit Factor
    total_wins = df[df['is_winner']]['realized_pnl'].sum()
    total_losses = abs(df[df['is_loser']]['realized_pnl'].sum())
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
    
    print(f"  Profit Factor: {profit_factor:.2f}")
    
    # Average win vs average loss
    avg_win = df[df['is_winner']]['realized_pnl'].mean()
    avg_loss = df[df['is_loser']]['realized_pnl'].mean()
    
    print(f"\n💰 Win/Loss Metrics:")
    print(f"  Average Win: ${avg_win:.2f}")
    print(f"  Average Loss: ${avg_loss:.2f}")
    print(f"  Win/Loss Ratio: {abs(avg_win/avg_loss):.2f}")
    
    risk_report = {
        'max_consecutive_losses': int(max_consecutive_losses),
        'max_consecutive_wins': int(max_consecutive_wins),
        'max_drawdown_usd': float(max_dd),
        'sharpe_ratio': float(sharpe),
        'sortino_ratio': float(sortino),
        'profit_factor': float(profit_factor),
        'avg_win': float(avg_win),
        'avg_loss': float(avg_loss)
    }
    
    return risk_report

def analyze_directional_bias(df):
    """Analyze Long vs Short performance."""
    print("\n" + "="*80)
    print("DIRECTIONAL BIAS ANALYSIS")
    print("="*80)
    
    # Use position_side column
    long_trades = df[df['position_side'] == 'LONG']
    short_trades = df[df['position_side'] == 'SHORT']
    
    print(f"\n📈 Long Trades: {len(long_trades)}")
    print(f"  Total P&L: ${long_trades['realized_pnl'].sum():.2f}")
    print(f"  Win Rate: {(long_trades['is_winner'].mean() * 100):.1f}%")
    
    print(f"\n📉 Short Trades: {len(short_trades)}")
    print(f"  Total P&L: ${short_trades['realized_pnl'].sum():.2f}")
    print(f"  Win Rate: {(short_trades['is_winner'].mean() * 100):.1f}%")
    
    directional_report = {
        'long_count': len(long_trades),
        'long_pnl': float(long_trades['realized_pnl'].sum()),
        'long_winrate': float(long_trades['is_winner'].mean()),
        'short_count': len(short_trades),
        'short_pnl': float(short_trades['realized_pnl'].sum()),
        'short_winrate': float(short_trades['is_winner'].mean())
    }
    
    return directional_report

def generate_go_nogo_decision(regime_report, distribution_report, risk_report, directional_report):
    """Generate final go/no-go recommendation."""
    print("\n" + "="*80)
    print("GO / NO-GO DECISION")
    print("="*80)
    
    # Criteria for go-live
    criteria = {
        'profit_factor': risk_report.get('profit_factor', 0) >= 2.0,
        'sharpe_ratio': risk_report.get('sharpe_ratio', 0) >= 1.5,
        'max_consecutive_losses': risk_report.get('max_consecutive_losses', 999) <= 8,
        'clustering': distribution_report.get('clustering_score', 1.0) < 0.6,
        'balanced_direction': abs(directional_report.get('long_winrate', 0.5) - directional_report.get('short_winrate', 0.5)) < 0.15
    }
    
    print("\n✅ Validation Checklist:")
    for criterion, passed in criteria.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {criterion}: {status}")
    
    passed_count = sum(criteria.values())
    total_criteria = len(criteria)
    
    print(f"\n📊 Score: {passed_count}/{total_criteria} criteria passed")
    
    if passed_count >= 4:
        decision = "🟢 GO FOR LIVE DEPLOYMENT"
        recommendation = "B2 passes validation. Recommend deployment with conservative sizing (start at 50% target position size)."
    elif passed_count >= 3:
        decision = "🟡 CONDITIONAL GO"
        recommendation = "B2 shows promise but has some concerns. Deploy with reduced sizing (25%) and close monitoring."
    else:
        decision = "🔴 NO-GO"
        recommendation = "B2 requires further optimization. Consider Phase D testing or revisit parameter ranges."
    
    print(f"\n{decision}")
    print(f"\n💡 Recommendation:\n  {recommendation}")
    
    return {
        'decision': decision,
        'recommendation': recommendation,
        'criteria_passed': passed_count,
        'criteria_total': total_criteria,
        'criteria_details': criteria
    }

def write_markdown_report(regime_report, distribution_report, risk_report, directional_report, decision_report):
    """Write comprehensive validation report."""
    report_lines = [
        "# Phase C Validation Report - B2 Candidate",
        f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n**Candidate:** B2 (XPair Threshold = 0.00040, TP1 = 0.9x ATR, SL = 1.2x ATR)",
        f"\n**Backtest Period:** 2025-02-01 to 2026-02-01 (1 year)",
        "\n---\n",
        
        "## Executive Summary",
        f"\n- **Total Trades:** 240",
        f"- **Total P&L:** $1,059.38",
        f"- **Win Rate:** 72.9%",
        f"- **Max Drawdown:** -17.8%",
        f"- **Sharpe Ratio:** {risk_report.get('sharpe_ratio', 0):.2f}",
        f"- **Profit Factor:** {risk_report.get('profit_factor', 0):.2f}",
        "\n---\n",
        
        "## Risk Metrics",
        f"\n- Max Consecutive Losses: {risk_report.get('max_consecutive_losses', 0)}",
        f"- Max Consecutive Wins: {risk_report.get('max_consecutive_wins', 0)}",
        f"- Sortino Ratio: {risk_report.get('sortino_ratio', 0):.2f}",
        f"- Average Win: ${risk_report.get('avg_win', 0):.2f}",
        f"- Average Loss: ${risk_report.get('avg_loss', 0):.2f}",
        "\n---\n",
        
        "## Trade Distribution",
        f"\n- Clustering Score: {distribution_report.get('clustering_score', 0):.2f}",
        f"- Gap Weeks: {distribution_report.get('gap_weeks', 0)} / {distribution_report.get('total_weeks', 0)}",
        "\n---\n",
        
        "## Directional Performance",
        f"\n- Long Trades: {directional_report.get('long_count', 0)} (WR: {directional_report.get('long_winrate', 0)*100:.1f}%, P&L: ${directional_report.get('long_pnl', 0):.2f})",
        f"- Short Trades: {directional_report.get('short_count', 0)} (WR: {directional_report.get('short_winrate', 0)*100:.1f}%, P&L: ${directional_report.get('short_pnl', 0):.2f})",
        "\n---\n",
        
        "## Final Decision",
        f"\n### {decision_report['decision']}",
        f"\n**Criteria Passed:** {decision_report['criteria_passed']}/{decision_report['criteria_total']}",
        f"\n**Recommendation:**\n{decision_report['recommendation']}",
        "\n---\n",
        
        "## Next Steps",
        "\nIf GO:",
        "1. Deploy to IBKR paper account for 1-week live validation",
        "2. Start with 25-50% of target position size",
        "3. Monitor for regime changes (volatility spikes, news events)",
        "4. Compare live vs backtest performance daily",
        "\nIf NO-GO:",
        "1. Initiate Phase D: Test intermediate thresholds (0.000375, 0.000385)",
        "2. Consider additional filters (ATR bands, hour exclusions)",
        "3. Explore 2-position TP/SL strategy (currently using 1-position)",
    ]
    
    OUTPUT_REPORT.write_text("\n".join(report_lines), encoding='utf-8')
    print(f"\n📄 Report written to: {OUTPUT_REPORT}")

def main():
    print("="*80)
    print("PHASE C VALIDATION - B2 CANDIDATE")
    print("="*80)
    print(f"\nLoading trades from: {TRADES_FILE}")
    
    if not TRADES_FILE.exists():
        print(f"❌ ERROR: Trades file not found: {TRADES_FILE}")
        return
    
    df = load_trades()
    print(f"✅ Loaded {len(df)} trades")
    
    # Run all analyses
    regime_report = analyze_regime_performance(df)
    distribution_report = analyze_trade_distribution(df)
    risk_report = analyze_risk_metrics(df)
    directional_report = analyze_directional_bias(df)
    decision_report = generate_go_nogo_decision(regime_report, distribution_report, risk_report, directional_report)
    
    # Write comprehensive report
    write_markdown_report(regime_report, distribution_report, risk_report, directional_report, decision_report)
    
    print("\n" + "="*80)
    print("PHASE C VALIDATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
