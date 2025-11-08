"""
Compare backtest results before and after the position closing fix
"""
import json
import pandas as pd
from pathlib import Path

# Find the two most recent backtest results
files = sorted(
    Path('logs/backtest_results').glob('EUR-USD_*/performance_stats.json'),
    key=lambda x: x.stat().st_mtime,
    reverse=True
)

if len(files) < 2:
    print("Need at least 2 backtest runs to compare")
    exit(1)

# Find the run before fix (has ~617 rejected signals) vs after fix (has ~1135 rejected signals)
latest_file = files[0]  # Most recent (after fix)
# Find the run with ~617 rejected signals (before fix)
prev_file = None
for f in files:
    stats = json.load(open(f))
    if stats["rejected_signals_count"] < 1000:  # Before fix had fewer rejected signals
        prev_file = f
        break

if prev_file is None:
    print("Could not find a backtest run before the fix")
    exit(1)

# Load performance stats
latest_stats = json.load(open(latest_file))
prev_stats = json.load(open(prev_file))

# Load position and order data
latest_positions = pd.read_csv(latest_file.parent / 'positions.csv')
prev_positions = pd.read_csv(prev_file.parent / 'positions.csv')

latest_orders = pd.read_csv(latest_file.parent / 'orders.csv')
prev_orders = pd.read_csv(prev_file.parent / 'orders.csv')

latest_fills = pd.read_csv(latest_file.parent / 'fills.csv')
prev_fills = pd.read_csv(prev_file.parent / 'fills.csv')

print('='*80)
print('BACKTEST COMPARISON: BEFORE FIX vs AFTER FIX')
print('='*80)
print()

print('BEFORE FIX (Previous Run):')
print(f'  Directory: {prev_file.parent.name}')
print(f'  Total PnL: ${prev_stats["pnls"]["PnL (total)"]:,.2f}')
print(f'  Total PnL%: {prev_stats["pnls"]["PnL% (total)"]:.2f}%')
print(f'  Win Rate: {prev_stats["pnls"]["Win Rate"]:.2%}')
sharpe_prev = prev_stats["general"].get("Sharpe Ratio (252 days)", "N/A")
sortino_prev = prev_stats["general"].get("Sortino Ratio (252 days)", "N/A")
profit_factor_prev = prev_stats["general"].get("Profit Factor", "N/A")
print(f'  Sharpe Ratio: {sharpe_prev}')
print(f'  Sortino Ratio: {sortino_prev}')
print(f'  Profit Factor: {profit_factor_prev}')
print(f'  Max Winner: ${prev_stats["pnls"]["Max Winner"]:,.2f}')
print(f'  Max Loser: ${prev_stats["pnls"]["Max Loser"]:,.2f}')
print(f'  Avg Winner: ${prev_stats["pnls"]["Avg Winner"]:,.2f}')
print(f'  Avg Loser: ${prev_stats["pnls"]["Avg Loser"]:,.2f}')
print(f'  Expectancy: ${prev_stats["pnls"]["Expectancy"]:,.2f}')
# Convert ts_closed to numeric for comparison
prev_positions['ts_closed_num'] = pd.to_numeric(prev_positions['ts_closed'], errors='coerce')
latest_positions['ts_closed_num'] = pd.to_numeric(latest_positions['ts_closed'], errors='coerce')

print(f'  Total Positions: {len(prev_positions)}')
print(f'  Closed Positions: {len(prev_positions[prev_positions["ts_closed_num"] > 0])}')
print(f'  Total Orders: {len(prev_orders)}')
print(f'  Total Fills: {len(prev_fills)}')
print(f'  Rejected Signals: {prev_stats["rejected_signals_count"]}')
print()

print('AFTER FIX (Latest Run):')
print(f'  Directory: {latest_file.parent.name}')
print(f'  Total PnL: ${latest_stats["pnls"]["PnL (total)"]:,.2f}')
print(f'  Total PnL%: {latest_stats["pnls"]["PnL% (total)"]:.2f}%')
print(f'  Win Rate: {latest_stats["pnls"]["Win Rate"]:.2%}')
sharpe_latest = latest_stats["general"].get("Sharpe Ratio (252 days)", "N/A")
sortino_latest = latest_stats["general"].get("Sortino Ratio (252 days)", "N/A")
profit_factor_latest = latest_stats["general"].get("Profit Factor", "N/A")
print(f'  Sharpe Ratio: {sharpe_latest}')
print(f'  Sortino Ratio: {sortino_latest}')
print(f'  Profit Factor: {profit_factor_latest}')
print(f'  Max Winner: ${latest_stats["pnls"]["Max Winner"]:,.2f}')
print(f'  Max Loser: ${latest_stats["pnls"]["Max Loser"]:,.2f}')
print(f'  Avg Winner: ${latest_stats["pnls"]["Avg Winner"]:,.2f}')
print(f'  Avg Loser: ${latest_stats["pnls"]["Avg Loser"]:,.2f}')
print(f'  Expectancy: ${latest_stats["pnls"]["Expectancy"]:,.2f}')
print(f'  Total Positions: {len(latest_positions)}')
print(f'  Closed Positions: {len(latest_positions[latest_positions["ts_closed_num"] > 0])}')
print(f'  Total Orders: {len(latest_orders)}')
print(f'  Total Fills: {len(latest_fills)}')
print(f'  Rejected Signals: {latest_stats["rejected_signals_count"]}')
print()

print('='*80)
print('DIFFERENCES')
print('='*80)
pnl_diff = latest_stats["pnls"]["PnL (total)"] - prev_stats["pnls"]["PnL (total)"]
pnl_pct_diff = ((latest_stats["pnls"]["PnL (total)"] / prev_stats["pnls"]["PnL (total)"] - 1) * 100) if prev_stats["pnls"]["PnL (total)"] != 0 else 0
print(f'  PnL Change: ${pnl_diff:+,.2f} ({pnl_pct_diff:+.2f}%)')
print(f'  PnL% Change: {latest_stats["pnls"]["PnL% (total)"] - prev_stats["pnls"]["PnL% (total)"]:+.2f} percentage points')
print(f'  Win Rate Change: {(latest_stats["pnls"]["Win Rate"] - prev_stats["pnls"]["Win Rate"]) * 100:+.2f} percentage points')
if isinstance(sharpe_latest, (int, float)) and isinstance(sharpe_prev, (int, float)):
    print(f'  Sharpe Ratio Change: {sharpe_latest - sharpe_prev:+.3f}')
if isinstance(sortino_latest, (int, float)) and isinstance(sortino_prev, (int, float)):
    print(f'  Sortino Ratio Change: {sortino_latest - sortino_prev:+.3f}')
if isinstance(profit_factor_latest, (int, float)) and isinstance(profit_factor_prev, (int, float)):
    print(f'  Profit Factor Change: {profit_factor_latest - profit_factor_prev:+.3f}')
print(f'  Max Winner Change: ${latest_stats["pnls"]["Max Winner"] - prev_stats["pnls"]["Max Winner"]:+,.2f}')
print(f'  Max Loser Change: ${latest_stats["pnls"]["Max Loser"] - prev_stats["pnls"]["Max Loser"]:+,.2f}')
print(f'  Avg Winner Change: ${latest_stats["pnls"]["Avg Winner"] - prev_stats["pnls"]["Avg Winner"]:+,.2f}')
print(f'  Avg Loser Change: ${latest_stats["pnls"]["Avg Loser"] - prev_stats["pnls"]["Avg Loser"]:+,.2f}')
print(f'  Expectancy Change: ${latest_stats["pnls"]["Expectancy"] - prev_stats["pnls"]["Expectancy"]:+,.2f}')
print(f'  Position Count Change: {len(latest_positions) - len(prev_positions):+d}')
print(f'  Closed Positions Change: {len(latest_positions[latest_positions["ts_closed_num"] > 0]) - len(prev_positions[prev_positions["ts_closed_num"] > 0]):+d}')
print(f'  Order Count Change: {len(latest_orders) - len(prev_orders):+d}')
print(f'  Fill Count Change: {len(latest_fills) - len(prev_fills):+d}')
print(f'  Rejected Signals Change: {latest_stats["rejected_signals_count"] - prev_stats["rejected_signals_count"]:+d}')
print()

# Check for position closing reasons
print('='*80)
print('POSITION CLOSING ANALYSIS')
print('='*80)

# Check how positions were closed (by looking at closing order types)
if 'closing_order_id' in latest_positions.columns:
    latest_closed = latest_positions[latest_positions['ts_closed_num'] > 0].copy()
    prev_closed = prev_positions[prev_positions['ts_closed_num'] > 0].copy()
    
    # Try to match closing orders
    if len(latest_closed) > 0:
        latest_closed_with_orders = latest_closed.merge(
            latest_orders,
            left_on='closing_order_id',
            right_on='client_order_id',
            how='left',
            suffixes=('', '_order')
        )
        tp_closes = len(latest_closed_with_orders[latest_closed_with_orders['tags_order'].str.contains('TP', na=False)])
        sl_closes = len(latest_closed_with_orders[latest_closed_with_orders['tags_order'].str.contains('SL', na=False)])
        
        print('AFTER FIX:')
        print(f'  Positions closed by TP: {tp_closes}')
        print(f'  Positions closed by SL: {sl_closes}')
        print(f'  Total closed positions: {len(latest_closed)}')
    
    if len(prev_closed) > 0:
        prev_closed_with_orders = prev_closed.merge(
            prev_orders,
            left_on='closing_order_id',
            right_on='client_order_id',
            how='left',
            suffixes=('', '_order')
        )
        tp_closes_prev = len(prev_closed_with_orders[prev_closed_with_orders['tags_order'].str.contains('TP', na=False)])
        sl_closes_prev = len(prev_closed_with_orders[prev_closed_with_orders['tags_order'].str.contains('SL', na=False)])
        
        print('BEFORE FIX:')
        print(f'  Positions closed by TP: {tp_closes_prev}')
        print(f'  Positions closed by SL: {sl_closes_prev}')
        print(f'  Total closed positions: {len(prev_closed)}')

print()
print('='*80)
print('KEY OBSERVATION')
print('='*80)
print('The fix ensures positions are only closed via TP/SL orders,')
print('not by opposite signals. This should result in:')
print('- More rejected signals when positions exist')
print('- Positions held longer (until TP/SL triggers)')
print('- Potentially different PnL due to letting TP/SL work')
print('='*80)
