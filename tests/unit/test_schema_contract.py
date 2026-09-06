"""Dedicated unit tests for Task 8 Schema Contract."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import pandas as pd
import pytest

from app.data.schema import SchemaValidationError, TelemetrySchemaContract
from app.data.loader import load_telemetry_window


def test_model_schema_precedence_over_monitoring_baseline(tmp_path: pathlib.Path):
    """Verify models/<version>/schema.json is authoritative and monitoring baseline never overrides."""
    models_dir = tmp_path / "models"
    model_v1 = models_dir / "v0001"
    model_v1.mkdir(parents=True)

    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir(parents=True)

    # Write model schema with custom required column
    model_schema_data = {
        "required_columns": ["gateway_id", "ts_utc", "offline_duration_sec", "custom_model_col"],
        "dtypes": {"gateway_id": "string", "ts_utc": "datetime", "offline_duration_sec": "float64", "custom_model_col": "float64"},
        "time_grain": "hourly",
        "timestamp_column": "ts_utc",
    }
    (model_v1 / "schema.json").write_text(json.dumps(model_schema_data), encoding="utf-8")

    # Write conflicting monitoring baseline
    monitoring_baseline_data = {
        "required_columns": ["gateway_id", "ts_utc", "monitoring_only_col"],
        "dtypes": {"gateway_id": "string", "ts_utc": "datetime"},
        "time_grain": "hourly",
        "timestamp_column": "ts_utc",
    }
    (monitoring_dir / "schema_baseline.json").write_text(json.dumps(monitoring_baseline_data), encoding="utf-8")

    # Write active.json pointing to v0001
    registry_path = tmp_path / "registry" / "active.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps({"production_version": "v0001"}), encoding="utf-8")

    # Load active schema
    contract = TelemetrySchemaContract.load_active_schema(
        models_dir=models_dir,
        registry_path=registry_path,
    )

    # Assert model-local schema is loaded
    assert "custom_model_col" in contract.required_columns
    assert "monitoring_only_col" not in contract.required_columns


def test_naive_timestamp_strings_rejected():
    """Verify naive timestamp strings lacking UTC indicator fail closed with SchemaValidationError."""
    contract = TelemetrySchemaContract()
    df = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01 12:00:00"],  # Naive string without Z or offset
    })
    is_valid, errors = contract.validate_dataframe(df)
    assert is_valid is False
    assert any("Naive timestamps must not be silently interpreted as UTC" in e for e in errors)


def test_naive_datetime64_objects_rejected():
    """Verify naive datetime64 Series is rejected with SchemaValidationError."""
    contract = TelemetrySchemaContract()
    df = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": pd.to_datetime(["2026-02-01 12:00:00"]),  # tz-naive datetime64
    })
    is_valid, errors = contract.validate_dataframe(df)
    assert is_valid is False
    assert any("Naive timestamps must not be silently interpreted as UTC" in e for e in errors)


def test_non_utc_timezone_rejected():
    """Verify non-UTC timezone timestamp is rejected."""
    contract = TelemetrySchemaContract()
    df = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:00:00+05:30"],  # Non-UTC timezone offset
    })
    is_valid, errors = contract.validate_dataframe(df)
    assert is_valid is False
    assert any("must be UTC timezone" in e for e in errors)


def test_valid_utc_timestamps_accepted():
    """Verify ISO8601 UTC strings and tz-aware UTC datetimes are accepted."""
    contract = TelemetrySchemaContract()
    df1 = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:00:00Z"],
    })
    is_valid, errors = contract.validate_dataframe(df1)
    assert is_valid is True
    assert len(errors) == 0

    df2 = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01 12:00:00+00:00"],
    })
    is_valid, errors = contract.validate_dataframe(df2)
    assert is_valid is True
    assert len(errors) == 0


def test_hourly_grain_validation():
    """Verify non-hourly timestamps (minutes/seconds != 0) fail validation."""
    contract = TelemetrySchemaContract(time_grain="hourly")
    df_non_hourly = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:15:00Z"],  # 15 minutes!
    })
    is_valid, errors = contract.validate_dataframe(df_non_hourly)
    assert is_valid is False
    assert any("non-hourly grain" in e for e in errors)


def test_mandatory_non_null_checks():
    """Verify null gateway_id or ts_utc fail validation."""
    contract = TelemetrySchemaContract()
    df_null_id = pd.DataFrame({
        "gateway_id": [None],
        "ts_utc": ["2026-02-01T12:00:00Z"],
    })
    is_valid, errors = contract.validate_dataframe(df_null_id)
    assert is_valid is False
    assert any("gateway_id contains null" in e for e in errors)

    df_null_ts = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": [None],
    })
    is_valid, errors = contract.validate_dataframe(df_null_ts)
    assert is_valid is False
    assert any("ts_utc contains null" in e for e in errors)


def test_range_checks_declared_fields():
    """Verify negative counters/duration fail validation."""
    contract = TelemetrySchemaContract(
        required_columns=["gateway_id", "ts_utc", "offline_duration_sec", "disconnection_cnt", "reboot_cnt"],
        dtypes={
            "offline_duration_sec": "float64",
            "disconnection_cnt": "float64",
            "reboot_cnt": "float64",
        },
    )
    # Negative offline duration
    df_neg_offline = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:00:00Z"],
        "offline_duration_sec": [-10.0],
        "disconnection_cnt": [0.0],
        "reboot_cnt": [0.0],
    })
    assert contract.validate_dataframe(df_neg_offline)[0] is False

    # Negative disconnection count
    df_neg_disc = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:00:00Z"],
        "offline_duration_sec": [0.0],
        "disconnection_cnt": [-1.0],
        "reboot_cnt": [0.0],
    })
    assert contract.validate_dataframe(df_neg_disc)[0] is False

    # Negative reboot count
    df_neg_reb = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"],
        "ts_utc": ["2026-02-01T12:00:00Z"],
        "offline_duration_sec": [0.0],
        "disconnection_cnt": [0.0],
        "reboot_cnt": [-2.0],
    })
    assert contract.validate_dataframe(df_neg_reb)[0] is False


def test_real_supplied_telemetry_partition_validation():
    """Verify real workspace telemetry partitions satisfy the authoritative contract."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "telemetry").exists() and not (data_dir / "telemetry.parquet").exists():
        pytest.skip("data/telemetry not present in local workspace")

    contract = TelemetrySchemaContract.load_active_schema()
    df = pd.read_parquet(data_dir / "telemetry")
    # Validate full dataframe
    valid, errors = contract.validate_dataframe(df)
    assert valid is True, f"Real telemetry failed schema validation: {errors}"
    assert len(errors) == 0


def test_anti_fake_schema_cannot_be_bypassed():
    """Anti-fake test: verify validate_or_raise fails closed on empty or invalid data."""
    contract = TelemetrySchemaContract()
    empty_df = pd.DataFrame()
    with pytest.raises(SchemaValidationError):
        contract.validate_or_raise(empty_df)


def test_load_active_schema_fails_closed_when_schema_missing(tmp_path: pathlib.Path):
    """Verify load_active_schema fails closed when active model exists but schema.json is missing."""
    models_dir = tmp_path / "models"
    model_v1 = models_dir / "v0001"
    model_v1.mkdir(parents=True)
    # schema.json deliberately NOT created

    registry_path = tmp_path / "registry" / "active.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps({"production_version": "v0001"}), encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="Authoritative schema contract missing"):
        TelemetrySchemaContract.load_active_schema(models_dir=models_dir, registry_path=registry_path)


def test_load_active_schema_fails_closed_when_schema_corrupt(tmp_path: pathlib.Path):
    """Verify load_active_schema fails closed when active model schema.json is corrupt."""
    models_dir = tmp_path / "models"
    model_v1 = models_dir / "v0001"
    model_v1.mkdir(parents=True)
    (model_v1 / "schema.json").write_text("{CORRUPT_JSON_DATA", encoding="utf-8")

    registry_path = tmp_path / "registry" / "active.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps({"production_version": "v0001"}), encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="corrupt or invalid"):
        TelemetrySchemaContract.load_active_schema(models_dir=models_dir, registry_path=registry_path)


def test_load_active_schema_fails_closed_when_registry_corrupt(tmp_path: pathlib.Path):
    """Verify load_active_schema fails closed when registry active.json is corrupt."""
    models_dir = tmp_path / "models"
    registry_path = tmp_path / "registry" / "active.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{CORRUPT_JSON", encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="unreadable or corrupt JSON"):
        TelemetrySchemaContract.load_active_schema(models_dir=models_dir, registry_path=registry_path)


def test_load_active_schema_fails_closed_when_model_dir_missing(tmp_path: pathlib.Path):
    """Verify load_active_schema fails closed when active version has no model directory."""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    registry_path = tmp_path / "registry" / "active.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps({"production_version": "v9999"}), encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="model artifact directory .* does not exist"):
        TelemetrySchemaContract.load_active_schema(models_dir=models_dir, registry_path=registry_path)


def test_check_drift_cli_execution(tmp_path: pathlib.Path):
    """Verify scripts/check_drift.py executes structural schema monitoring cleanly."""
    import subprocess
    import sys

    data_dir = pathlib.Path("data")
    if not (data_dir.exists() and (data_dir / "gateway_master.csv").exists()):
        # Synthesize minimal valid dataset so test never skips on clean clones without data
        data_dir = tmp_path / "mock_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "gateway_master.csv").write_text(
            "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
            "0639EA5602C1,tenant_a,pole,EU-NORTH,rev_1,omni,1.0.0,2025-01-01,10\n",
            encoding="cp1252",
        )
        telemetry_dir = data_dir / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        ts_range = pd.date_range("2026-01-10", "2026-02-01", freq="h", tz="UTC")
        df_telemetry = pd.DataFrame({
            "gateway_id": ["0639EA5602C1"] * len(ts_range),
            "ts_utc": ts_range,
            "offline_duration_sec": [0.0] * len(ts_range),
            "disconnection_cnt": [0.0] * len(ts_range),
            "reboot_cnt": [0.0] * len(ts_range),
        })
        df_telemetry.to_parquet(telemetry_dir / "part-0.parquet")

    report_out = tmp_path / "drift_report.json"
    res = subprocess.run(
        [
            sys.executable,
            "scripts/check_drift.py",
            "--data", str(data_dir),
            "--output", str(report_out),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"check_drift failed: {res.stderr}"
    assert "STRUCTURAL SCHEMA MONITORING" in res.stdout
    assert "Structural Schema:      PASS" in res.stdout
    assert report_out.exists()

    report_data = json.loads(report_out.read_text(encoding="utf-8"))
    assert report_data["status"] == "PASS"
    assert report_data["schema_validation_passed"] is True
    assert report_data["source_completeness_safe"] is True
    assert report_data["rows_checked"] > 0
    # Provenance assertion: timestamp_utc must be a valid, timezone-aware ISO-8601 string
    parsed_ts = dt.datetime.fromisoformat(report_data["timestamp_utc"])
    assert parsed_ts.tzinfo is not None


def test_check_drift_cli_synthetic_data_isolation(tmp_path: pathlib.Path):
    """Verify scripts/check_drift.py executes cleanly against a standalone synthetic data directory."""
    import subprocess
    import sys

    mock_data = tmp_path / "mock_data"
    mock_data.mkdir(parents=True, exist_ok=True)
    (mock_data / "gateway_master.csv").write_text(
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        "0639EA5602C1,tenant_a,pole,EU-NORTH,rev_1,omni,1.0.0,2025-01-01,10\n",
        encoding="cp1252",
    )
    telemetry_dir = mock_data / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    ts_range = pd.date_range("2026-01-10", "2026-02-01", freq="h", tz="UTC")
    df_telemetry = pd.DataFrame({
        "gateway_id": ["0639EA5602C1"] * len(ts_range),
        "ts_utc": ts_range,
        "offline_duration_sec": [0.0] * len(ts_range),
        "disconnection_cnt": [0.0] * len(ts_range),
        "reboot_cnt": [0.0] * len(ts_range),
    })
    df_telemetry.to_parquet(telemetry_dir / "part-0.parquet")

    report_out = tmp_path / "drift_report_synthetic.json"
    res = subprocess.run(
        [
            sys.executable,
            "scripts/check_drift.py",
            "--data", str(mock_data),
            "--output", str(report_out),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"check_drift failed on synthetic data: {res.stderr}"
    assert "STRUCTURAL SCHEMA MONITORING" in res.stdout
    assert "Structural Schema:      PASS" in res.stdout
    assert report_out.exists()

    report_data = json.loads(report_out.read_text(encoding="utf-8"))
    assert report_data["status"] == "PASS"
    assert report_data["schema_validation_passed"] is True
    assert report_data["source_completeness_safe"] is True
    assert report_data["rows_checked"] == len(ts_range)
    parsed_ts = dt.datetime.fromisoformat(report_data["timestamp_utc"])
    assert parsed_ts.tzinfo is not None



