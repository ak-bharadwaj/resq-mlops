"""Committed lifecycle fixtures for promotion and rejection demonstrations.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 8, 8A, 8B, 8C, 8D, 10, 10A, 11
- Committed demo fixtures ensuring promotion and rejection mechanics are verified
  deterministically without depending on production data mutations.
"""
from __future__ import annotations

from typing import Any, Dict
from app.model.evaluate import (
    CoverageEvaluationResult,
    GroupedHoldoutEvaluationResult,
    MultiWindowEvaluationReport,
    WindowEvaluationResult,
)


def make_fixture_window_result(
    window_id: str,
    name: str,
    active_missed: int,
    cand_missed: int,
) -> WindowEvaluationResult:
    diff = active_missed - cand_missed
    pct = (diff / active_missed * 100.0) if active_missed > 0 else 0.0
    return WindowEvaluationResult(
        window_id=window_id,
        name=name,
        train_period=("2025-08-01", "2025-10-31"),
        holdout_month="2025-11",
        mondays=["2025-11-03", "2025-11-10"],
        active_missed_broken_weeks=active_missed,
        candidate_missed_broken_weeks=cand_missed,
        differential=diff,
        differential_percent=round(pct, 2),
        is_regression=cand_missed > active_missed,
        cost_differential_eur=diff * 600.0,
    )


def make_fixture_report(
    active_version: str = "v0001",
    candidate_version: str = "v_test",
    window_missed_pairs: Dict[str, tuple[int, int]] = None,
    holdout_missed_pair: tuple[int, int] = (17, 18),
    coverage_ratio: float = 1.0,
) -> MultiWindowEvaluationReport:
    """Construct a deterministic MultiWindowEvaluationReport fixture."""
    if window_missed_pairs is None:
        window_missed_pairs = {
            "window_1": (32, 26),
            "window_2": (24, 20),
            "window_3": (15, 14),
        }

    windows: Dict[str, WindowEvaluationResult] = {}
    for w_id, (act_m, cand_m) in window_missed_pairs.items():
        windows[w_id] = make_fixture_window_result(w_id, f"Window {w_id}", act_m, cand_m)

    act_agg = sum(w.active_missed_broken_weeks for w in windows.values())
    cand_agg = sum(w.candidate_missed_broken_weeks for w in windows.values())
    agg_diff = act_agg - cand_agg
    agg_pct = (agg_diff / act_agg * 100.0) if act_agg > 0 else 0.0
    agg_cost_diff = agg_diff * 600.0
    fixed_cost = 45600.0

    h_act, h_cand = holdout_missed_pair
    h_diff = h_act - h_cand

    grouped = GroupedHoldoutEvaluationResult(
        holdout_gateways_count=59,
        mondays=["2025-11-03", "2025-11-10"],
        active_missed_broken_weeks=h_act,
        candidate_missed_broken_weeks=h_cand,
        differential=h_diff,
        directional_agreement=h_cand <= h_act,
        cost_differential_eur=h_diff * 600.0,
    )

    cov = CoverageEvaluationResult(
        evaluation_population_total=1000,
        active_valid_count=1000,
        candidate_valid_count=1000,
        common_valid_count=int(1000 * coverage_ratio),
        excluded_due_to_model_input=int(1000 * (1 - coverage_ratio)),
        coverage_ratio=coverage_ratio,
        minimum_coverage_ratio=0.90,
        passes_coverage=coverage_ratio >= 0.90,
    )

    return MultiWindowEvaluationReport(
        active_version=active_version,
        candidate_version=candidate_version,
        evaluation_mode="cost_backtest",
        windows=windows,
        aggregate_active_missed=act_agg,
        aggregate_candidate_missed=cand_agg,
        aggregate_differential=agg_diff,
        aggregate_improvement_percent=round(agg_pct, 2),
        aggregate_cost_differential_eur=agg_cost_diff,
        fixed_visit_cost_eur=fixed_cost,
        total_active_cost_eur=fixed_cost + (act_agg * 600.0),
        total_candidate_cost_eur=fixed_cost + (cand_agg * 600.0),
        has_window_regression=any(w.is_regression for w in windows.values()),
        grouped_holdout=grouped,
        coverage=cov,
        created_at_utc="2026-09-05T00:00:00Z",
    )
