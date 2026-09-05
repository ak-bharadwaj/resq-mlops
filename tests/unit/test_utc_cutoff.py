"""Tests verifying Monday 00:00 UTC temporal cutoff via actual load_telemetry_window function."""
import datetime as dt
import pathlib
import pandas as pd
import pytest
from app.data.loader import load_telemetry_window


def test_production_load_telemetry_window_utc_boundary(tmp_path: pathlib.Path):
    # Create telemetry partition directory
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    # Telemetry test rows across boundary
    raw_rows = [
        # 1. Strictly before cutoff (valid in window)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-01T23:59:59Z", "offline_duration_sec": 10.0},
        # 2. Exact Monday 00:00:00 UTC cutoff -> MUST BE EXCLUDED (< cutoff)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T00:00:00Z", "offline_duration_sec": 20.0},
        # 3. Strictly after cutoff -> MUST BE EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T01:00:00Z", "offline_duration_sec": 30.0},
        # 4. Before start window -> MUST BE EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-04T23:59:59Z", "offline_duration_sec": 40.0},
        # 5. Inside window -> MUST BE INCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-15T12:00:00Z", "offline_duration_sec": 50.0},
    ]
    sample_df = pd.DataFrame(raw_rows)
    sample_df.to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc)

    # Call the actual production function load_telemetry_window
    loaded = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc, start_utc=start_utc)

    # Assertions
    assert len(loaded) == 2
    assert set(loaded["offline_duration_sec"]) == {10.0, 50.0}
    assert 20.0 not in loaded["offline_duration_sec"].values  # Exact cutoff excluded
    assert 30.0 not in loaded["offline_duration_sec"].values
    assert 40.0 not in loaded["offline_duration_sec"].values
