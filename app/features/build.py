"""Deterministic feature construction engine per Rule 4, 5, 6, 7, 8 and v25 Sections 2B & 3.

Strict Invariants:
1. Monotonic Time Authority: FEATURE_CUTOFF is Monday 00:00:00 UTC. Zero system clock calls.
   All telemetry rows at or after cutoff are strictly excluded.
2. Grouped Holdout Isolation: Gateways in GROUP_HOLDOUT_IDS are excluded from candidate
   feature extraction and training unless allow_holdout=True.
3. Missing Telemetry Taxonomy:
   - Institutional non-coverage (0 hours across baseline): excluded with NO_TELEMETRY.
   - Recently silent (prior history, 0 recent hours): scored with recent_silence_ratio=1.0.
   - Complete reporting (168+ recent hours): recent_silence_ratio=0.0.
4. Train/Predict Parity: The exact same feature calculation logic is used in both training
   and inference paths.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Set

import numpy as np
import pandas as pd

from app.data.quality import (
    HoldoutProtection,
    SourceCompletenessError,
    check_source_completeness,
)
from app.features.definitions import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_METRICS,
    DEFAULT_RECENT_DAYS,
    DEFAULT_SIGMA,
    EXPECTED_HOURS_WEEK,
    GatewayFeatures,
)
from app.features.holdout import load_group_holdout_ids


def extract_candidate_features(
    telemetry_df: pd.DataFrame,
    eligible_gateways: Set[str],
    monday: dt.date,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    recent_days: int = DEFAULT_RECENT_DAYS,
    sigma: float = DEFAULT_SIGMA,
    metrics: Optional[list[str]] = None,
    expected_hours_week: int = EXPECTED_HOURS_WEEK,
    allow_holdout: bool = False,
    holdout_gateways: Optional[Set[str]] = None,
    enforce_source_completeness: bool = True,
) -> dict[str, Any]:
    """Extract frozen candidate features for eligible gateways over the scored week.

    Args:
        telemetry_df: Raw or filtered telemetry dataframe containing 'canonical_id' (or 'gateway_id'),
                      'ts', and metric columns.
        eligible_gateways: Set of canonical gateway IDs eligible for scoring on Monday.
        monday: Scored Monday date.
        baseline_days: Number of days in historical baseline window (default: 28).
        recent_days: Number of days in recent evaluation window (default: 7).
        sigma: Threshold multiplier for standard deviation (default: 3.0).
        metrics: List of metric column names to monitor.
        expected_hours_week: Expected observations per 7-day window (default: 168).
        allow_holdout: Flag indicating whether holdout gateways are permitted (False in dev/train).
        holdout_gateways: Optional set of holdout gateway IDs to guard against.
        enforce_source_completeness: Whether to verify fleet absence before computing features.

    Returns:
        Dictionary containing:
        - "features": list of GatewayFeatures objects for all eligible gateways
        - "valid_features": list of valid GatewayFeatures eligible for risk ranking
        - "excluded_features": list of GatewayFeatures excluded due to missing data
        - "cutoff_utc": cutoff timestamp applied
        - "week_start": Monday date
    """
    active_metrics = metrics or list(DEFAULT_METRICS)
    id_col = "canonical_id" if "canonical_id" in telemetry_df.columns else "gateway_id"

    # 1. Monotonic Time Authority: Cutoff is Monday 00:00:00 UTC
    cutoff_utc = dt.datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=baseline_days)
    recent_start_utc = cutoff_utc - dt.timedelta(days=recent_days)

    # 2. Holdout Protection Guard (Rule 8, Fail-Closed)
    if holdout_gateways is None and not allow_holdout:
        holdout_gateways = load_group_holdout_ids()

    if holdout_gateways and not allow_holdout:
        for gid in eligible_gateways:
            HoldoutProtection.check_gateway_access(
                gateway_id=gid,
                holdout_gateways=holdout_gateways,
                allow_holdout=False,
            )

    # 3. Temporal Cutoff Enforcement: telemetry MUST be strictly before cutoff_utc
    # ts < cutoff_utc (at or after Monday 00:00:00 UTC is strictly excluded)
    valid_time_mask = (telemetry_df["ts"] >= start_utc) & (telemetry_df["ts"] < cutoff_utc)
    window_df = telemetry_df.loc[valid_time_mask].copy()

    # 4. Source Completeness Guard (Rule 7, Section 2B)
    if enforce_source_completeness:
        completeness = check_source_completeness(
            window_df,
            eligible_gateways=eligible_gateways,
            start_utc=start_utc,
            cutoff_utc=cutoff_utc,
        )
        if not completeness.is_safe:
            raise SourceCompletenessError(
                f"Source completeness guard tripped: fleet absence rate {completeness.absence_rate:.2%} "
                f"exceeds threshold. Entering BLOCK_FEATURES."
            )

    # Filter to eligible gateways
    eligible_mask = window_df[id_col].isin(eligible_gateways)
    eligible_telemetry = window_df[eligible_mask]

    # Partition into baseline and recent windows
    recent_mask = eligible_telemetry["ts"] >= recent_start_utc
    recent_df = eligible_telemetry[recent_mask]

    # Compute baseline statistics (mean, std) per gateway
    stats = (
        eligible_telemetry.groupby(id_col)[active_metrics]
        .agg(["mean", "std"])
        if not eligible_telemetry.empty
        else pd.DataFrame()
    )

    # Count observed hours per gateway
    baseline_counts = (
        eligible_telemetry.groupby(id_col).size().to_dict()
        if not eligible_telemetry.empty
        else {}
    )
    recent_counts = (
        recent_df.groupby(id_col).size().to_dict()
        if not recent_df.empty
        else {}
    )

    # Compute 3-sigma flagged hours in recent window
    flagged_map: dict[str, float] = {}
    worst_map: dict[str, str] = {}

    if not recent_df.empty and not stats.empty:
        flags = pd.Series(0, index=recent_df.index, dtype=int)
        worst = pd.Series("", index=recent_df.index, dtype=object)

        for metric in active_metrics:
            mean = recent_df[id_col].map(stats[(metric, "mean")])
            std = recent_df[id_col].map(stats[(metric, "std")]).replace(0, np.nan)
            exceeded = (recent_df[metric] - mean) > sigma * std
            exceeded = exceeded.fillna(False)
            flags = flags + exceeded.astype(int)
            worst = worst.where(~exceeded | (worst != ""), metric)

        recent_df_flags = recent_df.copy()
        recent_df_flags["flagged"] = flags
        recent_df_flags["worst_metric"] = worst

        grouped_recent = recent_df_flags.groupby(id_col).agg(
            flagged_hours=("flagged", "sum"),
            worst_metric=("worst_metric", lambda s: next((v for v in s if v), "")),
        ).reset_index()

        flagged_map = dict(zip(grouped_recent[id_col], grouped_recent["flagged_hours"]))
        worst_map = dict(zip(grouped_recent[id_col], grouped_recent["worst_metric"]))

    # 5. Extract GatewayFeatures for each eligible gateway
    features_list: list[GatewayFeatures] = []
    valid_features: list[GatewayFeatures] = []
    excluded_features: list[GatewayFeatures] = []

    for gid in sorted(eligible_gateways):
        b_hours = baseline_counts.get(gid, 0)
        r_hours = recent_counts.get(gid, 0)

        # Section 2B: Case 1 - Zero telemetry across complete eligible history
        if b_hours == 0:
            feat = GatewayFeatures(
                gateway_id=gid,
                flagged_hours=0.0,
                norm_anomaly=0.0,
                recent_silence_ratio=0.0,
                worst_metric="",
                baseline_observed_hours=0,
                recent_observed_hours=0,
                status="NO_TELEMETRY",
                exclusion_reason="NO_TELEMETRY",
            )
            features_list.append(feat)
            excluded_features.append(feat)
            continue

        # Section 2B: Case 2 - Established prior history: compute silence ratio
        missing_hours = max(0, expected_hours_week - r_hours)
        recent_silence_ratio = float(min(1.0, missing_hours / float(expected_hours_week)))

        f_hours = float(flagged_map.get(gid, 0.0))
        norm_anomaly = float(min(1.0, f_hours / float(expected_hours_week)))
        worst_m = worst_map.get(gid, "")

        feat = GatewayFeatures(
            gateway_id=gid,
            flagged_hours=f_hours,
            norm_anomaly=norm_anomaly,
            recent_silence_ratio=recent_silence_ratio,
            worst_metric=worst_m,
            baseline_observed_hours=b_hours,
            recent_observed_hours=r_hours,
            status="VALID",
            exclusion_reason=None,
        )
        features_list.append(feat)
        valid_features.append(feat)

    return {
        "features": features_list,
        "valid_features": valid_features,
        "excluded_features": excluded_features,
        "cutoff_utc": cutoff_utc,
        "week_start": monday,
    }
