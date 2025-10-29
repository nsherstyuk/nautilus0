"""
Typed loader for Phase 6 optimization results.

This module provides dataclasses for Phase 6 parameters and performance metrics,
along with a loader class that reads the JSON results file and exposes convenient
query methods.

Usage examples:

    from config.phase6_config_loader import (
        load_phase6_results,
        get_phase6_best_parameters,
        get_phase6_best_metrics,
    )

    # Create a loader (uses default results path by default)
    loader = load_phase6_results()
    best = loader.get_best()
    print(best.rank, best.run_id)

    # Get best parameters directly
    params = get_phase6_best_parameters()
    print(params.fast_period, params.slow_period)

    # Get best performance metrics directly
    metrics = get_phase6_best_metrics()
    print(metrics.sharpe_ratio, metrics.total_pnl)

The default results file path is resolved relative to the project root:
"optimization/results/phase6_refinement_results_top_10.json".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def _to_int(value: object, *, field_name: str) -> int:
    """Best-effort conversion to int with helpful error messages."""
    try:
        if isinstance(value, bool):  # bool is subclass of int; reject to avoid surprises
            return int(value)
        if isinstance(value, (int,)):
            return int(value)
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            # Support strings like "3" or "3.0"
            if value.strip() == "":
                raise ValueError("empty string")
            return int(float(value))
    except Exception as exc:  # noqa: BLE001 - rewrap with context
        raise ValueError(f"Cannot convert field '{field_name}' value {value!r} to int: {exc}") from exc
    raise ValueError(f"Cannot convert field '{field_name}' value {value!r} to int")


def _to_float(value: object, *, field_name: str) -> float:
    """Best-effort conversion to float with helpful error messages."""
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            if value.strip() == "":
                raise ValueError("empty string")
            return float(value)
    except Exception as exc:  # noqa: BLE001 - rewrap with context
        raise ValueError(f"Cannot convert field '{field_name}' value {value!r} to float: {exc}") from exc
    raise ValueError(f"Cannot convert field '{field_name}' value {value!r} to float")


def _to_bool(value: object, *, field_name: str) -> bool:
    """Best-effort conversion to bool with common string/number forms supported."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
        raise ValueError(f"unrecognized boolean string: {value!r}")
    raise ValueError(f"Cannot convert field '{field_name}' value {value!r} to bool")


@dataclass(frozen=True)
class Phase6Parameters:
    """Strategy parameters for a Phase 6 optimization run.

    Note: The schema includes a run identifier within the parameters.
    """

    run_id: int
    fast_period: int
    slow_period: int
    crossover_threshold_pips: float
    stop_loss_pips: int
    take_profit_pips: int
    trailing_stop_activation_pips: int
    trailing_stop_distance_pips: int
    dmi_enabled: bool
    dmi_period: int
    stoch_enabled: bool
    stoch_period_k: int
    stoch_period_d: int
    stoch_bullish_threshold: int
    stoch_bearish_threshold: int

    @classmethod
    def from_dict(cls, data: dict) -> "Phase6Parameters":
        """Construct from a JSON dictionary.

        Raises KeyError/ValueError when required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected parameters to be a dict, got {type(data).__name__}")

        return cls(
            run_id=_to_int(data.get("run_id"), field_name="run_id"),
            fast_period=_to_int(data.get("fast_period"), field_name="fast_period"),
            slow_period=_to_int(data.get("slow_period"), field_name="slow_period"),
            crossover_threshold_pips=_to_float(
                data.get("crossover_threshold_pips"), field_name="crossover_threshold_pips"
            ),
            stop_loss_pips=_to_int(data.get("stop_loss_pips"), field_name="stop_loss_pips"),
            take_profit_pips=_to_int(data.get("take_profit_pips"), field_name="take_profit_pips"),
            trailing_stop_activation_pips=_to_int(
                data.get("trailing_stop_activation_pips"), field_name="trailing_stop_activation_pips"
            ),
            trailing_stop_distance_pips=_to_int(
                data.get("trailing_stop_distance_pips"), field_name="trailing_stop_distance_pips"
            ),
            dmi_enabled=_to_bool(data.get("dmi_enabled"), field_name="dmi_enabled"),
            dmi_period=_to_int(data.get("dmi_period"), field_name="dmi_period"),
            stoch_enabled=_to_bool(data.get("stoch_enabled"), field_name="stoch_enabled"),
            stoch_period_k=_to_int(data.get("stoch_period_k"), field_name="stoch_period_k"),
            stoch_period_d=_to_int(data.get("stoch_period_d"), field_name="stoch_period_d"),
            stoch_bullish_threshold=_to_int(
                data.get("stoch_bullish_threshold"), field_name="stoch_bullish_threshold"
            ),
            stoch_bearish_threshold=_to_int(
                data.get("stoch_bearish_threshold"), field_name="stoch_bearish_threshold"
            ),
        )


@dataclass(frozen=True)
class Phase6PerformanceMetrics:
    """Performance metrics for a Phase 6 optimization result.

    Required fields: `sharpe_ratio`, `total_pnl`, `win_rate`, `trade_count`.
    Optional fields (may be None if not provided in the results JSON):
    `max_drawdown`, `avg_winner`, `avg_loser`, `profit_factor`, `expectancy`,
    `rejected_signals_count`, and `consecutive_losses`.
    """

    sharpe_ratio: float
    total_pnl: float
    win_rate: float
    trade_count: int
    max_drawdown: Optional[float] = None
    avg_winner: Optional[float] = None
    avg_loser: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    rejected_signals_count: Optional[int] = None
    consecutive_losses: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Phase6PerformanceMetrics":
        """Construct from a JSON dictionary (top-level result fields)."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected metrics to be a dict, got {type(data).__name__}")

        # Optional fields: only convert when present (non-None)
        max_drawdown_raw = data.get("max_drawdown")
        avg_winner_raw = data.get("avg_winner")
        avg_loser_raw = data.get("avg_loser")
        profit_factor_raw = data.get("profit_factor")
        expectancy_raw = data.get("expectancy")
        rejected_signals_count_raw = data.get("rejected_signals_count")
        consecutive_losses_raw = data.get("consecutive_losses")

        return cls(
            sharpe_ratio=_to_float(data.get("sharpe_ratio"), field_name="sharpe_ratio"),
            total_pnl=_to_float(data.get("total_pnl"), field_name="total_pnl"),
            win_rate=_to_float(data.get("win_rate"), field_name="win_rate"),
            trade_count=_to_int(data.get("trade_count"), field_name="trade_count"),
            max_drawdown=(
                None if max_drawdown_raw is None else _to_float(max_drawdown_raw, field_name="max_drawdown")
            ),
            avg_winner=(None if avg_winner_raw is None else _to_float(avg_winner_raw, field_name="avg_winner")),
            avg_loser=(None if avg_loser_raw is None else _to_float(avg_loser_raw, field_name="avg_loser")),
            profit_factor=(
                None if profit_factor_raw is None else _to_float(profit_factor_raw, field_name="profit_factor")
            ),
            expectancy=(None if expectancy_raw is None else _to_float(expectancy_raw, field_name="expectancy")),
            rejected_signals_count=(
                None
                if rejected_signals_count_raw is None
                else _to_int(rejected_signals_count_raw, field_name="rejected_signals_count")
            ),
            consecutive_losses=(
                None if consecutive_losses_raw is None else _to_int(consecutive_losses_raw, field_name="consecutive_losses")
            ),
        )


@dataclass(frozen=True)
class Phase6Result:
    """A single Phase 6 optimization result entry."""

    rank: int
    run_id: int
    parameters: Phase6Parameters
    metrics: Phase6PerformanceMetrics

    @classmethod
    def from_dict(cls, data: dict) -> "Phase6Result":
        """Construct a result from a JSON dictionary.

        Expects a structure with a nested "parameters" object and metrics at the top level.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected result to be a dict, got {type(data).__name__}")

        params_raw = data.get("parameters")
        if params_raw is None:
            raise KeyError("Missing required 'parameters' key in result entry")
        parameters = Phase6Parameters.from_dict(params_raw)

        rank = _to_int(data.get("rank"), field_name="rank")
        # Some schemas include run_id at top-level; if absent, fall back to parameters.run_id
        run_id_value = data.get("run_id", parameters.run_id)
        run_id = _to_int(run_id_value, field_name="run_id")

        metrics = Phase6PerformanceMetrics.from_dict(data)
        return cls(rank=rank, run_id=run_id, parameters=parameters, metrics=metrics)


class Phase6ConfigLoader:
    """Loader and accessor for Phase 6 optimization results.

    Parameters
    ----------
    results_path : Optional[pathlib.Path]
        Path to the Phase 6 results JSON file. If omitted, defaults to
        project_root/optimization/results/phase6_refinement_results_top_10.json

    Examples
    --------
    >>> loader = Phase6ConfigLoader()
    >>> best = loader.get_best()
    >>> best.rank
    1
    """

    def __init__(self, results_path: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_results = project_root / "optimization" / "results" / "phase6_refinement_results_top_10.json"
        self._results_path: Path = Path(results_path) if results_path is not None else default_results
        self._results: Optional[List[Phase6Result]] = None

    def _load_results(self) -> List[Phase6Result]:
        """Load and parse results from disk.

        Returns
        -------
        List[Phase6Result]

        Raises
        ------
        FileNotFoundError
            If the results file does not exist.
        ValueError
            If the file cannot be parsed or contains invalid entries.
        """
        if not self._results_path.exists():
            raise FileNotFoundError(
                f"Phase 6 results file not found at '{self._results_path}'. "
                "Expected file: optimization/results/phase6_refinement_results_top_10.json"
            )

        try:
            with self._results_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Failed to parse JSON from '{self._results_path}': {exc.msg} (pos {exc.pos})"
            ) from exc

        if not isinstance(raw, list):
            raise ValueError(
                f"Expected results file to contain a JSON array, got {type(raw).__name__}"
            )

        results: List[Phase6Result] = []
        for idx, entry in enumerate(raw):
            try:
                results.append(Phase6Result.from_dict(entry))
            except Exception as exc:  # noqa: BLE001 - attach index context
                raise ValueError(f"Invalid result entry at index {idx}: {exc}") from exc

        # Deterministic ordering by rank regardless of source ordering
        results.sort(key=lambda r: r.rank)

        if not results:
            raise ValueError(
                f"No Phase 6 results found in '{self._results_path}'. The JSON array is empty."
            )

        return results

    @property
    def results(self) -> List[Phase6Result]:
        """All loaded results (lazy-loaded and cached)."""
        if self._results is None:
            self._results = self._load_results()
        return self._results

    def get_top_n(self, n: int = 10) -> List[Phase6Result]:
        """Return the top n results.

        Parameters
        ----------
        n : int, default 10
            Number of top entries to return. Must be positive.

        Returns
        -------
        List[Phase6Result]
            First n results (sorted by rank at load time). May return fewer than n
            if the results file contains fewer entries.

        Raises
        ------
        ValueError
            If n is not positive.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        return self.results[:n]

    def get_by_rank(self, rank: int) -> Optional[Phase6Result]:
        """Return the result entry with the given rank, if present.

        Parameters
        ----------
        rank : int
            Desired rank (1-based). Must be positive.

        Returns
        -------
        Optional[Phase6Result]
            Matching entry or None if not found.

        Raises
        ------
        ValueError
            If rank is not positive.
        """
        if rank <= 0:
            raise ValueError("rank must be positive")
        for result in self.results:
            if result.rank == rank:
                return result
        return None

    def get_by_run_id(self, run_id: int) -> Optional[Phase6Result]:
        """Return the result entry with the given run_id, if present."""
        for result in self.results:
            if result.run_id == run_id:
                return result
        return None

    def get_best(self) -> Phase6Result:
        """Return the best-performing configuration (rank 1).

        Raises
        ------
        ValueError
            If the results list is empty.
        """
        if not self.results:
            raise ValueError("No Phase 6 results available")
        return self.results[0]


def load_phase6_results(results_path: Optional[Path] = None) -> Phase6ConfigLoader:
    """Create a Phase6ConfigLoader for the given results path (or default)."""
    return Phase6ConfigLoader(results_path=results_path)


def get_phase6_best_parameters(results_path: Optional[Path] = None) -> Phase6Parameters:
    """Return parameters for the best (rank 1) configuration.

    Parameters
    ----------
    results_path : Optional[pathlib.Path]
        Optional override path to the results file.
    """
    loader = load_phase6_results(results_path=results_path)
    return loader.get_best().parameters


def get_phase6_best_metrics(results_path: Optional[Path] = None) -> Phase6PerformanceMetrics:
    """Return performance metrics for the best (rank 1) configuration.

    Parameters
    ----------
    results_path : Optional[pathlib.Path]
        Optional override path to the results file.
    """
    loader = load_phase6_results(results_path=results_path)
    return loader.get_best().metrics


