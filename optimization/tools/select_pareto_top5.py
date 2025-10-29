#!/usr/bin/env python3
"""
Pareto Frontier Top 5 Selection Tool for Phase 6 Optimization Results

This script selects 5 diverse parameter sets from the Pareto frontier for Phase 7 walk-forward validation.
It uses a diversity-based selection strategy to ensure robust out-of-sample testing.
"""

import json
import argparse
import sys
import pathlib
import logging
import numpy as np
from typing import Dict, List, Any, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_pareto_frontier(json_path: str) -> Dict[str, Any]:
    """Load Pareto frontier JSON from grid search results."""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        logger.info(f"Loaded Pareto frontier with {len(data.get('frontier', []))} points")
        
        # Validate structure
        if 'objectives' not in data or 'frontier' not in data:
            raise ValueError("Invalid Pareto frontier structure")
        
        return data
        
    except Exception as e:
        logger.error(f"Error loading Pareto frontier: {e}")
        sys.exit(1)

def normalize_objectives(frontier: List[Dict], objectives: List[str]) -> np.ndarray:
    """Normalize objectives to [0, 1] range for fair comparison."""
    if not frontier:
        return np.array([])
    
    # Extract objective values (support nested 'objective_values' structure)
    objective_values = []
    for point in frontier:
        values = []
        obj_map = point.get('objective_values', {})
        for obj in objectives:
            if obj in obj_map:
                values.append(obj_map[obj])
            else:
                # Fallback to metrics or top-level if present
                metrics = point.get('metrics', {})
                if obj in metrics:
                    values.append(metrics[obj])
                else:
                    values.append(point.get(obj, 0.0))
        objective_values.append(values)
    
    objective_values = np.array(objective_values)
    
    # Normalize each objective to [0, 1]
    normalized = np.zeros_like(objective_values)
    for i, obj in enumerate(objectives):
        col = objective_values[:, i]
        min_val = np.min(col)
        max_val = np.max(col)
        
        if max_val > min_val:
            # Check if this is a minimization objective
            if obj in ['max_drawdown', 'min_max_drawdown', 'consecutive_losses', 'min_consecutive_losses']:
                # For minimization objectives, invert the normalization
                # normalized = (max - value) / (max - min) so that higher values become lower normalized scores
                normalized[:, i] = (max_val - col) / (max_val - min_val)
            else:
                # For maximization objectives, normal normalization
                normalized[:, i] = (col - min_val) / (max_val - min_val)
        else:
            # All values are the same
            normalized[:, i] = 0.5
    
    return normalized

def select_diverse_points(frontier: List[Dict], normalized_objectives: np.ndarray, 
                         objectives: List[str], n: int = 5) -> List[Dict[str, Any]]:
    """Select diverse points from Pareto frontier using diversity-based strategy."""
    if len(frontier) <= n:
        # Return all points if frontier is small
        return [dict(point) for point in frontier]
    
    selected_points = []
    selected_indices = []
    
    # Strategy 1: Best Sharpe ratio
    sharpe_idx = 0
    if 'sharpe_ratio' in objectives:
        sharpe_idx = objectives.index('sharpe_ratio')
        best_sharpe_idx = np.argmax(normalized_objectives[:, sharpe_idx])
        selected_points.append(dict(frontier[best_sharpe_idx]))
        selected_indices.append(best_sharpe_idx)
    
    # Strategy 2: Best PnL (if different from best Sharpe)
    pnl_idx = 1 if 'total_pnl' in objectives else 0
    if 'total_pnl' in objectives:
        best_pnl_idx = np.argmax(normalized_objectives[:, pnl_idx])
        if best_pnl_idx not in selected_indices:
            selected_points.append(dict(frontier[best_pnl_idx]))
            selected_indices.append(best_pnl_idx)
    
    # Strategy 3: Best Drawdown (if different from already selected)
    drawdown_idx = 2 if 'max_drawdown' in objectives else 1
    if 'max_drawdown' in objectives:
        # For drawdown, we want minimum (best) raw value
        # Since max_drawdown is a minimization objective, it gets inverted during normalization
        # So higher normalized values correspond to lower (better) raw drawdown values
        best_drawdown_idx = np.argmax(normalized_objectives[:, drawdown_idx])
        if best_drawdown_idx not in selected_indices:
            selected_points.append(dict(frontier[best_drawdown_idx]))
            selected_indices.append(best_drawdown_idx)
    
    # Strategy 4: Balanced point (closest to ideal point (1,1,1))
    if len(selected_indices) < n:
        ideal_point = np.ones(len(objectives))
        distances = np.linalg.norm(normalized_objectives - ideal_point, axis=1)
        
        # Find point closest to ideal that's not already selected
        for idx in np.argsort(distances):
            if idx not in selected_indices:
                selected_points.append(dict(frontier[idx]))
                selected_indices.append(idx)
                break
    
    # Strategy 5: Maximum diversity point
    if len(selected_indices) < n:
        # Find point with maximum minimum distance to already selected points
        max_min_distance = -1
        best_diversity_idx = -1
        
        for i in range(len(frontier)):
            if i in selected_indices:
                continue
                
            # Calculate minimum distance to already selected points
            min_distance = float('inf')
            for selected_idx in selected_indices:
                distance = np.linalg.norm(normalized_objectives[i] - normalized_objectives[selected_idx])
                min_distance = min(min_distance, distance)
            
            if min_distance > max_min_distance:
                max_min_distance = min_distance
                best_diversity_idx = i
        
        if best_diversity_idx != -1:
            selected_points.append(dict(frontier[best_diversity_idx]))
            selected_indices.append(best_diversity_idx)
    
    # Fill remaining slots with next best points if needed
    while len(selected_points) < n and len(selected_points) < len(frontier):
        # Find next best point by combined score
        best_score = -1
        best_idx = -1
        
        for i in range(len(frontier)):
            if i in selected_indices:
                continue
                
            # Calculate combined normalized score
            score = np.mean(normalized_objectives[i])
            if score > best_score:
                best_score = score
                best_idx = i
        
        if best_idx != -1:
            selected_points.append(dict(frontier[best_idx]))
            selected_indices.append(best_idx)
    
    return selected_points[:n]

def calculate_trade_offs(selected_points: List[Dict], objectives: List[str], full_frontier: List[Dict] = None) -> Dict[int, Dict[str, Any]]:
    """Calculate trade-offs for each selected point."""
    trade_offs = {}
    
    # Use full frontier if provided, otherwise use selected points
    reference_points = full_frontier if full_frontier is not None else selected_points
    
    # Calculate percentiles for each objective across all reference points
    objective_values = {obj: [] for obj in objectives}
    for point in reference_points:
        obj_map = point.get('objective_values', {})
        for obj in objectives:
            val = obj_map.get(obj)
            if val is None:
                val = point.get('metrics', {}).get(obj, point.get(obj))
            if val is not None:
                objective_values[obj].append(val)
    
    for obj in objectives:
        if objective_values[obj]:
            objective_values[obj] = np.array(objective_values[obj])
    
    for i, point in enumerate(selected_points):
        strengths = []
        weaknesses = []
        
        for obj in objectives:
            if (point.get('objective_values', {}).get(obj) is None and
                point.get('metrics', {}).get(obj) is None and
                point.get(obj) is None) or not objective_values[obj].size:
                continue
                
            value = point.get('objective_values', {}).get(obj, point.get('metrics', {}).get(obj, point.get(obj, 0)))
            values = objective_values[obj]
            
            # Calculate percentile
            percentile = (np.sum(values <= value) / len(values)) * 100
            
            if percentile >= 75:  # Top 25%
                strengths.append(f"{obj} (top {100-percentile:.0f}%)")
            elif percentile <= 25:  # Bottom 25%
                weaknesses.append(f"{obj} (bottom {percentile:.0f}%)")
        
        # Generate description
        if strengths and weaknesses:
            description = f"Strong in {', '.join(strengths)} but weak in {', '.join(weaknesses)}"
        elif strengths:
            description = f"Strong in {', '.join(strengths)}"
        elif weaknesses:
            description = f"Weak in {', '.join(weaknesses)}"
        else:
            description = "Balanced performance across objectives"
        
        trade_offs[i] = {
            'strengths': strengths,
            'weaknesses': weaknesses,
            'description': description
        }
    
    return trade_offs

def export_top5_for_walkforward(selected_points: List[Dict], trade_offs: Dict[int, Dict[str, Any]], 
                              output_path: str) -> None:
    """Export top 5 parameter sets for Phase 7 walk-forward validation."""
    output_dir = pathlib.Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create structure for walk-forward validation
    walkforward_data = {
        "source": "phase6_refinement",
        "selection_method": "pareto_diversity",
        "objectives": ["sharpe_ratio", "total_pnl", "max_drawdown"],
        "parameter_sets": []
    }
    
    # Add each selected parameter set
    for i, point in enumerate(selected_points):
        # Extract parameters from point['parameters'] directly, excluding run_id
        parameters = {}
        if 'parameters' in point:
            for key, value in point['parameters'].items():
                if key != 'run_id':
                    parameters[key] = value
        else:
            # Fallback: extract parameters excluding objectives and metadata
            for key, value in point.items():
                if key not in ['sharpe_ratio', 'total_pnl', 'max_drawdown', 'profit_factor', 'win_rate', 'total_trades', 'run_id']:
                    parameters[key] = value
        
        # Get performance metrics
        expected_performance = {}
        obj_map = point.get('objective_values', {})
        for obj in ["sharpe_ratio", "total_pnl", "max_drawdown"]:
            if obj in obj_map:
                expected_performance[obj] = obj_map[obj]
            elif obj in point.get('metrics', {}):
                expected_performance[obj] = point['metrics'][obj]
            elif obj in point:
                expected_performance[obj] = point[obj]
        
        # Determine name based on selection strategy
        if i == 0:
            name = "best_sharpe"
        elif i == 1:
            name = "best_pnl"
        elif i == 2:
            name = "best_drawdown"
        elif i == 3:
            name = "balanced_1"
        else:
            name = "balanced_2"
        
        parameter_set = {
            "id": i + 1,
            "name": name,
            "parameters": parameters,
            "expected_performance": expected_performance,
            "trade_offs": trade_offs.get(i, {}).get('description', 'No trade-off analysis available'),
            "strengths": trade_offs.get(i, {}).get('strengths', []),
            "weaknesses": trade_offs.get(i, {}).get('weaknesses', [])
        }
        
        walkforward_data["parameter_sets"].append(parameter_set)
    
    # Write to JSON
    with open(output_path, 'w') as f:
        json.dump(walkforward_data, f, indent=2)
    
    logger.info(f"Exported {len(selected_points)} parameter sets to {output_path}")

def generate_selection_report(selected_points: List[Dict], trade_offs: Dict[int, Dict[str, Any]], 
                            frontier_size: int, output_path: str) -> None:
    """Generate markdown report explaining the selection."""
    report_path = pathlib.Path(output_path).parent / "phase6_pareto_selection_report.md"
    
    with open(report_path, 'w') as f:
        f.write("# Phase 6 Pareto Frontier Top 5 Selection Report\n\n")
        
        f.write(f"**Pareto frontier size**: {frontier_size} non-dominated solutions\n")
        f.write(f"**Selection method**: Diversity-based (best Sharpe, best PnL, best drawdown, 2 balanced)\n\n")
        
        f.write("## Selected Parameter Sets\n\n")
        f.write("| ID | Name | Sharpe | PnL | Drawdown | Trade-offs |\n")
        f.write("|----|------|--------|-----|----------|------------|\n")
        
        for i, point in enumerate(selected_points):
            name = ["best_sharpe", "best_pnl", "best_drawdown", "balanced_1", "balanced_2"][i]
            sharpe = point.get('objective_values', {}).get('sharpe_ratio', point.get('metrics', {}).get('sharpe_ratio', point.get('sharpe_ratio', 0)))
            pnl = point.get('objective_values', {}).get('total_pnl', point.get('metrics', {}).get('total_pnl', point.get('total_pnl', 0)))
            drawdown = point.get('objective_values', {}).get('max_drawdown', point.get('metrics', {}).get('max_drawdown', point.get('max_drawdown', 0)))
            trade_off = trade_offs.get(i, {}).get('description', 'N/A')
            
            f.write(f"| {i+1} | {name} | {sharpe:.4f} | ${pnl:,.0f} | ${drawdown:,.0f} | {trade_off} |\n")
        
        f.write("\n## Detailed Parameter Set Descriptions\n\n")
        
        for i, point in enumerate(selected_points):
            name = ["best_sharpe", "best_pnl", "best_drawdown", "balanced_1", "balanced_2"][i]
            f.write(f"### Parameter Set {i+1}: {name.replace('_', ' ').title()}\n\n")
            
            # Performance metrics
            f.write("**Performance Metrics:**\n")
            f.write(f"- Sharpe Ratio: {point.get('sharpe_ratio', 0):.4f}\n")
            f.write(f"- Total PnL: ${point.get('total_pnl', 0):,.0f}\n")
            f.write(f"- Max Drawdown: ${point.get('max_drawdown', 0):,.0f}\n")
            # Additional metrics if available
            m = point.get('metrics', {})
            if 'profit_factor' in m:
                f.write(f"- Profit Factor: {m.get('profit_factor', 0):.2f}\n")
            if 'win_rate' in m:
                f.write(f"- Win Rate: {m.get('win_rate', 0):.1%}\n")
            if 'trade_count' in m:
                f.write(f"- Total Trades: {m.get('trade_count', 0)}\n\n")
            
            # Parameters
            f.write("**Parameters:**\n")
            # Print parameters and any extra keys except nested structures
            for key, value in point.items():
                if key in ['objective_values', 'metrics', 'parameters']:
                    continue
                if key not in ['sharpe_ratio', 'total_pnl', 'max_drawdown', 'profit_factor', 'win_rate', 'total_trades']:
                    f.write(f"- {key}: {value}\n")
            
            # Trade-offs
            f.write(f"\n**Trade-offs**: {trade_offs.get(i, {}).get('description', 'N/A')}\n")
            
            # Strengths and weaknesses
            if trade_offs.get(i, {}).get('strengths'):
                f.write(f"\n**Strengths**: {', '.join(trade_offs[i]['strengths'])}\n")
            if trade_offs.get(i, {}).get('weaknesses'):
                f.write(f"\n**Weaknesses**: {', '.join(trade_offs[i]['weaknesses'])}\n")
            
            f.write("\n---\n\n")
        
        f.write("## Selection Methodology\n\n")
        f.write("The 5 parameter sets were selected using a diversity-based approach:\n\n")
        f.write("1. **Best Sharpe**: Highest risk-adjusted returns\n")
        f.write("2. **Best PnL**: Highest absolute returns (if different from best Sharpe)\n")
        f.write("3. **Best Drawdown**: Lowest maximum drawdown (if different from above)\n")
        f.write("4. **Balanced 1**: Point closest to ideal (1,1,1) in normalized objective space\n")
        f.write("5. **Balanced 2**: Point with maximum diversity from already selected points\n\n")
        
        f.write("This selection strategy ensures robust walk-forward validation by testing:\n")
        f.write("- High Sharpe strategies (risk-adjusted performance)\n")
        f.write("- High return strategies (absolute performance)\n")
        f.write("- Low drawdown strategies (capital preservation)\n")
        f.write("- Balanced strategies (compromise solutions)\n")
        f.write("- Diverse strategies (different parameter combinations)\n")
    
    logger.info(f"Exported selection report to {report_path}")

def main():
    """Main function to select top 5 parameter sets from Pareto frontier."""
    parser = argparse.ArgumentParser(description='Select top 5 parameter sets from Pareto frontier')
    parser.add_argument('--pareto-json', 
                       default='optimization/results/phase6_refinement_results_pareto_frontier.json',
                       help='Path to Pareto frontier JSON')
    parser.add_argument('--output', 
                       default='optimization/results/phase6_top_5_parameters.json',
                       help='Path to output top 5 JSON')
    parser.add_argument('--n', type=int, default=5,
                       help='Number of parameter sets to select')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting Pareto frontier top 5 selection...")
    
    # Load Pareto frontier
    pareto_data = load_pareto_frontier(args.pareto_json)
    frontier = pareto_data['frontier']
    objectives = pareto_data['objectives']
    
    if not frontier:
        logger.error("Empty Pareto frontier")
        sys.exit(1)
    
    # Normalize objectives
    logger.info("Normalizing objectives...")
    normalized_objectives = normalize_objectives(frontier, objectives)
    
    # Select diverse points
    logger.info(f"Selecting {args.n} diverse points from {len(frontier)} frontier points...")
    selected_points = select_diverse_points(frontier, normalized_objectives, objectives, args.n)
    
    # Calculate trade-offs
    logger.info("Calculating trade-offs...")
    trade_offs = calculate_trade_offs(selected_points, objectives, frontier)
    
    # Export for walk-forward validation
    logger.info("Exporting top 5 parameter sets...")
    export_top5_for_walkforward(selected_points, trade_offs, args.output)
    
    # Generate selection report
    logger.info("Generating selection report...")
    generate_selection_report(selected_points, trade_offs, len(frontier), args.output)
    
    # Print summary
    print("\n" + "="*60)
    print("PARETO FRONTIER TOP 5 SELECTION SUMMARY")
    print("="*60)
    print(f"Frontier size: {len(frontier)} non-dominated solutions")
    print(f"Selected parameter sets: {len(selected_points)}")
    print(f"Selection method: Diversity-based")
    print(f"\nSelected parameter sets:")
    for i, point in enumerate(selected_points):
        name = ["best_sharpe", "best_pnl", "best_drawdown", "balanced_1", "balanced_2"][i]
        sharpe = point.get('objective_values', {}).get('sharpe_ratio', point.get('metrics', {}).get('sharpe_ratio', point.get('sharpe_ratio', 0)))
        pnl = point.get('objective_values', {}).get('total_pnl', point.get('metrics', {}).get('total_pnl', point.get('total_pnl', 0)))
        drawdown = point.get('objective_values', {}).get('max_drawdown', point.get('metrics', {}).get('max_drawdown', point.get('max_drawdown', 0)))
        print(f"  {i+1}. {name}: Sharpe={sharpe:.4f}, PnL=${pnl:,.0f}, Drawdown=${drawdown:,.0f}")
    
    print(f"\nOutput files:")
    print(f"  - {args.output} (for Phase 7 walk-forward)")
    print(f"  - {pathlib.Path(args.output).parent}/phase6_pareto_selection_report.md")
    print("="*60)

if __name__ == "__main__":
    main()
