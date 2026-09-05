"""Unit tests for Monday 00:00 UTC temporal boundary."""
import datetime as dt
import pandas as pd
import pytest


def test_utc_cutoff_filtering():
    scored_monday_cutoff = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_window = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc)

    # Telemetry samples around cutoff
    df = pd.DataFrame([
        # Within window (1 second before cutoff)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-01T23:59:59Z", "val": 1.0},
        # Exactly at cutoff -> MUST BE EXCLUDED (strict ts < cutoff)
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T00:00:00Z", "val": 2.0},
        # After cutoff -> EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-02-02T01:00:00Z", "val": 3.0},
        # Before start window -> EXCLUDED
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-04T23:59:59Z", "val": 4.0},
        # Within window
        {"gateway_id": "0639EA560201", "ts_utc": "2026-01-15T12:00:00Z", "val": 5.0},
    ])
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)

    # Filter logic per load_telemetry_window
    mask = (df["ts"] >= start_window) & (df["ts"] < scored_monday_cutoff)
    filtered = df.loc[mask]

    assert len(filtered) == 2
    assert set(filtered["val"]) == {1.0, 5.0}
    assert 2.0 not in filtered["val"].values  # Cutoff point strictly excluded
    assert 3.0 not in filtered["val"].values
    assert 4.0 not in filtered["val"].values
