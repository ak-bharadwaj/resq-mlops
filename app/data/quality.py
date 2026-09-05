"""Data quality audits, coverage analysis, and source-completeness guards."""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Set, Tuple
import pandas as pd
from app.data.schema import MissingDataReason


def classify_telemetry_status(
    has_any_historical_telemetry: bool,
    has_recent_telemetry: bool,
    history_hours: Optional[int] = None,
    min_required_hours: Optional[int] = None,
) -> Optional[MissingDataReason]:
    """Classify telemetry presence for an eligible gateway.

    Frozen Rules:
    - Zero telemetry across complete eligible history: NO_TELEMETRY exclusion. Never invent a score.
    - Below baseline history requirements (when history_hours and min_required_hours given): INSUFFICIENT_HISTORY exclusion.
    - A previously-reporting gateway that becomes recently silent: NOT a NO_TELEMETRY exclusion
      (surfaced as recent_silence_ratio risk feature in candidate model, not dropped).
    """
    if not has_any_historical_telemetry:
        return MissingDataReason.NO_TELEMETRY
    if history_hours is not None and min_required_hours is not None:
        if history_hours < min_required_hours:
            return MissingDataReason.INSUFFICIENT_HISTORY
    return None


def check_source_completeness(
    telemetry_df: pd.DataFrame,
    eligible_gateways: Set[str],
    expected_hours_per_gw: int = 168,
    threshold_absence_rate: float = 0.50,
) -> Tuple[bool, float]:
    """Source-completeness guard ahead of feature scoring (Section 2B & v22).

    Checks fleet-wide expected-vs-received telemetry coverage.
    If fleet-wide absence rate exceeds threshold, returns (False, absence_rate)
    which must trip prediction into BLOCK_FEATURES rather than reading a systemic
    pipeline outage as hundreds of individual gateway failures.
    """
    if not eligible_gateways:
        return True, 0.0

    if "canonical_id" in telemetry_df.columns:
        id_col = "canonical_id"
    elif "gateway_id" in telemetry_df.columns:
        id_col = "gateway_id"
    else:
        return False, 1.0

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
        rec_absence_rate = 0.0

    absence_rate = max(gw_absence_rate, rec_absence_rate)
    is_safe = absence_rate <= threshold_absence_rate
    return is_safe, float(absence_rate)
