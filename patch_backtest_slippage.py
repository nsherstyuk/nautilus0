"""
Patch backtest.py to add slippage modeling
"""

filepath = r'c:\nautilus0\v5_xauusd_orb\backtest.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Add slippage parameter to function signature
content = content.replace(
    '    spread_per_side: float = 0.10,   # assumed slippage/spread per entry in $\n) -> pd.DataFrame:',
    '    spread_per_side: float = 0.10,   # assumed bid/ask spread per entry in $\n    slippage: float = 0.15,          # assumed slippage for stop/market orders in $\n) -> pd.DataFrame:'
)

# Apply slippage to entry prices
content = content.replace(
    "                direction  = 'LONG'\n                entry_px   = long_entry",
    "                direction  = 'LONG'\n                entry_px   = long_entry + slippage"
)

content = content.replace(
    "                direction  = 'SHORT'\n                entry_px   = short_entry",
    "                direction  = 'SHORT'\n                entry_px   = short_entry - slippage"
)

# Apply slippage to SL exits
content = content.replace(
    "                if bar['low'] <= sl_px:\n                    result   = 'SL'\n                    exit_px  = sl_px",
    "                if bar['low'] <= sl_px:\n                    result   = 'SL'\n                    exit_px  = sl_px - slippage"
)

content = content.replace(
    "                if bar['high'] >= sl_px:\n                    result   = 'SL'\n                    exit_px  = sl_px",
    "                if bar['high'] >= sl_px:\n                    result   = 'SL'\n                    exit_px  = sl_px + slippage"
)

# Apply slippage to EOD exits (before the loop, default case)
content = content.replace(
    "        result   = 'EOD'\n        exit_px  = monitor['close'].iloc[-1] if len(monitor) > 0 else entry_px\n        hold_bars = len(monitor)",
    "        result   = 'EOD'\n        exit_px  = monitor['close'].iloc[-1] if len(monitor) > 0 else entry_px\n        \n        if result == 'EOD' and len(monitor) > 0:\n            # EOD close is a market order, so it has slippage\n            exit_px = exit_px - slippage if direction == 'LONG' else exit_px + slippage\n            \n        hold_bars = len(monitor)"
)

# Fix spread cost calculation (should be 2x for entry + exit)
content = content.replace(
    '        pnl = raw_pnl - spread_per_side * qty  # cost',
    '        pnl = raw_pnl - (spread_per_side * 2 * qty)  # cost per side (entry and exit)'
)

# Add slippage argument to argparse
content = content.replace(
    '    parser.add_argument("--spread", type=float, default=0.10,\n                        help="One-way slippage/spread per oz in $ (default: 0.10)")\n    parser.add_argument("--save",   default=None,',
    '    parser.add_argument("--spread", type=float, default=0.10,\n                        help="One-way spread per oz in $ (default: 0.10)")\n    parser.add_argument("--slippage", type=float, default=0.15,\n                        help="Slippage for stop/market orders per oz in $ (default: 0.15)")\n    parser.add_argument("--save",   default=None,'
)

# Pass slippage to backtest function
content = content.replace(
    '        qty           = cfg.position.qty,\n        spread_per_side = args.spread,\n    )',
    '        qty           = cfg.position.qty,\n        spread_per_side = args.spread,\n        slippage      = args.slippage,\n    )'
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print('Slippage modeling added to backtest.py')
