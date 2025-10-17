"""
Parameter Sensitivity Analysis Tool
-----------------------------------

Purpose:
    Analyze parameter sensitivity from grid search results to identify high-impact parameters
    and provide actionable recommendations. Computes Pearson and Spearman correlations with
    statistical significance testing, detects parameter interactions, and generates
    comprehensive HTML and optional JSON reports with embedded visualizations.

Usage examples:
    Basic:
        python analysis/parameter_sensitivity.py --input optimization/results/grid_search_results.csv

    Multi-objective:
        python analysis/parameter_sensitivity.py --input results.csv --objectives total_pnl sharpe_ratio win_rate

    With JSON export:
        python analysis/parameter_sensitivity.py --input results.csv --json --output reports/sensitivity.html

Output formats:
    - Console report (always)
    - HTML report (always)
    - JSON export (optional with --json flag)

Exit codes:
    - 0: success
    - 1: error
    - 2: invalid arguments

Analysis types:
    - Pearson correlation, Spearman correlation
    - Statistical significance (p-values)
    - Parameter interactions (pairwise interaction detection)
"""

from __future__ import annotations

import argparse
import base64
import io
import itertools
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats


# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# Constants
HIGH_IMPACT_THRESHOLD: float = 0.5
MEDIUM_IMPACT_THRESHOLD: float = 0.3
SIGNIFICANCE_LEVEL: float = 0.05
MIN_SAMPLES_FOR_CORRELATION: int = 10
CHART_STYLE: str = "whitegrid"
CHART_DPI: int = 100
MAX_INTERACTION_PAIRS: int = 15


# Dataclasses
@dataclass
class ParameterSensitivity:
    parameter_name: str
    objective_name: str
    pearson_correlation: float
    pearson_pvalue: float
    spearman_correlation: float
    spearman_pvalue: float
    impact_level: str
    is_significant: bool
    sample_size: int


@dataclass
class ParameterInteraction:
    param1_name: str
    param2_name: str
    objective_name: str
    interaction_strength: float
    description: str


@dataclass
class SensitivityReport:
    input_file: str
    total_runs: int
    completed_runs: int
    parameters_analyzed: List[str]
    objectives_analyzed: List[str]
    sensitivities: List[ParameterSensitivity]
    interactions: List[ParameterInteraction]
    recommendations: List[str]


# Data loading and detection
def load_grid_search_results(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists() or not csv_path.is_file():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to read CSV: {exc}")

    required_columns = {"run_id", "status"}
    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    total = len(df)
    df_completed = df[df["status"].astype(str).str.lower() == "completed"].copy()
    completed = len(df_completed)
    logger.info("Loaded grid search results: total_runs=%s completed_runs=%s", total, completed)

    # Optional: infer date range if timestamp present
    ts_col = None
    for c in ["timestamp", "start_time", "end_time", "created_at"]:
        if c in df_completed.columns:
            ts_col = c
            break
    if ts_col is not None:
        try:
            ts = pd.to_datetime(df_completed[ts_col], errors="coerce")
            if ts.notna().any():
                logger.info("Completed runs time range: %s to %s", ts.min(), ts.max())
        except Exception:
            pass

    return df_completed


def detect_parameter_columns(df: pd.DataFrame) -> List[str]:
    metadata_exclusions = {
        "run_id",
        "status",
        "output_directory",
        "timestamp",
        "objective_value",
        "rank",
        "start_time",
        "end_time",
    }

    # Whitelist of known parameter names from grid_search.ParameterSet
    known_parameter_names = {
        "fast_period",
        "slow_period",
        "crossover_threshold_pips",
        "stop_loss_pips",
        "take_profit_pips",
        "trailing_stop_activation_pips",
        "trailing_stop_distance_pips",
        "dmi_enabled",
        "dmi_period",
        "stoch_enabled",
        "stoch_period_k",
        "stoch_period_d",
        "stoch_bullish_threshold",
        "stoch_bearish_threshold",
    }

    candidate_columns: List[str] = []
    for col in df.columns:
        if col in metadata_exclusions:
            continue
        series = df[col]
        if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
            if series.nunique(dropna=True) > 1:
                candidate_columns.append(col)

    # Enhanced heuristic: remove columns that look like metrics/objectives by substring
    objective_name_hints = {
        "total_pnl",
        "sharpe",
        "sharpe_ratio",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "expectancy",
        "consecutive_losses",
        "objective",
        "objective_value",
        "sortino",
        "calmar",
        "trade_count",
        "avg_winner",
        "avg_loser",
    }

    def looks_like_metric(col_name: str, series: pd.Series) -> bool:
        name_lc = col_name.lower()
        if any(h in name_lc for h in objective_name_hints):
            return True
        # Optional numeric range heuristic for win_rate in [0,1]
        if name_lc == "win_rate":
            vals = pd.to_numeric(series, errors="coerce")
            if vals.notna().any():
                vmin = float(vals.min())
                vmax = float(vals.max())
                if 0.0 <= vmin <= 1.0 and 0.0 <= vmax <= 1.0:
                    return True
        return False

    parameters: List[str] = []
    for c in candidate_columns:
        s = df[c]
        if c in known_parameter_names:
            parameters.append(c)
            continue
        if looks_like_metric(c, s):
            continue
        parameters.append(c)

    parameters = sorted(parameters)
    logger.info("Detected parameter columns: %s", parameters)
    return parameters


def detect_objective_columns(df: pd.DataFrame, parameter_columns: Optional[List[str]] = None) -> List[str]:
    if parameter_columns is None:
        parameter_columns = []
    metadata_exclusions = {
        "run_id",
        "status",
        "output_directory",
        "timestamp",
        "rank",
        "start_time",
        "end_time",
    }
    objectives: List[str] = []
    for col in df.columns:
        if col in metadata_exclusions or col in parameter_columns:
            continue
        series = df[col]
        if pd.api.types.is_numeric_dtype(series) and series.notna().sum() >= MIN_SAMPLES_FOR_CORRELATION:
            # Likely a metric/objective if not constant
            if series.nunique(dropna=True) > 1:
                objectives.append(col)
    objectives = sorted(objectives)
    logger.info("Detected objective columns: %s", objectives)
    return objectives


def validate_data_for_analysis(df: pd.DataFrame, parameters: List[str], objectives: List[str]) -> bool:
    if len(df) < MIN_SAMPLES_FOR_CORRELATION:
        logger.warning("Insufficient samples: %s < %s", len(df), MIN_SAMPLES_FOR_CORRELATION)
        return False

    if not parameters:
        logger.warning("No parameter columns detected.")
        return False
    if not objectives:
        logger.warning("No objective columns detected.")
        return False

    # Collect and remove no-variance columns; log them instead of aborting
    dropped_params = [c for c in parameters if df[c].dropna().nunique() <= 1]
    dropped_objs = [c for c in objectives if df[c].dropna().nunique() <= 1]
    if dropped_params:
        logger.warning("Dropping parameter columns with no variance: %s", dropped_params)
    if dropped_objs:
        logger.warning("Dropping objective columns with no variance: %s", dropped_objs)

    # Missing data check (<20% NaN allowed)
    for c in parameters + objectives:
        if c in dropped_params or c in dropped_objs:
            continue
        na_ratio = df[c].isna().mean()
        if na_ratio > 0.2:
            logger.warning("Excessive missing data in %s: %.1f%%", c, na_ratio * 100)

    remaining_params = [c for c in parameters if c not in dropped_params]
    remaining_objs = [c for c in objectives if c not in dropped_objs]
    if not remaining_params or not remaining_objs:
        logger.warning("No analyzable columns remain after filtering.")
        return False
    return True


# Correlation analysis
def calculate_correlations(df: pd.DataFrame, parameter: str, objective: str) -> Tuple[float, float, float, float, int]:
    data = df[[parameter, objective]].dropna()
    n = len(data)
    if n < MIN_SAMPLES_FOR_CORRELATION:
        return (np.nan, np.nan, np.nan, np.nan, n)
    x = data[parameter]
    y = data[objective]
    if x.nunique() <= 1 or y.nunique() <= 1:
        return (np.nan, np.nan, np.nan, np.nan, n)
    try:
        pearson_r, pearson_p = stats.pearsonr(x, y)
    except Exception:
        pearson_r, pearson_p = (np.nan, np.nan)
    try:
        spearman_r, spearman_p = stats.spearmanr(x, y)
    except Exception:
        spearman_r, spearman_p = (np.nan, np.nan)
    return (float(pearson_r), float(pearson_p), float(spearman_r), float(spearman_p), int(n))


def classify_impact_level(correlation: float, pvalue: float) -> str:
    if not np.isfinite(correlation) or not np.isfinite(pvalue):
        return "low"
    if pvalue >= SIGNIFICANCE_LEVEL:
        return "low"
    if abs(correlation) >= HIGH_IMPACT_THRESHOLD:
        return "high"
    if abs(correlation) >= MEDIUM_IMPACT_THRESHOLD:
        return "medium"
    return "low"


def analyze_parameter_sensitivity(df: pd.DataFrame, parameters: List[str], objectives: List[str]) -> List[ParameterSensitivity]:
    total = len(parameters) * len(objectives)
    logger.info("Analyzing %s parameters x %s objectives = %s combinations", len(parameters), len(objectives), total)
    results: List[ParameterSensitivity] = []
    for param in parameters:
        for obj in objectives:
            pr, pp, sr, sp, n = calculate_correlations(df, param, obj)
            impact = classify_impact_level(pr if np.isfinite(pr) else 0.0, pp if np.isfinite(pp) else 1.0)
            is_sig = (pp < SIGNIFICANCE_LEVEL) if np.isfinite(pp) else False
            results.append(
                ParameterSensitivity(
                    parameter_name=param,
                    objective_name=obj,
                    pearson_correlation=pr if np.isfinite(pr) else np.nan,
                    pearson_pvalue=pp if np.isfinite(pp) else np.nan,
                    spearman_correlation=sr if np.isfinite(sr) else np.nan,
                    spearman_pvalue=sp if np.isfinite(sp) else np.nan,
                    impact_level=impact,
                    is_significant=is_sig,
                    sample_size=n,
                )
            )
    return results


def detect_parameter_interactions(df: pd.DataFrame, parameters: List[str], objectives: List[str]) -> List[ParameterInteraction]:
    params_to_check = parameters
    if len(parameters) > 10:
        # Select top parameters by max absolute correlation across objectives (using Pearson as proxy)
        sens = analyze_parameter_sensitivity(df, parameters, objectives)
        param_to_score: Dict[str, float] = {}
        for s in sens:
            score = abs(s.pearson_correlation) if np.isfinite(s.pearson_correlation) else 0.0
            param_to_score[s.parameter_name] = max(param_to_score.get(s.parameter_name, 0.0), score)
        # Reduce shortlist size to 8 for better coverage when parameter count is large
        params_to_check = [p for p, _ in sorted(param_to_score.items(), key=lambda kv: kv[1], reverse=True)[:8]]

    # Calculate theoretical pair count and effective cap
    theoretical_pairs = len(list(itertools.combinations(params_to_check, 2)))
    effective_cap = min(MAX_INTERACTION_PAIRS, theoretical_pairs)
    cap_engaged = effective_cap < theoretical_pairs
    
    logger.info(
        "Interaction detection: parameters=%d, theoretical_pairs=%d, effective_cap=%d, cap_engaged=%s",
        len(params_to_check), theoretical_pairs, effective_cap, cap_engaged
    )

    interactions: List[ParameterInteraction] = []
    pairs_evaluated = 0
    
    for p1, p2 in itertools.combinations(params_to_check, 2):
        if pairs_evaluated >= effective_cap:
            break
            
        inter_term = df[p1] * df[p2]
        # Compare interaction vs individual correlations
        for obj in objectives:
            comp_df = pd.DataFrame({"i": inter_term, p1: df[p1], p2: df[p2], obj: df[obj]}).dropna()
            if len(comp_df) < MIN_SAMPLES_FOR_CORRELATION:
                continue
            try:
                r_i, p_i = stats.pearsonr(comp_df["i"], comp_df[obj])
            except Exception:
                r_i, p_i = (np.nan, np.nan)
            try:
                r_1, _ = stats.pearsonr(comp_df[p1], comp_df[obj])
            except Exception:
                r_1 = np.nan
            try:
                r_2, _ = stats.pearsonr(comp_df[p2], comp_df[obj])
            except Exception:
                r_2 = np.nan

            base = np.nanmax([abs(r_1), abs(r_2)]) if any(np.isfinite(v) for v in [r_1, r_2]) else 0.0
            strength = float(max(0.0, (abs(r_i) if np.isfinite(r_i) else 0.0) - base))
            if np.isfinite(r_i) and np.isfinite(p_i) and p_i < SIGNIFICANCE_LEVEL and strength > 0.1:
                desc = (
                    f"Interaction between {p1} and {p2} on {obj}: |r_int|={abs(r_i):.3f} exceeds max(|r_ind|)={base:.3f}"
                )
                interactions.append(
                    ParameterInteraction(
                        param1_name=p1,
                        param2_name=p2,
                        objective_name=obj,
                        interaction_strength=strength,
                        description=desc,
                    )
                )
        
        pairs_evaluated += 1

    # Limit to top 5 strongest interactions
    interactions.sort(key=lambda x: x.interaction_strength, reverse=True)
    return interactions[:5]


# Recommendations
def generate_recommendations(
    sensitivities: List[ParameterSensitivity],
    interactions: List[ParameterInteraction],
    parameters: List[str],
) -> List[str]:
    recs: List[str] = []

    # High-impact per objective
    by_param: Dict[str, List[ParameterSensitivity]] = {}
    for s in sensitivities:
        by_param.setdefault(s.parameter_name, []).append(s)

    for param, sens_list in by_param.items():
        # Significant correlations
        significant = [s for s in sens_list if s.is_significant and np.isfinite(s.pearson_correlation)]
        if significant:
            best = max(significant, key=lambda s: abs(s.pearson_correlation))
            if abs(best.pearson_correlation) >= HIGH_IMPACT_THRESHOLD:
                recs.append(
                    f"Parameter {param} strongly influences {best.objective_name} (correlation={best.pearson_correlation:.3f}, p={best.pearson_pvalue:.4f}). Prioritize careful tuning of this parameter."
                )
            elif abs(best.pearson_correlation) >= MEDIUM_IMPACT_THRESHOLD:
                recs.append(
                    f"Parameter {param} moderately influences {best.objective_name} (correlation={best.pearson_correlation:.3f}, p={best.pearson_pvalue:.4f}). Consider tuning this parameter."
                )

        # Low-impact overall
        max_abs = max([abs(s.pearson_correlation) if np.isfinite(s.pearson_correlation) else 0.0 for s in sens_list])
        if max_abs < MEDIUM_IMPACT_THRESHOLD:
            recs.append(
                f"Parameter {param} shows weak influence across all objectives (max |correlation|={max_abs:.3f}). Consider fixing this parameter to reduce search space."
            )

        # Inconsistent sign across objectives
        signs = set()
        for s in sens_list:
            if np.isfinite(s.pearson_correlation) and s.is_significant and abs(s.pearson_correlation) >= MEDIUM_IMPACT_THRESHOLD:
                signs.add(np.sign(s.pearson_correlation))
        if len(signs) > 1:
            pos_objs = [s.objective_name for s in sens_list if s.is_significant and s.pearson_correlation > 0]
            neg_objs = [s.objective_name for s in sens_list if s.is_significant and s.pearson_correlation < 0]
            if pos_objs and neg_objs:
                recs.append(
                    f"Parameter {param} has opposite effects on different objectives (positive for {', '.join(pos_objs)}, negative for {', '.join(neg_objs)}). Requires multi-objective optimization."
                )

    if interactions:
        for inter in interactions:
            recs.append(
                f"Parameters {inter.param1_name} and {inter.param2_name} show interaction effects on {inter.objective_name}. Consider joint optimization."
            )

    # Insignificant parameters
    insignificant = []
    for p in parameters:
        sens_list = by_param.get(p, [])
        if sens_list and not any(s.is_significant for s in sens_list):
            insignificant.append(p)
    if insignificant:
        recs.append(
            f"Parameters {', '.join(sorted(insignificant))} show no statistically significant correlations. May be noise or require larger sample size."
        )

    # Deduplicate while preserving order
    seen: set = set()
    deduped: List[str] = []
    for r in recs:
        if r not in seen:
            deduped.append(r)
            seen.add(r)
    # Sort with high-impact style recommendations first (heuristic by keywords)
    priority = [
        "strongly influences",
        "moderately influences",
        "interaction effects",
        "opposite effects",
        "weak influence",
        "no statistically significant",
    ]
    deduped.sort(key=lambda x: next((i for i, k in enumerate(priority) if k in x), len(priority)))
    return deduped


# Chart helpers
def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return data


def create_correlation_heatmap(sensitivities: List[ParameterSensitivity], correlation_type: str = "pearson") -> str:
    sns.set_style(CHART_STYLE)
    params = sorted({s.parameter_name for s in sensitivities})
    objs = sorted({s.objective_name for s in sensitivities})
    mat = pd.DataFrame(index=params, columns=objs, dtype=float)
    sig = pd.DataFrame(index=params, columns=objs, dtype=bool)
    for s in sensitivities:
        val = s.pearson_correlation if correlation_type == "pearson" else s.spearman_correlation
        p = s.pearson_pvalue if correlation_type == "pearson" else s.spearman_pvalue
        mat.loc[s.parameter_name, s.objective_name] = val
        sig.loc[s.parameter_name, s.objective_name] = (p < SIGNIFICANCE_LEVEL) if np.isfinite(p) else False

    fig, ax = plt.subplots(figsize=(12, 8))
    cmap = sns.diverging_palette(240, 10, as_cmap=True)
    sns.heatmap(mat.astype(float), ax=ax, cmap=cmap, center=0.0, annot=True, fmt=".2f", cbar=True, linewidths=0.5, linecolor="#f0f0f0")
    # Add asterisks for significant cells
    for i, p in enumerate(mat.index):
        for j, o in enumerate(mat.columns):
            if bool(sig.loc[p, o]):
                ax.text(j + 0.5, i + 0.3, "*", ha="center", va="center", color="black", fontsize=14)
    ax.set_title(f"{correlation_type.capitalize()} Correlation: Parameters vs Objectives")
    ax.set_xlabel("Objectives")
    ax.set_ylabel("Parameters")
    plt.tight_layout()
    return _fig_to_base64(fig)


def create_impact_ranking_chart(sensitivities: List[ParameterSensitivity], objective: str) -> str:
    sns.set_style(CHART_STYLE)
    rows = [s for s in sensitivities if s.objective_name == objective]
    if not rows:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, f"No data for {objective}", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    df = pd.DataFrame({
        "parameter": [r.parameter_name for r in rows],
        "corr": [r.pearson_correlation for r in rows],
        "impact": [r.impact_level for r in rows],
    })
    df["abs_corr"] = df["corr"].abs()
    df = df.sort_values("abs_corr", ascending=False)
    color_map = {"high": "#d62728", "medium": "#ff7f0e", "low": "#9e9e9e"}
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(df["parameter"], df["abs_corr"], color=[color_map.get(i, "#9e9e9e") for i in df["impact"]])
    ax.invert_yaxis()
    ax.set_xlabel("|Correlation| (Pearson)")
    ax.set_title(f"Parameter Impact Ranking for {objective}")
    for bar, val in zip(bars, df["abs_corr"]):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2, f"{val:.2f}", va="center")
    plt.tight_layout()
    return _fig_to_base64(fig)


def create_scatter_plots(df: pd.DataFrame, high_impact_params: List[Tuple[str, str, float]]) -> Dict[str, str]:
    sns.set_style(CHART_STYLE)
    plots: Dict[str, str] = {}
    top = sorted(high_impact_params, key=lambda t: abs(t[2]), reverse=True)[:6]
    for param, objective, corr in top:
        data = df[[param, objective]].dropna()
        if len(data) < MIN_SAMPLES_FOR_CORRELATION:
            continue
        fig, ax = plt.subplots(figsize=(8, 6))
        sns.regplot(data=data, x=param, y=objective, ax=ax, scatter_kws={"alpha": 0.6, "s": 20}, line_kws={"color": "#2ca02c"})
        try:
            r, p = stats.pearsonr(data[param], data[objective])
        except Exception:
            r, p = (np.nan, np.nan)
        ax.set_title(f"{param} vs {objective} (r={r:.2f} p={p:.3f})")
        ax.set_xlabel(param)
        ax.set_ylabel(objective)
        plt.tight_layout()
        key = f"{param}__{objective}"
        plots[key] = _fig_to_base64(fig)
    return plots


def create_parameter_interaction_heatmap(df: pd.DataFrame, param1: str, param2: str, objective: str) -> str:
    sns.set_style(CHART_STYLE)
    data = df[[param1, param2, objective]].dropna()
    if data.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    pivot = data.pivot_table(index=param1, columns=param2, values=objective, aggfunc=np.mean)
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pivot, ax=ax, cmap="viridis", cbar=True)
    ax.set_title(f"Interaction: {param1} x {param2} on {objective}")
    ax.set_xlabel(param2)
    ax.set_ylabel(param1)
    plt.tight_layout()
    return _fig_to_base64(fig)


def create_sensitivity_summary_chart(sensitivities: List[ParameterSensitivity]) -> str:
    sns.set_style(CHART_STYLE)
    if not sensitivities:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")
        return _fig_to_base64(fig)
    params = sorted({s.parameter_name for s in sensitivities})
    objs = sorted({s.objective_name for s in sensitivities})
    # Build matrix of Pearson correlations
    mat = pd.DataFrame(index=params, columns=objs, dtype=float)
    for s in sensitivities:
        mat.loc[s.parameter_name, s.objective_name] = s.pearson_correlation
    fig, ax = plt.subplots(figsize=(max(10, len(params) * 0.8), 6))
    width = 0.8 / max(1, len(objs))
    x = np.arange(len(params))
    for i, obj in enumerate(objs):
        vals = mat[obj].astype(float).fillna(0.0).values
        ax.bar(x + i * width, vals, width=width, label=obj)
    ax.set_xticks(x + (len(objs) - 1) * width / 2)
    ax.set_xticklabels(params, rotation=45, ha="right")
    ax.set_ylabel("Correlation (Pearson)")
    ax.set_title("Sensitivity Summary Across Objectives")
    ax.legend()
    plt.tight_layout()
    return _fig_to_base64(fig)


# Report generation
def generate_console_report(report: SensitivityReport) -> None:
    line = "=" * 80
    subline = "-" * 80
    print(line)
    print("Parameter Sensitivity Analysis Report")
    print(line)
    print("Data Summary")
    print(subline)
    print(f"Input file: {report.input_file}")
    print(f"Total runs: {report.total_runs}")
    print(f"Completed runs: {report.completed_runs}")
    print(f"Parameters analyzed: {', '.join(report.parameters_analyzed)}")
    print(f"Objectives analyzed: {', '.join(report.objectives_analyzed)}")
    print()

    # High-impact
    hi = [s for s in report.sensitivities if s.impact_level == "high" and s.is_significant]
    print("High-Impact Parameters")
    print(subline)
    if not hi:
        print("None detected.")
    else:
        header = f"{'Parameter':20} {'Objective':20} {'r(Pearson)':>12} {'p':>8} {'Level':>8}"
        print(header)
        print("." * len(header))
        for s in sorted(hi, key=lambda x: abs(x.pearson_correlation if np.isfinite(x.pearson_correlation) else 0.0), reverse=True):
            r = s.pearson_correlation if np.isfinite(s.pearson_correlation) else np.nan
            p = s.pearson_pvalue if np.isfinite(s.pearson_pvalue) else np.nan
            print(f"{s.parameter_name:20} {s.objective_name:20} {r:12.3f} {p:8.4f} {s.impact_level:>8}")
    print()

    # Low-impact
    print("Low-Impact Parameters")
    print(subline)
    low_params: List[str] = []
    by_param: Dict[str, List[ParameterSensitivity]] = {}
    for s in report.sensitivities:
        by_param.setdefault(s.parameter_name, []).append(s)
    for p, lst in by_param.items():
        max_abs = max([abs(s.pearson_correlation) if np.isfinite(s.pearson_correlation) else 0.0 for s in lst])
        if max_abs < MEDIUM_IMPACT_THRESHOLD:
            low_params.append(p)
    if low_params:
        print(", ".join(sorted(low_params)))
    else:
        print("None detected.")
    print()

    # Interactions
    print("Parameter Interactions")
    print(subline)
    if not report.interactions:
        print("None detected.")
    else:
        for inter in report.interactions:
            print(f"{inter.param1_name} x {inter.param2_name} on {inter.objective_name}: strength={inter.interaction_strength:.3f} - {inter.description}")
    print()

    # Recommendations
    print("Recommendations")
    print(subline)
    if not report.recommendations:
        print("No recommendations generated.")
    else:
        for i, r in enumerate(report.recommendations, 1):
            print(f"{i}. {r}")
    print()


def _serialize_for_json(obj: Any) -> Any:
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    return obj


def generate_json_report(report: SensitivityReport, output_path: Path) -> None:
    data: Dict[str, Any] = {
        "input_file": report.input_file,
        "total_runs": report.total_runs,
        "completed_runs": report.completed_runs,
        "parameters_analyzed": report.parameters_analyzed,
        "objectives_analyzed": report.objectives_analyzed,
        "sensitivities": [
            {
                "parameter": s.parameter_name,
                "objective": s.objective_name,
                "pearson_correlation": _serialize_for_json(s.pearson_correlation),
                "pearson_pvalue": _serialize_for_json(s.pearson_pvalue),
                "spearman_correlation": _serialize_for_json(s.spearman_correlation),
                "spearman_pvalue": _serialize_for_json(s.spearman_pvalue),
                "impact_level": s.impact_level,
                "is_significant": s.is_significant,
                "sample_size": s.sample_size,
            }
            for s in report.sensitivities
        ],
        "interactions": [
            {
                "param1": i.param1_name,
                "param2": i.param2_name,
                "objective": i.objective_name,
                "interaction_strength": _serialize_for_json(i.interaction_strength),
                "description": i.description,
            }
            for i in report.interactions
        ],
        "recommendations": report.recommendations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info("JSON report written to: %s", output_path)


def generate_html_report(report: SensitivityReport, output_path: Path, charts: Dict[str, Any]) -> None:
    css = """
    <style>
      body { font-family: Arial, sans-serif; margin: 24px; color: #222; }
      h1 { margin-bottom: 4px; }
      h2 { margin-top: 28px; border-bottom: 2px solid #eee; padding-bottom: 4px; }
      .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 8px; }
      .card { background: #fafafa; border: 1px solid #eee; border-radius: 8px; padding: 12px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; border-bottom: 1px solid #f0f0f0; padding: 8px; }
      th { background: #f7f7f7; }
      .img-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
      .impact-high { color: #d62728; font-weight: bold; }
      .impact-medium { color: #ff7f0e; font-weight: bold; }
      .impact-low { color: #9e9e9e; font-weight: bold; }
      .footer { color: #666; font-size: 12px; margin-top: 24px; }
    </style>
    """

    def _impact_class(level: str) -> str:
        return {"high": "impact-high", "medium": "impact-medium"}.get(level, "impact-low")

    # Build high-impact table rows
    hi = [s for s in report.sensitivities if s.impact_level == "high" and s.is_significant]
    hi_rows = "\n".join(
        f"<tr><td>{s.parameter_name}</td><td>{s.objective_name}</td><td>{s.pearson_correlation:.3f}</td><td>{s.pearson_pvalue:.4f}</td><td class=\"{_impact_class(s.impact_level)}\">{s.impact_level}</td></tr>"
        for s in sorted(hi, key=lambda x: abs(x.pearson_correlation if np.isfinite(x.pearson_correlation) else 0.0), reverse=True)
    ) or "<tr><td colspan=5>None detected.</td></tr>"

    recommendations_html = "\n".join(f"<li>{r}</li>" for r in report.recommendations) or "<li>No recommendations generated.</li>"

    html = f"""
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <title>Parameter Sensitivity Analysis</title>
        {css}
      </head>
      <body>
        <header>
          <h1>Parameter Sensitivity Analysis</h1>
          <div class=\"summary\">
            <div class=\"card\"><strong>Input file</strong><br>{report.input_file}</div>
            <div class=\"card\"><strong>Total runs</strong><br>{report.total_runs}</div>
            <div class=\"card\"><strong>Completed runs</strong><br>{report.completed_runs}</div>
            <div class=\"card\"><strong>Parameters</strong><br>{', '.join(report.parameters_analyzed)}</div>
            <div class=\"card\"><strong>Objectives</strong><br>{', '.join(report.objectives_analyzed)}</div>
          </div>
        </header>

        <section>
          <h2>Correlation Heatmaps</h2>
          <div class=\"img-row\">
            <img alt=\"Pearson heatmap\" src=\"data:image/png;base64,{charts.get('heatmap_pearson','')}\" />
            <img alt=\"Spearman heatmap\" src=\"data:image/png;base64,{charts.get('heatmap_spearman','')}\" />
          </div>
        </section>

        <section>
          <h2>High-Impact Parameters</h2>
          <table>
            <thead><tr><th>Parameter</th><th>Objective</th><th>r (Pearson)</th><th>p</th><th>Impact</th></tr></thead>
            <tbody>
              {hi_rows}
            </tbody>
          </table>
        </section>

        <section>
          <h2>Impact Rankings by Objective</h2>
          <div class=\"img-row\">
            {''.join(f'<img alt="ranking {o}" src="data:image/png;base64,{charts.get(f"rank_{o}", "")}" />' for o in report.objectives_analyzed)}
          </div>
        </section>

        <section>
          <h2>Scatter Plots (High-Impact Pairs)</h2>
          <div class=\"img-row\">
            {''.join(f'<img alt="scatter {k}" src="data:image/png;base64,{v}" />' for k, v in charts.get('scatters', {}).items())}
          </div>
        </section>

        <section>
          <h2>Parameter Interactions</h2>
          <div class=\"img-row\">
            {''.join(f'<figure><img alt="interaction {k}" src="data:image/png;base64,{v}" /><figcaption>{k}</figcaption></figure>' for k, v in charts.get('interactions', {}).items())}
          </div>
        </section>

        <section>
          <h2>Sensitivity Summary</h2>
          <div class=\"img-row\">
            <img alt=\"summary\" src=\"data:image/png;base64,{charts.get('summary','')}\" />
          </div>
        </section>

        <section>
          <h2>Recommendations</h2>
          <ul>
            {recommendations_html}
          </ul>
        </section>

        <footer class=\"footer\">
          Generated by parameter_sensitivity.py
        </footer>
      </body>
    </html>
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report written to: %s", output_path)


# CLI
def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze parameter sensitivity from grid search CSV results.")
    parser.add_argument("--input", required=True, help="Path to grid search results CSV")
    parser.add_argument("--output", default="reports/parameter_sensitivity.html", help="Path to output HTML report")
    parser.add_argument("--objectives", nargs="*", default=None, help="Specific objective columns to analyze")
    parser.add_argument("--parameters", nargs="*", default=None, help="Specific parameter columns to analyze")
    parser.add_argument("--json", action="store_true", help="Also export JSON report alongside HTML")
    parser.add_argument("--json-output", default=None, help="Path to JSON report output (used when --json is set)")
    parser.add_argument("--no-interactions", action="store_true", help="Disable interaction detection for speed")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES_FOR_CORRELATION, help="Minimum samples required for correlation analysis")

    args = parser.parse_args(argv)

    # Validate input path
    in_path = Path(args.input)
    if not in_path.exists() or not in_path.is_file():
        print(f"Error: input file does not exist: {in_path}", file=sys.stderr)
        sys.exit(2)
    return args


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = parse_arguments(argv)
        if args.verbose:
            logger.setLevel(logging.DEBUG)
            logging.getLogger().setLevel(logging.DEBUG)

        global MIN_SAMPLES_FOR_CORRELATION
        MIN_SAMPLES_FOR_CORRELATION = int(args.min_samples)

        input_path = Path(args.input)
        output_path = Path(args.output)
        json_output_path = Path(args.json_output) if getattr(args, "json_output", None) else output_path.with_suffix(".json")

        df = load_grid_search_results(input_path)
        total_runs = len(pd.read_csv(input_path))
        completed_runs = len(df)

        # Detect parameters/objectives
        parameters = args.parameters if args.parameters else detect_parameter_columns(df)
        objectives = args.objectives if args.objectives else detect_objective_columns(df, parameters)

        # Pre-filter out no-variance columns and log
        filtered_parameters = [c for c in parameters if df[c].dropna().nunique() > 1]
        dropped_p = sorted(set(parameters) - set(filtered_parameters))
        if dropped_p:
            logger.warning("Dropping parameter columns with no variance: %s", dropped_p)
        filtered_objectives = [c for c in objectives if df[c].dropna().nunique() > 1]
        dropped_o = sorted(set(objectives) - set(filtered_objectives))
        if dropped_o:
            logger.warning("Dropping objective columns with no variance: %s", dropped_o)

        parameters = filtered_parameters
        objectives = filtered_objectives

        if not validate_data_for_analysis(df, parameters, objectives):
            logger.error("Validation failed. Aborting.")
            return 1

        sensitivities = analyze_parameter_sensitivity(df, parameters, objectives)
        interactions: List[ParameterInteraction] = []
        if not getattr(args, "no_interactions", False):
            interactions = detect_parameter_interactions(df, parameters, objectives)
        recommendations = generate_recommendations(sensitivities, interactions, parameters)

        report = SensitivityReport(
            input_file=str(input_path),
            total_runs=int(total_runs),
            completed_runs=int(completed_runs),
            parameters_analyzed=parameters,
            objectives_analyzed=objectives,
            sensitivities=sensitivities,
            interactions=interactions,
            recommendations=recommendations,
        )

        # Console report
        generate_console_report(report)

        # Charts
        charts: Dict[str, Any] = {}
        charts["heatmap_pearson"] = create_correlation_heatmap(sensitivities, "pearson")
        charts["heatmap_spearman"] = create_correlation_heatmap(sensitivities, "spearman")
        for obj in objectives:
            charts[f"rank_{obj}"] = create_impact_ranking_chart(sensitivities, obj)

        # High-impact pairs selection for scatter plots
        high_pairs: List[Tuple[str, str, float]] = []
        for s in sensitivities:
            if s.is_significant and abs(s.pearson_correlation) >= MEDIUM_IMPACT_THRESHOLD:
                high_pairs.append((s.parameter_name, s.objective_name, s.pearson_correlation))
        charts["scatters"] = create_scatter_plots(df, high_pairs)

        # Interaction heatmaps
        inter_imgs: Dict[str, str] = {}
        for inter in interactions:
            key = f"{inter.param1_name} x {inter.param2_name} on {inter.objective_name}"
            inter_imgs[key] = create_parameter_interaction_heatmap(df, inter.param1_name, inter.param2_name, inter.objective_name)
        charts["interactions"] = inter_imgs

        charts["summary"] = create_sensitivity_summary_chart(sensitivities)

        # HTML report
        generate_html_report(report, output_path, charts)

        # JSON report
        if args.json:
            generate_json_report(report, json_output_path)

        logger.info("Reports generated: HTML=%s JSON=%s", output_path, json_output_path if args.json else "(skipped)")
        return 0
    except SystemExit as se:
        raise se
    except Exception as exc:
        logger.exception("Error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())


