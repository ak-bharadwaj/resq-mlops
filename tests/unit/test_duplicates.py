"""Comprehensive unit and integration tests for Task 7 Duplicate-Record Policy.

Tests frozen policy across all three ingestion paths:
1. Exact / Equivalent duplicate:
   - Deterministic deduplication (keep first occurrence)
   - Structured logging via logger.info with source and count
2. Same logical key + Conflicting values:
   - BLOCK by raising ConflictingRecordError
   - Anti-silent-selection: never pick first, last, or average
3. Connected pipeline integration and real-data verification.
"""
from __future__ import annotations

import datetime as dt
import logging
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    canonicalize_gateway_id,
    enforce_duplicate_policy,
    get_gateway_eligibility,
    load_field_visits,
    load_gateway_master,
    load_telemetry_window,
    resolve_telemetry_duplicates,
)
from app.data.schema import ConflictingRecordError


# ---------------------------------------------------------------------------
# 1. Base enforce_duplicate_policy unit tests
# ---------------------------------------------------------------------------

def test_duplicate_policy_empty_dataframe():
    """Verify empty DataFrame returns empty DataFrame and 0 count without errors."""
    df = pd.DataFrame()
    res, count = enforce_duplicate_policy(df, key_cols=["canonical_id"])
    assert res.empty
    assert count == 0


def test_duplicate_policy_no_duplicates_emits_no_logs(caplog: pytest.LogCaptureFixture):
    """Verify that when no duplicates exist, no duplicate log messages are emitted."""
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "site_type": "Mast", "val": 1},
        {"canonical_id": "0639EA560202", "site_type": "Dach", "val": 2},
    ])
    with caplog.at_level(logging.INFO):
        deduped, count = enforce_duplicate_policy(df, key_cols=["canonical_id"], source_name="test_clean")
    assert count == 0
    assert len(deduped) == 2
    assert not any("Duplicate policy" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 2. Gateway Master Ingestion Path
# ---------------------------------------------------------------------------

def test_master_exact_duplicates_collapse_and_log(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """Verify exact duplicate rows in gateway_master.csv collapse deterministically with logging."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(csv_content.encode("cp1252"))

    with caplog.at_level(logging.INFO):
        df = load_gateway_master(tmp_path)

    assert len(df) == 1
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert any("Duplicate policy [gateway_master]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_master_equivalent_raw_ids_collapse_and_log(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """Verify equivalent raw gateway_id representations collapse deterministically with logging."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
        "0639ea5602c1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(csv_content.encode("cp1252"))

    with caplog.at_level(logging.INFO):
        df = load_gateway_master(tmp_path)

    assert len(df) == 1
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert any("Duplicate policy [gateway_master]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_master_conflicting_attributes_raise_conflicting_record_error(tmp_path: pathlib.Path):
    """Verify conflicting master attributes for same canonical ID raise ConflictingRecordError (BLOCK)."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
        "0639EA5602C1,tenant_b,Gebäude,Region_2,Modell_B,Directional,v2.0,2021-01-01,200\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(ConflictingRecordError, match="Conflicting master records detected"):
        load_gateway_master(tmp_path)


def test_master_conflicting_meters_blocks_ingestion(tmp_path: pathlib.Path):
    """Verify conflicting n_meters_installed for same canonical ID raises ConflictingRecordError."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,100\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,2020-01-01,250\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(ConflictingRecordError, match="Conflicting master records detected"):
        load_gateway_master(tmp_path)


# ---------------------------------------------------------------------------
# 3. Field Visits Ingestion Path
# ---------------------------------------------------------------------------

def test_field_visits_exact_duplicates_collapse_and_log(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """Verify exact duplicate rows in field_visits.csv collapse deterministically with logging."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (tmp_path / "field_visits.csv").write_text(csv_content, encoding="utf-8")

    with caplog.at_level(logging.INFO):
        df = load_field_visits(tmp_path)

    assert len(df) == 1
    assert df.loc[0, "visit_id"] == "V001"
    assert any("Duplicate policy [field_visits]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_field_visits_equivalent_duplicates_collapse_and_log(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """Verify equivalent duplicate visits differing only in raw gateway_id formatting collapse with logging."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (tmp_path / "field_visits.csv").write_text(csv_content, encoding="utf-8")

    with caplog.at_level(logging.INFO):
        df = load_field_visits(tmp_path)

    assert len(df) == 1
    assert df.loc[0, "visit_id"] == "V001"
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert any("Duplicate policy [field_visits]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_field_visits_conflicting_visit_id_raises_conflicting_record_error(tmp_path: pathlib.Path):
    """Verify conflicting records sharing visit_id raise ConflictingRecordError (BLOCK)."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,COMM_FAULT,NO_FAULT_FOUND,NONE,1.0\n"
    )
    (tmp_path / "field_visits.csv").write_text(csv_content, encoding="utf-8")

    with pytest.raises(ConflictingRecordError, match="Conflicting visit records detected"):
        load_field_visits(tmp_path)


def test_field_visits_conflicting_gateway_for_same_visit_id_blocks(tmp_path: pathlib.Path):
    """Verify same visit_id referencing different gateway IDs raises ConflictingRecordError."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639EA560201,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639EA560202,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (tmp_path / "field_visits.csv").write_text(csv_content, encoding="utf-8")

    with pytest.raises(ConflictingRecordError, match="Conflicting visit records detected"):
        load_field_visits(tmp_path)


# ---------------------------------------------------------------------------
# 4. Telemetry Ingestion Path
# ---------------------------------------------------------------------------

def test_telemetry_exact_duplicates_collapse_and_log(caplog: pytest.LogCaptureFixture):
    """Verify exact duplicate telemetry rows collapse deterministically with logging."""
    ts = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 10.0, "val2": 5},
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 10.0, "val2": 5},
        {"canonical_id": "0639EA560202", "ts": ts, "val1": 20.0, "val2": 8},
    ])

    with caplog.at_level(logging.INFO):
        deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])

    assert dup_count == 1
    assert len(deduped) == 2
    assert list(deduped["canonical_id"]) == ["0639EA560201", "0639EA560202"]
    assert any("Duplicate policy [telemetry]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_telemetry_equivalent_raw_formatting_collapses_and_logs(caplog: pytest.LogCaptureFixture):
    """Verify equivalent telemetry with raw gateway_id and ts_utc formatting variations collapses with logging."""
    df = pd.DataFrame([
        {
            "gateway_id": "06:39:EA:56:02:01",
            "ts_utc": "2026-01-01T12:00:00Z",
            "offline_duration_sec": 120.0,
            "disconnection_cnt": 2,
        },
        {
            "gateway_id": "0639ea560201",
            "ts_utc": "2026-01-01 12:00:00+00:00",
            "offline_duration_sec": 120.0,
            "disconnection_cnt": 2,
        },
    ])

    with caplog.at_level(logging.INFO):
        deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])

    assert dup_count == 1
    assert len(deduped) == 1
    assert deduped["canonical_id"].iloc[0] == "0639EA560201"
    assert any("Duplicate policy [telemetry]: deterministically deduplicated 1" in r.message for r in caplog.records)


def test_telemetry_conflicting_measurements_raise_conflicting_record_error():
    """Verify conflicting telemetry measurements for same (canonical_id, ts) raise ConflictingRecordError."""
    ts = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts, "offline_duration_sec": 10.0},
        {"canonical_id": "0639EA560201", "ts": ts, "offline_duration_sec": 99.0},
    ])

    with pytest.raises(ConflictingRecordError, match="Conflicting telemetry records detected"):
        resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])


def test_telemetry_conflicting_multiple_timestamps_reports_sample():
    """Verify multiple conflicting timestamps report conflicting key samples in exception message."""
    ts1 = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    ts2 = pd.Timestamp("2026-01-01 13:00:00", tz="UTC")
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts1, "val": 10.0},
        {"canonical_id": "0639EA560201", "ts": ts1, "val": 20.0},
        {"canonical_id": "0639EA560202", "ts": ts2, "val": 30.0},
        {"canonical_id": "0639EA560202", "ts": ts2, "val": 40.0},
    ])

    with pytest.raises(ConflictingRecordError) as exc_info:
        resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])

    assert "Conflicting telemetry records detected" in str(exc_info.value)
    assert "0639EA560201" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Anti-Silent-Selection & Defensive Invariants
# ---------------------------------------------------------------------------

def test_anti_silent_selection_never_picks_arbitrary_winner_or_averages():
    """Verify conflicting records unconditionally BLOCK and never silently select first/last or average values."""
    df_conflict = pd.DataFrame([
        {"canonical_id": "0639EA560201", "site_type": "Mast", "n_meters_installed": 10},
        {"canonical_id": "0639EA560201", "site_type": "Mast", "n_meters_installed": 20},
    ])

    # 1. Unconditional raise: neither first (10), last (20), nor mean (15) is silently returned
    with pytest.raises(ConflictingRecordError):
        enforce_duplicate_policy(df_conflict, key_cols=["canonical_id"], source_name="test_policy")

    # 2. Verify that any implementation attempting silent first/last selection would fail this assertion
    first_choice = df_conflict.drop_duplicates(subset=["canonical_id"], keep="first")
    last_choice = df_conflict.drop_duplicates(subset=["canonical_id"], keep="last")
    mean_meters = df_conflict.groupby("canonical_id")["n_meters_installed"].mean().iloc[0]

    assert len(first_choice) == 1 and first_choice["n_meters_installed"].iloc[0] == 10
    assert len(last_choice) == 1 and last_choice["n_meters_installed"].iloc[0] == 20
    assert mean_meters == 15.0
    # Because enforce_duplicate_policy raises ConflictingRecordError, none of these silent outcomes can occur!


# ---------------------------------------------------------------------------
# 6. Real Workspace Datasets Clean Verification
# ---------------------------------------------------------------------------

def test_real_workspace_datasets_satisfy_duplicate_policy():
    """Verify real workspace data (gateway_master, field_visits, telemetry) loads cleanly under duplicate policy."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("data/ directory not present in workspace")

    # 1. Real Gateway Master: 332 unique canonical gateways, zero conflicts
    master_df = load_gateway_master(data_dir)
    assert len(master_df) == 332
    assert master_df["canonical_id"].is_unique

    # 2. Real Field Visits: 642 unique visits, zero conflicts
    visits_df = load_field_visits(data_dir)
    assert len(visits_df) == 642
    assert visits_df["visit_id"].is_unique

    # 3. Real Telemetry Window: zero conflicting records
    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=7)
    telemetry_df = load_telemetry_window(
        data_dir,
        cutoff_utc=cutoff_utc,
        start_utc=start_utc,
        columns=["canonical_id", "ts", "offline_duration_sec"],
    )
    assert not telemetry_df.empty
    assert not telemetry_df.duplicated(subset=["canonical_id", "ts"]).any()


# ---------------------------------------------------------------------------
# 7. Connected Pipeline Integration
# ---------------------------------------------------------------------------

def test_connected_pipeline_injected_equivalent_duplicates_resolve(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """Verify connected pipeline handles injected equivalent duplicates across master, visits, and telemetry."""
    # Master with 1 real row + 1 equivalent row
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,TENANT_A,Gebäude,NORTH,V1,OMNI,1.0.0,2025-01-01,5\n"
        "0639ea5602c1,TENANT_A,Gebäude,NORTH,V1,OMNI,1.0.0,2025-01-01,5\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    # Field visits with 1 real row + 1 equivalent row
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (tmp_path / "field_visits.csv").write_text(visits_csv, encoding="utf-8")

    # Telemetry with 1 real row + 1 equivalent row
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)
    rows = [
        {"gateway_id": "06:39:ea:56:02:c1", "ts_utc": "2026-02-01T12:00:00Z", "offline_duration_sec": 10.0},
        {"gateway_id": "0639EA5602C1", "ts_utc": "2026-02-01 12:00:00+00:00", "offline_duration_sec": 10.0},
    ]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)

    with caplog.at_level(logging.INFO):
        m_df = load_gateway_master(tmp_path)
        v_df = load_field_visits(tmp_path)
        t_df = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)

    # All three deduplicated deterministically to 1 row each
    assert len(m_df) == 1
    assert len(v_df) == 1
    assert len(t_df) == 1

    # Downstream joins succeed cleanly
    mv = m_df.merge(v_df, on="canonical_id", how="inner")
    mt = m_df.merge(t_df, on="canonical_id", how="inner")
    assert len(mv) == 1
    assert len(mt) == 1


def test_connected_pipeline_injected_conflict_in_master_blocks_pipeline(tmp_path: pathlib.Path):
    """Verify conflicting master records block the connected pipeline immediately."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "0639EA5602C1,TENANT_A,Gebäude,NORTH,V1,OMNI,1.0.0,2025-01-01,5\n"
        "0639EA5602C1,TENANT_B,Außenmast,SOUTH,V2,DIRECTIONAL,1.0.0,2025-01-01,10\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    with pytest.raises(ConflictingRecordError):
        load_gateway_master(tmp_path)


def test_connected_pipeline_injected_conflict_in_visits_blocks_pipeline(tmp_path: pathlib.Path):
    """Verify conflicting visit records block the connected pipeline immediately."""
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639EA5602C1,2025-09-01,2025-09-03,POWER_FAULT,REPLACED_FUSE,FUSE,1.0\n"
    )
    (tmp_path / "field_visits.csv").write_text(visits_csv, encoding="utf-8")

    with pytest.raises(ConflictingRecordError):
        load_field_visits(tmp_path)


def test_connected_pipeline_injected_conflict_in_telemetry_blocks_pipeline(tmp_path: pathlib.Path):
    """Verify conflicting telemetry records block the connected pipeline immediately."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)
    rows = [
        {"gateway_id": "0639EA5602C1", "ts_utc": "2026-02-01T12:00:00Z", "offline_duration_sec": 10.0},
        {"gateway_id": "0639EA5602C1", "ts_utc": "2026-02-01T12:00:00Z", "offline_duration_sec": 99.0},
    ]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")
    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)

    with pytest.raises(ConflictingRecordError):
        load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)
