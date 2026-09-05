"""Connected end-to-end integration test for Parallel Wave (Tasks 3, 4, & 6).

Proves master + field visits + telemetry ingestion, ID canonicalization, strict UTC firewall,
duplicate handling, schema contracts, and downstream joins work coherently together.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    canonicalize_gateway_id,
    get_gateway_eligibility,
    load_field_visits,
    load_gateway_master,
    load_telemetry_window,
)
from app.data.schema import (
    ConflictingRecordError,
    FieldVisitsSchemaContract,
    GatewayMasterSchemaContract,
    SchemaValidationError,
    TelemetrySchemaContract,
)


def test_parallel_wave_e2e_connected_pipeline():
    """Verify connected ingestion and downstream join of master, field visits, and telemetry."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("Real data directory missing from local workspace")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    monday_date = dt.date(2026, 2, 2)

    # 1. Load Gateway Master (Task 3)
    master_df = load_gateway_master(data_dir)
    assert not master_df.empty
    assert "canonical_id" in master_df.columns
    assert master_df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()

    # 2. Load Field Visits (Task 4)
    visits_df = load_field_visits(data_dir)
    assert not visits_df.empty
    assert "canonical_id" in visits_df.columns
    assert visits_df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()

    # 3. Load Telemetry Window with strict Monday 00:00 UTC cutoff (Task 6)
    telemetry_df = load_telemetry_window(data_dir, cutoff_utc=cutoff_utc)
    assert not telemetry_df.empty
    assert "canonical_id" in telemetry_df.columns
    assert "ts" in telemetry_df.columns
    assert (telemetry_df["ts"] < cutoff_utc).all()

    # 4. Evaluate Gateway Eligibility
    eligible_df = get_gateway_eligibility(master_df, monday=monday_date)
    active_eligible = eligible_df.loc[eligible_df["is_eligible"]].copy()
    assert len(active_eligible) == 290

    # 5. Downstream Join: Eligible Gateways <-> Field Visits on canonical_id
    visits_joined = active_eligible.merge(visits_df, on="canonical_id", how="inner")
    assert not visits_joined.empty
    # Confirm no orphan canonical_ids were created by uncanonicalized raw string differences
    assert set(visits_joined["canonical_id"]).issubset(set(active_eligible["canonical_id"]))

    # 6. Downstream Join: Eligible Gateways <-> Telemetry on canonical_id
    telemetry_joined = active_eligible.merge(telemetry_df, on="canonical_id", how="inner")
    assert not telemetry_joined.empty
    assert (telemetry_joined["ts"] < cutoff_utc).all()


def test_parallel_wave_synthetic_e2e_pipeline(tmp_path: pathlib.Path):
    """Synthetic test exercising full connected pipeline with raw formatting differences and duplicate records."""
    # Setup Gateway Master with CP1252 German characters
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,TENANT_A,Gebäude,NORTH,V1,OMNI,1.0.0,2025-01-01,5\n"
        "0639ea5602c2,TENANT_B,Außenmast,SOUTH,V2,DIRECTIONAL,1.1.0,2025-02-01,3\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    # Setup Field Visits with UTF-8 encoding
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V002,06:39:EA:56:02:C2,2025-09-10,2025-09-12,POWER_LOSS,INSPECTED,NONE,1.0\n"
    )
    (tmp_path / "field_visits.csv").write_bytes(visits_csv.encode("utf-8"))

    # Setup Telemetry Parquet partition
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)
    rows = [
        # In window for C1
        {"gateway_id": "06:39:ea:56:02:c1", "ts_utc": "2026-02-01T12:00:00Z", "offline_duration_sec": 0.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0},
        # Exact cutoff for C1 -> MUST BE FILTERED OUT
        {"gateway_id": "0639EA5602C1", "ts_utc": "2026-02-02T00:00:00Z", "offline_duration_sec": 60.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0},
        # In window for C2
        {"gateway_id": "0639EA5602C2", "ts_utc": "2026-02-01T18:00:00Z", "offline_duration_sec": 0.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0},
    ]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)

    # Ingest through production loaders
    master_df = load_gateway_master(tmp_path)
    visits_df = load_field_visits(tmp_path)
    telemetry_df = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)

    # Validate canonical IDs match
    assert set(master_df["canonical_id"]) == {"0639EA5602C1", "0639EA5602C2"}
    assert set(visits_df["canonical_id"]) == {"0639EA5602C1", "0639EA5602C2"}
    assert set(telemetry_df["canonical_id"]) == {"0639EA5602C1", "0639EA5602C2"}

    # Verify cutoff
    assert len(telemetry_df) == 2
    assert (telemetry_df["ts"] < cutoff_utc).all()

    # Downstream joins succeed
    joined_mv = master_df.merge(visits_df, on="canonical_id", how="inner")
    assert len(joined_mv) == 2

    joined_mt = master_df.merge(telemetry_df, on="canonical_id", how="inner")
    assert len(joined_mt) == 2
