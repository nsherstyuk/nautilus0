"""
Diagnostic script to trace live trading execution flow.
Analyzes logs to identify where execution stops.
"""
import re
from pathlib import Path
from datetime import datetime

def analyze_strategy_log():
    """Analyze strategy.log for execution checkpoints."""
    log_file = Path("logs/live_mtf/strategy.log")
    
    if not log_file.exists():
        print("ERROR: strategy.log not found at", log_file)
        print("Make sure live trading has been started at least once")
        return
    
    print("="*80)
    print("LIVE TRADING DIAGNOSTIC ANALYSIS")
    print("="*80)
    print(f"Analyzing: {log_file}")
    print(f"File size: {log_file.stat().st_size} bytes")
    print(f"Last modified: {datetime.fromtimestamp(log_file.stat().st_mtime)}")
    print("="*80)
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    print(f"\nTotal log lines: {len(lines)}")
    
    # Checkpoints to look for
    checkpoints = {
        'model_loaded': r'Loaded model from',
        'strategy_initialized': r'Strategy initialized successfully',
        'bars_received': r'Received.*bar',
        'session_excluded': r'Bar excluded',
        'warmup_waiting': r'Waiting for warmup',
        'warmup_complete': r'WARMUP COMPLETE',
        'prediction_made': r'prediction=',
        'debug_mode': r'\[DEBUG MODE\]',
        'filter_confidence': r'\[FILTERED\] Confidence',
        'filter_atr': r'\[FILTERED\] ATR',
        'filter_cooldown': r'\[FILTERED\] Cooldown',
        'order_submitted': r'Submitting.*order',
    }
    
    results = {k: [] for k in checkpoints.keys()}
    
    for line in lines:
        for checkpoint, pattern in checkpoints.items():
            if re.search(pattern, line, re.IGNORECASE):
                results[checkpoint].append(line.strip())
    
    # Print results
    print("\n## CHECKPOINT ANALYSIS ##\n")
    
    for checkpoint, matches in results.items():
        count = len(matches)
        status = "OK" if count > 0 else "MISSING"
        print(f"{checkpoint:25s}: {status:8s} ({count} occurrences)")
        if count > 0 and count <= 3:
            for match in matches[:3]:
                # Truncate long lines
                display = match[:120] + "..." if len(match) > 120 else match
                print(f"  -> {display}")
    
    # Determine failure point
    print("\n" + "="*80)
    print("## FAILURE POINT ANALYSIS ##")
    print("="*80 + "\n")
    
    if results['model_loaded']:
        print("[OK] Model loaded successfully")
    else:
        print("[FAIL] Model not loaded - check model path")
        print("  Action: Verify models/ml_model_mtf.pkl exists")
        return
    
    if results['strategy_initialized']:
        print("[OK] Strategy initialized")
    else:
        print("[FAIL] Strategy not initialized")
        print("  Action: Check on_start method for errors")
        return
    
    if results['bars_received']:
        print(f"[OK] Bars being received ({len(results['bars_received'])} bars)")
    else:
        print("[FAIL] No bars received - check bar subscription")
        print("  Action: Verify IB Gateway connection and bar subscription")
        return
    
    if results['session_excluded']:
        print(f"[WARN] Bars being excluded by session filter ({len(results['session_excluded'])} bars)")
        print("  -> Historical bars may be filtered out")
        print("  Action: Add warmup_mode flag to bypass session filter during backfill")
    
    if results['warmup_waiting']:
        print(f"[WARN] Strategy waiting for warmup ({len(results['warmup_waiting'])} messages)")
        print("  -> Buffers not full yet")
        print("  Action: Check if historical bars are being added to buffers")
    
    if results['warmup_complete']:
        print("[OK] Warmup completed")
    else:
        print("[FAIL] Warmup not completed - buffers not full")
        print("  -> THIS IS THE PRIMARY ISSUE")
        print("  Action: Apply warmup_mode fix to accept historical bars")
        return
    
    if results['prediction_made']:
        print(f"[OK] Predictions being made ({len(results['prediction_made'])} predictions)")
    else:
        print("[FAIL] No predictions - check feature calculation")
        print("  Action: Verify feature calculation is working")
        return
    
    if results['debug_mode']:
        print(f"[OK] Debug mode active ({len(results['debug_mode'])} bypasses)")
    else:
        print("[WARN] Debug mode not active - filters may block trades")
        print("  Action: Set MTF_DEBUG_MODE=true in .env.mtf")
    
    if results['filter_confidence'] or results['filter_atr'] or results['filter_cooldown']:
        total_filtered = len(results['filter_confidence']) + len(results['filter_atr']) + len(results['filter_cooldown'])
        print(f"[WARN] Signals being filtered ({total_filtered} filtered)")
        print(f"  -> Confidence: {len(results['filter_confidence'])}")
        print(f"  -> ATR: {len(results['filter_atr'])}")
        print(f"  -> Cooldown: {len(results['filter_cooldown'])}")
        print("  Action: Lower thresholds or enable debug mode")
    
    if results['order_submitted']:
        print(f"[OK] Orders being submitted ({len(results['order_submitted'])} orders)")
        print("\n" + "="*80)
        print("SUCCESS: System is working correctly!")
        print("="*80)
    else:
        print("[FAIL] No orders submitted")
        print("  Action: Check order submission logic and IB Gateway permissions")
    
    print("\n" + "="*80)
    print("## RECOMMENDATIONS ##")
    print("="*80 + "\n")
    
    if not results['warmup_complete']:
        print("1. CRITICAL: Apply warmup_mode fix")
        print("   - Add _warmup_mode flag to strategy __init__")
        print("   - Skip session check during warmup")
        print("   - Exit warmup mode when buffers full")
        print()
    
    if not results['debug_mode'] and not results['order_submitted']:
        print("2. Enable debug mode for testing")
        print("   - Set MTF_DEBUG_MODE=true in .env.mtf")
        print()
    
    if results['session_excluded']:
        print("3. Session filter is blocking bars")
        print("   - This is why historical bars aren't filling buffers")
        print()
    
    print("4. Run diagnostic again after applying fixes")
    print("   - python diagnose_live.py")
    print()

if __name__ == "__main__":
    try:
        analyze_strategy_log()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
