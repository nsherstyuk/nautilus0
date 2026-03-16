"""
IBKRExecutionEngine - Live bracket order execution via IBKR
Implements ExecutionEngine interface for live trading.
"""
from typing import Optional, Callable
import logging

from ib_insync import IB, Contract, Order, Trade

from ..core.interfaces import ExecutionEngine
from ..core.market_event import Fill, RangeInfo, Tick


class IBKRExecutionEngine(ExecutionEngine):
    """
    Implements ExecutionEngine for live IBKR trading.
    Manages bracket orders (entry stop + SL/TP legs).
    """
    
    def __init__(
        self,
        ib: IB,
        contract: Contract,
        quantity: int,
        on_fill_callback: Callable[[Fill], None],
        logger: Optional[logging.Logger] = None
    ):
        """
        Args:
            ib: Connected ib_insync IB instance
            contract: IBKR contract to trade
            quantity: Position size (e.g., 1 for 1 oz XAUUSD, 20000 for EURUSD)
            on_fill_callback: Called when orders fill
            logger: Optional logger
        """
        self.ib = ib
        self.contract = contract
        self.quantity = quantity
        self.on_fill_callback = on_fill_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # Track active orders
        self.long_entry_trade: Optional[Trade] = None
        self.short_entry_trade: Optional[Trade] = None
        self.sl_trade: Optional[Trade] = None
        self.tp_trade: Optional[Trade] = None
        
        # Position state
        self.position = 0  # 1 for LONG, -1 for SHORT, 0 for flat
        
        # Register fill callback
        self.ib.execDetailsEvent += self._on_execution
        
    def set_orb_brackets(self, range_info: RangeInfo, rr_ratio: float):
        """
        Place OCA bracket orders for ORB breakout.
        
        Structure:
        - Long entry stop @ range.high
        - Short entry stop @ range.low
        - Once filled, attach SL/TP bracket to the position
        """
        self.logger.info(f"Placing ORB brackets: Long @ {range_info.high:.4f}, Short @ {range_info.low:.4f}, RR={rr_ratio}")
        
        # Cancel any existing entry orders
        self.cancel_orb_brackets()
        
        # Create OCA group for entry stops (one-cancels-all)
        oca_group = f"ORB_ENTRY_{self.ib.client.getReqId()}"
        
        # Long entry stop
        long_order = Order(
            action='BUY',
            orderType='STP',
            auxPrice=range_info.high,
            totalQuantity=self.quantity,
            ocaGroup=oca_group,
            ocaType=1,  # Cancel all on fill
            transmit=False  # Don't transmit yet
        )
        
        # Short entry stop  
        short_order = Order(
            action='SELL',
            orderType='STP',
            auxPrice=range_info.low,
            totalQuantity=self.quantity,
            ocaGroup=oca_group,
            ocaType=1,
            transmit=True  # Transmit all orders in batch
        )
        
        # Place orders
        self.long_entry_trade = self.ib.placeOrder(self.contract, long_order)
        self.short_entry_trade = self.ib.placeOrder(self.contract, short_order)
        
        # Store range info and RR for later SL/TP calculation
        self.range_info = range_info
        self.rr_ratio = rr_ratio
        
        self.logger.info(f"Entry brackets placed: Long order {self.long_entry_trade.order.orderId}, Short order {self.short_entry_trade.order.orderId}")
        
    def cancel_orb_brackets(self):
        """
        Cancel resting entry brackets (does NOT cancel SL/TP if position active).
        """
        if self.long_entry_trade and self.long_entry_trade.orderStatus.status in ('Submitted', 'PreSubmitted'):
            self.ib.cancelOrder(self.long_entry_trade.order)
            self.logger.info(f"Canceled long entry order {self.long_entry_trade.order.orderId}")
            
        if self.short_entry_trade and self.short_entry_trade.orderStatus.status in ('Submitted', 'PreSubmitted'):
            self.ib.cancelOrder(self.short_entry_trade.order)
            self.logger.info(f"Canceled short entry order {self.short_entry_trade.order.orderId}")
            
        self.long_entry_trade = None
        self.short_entry_trade = None
        
    def close_at_market(self):
        """
        Close position immediately at market.
        Cancels SL/TP and submits market order.
        """
        if self.position == 0:
            return
            
        self.logger.info(f"Closing position at market (current position: {self.position})")
        
        # Cancel resting SL/TP
        if self.sl_trade:
            self.ib.cancelOrder(self.sl_trade.order)
        if self.tp_trade:
            self.ib.cancelOrder(self.tp_trade.order)
            
        # Submit market close
        action = 'SELL' if self.position > 0 else 'BUY'
        market_order = Order(
            action=action,
            orderType='MKT',
            totalQuantity=self.quantity
        )
        
        trade = self.ib.placeOrder(self.contract, market_order)
        self.logger.info(f"Market close order submitted: {trade.order.orderId}")
        
    def _get_order_id(self, trade: Optional[Trade]) -> Optional[int]:
        """Safely extract order ID from a Trade object."""
        if trade and trade.order:
            return trade.order.orderId
        return None

    def _on_execution(self, trade: Trade, fill):
        """
        Called by ib_insync when an order fills.
        Converts IBKR fill to our Fill dataclass and notifies strategy.
        Uses order ID comparison (not object identity) for reliability.
        """
        order_id = trade.order.orderId if trade.order else None
        
        # Match by order ID - survives reconnects and object recreation
        if order_id and order_id == self._get_order_id(self.long_entry_trade):
            self._handle_entry_fill(trade, fill, 'LONG')
        elif order_id and order_id == self._get_order_id(self.short_entry_trade):
            self._handle_entry_fill(trade, fill, 'SHORT')
        elif order_id and order_id == self._get_order_id(self.sl_trade):
            self._handle_exit_fill(trade, fill, 'SL')
        elif order_id and order_id == self._get_order_id(self.tp_trade):
            self._handle_exit_fill(trade, fill, 'TP')
        else:
            # Market close or unrecognized order
            if self.position != 0:
                self._handle_exit_fill(trade, fill, 'MARKET')
            else:
                self.logger.warning(f"Unrecognized fill: order_id={order_id}, price={fill.execution.avgPrice}")
            
    def _handle_entry_fill(self, trade: Trade, fill, direction: str):
        """
        Handle entry fill - update position and place SL/TP bracket.
        """
        self.logger.info(f"Entry filled: {direction} @ {fill.execution.avgPrice}")
        
        # Update position
        self.position = 1 if direction == 'LONG' else -1
        entry_price = fill.execution.avgPrice
        
        # Calculate SL/TP levels
        if direction == 'LONG':
            sl_price = self.range_info.low
            risk = entry_price - sl_price
            tp_price = entry_price + (risk * self.rr_ratio)
        else:  # SHORT
            sl_price = self.range_info.high
            risk = sl_price - entry_price
            tp_price = entry_price - (risk * self.rr_ratio)
            
        # Place SL/TP bracket
        self._place_bracket(direction, sl_price, tp_price)
        
        # Notify strategy
        fill_event = Fill(
            timestamp=fill.execution.time,
            price=entry_price,
            direction=direction,
            reason='ENTRY'
        )
        self.on_fill_callback(fill_event)
        
    def _place_bracket(self, direction: str, sl_price: float, tp_price: float):
        """
        Place SL/TP bracket for active position.
        """
        self.logger.info(f"Placing bracket: SL @ {sl_price:.4f}, TP @ {tp_price:.4f}")
        
        # OCA group for SL/TP
        oca_group = f"ORB_EXIT_{self.ib.client.getReqId()}"
        
        # Stop loss (stop market order)
        sl_action = 'SELL' if direction == 'LONG' else 'BUY'
        sl_order = Order(
            action=sl_action,
            orderType='STP',
            auxPrice=sl_price,
            totalQuantity=self.quantity,
            ocaGroup=oca_group,
            ocaType=1,
            transmit=False
        )
        
        # Take profit (limit order)
        tp_action = 'SELL' if direction == 'LONG' else 'BUY'
        tp_order = Order(
            action=tp_action,
            orderType='LMT',
            lmtPrice=tp_price,
            totalQuantity=self.quantity,
            ocaGroup=oca_group,
            ocaType=1,
            transmit=True
        )
        
        self.sl_trade = self.ib.placeOrder(self.contract, sl_order)
        self.tp_trade = self.ib.placeOrder(self.contract, tp_order)
        
        self.logger.info(f"Bracket placed: SL order {self.sl_trade.order.orderId}, TP order {self.tp_trade.order.orderId}")
        
    def _handle_exit_fill(self, trade: Trade, fill, reason: str):
        """
        Handle exit fill (SL, TP, or MARKET close).
        """
        exit_price = fill.execution.avgPrice
        direction = 'SHORT' if self.position > 0 else 'LONG'  # Opposite of entry
        
        self.logger.info(f"{reason} fill: {direction} @ {exit_price}")
        
        # Reset position
        self.position = 0
        self.sl_trade = None
        self.tp_trade = None
        
        # Notify strategy
        fill_event = Fill(
            timestamp=fill.execution.time,
            price=exit_price,
            direction=direction,
            reason=reason
        )
        self.on_fill_callback(fill_event)
