"""Dedicated unit tests for Task 10 Fleet-Wide Telemetry Completeness Guard."""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.quality import CompletenessResult, check_source_completeness
from app.data.loader import get_gateway_eligibility, load_gateway_master, load_telemetry_window


def test_synthetic_fleet_breach_trips_block_features():
    """Verify fleet-wide absence rate > 50% returns is_safe=False and status=BLOCK_FEATURES."""
    eligible = {f"0639EA5602{i:02d}" for i in range(10)}  # 10 gateways
    # Only 2 gateways present (80% missing gateways)
    telemetry_df = pd.DataFrame([
        {"canonical_id": "0639EA560200", "ts": pd.Timestamp("2026-02-01 00:00:00", tz="UTC")},
        {"canonical_id": "0639EA560201", "ts": pd.Timestamp("2026-02-01 00:00:00", tz="UTC")},
    ])
    result = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible,
        expected_hours_per_gw=24,
        threshold_absence_rate=0.50,
    )
    assert result.is_safe is False
    assert result[0] is False  # Unpacking compatibility
    assert result.absence_rate >= 0.80
    assert result.details["status"] == "BLOCK_FEATURES"


def test_synthetic_fleet_healthy_case_passes():
    """Verify healthy fleet (100% present) returns is_safe=True and status=HEALTHY."""
    eligible = {f"0639EA5602{i:02d}" for i in range(5)}
    rows = []
    for gw in eligible:
        for h in range(24):
            rows.append({"canonical_id": gw, "ts": pd.Timestamp(f"2026-02-01 {h:02d}:00:00", tz="UTC")})
    telemetry_df = pd.DataFrame(rows)

    start_utc = pd.Timestamp("2026-02-01 00:00:00", tz="UTC")
    cutoff_utc = pd.Timestamp("2026-02-02 00:00:00", tz="UTC")

    result = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
    )
    assert result.is_safe is True
    assert result.absence_rate == 0.0
    assert result.details["status"] == "HEALTHY"


def test_individual_missing_gateway_does_not_falsely_trigger_fleet_block():
    """Verify 1 silent gateway out of 290 eligible gateways does NOT trip fleet BLOCK_FEATURES."""
    # 290 eligible gateways
    eligible = {f"0639EA56{i:04d}" for i in range(290)}
    # 289 gateways have full 168 hours of data; exactly 1 is completely missing
    silent_gw = "0639EA560000"
    reporting_gateways = eligible - {silent_gw}

    # Simulate presence
    rows = [{"canonical_id": gw} for gw in reporting_gateways for _ in range(168)]
    telemetry_df = pd.DataFrame(rows)

    result = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible,
        expected_hours_per_gw=168,
        threshold_absence_rate=0.50,
    )
    # Fleet is HEALTHY because absence rate is 1/290 = 0.34% << 50%
    assert result.is_safe is True
    assert result.absence_rate < 0.01
    assert result.details["status"] == "HEALTHY"
    assert result.details["gateways_missing_count"] == 1


def test_dynamic_expected_hours_derivation_across_windows():
    """Verify expected hours is dynamically derived from time window rather than hardcoded 168."""
    eligible = {"0639EA560201"}

    # 1. 24-hour window
    start_24 = pd.Timestamp("2026-02-01 00:00:00", tz="UTC")
    cutoff_24 = pd.Timestamp("2026-02-02 00:00:00", tz="UTC")
    res_24 = check_source_completeness(
        pd.DataFrame([{"canonical_id": "0639EA560201"} for _ in range(24)]),
        eligible_gateways=eligible,
        start_utc=start_24,
        cutoff_utc=cutoff_24,
    )
    assert res_24.details["expected_hours_per_gw"] == 24
    assert res_24.absence_rate == 0.0

    # 2. 72-hour window
    start_72 = pd.Timestamp("2026-01-30 00:00:00", tz="UTC")
    cutoff_72 = pd.Timestamp("2026-02-02 00:00:00", tz="UTC")
    res_72 = check_source_completeness(
        pd.DataFrame([{"canonical_id": "0639EA560201"} for _ in range(72)]),
        eligible_gateways=eligible,
        start_utc=start_72,
        cutoff_utc=cutoff_72,
    )
    assert res_72.details["expected_hours_per_gw"] == 72
    assert res_72.absence_rate == 0.0

    # 3. 168-hour (7-day) window
    start_168 = pd.Timestamp("2026-01-26 00:00:00", tz="UTC")
    cutoff_168 = pd.Timestamp("2026-02-02 00:00:00", tz="UTC")
    res_168 = check_source_completeness(
        pd.DataFrame([{"canonical_id": "0639EA560201"} for _ in range(168)]),
        eligible_gateways=eligible,
        start_utc=start_168,
        cutoff_utc=cutoff_168,
    )
    assert res_168.details["expected_hours_per_gw"] == 168
    assert res_168.absence_rate == 0.0


def test_pre_feature_execution_guard_blocks_downstream_computation():
    """Verify pre-feature execution flow halts safely when completeness guard trips."""
    eligible = {"0639EA560201", "0639EA560202", "0639EA560203", "0639EA560204"}
    # Systemic outage: empty telemetry
    empty_telemetry = pd.DataFrame()

    res = check_source_completeness(
        empty_telemetry,
        eligible_gateways=eligible,
        start_utc=pd.Timestamp("2026-01-26 00:00:00", tz="UTC"),
        cutoff_utc=pd.Timestamp("2026-02-02 00:00:00", tz="UTC"),
    )

    feature_construction_executed = False
    if res.is_safe:
        feature_construction_executed = True

    assert feature_construction_executed is False, "Feature extraction must be halted in BLOCK_FEATURES state"


def test_real_data_source_completeness_audit():
    """Verify completeness guard on real workspace data."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("data/ not present in workspace")

    master_df = load_gateway_master(data_dir)
    eligibility_df = get_gateway_eligibility(master_df, monday=dt.date(2026, 2, 2))
    eligible_gateways = set(eligibility_df.loc[eligibility_df["is_eligible"], "canonical_id"])
    assert len(eligible_gateways) == 290

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=7)
    telemetry_df = load_telemetry_window(data_dir, cutoff_utc=cutoff_utc, start_utc=start_utc)

    result = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible_gateways,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
    )
    # Real data for week 2026-02-02 must be healthy
    assert result.is_safe is True
    assert result.details["status"] == "HEALTHY"
    assert result.details["expected_hours_per_gw"] == 168
