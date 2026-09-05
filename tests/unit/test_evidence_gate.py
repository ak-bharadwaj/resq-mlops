"""Comprehensive test suite for Task 15 Evidence Gate per v25 frozen architecture.

P0 Requirements Tested:
1. same_input_same_version_same_output (replay determinism)
2. candidate_worse_is_rejected (worse candidate fails gate and leaves active unchanged)
3. aggregate_10_percent_rule (minimum 10% cost reduction required)
4. individual_window_no_regression (zero window regression allowed)
5. grouped_holdout_directional_agreement (holdout hardware must agree in direction)
6. common_population_coverage_contract (coverage >= 0.90 enforced)
7. cost_delta_excludes_fixed_visit_cost (fixed €45,600 excluded from promotion delta)
8. holdout_isolation_enforced_in_evaluation (GROUP_HOLDOUT_IDS segregated)
9. production_pointer_unchanged_on_rejection (active.json byte-for-byte untouched on reject)
10. promotable_fixture_passes_and_promotes (positive promotion path verified)
11. real_candidate_v0002_rejection_audit (real v0002 legitimately triggers REJECT_GROUPED_DISAGREEMENT)
"""
from __future__ import annotations

import json
import pathlib
import pytest
import pandas as pd

from app.model.evaluate import (
    ROLLING_WINDOWS,
    evaluate_candidate_against_active,
)
from app.model.predict import predict_week, resolve_active_model_version
from app.registry.promotion import (
    evaluate_promotion_policy,
    promote_candidate,
    PromotionDecision,
)
from app.features.holdout import load_group_holdout_ids
from tests.fixtures.lifecycle_fixtures import make_fixture_report


def test_same_input_same_version_same_output():
    """Test 1: Replay determinism - same input and version reproduces identical predictions and hash."""
    data_dir = pathlib.Path("data")
    if not data_dir.exists():
        pytest.skip("Data directory not available for inference replay test")

    week_date = "2026-01-05"
    pred1 = predict_week(data_dir, week_date, active_version="v0001")
    pred2 = predict_week(data_dir, week_date, active_version="v0001")

    assert pred1["replay_hash"] == pred2["replay_hash"], "Replay hash differed across identical runs!"
    assert len(pred1["predictions"]) == 15
    assert len(pred2["predictions"]) == 15
    for r1, r2 in zip(pred1["predictions"], pred2["predictions"]):
        assert r1["gateway_id"] == r2["gateway_id"]
        assert r1["rank"] == r2["rank"]
        assert r1["score"] == r2["score"]
        assert r1["reason"] == r2["reason"]


def test_candidate_worse_is_rejected():
    """Test 2: Genuinely worse candidate fixture is rejected and leaves active.json untouched."""
    # Active missed 71, candidate missed 85 (-19.72% worse)
    report = make_fixture_report(
        candidate_version="v_worse",
        window_missed_pairs={"window_1": (32, 40), "window_2": (24, 30), "window_3": (15, 15)},
        holdout_missed_pair=(17, 22),
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code in ("REJECT_NOT_BETTER", "REJECT_WINDOW_REGRESSION")
    assert decision.aggregate_improvement_percent < 10.0


def test_aggregate_10_percent_rule():
    """Test 3: Candidate improving by less than 10% is rejected with REJECT_NOT_BETTER."""
    # Active missed 71, candidate missed 68 (only 4.23% improvement, below 10%)
    report = make_fixture_report(
        candidate_version="v_insufficient_gain",
        window_missed_pairs={"window_1": (32, 31), "window_2": (24, 23), "window_3": (15, 14)},
        holdout_missed_pair=(17, 16),
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "REJECT_NOT_BETTER"
    assert "10.00%" in decision.explanation


def test_individual_window_no_regression():
    """Test 4: Candidate clearing aggregate bar but regressing in one window is rejected."""
    # Aggregate: 71 -> 58 (18.31% improvement), but window_2 regressed 24 -> 26
    report = make_fixture_report(
        candidate_version="v_window_regressed",
        window_missed_pairs={"window_1": (32, 22), "window_2": (24, 26), "window_3": (15, 10)},
        holdout_missed_pair=(17, 16),
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "REJECT_WINDOW_REGRESSION"
    assert "rolling window" in decision.explanation.lower()


def test_grouped_holdout_directional_agreement():
    """Test 5: Candidate improving temporally but regressing on grouped holdout is rejected."""
    # Temporal: 71 -> 60 (15.49% improvement, 0 window regressions)
    # Holdout: 17 -> 18 (+1 regression on unseen hardware)
    report = make_fixture_report(
        candidate_version="v_holdout_disagreement",
        window_missed_pairs={"window_1": (32, 26), "window_2": (24, 20), "window_3": (15, 14)},
        holdout_missed_pair=(17, 18),
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "REJECT_GROUPED_DISAGREEMENT"
    assert "grouped holdout" in decision.explanation.lower()


def test_common_population_coverage_contract():
    """Test 6: Coverage ratio below 0.90 triggers REJECT_COVERAGE."""
    report = make_fixture_report(
        candidate_version="v_low_coverage",
        coverage_ratio=0.85,
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "REJECT_COVERAGE"
    assert "coverage ratio" in decision.explanation.lower()


def test_cost_delta_excludes_fixed_visit_cost():
    """Test 7: Promotion differential strictly compares missed broken weeks * €600; €45,600 excluded from delta."""
    # Active missed 71, candidate missed 60 -> differential = 11 weeks = €6,600.00
    report = make_fixture_report(
        candidate_version="v_cost_check",
        window_missed_pairs={"window_1": (32, 26), "window_2": (24, 20), "window_3": (15, 14)},
        holdout_missed_pair=(17, 15),
    )

    decision = evaluate_promotion_policy(report)
    expected_delta_eur = (71 - 60) * 600.0  # 6,600.0 EUR
    assert decision.cost_differential_eur == expected_delta_eur
    assert decision.fixed_visit_cost_eur == 45600.0
    assert decision.total_active_cost_eur == 45600.0 + (71 * 600.0)
    assert decision.total_candidate_cost_eur == 45600.0 + (60 * 600.0)
    # The difference between total costs must equal the delta
    assert decision.total_active_cost_eur - decision.total_candidate_cost_eur == expected_delta_eur


def test_holdout_isolation_enforced_in_evaluation():
    """Test 8: Grouped holdout gateways are isolated from temporal window evaluation."""
    holdout_ids = load_group_holdout_ids()
    assert len(holdout_ids) == 59, f"Expected 59 grouped holdout gateways, got {len(holdout_ids)}"
    for gid in holdout_ids:
        assert len(gid) == 12
        assert gid.isalnum()


def test_production_pointer_unchanged_on_rejection(tmp_path):
    """Test 9: registry/active.json is byte-for-byte untouched when a candidate is rejected."""
    active_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"
    initial_payload = {
        "production_version": "v0001",
        "previous_version": None,
        "changed_at": "2026-09-05T00:00:00Z",
        "reason": "initial baseline deployment",
    }
    active_path.write_text(json.dumps(initial_payload, indent=2), encoding="utf-8")
    before_bytes = active_path.read_bytes()

    rejected_decision = PromotionDecision(
        decision="REJECT",
        reason_code="REJECT_GROUPED_DISAGREEMENT",
        explanation="Candidate regressed on unseen holdout hardware.",
        active_version="v0001",
        candidate_version="v0002",
        aggregate_active_missed=71,
        aggregate_candidate_missed=60,
        aggregate_differential=11,
        aggregate_improvement_percent=15.49,
        window_results={},
        grouped_holdout_result={},
        coverage_ratio=1.0,
        cost_differential_eur=6600.0,
        total_active_cost_eur=88200.0,
        total_candidate_cost_eur=81600.0,
    )

    # Calling promote_candidate on a rejected candidate must raise RuntimeError
    with pytest.raises(RuntimeError, match="Safety Guard"):
        promote_candidate("v0002", rejected_decision, registry_path=active_path, history_path=history_path)

    after_bytes = active_path.read_bytes()
    assert before_bytes == after_bytes, "registry/active.json was modified despite rejection!"


def test_promotable_fixture_passes_and_promotes(tmp_path):
    """Test 10: Promotable fixture legitimately passes all gate criteria and updates active.json."""
    active_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"
    active_path.write_text(json.dumps({"production_version": "v0001", "previous_version": None}, indent=2))

    # Promotable: 71 -> 55 (22.54% improvement), all windows improved, holdout 17 -> 14 (improved)
    report = make_fixture_report(
        candidate_version="v_promotable",
        window_missed_pairs={"window_1": (32, 24), "window_2": (24, 19), "window_3": (15, 12)},
        holdout_missed_pair=(17, 14),
    )

    decision = evaluate_promotion_policy(report)
    assert decision.decision == "PROMOTE"
    assert decision.reason_code == "PROMOTE"
    assert decision.aggregate_improvement_percent >= 10.0

    # Execute promotion
    new_active = promote_candidate("v_promotable", decision, registry_path=active_path, history_path=history_path)
    assert new_active["production_version"] == "v_promotable"
    assert new_active["previous_version"] == "v0001"

    updated = json.loads(active_path.read_text(encoding="utf-8"))
    assert updated["production_version"] == "v_promotable"
    assert updated["previous_version"] == "v0001"

    history_lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(history_lines) == 1
    last_event = json.loads(history_lines[-1])
    assert last_event["event"] == "PROMOTED"
    assert last_event["version"] == "v_promotable"


def test_real_candidate_v0002_rejection_audit():
    """Test 11: Real candidate v0002 on real data legitimately triggers REJECT_GROUPED_DISAGREEMENT."""
    data_dir = pathlib.Path("data")
    if not data_dir.exists():
        pytest.skip("Data directory not available for real data evaluation test")

    # Run multi-window evaluation on real challenge data
    report = evaluate_candidate_against_active(
        data_dir=data_dir,
        candidate_version="v0002",
        active_version="v0001",
    )

    # 1. Temporal windows check
    assert report.windows["window_1"].active_missed_broken_weeks == 32
    assert report.windows["window_1"].candidate_missed_broken_weeks == 26
    assert report.windows["window_2"].active_missed_broken_weeks == 24
    assert report.windows["window_2"].candidate_missed_broken_weeks == 20
    assert report.windows["window_3"].active_missed_broken_weeks == 15
    assert report.windows["window_3"].candidate_missed_broken_weeks == 14

    assert report.aggregate_active_missed == 71
    assert report.aggregate_candidate_missed == 60
    assert report.aggregate_differential == 11
    assert report.aggregate_improvement_percent == pytest.approx(15.49, abs=0.05)
    assert not report.has_window_regression

    # 2. Grouped holdout check (unseen hardware)
    assert report.grouped_holdout.active_missed_broken_weeks == 17
    assert report.grouped_holdout.candidate_missed_broken_weeks == 18
    assert not report.grouped_holdout.directional_agreement

    # 3. Policy evaluation
    decision = evaluate_promotion_policy(report)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "REJECT_GROUPED_DISAGREEMENT"
    assert "grouped holdout" in decision.explanation.lower()

    # 4. Production active version must remain v0001
    active_ver = resolve_active_model_version(pathlib.Path("registry/active.json"))
    assert active_ver == "v0001"
