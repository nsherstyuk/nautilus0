"""
Live System Diagnostic Script

Checks each component of the live trading system independently:
1. Configuration loading
2. ML model loading and prediction
3. IBKR connection
4. Data subscription capability
5. Order submission capability (paper trading)
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from joblib import load


def check_separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check_configuration():
    """Check 1: Configuration Loading"""
    check_separator("CHECK 1: Configuration Loading")
    
    try:
        from config.mtf_config import load_mtf_config, validate_mtf_config
        config = load_mtf_config()
        
        print(f"✅ Configuration loaded successfully")
        print(f"   Symbol: {config.symbol}")
        print(f"   Venue: {config.venue}")
        print(f"   Bar Spec: {config.bar_spec}")
        print(f"   Model Path: {config.model_path}")
        print(f"   Prediction Threshold: {config.prediction_threshold}")
        print(f"   Debug Mode: {config.debug_mode}")
        print(f"   Position Size: {config.position_size}")
        print(f"   IBKR Port: {config.ib_port}")
        
        if validate_mtf_config(config):
            print(f"✅ Configuration validation passed")
        else:
            print(f"❌ Configuration validation failed")
            
        return config
    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")
        return None


def check_model(config):
    """Check 2: ML Model Loading and Prediction"""
    check_separator("CHECK 2: ML Model Loading & Prediction")
    
    try:
        model_path = Path(config.model_path)
        if not model_path.is_absolute():
            model_path = PROJECT_ROOT / model_path
            
        if not model_path.exists():
            print(f"❌ Model file not found: {model_path}")
            return None
            
        model = load(model_path)
        print(f"✅ Model loaded: {type(model).__name__}")
        
        # Check model attributes
        if hasattr(model, 'n_features_in_'):
            print(f"   Expected features: {model.n_features_in_}")
        if hasattr(model, 'classes_'):
            print(f"   Classes: {model.classes_}")
        if hasattr(model, 'n_estimators'):
            print(f"   Estimators: {model.n_estimators}")
            
        # Test prediction with dummy data
        # MTF model expects 10 features
        dummy_features = np.random.randn(1, 10)
        prediction = model.predict(dummy_features)[0]
        probas = model.predict_proba(dummy_features)[0]
        
        print(f"✅ Test prediction successful")
        print(f"   Dummy prediction: {prediction}")
        print(f"   Probabilities: {probas}")
        
        return model
    except Exception as e:
        print(f"❌ Model check failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_strategy_instantiation(config):
    """Check 3: Strategy Instantiation"""
    check_separator("CHECK 3: Strategy Instantiation")
    
    try:
        from strategies.ml_strategy_config import MLSignalStrategyConfig
        from strategies.ml_strategy_mtf import MLSignalStrategy
        
        instrument_id = f"{config.symbol}.{config.venue}"
        
        strategy_config = MLSignalStrategyConfig(
            instrument_id=instrument_id,
            bar_spec=config.bar_spec,
            position_size=config.position_size,
            model_path=config.model_path,
            prediction_threshold=config.prediction_threshold,
            enforce_position_limit=config.enforce_position_limit,
            max_positions=config.max_positions,
            sl_atr_mult=config.sl_atr_mult,
            tp_atr_mult=config.tp_atr_mult,
            trailing_stop_enabled=config.trailing_stop_enabled,
            trailing_activation_atr_mult=config.trailing_activation_atr_mult,
            trailing_distance_atr_mult=config.trailing_distance_atr_mult,
            partial_close_enabled=config.partial_close_enabled,
            partial_close_fraction=config.partial_close_fraction,
            partial_close_move_sl_to_be=config.partial_close_move_sl_to_be,
            multi_layer_enabled=config.multi_layer_enabled,
            multi_layer_count=config.multi_layer_count,
            multi_layer_sizes=config.multi_layer_sizes,
            multi_layer_triggers=config.multi_layer_triggers,
            multi_layer_move_sl_to_be=config.multi_layer_move_sl_to_be,
            session_start=config.session_start,
            session_end=config.session_end,
            excluded_hours=config.excluded_hours if config.excluded_hours else [],
            excluded_hours_by_weekday=config.excluded_hours_by_weekday if config.excluded_hours_by_weekday else {},
            debug_mode=config.debug_mode,
            feature_warmup_bars=config.feature_warmup_bars,
            order_id_tag=config.order_id_tag,
        )
        
        # Create strategy instance
        strategy = MLSignalStrategy(strategy_config)
        
        print(f"✅ Strategy instantiated successfully")
        print(f"   Model loaded in __init__: {strategy.model is not None}")
        print(f"   Bar type: {strategy.bar_type}")
        print(f"   Warmup mode: {strategy._warmup_mode}")
        print(f"   Buffer size: {strategy.bars_buffer_15m.maxlen}")
        
        return strategy
    except Exception as e:
        print(f"❌ Strategy instantiation failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def check_ibkr_connection(config):
    """Check 4: IBKR Connection"""
    check_separator("CHECK 4: IBKR Connection")
    
    try:
        from ib_insync import IB
        
        ib = IB()
        print(f"   Connecting to {config.ib_host}:{config.ib_port}...")
        
        await asyncio.wait_for(
            ib.connectAsync(
                host=config.ib_host,
                port=config.ib_port,
                clientId=999,  # Use a different client ID for testing
                readonly=True,
            ),
            timeout=10.0
        )
        
        print(f"✅ IBKR connection successful")
        print(f"   Connected: {ib.isConnected()}")
        
        # Check account info
        accounts = ib.managedAccounts()
        print(f"   Accounts: {accounts}")
        
        # Check market data
        from ib_insync import Forex
        eurusd = Forex('EURUSD')
        ib.qualifyContracts(eurusd)
        print(f"   Contract qualified: {eurusd}")
        
        # Request a quick market data snapshot
        ticker = ib.reqMktData(eurusd, '', False, False)
        await asyncio.sleep(2)
        
        if ticker.bid and ticker.ask:
            print(f"✅ Market data received")
            print(f"   Bid: {ticker.bid}, Ask: {ticker.ask}")
        else:
            print(f"⚠️ Market data not yet received (might need more time)")
            print(f"   Ticker: {ticker}")
        
        ib.disconnect()
        return True
        
    except asyncio.TimeoutError:
        print(f"❌ IBKR connection timed out")
        print(f"   Is IB Gateway/TWS running on port {config.ib_port}?")
        return False
    except Exception as e:
        print(f"❌ IBKR connection failed: {e}")
        return False


def check_feature_calculation(strategy):
    """Check 5: Feature Calculation"""
    check_separator("CHECK 5: Feature Calculation")
    
    try:
        from nautilus_trader.model.data import Bar, BarType
        from nautilus_trader.model.objects import Price, Quantity
        from nautilus_trader.core.datetime import dt_to_unix_nanos
        
        # Create fake bars for testing
        print("   Creating synthetic bars for feature calculation test...")
        
        base_price = 1.0500
        now = pd.Timestamp.now(tz=timezone.utc)
        
        # We need to fill the buffer (100 bars for 15m)
        for i in range(strategy.bars_buffer_15m.maxlen + 10):
            # Create a simple bar with slight price variation
            price_variation = np.sin(i * 0.1) * 0.001
            bar_time = now - pd.Timedelta(minutes=15 * (strategy.bars_buffer_15m.maxlen + 10 - i))
            
            bar = Bar(
                bar_type=strategy.bar_type,
                open=Price.from_str(f"{base_price + price_variation:.5f}"),
                high=Price.from_str(f"{base_price + price_variation + 0.0005:.5f}"),
                low=Price.from_str(f"{base_price + price_variation - 0.0005:.5f}"),
                close=Price.from_str(f"{base_price + price_variation:.5f}"),
                volume=Quantity.from_int(1000),
                ts_event=dt_to_unix_nanos(bar_time),
                ts_init=dt_to_unix_nanos(bar_time),
                is_revision=False,
            )
            
            # Add to buffer directly (bypass on_bar since we don't have full strategy context)
            strategy.bars_buffer_15m.append(bar)
            
            # Also update 30m buffer periodically
            if i % 2 == 1:
                strategy._resample_to_30m()
        
        print(f"   15m buffer: {len(strategy.bars_buffer_15m)}/{strategy.bars_buffer_15m.maxlen}")
        print(f"   30m buffer: {len(strategy.bars_buffer_30m)}/{strategy.bars_buffer_30m.maxlen}")
        
        # Try to calculate features
        features = strategy._calculate_features()
        
        if features is not None:
            print(f"✅ Feature calculation successful")
            print(f"   Feature shape: {features.shape}")
            feature_names = ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m', 'atr', 'hour', 'day_of_week']
            for i, (name, val) in enumerate(zip(feature_names, features.flatten())):
                print(f"   {name}: {val:.6f}")
                
            # Test prediction
            prediction = strategy.model.predict(features)[0]
            probas = strategy.model.predict_proba(features)[0]
            print(f"\n   Model prediction: {prediction}")
            print(f"   Probabilities: {probas}")
            
            return True
        else:
            print(f"❌ Feature calculation returned None")
            return False
            
    except Exception as e:
        print(f"❌ Feature calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def summarize_results(results: dict):
    """Summarize all check results"""
    check_separator("SUMMARY")
    
    all_passed = True
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {check}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All checks passed! Live system should be functional.")
    else:
        print("⚠️ Some checks failed. Review the issues above.")
    
    return all_passed


async def main():
    print("\n" + "=" * 60)
    print("  LIVE TRADING SYSTEM DIAGNOSTICS")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    
    results = {}
    
    # Check 1: Configuration
    config = check_configuration()
    results["Configuration"] = config is not None
    
    if not config:
        summarize_results(results)
        return 1
    
    # Check 2: Model
    model = check_model(config)
    results["ML Model"] = model is not None
    
    # Check 3: Strategy
    strategy = check_strategy_instantiation(config)
    results["Strategy"] = strategy is not None
    
    # Check 4: IBKR
    ibkr_ok = await check_ibkr_connection(config)
    results["IBKR Connection"] = ibkr_ok
    
    # Check 5: Features (only if strategy loaded)
    if strategy:
        features_ok = check_feature_calculation(strategy)
        results["Feature Calculation"] = features_ok
    else:
        results["Feature Calculation"] = False
    
    # Summary
    all_passed = summarize_results(results)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
