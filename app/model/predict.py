"""Production inference engine for active model prediction.

Strict Invariants:
1. Physical Module Separation: NEVER imports training, evaluation, label construction, or field_visits.
2. Monotonic Time Authority: Zero wall-clock calls (datetime.now(), time.time()). All dates derived from input week.
3. Immutability: Reads active model artifact, never mutates registry/active.json or model packages.
4. Authoritative Schema Enforcement: Invokes schema_contract.validate_or_raise(telemetry_df) before scoring.
5. Determinism: Fixed tie-breaking by canonical gateway_id, 6-decimal score serialization.
6. Frozen Replay Contract: SHA256(canonical_input_bytes || canonical_predictions_csv_bytes).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Set

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
from app.model.scorer import Baseline3SigmaScorer


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


def build_canonical_input_bytes(
    telemetry_df: pd.DataFrame,
    start_utc: dt.datetime,
    cutoff_utc: dt.datetime,
    week_start: str | dt.date | None = None,
    active_version: str | None = None,
    eligibility_df: pd.DataFrame | None = None,
    eligible_gateways: Set[str] | None = None,
) -> bytes:
    """Build canonical input bytes per Section 6 / v25 replay contract.

    v25 Specification:
    Cryptographically binds declared decision inputs:
    1. Context Header: week_start, active_version, cutoff_utc
    2. Eligible Gateway State: canonical_id, installed_on, decommissioned_on (sorted ascending)
    3. Telemetry Block: canonical_id, ts, offline_duration_sec, disconnection_cnt, reboot_cnt
       (sorted by ts ascending, then canonical_id ascending)
    Fixed column order, UTF-8, LF endings, explicit null tokens ('NA') and fixed numeric serialization.
    """
    # Handle legacy positional calls: (telemetry_df, start_utc, cutoff_utc, eligible_gateways)
    if isinstance(week_start, (set, list)):
        eligible_gateways = set(week_start)
        week_start = None

    lines: list[str] = []

    # 1. Context Header
    week_str = week_start.isoformat() if hasattr(week_start, "isoformat") else str(week_start or "NA")
    active_str = str(active_version or "NA")
    cutoff_str = cutoff_utc.isoformat() if hasattr(cutoff_utc, "isoformat") else str(cutoff_utc)
    lines.append(f"# context:week_start={week_str},active_version={active_str},cutoff_utc={cutoff_str}\n")

    # 2. Eligible Gateway State Block
    lines.append("canonical_id,installed_on,decommissioned_on\n")
    if eligibility_df is not None and not eligibility_df.empty:
        id_col_elig = "canonical_id" if "canonical_id" in eligibility_df.columns else "gateway_id"
        if "is_eligible" in eligibility_df.columns:
            eligible_rows = eligibility_df[eligibility_df["is_eligible"]].copy()
        else:
            eligible_rows = eligibility_df.copy()

        eligible_rows.sort_values(by=id_col_elig, ascending=True, inplace=True)
        for row in eligible_rows.itertuples(index=False):
            gid = str(getattr(row, id_col_elig))
            inst = getattr(row, "installed_on", None)
            inst_str = str(inst) if pd.notna(inst) else "NA"
            decom = getattr(row, "decommissioned_on", None)
            decom_str = str(decom) if pd.notna(decom) else "NA"
            lines.append(f"{gid},{inst_str},{decom_str}\n")
    elif eligible_gateways:
        for gid in sorted(eligible_gateways):
            lines.append(f"{gid},NA,NA\n")

    # 3. Telemetry Block
    lines.append("canonical_id,ts,offline_duration_sec,disconnection_cnt,reboot_cnt\n")
    id_col = "canonical_id" if "canonical_id" in telemetry_df.columns else "gateway_id"
    metrics = ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]

    mask = (
        (telemetry_df["ts"] >= start_utc)
        & (telemetry_df["ts"] < cutoff_utc)
    )
    if eligible_gateways is not None:
        mask = mask & (telemetry_df[id_col].isin(eligible_gateways))
    elif eligibility_df is not None and not eligibility_df.empty:
        id_col_elig = "canonical_id" if "canonical_id" in eligibility_df.columns else "gateway_id"
        if "is_eligible" in eligibility_df.columns:
            el_set = set(eligibility_df[eligibility_df["is_eligible"]][id_col_elig])
        else:
            el_set = set(eligibility_df[id_col_elig])
        mask = mask & (telemetry_df[id_col].isin(el_set))

    subset = telemetry_df.loc[mask, [id_col, "ts", *metrics]].copy()

    # Deterministic sort: timestamp ascending, then canonical ID ascending
    subset.sort_values(by=["ts", id_col], ascending=[True, True], inplace=True)

    for row in subset.itertuples(index=False):
        gid = str(getattr(row, id_col))
        ts_str = pd.to_datetime(row.ts).isoformat()
        off_str = f"{float(row.offline_duration_sec):.6f}" if pd.notna(row.offline_duration_sec) else "NA"
        disc_str = f"{float(row.disconnection_cnt):.6f}" if pd.notna(row.disconnection_cnt) else "NA"
        reb_str = f"{float(row.reboot_cnt):.6f}" if pd.notna(row.reboot_cnt) else "NA"
        lines.append(f"{gid},{ts_str},{off_str},{disc_str},{reb_str}\n")

    return "".join(lines).encode("utf-8")


def build_canonical_predictions_bytes(predictions: list[dict[str, Any]]) -> bytes:
    """Build canonical predictions bytes per Section 6 / v25 replay contract.

    v25 Specification:
    Canonical predictions use week_start, rank, gateway_id, score, reason in fixed order,
    UTF-8/LF, score serialized to six decimals and deterministic reason truncation.
    """
    sorted_preds = sorted(predictions, key=lambda p: p["rank"])
    lines = ["week_start,rank,gateway_id,score,reason\n"]
    for p in sorted_preds:
        lines.append(
            f"{p['week_start']},{p['rank']},{p['gateway_id']},{float(p['score']):.6f},{p['reason']}\n"
        )
    return "".join(lines).encode("utf-8")


def compute_v25_replay_hash(
    canonical_input_bytes: bytes,
    canonical_predictions_bytes: bytes,
) -> str:
    """Compute replay hash per v25: SHA256(canonical_input_bytes || canonical_predictions_csv_bytes)."""
    hasher = hashlib.sha256()
    hasher.update(canonical_input_bytes)
    hasher.update(canonical_predictions_bytes)
    return f"sha256:{hasher.hexdigest()}"


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
        - "replay_hash": SHA256 deterministic replay hash per v25
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

    # 5. Authoritative Schema Contract Enforcement on Raw Window
    # Explicitly validates columns, dtypes, hourly grain, and ranges per models/<version>/schema.json
    schema_contract.validate_or_raise(telemetry_df)

    # 6. Pre-feature source completeness guard
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

    # 7. Model Scoring via Baseline3SigmaScorer (Rule 9 / v0001)
    scorer = Baseline3SigmaScorer(
        baseline_days=baseline_days,
        recent_days=recent_days,
        sigma=sigma,
        metrics=metrics,
    )
    scored_records = scorer.score_telemetry(
        telemetry_df=telemetry_df,
        eligible_gateways=eligible_gateways,
        monday=monday,
    )

    if len(scored_records) < visits_per_week:
        raise InsufficientEligibleGatewaysError(
            f"Only {len(scored_records)} reporting gateways with data before {monday}, "
            f"cannot fulfill required {visits_per_week} visits"
        )

    # 8. Split into Top-15 and Deferred Backlog (ordered non-increasing by score, then canonical ID)
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

    # 10. Replay Hash Construction per Frozen v25 Contract
    canonical_input_bytes = build_canonical_input_bytes(
        telemetry_df=telemetry_df,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
        week_start=monday,
        active_version=active_version,
        eligibility_df=eligibility_df,
        eligible_gateways=eligible_gateways,
    )
    canonical_pred_bytes = build_canonical_predictions_bytes(predictions)
    replay_hash = compute_v25_replay_hash(canonical_input_bytes, canonical_pred_bytes)

    return {
        "predictions": predictions,
        "backlog_report": backlog_report,
        "replay_hash": replay_hash,
        "active_version": active_version,
        "week_start": monday.isoformat(),
    }
