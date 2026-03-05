"""
Simple V4 Test - Verify dynamic SL/TP configuration works
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add paths
project_root = Path(__file__).parent
v4_path = project_root / "v4"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(v4_path))

def test_v4_config():
    """Test V4 configuration loading."""
    
    print("Testing V4 Configuration...")
    
    try:
        # Import V4 config
        from config.mtf_v4_config import load_mtf_v4_config, get_dynamic_sl_tp, load_dynamic_parameters
        
        # Load config
        config = load_mtf_v4_config()
        print(f"✅ V4 config loaded successfully")
        print(f"   Dynamic SL enabled: {config.dynamic_sl_enabled}")
        print(f"   Dynamic TP enabled: {config.dynamic_tp_enabled}")
        print(f"   Default SL mult: {config.default_sl_atr_mult}")
        print(f"   Default TP mult: {config.default_pos1_tp_atr_mult}")
        
        # Test dynamic parameters
        dynamic_params = load_dynamic_parameters()
        print(f"✅ Dynamic parameters loaded:")
        print(f"   SL rules by hour: {len(dynamic_params['sl_by_hour'])} hours")
        print(f"   TP rules by hour: {len(dynamic_params['tp_by_hour'])} hours")
        print(f"   Weekday multipliers: {len(dynamic_params['weekday_multipliers'])} days")
        
        # Test dynamic SL/TP calculation
        test_times = [
            datetime(2025, 1, 15, 10, 0),  # 10AM - high performance
            datetime(2025, 1, 15, 20, 0),  # 8PM - high fade
            datetime(2025, 1, 15, 6, 0),   # 6AM - low fade
        ]
        
        print(f"\n✅ Dynamic SL/TP Test Results:")
        for test_time in test_times:
            sl_tp = get_dynamic_sl_tp(test_time, config)
            hour = test_time.hour
            print(f"   Hour {hour:02d}: SL={sl_tp['sl_atr_mult']}x, TP={sl_tp['pos1_tp_atr_mult']}x")
        
        return True
        
    except Exception as e:
        print(f"❌ V4 config test failed: {e}")
        return False

def test_v4_strategy():
    """Test V4 strategy can be imported."""
    
    print("\nTesting V4 Strategy Import...")
    
    try:
        from strategies.ml_strategy_mtf_v4 import MLSignalStrategyV4
        print("✅ V4 strategy imported successfully")
        
        # Test strategy config creation
        from nautilus_trader.config import StrategyConfig
        strategy_config = StrategyConfig(
            instrument_id="EUR/USD.IDEALPRO",
            bar_type="EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
        )
        
        strategy = MLSignalStrategyV4(strategy_config)
        print("✅ V4 strategy instance created successfully")
        print(f"   Strategy ID: {strategy.id}")
        
        return True
        
    except Exception as e:
        print(f"❌ V4 strategy test failed: {e}")
        return False

def test_v4_environment():
    """Test V4 environment setup."""
    
    print("\nTesting V4 Environment...")
    
    # Check directories
    required_dirs = ["v4/config", "v4/strategies", "v4/backtest", "v4/logs", "v4/models"]
    
    for directory in required_dirs:
        if Path(directory).exists():
            print(f"✅ {directory} exists")
        else:
            print(f"❌ {directory} missing")
            return False
    
    # Check files
    required_files = [
        "v4/.env.mtf_v4",
        "v4/config/mtf_v4_config.py",
        "v4/strategies/ml_strategy_mtf_v4.py",
        "v4/backtest/run_backtest_mtf_v4_replay.py",
        "v4/README.md"
    ]
    
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"✅ {file_path} exists")
        else:
            print(f"❌ {file_path} missing")
            return False
    
    # Check model
    model_path = Path("v4/models/ml_model_mtf.pkl")
    if model_path.exists():
        print(f"✅ Model file exists ({model_path.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print(f"❌ Model file missing")
        return False
    
    return True

def main():
    """Run all V4 tests."""
    
    print("MTF V4 Environment Test")
    print("=" * 40)
    
    # Test environment
    env_ok = test_v4_environment()
    
    # Test configuration
    config_ok = test_v4_config()
    
    # Test strategy
    strategy_ok = test_v4_strategy()
    
    print("\n" + "=" * 40)
    print("V4 Test Summary:")
    print(f"Environment: {'✅ PASS' if env_ok else '❌ FAIL'}")
    print(f"Configuration: {'✅ PASS' if config_ok else '❌ FAIL'}")
    print(f"Strategy: {'✅ PASS' if strategy_ok else '❌ FAIL'}")
    
    if env_ok and config_ok and strategy_ok:
        print("\n🎉 V4 is ready for backtesting!")
        print("\nNext steps:")
        print("1. Run: python v4/backtest/run_backtest_mtf_v4_replay.py")
        print("2. Check results in: v4/backtest_results/")
        print("3. Compare with V2 performance")
    else:
        print("\n❌ V4 setup has issues. Fix errors above.")
    
    return env_ok and config_ok and strategy_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
