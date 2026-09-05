"""Unit tests for exact vs conflicting duplicate detection (Section 7A)."""
import datetime as dt
import pandas as pd
import pytest
from app.data.loader import resolve_telemetry_duplicates
from app.data.schema import ConflictingRecordError


def test_exact_duplicates_deduplicated_deterministically():
    ts = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 10.0, "val2": 5},
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 10.0, "val2": 5},  # Exact duplicate
        {"canonical_id": "0639EA560202", "ts": ts, "val1": 20.0, "val2": 8},
    ])

    deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])
    assert dup_count == 1
    assert len(deduped) == 2
    assert list(deduped["canonical_id"]) == ["0639EA560201", "0639EA560202"]


def test_conflicting_duplicates_raises_conflicting_record_error():
    ts = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    # Same canonical_id and ts, but different val1 (conflicting)
    df = pd.DataFrame([
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 10.0},
        {"canonical_id": "0639EA560201", "ts": ts, "val1": 99.0},  # Conflict!
    ])

    with pytest.raises(ConflictingRecordError):
        resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])
