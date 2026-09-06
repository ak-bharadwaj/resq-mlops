"""Production model rollback engine and deterministic replay verification.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 10, 10A, 11
- Registry State: registry/active.json, registry/history.jsonl

Safety Invariants:
1. Target Validation Before Mutation:
   Validates the candidate package (manifest, schema, model_config, scorer identity,
   cryptographic artifact hash verification, and executable smoke prediction) before mutating
   registry/active.json. If validation fails, registry/active.json remains strictly untouched.
2. Mandatory Expected Replay Proof:
   Requires restored model to reproduce the expected target prediction replay hash, obtained
   and verified from pre-switch validation or explicit operational specification.
3. Post-Switch Compensating Transaction:
   If post-switch prediction or replay equality fails, atomic compensating rollback is executed
   immediately, restoring registry/active.json to the pre-switch active model. Production is NEVER
   left in a half-switched state.
4. Audit Log Immutability:
   Appends ROLLED_BACK event to registry/history.jsonl only upon complete, verified success.
5. Monotonic Temporal Authority:
   Zero system clock calls. Deterministic timestamps.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from app.data.schema import TelemetrySchemaContract
from app.model.predict import (
    InsufficientEligibleGatewaysError,
    ModelArtifactError,
    load_active_artifact_config,
    predict_week,
    resolve_active_model_version,
)
from app.model.train import compute_artifact_hash


class RollbackError(Exception):
    """Base exception for rollback lifecycle errors."""


class RollbackTargetValidationError(RollbackError):
    """Raised when target package validation fails prior to mutation."""


class RollbackReplayMismatchError(RollbackError):
    """Raised when restored model output does not match expected replay hash."""


class RollbackResult(BaseModel):
    """Authoritative rollback execution result contract."""
    current_active_before: str = Field(description="Active model version prior to rollback")
    rollback_target: str = Field(description="Target model version restored by rollback")
    pre_rollback_replay_hash: str = Field(description="Deterministic replay hash of active model before rollback")
    post_rollback_replay_hash: str = Field(description="Deterministic replay hash of restored model after rollback")
    expected_target_replay_hash: str = Field(description="Expected target replay hash proven against post-rollback output")
    replay_equality: bool = Field(description="True if post-rollback prediction matches expected deterministic replay")
    target_validation_passed: bool = Field(description="True if target package validation succeeded prior to switch")
    active_restored: str = Field(description="Active model confirmed in registry/active.json")
    timestamp_utc: str = Field(default="2026-09-05T00:00:00Z", description="Deterministic UTC timestamp of rollback")

    model_config = {
        "frozen": True,
    }


def validate_rollback_target(
    target_version: str,
    models_dir: pathlib.Path = pathlib.Path("models"),
    data_dir: pathlib.Path = pathlib.Path("data"),
    test_date: str = "2026-02-02",
) -> Dict[str, Any]:
    """Validate that target model package exists, conforms to schemas, and executes cleanly.

    Safety:
    - This check runs BEFORE any mutation to registry/active.json.
    - If any check fails, raises RollbackTargetValidationError.
    """
    target_dir = models_dir / target_version
    if not target_dir.exists() or not target_dir.is_dir():
        raise RollbackTargetValidationError(
            f"Rollback target package directory does not exist: {target_dir}"
        )

    # 1. Validate manifest.json
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        raise RollbackTargetValidationError(f"Missing manifest.json in {target_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RollbackTargetValidationError(f"Corrupt manifest.json in {target_dir}: {exc}") from exc

    if manifest.get("model_version") != target_version:
        raise RollbackTargetValidationError(
            f"manifest.json model_version mismatch: expected '{target_version}', got '{manifest.get('model_version')}'"
        )
    declared_artifact_hash = manifest.get("artifact_hash")
    if not declared_artifact_hash or not manifest.get("schema_version"):
        raise RollbackTargetValidationError(
            f"manifest.json missing required contract fields in {target_dir}"
        )

    # 2. Validate model_config.json and schema.json
    try:
        config, schema_contract = load_active_artifact_config(target_dir)
    except Exception as exc:
        raise RollbackTargetValidationError(
            f"Target artifact configuration/schema validation failed: {exc}"
        ) from exc

    # 3. Validate scorer_identity.txt
    scorer_path = target_dir / "scorer_identity.txt"
    if not scorer_path.exists():
        raise RollbackTargetValidationError(f"Missing scorer_identity.txt in {target_dir}")

    # 4. Cryptographic Artifact Integrity Verification: compare computed vs declared SHA-256
    computed_art_hash = compute_artifact_hash(target_dir)
    if declared_artifact_hash != computed_art_hash:
        raise RollbackTargetValidationError(
            f"Artifact hash mismatch in {target_dir}: declared '{declared_artifact_hash}', "
            f"computed '{computed_art_hash}'"
        )

    # 5. Smoke Prediction Test: verify executable prediction path and capture pre-switch replay hash
    try:
        smoke_res = predict_week(
            data_dir=data_dir,
            week_start=test_date,
            active_version=target_version,
            models_dir=models_dir,
        )
    except Exception as exc:
        raise RollbackTargetValidationError(
            f"Smoke prediction failed for rollback target '{target_version}': {exc}"
        ) from exc

    preds = smoke_res.get("predictions", [])
    if not preds or len(preds) != 15:
        raise RollbackTargetValidationError(
            f"Smoke prediction produced invalid candidate count: {len(preds)} (expected exactly 15)"
        )
    replay_hash = smoke_res.get("replay_hash")
    if not replay_hash or not replay_hash.startswith("sha256:"):
        raise RollbackTargetValidationError(
            f"Smoke prediction emitted invalid replay_hash: {replay_hash}"
        )

    return {
        "target_version": target_version,
        "artifact_hash": declared_artifact_hash,
        "smoke_replay_hash": replay_hash,
    }


def execute_rollback(
    target_version: Optional[str] = None,
    registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
    history_path: pathlib.Path = pathlib.Path("registry/history.jsonl"),
    models_dir: pathlib.Path = pathlib.Path("models"),
    data_dir: pathlib.Path = pathlib.Path("data"),
    replay_week: str = "2026-02-02",
    expected_replay_hash: Optional[str] = None,
    timestamp_utc: str = "2026-09-05T00:00:00Z",
) -> RollbackResult:
    """Execute the complete 7-step rollback lifecycle with compensating transactional safety.

    Lifecycle Steps (v25 Section 10):
    1. Read current active version from registry/active.json.
    2. Validate rollback target package BEFORE mutation, verifying artifact hash and capturing expected replay hash.
    3. Capture pre-rollback prediction replay hash for active model.
    4. Atomically switch active pointer in registry/active.json.
    5. Run post-rollback prediction with restored active model.
    6. Prove replay equality against expected target prediction.
       [COMPENSATING TRANSACTION]: If post-switch validation fails, registry/active.json is atomically
       restored to the pre-switch active version.
    7. Assert registry state confirms restored model and record in history.jsonl.
    """
    # Step 1: Read current active version
    if not registry_path.exists():
        raise RollbackError(f"Active registry pointer missing: {registry_path}")

    try:
        active_data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RollbackError(f"Corrupt active registry pointer at {registry_path}: {exc}") from exc

    curr_active = active_data.get("production_version")
    if not curr_active:
        raise RollbackError(f"registry/active.json lacks 'production_version': {active_data}")

    prev_version = active_data.get("previous_version")

    resolved_target = target_version or prev_version
    if not resolved_target:
        raise RollbackError(
            "No target version specified and no 'previous_version' found in registry/active.json to rollback to."
        )

    if resolved_target == curr_active:
        raise RollbackError(
            f"Rollback target '{resolved_target}' is already the active production model."
        )

    # Save original state for compensating transaction
    original_active_bytes = registry_path.read_bytes()
    original_history_bytes = history_path.read_bytes() if history_path.exists() else None

    # Step 2: Validate rollback target BEFORE mutation (Fail-Closed)
    val_info = validate_rollback_target(
        target_version=resolved_target,
        models_dir=models_dir,
        data_dir=data_dir,
        test_date=replay_week,
    )

    # Resolve authoritative expected replay hash for target
    target_expected_hash = expected_replay_hash or val_info["smoke_replay_hash"]
    if expected_replay_hash is not None and expected_replay_hash != val_info["smoke_replay_hash"]:
        raise RollbackTargetValidationError(
            f"Target model smoke replay hash '{val_info['smoke_replay_hash']}' does not match "
            f"specified expected hash '{expected_replay_hash}'"
        )

    # Step 3: Capture pre-rollback prediction for current active model
    pre_pred = predict_week(
        data_dir=data_dir,
        week_start=replay_week,
        active_version=curr_active,
        models_dir=models_dir,
        registry_path=registry_path,
    )
    pre_replay_hash = pre_pred["replay_hash"]

    # Step 4: Atomically switch registry/active.json
    new_active_payload = {
        "production_version": resolved_target,
        "previous_version": curr_active,
        "changed_at": timestamp_utc,
        "reason": f"rollback to {resolved_target}",
    }

    if not registry_path.parent.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = registry_path.parent / f"{registry_path.name}.tmp"
    tmp_path.write_text(json.dumps(new_active_payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, registry_path)

    # Post-switch verification protected by compensating rollback transaction
    try:
        # Step 5: Run post-rollback prediction through restored model
        post_pred_1 = predict_week(
            data_dir=data_dir,
            week_start=replay_week,
            models_dir=models_dir,
            registry_path=registry_path,
        )
        post_replay_hash = post_pred_1["replay_hash"]

        # Step 6: Prove equality against expected previous prediction
        if post_replay_hash != target_expected_hash:
            raise RollbackReplayMismatchError(
                f"Restored model replay hash '{post_replay_hash}' does not match "
                f"expected previous prediction hash '{target_expected_hash}'"
            )

        # 6b. Consecutive run determinism
        post_pred_2 = predict_week(
            data_dir=data_dir,
            week_start=replay_week,
            models_dir=models_dir,
            registry_path=registry_path,
        )
        if post_pred_1["replay_hash"] != post_pred_2["replay_hash"]:
            raise RollbackReplayMismatchError(
                f"Restored model is non-deterministic: first replay hash {post_pred_1['replay_hash']} "
                f"differs from second replay hash {post_pred_2['replay_hash']}"
            )

        # 6c. Verify active_version in prediction matches resolved target
        if post_pred_1["active_version"] != resolved_target:
            raise RollbackReplayMismatchError(
                f"Prediction output active_version '{post_pred_1['active_version']}' differs from target '{resolved_target}'"
            )

        # Step 7: Assert registry state confirms restored model
        confirmed_active = resolve_active_model_version(registry_path)
        if confirmed_active != resolved_target:
            raise RollbackError(
                f"Registry verification failed: active.json reports '{confirmed_active}', expected '{resolved_target}'"
            )

        # Append to history.jsonl only after post-switch verification completely succeeds
        history_entry = {
            "event": "ROLLED_BACK",
            "version": resolved_target,
            "to": resolved_target,
            "previous_version": curr_active,
            "from": curr_active,
            "timestamp": timestamp_utc,
            "reason": f"rollback to {resolved_target}",
            "reason_code": "ROLLBACK_SUCCESS",
        }
        if not history_path.parent.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_entry) + "\n")

    except Exception as exc:
        # COMPENSATING TRANSACTION: Atomically restore registry/active.json to original active state
        comp_tmp = registry_path.parent / f"{registry_path.name}.tmp"
        comp_tmp.write_bytes(original_active_bytes)
        os.replace(comp_tmp, registry_path)

        if original_history_bytes is not None:
            history_path.write_bytes(original_history_bytes)

        if isinstance(exc, RollbackError):
            raise RollbackReplayMismatchError(
                f"Post-switch replay verification failed: {exc}. "
                f"Compensating transaction executed: registry/active.json safely restored to '{curr_active}'."
            ) from exc
        else:
            raise RollbackError(
                f"Unexpected post-switch error: {exc}. "
                f"Compensating transaction executed: registry/active.json safely restored to '{curr_active}'."
            ) from exc

    return RollbackResult(
        current_active_before=curr_active,
        rollback_target=resolved_target,
        pre_rollback_replay_hash=pre_replay_hash,
        post_rollback_replay_hash=post_replay_hash,
        expected_target_replay_hash=target_expected_hash,
        replay_equality=True,
        target_validation_passed=True,
        active_restored=confirmed_active,
        timestamp_utc=timestamp_utc,
    )
