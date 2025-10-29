from typing import Dict, Any

MICROPIP = 0.00001
PIP = 0.0001


def build_bracket_preview(signal: Dict[str, Any], entry_price: float, params: Dict[str, Any], trailing_stop_pips: float) -> Dict[str, Any]:
    """
    Build a non-invasive preview of a bracket order using:
    - Parent: Limit at entry_price
    - Child 1: Take profit limit using take_profit_micropips
    - Child 2: Native trailing stop (distance in pips)

    Returns a dict suitable for logging/inspection only.
    """
    direction = signal.get('direction')
    tp_micro = params.get('take_profit_micropips', 100)
    pos_size = params.get('position_size', 2.0)

    tp_offset = tp_micro * MICROPIP

    if direction == 'buy':
        tp_price = entry_price + tp_offset
        side = 'BUY'
    else:
        tp_price = entry_price - tp_offset
        side = 'SELL'

    return {
        'side': side,
        'position_size': pos_size,
        'parent': {
            'type': 'LMT',
            'price': float(entry_price),
        },
        'take_profit': {
            'type': 'LMT',
            'price': float(tp_price),
        },
        'trailing_stop': {
            'type': 'TRAIL',
            'distance_pips': float(trailing_stop_pips),
        },
        'risk': {
            'take_profit_micropips': tp_micro,
            'micropip_value': MICROPIP,
            'pip_value': PIP,
        },
    }
