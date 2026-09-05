"""Dedicated unit tests for Task 6 Telemetry Loader + Monday 00:00 UTC Firewall contract.

Covered Invariants:
1. Exact Monday 00:00:00 UTC boundary cutoff (< cutoff_utc).
2. Start window bound support [start_utc, cutoff_utc).
3. Real Parquet partition ingestion from data/telemetry.
4. Equivalent telemetry duplicate resolution (Section 7A).
5. Conflicting measurement duplicate detection (ConflictingRecordError).
6. Source completeness guard tripping on >50% absence.
7. Naive datetime rejection.
8. TelemetrySchemaContract schema validation.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    canonicalize_gateway_id,
    load_telemetry_window,
    resolve_telemetry_duplicates,
)
from app.data.quality import check_source_completeness, classify_telemetry_status
from app.data.schema import (
    ConflictingRecordError,
    MissingDataReason,
    SchemaValidationError,
    TelemetrySchemaContract,
)


def test_exact_boundary_cutoff_exclusion(tmp_path: pathlib.Path):
    """Verify strictly < cutoff_utc filtering. Exactly Monday 00:00:00 UTC must be EXCLUDED."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    rows = [
        # Strictly before cutoff (valid in window)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-01T23:59:59Z", "offline_duration_sec": 10.0},
        # Exact Monday 00:00:00 UTC cutoff -> MUST BE EXCLUDED (< cutoff_utc)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T00:00:00Z", "offline_duration_sec": 20.0},
        # Strictly after cutoff -> MUST BE EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T00:00:01Z", "offline_duration_sec": 30.0},
    ]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    loaded = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)

    assert len(loaded) == 1
    assert loaded["offline_duration_sec"].iloc[0] == 10.0
    assert 20.0 not in loaded["offline_duration_sec"].values
    assert 30.0 not in loaded["offline_duration_sec"].values


def test_start_window_bound(tmp_path: pathlib.Path):
    """Verify half-open window filtering: [start_utc, cutoff_utc)."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    rows = [
        # Strictly before start_utc -> EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-04T23:59:59Z", "val": 1.0},
        # Exact start_utc bound -> INCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-05T00:00:00Z", "val": 2.0},
        # Strictly inside window -> INCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-15T12:00:00Z", "val": 3.0},
        # Exact cutoff_utc -> EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-26T00:00:00Z", "val": 4.0},
    ]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    start_utc = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc)
    cutoff_utc = dt.datetime(2026, 1, 26, 0, 0, 0, tzinfo=dt.timezone.utc)

    loaded = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc, start_utc=start_utc)

    assert len(loaded) == 2
    assert set(loaded["val"]) == {2.0, 3.0}


def test_real_parquet_partition_ingestion():
    """Verify loading real parquet partitions from data/telemetry directory."""
    data_dir = pathlib.Path("data")
    cutoff_utc = dt.datetime(2025, 12, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2025, 11, 24, 0, 0, 0, tzinfo=dt.timezone.utc)

    loaded = load_telemetry_window(
        data_dir=data_dir,
        cutoff_utc=cutoff_utc,
        start_utc=start_utc,
        columns=["canonical_id", "ts", "offline_duration_sec", "disconnection_cnt"],
    )

    assert not loaded.empty
    assert "canonical_id" in loaded.columns
    assert "ts" in loaded.columns
    assert "offline_duration_sec" in loaded.columns
    assert (loaded["ts"] >= start_utc).all()
    assert (loaded["ts"] < cutoff_utc).all()
    assert str(loaded["ts"].dt.tz) in ("UTC", "datetime.timezone.utc")


def test_equivalent_telemetry_deduplication():
    """Verify deterministic deduplication of equivalent telemetry measurements (Section 7A)."""
    ts1 = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"gateway_id": "06:39:EA:56:02:01", "ts": ts1, "offline_duration_sec": 120.0},
        {"gateway_id": "0639ea560201", "ts": ts1, "offline_duration_sec": 120.0},  # Equivalent
    ])

    deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])

    assert dup_count == 1
    assert len(deduped) == 1
    assert deduped["canonical_id"].iloc[0] == "0639EA560201"


def test_conflicting_measurement_blocking():
    """Verify conflicting measurement values for same (canonical_id, ts) raise ConflictingRecordError."""
    ts1 = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts1, "offline_duration_sec": 120.0},
        {"canonical_id": "0639EA560201", "ts": ts1, "offline_duration_sec": 999.0},  # Conflicting!
    ])

    with pytest.raises(ConflictingRecordError):
        resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])


def test_source_completeness_guard_tripping():
    """Verify source completeness guard trips into unsafe state when >50% missing."""
    eligible = {"0639EA560201", "0639EA560202", "0639EA560203", "0639EA560204"}

    # Only 1 gateway present -> 75% gateway absence (>50%)
    df_missing_gateways = pd.DataFrame({
        "canonical_id": ["0639EA560201"] * 168,
    })
    is_safe, absence_rate = check_source_completeness(
        telemetry_df=df_missing_gateways,
        eligible_gateways=eligible,
        expected_hours_per_gw=168,
        threshold_absence_rate=0.50,
    )
    assert is_safe is False
    assert absence_rate > 0.50

    # All gateways present but receiving only 10 out of 168 hours -> 94% record absence (>50%)
    df_sparse = pd.DataFrame({
        "canonical_id": ["0639EA560201", "0639EA560202", "0639EA560203", "0639EA560204"] * 2,
    })
    is_safe_sparse, absence_rate_sparse = check_source_completeness(
        telemetry_df=df_sparse,
        eligible_gateways=eligible,
        expected_hours_per_gw=168,
        threshold_absence_rate=0.50,
    )
    assert is_safe_sparse is False
    assert absence_rate_sparse > 0.50


def test_naive_datetime_rejection(tmp_path: pathlib.Path):
    """Verify naive (non-timezone aware) datetime bounds are rejected with ValueError."""
    naive_cutoff = dt.datetime(2026, 2, 2, 0, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        load_telemetry_window(tmp_path, cutoff_utc=naive_cutoff)

    valid_cutoff = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    naive_start = dt.datetime(2026, 1, 1, 0, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        load_telemetry_window(tmp_path, cutoff_utc=valid_cutoff, start_utc=naive_start)


def test_non_utc_timezone_datetime_rejection(tmp_path: pathlib.Path):
    """Verify non-UTC timezone-aware datetime bounds (e.g. IST +05:30) are rejected with ValueError."""
    ist_tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
    non_utc_cutoff = dt.datetime(2026, 2, 2, 5, 30, 0, tzinfo=ist_tz)

    with pytest.raises(ValueError, match="cutoff_utc must be in UTC timezone"):
        load_telemetry_window(tmp_path, cutoff_utc=non_utc_cutoff)

    valid_cutoff = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    non_utc_start = dt.datetime(2026, 1, 1, 5, 30, 0, tzinfo=ist_tz)
    with pytest.raises(ValueError, match="start_utc must be in UTC timezone"):
        load_telemetry_window(tmp_path, cutoff_utc=valid_cutoff, start_utc=non_utc_start)


def test_load_telemetry_window_fails_closed_on_unexpected_path(tmp_path: pathlib.Path):
    """Verify load_telemetry_window fails closed with FileNotFoundError if telemetry data is not at expected location."""
    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)

    # Empty directory with random parquet file that is NOT in telemetry/ or telemetry.parquet
    random_parquet = tmp_path / "random_data.parquet"
    pd.DataFrame([{"gateway_id": "0639EA560201", "ts_utc": "2026-01-01T00:00:00Z"}]).to_parquet(random_parquet)

    with pytest.raises(FileNotFoundError, match="Telemetry path not found"):
        load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)


def test_load_telemetry_window_enforces_schema_contract(tmp_path: pathlib.Path):
    """Verify load_telemetry_window enforces TelemetrySchemaContract in production loading path."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    # Parquet file missing 'ts_utc' column
    rows = [{"gateway_id": "0639EA560201", "some_metric": 10.0}]
    pd.DataFrame(rows).to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    with pytest.raises(SchemaValidationError, match="Telemetry schema validation failed"):
        load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc)


def test_telemetry_schema_contract_validation():
    """Verify TelemetrySchemaContract loading and validate_or_raise behavior."""
    schema = TelemetrySchemaContract.load_from_model(pathlib.Path("models/v0001"))

    # Valid telemetry dataframe
    valid_df = pd.DataFrame({
        "gateway_id": ["0639EA560201"],
        "ts_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "offline_duration_sec": [0.0],
        "disconnection_cnt": [0.0],
        "reboot_cnt": [0.0],
    })
    schema.validate_or_raise(valid_df)

    # Missing required column
    invalid_df = pd.DataFrame({
        "gateway_id": ["0639EA560201"],
        "ts_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
    })
    with pytest.raises(SchemaValidationError):
        schema.validate_or_raise(invalid_df)
