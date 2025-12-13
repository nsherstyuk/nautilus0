"""
Market Regime Detection Implementation Example

This shows how to integrate regime detection into the MovingAverageCrossover strategy.
Copy relevant parts into strategies/moving_average_crossover.py
"""

from decimal import Decimal
from typing import Tuple, Optional
from nautilus_trader.model.data import Bar
from nautilus_trader.model.identifiers import OrderSide


class RegimeDetectionMixin:
    """
    Mixin class for market regime detection.
    Can be added to MovingAverageCrossover class.
    """
    
    def _detect_market_regime(self, bar: Bar) -> str:
        """
        Detect current market regime using ADX from DMI indicator.
        
        Returns:
            'trending': Strong trend (ADX > threshold_strong)
            'ranging': Weak/no trend (ADX < threshold_weak)
            'moderate': Moderate trend (between thresholds)
            'unknown': DMI not initialized
        """
        # Check if DMI is available and initialized
        if not hasattr(self, 'dmi') or self.dmi is None:
            return 'moderate'  # Default if DMI not enabled
        
        if not hasattr(self.dmi, 'adx') or not self.dmi.adx.initialized:
            return 'moderate'  # Default if ADX not ready
        
        # Get thresholds from config (or use defaults)
        threshold_strong = getattr(self.cfg, 'regime_adx_trending_threshold', 25.0)
        threshold_weak = getattr(self.cfg, 'regime_adx_ranging_threshold', 20.0)
        
        adx_value = self.dmi.adx.value
        
        # Log regime changes for debugging
        if not hasattr(self, '_last_regime'):
            self._last_regime = None
        
        if adx_value > threshold_strong:
            regime = 'trending'
        elif adx_value < threshold_weak:
            regime = 'ranging'
        else:
            regime = 'moderate'
        
        # Log regime changes
        if regime != self._last_regime:
            self.log.debug(
                f"Market regime: {regime} (ADX={adx_value:.2f}, "
                f"thresholds: strong>{threshold_strong}, weak<{threshold_weak})"
            )
            self._last_regime = regime
        
        return regime
    
    def _get_regime_adjusted_tp_sl(
        self, 
        base_tp_pips: Decimal, 
        base_sl_pips: Decimal, 
        bar: Bar
    ) -> Tuple[Decimal, Decimal]:
        """
        Get TP/SL adjusted for current market regime.
        
        Args:
            base_tp_pips: Base TP in pips from config
            base_sl_pips: Base SL in pips from config
            bar: Current bar for regime detection
        
        Returns:
            Tuple of (adjusted_tp_pips, adjusted_sl_pips)
        """
        if not getattr(self.cfg, 'regime_detection_enabled', False):
            return base_tp_pips, base_sl_pips
        
        regime = self._detect_market_regime(bar)
        
        # Get multipliers from config (or use defaults)
        tp_mult_trending = getattr(self.cfg, 'regime_tp_multiplier_trending', Decimal('1.5'))
        tp_mult_ranging = getattr(self.cfg, 'regime_tp_multiplier_ranging', Decimal('0.8'))
        
        if regime == 'trending':
            # Trending: Wider TP to let trends run
            adjusted_tp = base_tp_pips * tp_mult_trending
            adjusted_sl = base_sl_pips  # Keep SL same
        elif regime == 'ranging':
            # Ranging: Tighter TP to take profits quickly
            adjusted_tp = base_tp_pips * tp_mult_ranging
            adjusted_sl = base_sl_pips  # Keep SL same
        else:
            # Moderate: Use base values
            adjusted_tp = base_tp_pips
            adjusted_sl = base_sl_pips
        
        return adjusted_tp, adjusted_sl
    
    def _get_regime_adjusted_trailing_params(
        self, 
        base_activation_pips: Decimal, 
        base_distance_pips: Decimal, 
        bar: Bar
    ) -> Tuple[Decimal, Decimal]:
        """
        Get trailing stop parameters adjusted for current market regime.
        
        Args:
            base_activation_pips: Base activation threshold from config
            base_distance_pips: Base trailing distance from config
            bar: Current bar for regime detection
        
        Returns:
            Tuple of (adjusted_activation_pips, adjusted_distance_pips)
        """
        if not getattr(self.cfg, 'regime_detection_enabled', False):
            return base_activation_pips, base_distance_pips
        
        regime = self._detect_market_regime(bar)
        
        # Get multipliers from config (or use defaults)
        act_mult_trending = getattr(
            self.cfg, 
            'regime_trailing_activation_multiplier_trending', 
            Decimal('0.75')
        )
        act_mult_ranging = getattr(
            self.cfg, 
            'regime_trailing_activation_multiplier_ranging', 
            Decimal('1.25')
        )
        dist_mult_trending = getattr(
            self.cfg, 
            'regime_trailing_distance_multiplier_trending', 
            Decimal('0.67')
        )
        dist_mult_ranging = getattr(
            self.cfg, 
            'regime_trailing_distance_multiplier_ranging', 
            Decimal('1.33')
        )
        
        if regime == 'trending':
            # Trending: Lower activation (activate sooner), tighter distance
            adjusted_activation = base_activation_pips * act_mult_trending
            adjusted_distance = base_distance_pips * dist_mult_trending
        elif regime == 'ranging':
            # Ranging: Higher activation (wait for confirmation), wider distance
            adjusted_activation = base_activation_pips * act_mult_ranging
            adjusted_distance = base_distance_pips * dist_mult_ranging
        else:
            # Moderate: Use base values
            adjusted_activation = base_activation_pips
            adjusted_distance = base_distance_pips
        
        return adjusted_activation, adjusted_distance


# Example: How to integrate into _calculate_sl_tp_prices method
"""
def _calculate_sl_tp_prices(self, entry_price: Decimal, side: OrderSide, bar: Bar) -> Tuple[Decimal, Decimal]:
    '''Calculate SL/TP prices, adjusted for market regime.'''
    # Base TP/SL from config
    base_tp_pips = Decimal(str(self.cfg.take_profit_pips))
    base_sl_pips = Decimal(str(self.cfg.stop_loss_pips))
    
    # Get regime-adjusted values
    tp_pips, sl_pips = self._get_regime_adjusted_tp_sl(base_tp_pips, base_sl_pips, bar)
    
    # Rest of existing calculation logic...
    pip_value = self._calculate_pip_value()
    # ... calculate actual prices ...
"""

# Example: How to integrate into _update_trailing_stop method
"""
def _update_trailing_stop(self, bar: Bar) -> None:
    '''Update trailing stop logic, adjusted for market regime.'''
    # ... existing position checks ...
    
    # Get regime-adjusted trailing parameters
    base_activation = Decimal(str(self.cfg.trailing_stop_activation_pips))
    base_distance = Decimal(str(self.cfg.trailing_stop_distance_pips))
    
    activation_pips, distance_pips = self._get_regime_adjusted_trailing_params(
        base_activation, base_distance, bar
    )
    
    # Use adjusted values in trailing stop logic
    # ... rest of trailing stop calculation ...
"""



