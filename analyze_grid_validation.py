#!/usr/bin/env python3
"""
Analyze Phase 1 Grid for Valid vs Invalid Parameter Combinations

Check which combinations pass validation rules:
1. Activation > Distance
2. Activation < TP (to avoid warning)
"""
import json
import itertools

def analyze_phase1_grid():
    """Analyze the Phase 1 grid for validation issues"""
    
    # Load grid
    with open("re_optimization_results/phase1_core_trailing_grid.json", 'r') as f:
        grid = json.load(f)
    
    # Extract parameter ranges
    sl_values = grid["BACKTEST_STOP_LOSS_PIPS"]
    tp_values = grid["BACKTEST_TAKE_PROFIT_PIPS"]
    activation_values = grid["BACKTEST_TRAILING_STOP_ACTIVATION_PIPS"]
    distance_values = grid["BACKTEST_TRAILING_STOP_DISTANCE_PIPS"]
    
    print("📊 PHASE 1 GRID VALIDATION ANALYSIS")
    print("=" * 50)
    print(f"SL values: {sl_values}")
    print(f"TP values: {tp_values}")
    print(f"Activation values: {activation_values}")
    print(f"Distance values: {distance_values}")
    
    # Generate all combinations
    total_combinations = 0
    valid_combinations = 0
    invalid_combinations = []
    
    for sl, tp, activation, distance in itertools.product(sl_values, tp_values, activation_values, distance_values):
        total_combinations += 1
        
        # Check validation rules
        is_valid = True
        reasons = []
        
        if tp <= sl:
            is_valid = False
            reasons.append("TP <= SL")
        
        if activation <= distance:
            is_valid = False
            reasons.append(f"Activation({activation}) <= Distance({distance})")
        
        if activation > tp:
            # This is just a warning, not a failure
            reasons.append(f"Activation({activation}) > TP({tp}) - may not activate")
        
        if is_valid:
            valid_combinations += 1
        else:
            invalid_combinations.append({
                'sl': sl, 'tp': tp, 'activation': activation, 'distance': distance,
                'reasons': reasons
            })
    
    print(f"\n📈 RESULTS:")
    print(f"Total combinations: {total_combinations}")
    print(f"Valid combinations: {valid_combinations}")
    print(f"Invalid combinations: {len(invalid_combinations)}")
    print(f"Success rate: {valid_combinations/total_combinations*100:.1f}%")
    
    # Show breakdown by issue type
    activation_distance_issues = sum(1 for combo in invalid_combinations 
                                   if any("Activation" in reason and "<=" in reason for reason in combo['reasons']))
    
    print(f"\n🚨 ISSUE BREAKDOWN:")
    print(f"Activation <= Distance: {activation_distance_issues} combinations")
    
    # Show examples of invalid combinations
    print(f"\n❌ SAMPLE INVALID COMBINATIONS:")
    for i, combo in enumerate(invalid_combinations[:10], 1):
        print(f"  {i}. SL={combo['sl']}, TP={combo['tp']}, Act={combo['activation']}, Dist={combo['distance']} - {', '.join(combo['reasons'])}")
    
    if len(invalid_combinations) > 10:
        print(f"  ... and {len(invalid_combinations) - 10} more")
    
    # Show which activation/distance pairs are valid
    print(f"\n✅ VALID ACTIVATION/DISTANCE COMBINATIONS:")
    valid_pairs = set()
    for activation in activation_values:
        for distance in distance_values:
            if activation > distance:
                valid_pairs.add((activation, distance))
    
    for activation, distance in sorted(valid_pairs):
        print(f"  Activation={activation}, Distance={distance}")
    
    # Calculate optimized grid
    print(f"\n🔧 RECOMMENDATIONS:")
    print(f"1. Use only valid activation/distance pairs: {len(valid_pairs)} combinations")
    print(f"2. Current grid wastes ~{len(invalid_combinations)/total_combinations*100:.0f}% of optimization time")
    print(f"3. Consider adjusting distance values to avoid overlap with activation")
    
    # Suggest corrected grid
    corrected_distance = [d for d in distance_values if d < min(activation_values)]
    if not corrected_distance:
        corrected_distance = [5, 8, 10, 12]  # Ensure all are less than min activation (15)
    
    print(f"\n💡 SUGGESTED CORRECTED GRID:")
    print(f"   Distance values: {corrected_distance} (all < min activation of {min(activation_values)})")
    corrected_combinations = len(sl_values) * len(tp_values) * len(activation_values) * len(corrected_distance)
    print(f"   This would give {corrected_combinations} combinations (vs {total_combinations} current)")
    print(f"   100% success rate vs current {valid_combinations/total_combinations*100:.1f}%")

if __name__ == "__main__":
    analyze_phase1_grid()