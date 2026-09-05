"""Data quality audits, coverage analysis, and source-completeness guards."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
from app.data.schema import MissingDataReason


class SourceCompletenessError(Exception):
    """Raised when systemic fleet absence trips the source-completeness guard into BLOCK_FEATURES."""


class CompletenessResult(tuple):
    """Result of fleet-wide source completeness check.

    Unpacks cleanly as (is_safe, absence_rate) for 2-tuple compatibility,
    while exposing .is_safe, .absence_rate, and .details attributes.
    """
    is_safe: bool
    absence_rate: float
    details: Dict[str, Any]

    def __new__(cls, is_safe: bool, absence_rate: float, details: Optional[Dict[str, Any]] = None):
        return super().__new__(cls, (is_safe, absence_rate))

    def __init__(self, is_safe: bool, absence_rate: float, details: Optional[Dict[str, Any]] = None):
        self.is_safe = is_safe
        self.absence_rate = absence_rate
        self.details = details or {}


def classify_telemetry_status(
    has_any_historical_telemetry: bool,
    has_recent_telemetry: bool,
    history_hours: Optional[int] = None,
    min_required_hours: Optional[int] = None,
    recent_hours: Optional[int] = None,
    min_feature_hours: Optional[int] = None,
) -> Optional[MissingDataReason]:
    """Classify telemetry presence for an individual eligible gateway.

    Frozen Rules:
    - Zero telemetry across complete eligible history: NO_TELEMETRY exclusion. Never invent a score.
    - Below baseline history requirements: INSUFFICIENT_HISTORY exclusion.
    - Sparse intermediate feature window (< min_feature_hours while reporting): INSUFFICIENT_FEATURE_DATA.
    - A previously-reporting gateway that becomes recently silent: NOT a NO_TELEMETRY exclusion
      (surfaced as recent_silence_ratio risk feature in candidate model, not dropped).
    """
    if not has_any_historical_telemetry:
        return MissingDataReason.NO_TELEMETRY
    if history_hours is not None and min_required_hours is not None:
        if history_hours < min_required_hours:
            return MissingDataReason.INSUFFICIENT_HISTORY
    if (
        recent_hours is not None
        and min_feature_hours is not None
        and has_recent_telemetry
        and recent_hours < min_feature_hours
    ):
        return MissingDataReason.INSUFFICIENT_FEATURE_DATA
    return None


def check_source_completeness(
    telemetry_df: pd.DataFrame,
    eligible_gateways: Set[str],
    start_utc: Optional[dt.datetime | pd.Timestamp] = None,
    cutoff_utc: Optional[dt.datetime | pd.Timestamp] = None,
    expected_hours_per_gw: Optional[int] = None,
    threshold_absence_rate: float = 0.50,
) -> CompletenessResult:
    """Source-completeness guard ahead of feature scoring (Section 2B & v22).

    Inspects telemetry structure and dynamically derives expected hours per gateway
    from (cutoff_utc - start_utc) and declared hourly grain rather than hardcoding 168.

    Checks fleet-wide expected-vs-received telemetry coverage:
    - If fleet-wide absence rate exceeds threshold (default 0.50), returns
      CompletenessResult(False, absence_rate, details), tripping the pipeline into
      BLOCK_FEATURES state rather than interpreting an ingestion outage as individual failures.
    - Systemic absence (many missing) triggers BLOCK_FEATURES.
    - Individual gateway silence (1-2 silent out of fleet) does NOT trigger fleet BLOCK.
    """
    if not eligible_gateways:
        return CompletenessResult(True, 0.0, {"status": "HEALTHY", "reason": "No eligible gateways"})

    if "canonical_id" in telemetry_df.columns:
        id_col = "canonical_id"
    elif "gateway_id" in telemetry_df.columns:
        id_col = "gateway_id"
    else:
        return CompletenessResult(False, 1.0, {"status": "BLOCK_FEATURES", "reason": "Missing gateway identifier column"})

    # Dynamic derivation of expected hours per gateway
    if expected_hours_per_gw is None:
        if start_utc is not None and cutoff_utc is not None:
            s_ts = pd.to_datetime(start_utc, utc=True)
            c_ts = pd.to_datetime(cutoff_utc, utc=True)
            delta_sec = (c_ts - s_ts).total_seconds()
            expected_hours_per_gw = max(1, int(delta_sec // 3600))
        elif not telemetry_df.empty and "ts" in telemetry_df.columns:
            ts_min = telemetry_df["ts"].min()
            ts_max = telemetry_df["ts"].max()
            if pd.notna(ts_min) and pd.notna(ts_max):
                delta_sec = (pd.to_datetime(ts_max, utc=True) - pd.to_datetime(ts_min, utc=True)).total_seconds()
                expected_hours_per_gw = max(1, int(delta_sec // 3600) + 1)
            else:
                expected_hours_per_gw = 168
        else:
            expected_hours_per_gw = 168

    # 1. Gateway-level absence rate: eligible gateways with 0 telemetry rows in window
    observed_gateways = set(telemetry_df[id_col].unique())
    gateways_missing = eligible_gateways - observed_gateways
    gw_absence_rate = len(gateways_missing) / len(eligible_gateways)

    # 2. Record-level absence rate: total expected vs total received rows
    total_expected = len(eligible_gateways) * expected_hours_per_gw
    if total_expected > 0:
        eligible_mask = telemetry_df[id_col].isin(eligible_gateways)
        total_received = int(eligible_mask.sum())
        rec_absence_rate = max(0.0, (total_expected - total_received) / total_expected)
    else:
        total_received = 0
        rec_absence_rate = 0.0

    absence_rate = max(gw_absence_rate, rec_absence_rate)
    is_safe = absence_rate <= threshold_absence_rate
    status_str = "HEALTHY" if is_safe else "BLOCK_FEATURES"

    details = {
        "status": status_str,
        "eligible_gateways_count": len(eligible_gateways),
        "gateways_present_count": len(observed_gateways.intersection(eligible_gateways)),
        "gateways_missing_count": len(gateways_missing),
        "gw_absence_rate": gw_absence_rate,
        "expected_hours_per_gw": expected_hours_per_gw,
        "total_expected_records": total_expected,
        "total_received_records": total_received,
        "rec_absence_rate": rec_absence_rate,
        "threshold_absence_rate": threshold_absence_rate,
    }

    return CompletenessResult(is_safe, float(absence_rate), details)


def audit_gateway_telemetry_status(
    master_df: pd.DataFrame,
    telemetry_df: pd.DataFrame,
    monday: dt.date | str,
    start_utc: Optional[dt.datetime | pd.Timestamp] = None,
    min_history_days: int = 14,
    min_feature_hours: int = 24,
) -> pd.DataFrame:
    """Audit and classify missing-data reason taxonomy for each gateway in master_df.

    Frozen Taxonomy & Distinctions:
    - INELIGIBLE_DATE: Gateway decommissioned on or before Monday, or installed after Monday.
      Date-ineligible != No telemetry (never conflated).
    - NO_TELEMETRY: Date-eligible gateway with zero telemetry records across its history.
      Excluded from ranking; never receives an invented score.
    - INSUFFICIENT_HISTORY: Date-eligible gateway has telemetry, but total span < min_history_days.
    - INSUFFICIENT_FEATURE_DATA: Date-eligible gateway with sufficient history, but recent
      feature window has incomplete observations (< min_feature_hours) without complete silence.
    - ACTIVE: Date-eligible gateway with valid telemetry or recently silent (which is treated as
      a candidate risk feature 'recent_silence_ratio', NOT excluded).
    """
    from app.data.loader import get_gateway_eligibility, canonicalize_gateway_id

    # 1. Eligibility evaluation (Task 5)
    eligibility_df = get_gateway_eligibility(master_df, monday=monday)

    # 2. Canonical IDs and timestamp normalization in telemetry
    t_df = telemetry_df
    if not t_df.empty:
        if "canonical_id" not in t_df.columns and "gateway_id" in t_df.columns:
            t_df = t_df.copy()
            t_df["canonical_id"] = t_df["gateway_id"].apply(canonicalize_gateway_id)
        if "ts" not in t_df.columns and "ts_utc" in t_df.columns:
            t_df = t_df.copy()
            t_df["ts"] = pd.to_datetime(t_df["ts_utc"], utc=True, format="ISO8601")

    results = []
    for _, row in eligibility_df.iterrows():
        cid = row["canonical_id"]
        is_el = bool(row["is_eligible"])

        if not is_el:
            # Date-ineligible: decommissioned on/before Monday or installed after Monday
            results.append({
                "canonical_id": cid,
                "is_eligible": False,
                "status": "INELIGIBLE",
                "exclusion_reason": MissingDataReason.INELIGIBLE_DATE.value,
            })
            continue

        # For date-eligible gateway, inspect telemetry presence
        gw_tel = t_df[t_df["canonical_id"] == cid] if not t_df.empty else pd.DataFrame()

        if gw_tel.empty:
            # Zero telemetry ever: must be excluded with NO_TELEMETRY, never scored
            results.append({
                "canonical_id": cid,
                "is_eligible": True,
                "status": "EXCLUDED",
                "exclusion_reason": MissingDataReason.NO_TELEMETRY.value,
            })
            continue

        # Gateway has historical telemetry: check history span
        min_ts = gw_tel["ts"].min()
        max_ts = gw_tel["ts"].max()
        history_span_days = (max_ts - min_ts).total_seconds() / 86400.0

        if history_span_days < min_history_days:
            results.append({
                "canonical_id": cid,
                "is_eligible": True,
                "status": "EXCLUDED",
                "exclusion_reason": MissingDataReason.INSUFFICIENT_HISTORY.value,
            })
            continue

        # Check recent window if start_utc specified
        if start_utc is not None:
            s_ts = pd.to_datetime(start_utc, utc=True)
            recent_tel = gw_tel[gw_tel["ts"] >= s_ts]
            # If completely silent in recent window but has history -> NOT excluded with NO_TELEMETRY!
            # It remains ACTIVE and will be scored via recent_silence_ratio.
            # Only if it has partial/sparse corrupted feature data below min_feature_hours without complete silence:
            if 0 < len(recent_tel) < min_feature_hours:
                results.append({
                    "canonical_id": cid,
                    "is_eligible": True,
                    "status": "EXCLUDED",
                    "exclusion_reason": MissingDataReason.INSUFFICIENT_FEATURE_DATA.value,
                })
                continue

        results.append({
            "canonical_id": cid,
            "is_eligible": True,
            "status": "ACTIVE",
            "exclusion_reason": None,
        })

    return pd.DataFrame(results)

