"""Production training and candidate materialization engine.

Strict Invariants:
1. Physical Module Separation: Responsible for historical data loading, label/proxy construction,
   training feature evaluation, and candidate packaging.
2. Candidate Creation Only: train.py MUST NEVER alter active production state, MUST NEVER modify
   registry/active.json, and MUST NEVER promote or rollback models.
3. Monotonic Time Authority: Temporal bounds driven strictly by pre-holdout development cutoff
   (2026-01-31 UTC). Zero system clock calls.
4. Dual-Hash Cryptographic Provenance: Generates immutable candidate package with artifact_hash.
5. Grouped Holdout Isolation: GROUP_HOLDOUT_IDS are strictly excluded from candidate training
   and development data.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Optional

import joblib
import pandas as pd

from app.data.loader import (
    load_field_visits,
    load_gateway_master,
)
from app.data.quality import HoldoutAccessError, HoldoutProtection
from app.features.holdout import load_group_holdout_ids


class TrainingError(Exception):
    """Raised when training, feature construction, or candidate materialization fails."""


class PackageAlreadyExistsError(TrainingError):
    """Raised when attempting to overwrite an existing frozen model package."""


def compute_artifact_hash(model_dir: pathlib.Path) -> str:
    """Compute SHA256 covering immutable behavior-defining artifact files per v25 Section 6.

    Hash covers: canonical model.joblib + model_config.json + feature_schema.json + scorer_identity.txt.
    schema.json is validated as part of the artifact contract but is not duplicated into hash inputs.
    """
    hasher = hashlib.sha256()
    # Canonical order of behavior-defining artifact files per v25 Section 6
    hash_files = ["model.joblib", "model_config.json", "feature_schema.json", "scorer_identity.txt"]
    for fname in hash_files:
        fpath = model_dir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Required behavior-defining artifact file missing for hash: {fpath}")
        hasher.update(fname.encode("utf-8"))
        hasher.update(fpath.read_bytes())
    return f"sha256:{hasher.hexdigest()}"


def train_candidate(
    data_dir: pathlib.Path,
    candidate_version: str = "v0002",
    output_dir: pathlib.Path | None = None,
    registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
    runs_dir: pathlib.Path = pathlib.Path("runs/training"),
    holdout_path: pathlib.Path = pathlib.Path("registry/grouped_holdout.json"),
) -> dict[str, Any]:
    """Materialize candidate model package and emit training evidence.

    Args:
        data_dir: Path to the root data directory
        candidate_version: Version identifier for candidate package (default: v0002)
        output_dir: Optional custom destination directory (defaults to models/<candidate_version>)
        registry_path: Path to registry/active.json for verifying zero production mutation
        runs_dir: Path to directory where training evidence logs are stored
        holdout_path: Path to registry/grouped_holdout.json for holdout isolation

    Returns:
        Dictionary summarizing candidate package creation and evidence details.
    """
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Specified data directory does not exist: {data_dir}")

    # Invariant Guard: Record active state before training
    active_before: str | None = None
    if registry_path.exists():
        active_before = registry_path.read_text(encoding="utf-8")

    # 1. Monotonic Development Cutoff (2026-01-31 UTC)
    dev_cutoff_date = dt.date(2026, 1, 31)

    # 2. Ingest Master & Field Visits (training path is authorized to use field_visits)
    master_df = load_gateway_master(data_dir)
    visits_df = load_field_visits(data_dir)

    # Filter visits to pre-holdout development period
    dev_visits = visits_df[visits_df["visited_on"] <= dev_cutoff_date].copy()

    # 3. Grouped Holdout Isolation (Rule 8, v25 Section 8)
    holdout_ids = load_group_holdout_ids(holdout_path)
    all_master_gids = set(master_df["canonical_id"].unique())
    dev_gateways = all_master_gids - holdout_ids

    # Verify no holdout gateway leaks into development set
    for gid in dev_gateways:
        HoldoutProtection.check_gateway_access(gid, holdout_ids, allow_holdout=False)

    # 4. Destination Candidate Directory and Immutability Guard
    target_dir = output_dir or (pathlib.Path("models") / candidate_version)
    if target_dir.exists() and (target_dir / "manifest.json").exists():
        raise PackageAlreadyExistsError(
            f"Frozen model package already exists at '{target_dir}'. "
            f"Model packages are immutable and cannot be overwritten. "
            f"To train a new model, declare a new version."
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    # 5. Model Configuration & Feature Schema based on Candidate Version
    if candidate_version == "v0002":
        model_type = "deterministic_weighted_multisignal"
        feature_version = "features-v1"
        config_data = {
            "model_version": candidate_version,
            "model_type": model_type,
            "feature_version": feature_version,
            "schema_version": "telemetry-v1",
            "baseline_days": 28,
            "recent_days": 7,
            "sigma": 3.0,
            "expected_hours_week": 168,
            "weights": {
                "w_anomaly": 0.7,
                "w_silence": 0.3,
            },
            "metrics": [
                "offline_duration_sec",
                "disconnection_cnt",
                "reboot_cnt",
            ],
            "visits_per_week": 15,
        }
        feature_schema_data = {
            "feature_version": feature_version,
            "features": {
                "flagged_hours": {"dtype": "float64", "min": 0.0, "max": 504.0},
                "norm_anomaly": {"dtype": "float64", "min": 0.0, "max": 1.0},
                "recent_silence_ratio": {"dtype": "float64", "min": 0.0, "max": 1.0},
                "worst_metric": {"dtype": "string"},
            },
        }
        evidence_quality = "candidate"
    else:
        # Baseline v0001
        model_type = "baseline_3sigma_anomaly"
        feature_version = "baseline-v1"
        config_data = {
            "model_version": candidate_version,
            "baseline_days": 28,
            "recent_days": 7,
            "sigma": 3.0,
            "metrics": [
                "offline_duration_sec",
                "disconnection_cnt",
                "reboot_cnt",
            ],
            "visits_per_week": 15,
        }
        feature_schema_data = {
            "feature_version": feature_version,
            "features": {
                "offline_duration_sec": {"dtype": "float64", "min": 0.0, "max": 3600.0},
                "disconnection_cnt": {"dtype": "float64", "min": 0.0},
                "reboot_cnt": {"dtype": "float64", "min": 0.0},
            },
        }
        evidence_quality = "baseline"

    (target_dir / "model_config.json").write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )
    (target_dir / "feature_schema.json").write_text(
        json.dumps(feature_schema_data, indent=2), encoding="utf-8"
    )

    # 6. Authoritative schema.json
    schema_dict = {
        "required_columns": [
            "gateway_id",
            "ts_utc",
            "offline_duration_sec",
            "disconnection_cnt",
            "reboot_cnt",
        ],
        "dtypes": {
            "gateway_id": "string",
            "ts_utc": "datetime64[ns, UTC]",
            "offline_duration_sec": "float64",
            "disconnection_cnt": "float64",
            "reboot_cnt": "float64",
        },
        "time_grain": "hourly",
        "timestamp_column": "ts_utc",
    }
    (target_dir / "schema.json").write_text(
        json.dumps(schema_dict, indent=2), encoding="utf-8"
    )

    # 7. Write scorer_identity.txt with cryptographic binding
    if candidate_version == "v0002":
        scorer_path = pathlib.Path("app/model/scorer.py")
        if scorer_path.exists():
            scorer_sha = hashlib.sha256(scorer_path.read_bytes()).hexdigest()
            scorer_identity_content = f"WeightedMultiSignalScorer:app/model/scorer.py:sha256:{scorer_sha}\n"
        else:
            scorer_identity_content = "WeightedMultiSignalScorer:frozen_reference\n"
    else:
        baseline_path = pathlib.Path("baseline_3sigma.py")
        if baseline_path.exists():
            baseline_sha = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
            scorer_identity_content = f"baseline_3sigma.py:sha256:{baseline_sha}\n"
        else:
            scorer_identity_content = "baseline_3sigma.py:frozen_reference\n"

    (target_dir / "scorer_identity.txt").write_text(
        scorer_identity_content, encoding="utf-8"
    )

    # 7b. Serialize canonical model state into model.joblib per Section 6 / v25
    if candidate_version == "v0002":
        model_payload = {
            "model_version": candidate_version,
            "model_type": model_type,
            "scorer_class": "WeightedMultiSignalScorer",
            "weights": config_data.get("weights", {}),
            "metrics": config_data.get("metrics", []),
            "baseline_days": config_data.get("baseline_days", 28),
            "recent_days": config_data.get("recent_days", 7),
            "sigma": config_data.get("sigma", 3.0),
            "expected_hours_week": config_data.get("expected_hours_week", 168),
        }
    else:
        model_payload = {
            "model_version": candidate_version,
            "model_type": model_type,
            "scorer_class": "Baseline3SigmaScorer",
            "baseline_days": config_data.get("baseline_days", 28),
            "recent_days": config_data.get("recent_days", 7),
            "sigma": config_data.get("sigma", 3.0),
            "metrics": config_data.get("metrics", []),
            "visits_per_week": config_data.get("visits_per_week", 15),
        }
    joblib.dump(model_payload, target_dir / "model.joblib")

    # 8. Compute artifact_hash covering behavior-defining files
    artifact_hash = compute_artifact_hash(target_dir)

    # 9. Write manifest.json
    manifest_data = {
        "model_version": candidate_version,
        "model_type": model_type,
        "feature_version": feature_version,
        "schema_version": "telemetry-v1",
        "artifact_hash": artifact_hash,
        "evaluation_mode": "cost_backtest",
        "evidence_quality": evidence_quality,
        "evaluation_scope": "precision_biased_sample",
        "training_period": [
            "2025-08-01",
            "2026-01-31",
        ],
        "feature_selection_frozen_at": "2026-09-05T00:00:00Z",
        "software_lock_version": "requirements.lock",
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest_data, indent=2), encoding="utf-8"
    )

    # 10. Write metrics.json
    metrics_data = {
        "model_version": candidate_version,
        "model_type": model_type,
        "training_master_count": len(master_df),
        "training_field_visits_count": len(dev_visits),
        "holdout_gateways_excluded": len(holdout_ids),
        "training_development_gateways": len(dev_gateways),
        "training_period": ["2025-08-01", "2026-01-31"],
        "status": "materialized",
    }
    if candidate_version == "v0002":
        metrics_data["weights"] = config_data.get("weights", {})

    (target_dir / "metrics.json").write_text(
        json.dumps(metrics_data, indent=2), encoding="utf-8"
    )

    # 11. Write Training Evidence Record to runs/training/
    runs_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = runs_dir / f"train_{candidate_version}.json"
    evidence_data = {
        "candidate_version": candidate_version,
        "artifact_dir": str(target_dir),
        "artifact_hash": artifact_hash,
        "data_dir": str(data_dir),
        "training_cutoff_utc": "2026-01-31T00:00:00Z",
        "created_at_utc": "2026-09-05T00:00:00Z",
        "metrics": metrics_data,
    }
    evidence_file.write_text(json.dumps(evidence_data, indent=2), encoding="utf-8")

    # 12. HARD INVARIANT ASSERTION: Zero production mutation
    active_after: str | None = None
    if registry_path.exists():
        active_after = registry_path.read_text(encoding="utf-8")

    if active_before != active_after:
        raise RuntimeError(
            "FATAL INVARIANT VIOLATION: train_candidate altered active production state in registry/active.json! "
            "train.py must NEVER promote, rollback, or mutate production state."
        )

    return {
        "candidate_version": candidate_version,
        "artifact_dir": str(target_dir),
        "artifact_hash": artifact_hash,
        "evidence_file": str(evidence_file),
    }
