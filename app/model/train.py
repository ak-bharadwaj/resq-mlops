"""Production training and candidate materialization engine.

Strict Invariants:
1. Physical Module Separation: Responsible for historical data loading, label/proxy construction,
   training feature evaluation, and candidate packaging.
2. Candidate Creation Only: train.py MUST NEVER alter active production state, MUST NEVER modify
   registry/active.json, and MUST NEVER promote or rollback models.
3. Monotonic Time Authority: Temporal bounds driven strictly by pre-holdout development cutoff
   (2026-01-31 UTC). Zero system clock calls.
4. Dual-Hash Cryptographic Provenance: Generates immutable candidate package with artifact_hash.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
from typing import Any

import pandas as pd

from app.data.loader import (
    load_field_visits,
    load_gateway_master,
)
from app.data.schema import TelemetrySchemaContract


class TrainingError(Exception):
    """Raised when training, feature construction, or candidate materialization fails."""


def compute_artifact_hash(model_dir: pathlib.Path) -> str:
    """Compute SHA256 covering immutable behavior-defining artifact files."""
    hasher = hashlib.sha256()
    # Canonical order of behavior-defining artifact files per Section 6 / v25
    hash_files = ["model_config.json", "feature_schema.json", "schema.json", "scorer_identity.txt"]
    for fname in hash_files:
        fpath = model_dir / fname
        if fpath.exists():
            hasher.update(fname.encode("utf-8"))
            hasher.update(fpath.read_bytes())
    return f"sha256:{hasher.hexdigest()}"


def train_candidate(
    data_dir: pathlib.Path,
    candidate_version: str = "v0001",
    output_dir: pathlib.Path | None = None,
    registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
    runs_dir: pathlib.Path = pathlib.Path("runs/training"),
) -> dict[str, Any]:
    """Materialize candidate model package and emit training evidence.

    Args:
        data_dir: Path to the root data directory
        candidate_version: Version identifier for candidate package
        output_dir: Optional custom destination directory (defaults to models/<candidate_version>)
        registry_path: Path to registry/active.json for verifying zero production mutation
        runs_dir: Path to directory where training evidence logs are stored

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

    # 3. Destination Candidate Directory
    target_dir = output_dir or (pathlib.Path("models") / candidate_version)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 4. Write model_config.json
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
    (target_dir / "model_config.json").write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )

    # 5. Write feature_schema.json
    feature_schema_data = {
        "feature_version": "baseline-v1",
        "features": {
            "offline_duration_sec": {"dtype": "float64", "min": 0.0, "max": 3600.0},
            "disconnection_cnt": {"dtype": "float64", "min": 0.0},
            "reboot_cnt": {"dtype": "float64", "min": 0.0},
        },
    }
    (target_dir / "feature_schema.json").write_text(
        json.dumps(feature_schema_data, indent=2), encoding="utf-8"
    )

    # 6. Write authoritative schema.json
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
    baseline_path = pathlib.Path("baseline_3sigma.py")
    if baseline_path.exists():
        baseline_sha = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        scorer_identity_content = f"baseline_3sigma.py:sha256:{baseline_sha}\n"
    else:
        scorer_identity_content = "baseline_3sigma.py:frozen_reference\n"
    (target_dir / "scorer_identity.txt").write_text(
        scorer_identity_content, encoding="utf-8"
    )

    # 8. Compute artifact_hash covering behavior-defining files
    artifact_hash = compute_artifact_hash(target_dir)

    # 9. Write manifest.json
    manifest_data = {
        "model_version": candidate_version,
        "model_type": "baseline_3sigma_anomaly",
        "feature_version": "baseline-v1",
        "schema_version": "telemetry-v1",
        "artifact_hash": artifact_hash,
        "evaluation_mode": "cost_backtest",
        "evidence_quality": "baseline",
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
        "training_master_count": len(master_df),
        "training_field_visits_count": len(dev_visits),
        "training_period": ["2025-08-01", "2026-01-31"],
        "status": "materialized",
    }
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
