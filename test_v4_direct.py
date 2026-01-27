"""
Direct V4 Config Test
"""

import sys
from pathlib import Path

# Add V4 path directly
v4_config_path = Path(__file__).parent / "v4" / "config"
sys.path.insert(0, str(v4_config_path))

# Try direct import
try:
    import mtf_v4_config
    print("✅ V4 config module imported directly")
    
    # Test loading config
    config = mtf_v4_config.load_mtf_v4_config()
    print(f"✅ Config loaded: SL={config.default_sl_atr_mult}, TP={config.default_pos1_tp_atr_mult}")
    
    # Test dynamic parameters
    dynamic_params = mtf_v4_config.load_dynamic_parameters()
    print(f"✅ Dynamic params: {len(dynamic_params['sl_by_hour'])} SL rules")
    
    # Test dynamic SL/TP
    from datetime import datetime
    test_time = datetime(2025, 1, 15, 20, 0)  # 8PM
    sl_tp = mtf_v4_config.get_dynamic_sl_tp(test_time, config)
    print(f"✅ Dynamic SL/TP for 8PM: SL={sl_tp['sl_atr_mult']}x, TP={sl_tp['pos1_tp_atr_mult']}x")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
