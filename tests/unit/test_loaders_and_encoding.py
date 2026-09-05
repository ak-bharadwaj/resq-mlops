"""Unit tests for CP1252 parsing, field_visits encoding verification, and master loading."""
import pathlib
import pytest
from app.data.loader import load_gateway_master, verify_field_visits_encoding, load_field_visits


def test_gateway_master_cp1252_loading():
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("data/gateway_master.csv not present")

    master_df = load_gateway_master(data_dir)
    assert len(master_df) == 332
    assert "canonical_id" in master_df.columns
    # Check all canonical IDs are 12 uppercase hex characters
    assert master_df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()
    # Check site_type or tenant is not garbled
    assert master_df["tenant"].notna().all()


def test_field_visits_encoding_verification():
    data_dir = pathlib.Path("data")
    if not (data_dir / "field_visits.csv").exists():
        pytest.skip("data/field_visits.csv not present")

    encoding = verify_field_visits_encoding(data_dir)
    assert encoding in ("utf-8", "cp1252", "latin-1")

    visits_df = load_field_visits(data_dir)
    assert len(visits_df) == 642
    assert "canonical_id" in visits_df.columns
    assert "visited_on" in visits_df.columns
