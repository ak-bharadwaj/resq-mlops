"""Polymorphic model scorer implementations per Rule 9 and frozen v25 architecture.

Rule 9: Scorer implementations inherit from a polymorphic BaseScorer abstract class:
- Baseline3SigmaScorer for v0001 (packages supplied baseline_3sigma.py decision logic)
- WeightedMultiSignalScorer for v0002 (frozen features, deterministic weights)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import datetime as dt
from typing import Any, Optional, Set

import numpy as np
import pandas as pd

from app.features.build import extract_candidate_features
from app.features.definitions import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_METRICS,
    DEFAULT_RECENT_DAYS,
    DEFAULT_SIGMA,
    EXPECTED_HOURS_WEEK,
    GatewayFeatures,
)


class BaseScorer(ABC):
    """Abstract base class for deterministic model scorers."""

    @abstractmethod
    def score_telemetry(
        self,
        telemetry_df: pd.DataFrame,
        eligible_gateways: Set[str],
        monday: dt.date,
    ) -> list[dict[str, Any]]:
        """Score eligible gateways over the relevant temporal window.

        Returns:
            List of dictionaries containing gateway_id, score, reason.
            Sorted non-increasing by score, tie-broken by canonical gateway_id ascending.
        """
        raise NotImplementedError


class Baseline3SigmaScorer(BaseScorer):
    """v0001 Control Scorer: Packages supplied baseline_3sigma.py without changing decision logic.

    Decision constants:
    - baseline_days: 28
    - recent_days: 7
    - sigma: 3.0
    - metrics: ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]
    """

    def __init__(
        self,
        baseline_days: int = 28,
        recent_days: int = 7,
        sigma: float = 3.0,
        metrics: Optional[list[str]] = None,
    ):
        self.baseline_days = baseline_days
        self.recent_days = recent_days
        self.sigma = sigma
        self.metrics = metrics or ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]

    def compute_window_stats(
        self,
        window_df: pd.DataFrame,
        monday: dt.date,
        id_col: str = "canonical_id",
    ) -> pd.DataFrame:
        """Compute exact 3-sigma flagged hours and worst metric identical to baseline_3sigma.py.

        This method replicates the exact mathematical decisions of baseline_3sigma.py:rank_week:
        1. Group by gateway over trailing 28 days for mean and std.
        2. In trailing 7 days, flag hours where (metric - mean) > 3.0 * std.
        3. Sum flagged hours and record first breach on worst_metric.
        """
        end = pd.Timestamp(monday, tz="UTC")
        window = window_df[
            (window_df["ts"] >= end - dt.timedelta(days=self.baseline_days))
            & (window_df["ts"] < end)
        ]
        if window.empty:
            return pd.DataFrame(columns=[id_col, "flagged_hours", "worst_metric"])

        stats = window.groupby(id_col)[self.metrics].agg(["mean", "std"])
        recent = window[window["ts"] >= end - dt.timedelta(days=self.recent_days)].copy()

        if recent.empty:
            return pd.DataFrame(columns=[id_col, "flagged_hours", "worst_metric"])

        flags = pd.Series(0, index=recent.index, dtype=int)
        worst = pd.Series("", index=recent.index, dtype=object)

        for metric in self.metrics:
            mean = recent[id_col].map(stats[(metric, "mean")])
            std = recent[id_col].map(stats[(metric, "std")]).replace(0, np.nan)
            exceeded = (recent[metric] - mean) > self.sigma * std
            exceeded = exceeded.fillna(False)
            flags = flags + exceeded.astype(int)
            worst = worst.where(~exceeded | (worst != ""), metric)

        recent["flagged"] = flags
        recent["worst_metric"] = worst
        grouped = recent.groupby(id_col).agg(
            flagged_hours=("flagged", "sum"),
            worst_metric=("worst_metric", lambda s: next((v for v in s if v), "")),
        ).reset_index()

        return grouped

    def score_telemetry(
        self,
        telemetry_df: pd.DataFrame,
        eligible_gateways: Set[str],
        monday: dt.date,
    ) -> list[dict[str, Any]]:
        """Score eligible gateways with exact baseline logic + v25 canonical tie-breaking."""
        id_col = "canonical_id" if "canonical_id" in telemetry_df.columns else "gateway_id"

        # Filter telemetry to eligible gateways only
        eligible_mask = telemetry_df[id_col].isin(eligible_gateways)
        window_df = telemetry_df[eligible_mask]

        grouped = self.compute_window_stats(window_df, monday, id_col=id_col)

        flagged_map = dict(zip(grouped[id_col], grouped["flagged_hours"])) if not grouped.empty else {}
        worst_map = dict(zip(grouped[id_col], grouped["worst_metric"])) if not grouped.empty else {}

        # Also gateways in window_df that had zero recent flags
        all_reporting = set(window_df[id_col].unique()) if not window_df.empty else set()

        scored_records: list[dict[str, Any]] = []
        for gid in all_reporting:
            hours = float(flagged_map.get(gid, 0.0))
            worst_m = worst_map.get(gid, "") or "no metric over 3 sigma"
            reason = (
                f"{int(hours)} hour(s) beyond 3 sigma of this gateway's own "
                f"28-day baseline in the last 7 days; first breach on {worst_m}"
            )
            if len(reason) > 300:
                reason = reason[:297] + "..."
            scored_records.append({
                "gateway_id": gid,
                "score": hours,
                "reason": reason,
            })

        # Deterministic Ranking: non-increasing score, tie-break by canonical gateway_id ascending
        scored_records.sort(key=lambda r: (-r["score"], r["gateway_id"]))
        return scored_records


class WeightedMultiSignalScorer(BaseScorer):
    """v0002 Candidate Scorer: Deterministic weighted multi-signal scorer per v25 Sections 2B & 3.

    Mathematical Formulation:
        score = w_anomaly * norm_anomaly + w_silence * recent_silence_ratio

    Invariants:
    - w_anomaly + w_silence = 1.0 (configured in model_config.json)
    - norm_anomaly: min(flagged_hours / 168.0, 1.0)
    - recent_silence_ratio: missing expected hours in trailing 7 days / 168.0
    - Deterministic ordering: non-increasing by score, then canonical gateway_id ascending
    - Serialization: finite non-negative float serialized to 6 decimal places, no NaN/Inf
    - Reason: operations-manager narrative <= 300 chars
    """

    def __init__(
        self,
        w_anomaly: float = 0.7,
        w_silence: float = 0.3,
        baseline_days: int = DEFAULT_BASELINE_DAYS,
        recent_days: int = DEFAULT_RECENT_DAYS,
        sigma: float = DEFAULT_SIGMA,
        metrics: Optional[list[str]] = None,
        expected_hours_week: int = EXPECTED_HOURS_WEEK,
        allow_holdout: bool = False,
        holdout_gateways: Optional[Set[str]] = None,
        enforce_source_completeness: bool = True,
    ):
        self.w_anomaly = float(w_anomaly)
        self.w_silence = float(w_silence)
        self.baseline_days = baseline_days
        self.recent_days = recent_days
        self.sigma = sigma
        self.metrics = metrics or list(DEFAULT_METRICS)
        self.expected_hours_week = expected_hours_week
        self.allow_holdout = allow_holdout
        self.holdout_gateways = holdout_gateways
        self.enforce_source_completeness = enforce_source_completeness
        self.last_features_: list[GatewayFeatures] = []
        self.excluded_records_: list[GatewayFeatures] = []

    def score_telemetry(
        self,
        telemetry_df: pd.DataFrame,
        eligible_gateways: Set[str],
        monday: dt.date,
    ) -> list[dict[str, Any]]:
        """Extract features and score eligible gateways with deterministic tie-breaking."""
        feature_result = extract_candidate_features(
            telemetry_df=telemetry_df,
            eligible_gateways=eligible_gateways,
            monday=monday,
            baseline_days=self.baseline_days,
            recent_days=self.recent_days,
            sigma=self.sigma,
            metrics=self.metrics,
            expected_hours_week=self.expected_hours_week,
            allow_holdout=self.allow_holdout,
            holdout_gateways=self.holdout_gateways,
            enforce_source_completeness=self.enforce_source_completeness,
        )

        self.last_features_ = feature_result["valid_features"]
        self.excluded_records_ = feature_result["excluded_features"]

        scored_records: list[dict[str, Any]] = []

        for feat in self.last_features_:
            combined_score = (
                self.w_anomaly * feat.norm_anomaly
                + self.w_silence * feat.recent_silence_ratio
            )
            # Ensure finite float
            if np.isnan(combined_score) or np.isinf(combined_score):
                raise ValueError(f"Encountered non-finite score {combined_score} for gateway {feat.gateway_id}")

            score_val = round(float(combined_score), 6)

            breach_str = feat.worst_metric if feat.worst_metric else "none"
            missing_hours = max(0, self.expected_hours_week - feat.recent_observed_hours)
            reason = (
                f"Multi-signal risk {score_val:.4f}: {int(feat.flagged_hours)}h 3-sigma "
                f"(norm={feat.norm_anomaly:.4f}, w={self.w_anomaly:.2f}), "
                f"silence {feat.recent_silence_ratio:.4f} ({missing_hours}/168h, w={self.w_silence:.2f}); "
                f"breach={breach_str}"
            )
            if len(reason) > 300:
                reason = reason[:297] + "..."

            scored_records.append({
                "gateway_id": feat.gateway_id,
                "score": score_val,
                "reason": reason,
            })

        # Deterministic Ranking: non-increasing score, tie-break by canonical gateway_id ascending
        scored_records.sort(key=lambda r: (-r["score"], r["gateway_id"]))
        return scored_records


def get_scorer_for_config(
    config: dict[str, Any],
    allow_holdout: bool = False,
    holdout_gateways: Optional[Set[str]] = None,
) -> BaseScorer:
    """Factory helper to instantiate appropriate polymorphic scorer from artifact config."""
    model_type = config.get("model_type", "")
    model_version = config.get("model_version", "")

    baseline_days = int(config.get("baseline_days", DEFAULT_BASELINE_DAYS))
    recent_days = int(config.get("recent_days", DEFAULT_RECENT_DAYS))
    sigma = float(config.get("sigma", DEFAULT_SIGMA))
    metrics = list(config.get("metrics", DEFAULT_METRICS))

    if model_type == "deterministic_weighted_multisignal" or model_version == "v0002":
        weights = config.get("weights", {})
        w_anomaly = float(weights.get("w_anomaly", 0.7))
        w_silence = float(weights.get("w_silence", 0.3))
        expected_hours_week = int(config.get("expected_hours_week", EXPECTED_HOURS_WEEK))
        return WeightedMultiSignalScorer(
            w_anomaly=w_anomaly,
            w_silence=w_silence,
            baseline_days=baseline_days,
            recent_days=recent_days,
            sigma=sigma,
            metrics=metrics,
            expected_hours_week=expected_hours_week,
            allow_holdout=allow_holdout,
            holdout_gateways=holdout_gateways,
        )

    return Baseline3SigmaScorer(
        baseline_days=baseline_days,
        recent_days=recent_days,
        sigma=sigma,
        metrics=metrics,
    )
