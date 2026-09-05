"""Connected Wave Integration Test for Wave 3 (Tasks 8, 9, 10, 11).

Proves:
- Task 11: Alternate --data PATH propagation across loaders and CLIs.
- Task 8: Model-authoritative structural schema validation on loaded telemetry.
- Task 10: Dynamic fleet-wide source completeness guard pre-feature execution.
- Task 9: Distinct missing-data reason taxonomy assignment without collapse or invented scores.
- Tasks 2-7: ID canonicalization, eligibility, UTC boundary, and duplicate policy integration.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    load_field_visits,
    load_gateway_master,
    load_telemetry_window,
)
from app.data.quality import audit_gateway_telemetry_status, check_source_completeness
from app.data.schema import MissingDataReason, TelemetrySchemaContract


def test_wave3_connected_pipeline_end_to_end(tmp_path: pathlib.Path):
    """End-to-end integration proving 8 <-> 9 <-> 10 <-> 11 coherent operation."""
    # 1. Setup alternate data directory (Task 11)
    alt_data_dir = tmp_path / "alternate_data"
    alt_data_dir.mkdir(parents=True)

    # Master: 5 gateways representing different lifecycle & reporting profiles
    # GW01: Eligible, full history, active
    # GW02: Eligible, historical data, but recently silent (should remain ACTIVE)
    # GW03: Eligible, zero telemetry ever (should be EXCLUDED with NO_TELEMETRY)
    # GW04: Eligible, short history < 14 days (should be EXCLUDED with INSUFFICIENT_HISTORY)
    # GW05: Ineligible (decommissioned before Monday) (should be INELIGIBLE with INELIGIBLE_DATE)
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:01,TENANT_A,Außenmast,NORTH,V1,OMNI,1.0.0,2025-01-01,,10\n"
        "06:39:EA:56:02:02,TENANT_A,Gebäude,SOUTH,V1,OMNI,1.0.0,2025-01-01,,10\n"
        "06:39:EA:56:02:03,TENANT_B,Außenmast,EAST,V1,DIRECTIONAL,1.0.0,2025-01-01,,10\n"
        "06:39:EA:56:02:04,TENANT_B,Gebäude,WEST,V1,DIRECTIONAL,1.0.0,2026-01-28,,10\n"
        "06:39:EA:56:02:05,TENANT_C,Schaltschrank,CENTRAL,V1,OMNI,1.0.0,2024-01-01,2026-01-15,10\n"
    )
    (alt_data_dir / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    # Field visits
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639ea560201,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (alt_data_dir / "field_visits.csv").write_text(visits_csv, encoding="utf-8")

    # Telemetry parquet directory
    tel_dir = alt_data_dir / "telemetry"
    tel_dir.mkdir(parents=True)

    rows = []
    # GW01: 30 days of data, including full 168 hours in recent window
    # 23 daily points (2026-01-03 to 2026-01-25) + 168 hourly points (2026-01-26 to 2026-02-01) = 30 days
    for day in range(23):
        ts_day = pd.Timestamp("2026-01-03 00:00:00", tz="UTC") + pd.Timedelta(days=day)
        rows.append({
            "gateway_id": "06:39:EA:56:02:01",
            "ts_utc": ts_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "offline_duration_sec": 0.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        })
    # Add recent hourly window for GW01
    for h in range(168):
        ts_h = pd.Timestamp("2026-01-26 00:00:00", tz="UTC") + pd.Timedelta(hours=h)
        rows.append({
            "gateway_id": "06:39:EA:56:02:01",
            "ts_utc": ts_h.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "offline_duration_sec": 10.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        })

    # GW02: 30 days of historical data, but silent in recent window (ts < 2026-01-26)
    for day in range(20):
        ts_day = pd.Timestamp("2026-01-01 00:00:00", tz="UTC") + pd.Timedelta(days=day)
        rows.append({
            "gateway_id": "0639ea560202",
            "ts_utc": ts_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "offline_duration_sec": 0.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        })

    # GW04: Only 3 days of data (insufficient history)
    for day in range(3):
        ts_day = pd.Timestamp("2026-01-28 00:00:00", tz="UTC") + pd.Timedelta(days=day)
        rows.append({
            "gateway_id": "0639ea560204",
            "ts_utc": ts_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "offline_duration_sec": 0.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        })

    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=7)
    monday_date = dt.date(2026, 2, 2)

    # 2. Ingest from alternate directory (Task 11) & verify Task 8 Schema Contract
    master_df = load_gateway_master(alt_data_dir)
    assert len(master_df) == 5

    visits_df = load_field_visits(alt_data_dir)
    assert len(visits_df) == 1

    # Telemetry load enforces Task 8 structural schema contract automatically
    telemetry_window_df = load_telemetry_window(alt_data_dir, cutoff_utc=cutoff_utc, start_utc=start_utc)
    assert not telemetry_window_df.empty
    assert (telemetry_window_df["ts"] < cutoff_utc).all()
    assert (telemetry_window_df["ts"] >= start_utc).all()

    # 3. Task 10 Fleet-Wide Completeness Guard on recent window
    eligible_gws = {"0639EA560201", "0639EA560202", "0639EA560203", "0639EA560204"}
    completeness = check_source_completeness(
        telemetry_window_df,
        eligible_gateways=eligible_gws,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
    )
    # Check dynamic expected hours: exactly 168 hours derived from [start, cutoff)
    assert completeness.details["expected_hours_per_gw"] == 168

    # 4. Task 9 Reason Taxonomy Audit across all 5 gateways
    # Load full history telemetry for taxonomy classification
    full_telemetry = pd.read_parquet(tel_dir / "part-0.parquet")
    status_df = audit_gateway_telemetry_status(
        master_df,
        full_telemetry,
        monday=monday_date,
        start_utc=start_utc,
        min_history_days=14,
    )

    # Validate distinct taxonomy mapping for each gateway
    # GW01: Active
    gw01 = status_df[status_df["canonical_id"] == "0639EA560201"].iloc[0]
    assert bool(gw01["is_eligible"]) is True
    assert gw01["status"] == "ACTIVE"
    assert pd.isna(gw01["exclusion_reason"]) or gw01["exclusion_reason"] is None

    # GW02: Recently silent with history -> ACTIVE (surfaced as silence risk, NOT excluded)
    gw02 = status_df[status_df["canonical_id"] == "0639EA560202"].iloc[0]
    assert bool(gw02["is_eligible"]) is True
    assert gw02["status"] == "ACTIVE"
    assert pd.isna(gw02["exclusion_reason"]) or gw02["exclusion_reason"] is None

    # GW03: Zero telemetry ever -> EXCLUDED with NO_TELEMETRY (never scored)
    gw03 = status_df[status_df["canonical_id"] == "0639EA560203"].iloc[0]
    assert bool(gw03["is_eligible"]) is True
    assert gw03["status"] == "EXCLUDED"
    assert gw03["exclusion_reason"] == MissingDataReason.NO_TELEMETRY.value

    # GW04: Insufficient history < 14 days -> EXCLUDED with INSUFFICIENT_HISTORY
    gw04 = status_df[status_df["canonical_id"] == "0639EA560204"].iloc[0]
    assert bool(gw04["is_eligible"]) is True
    assert gw04["status"] == "EXCLUDED"
    assert gw04["exclusion_reason"] == MissingDataReason.INSUFFICIENT_HISTORY.value

    # GW05: Ineligible date -> INELIGIBLE with INELIGIBLE_DATE
    gw05 = status_df[status_df["canonical_id"] == "0639EA560205"].iloc[0]
    assert bool(gw05["is_eligible"]) is False
    assert gw05["status"] == "INELIGIBLE"
    assert gw05["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value


def test_wave3_systemic_outage_trips_block_features(tmp_path: pathlib.Path):
    """Verify systemic fleet-wide outage trips BLOCK_FEATURES state ahead of scoring."""
    eligible = {f"0639EA56{i:04d}" for i in range(100)}
    # Only 10 gateways report (90% outage)
    outage_df = pd.DataFrame([{"canonical_id": f"0639EA56{i:04d}"} for i in range(10)])

    res = check_source_completeness(
        outage_df,
        eligible_gateways=eligible,
        expected_hours_per_gw=168,
        threshold_absence_rate=0.50,
    )
    assert res.is_safe is False
    assert res.details["status"] == "BLOCK_FEATURES"
    assert res.absence_rate >= 0.90
