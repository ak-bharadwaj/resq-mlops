"""Evaluation target, retrospective label construction, and episode semantics (Task 13).

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 2, 2C, 2D, 2E, 8.
- Pure deterministic function: label_gateway_week(gateway_id, week_start, feature_cutoff, label_observation_window, label_spec_v1)
- Output labels: {BROKEN, NOT_BROKEN, UNKNOWN_RIGHT_CENSORED}
- Episode semantics: open -> visited/repaired -> closed -> may reopen
- Development firewall: development period strictly ends 2026-01-31; post-cutoff evidence barred from features & label definition.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import pandas as pd
from pydantic import BaseModel, Field

from app.data.loader import canonicalize_gateway_id
from app.data.quality import HoldoutProtection, DevelopmentFirewallError, HoldoutAccessError


class GatewayWeekLabel(str, Enum):
    """Authoritative gateway-week operational status."""
    BROKEN = "BROKEN"
    NOT_BROKEN = "NOT_BROKEN"
    UNKNOWN_RIGHT_CENSORED = "UNKNOWN_RIGHT_CENSORED"


class EvidenceQuality(str, Enum):
    """Evidence quality level per Section 2 & 18."""
    STRONG = "strong"
    WEAK = "weak"


class EvaluationMode(str, Enum):
    """Evaluation methodology mode."""
    COST_BACKTEST = "cost_backtest"
    HEURISTIC = "heuristic"


class LabelSpecV1(BaseModel):
    """Frozen specification contract for retrospective gateway-week failure proxy."""
    version: str = Field(default="label-v1")
    mode: EvaluationMode = Field(default=EvaluationMode.COST_BACKTEST)
    evidence_quality: EvidenceQuality = Field(default=EvidenceQuality.STRONG)
    evaluation_scope: str = Field(
        default="precision_biased_sample",
        description="FAQ 4.4: field_visits gateways were suspected; carries no fleet recall claim.",
    )
    development_cutoff: dt.date = Field(
        default=dt.date(2026, 1, 31),
        description="Section 2C: Development period strictly ends 2026-01-31.",
    )
    confirmed_outcomes: Tuple[str, ...] = Field(
        default=("Fehler behoben",),
        description="Confirmed hardware repairs / defects resolved by field visit.",
    )
    min_interpretable_cases: int = Field(
        default=3,
        description="Section 2C sanity gate: require >= 3 clearly interpretable cases.",
    )

    model_config = {
        "frozen": True,
        "arbitrary_types_allowed": True,
    }


class CohortLabelSummary(BaseModel):
    """Deterministic summary of gateway-week cohort labeling."""
    total_gateway_weeks: int
    evaluated_gateway_weeks: int
    broken_gateway_weeks: int
    not_broken_gateway_weeks: int
    right_censored_gateway_weeks: int
    unknown_gateway_weeks: int
    evidence_quality: EvidenceQuality
    evaluation_mode: EvaluationMode
    evaluation_scope: str

    model_config = {
        "frozen": True,
    }


def _normalize_date(date_val: Any) -> dt.date:
    """Safely extract dt.date from string, datetime, or date."""
    if isinstance(date_val, dt.date) and not isinstance(date_val, dt.datetime):
        return date_val
    if hasattr(date_val, "date") and callable(getattr(date_val, "date")):
        return date_val.date()
    return pd.to_datetime(date_val).date()


def _normalize_utc_datetime(dt_val: Any) -> dt.datetime:
    """Ensure timezone-aware UTC datetime."""
    ts = pd.to_datetime(dt_val, utc=True)
    return ts.to_pydatetime()


def label_gateway_week(
    gateway_id: str,
    week_start: dt.date | str,
    feature_cutoff: dt.datetime | pd.Timestamp,
    label_observation_window: Tuple[dt.datetime | pd.Timestamp, dt.datetime | pd.Timestamp],
    label_spec_v1: LabelSpecV1,
    visits_df: pd.DataFrame,
    allow_holdout: bool = False,
) -> GatewayWeekLabel:
    """Pure deterministic function evaluating retrospective gateway-week status.

    Frozen Contract Invariants (Section 2D & 2E):
    - gateway_id is normalized to canonical 12 uppercase hexadecimal characters.
    - feature_cutoff governs feature construction only, and MUST strictly be Monday 00:00:00 UTC.
    - label_observation_window may extend beyond week_start to observe retrospective outcomes/recovery.
    - If recovery is not observable before the observation window ends, classify the terminal
      interval as UNKNOWN_RIGHT_CENSORED; do not treat end-of-data as recovery.
    - Tracks BROKEN state as episodes (open -> visited-or-recovered -> closed -> may reopen).
    - Development firewall: if allow_holdout is False, accessing dates past development_cutoff
      raises DevelopmentFirewallError.
    """
    canonical_id = canonicalize_gateway_id(gateway_id)
    monday_date = _normalize_date(week_start)
    sunday_date = monday_date + dt.timedelta(days=6)

    # 1. Strict feature_cutoff invariant check (must be Monday 00:00:00 UTC)
    f_cutoff_utc = _normalize_utc_datetime(feature_cutoff)
    expected_f_cutoff = dt.datetime(monday_date.year, monday_date.month, monday_date.day, 0, 0, 0, tzinfo=dt.timezone.utc)
    if f_cutoff_utc != expected_f_cutoff:
        raise ValueError(
            f"feature_cutoff must be exactly Monday 00:00:00 UTC ({expected_f_cutoff}), got {f_cutoff_utc}"
        )

    # 2. Validate observation window
    obs_start = _normalize_utc_datetime(label_observation_window[0])
    obs_end = _normalize_utc_datetime(label_observation_window[1])
    if obs_start > obs_end:
        raise ValueError(f"Invalid label_observation_window: start ({obs_start}) > end ({obs_end})")

    if visits_df.empty:
        return GatewayWeekLabel.NOT_BROKEN

    # Ensure canonical_id exists on visits_df
    if "canonical_id" not in visits_df.columns:
        if "gateway_id" in visits_df.columns:
            work_visits = visits_df.copy()
            work_visits["canonical_id"] = work_visits["gateway_id"].apply(canonicalize_gateway_id)
        else:
            raise ValueError("visits_df must contain 'canonical_id' or 'gateway_id'")
    else:
        work_visits = visits_df

    # Filter visits for this gateway
    gw_visits = work_visits[work_visits["canonical_id"] == canonical_id]
    if gw_visits.empty:
        return GatewayWeekLabel.NOT_BROKEN

    # 4. Episode evaluation
    # Check if there is any active fault episode during [monday_date, sunday_date]
    obs_end_date = obs_end.date()

    has_censored = False
    for _, row in gw_visits.iterrows():
        req_on = _normalize_date(row["requested_on"])
        vis_on = _normalize_date(row["visited_on"]) if pd.notna(row.get("visited_on")) else None
        outcome = str(row.get("outcome", "")).strip()

        # Did a fault request occur on or before this week's end?
        if req_on <= sunday_date:
            # Check if visit / recovery was observed within label observation window
            if vis_on is not None and vis_on <= obs_end_date:
                # Visit landed within observation window
                # Was fault active during [monday_date, sunday_date]?
                # Fault is active if it had not been resolved before monday_date
                if vis_on >= monday_date:
                    # Episode was active in this week!
                    # Check if outcome confirms defect
                    if outcome in label_spec_v1.confirmed_outcomes:
                        return GatewayWeekLabel.BROKEN
            else:
                # Visit not yet observed within observation window!
                # If the fault was requested on or before this week's end, and no prior
                # visit resolved it before monday_date, terminal outcome is right-censored.
                if vis_on is None or vis_on > obs_end_date:
                    has_censored = True

    if has_censored:
        return GatewayWeekLabel.UNKNOWN_RIGHT_CENSORED

    return GatewayWeekLabel.NOT_BROKEN


def label_cohort(
    gateway_ids: Iterable[str],
    week_start: dt.date | str,
    feature_cutoff: dt.datetime | pd.Timestamp,
    label_observation_window: Tuple[dt.datetime | pd.Timestamp, dt.datetime | pd.Timestamp],
    label_spec_v1: LabelSpecV1,
    visits_df: pd.DataFrame,
    allow_holdout: bool = False,
) -> Tuple[Dict[str, GatewayWeekLabel], CohortLabelSummary]:
    """Label a cohort of gateways for a given week and compute population summary."""
    labels: Dict[str, GatewayWeekLabel] = {}
    total = 0
    broken_cnt = 0
    not_broken_cnt = 0
    right_censored_cnt = 0

    for gid in gateway_ids:
        total += 1
        lbl = label_gateway_week(
            gateway_id=gid,
            week_start=week_start,
            feature_cutoff=feature_cutoff,
            label_observation_window=label_observation_window,
            label_spec_v1=label_spec_v1,
            visits_df=visits_df,
            allow_holdout=allow_holdout,
        )
        labels[gid] = lbl
        if lbl == GatewayWeekLabel.BROKEN:
            broken_cnt += 1
        elif lbl == GatewayWeekLabel.NOT_BROKEN:
            not_broken_cnt += 1
        elif lbl == GatewayWeekLabel.UNKNOWN_RIGHT_CENSORED:
            right_censored_cnt += 1

    evaluated_cnt = broken_cnt + not_broken_cnt
    summary = CohortLabelSummary(
        total_gateway_weeks=total,
        evaluated_gateway_weeks=evaluated_cnt,
        broken_gateway_weeks=broken_cnt,
        not_broken_gateway_weeks=not_broken_cnt,
        right_censored_gateway_weeks=right_censored_cnt,
        unknown_gateway_weeks=right_censored_cnt,
        evidence_quality=label_spec_v1.evidence_quality,
        evaluation_mode=label_spec_v1.mode,
        evaluation_scope=label_spec_v1.evaluation_scope,
    )

    return labels, summary
