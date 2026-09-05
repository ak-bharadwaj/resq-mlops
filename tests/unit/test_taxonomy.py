"""Dedicated unit and anti-confusion tests for Task 9 Missing-Data Reason Taxonomy."""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.schema import MissingDataReason
from app.data.quality import audit_gateway_telemetry_status, classify_telemetry_status
from app.data.loader import load_gateway_master, load_telemetry_window


def test_taxonomy_codes_strictly_distinct():
    """Verify all 5 required reason codes are distinct and strictly defined."""
    required = {
        MissingDataReason.NO_TELEMETRY,
        MissingDataReason.INSUFFICIENT_HISTORY,
        MissingDataReason.INSUFFICIENT_FEATURE_DATA,
        MissingDataReason.INELIGIBLE_DATE,
        MissingDataReason.SCHEMA_INVALID,
    }
    assert len(required) == 5
    for r in required:
        assert isinstance(r.value, str)
        assert len(r.value) > 0


def test_anti_confusion_date_ineligible_vs_no_telemetry():
    """Prove date-ineligible gateways receive INELIGIBLE_DATE, never NO_TELEMETRY."""
    # Gateway not yet installed on Monday
    master_df = pd.DataFrame([
        {
            "gateway_id": "0639EA560201",
            "canonical_id": "0639EA560201",
            "installed_on": dt.date(2026, 3, 1),  # Installed after Monday
            "decommissioned_on": None,
        },
        {
            "gateway_id": "0639EA560202",
            "canonical_id": "0639EA560202",
            "installed_on": dt.date(2020, 1, 1),
            "decommissioned_on": dt.date(2026, 1, 15),  # Decommissioned before Monday
        },
    ])
    empty_telemetry = pd.DataFrame()
    monday = dt.date(2026, 2, 2)

    status_df = audit_gateway_telemetry_status(master_df, empty_telemetry, monday=monday)
    assert len(status_df) == 2
    assert (status_df["is_eligible"] == False).all()
    assert (status_df["status"] == "INELIGIBLE").all()
    # Crucial invariant: never falsely labeled as NO_TELEMETRY
    assert (status_df["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value).all()
    assert not (status_df["exclusion_reason"] == MissingDataReason.NO_TELEMETRY.value).any()


def test_anti_confusion_zero_telemetry_vs_recently_silent():
    """Prove zero telemetry ever (excluded) is distinct from recently silent with history (active)."""
    master_df = pd.DataFrame([
        {
            "gateway_id": "0639EA560201",
            "canonical_id": "0639EA560201",
            "installed_on": dt.date(2020, 1, 1),
            "decommissioned_on": None,
        },
        {
            "gateway_id": "0639EA560202",
            "canonical_id": "0639EA560202",
            "installed_on": dt.date(2020, 1, 1),
            "decommissioned_on": None,
        },
    ])
    # 0639EA560201 has 30 days history, but 0 rows in the last 7 days (recently silent)
    # 0639EA560202 has 0 rows ever
    history_rows = [
        {"canonical_id": "0639EA560201", "ts": pd.Timestamp("2026-01-01 12:00:00", tz="UTC")},
        {"canonical_id": "0639EA560201", "ts": pd.Timestamp("2026-01-20 12:00:00", tz="UTC")},
    ]
    telemetry_df = pd.DataFrame(history_rows)

    monday = dt.date(2026, 2, 2)
    start_utc = pd.Timestamp("2026-01-26 00:00:00", tz="UTC")

    status_df = audit_gateway_telemetry_status(
        master_df,
        telemetry_df,
        monday=monday,
        start_utc=start_utc,
        min_history_days=14,
    )

    # Gateway with zero telemetry ever: must be EXCLUDED with NO_TELEMETRY
    gw2 = status_df[status_df["canonical_id"] == "0639EA560202"].iloc[0]
    assert bool(gw2["is_eligible"]) is True
    assert gw2["status"] == "EXCLUDED"
    assert gw2["exclusion_reason"] == MissingDataReason.NO_TELEMETRY.value

    # Gateway with history that went silent: NOT EXCLUDED with NO_TELEMETRY!
    # Stays ACTIVE so recent_silence_ratio can be computed as a risk signal
    gw1 = status_df[status_df["canonical_id"] == "0639EA560201"].iloc[0]
    assert bool(gw1["is_eligible"]) is True
    assert gw1["status"] == "ACTIVE"
    assert pd.isna(gw1["exclusion_reason"]) or gw1["exclusion_reason"] is None


def test_anti_confusion_insufficient_history_vs_feature_data():
    """Prove insufficient baseline history (< 14 days) is distinct from sparse feature window."""
    master_df = pd.DataFrame([
        {
            "gateway_id": "0639EA560201",
            "canonical_id": "0639EA560201",
            "installed_on": dt.date(2020, 1, 1),
            "decommissioned_on": None,
        },
        {
            "gateway_id": "0639EA560202",
            "canonical_id": "0639EA560202",
            "installed_on": dt.date(2020, 1, 1),
            "decommissioned_on": None,
        },
    ])
    # 0639EA560201 has only 3 days history (< 14 days)
    # 0639EA560202 has 60 days history, but recent window has only 5 hours (< 24 min_feature_hours)
    rows = [
        # Short history for 201
        {"canonical_id": "0639EA560201", "ts": pd.Timestamp("2026-01-20 12:00:00", tz="UTC")},
        {"canonical_id": "0639EA560201", "ts": pd.Timestamp("2026-01-23 12:00:00", tz="UTC")},
        # Long history for 202
        {"canonical_id": "0639EA560202", "ts": pd.Timestamp("2025-11-01 12:00:00", tz="UTC")},
        {"canonical_id": "0639EA560202", "ts": pd.Timestamp("2026-01-30 12:00:00", tz="UTC")},
        {"canonical_id": "0639EA560202", "ts": pd.Timestamp("2026-01-31 12:00:00", tz="UTC")},
    ]
    telemetry_df = pd.DataFrame(rows)

    monday = dt.date(2026, 2, 2)
    start_utc = pd.Timestamp("2026-01-26 00:00:00", tz="UTC")

    status_df = audit_gateway_telemetry_status(
        master_df,
        telemetry_df,
        monday=monday,
        start_utc=start_utc,
        min_history_days=14,
        min_feature_hours=24,
    )

    gw1 = status_df[status_df["canonical_id"] == "0639EA560201"].iloc[0]
    assert gw1["status"] == "EXCLUDED"
    assert gw1["exclusion_reason"] == MissingDataReason.INSUFFICIENT_HISTORY.value

    gw2 = status_df[status_df["canonical_id"] == "0639EA560202"].iloc[0]
    assert gw2["status"] == "EXCLUDED"
    assert gw2["exclusion_reason"] == MissingDataReason.INSUFFICIENT_FEATURE_DATA.value


def test_zero_telemetry_never_receives_invented_score():
    """Verify eligible gateway with zero telemetry is excluded and never given an invented score."""
    master_df = pd.DataFrame([{
        "gateway_id": "0639EA560201",
        "canonical_id": "0639EA560201",
        "installed_on": dt.date(2020, 1, 1),
        "decommissioned_on": None,
    }])
    status_df = audit_gateway_telemetry_status(master_df, pd.DataFrame(), monday="2026-02-02")
    assert status_df.iloc[0]["status"] == "EXCLUDED"
    assert status_df.iloc[0]["exclusion_reason"] == MissingDataReason.NO_TELEMETRY.value

    # Simulate ranking filter: excluded gateways must not enter score list
    active_gateways = status_df[status_df["status"] == "ACTIVE"]
    assert len(active_gateways) == 0, "Zero telemetry gateway must never enter active ranking population"


def test_real_data_taxonomy_audit():
    """Verify taxonomy categorization on real workspace data."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("data/ not present in workspace")

    master_df = load_gateway_master(data_dir)
    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=7)
    telemetry_df = load_telemetry_window(data_dir, cutoff_utc=cutoff_utc, start_utc=start_utc)

    status_df = audit_gateway_telemetry_status(
        master_df,
        telemetry_df,
        monday=dt.date(2026, 2, 2),
        start_utc=start_utc,
    )

    assert len(status_df) == 332
    # Exactly 42 gateways are date-ineligible on 2026-02-02
    ineligible = status_df[status_df["status"] == "INELIGIBLE"]
    assert len(ineligible) == 42
    assert (ineligible["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value).all()

    # 290 are date-eligible
    eligible = status_df[status_df["is_eligible"] == True]
    assert len(eligible) == 290
