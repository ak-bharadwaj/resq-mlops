"""Production inference engine for active model prediction.

Strict Invariants:
1. Physical Module Separation: NEVER imports training, evaluation, label construction, or field_visits.
2. Monotonic Time Authority: Zero wall-clock calls (datetime.now(), time.time()). All dates derived from input week.
3. Immutability: Reads active model artifact, never mutates registry/active.json or model packages.
4. Determinism: Fixed tie-breaking by canonical gateway_id, 6-decimal score serialization, replay hash.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any

import numpy as np
import pandas as pd

from app.data.loader import (
    canonicalize_gateway_id,
    get_gateway_eligibility,
    load_gateway_master,
    load_telemetry_window,
)
from app.data.quality import SourceCompletenessError, check_source_completeness
from app.data.schema import SchemaValidationError, TelemetrySchemaContract


class ModelArtifactError(Exception):
    """Raised when active model package is missing, incomplete, or corrupted."""


class InsufficientEligibleGatewaysError(Exception):
    """Raised when fewer than 15 eligible candidates exist for a scored week."""


def resolve_active_model_version(registry_path: pathlib.Path = pathlib.Path("registry/active.json")) -> str:
    """Resolve the active model version from registry/active.json."""
    if not registry_path.exists():
        raise ModelArtifactError(f"Active registry pointer missing: {registry_path}")
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelArtifactError(f"Corrupt active registry pointer at {registry_path}: {exc}") from exc

    version = data.get("production_version")
    if not version:
        raise ModelArtifactError(f"registry/active.json lacks 'production_version': {data}")
    return str(version)


def load_active_artifact_config(
    model_dir: pathlib.Path,
) -> tuple[dict[str, Any], TelemetrySchemaContract]:
    """Load and validate configuration and schema for the active model artifact."""
    if not model_dir.exists() or not model_dir.is_dir():
        raise ModelArtifactError(f"Active model artifact directory does not exist: {model_dir}")

    config_path = model_dir / "model_config.json"
    if not config_path.exists():
        raise ModelArtifactError(f"Active model config missing: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelArtifactError(f"Corrupt model config at {config_path}: {exc}") from exc

    schema_contract = TelemetrySchemaContract.load_from_model(model_dir)
    return config, schema_contract


def predict_week(
    data_dir: pathlib.Path,
    week_start: str | dt.date,
    active_version: str | None = None,
    registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
    models_dir: pathlib.Path = pathlib.Path("models"),
) -> dict[str, Any]:
    """Execute prediction pipeline for a single scored Monday.

    Args:
        data_dir: Path to the root data directory containing gateway_master.csv and telemetry/
        week_start: Scored Monday date (YYYY-MM-DD string or dt.date)
        active_version: Optional explicit version override (defaults to registry/active.json)
        registry_path: Path to registry/active.json
        models_dir: Path to models directory

    Returns:
        Dictionary containing:
        - "predictions": list of 15 dicts (week_start, rank, gateway_id, score, reason)
        - "backlog_report": dict of deferred backlog economics
        - "replay_hash": SHA256 deterministic replay hash
        - "active_version": active model version
        - "week_start": ISO formatted week start string
    """
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Specified data directory does not exist: {data_dir}")

    # 1. Monotonic Temporal Authority: parse Monday without system clock calls
    if isinstance(week_start, str):
        monday = dt.date.fromisoformat(week_start)
    else:
        monday = week_start

    # Monday 00:00:00 UTC temporal firewall cutoff
    cutoff_utc = dt.datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=dt.timezone.utc)

    # 2. Resolve Active Model Package
    if active_version is None:
        active_version = resolve_active_model_version(registry_path)

    model_dir = models_dir / active_version
    config, schema_contract = load_active_artifact_config(model_dir)

    baseline_days = int(config.get("baseline_days", 28))
    recent_days = int(config.get("recent_days", 7))
    sigma = float(config.get("sigma", 3.0))
    metrics = list(config.get("metrics", ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]))
    visits_per_week = int(config.get("visits_per_week", 15))

    start_utc = cutoff_utc - dt.timedelta(days=baseline_days)
    recent_start_utc = cutoff_utc - dt.timedelta(days=recent_days)

    # 3. Ingestion & Eligibility
    master_df = load_gateway_master(data_dir)
    eligibility_df = get_gateway_eligibility(master_df, monday)
    eligible_gateways = set(eligibility_df[eligibility_df["is_eligible"]]["canonical_id"])

    if len(eligible_gateways) < visits_per_week:
        raise InsufficientEligibleGatewaysError(
            f"Only {len(eligible_gateways)} eligible gateways on {monday}, required {visits_per_week}"
        )

    # 4. Telemetry Window Ingestion strictly before Monday 00:00 UTC
    telemetry_df = load_telemetry_window(
        data_dir,
        cutoff_utc=cutoff_utc,
        start_utc=start_utc,
    )

    # 5. Pre-feature source completeness guard
    completeness = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible_gateways,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
    )
    if not completeness.is_safe:
        raise SourceCompletenessError(
            f"Source completeness guard tripped: fleet absence rate {completeness.absence_rate:.2%} "
            f"exceeds threshold. Entering BLOCK_FEATURES."
        )

    # 6. Feature Construction & 3-Sigma Anomaly Scoring
    # Filter telemetry to eligible gateways only
    telemetry_eligible = telemetry_df[telemetry_df["canonical_id"].isin(eligible_gateways)].copy()

    reporting_gateways = set(telemetry_eligible["canonical_id"].unique()) if not telemetry_eligible.empty else set()
    zero_telemetry_gateways = eligible_gateways - reporting_gateways

    scored_records: list[dict[str, Any]] = []

    if not telemetry_eligible.empty:
        # Trailing 28-day baseline stats per gateway
        stats = telemetry_eligible.groupby("canonical_id")[metrics].agg(["mean", "std"])

        # Trailing 7-day window for recent anomaly evaluation
        recent_mask = telemetry_eligible["ts"] >= recent_start_utc
        recent_df = telemetry_eligible[recent_mask].copy()

        if not recent_df.empty:
            flags = pd.Series(0, index=recent_df.index, dtype=int)
            worst = pd.Series("", index=recent_df.index, dtype=object)

            for metric in metrics:
                mean_col = recent_df["canonical_id"].map(stats[(metric, "mean")])
                std_col = recent_df["canonical_id"].map(stats[(metric, "std")]).replace(0, np.nan)
                exceeded = (recent_df[metric] - mean_col) > (sigma * std_col)
                exceeded = exceeded.fillna(False)
                flags = flags + exceeded.astype(int)
                worst = worst.where(~exceeded | (worst != ""), metric)

            recent_df["flagged"] = flags
            recent_df["worst_metric"] = worst

            grouped = recent_df.groupby("canonical_id").agg(
                flagged_hours=("flagged", "sum"),
                worst_metric=("worst_metric", lambda s: next((v for v in s if v), "none")),
            ).reset_index()

            flagged_map = dict(zip(grouped["canonical_id"], grouped["flagged_hours"]))
            worst_map = dict(zip(grouped["canonical_id"], grouped["worst_metric"]))
        else:
            flagged_map = {}
            worst_map = {}

        for gid in reporting_gateways:
            hours = float(flagged_map.get(gid, 0.0))
            worst_m = worst_map.get(gid, "none")
            reason = (
                f"{int(hours)} hour(s) beyond 3 sigma of 28-day baseline in trailing 7 days; "
                f"primary breach on {worst_m}"
            )
            # Guarantee operations-manager reason length <= 300
            if len(reason) > 300:
                reason = reason[:297] + "..."
            scored_records.append({
                "gateway_id": gid,
                "score": hours,
                "reason": reason,
            })

    # Gateways with zero telemetry (NO_TELEMETRY) are never assigned invented scores;
    # they are excluded from candidate ranking per Section 2B / Task 9.

    if len(scored_records) < visits_per_week:
        raise InsufficientEligibleGatewaysError(
            f"Only {len(scored_records)} reporting gateways with data before {monday}, "
            f"cannot fulfill required {visits_per_week} visits"
        )

    # 7. Deterministic Ranking: non-increasing score, then canonical gateway_id ascending
    scored_records.sort(key=lambda r: (-r["score"], r["gateway_id"]))

    # 8. Split into Top-15 and Deferred Backlog
    top_15 = scored_records[:visits_per_week]
    backlog_records = scored_records[visits_per_week:]

    predictions: list[dict[str, Any]] = []
    for rank, rec in enumerate(top_15, 1):
        predictions.append({
            "week_start": monday.isoformat(),
            "rank": rank,
            "gateway_id": rec["gateway_id"],
            "score": float(rec["score"]),
            "reason": rec["reason"],
        })

    # 9. Backlog Report Generation (ranks 16+)
    deferred_count = len(backlog_records)
    deferred_high_risk = sum(1 for r in backlog_records if r["score"] > 0.0)
    deferred_proxy_score = sum(r["score"] for r in backlog_records)

    backlog_report = {
        "week_start": monday.isoformat(),
        "max_visits": visits_per_week,
        "selected_count": len(predictions),
        "deferred_count": deferred_count,
        "deferred_high_risk_count": deferred_high_risk,
        "deferred_risk_proxy_score": round(float(deferred_proxy_score), 6),
        "exposure_method": "heuristic_proxy",
        "evidence_quality": "baseline",
        "model_version": active_version,
    }

    # 10. Replay Hash Construction
    canonical_pred_lines = ["week_start,rank,gateway_id,score,reason\n"]
    for row in predictions:
        canonical_pred_lines.append(
            f"{row['week_start']},{row['rank']},{row['gateway_id']},{row['score']:.6f},{row['reason']}\n"
        )
    canonical_pred_bytes = "".join(canonical_pred_lines).encode("utf-8")

    input_hasher = hashlib.sha256()
    input_hasher.update(data_dir.name.encode("utf-8"))
    input_hasher.update(monday.isoformat().encode("utf-8"))
    input_hasher.update(f"eligible:{len(eligible_gateways)}".encode("utf-8"))
    input_hasher.update(f"reporting:{len(reporting_gateways)}".encode("utf-8"))
    input_bytes = input_hasher.digest()

    replay_hasher = hashlib.sha256()
    replay_hasher.update(input_bytes)
    replay_hasher.update(canonical_pred_bytes)
    replay_hash = f"sha256:{replay_hasher.hexdigest()}"

    return {
        "predictions": predictions,
        "backlog_report": backlog_report,
        "replay_hash": replay_hash,
        "active_version": active_version,
        "week_start": monday.isoformat(),
    }
