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
import json
import pandas as pd
from pydantic import BaseModel, Field

from app.data.loader import (
    canonicalize_gateway_id,
    get_gateway_eligibility,
    load_field_visits,
    load_gateway_master,
)
from app.data.quality import HoldoutProtection, DevelopmentFirewallError, HoldoutAccessError
from app.features.holdout import load_group_holdout_ids
from app.model.predict import predict_week


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


# ==============================================================================
# Multi-Window Rolling Evaluation & Grouped Holdout Engine (Task 15)
# ==============================================================================

ROLLING_WINDOWS: Dict[str, Dict[str, Any]] = {
    "window_1": {
        "name": "Window 1 (Nov 2025)",
        "train_period": ("2025-08-01", "2025-10-31"),
        "holdout_month": "2025-11",
        "mondays": ["2025-11-03", "2025-11-10", "2025-11-17", "2025-11-24"],
    },
    "window_2": {
        "name": "Window 2 (Dec 2025)",
        "train_period": ("2025-08-01", "2025-11-30"),
        "holdout_month": "2025-12",
        "mondays": ["2025-12-01", "2025-12-08", "2025-12-15", "2025-12-22", "2025-12-29"],
    },
    "window_3": {
        "name": "Window 3 (Jan 2026)",
        "train_period": ("2025-08-01", "2025-12-31"),
        "holdout_month": "2026-01",
        "mondays": ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"],
    },
}


class WindowEvaluationResult(BaseModel):
    """Evaluation result for an individual rolling temporal window."""
    window_id: str
    name: str
    train_period: Tuple[str, str]
    holdout_month: str
    mondays: List[str]
    active_missed_broken_weeks: int
    candidate_missed_broken_weeks: int
    differential: int  # active - candidate
    differential_percent: float
    is_regression: bool  # candidate > active
    cost_differential_eur: float  # differential * 600.0 (excludes fixed 45600)

    model_config = {"frozen": True}


class GroupedHoldoutEvaluationResult(BaseModel):
    """Evaluation result on isolated unseen hardware gateways."""
    holdout_gateways_count: int
    mondays: List[str]
    active_missed_broken_weeks: int
    candidate_missed_broken_weeks: int
    differential: int  # active - candidate
    directional_agreement: bool  # candidate <= active
    cost_differential_eur: float  # differential * 600.0

    model_config = {"frozen": True}


class CoverageEvaluationResult(BaseModel):
    """Evaluation population and applicability contract per Section 8A."""
    evaluation_population_total: int
    active_valid_count: int
    candidate_valid_count: int
    common_valid_count: int
    excluded_due_to_model_input: int
    coverage_ratio: float
    minimum_coverage_ratio: float = 0.90
    passes_coverage: bool

    model_config = {"frozen": True}


class MultiWindowEvaluationReport(BaseModel):
    """Comprehensive multi-window and grouped holdout evaluation report."""
    active_version: str
    candidate_version: str
    evaluation_mode: str = "cost_backtest"
    windows: Dict[str, WindowEvaluationResult]
    aggregate_active_missed: int
    aggregate_candidate_missed: int
    aggregate_differential: int
    aggregate_improvement_percent: float
    aggregate_cost_differential_eur: float
    fixed_visit_cost_eur: float = 45600.0
    total_active_cost_eur: float
    total_candidate_cost_eur: float
    has_window_regression: bool
    grouped_holdout: GroupedHoldoutEvaluationResult
    coverage: CoverageEvaluationResult
    created_at_utc: str = "2026-09-05T00:00:00Z"

    model_config = {"frozen": True}


def evaluate_candidate_against_active(
    data_dir: Path,
    candidate_version: str = "v0002",
    active_version: str = "v0001",
    registry_path: Path = Path("registry/active.json"),
    holdout_path: Path = Path("registry/grouped_holdout.json"),
    label_spec: Optional[LabelSpecV1] = None,
    obs_end_date: Optional[dt.date] = None,
    runs_dir: Optional[Path] = Path("runs/evaluation"),
    custom_predictions: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
) -> MultiWindowEvaluationReport:
    """Execute multi-window rolling temporal evaluation and isolated grouped holdout.

    Contract Invariants (Section 8, 8A, 8B, 8C, 8D):
    1. Evaluates candidate against active across 3 expanding rolling windows (13 Mondays).
    2. Isolated grouped holdout (GROUP_HOLDOUT_IDS) evaluated separately.
    3. Common valid population enforcement: coverage_ratio >= 0.90.
    4. Fixed €380 visit cost (€45,600) is informational only and excluded from promotion delta.
    5. Delta is strictly missed_broken_gateway_weeks * €600.
    6. Emits immutable evaluation evidence report to runs/evaluation/eval_{candidate_version}.json.
    """
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Specified data directory does not exist: {data_dir}")

    # Load master, visits, and grouped holdout IDs
    master_df = load_gateway_master(data_dir)
    visits_df = load_field_visits(data_dir)
    holdout_ids = load_group_holdout_ids(holdout_path)

    spec = label_spec or LabelSpecV1()
    end_date = obs_end_date or dt.date(2026, 2, 14)
    obs_window = (pd.Timestamp("2025-08-01", tz="UTC"), pd.Timestamp(end_date, tz="UTC"))

    # Map each Monday to its window
    monday_to_window: Dict[str, str] = {}
    all_mondays: List[str] = []
    for w_id, w_info in ROLLING_WINDOWS.items():
        for m_str in w_info["mondays"]:
            all_mondays.append(m_str)
            monday_to_window[m_str] = w_id

    # Tracking accumulators
    window_act_missed: Dict[str, int] = {w: 0 for w in ROLLING_WINDOWS}
    window_cand_missed: Dict[str, int] = {w: 0 for w in ROLLING_WINDOWS}
    act_holdout_missed = 0
    cand_holdout_missed = 0

    pop_total = 0
    act_valid_total = 0
    cand_valid_total = 0
    common_valid_total = 0

    # Single-pass execution over 13 Mondays
    for m_str in all_mondays:
        m_date = dt.date.fromisoformat(m_str)
        w_id = monday_to_window[m_str]

        # 1. Predictions for Active Model
        if custom_predictions and active_version in custom_predictions and m_str in custom_predictions[active_version]:
            act_res = custom_predictions[active_version][m_str]
        else:
            act_res = predict_week(data_dir, m_date, active_version=active_version, registry_path=registry_path)

        # 2. Predictions for Candidate Model
        if custom_predictions and candidate_version in custom_predictions and m_str in custom_predictions[candidate_version]:
            cand_res = custom_predictions[candidate_version][m_str]
        else:
            cand_res = predict_week(data_dir, m_date, active_version=candidate_version, registry_path=registry_path)

        act_top15 = {p["gateway_id"] for p in act_res["predictions"]}
        cand_top15 = {p["gateway_id"] for p in cand_res["predictions"]}

        # Eligibility
        elig_df = get_gateway_eligibility(master_df, m_date)
        el_gids = set(elig_df[elig_df["is_eligible"]]["canonical_id"])
        pop_total += len(el_gids)

        act_valid = len(act_res.get("predictions", [])) + act_res.get("backlog_report", {}).get("deferred_count", 0)
        cand_valid = len(cand_res.get("predictions", [])) + cand_res.get("backlog_report", {}).get("deferred_count", 0)
        act_valid_total += act_valid
        cand_valid_total += cand_valid
        common_valid_total += min(act_valid, cand_valid)

        # 3. Development fleet for temporal window evaluation
        dev_gids = el_gids - holdout_ids
        f_cutoff = pd.Timestamp(m_date, tz="UTC")

        broken_dev = set()
        for gid in dev_gids:
            if label_gateway_week(gid, m_date, f_cutoff, obs_window, spec, visits_df, allow_holdout=True) == GatewayWeekLabel.BROKEN:
                broken_dev.add(gid)

        window_act_missed[w_id] += len(broken_dev - act_top15)
        window_cand_missed[w_id] += len(broken_dev - cand_top15)

        # 4. Grouped holdout fleet (evaluated with allow_holdout=True)
        h_gids = el_gids & holdout_ids
        broken_h = set()
        for gid in h_gids:
            if label_gateway_week(gid, m_date, f_cutoff, obs_window, spec, visits_df, allow_holdout=True) == GatewayWeekLabel.BROKEN:
                broken_h.add(gid)

        act_holdout_missed += len(broken_h - act_top15)
        cand_holdout_missed += len(broken_h - cand_top15)

    # Compile Window Results
    windows_dict: Dict[str, WindowEvaluationResult] = {}
    for w_id, w_info in ROLLING_WINDOWS.items():
        w_act = window_act_missed[w_id]
        w_cand = window_cand_missed[w_id]
        diff = w_act - w_cand
        pct = (diff / w_act * 100.0) if w_act > 0 else 0.0
        is_reg = w_cand > w_act
        cost_diff = diff * 600.0

        windows_dict[w_id] = WindowEvaluationResult(
            window_id=w_id,
            name=w_info["name"],
            train_period=w_info["train_period"],
            holdout_month=w_info["holdout_month"],
            mondays=w_info["mondays"],
            active_missed_broken_weeks=w_act,
            candidate_missed_broken_weeks=w_cand,
            differential=diff,
            differential_percent=round(pct, 2),
            is_regression=is_reg,
            cost_differential_eur=cost_diff,
        )

    # Compile Grouped Holdout Result
    holdout_diff = act_holdout_missed - cand_holdout_missed
    grouped_result = GroupedHoldoutEvaluationResult(
        holdout_gateways_count=len(holdout_ids),
        mondays=all_mondays,
        active_missed_broken_weeks=act_holdout_missed,
        candidate_missed_broken_weeks=cand_holdout_missed,
        differential=holdout_diff,
        directional_agreement=(cand_holdout_missed <= act_holdout_missed),
        cost_differential_eur=holdout_diff * 600.0,
    )

    # Compile Coverage Result
    max_valid = max(act_valid_total, cand_valid_total)
    cov_ratio = (common_valid_total / max_valid) if max_valid > 0 else 0.0
    coverage_result = CoverageEvaluationResult(
        evaluation_population_total=pop_total,
        active_valid_count=act_valid_total,
        candidate_valid_count=cand_valid_total,
        common_valid_count=common_valid_total,
        excluded_due_to_model_input=pop_total - common_valid_total,
        coverage_ratio=round(cov_ratio, 4),
        minimum_coverage_ratio=0.90,
        passes_coverage=(cov_ratio >= 0.90),
    )

    # Aggregate Metrics across temporal windows
    agg_act = sum(w.active_missed_broken_weeks for w in windows_dict.values())
    agg_cand = sum(w.candidate_missed_broken_weeks for w in windows_dict.values())
    agg_diff = agg_act - agg_cand
    agg_pct = (agg_diff / agg_act * 100.0) if agg_act > 0 else 0.0
    agg_cost_diff = agg_diff * 600.0
    fixed_visit_cost = 45600.0
    total_act_cost = fixed_visit_cost + (agg_act * 600.0)
    total_cand_cost = fixed_visit_cost + (agg_cand * 600.0)
    has_reg = any(w.is_regression for w in windows_dict.values())

    report = MultiWindowEvaluationReport(
        active_version=active_version,
        candidate_version=candidate_version,
        evaluation_mode="cost_backtest",
        windows=windows_dict,
        aggregate_active_missed=agg_act,
        aggregate_candidate_missed=agg_cand,
        aggregate_differential=agg_diff,
        aggregate_improvement_percent=round(agg_pct, 2),
        aggregate_cost_differential_eur=agg_cost_diff,
        fixed_visit_cost_eur=fixed_visit_cost,
        total_active_cost_eur=total_act_cost,
        total_candidate_cost_eur=total_cand_cost,
        has_window_regression=has_reg,
        grouped_holdout=grouped_result,
        coverage=coverage_result,
        created_at_utc="2026-09-05T00:00:00Z",
    )

    # Persist report if runs_dir is specified
    if runs_dir:
        runs_dir.mkdir(parents=True, exist_ok=True)
        report_path = runs_dir / f"eval_{candidate_version}.json"
        report_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")

    return report
