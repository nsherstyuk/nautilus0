#!/usr/bin/env python3
"""
Detailed Trailing Activation Analysis

This script will:
1. Run a backtest with verbose trailing logs
2. Extract all trailing-related log messages  
3. Show exactly why trailing isn't activating
"""
import subprocess
import sys
from pathlib import Path
import re

def analyze_trailing_logs():
    """Run backtest and analyze trailing logs"""
    
    print("🔬 DETAILED TRAILING ACTIVATION ANALYSIS")
    print("=" * 60)
    
    # Set ultra-aggressive trailing to force activation
    print("📝 Setting ultra-aggressive trailing config...")
    update_env_for_trailing_test()
    
    # Run backtest with full output capture
    print("🚀 Running backtest with detailed logging...")
    try:
        result = subprocess.run(
            [sys.executable, "backtest/run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=180,
            encoding='utf-8',
            errors='replace'  # Handle encoding issues gracefully
        )
        
        print(f"📊 Backtest completed with return code: {result.returncode}")
        
        # Analyze stdout for trailing messages
        analyze_trailing_output(result.stdout)
        
        if result.returncode != 0:
            print(f"\n❌ Stderr: {result.stderr[:500]}")
        
    except subprocess.TimeoutExpired:
        print("⏰ Backtest timeout")
    except Exception as e:
        print(f"❌ Error: {e}")

def update_env_for_trailing_test():
    """Set extremely aggressive trailing parameters"""
    params = {
        "BACKTEST_STOP_LOSS_PIPS": 30,
        "BACKTEST_TAKE_PROFIT_PIPS": 100,
        "BACKTEST_TRAILING_STOP_ACTIVATION_PIPS": 2,  # Ultra-low activation
        "BACKTEST_TRAILING_STOP_DISTANCE_PIPS": 5,   # Small distance
        # Ensure these are disabled to focus on basic trailing
        "STRATEGY_REGIME_DETECTION_ENABLED": "false",
        "STRATEGY_TRAILING_DURATION_ENABLED": "false",
    }
    
    with open(".env", 'r') as f:
        lines = f.readlines()
    
    updated_lines = []
    for line in lines:
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
            if key in params:
                updated_lines.append(f"{key}={params[key]}\n")
                print(f"   Updated: {key}={params[key]}")
                continue
        updated_lines.append(line)
    
    with open(".env", 'w') as f:
        f.writelines(updated_lines)

def analyze_trailing_output(output):
    """Analyze backtest output for trailing-related messages"""
    
    print(f"\n🔍 ANALYZING OUTPUT ({len(output)} characters)")
    print("=" * 60)
    
    # Extract trailing-related lines
    lines = output.split('\n')
    trailing_lines = []
    
    for line in lines:
        if any(keyword in line.upper() for keyword in [
            'TRAILING', 'TRAIL', 'ACTIVATION', 'PROFIT_PIPS', 
            'THRESHOLD', 'STOP_ORDER', '_UPDATE_TRAILING'
        ]):
            trailing_lines.append(line)
    
    print(f"📋 Found {len(trailing_lines)} trailing-related log lines:")
    print("-" * 40)
    
    if not trailing_lines:
        print("⚠️  NO TRAILING LOGS FOUND!")
        print("   This suggests trailing method isn't being called at all.")
        return
    
    # Show first 20 trailing lines
    for i, line in enumerate(trailing_lines[:20], 1):
        line_clean = line.strip()
        if line_clean:
            print(f"{i:2d}. {line_clean}")
    
    if len(trailing_lines) > 20:
        print(f"... and {len(trailing_lines) - 20} more lines")
    
    # Look for specific patterns
    print(f"\n🎯 KEY PATTERNS:")
    
    activation_attempts = [l for l in trailing_lines if 'profit_pips' in l.lower() and 'threshold' in l.lower()]
    if activation_attempts:
        print(f"✅ Found {len(activation_attempts)} activation checks")
        print("   Sample:", activation_attempts[0][:100] + "..." if len(activation_attempts[0]) > 100 else activation_attempts[0])
    else:
        print("❌ No activation threshold checks found")
    
    activated_msgs = [l for l in trailing_lines if 'TRAILING ACTIVATED' in l.upper()]
    if activated_msgs:
        print(f"🎉 TRAILING ACTIVATED: {len(activated_msgs)} times")
        for msg in activated_msgs[:3]:
            print(f"   {msg.strip()}")
    else:
        print("❌ No 'TRAILING ACTIVATED' messages found")
    
    stop_modifications = [l for l in trailing_lines if 'modify_order' in l.lower() or 'moving stop' in l.lower()]
    if stop_modifications:
        print(f"🔄 Stop modifications: {len(stop_modifications)}")
        for mod in stop_modifications[:3]:
            print(f"   {mod.strip()}")
    else:
        print("❌ No stop order modifications found")
    
    # Check for error patterns
    error_patterns = [l for l in trailing_lines if any(err in l.upper() for err in ['ERROR', 'FAILED', 'ABORT', 'NO STOP'])]
    if error_patterns:
        print(f"🚨 Potential issues: {len(error_patterns)}")
        for err in error_patterns[:3]:
            print(f"   ⚠️  {err.strip()}")

if __name__ == "__main__":
    analyze_trailing_logs()