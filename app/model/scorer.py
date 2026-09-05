"""Polymorphic model scorer implementations per Rule 9 and frozen v25 architecture.

Rule 9: Scorer implementations inherit from a polymorphic BaseScorer abstract class:
- Baseline3SigmaScorer for v0001 (packages supplied baseline_3sigma.py decision logic)
- WeightedMultiSignalScorer for v0002 (frozen features, deterministic weights)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import datetime as dt
import pathlib
from typing import Any, Optional, Set

import numpy as np
import pandas as pd


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

        reporting_gateways = set(grouped[id_col].unique()) if not grouped.empty else set()
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
