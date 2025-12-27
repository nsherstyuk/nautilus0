"""
Interactive visualization of MTF v2 replay backtest results.

This script creates interactive Plotly charts showing:
- Price action (1-minute candlesticks)
- Trade entry/exit markers with P&L
- Stop loss and take profit levels
- Position tracking
- Cumulative P&L overlay

Usage:
    python visualize_replay_backtest.py <backtest_results_folder>
    
Example:
    python visualize_replay_backtest.py "backtest_results/MTF_V2_REPLAY_20251227_133941"
    python visualize_replay_backtest.py "optimization_results/optimization_results_20251226_151345/OPT_SL0.8_TP0.8_TR0.4_TH0.65_151347"
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import argparse

PROJECT_ROOT = Path(__file__).parent

# Add project root to path for imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId


def load_bar_data_from_catalog(symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Load 1-minute bar data from NautilusTrader catalog."""
    
    print(f"Loading bar data from catalog for {symbol} ({start_date.date()} to {end_date.date()})...")
    
    # Initialize catalog
    catalog_path = str(PROJECT_ROOT / "data" / "catalog")
    catalog = ParquetDataCatalog(catalog_path)
    
    # Construct instrument and bar type strings
    if symbol == "EURUSD":
        instrument_str = "EUR/USD.IDEALPRO"
    else:
        # Add more symbol mappings as needed
        instrument_str = f"{symbol}.IDEALPRO"
    
    bar_type_str = f"{instrument_str}-1-MINUTE-MID-INTERNAL"
    
    try:
        # Query bars from catalog
        instrument_id = InstrumentId.from_str(instrument_str)
        bar_type = BarType.from_str(bar_type_str)
        
        bars = catalog.bars(
            bar_type=bar_type_str,
            start=start_date,
            end=end_date,
        )
        
        if not bars:
            raise ValueError(f"No bars returned from catalog for {bar_type_str}")
        
        # Convert to DataFrame
        data = []
        for bar in bars:
            data.append({
                'timestamp': pd.Timestamp(bar.ts_init, unit='ns', tz='UTC'),
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': float(bar.volume),
            })
        
        df = pd.DataFrame(data)
        df = df.set_index('timestamp')
        df = df.sort_index()
        
        print(f"  ✓ Loaded {len(df)} bars from catalog")
        return df
        
    except Exception as e:
        print(f"  ✗ Error loading from catalog: {e}")
        raise


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
        print(f"  Win rate: {(trades['pnl'] > 0).sum() / len(trades) * 100:.1f}%")
    
    return fills, trades


def create_interactive_chart(bars: pd.DataFrame, fills: pd.DataFrame, trades: pd.DataFrame, 
                            output_file: str, title: str):
    """Create interactive Plotly chart with all trade information."""
    
    print(f"\nCreating interactive chart...")
    
    # Create figure with secondary y-axis for P&L
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=(f'{title} - Price Action & Trades', 'Cumulative P&L'),
        row_heights=[0.7, 0.3],
    )
    
    # Add candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=bars.index,
            open=bars['open'],
            high=bars['high'],
            low=bars['low'],
            close=bars['close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
        ),
        row=1, col=1
    )
    
    if trades is not None and len(trades) > 0:
        # Add entry markers
        long_entries = trades[trades['side'] == 'LONG']
        short_entries = trades[trades['side'] == 'SHORT']
        
        if len(long_entries) > 0:
            fig.add_trace(
                go.Scatter(
                    x=long_entries['entry_time'],
                    y=long_entries['entry'],
                    mode='markers',
                    name='Long Entry',
                    marker=dict(
                        symbol='triangle-up',
                        size=12,
                        color='#00ff00',
                        line=dict(width=1, color='darkgreen')
                    ),
                    text=[f"LONG<br>Entry: {row['entry']:.5f}<br>Time: {row['entry_time']}" 
                          for _, row in long_entries.iterrows()],
                    hovertemplate='<b>%{text}</b><extra></extra>',
                ),
                row=1, col=1
            )
        
        if len(short_entries) > 0:
            fig.add_trace(
                go.Scatter(
                    x=short_entries['entry_time'],
                    y=short_entries['entry'],
                    mode='markers',
                    name='Short Entry',
                    marker=dict(
                        symbol='triangle-down',
                        size=12,
                        color='#ff6b6b',
                        line=dict(width=1, color='darkred')
                    ),
                    text=[f"SHORT<br>Entry: {row['entry']:.5f}<br>Time: {row['entry_time']}" 
                          for _, row in short_entries.iterrows()],
                    hovertemplate='<b>%{text}</b><extra></extra>',
                ),
                row=1, col=1
            )
        
        # Add exit markers with P&L info
        for _, trade in trades.iterrows():
            color = '#4caf50' if trade['pnl'] > 0 else '#f44336'
            symbol = 'circle' if trade['exit_reason'] == 'TP' else ('x' if trade['exit_reason'] == 'SL' else 'square')
            
            fig.add_trace(
                go.Scatter(
                    x=[trade['exit_time']],
                    y=[trade['exit']],
                    mode='markers+text',
                    name=f"Exit ({trade['exit_reason']})",
                    marker=dict(
                        symbol=symbol,
                        size=12,
                        color=color,
                        line=dict(width=2, color='white')
                    ),
                    text=[f"${trade['pnl']:.2f}"],
                    textposition='top center',
                    textfont=dict(size=8, color=color),
                    hovertemplate=f"<b>Exit ({trade['exit_reason']})</b><br>" +
                                f"Exit: {trade['exit']:.5f}<br>" +
                                f"P&L: ${trade['pnl']:.2f}<br>" +
                                f"Duration: {trade['duration_bars']} bars<extra></extra>",
                    showlegend=False,
                ),
                row=1, col=1
            )
            
            # Draw lines connecting entry to exit
            line_color = 'rgba(76, 175, 80, 0.3)' if trade['pnl'] > 0 else 'rgba(244, 67, 54, 0.3)'
            fig.add_trace(
                go.Scatter(
                    x=[trade['entry_time'], trade['exit_time']],
                    y=[trade['entry'], trade['exit']],
                    mode='lines',
                    line=dict(color=line_color, width=1, dash='dot'),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=1, col=1
            )
        
        # Calculate and plot cumulative P&L
        trades_sorted = trades.sort_values('exit_time')
        trades_sorted['cumulative_pnl'] = trades_sorted['pnl'].cumsum()
        
        fig.add_trace(
            go.Scatter(
                x=trades_sorted['exit_time'],
                y=trades_sorted['cumulative_pnl'],
                mode='lines',
                name='Cumulative P&L',
                line=dict(color='#2196f3', width=2),
                fill='tozeroy',
                fillcolor='rgba(33, 150, 243, 0.1)',
                hovertemplate='<b>Cumulative P&L</b><br>$%{y:.2f}<extra></extra>',
            ),
            row=2, col=1
        )
        
        # Add zero line for P&L
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=20)
        ),
        xaxis_rangeslider_visible=False,
        hovermode='x unified',
        height=900,
        template='plotly_dark',
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(0,0,0,0.5)",
        ),
    )
    
    # Update axes
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="P&L ($)", row=2, col=1)
    
    # Save to HTML
    output_path = PROJECT_ROOT / output_file
    fig.write_html(str(output_path))
    print(f"\n✓ Chart saved to: {output_path}")
    print(f"  Open in your browser: file:///{output_path.absolute()}")
    
    return fig


def main():
    parser = argparse.ArgumentParser(
        description='Visualize MTF v2 replay backtest results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python visualize_replay_backtest.py "backtest_results/MTF_V2_REPLAY_20251227_133941"
  python visualize_replay_backtest.py "optimization_results/optimization_results_20251226_151345/OPT_SL0.8_TP0.8_TR0.4_TH0.65_151347"
  python visualize_replay_backtest.py "optimization_results/optimization_results_20251226_151345/OPT_SL0.8_TP0.8_TR0.4_TH0.65_151347" --symbol EURUSD --start "2025-01-02" --end "2025-01-31"
        """
    )
    parser.add_argument('results_folder', type=str, help='Path to backtest results folder')
    parser.add_argument('--symbol', type=str, default='EURUSD', help='Symbol to visualize (default: EURUSD)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD) - if not provided, uses trades min date')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD) - if not provided, uses trades max date')
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
    
    # Determine date range
    if args.start:
        start_date = pd.to_datetime(args.start, utc=True)
    elif trades is not None and len(trades) > 0:
        start_date = trades['entry_time'].min() - timedelta(hours=1)
    else:
        print("Error: No trades found and no --start date provided")
        sys.exit(1)
    
    if args.end:
        end_date = pd.to_datetime(args.end, utc=True)
    elif trades is not None and len(trades) > 0:
        end_date = trades['exit_time'].max() + timedelta(hours=1)
    else:
        print("Error: No trades found and no --end date provided")
        sys.exit(1)
    
    # Load bar data
    try:
        bars = load_bar_data_from_catalog(args.symbol, start_date, end_date)
    except Exception as e:
        print(f"Error loading bar data: {e}")
        sys.exit(1)
    
    # Generate output filename
    if args.output:
        output_file = args.output
    else:
        folder_name = results_folder.name
        output_file = f"visualizations/{folder_name}_chart.html"
    
    # Create output directory if needed
    output_path = PROJECT_ROOT / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create chart
    title = f"MTF V2 Replay - {results_folder.name}"
    create_interactive_chart(bars, fills, trades, output_file, title)
    
    print("\n✓ Visualization complete!")


if __name__ == "__main__":
    main()
