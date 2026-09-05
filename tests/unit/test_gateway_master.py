"""Dedicated unit tests for Gateway Master Loader and GatewayMasterSchemaContract."""

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import canonicalize_gateway_id, load_gateway_master
from app.data.schema import (
    ConflictingRecordError,
    GatewayMasterSchemaContract,
    SchemaValidationError,
)


def test_gateway_master_real_data():
    """Verify real data ingestion (332 gateways) with canonicalization and date parsing."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.fail("data/gateway_master.csv is required for test execution")

    df = load_gateway_master(data_dir)
    assert len(df) == 332
    assert "canonical_id" in df.columns
    assert df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()

    # Verify column presence
    contract = GatewayMasterSchemaContract()
    for col in contract.required_columns:
        assert col in df.columns

    # Verify date parsing
    for date_val in df["installed_on"]:
        assert isinstance(date_val, dt.date)

    for date_val in df["decommissioned_on"].dropna():
        assert isinstance(date_val, dt.date)

    if "fw_updated_on" in df.columns:
        for date_val in df["fw_updated_on"].dropna():
            assert isinstance(date_val, dt.date)

    # Verify non-negative n_meters_installed
    assert (df["n_meters_installed"] >= 0).all()


def test_gateway_master_cp1252_german_characters(tmp_path: pathlib.Path):
    """Verify CP1252 character handling for German special characters."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA560201,tenant_a,Außenmast,Baden-Württemberg,Modell_Ä,Stabantenne,v1.0,,2020-01-01,,100\n"
        "0639EA560202,tenant_b,Gebäude,Groß-Umstadt,Modell_Ö,Omni,v1.0,,2021-05-10,2026-01-01,50\n"
        "0639EA560203,tenant_c,Schaltschrank,München,Modell_Ü,Richtantenne,v1.1,2022-03-15,2019-11-20,,75\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert len(df) == 3
    assert df.loc[df["canonical_id"] == "0639EA560201", "site_type"].values[0] == "Außenmast"
    assert df.loc[df["canonical_id"] == "0639EA560201", "region"].values[0] == "Baden-Württemberg"
    assert df.loc[df["canonical_id"] == "0639EA560202", "site_type"].values[0] == "Gebäude"
    assert df.loc[df["canonical_id"] == "0639EA560202", "region"].values[0] == "Groß-Umstadt"
    assert df.loc[df["canonical_id"] == "0639EA560203", "site_type"].values[0] == "Schaltschrank"


def test_gateway_master_schema_contract_validation():
    """Verify GatewayMasterSchemaContract validation rules."""
    contract = GatewayMasterSchemaContract()

    # 1. Valid dataframe passes
    valid_df = pd.DataFrame({
        "gateway_id": ["06:39:EA:56:02:C1"],
        "canonical_id": ["0639EA5602C1"],
        "tenant": ["tenant_a"],
        "site_type": ["Außenmast"],
        "region": ["Baden-Württemberg"],
        "hw_model": ["v1"],
        "antenna_type": ["omni"],
        "fw_version": ["1.0.0"],
        "installed_on": [dt.date(2020, 1, 1)],
        "decommissioned_on": [dt.date(2025, 1, 1)],
        "n_meters_installed": [10],
    })
    is_valid, errors = contract.validate_dataframe(valid_df)
    assert is_valid is True
    assert len(errors) == 0

    # 2. Missing required columns fails
    invalid_cols_df = valid_df.drop(columns=["n_meters_installed"])
    is_valid, errors = contract.validate_dataframe(invalid_cols_df)
    assert is_valid is False
    assert any("n_meters_installed" in e for e in errors)

    # 3. Invalid date logical ordering (installed_on > decommissioned_on) fails
    invalid_dates_df = valid_df.copy()
    invalid_dates_df["installed_on"] = [dt.date(2026, 1, 1)]
    invalid_dates_df["decommissioned_on"] = [dt.date(2020, 1, 1)]
    is_valid, errors = contract.validate_dataframe(invalid_dates_df)
    assert is_valid is False
    assert any("Date ordering violation" in e for e in errors)

    # 4. Negative n_meters_installed fails
    negative_meters_df = valid_df.copy()
    negative_meters_df["n_meters_installed"] = [-5]
    is_valid, errors = contract.validate_dataframe(negative_meters_df)
    assert is_valid is False
    assert any("n_meters_installed invariant violation" in e for e in errors)


def test_gateway_master_loader_invalid_date_order_blocks(tmp_path: pathlib.Path):
    """Verify load_gateway_master raises SchemaValidationError when installed_on > decommissioned_on."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA560201,tenant_a,Außenmast,Baden-Württemberg,Modell_A,Stabantenne,v1.0,,2025-01-01,2020-01-01,100\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(SchemaValidationError, match="Date ordering violation"):
        load_gateway_master(tmp_path)


def test_gateway_master_loader_negative_meters_blocks(tmp_path: pathlib.Path):
    """Verify load_gateway_master raises SchemaValidationError when n_meters_installed < 0."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA560201,tenant_a,Außenmast,Baden-Württemberg,Modell_A,Stabantenne,v1.0,,2020-01-01,,-10\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(SchemaValidationError, match="n_meters_installed invariant violation"):
        load_gateway_master(tmp_path)


def test_gateway_master_equivalent_representation_collapsing(tmp_path: pathlib.Path):
    """Verify equivalent raw gateway_id representations with identical attributes collapse to 1 logical row."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert len(df) == 1
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"


def test_gateway_master_conflicting_attributes_blocking(tmp_path: pathlib.Path):
    """Verify conflicting attributes for the same canonical ID raise ConflictingRecordError."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
        "0639EA5602C1,tenant_b,Gebäude,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(ConflictingRecordError, match="Conflicting master records detected"):
        load_gateway_master(tmp_path)


def test_gateway_master_leading_zero_preservation(tmp_path: pathlib.Path):
    """Verify dtype={'gateway_id': str} preserves leading zeros in raw numeric IDs."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert df.loc[0, "gateway_id"] == "0639EA5602C1"
    assert df.loc[0, "gateway_id"].startswith("0")


def test_anti_fake_gateway_master_validation_and_canonicalization(tmp_path: pathlib.Path):
    """Anti-fake assertions verifying schema contract and canonicalization cannot be bypassed."""
    # 1. Verification that canonicalize_gateway_id function is strictly used
    raw = "06:39:ea:56:02:c1"
    assert canonicalize_gateway_id(raw) == "0639EA5602C1"

    # 2. Verification that missing required columns fail schema validation closed
    contract = GatewayMasterSchemaContract()
    empty_df = pd.DataFrame()
    valid, errors = contract.validate_dataframe(empty_df)
    assert valid is False
    assert len(errors) > 0

    # 3. Direct conflict detection assertion
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,100\n"
        "0639EA5602C1,tenant_a,Außenmast,Region_1,Modell_A,Omni,v1.0,,2020-01-01,,200\n"
    )
    test_file = tmp_path / "gateway_master.csv"
    test_file.write_bytes(csv_content.encode("cp1252"))

    with pytest.raises(ConflictingRecordError):
        load_gateway_master(tmp_path)
