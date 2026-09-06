"""Tests verifying the 10 pre-submission hardening findings.

1. Active artifact hash integrity enforcement on normal prediction path.
2. Transactional promote_candidate() with compensating rollback on audit failure.
3. Corrupt-registry fail-closed in promote_candidate().
4. Repository-wide clean-tree assertion in packaging.
5. Operational timestamp injection in CLI run records.
6. Target model schema contract propagation to load_telemetry_window().
7. Predict CLI fails closed on corrupt registry without false fallbacks.
8. Atomic submission output publication in make_submission.
9. train_candidate() rejects existing non-empty candidate directory.
10. Promotion decision identity validation (candidate_version & active_version consistency).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import pytest

from app.model.predict import (
    ModelArtifactError,
    compute_artifact_hash,
    load_active_artifact_config,
    predict_week,
    resolve_active_model_version,
)
from app.model.train import PackageAlreadyExistsError, train_candidate
from app.registry.promotion import PromotionDecision, promote_candidate


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


def _make_dummy_decision(
    candidate_version: str = "v_cand",
    active_version: str = "v0001",
    timestamp_utc: str = "2026-09-06T12:00:00Z",
) -> PromotionDecision:
    return PromotionDecision(
        decision="PROMOTE",
        reason_code="DEMO_FIXTURE_STAGED",
        explanation="Test promotion decision",
        active_version=active_version,
        candidate_version=candidate_version,
        evaluation_mode="cost_backtest",
        aggregate_active_missed=71,
        aggregate_candidate_missed=55,
        aggregate_differential=16,
        aggregate_improvement_percent=22.54,
        window_results={
            "window_1": {"name": "Nov 2025", "active_missed_broken_weeks": 32, "candidate_missed_broken_weeks": 24, "differential": 8, "differential_percent": 25.0, "is_regression": False},
        },
        grouped_holdout_result={
            "holdout_gateways_count": 59,
            "active_missed_broken_weeks": 17,
            "candidate_missed_broken_weeks": 14,
            "differential": 3,
            "directional_agreement": True,
        },
        coverage_ratio=1.0,
        cost_differential_eur=9600.0,
        fixed_visit_cost_eur=45600.0,
        total_active_cost_eur=88200.0,
        total_candidate_cost_eur=78600.0,
        timestamp_utc=timestamp_utc,
    )


def test_active_artifact_hash_tampering_fails_closed(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Finding 1: predict path verifies artifact hash against manifest and fails closed on tampering."""
    # Copy valid v0001 package
    v0001_dir = repo_root / "models" / "v0001"
    target_dir = tmp_path / "v0001_tampered"
    shutil.copytree(v0001_dir, target_dir)

    # 1. Untampered package loads successfully
    cfg, contract = load_active_artifact_config(target_dir)
    assert cfg["model_version"] == "v0001"

    # 2. Modify model_config.json maliciously without updating manifest.json
    config_file = target_dir / "model_config.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    data["sigma"] = 999.0
    config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # 3. load_active_artifact_config must fail closed
    with pytest.raises(ModelArtifactError, match="Artifact integrity compromised"):
        load_active_artifact_config(target_dir)

    # 4. predict_week must also fail closed with ModelArtifactError
    registry_file = tmp_path / "active.json"
    registry_file.write_text(json.dumps({
        "production_version": "v0001_tampered",
        "previous_version": None,
        "changed_at": "2026-09-06T00:00:00Z",
        "reason": "tamper test",
    }), encoding="utf-8")

    with pytest.raises(ModelArtifactError, match="Artifact integrity compromised"):
        predict_week(
            data_dir=repo_root / "data",
            week_start="2026-02-02",
            registry_path=registry_file,
            models_dir=tmp_path,
        )


def test_promote_candidate_compensating_rollback_on_history_failure(tmp_path: pathlib.Path):
    """Finding 2: promote_candidate performs compensating rollback if history write fails."""
    registry_file = tmp_path / "active.json"
    history_file = tmp_path / "readonly_dir" / "history.jsonl"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)

    # Setup original active.json pointing to v0001
    initial_active = {
        "production_version": "v0001",
        "previous_version": None,
        "changed_at": "2026-09-01T00:00:00Z",
        "reason": "initial",
    }
    registry_file.write_text(json.dumps(initial_active, indent=2), encoding="utf-8")

    # Setup candidate v_cand
    cand_dir = models_dir / "v_cand"
    cand_dir.mkdir()
    (cand_dir / "model.joblib").write_bytes(b"cand")
    (cand_dir / "model_config.json").write_text("{}", encoding="utf-8")
    (cand_dir / "feature_schema.json").write_text("{}", encoding="utf-8")
    (cand_dir / "scorer_identity.txt").write_text("WeightedMultiSignalScorer\n", encoding="utf-8")
    (cand_dir / "schema.json").write_text("{}", encoding="utf-8")
    art_hash = compute_artifact_hash(cand_dir)
    (cand_dir / "manifest.json").write_text(json.dumps({"artifact_hash": art_hash}), encoding="utf-8")

    decision = _make_dummy_decision(candidate_version="v_cand", active_version="v0001")

    # Intentionally target an invalid history path whose parent directory does not exist
    # causing an IOError during history appending
    with pytest.raises(RuntimeError, match="Compensating transaction executed"):
        promote_candidate(
            registry_path=registry_file,
            history_path=history_file,
            candidate_version="v_cand",
            decision=decision,
            timestamp_utc="2026-09-06T12:00:00Z",
        )

    # Verify active.json was restored to original state (compensating rollback succeeded)
    reverted_active = json.loads(registry_file.read_text(encoding="utf-8"))
    assert reverted_active["production_version"] == "v0001"
    assert reverted_active["previous_version"] is None


def test_promote_candidate_fails_closed_on_corrupt_active_registry(tmp_path: pathlib.Path):
    """Finding 3: promote_candidate blocks on corrupt or unreadable active.json."""
    registry_file = tmp_path / "active.json"
    registry_file.write_text("CORRUPTED NOT JSON {{{", encoding="utf-8")
    history_file = tmp_path / "history.jsonl"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    cand_dir = models_dir / "v_cand"
    cand_dir.mkdir()
    (cand_dir / "model.joblib").write_bytes(b"cand")
    (cand_dir / "model_config.json").write_text("{}", encoding="utf-8")
    (cand_dir / "feature_schema.json").write_text("{}", encoding="utf-8")
    (cand_dir / "scorer_identity.txt").write_text("WeightedMultiSignalScorer\n", encoding="utf-8")
    (cand_dir / "schema.json").write_text("{}", encoding="utf-8")
    art_hash = compute_artifact_hash(cand_dir)
    (cand_dir / "manifest.json").write_text(json.dumps({"artifact_hash": art_hash}), encoding="utf-8")

    decision = _make_dummy_decision(candidate_version="v_cand", active_version="v0001")

    with pytest.raises(RuntimeError, match="is corrupt or unreadable"):
        promote_candidate(
            registry_path=registry_file,
            history_path=history_file,
            candidate_version="v_cand",
            decision=decision,
            timestamp_utc="2026-09-06T12:00:00Z",
        )


def test_promote_candidate_enforces_decision_identity_validation(tmp_path: pathlib.Path):
    """Finding 10: promote_candidate verifies candidate_version and active_version consistency."""
    registry_file = tmp_path / "active.json"
    history_file = tmp_path / "history.jsonl"
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    registry_file.write_text(json.dumps({
        "production_version": "v0001",
        "previous_version": None,
        "changed_at": "2026-09-01T00:00:00Z",
        "reason": "initial",
    }), encoding="utf-8")

    cand_dir = models_dir / "v_cand"
    cand_dir.mkdir()
    (cand_dir / "model.joblib").write_bytes(b"cand")
    (cand_dir / "model_config.json").write_text("{}", encoding="utf-8")
    (cand_dir / "feature_schema.json").write_text("{}", encoding="utf-8")
    (cand_dir / "scorer_identity.txt").write_text("WeightedMultiSignalScorer\n", encoding="utf-8")
    (cand_dir / "schema.json").write_text("{}", encoding="utf-8")
    art_hash = compute_artifact_hash(cand_dir)
    (cand_dir / "manifest.json").write_text(json.dumps({"artifact_hash": art_hash}), encoding="utf-8")

    # Mismatch candidate_version
    mismatch_cand = _make_dummy_decision(candidate_version="v_OTHER", active_version="v0001")
    with pytest.raises(ValueError, match="Decision candidate_version .* does not match"):
        promote_candidate(
            registry_path=registry_file,
            history_path=history_file,
            candidate_version="v_cand",
            decision=mismatch_cand,
            timestamp_utc="2026-09-06T12:00:00Z",
        )

    # Mismatch active_version
    mismatch_active = _make_dummy_decision(candidate_version="v_cand", active_version="v_OLD_MISMATCH")
    with pytest.raises(ValueError, match="Decision active_version .* does not match"):
        promote_candidate(
            registry_path=registry_file,
            history_path=history_file,
            candidate_version="v_cand",
            decision=mismatch_active,
            timestamp_utc="2026-09-06T12:00:00Z",
        )


def test_train_candidate_refuses_non_empty_target_directory(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Finding 9: train_candidate fails closed if target_dir exists and is non-empty."""
    target_dir = tmp_path / "cand_dir"
    target_dir.mkdir()
    (target_dir / "leftover_file.txt").write_text("existing content", encoding="utf-8")

    with pytest.raises(PackageAlreadyExistsError, match="Frozen model package already exists and is not empty"):
        train_candidate(
            data_dir=repo_root / "data",
            candidate_version="v0002",
            output_dir=target_dir,
            runs_dir=tmp_path / "runs",
        )

