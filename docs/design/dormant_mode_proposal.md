"""
Proposal: Adaptive Dormant Mode for Moving Average Crossover Strategy

This feature activates when EMA crossings are rare, switching to lower timeframe
detection with directional filtering based on higher timeframe trend.
"""

# CONCEPT SUMMARY
# ===============
# 
# Problem: During prolonged periods without EMA crossings (e.g., trending markets),
#          the strategy misses opportunities while waiting for the next crossover.
#
# Solution: When no crossings occur for X hours, switch to lower timeframe
#           detection but only take trades aligned with higher timeframe trend.
#
# Example:
#   - Primary: 15-minute bars, Fast EMA below Slow EMA (bearish trend)
#   - No crossings for 14+ hours
#   - Switch to: 1-minute bars for signal detection
#   - Only take: SELL signals (aligned with bearish trend)
#   - Use: Separate TP/SL/trailing values optimized for lower timeframe

# DESIGN DECISIONS
# ================
# 1. Zero Impact: All new features disabled by default
# 2. Mode Detection: Track last crossover timestamp
# 3. Direction Filter: Use primary timeframe MA relationship
# 4. Separate Risk: Independent TP/SL/trailing for dormant mode
# 5. Mode Exit: Return to normal mode when primary timeframe crossing occurs

# CONFIGURATION STRUCTURE
# ======================
class DormantModeConfig:
    """Configuration for dormant mode feature."""
    
    # Feature enable/disable
    dormant_mode_enabled: bool = False
    
    # Activation threshold
    dormant_threshold_hours: float = 14.0  # Hours without crossing before activation
    
    # Lower timeframe for signal detection
    dormant_bar_spec: str = "1-MINUTE-MID-EXTERNAL"  # Lower timeframe bars
    dormant_fast_period: int = 5   # Fast MA period for lower timeframe
    dormant_slow_period: int = 10  # Slow MA period for lower timeframe
    
    # Risk management (separate from primary)
    dormant_stop_loss_pips: int = 20      # Tighter SL for lower timeframe
    dormant_take_profit_pips: int = 30    # Smaller TP for lower timeframe
    dormant_trailing_activation_pips: int = 15  # Lower activation threshold
    dormant_trailing_distance_pips: int = 8     # Tighter trailing distance
    
    # Optional: Additional filters for dormant mode
    dormant_dmi_enabled: bool = False      # Use DMI filter in dormant mode
    dormant_stoch_enabled: bool = False   # Use Stochastic filter in dormant mode

# IMPLEMENTATION APPROACH
# =======================
#
# 1. State Tracking
#    - Track last crossover timestamp
#    - Track current mode (NORMAL vs DORMANT)
#    - Track higher timeframe trend direction
#
# 2. Mode Detection Logic
#    - On each primary bar, check time since last crossover
#    - If > threshold_hours AND no position open: switch to DORMANT
#    - If primary crossover occurs: switch back to NORMAL
#
# 3. Signal Generation in Dormant Mode
#    - Subscribe to lower timeframe bars
#    - Calculate MA crossovers on lower timeframe
#    - Filter by higher timeframe trend direction:
#      * If Fast > Slow on primary: Only take BUY signals
#      * If Fast < Slow on primary: Only take SELL signals
#
# 4. Risk Management
#    - Use dormant_mode TP/SL/trailing values when in dormant mode
#    - Position opened in dormant mode uses dormant risk parameters
#
# 5. Mode Exit Conditions
#    - Primary timeframe crossover occurs
#    - Position closes (can re-evaluate mode)
#    - Manual reset (optional)

# BENEFITS
# ========
# 1. Captures intraday moves during trending periods
# 2. Reduces counter-trend trades (directional filter)
# 3. Adapts to market conditions automatically
# 4. Separate risk parameters for faster timeframes
# 5. Backward compatible (disabled by default)

# CONCERNS & CONSIDERATIONS
# =========================
# 1. Overtrading: Lower timeframe = more signals (mitigated by directional filter)
# 2. Complexity: More moving parts to debug
# 3. Risk: Lower timeframe trades need tighter risk management
# 4. Performance: More bars to process
# 5. Testing: Need extensive backtesting to validate

# ALTERNATIVE APPROACHES
# ======================
# 1. Use existing entry_timing feature (already has lower timeframe)
#    - But it doesn't switch modes or filter by direction
# 2. Use trend_filter feature (already has trend direction)
#    - But it doesn't switch timeframes or activate conditionally
# 3. Create separate strategy variant
#    - Cleaner separation but more code duplication

# RECOMMENDATION
# ==============
# Implement as optional feature in existing strategy:
# - Zero impact when disabled (default)
# - Can be tested independently
# - Integrates with existing multi-timeframe infrastructure
# - Allows gradual rollout and optimization

