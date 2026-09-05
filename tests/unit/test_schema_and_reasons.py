"""Unit tests for missing-data taxonomy, schema validation, and quality guards."""
import pathlib
import pandas as pd
import pytest
from app.data.schema import MissingDataReason, TelemetrySchemaContract
from app.data.quality import classify_telemetry_status, check_source_completeness


def test_missing_data_reasons_distinct():
    reasons = [
        MissingDataReason.NO_TELEMETRY,
        MissingDataReason.INSUFFICIENT_HISTORY,
        MissingDataReason.INSUFFICIENT_FEATURE_DATA,
        MissingDataReason.INELIGIBLE_DATE,
        MissingDataReason.SCHEMA_INVALID,
    ]
    # Verify all 5 reasons are distinct
    assert len(set(reasons)) == 5
    for r in reasons:
        assert isinstance(r.value, str)


def test_zero_telemetry_vs_recently_silent():
    # 1. Zero telemetry across history -> NO_TELEMETRY exclusion
    assert classify_telemetry_status(
        has_any_historical_telemetry=False,
        has_recent_telemetry=False,
    ) == MissingDataReason.NO_TELEMETRY

    # 2. Has prior telemetry, but 0 in recent window -> NOT NO_TELEMETRY
    # (Surfaced as recent_silence_ratio, not excluded)
    assert classify_telemetry_status(
        has_any_historical_telemetry=True,
        has_recent_telemetry=False,
    ) is None

    # 3. Has telemetry everywhere -> NOT excluded
    assert classify_telemetry_status(
        has_any_historical_telemetry=True,
        has_recent_telemetry=True,
    ) is None


def test_schema_validation_success():
    schema = TelemetrySchemaContract(
        required_columns=["canonical_id", "ts_utc", "offline_duration_sec"],
        dtypes={"offline_duration_sec": "float64"},
        time_grain="hourly",
        timestamp_column="ts_utc",
    )
    df = pd.DataFrame({
        "canonical_id": ["0639EA560201"],
        "ts_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "offline_duration_sec": [120.0],
    })
    is_valid, errors = schema.validate_dataframe(df)
    assert is_valid is True
    assert len(errors) == 0


def test_schema_validation_missing_columns():
    schema = TelemetrySchemaContract(
        required_columns=["canonical_id", "ts_utc", "offline_duration_sec"],
        dtypes={"offline_duration_sec": "float64"},
    )
    # Missing offline_duration_sec
    df = pd.DataFrame({
        "canonical_id": ["0639EA560201"],
        "ts_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
    })
    is_valid, errors = schema.validate_dataframe(df)
    assert is_valid is False
    assert any("offline_duration_sec" in e for e in errors)


def test_source_completeness_guard_trips_on_systemic_absence():
    eligible = {"0639EA560201", "0639EA560202", "0639EA560203", "0639EA560204"}
    # Expected: 4 * 10 = 40 rows. Received only 5 rows (absence rate = 35/40 = 87.5% > 50%)
    df = pd.DataFrame({"canonical_id": ["0639EA560201"] * 5})

    is_safe, absence_rate = check_source_completeness(
        telemetry_df=df,
        eligible_gateways=eligible,
        expected_hours_per_gw=10,
        threshold_absence_rate=0.50,
    )
    assert is_safe is False
    assert absence_rate > 0.50
