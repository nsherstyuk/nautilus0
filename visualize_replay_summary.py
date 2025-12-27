"""
Create summary visualization showing key trades and performance metrics.

This is faster than full visualization and focuses on:
- Trade timeline with P&L
- Performance metrics dashboard
- Win/loss distribution
- Drawdown visualization

Usage:
    python visualize_replay_summary.py <backtest_results_folder>
"""

import sys
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import argparse

PROJECT_ROOT = Path(__file__).parent


def load_backtest_results(results_folder: Path):
    """Load fills and trades from backtest results folder."""
    fills_path = results_folder / "fills.csv"
    trades_path = results_folder / "trades.csv"
    
    if not fills_path.exists():
        raise FileNotFoundError(f"fills.csv not found in {results_folder}")
    
    print(f"\nLoading backtest results from: {results_folder.name}")
    
    # Load fills
    fills = pd.read_csv(fills_path)
    fills['ts_event'] = pd.to_datetime(fills['ts_event'], utc=True)
    print(f"  Fills: {len(fills)} executions")
    
    # Load trades if exists
    trades = None
    if trades_path.exists():
        trades = pd.read_csv(trades_path)
        trades['entry_time'] = pd.to_datetime(trades['entry_time'], utc=True)
        trades['exit_time'] = pd.to_datetime(trades['exit_time'], utc=True)
        print(f"  Trades: {len(trades)} completed trades")
        print(f"  Total P&L: ${trades['pnl'].sum():.2f}")
        win_rate = (trades['pnl'] > 0).sum() / len(trades) * 100
        print(f"  Win rate: {win_rate:.1f}%")
    
    return fills, trades


def calculate_metrics(trades: pd.DataFrame) -> dict:
    """Calculate key performance metrics."""
    winning_trades = trades[trades['pnl'] > 0]
    losing_trades = trades[trades['pnl'] <= 0]
    
    metrics = {
        'total_trades': len(trades),
        'total_pnl': trades['pnl'].sum(),
        'win_rate': len(winning_trades) / len(trades) * 100,
        'avg_win': winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0,
        'avg_loss': losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0,
        'largest_win': trades['pnl'].max(),
        'largest_loss': trades['pnl'].min(),
        'profit_factor': winning_trades['pnl'].sum() / abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else float('inf'),
    }
    
    # Calculate drawdown
    trades_sorted = trades.sort_values('exit_time')
    trades_sorted['cumulative_pnl'] = trades_sorted['pnl'].cumsum()
    trades_sorted['peak'] = trades_sorted['cumulative_pnl'].cummax()
    trades_sorted['drawdown'] = trades_sorted['cumulative_pnl'] - trades_sorted['peak']
    
    metrics['max_drawdown'] = trades_sorted['drawdown'].min()
    metrics['max_drawdown_pct'] = (metrics['max_drawdown'] / trades_sorted['peak'].max() * 100) if trades_sorted['peak'].max() > 0 else 0
    
    return metrics


def create_summary_chart(trades: pd.DataFrame, metrics: dict, output_file: str, title: str):
    """Create comprehensive summary visualization."""
    
    print(f"\nCreating summary visualization...")
    
    # Create subplots
    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=(
            'Cumulative P&L', 
            'P&L Distribution',
            'Drawdown', 
            'Win/Loss Ratio by Exit Reason',
            'Trade Timeline',
            'Performance by Hour'
        ),
        specs=[
            [{"type": "scatter"}, {"type": "histogram"}],
            [{"type": "scatter"}, {"type": "bar"}],
            [{"type": "scatter", "colspan": 2}, None],
            [{"type": "bar", "colspan": 2}, None],
        ],
        vertical_spacing=0.08,
        horizontal_spacing=0.12,
        row_heights=[0.25, 0.25, 0.25, 0.25],
    )
    
    trades_sorted = trades.sort_values('exit_time')
    trades_sorted['cumulative_pnl'] = trades_sorted['pnl'].cumsum()
    
    # 1. Cumulative P&L
    fig.add_trace(
        go.Scatter(
            x=trades_sorted['exit_time'],
            y=trades_sorted['cumulative_pnl'],
            mode='lines',
            name='Cumulative P&L',
            line=dict(color='#2196f3', width=2),
            fill='tozeroy',
            fillcolor='rgba(33, 150, 243, 0.1)',
        ),
        row=1, col=1
    )
    
    # 2. P&L Distribution
    fig.add_trace(
        go.Histogram(
            x=trades['pnl'],
            nbinsx=50,
            name='P&L Distribution',
            marker=dict(
                color=trades['pnl'],
                colorscale=[[0, '#ef5350'], [0.5, '#ffeb3b'], [1, '#4caf50']],
                cmin=trades['pnl'].min(),
                cmax=trades['pnl'].max(),
            ),
        ),
        row=1, col=2
    )
    
    # 3. Drawdown
    trades_sorted['peak'] = trades_sorted['cumulative_pnl'].cummax()
    trades_sorted['drawdown'] = trades_sorted['cumulative_pnl'] - trades_sorted['peak']
    
    fig.add_trace(
        go.Scatter(
            x=trades_sorted['exit_time'],
            y=trades_sorted['drawdown'],
            mode='lines',
            name='Drawdown',
            line=dict(color='#f44336', width=2),
            fill='tozeroy',
            fillcolor='rgba(244, 67, 54, 0.2)',
        ),
        row=2, col=1
    )
    
    # 4. Win/Loss by Exit Reason
    exit_stats = trades.groupby('exit_reason').agg({
        'pnl': ['count', lambda x: (x > 0).sum(), lambda x: (x <= 0).sum()]
    }).reset_index()
    exit_stats.columns = ['exit_reason', 'total', 'wins', 'losses']
    
    fig.add_trace(
        go.Bar(
            x=exit_stats['exit_reason'],
            y=exit_stats['wins'],
            name='Wins',
            marker_color='#4caf50',
        ),
        row=2, col=2
    )
    fig.add_trace(
        go.Bar(
            x=exit_stats['exit_reason'],
            y=exit_stats['losses'],
            name='Losses',
            marker_color='#f44336',
        ),
        row=2, col=2
    )
    
    # 5. Trade Timeline
    colors = ['#4caf50' if pnl > 0 else '#f44336' for pnl in trades_sorted['pnl']]
    fig.add_trace(
        go.Scatter(
            x=trades_sorted['exit_time'],
            y=trades_sorted['pnl'],
            mode='markers',
            name='Individual Trades',
            marker=dict(
                size=6,
                color=colors,
                opacity=0.6,
            ),
        ),
        row=3, col=1
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=3, col=1)
    
    # 6. Performance by Hour
    if 'entry_hour' in trades.columns:
        hourly_stats = trades.groupby('entry_hour').agg({
            'pnl': ['sum', 'count']
        }).reset_index()
        hourly_stats.columns = ['hour', 'total_pnl', 'count']
        
        fig.add_trace(
            go.Bar(
                x=hourly_stats['hour'],
                y=hourly_stats['total_pnl'],
                name='P&L by Hour',
                marker=dict(
                    color=hourly_stats['total_pnl'],
                    colorscale=[[0, '#ef5350'], [0.5, '#ffeb3b'], [1, '#4caf50']],
                ),
                text=[f"${pnl:.0f}<br>({cnt} trades)" for pnl, cnt in zip(hourly_stats['total_pnl'], hourly_stats['count'])],
                textposition='outside',
            ),
            row=4, col=1
        )
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=4, col=1)
    
    # Update layout
    annotations_text = (
        f"<b>Performance Summary</b><br>"
        f"Total Trades: {metrics['total_trades']}<br>"
        f"Total P&L: ${metrics['total_pnl']:.2f}<br>"
        f"Win Rate: {metrics['win_rate']:.1f}%<br>"
        f"Avg Win: ${metrics['avg_win']:.2f}<br>"
        f"Avg Loss: ${metrics['avg_loss']:.2f}<br>"
        f"Profit Factor: {metrics['profit_factor']:.2f}<br>"
        f"Max Drawdown: ${metrics['max_drawdown']:.2f} ({metrics['max_drawdown_pct']:.1f}%)<br>"
        f"Largest Win: ${metrics['largest_win']:.2f}<br>"
        f"Largest Loss: ${metrics['largest_loss']:.2f}"
    )
    
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=20)
        ),
        height=1400,
        template='plotly_dark',
        showlegend=True,
        annotations=[
            dict(
                text=annotations_text,
                xref="paper", yref="paper",
                x=1.02, y=0.98,
                xanchor="left", yanchor="top",
                showarrow=False,
                font=dict(size=11, family="Courier New, monospace"),
                bgcolor="rgba(0,0,0,0.7)",
                bordercolor="white",
                borderwidth=1,
                borderpad=10,
            )
        ]
    )
    
    # Update axes labels
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_yaxes(title_text="Cumulative P&L ($)", row=1, col=1)
    fig.update_xaxes(title_text="P&L ($)", row=1, col=2)
    fig.update_yaxes(title_text="Count", row=1, col=2)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text="Drawdown ($)", row=2, col=1)
    fig.update_xaxes(title_text="Exit Reason", row=2, col=2)
    fig.update_yaxes(title_text="Count", row=2, col=2)
    fig.update_xaxes(title_text="Time", row=3, col=1)
    fig.update_yaxes(title_text="Trade P&L ($)", row=3, col=1)
    fig.update_xaxes(title_text="Hour (UTC)", row=4, col=1)
    fig.update_yaxes(title_text="Total P&L ($)", row=4, col=1)
    
    # Save to HTML
    output_path = PROJECT_ROOT / output_file
    fig.write_html(str(output_path))
    print(f"\n✓ Summary chart saved to: {output_path}")
    print(f"  Open in your browser to view the interactive dashboard")
    
    return fig


def main():
    parser = argparse.ArgumentParser(
        description='Create summary visualization of MTF v2 replay backtest results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('results_folder', type=str, help='Path to backtest results folder')
    parser.add_argument('--output', type=str, help='Output HTML filename (default: auto-generated)')
    
    args = parser.parse_args()
    
    # Resolve results folder
    results_folder = PROJECT_ROOT / args.results_folder
    if not results_folder.exists():
        print(f"Error: Results folder not found: {results_folder}")
        sys.exit(1)
    
    # Load backtest results
    try:
        fills, trades = load_backtest_results(results_folder)
    except Exception as e:
        print(f"Error loading backtest results: {e}")
        sys.exit(1)
    
    if trades is None or len(trades) == 0:
        print("Error: No trades found in results")
        sys.exit(1)
    
    # Calculate metrics
    metrics = calculate_metrics(trades)
    
    # Generate output filename
    if args.output:
        output_file = args.output
    else:
        folder_name = results_folder.name
        output_file = f"visualizations/{folder_name}_summary.html"
    
    # Create output directory if needed
    output_path = PROJECT_ROOT / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create chart
    title = f"MTF V2 Replay Summary - {results_folder.name}"
    create_summary_chart(trades, metrics, output_file, title)
    
    print("\n✓ Summary visualization complete!")
    print(f"\nKey Metrics:")
    print(f"  Total P&L: ${metrics['total_pnl']:.2f}")
    print(f"  Win Rate: {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown: ${metrics['max_drawdown']:.2f}")


if __name__ == "__main__":
    main()
