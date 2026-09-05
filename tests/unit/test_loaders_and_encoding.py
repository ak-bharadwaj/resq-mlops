"""Tests for CP1252 loading and field visits encoding verification on real and synthetic data."""
import pathlib
import pytest
from app.data.loader import load_gateway_master, verify_field_visits_encoding, load_field_visits


def test_gateway_master_cp1252_synthetic_german_characters(tmp_path: pathlib.Path):
    # Synthetic test verifying CP1252 character handling
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA560201,tenant_a,Außenmast,Baden-Württemberg,Modell_Ä,Stabantenne,v1.0,,2020-01-01,,100\n"
        "0639EA560202,tenant_b,Gebäude,Groß-Umstadt,Modell_Ö,Omni,v1.0,,2021-05-10,2026-01-01,50\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert len(df) == 2
    assert df.loc[0, "site_type"] == "Außenmast"
    assert df.loc[0, "region"] == "Baden-Württemberg"
    assert df.loc[1, "site_type"] == "Gebäude"


def test_gateway_master_real_data():
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.fail("data/gateway_master.csv is required for test execution")

    df = load_gateway_master(data_dir)
    assert len(df) == 332
    assert "canonical_id" in df.columns
    assert df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()


def test_field_visits_real_data():
    data_dir = pathlib.Path("data")
    if not (data_dir / "field_visits.csv").exists():
        pytest.fail("data/field_visits.csv is required for test execution")

    enc = verify_field_visits_encoding(data_dir)
    assert enc in ("utf-8", "cp1252", "latin-1")

    df = load_field_visits(data_dir)
    assert len(df) == 642
    assert "canonical_id" in df.columns
    assert "visited_on" in df.columns
