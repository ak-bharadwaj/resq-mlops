"""Tests for model rollback mechanism and deterministic replay equality.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 10, 10A, 11
- Mandatory P0 Tests:
  - rollback_restores_previous_prediction
  - invalid_rollback_target_leaves_active_unchanged
- P1 Tests:
  - rollback_validation_failure_preserves_active
  - rollback_retains_candidate
  - rollback_idempotency / same-version rejection
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import pytest

from app.model.predict import predict_week, resolve_active_model_version
from app.registry.promotion import evaluate_promotion_policy, promote_candidate
from app.registry.rollback import (
    RollbackError,
    RollbackReplayMismatchError,
    RollbackResult,
    RollbackTargetValidationError,
    execute_rollback,
    validate_rollback_target,
)
from tests.fixtures.lifecycle_fixtures import make_fixture_report


def test_rollback_restores_previous_prediction(tmp_path):
    """P0 Contract: Validated rollback target becomes active and reproduces exact prior prediction."""
    data_dir = pathlib.Path("data")
    if not data_dir.exists():
        pytest.skip("Data directory not available for rollback test")

    registry_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"

    # 1. Initial State: active = v0001
    registry_path.write_text(
        json.dumps({"production_version": "v0001", "previous_version": None, "changed_at": "2026-09-05T00:00:00Z"}, indent=2),
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps({"event": "INITIALIZED", "version": "v0001", "timestamp": "2026-09-05T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    # 2. Record pre-promotion baseline prediction and replay hash for v0001
    v1_pred_before = predict_week(data_dir=data_dir, week_start="2026-02-02", registry_path=registry_path)
    v1_hash_before = v1_pred_before["replay_hash"]
    v1_rows_before = v1_pred_before["predictions"]
    assert len(v1_rows_before) == 15
    assert v1_hash_before.startswith("sha256:")

    # 3. Promote v_promotable candidate using committed lifecycle fixture
    report = make_fixture_report(
        candidate_version="v_promotable",
        window_missed_pairs={"window_1": (32, 24), "window_2": (24, 19), "window_3": (15, 12)},
        holdout_missed_pair=(17, 14),
    )
    decision = evaluate_promotion_policy(report)
    assert decision.decision == "PROMOTE"

    promote_candidate("v_promotable", decision, registry_path=registry_path, history_path=history_path)
    assert resolve_active_model_version(registry_path) == "v_promotable"

    # 4. Predict with active v_promotable
    v_prom_pred = predict_week(data_dir=data_dir, week_start="2026-02-02", registry_path=registry_path)
    v_prom_hash = v_prom_pred["replay_hash"]
    assert v_prom_hash != v1_hash_before, "Candidate model must produce distinct replay hash from baseline"

    # 5. Execute rollback to v0001 with expected replay hash check
    res = execute_rollback(
        target_version="v0001",
        registry_path=registry_path,
        history_path=history_path,
        data_dir=data_dir,
        replay_week="2026-02-02",
        expected_replay_hash=v1_hash_before,
    )

    # 6. Assert RollbackResult contract
    assert isinstance(res, RollbackResult)
    assert res.current_active_before == "v_promotable"
    assert res.rollback_target == "v0001"
    assert res.pre_rollback_replay_hash == v_prom_hash
    assert res.post_rollback_replay_hash == v1_hash_before
    assert res.replay_equality is True
    assert res.target_validation_passed is True
    assert res.active_restored == "v0001"

    # 7. Assert registry state
    assert resolve_active_model_version(registry_path) == "v0001"
    active_record = json.loads(registry_path.read_text(encoding="utf-8"))
    assert active_record["production_version"] == "v0001"
    assert active_record["previous_version"] == "v_promotable"

    # 8. Run fresh post-rollback prediction and assert exact content equality
    v1_pred_after = predict_week(data_dir=data_dir, week_start="2026-02-02", registry_path=registry_path)
    assert v1_pred_after["replay_hash"] == v1_hash_before
    assert v1_pred_after["active_version"] == "v0001"
    assert len(v1_pred_after["predictions"]) == 15
    for row_before, row_after in zip(v1_rows_before, v1_pred_after["predictions"]):
        assert row_before["gateway_id"] == row_after["gateway_id"]
        assert row_before["score"] == pytest.approx(row_after["score"], abs=1e-6)
        assert row_before["reason"] == row_after["reason"]

    # 9. Assert history audit trail
    history_lines = [json.loads(line) for line in history_path.read_text(encoding="utf-8").strip().splitlines()]
    last_event = history_lines[-1]
    assert last_event["event"] == "ROLLED_BACK"
    assert last_event["version"] == "v0001"
    assert last_event["previous_version"] == "v_promotable"


def test_invalid_rollback_target_leaves_active_unchanged(tmp_path):
    """P0 Contract: Failure during target validation must leave active.json byte-for-byte untouched."""
    registry_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"

    initial_payload = {
        "production_version": "v_promotable",
        "previous_version": "v0001",
        "changed_at": "2026-09-05T00:00:00Z",
        "reason": "promoted",
    }
    registry_path.write_text(json.dumps(initial_payload, indent=2), encoding="utf-8")
    before_bytes = registry_path.read_bytes()

    history_initial = json.dumps({"event": "PROMOTED", "version": "v_promotable"}) + "\n"
    history_path.write_text(history_initial, encoding="utf-8")

    # Attempt rollback to non-existent target package
    with pytest.raises(RollbackTargetValidationError, match="does not exist"):
        execute_rollback(
            target_version="v_nonexistent_9999",
            registry_path=registry_path,
            history_path=history_path,
        )

    # Invariant: registry/active.json was not mutated
    after_bytes = registry_path.read_bytes()
    assert before_bytes == after_bytes, "registry/active.json was modified despite target validation failure!"

    # Invariant: no ROLLED_BACK event in history
    assert history_path.read_text(encoding="utf-8") == history_initial


def test_rollback_corrupted_target_rejected(tmp_path):
    """P1 Contract: Target with corrupt manifest or missing schema fails validation and blocks rollback."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    corrupt_dir = models_dir / "v_corrupt"
    corrupt_dir.mkdir()

    # Missing manifest.json
    with pytest.raises(RollbackTargetValidationError, match="Missing manifest.json"):
        validate_rollback_target("v_corrupt", models_dir=models_dir)

    # Corrupt manifest.json (invalid JSON)
    (corrupt_dir / "manifest.json").write_text("{invalid_json", encoding="utf-8")
    with pytest.raises(RollbackTargetValidationError, match="Corrupt manifest.json"):
        validate_rollback_target("v_corrupt", models_dir=models_dir)

    # Manifest with mismatched model_version
    (corrupt_dir / "manifest.json").write_text(
        json.dumps({"model_version": "v_other", "artifact_hash": "sha256:123", "schema_version": "v1"}),
        encoding="utf-8",
    )
    with pytest.raises(RollbackTargetValidationError, match="mismatch"):
        validate_rollback_target("v_corrupt", models_dir=models_dir)


def test_rollback_same_version_rejected(tmp_path):
    """P1 Contract: Attempting rollback to already active model raises RollbackError without mutation."""
    registry_path = tmp_path / "active.json"
    registry_path.write_text(
        json.dumps({"production_version": "v0001", "previous_version": None}),
        encoding="utf-8",
    )
    before_bytes = registry_path.read_bytes()

    with pytest.raises(RollbackError, match="already the active"):
        execute_rollback(target_version="v0001", registry_path=registry_path)

    assert registry_path.read_bytes() == before_bytes


def test_rollback_retains_candidate(tmp_path):
    """P1 Contract: Rolling back active pointer does not delete or mutate candidate artifacts."""
    data_dir = pathlib.Path("data")
    if not data_dir.exists():
        pytest.skip("Data directory not available")

    registry_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"
    registry_path.write_text(
        json.dumps({"production_version": "v_promotable", "previous_version": "v0001"}),
        encoding="utf-8",
    )

    promotable_dir = pathlib.Path("models/v_promotable")
    assert promotable_dir.exists()
    manifest_before = (promotable_dir / "manifest.json").read_bytes()

    execute_rollback(
        target_version="v0001",
        registry_path=registry_path,
        history_path=history_path,
        data_dir=data_dir,
    )

    # Candidate directory remains intact and untouched
    assert promotable_dir.exists()
    assert (promotable_dir / "manifest.json").read_bytes() == manifest_before


def test_rollback_cli_execution(tmp_path):
    """Operational Contract: scripts/rollback.py CLI executes cleanly and emits expected output."""
    data_dir = pathlib.Path("data")
    if not data_dir.exists():
        pytest.skip("Data directory not available")

    # 1. Failure path CLI test
    res_fail = subprocess.run(
        [sys.executable, "scripts/rollback.py", "--to", "v_nonexistent_model"],
        capture_output=True,
        text=True,
    )
    assert res_fail.returncode == 1
    assert "Target validation: FAIL" in res_fail.stdout or "Target validation: FAIL" in res_fail.stderr

    # 2. Success path CLI test using tmp registry fixture
    registry_path = tmp_path / "active.json"
    history_path = tmp_path / "history.jsonl"
    registry_path.write_text(
        json.dumps({"production_version": "v_promotable", "previous_version": "v0001"}),
        encoding="utf-8",
    )

    res_success = subprocess.run(
        [
            sys.executable,
            "scripts/rollback.py",
            "--registry", str(registry_path),
            "--history", str(history_path),
            "--to", "v0001",
        ],
        capture_output=True,
        text=True,
    )
    assert res_success.returncode == 0
    stdout = res_success.stdout
    assert "Current active: v_promotable" in stdout
    assert "Rollback target: v0001" in stdout
    assert "Target validation: PASS" in stdout
    assert "Pre-rollback replay hash: sha256:" in stdout
    assert "Atomic switch: PASS" in stdout
    assert "Post-rollback replay hash: sha256:" in stdout
    assert "Replay equality: PASS" in stdout
    assert "Active model: v0001" in stdout
