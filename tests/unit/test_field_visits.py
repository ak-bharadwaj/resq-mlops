"""Dedicated unit tests for Field-Visits Loader, encoding verification, schema contract, and duplicate safety."""
import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    canonicalize_gateway_id,
    load_field_visits,
    verify_field_visits_encoding,
)
from app.data.schema import (
    ConflictingRecordError,
    FieldVisitsSchemaContract,
    SchemaValidationError,
)


def test_verify_field_visits_encoding_utf8(tmp_path: pathlib.Path):
    """Verify encoding check returns 'utf-8' for valid UTF-8 file."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    test_file = tmp_path / "field_visits.csv"
    test_file.write_bytes(csv_content.encode("utf-8"))

    encoding = verify_field_visits_encoding(tmp_path)
    assert encoding == "utf-8"


def test_verify_field_visits_encoding_cp1252(tmp_path: pathlib.Path):
    """Verify encoding check falls back to 'cp1252' when non-UTF8 bytes are present."""
    # Byte 0x80 is invalid in UTF-8 but decodes to '€' in CP1252
    csv_bytes = (
        b"visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        b"V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,Modell_\x80,2.5\n"
    )
    test_file = tmp_path / "field_visits.csv"
    test_file.write_bytes(csv_bytes)

    encoding = verify_field_visits_encoding(tmp_path)
    assert encoding == "cp1252"


def test_verify_field_visits_encoding_unsupported_bytes_raises_error(tmp_path: pathlib.Path):
    """Verify ValueError is raised when file contains unsupported or malformed byte sequences."""
    # Bytes b'\x80\x81\xff\xfe' are invalid UTF-8 and invalid CP1252
    csv_bytes = (
        b"visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        b"V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,\x81\x8d\x8f\x90\x9d,2.5\n"
    )
    test_file = tmp_path / "field_visits.csv"
    test_file.write_bytes(csv_bytes)

    with pytest.raises(ValueError, match="Unsupported or malformed encoding"):
        verify_field_visits_encoding(tmp_path)



def test_verify_field_visits_encoding_missing_file_raises_filenotfound(tmp_path: pathlib.Path):
    """Verify FileNotFoundError is raised when field_visits.csv is missing."""
    with pytest.raises(FileNotFoundError, match="Missing field_visits.csv"):
        verify_field_visits_encoding(tmp_path)


def test_field_visits_schema_contract_valid():
    """Verify FieldVisitsSchemaContract passes on valid DataFrame."""
    contract = FieldVisitsSchemaContract()
    df = pd.DataFrame([
        {
            "visit_id": "V001",
            "gateway_id": "06:39:EA:56:02:C1",
            "requested_on": "2025-09-01",
            "visited_on": "2025-09-03",
            "reason_reported": "COMM_FAULT",
            "outcome": "REPAIRED",
            "parts_replaced": "MODEM",
            "technician_hours": 2.5,
        }
    ])
    valid, errors = contract.validate_dataframe(df)
    assert valid is True
    assert len(errors) == 0
    contract.validate(df)  # Should not raise exception


def test_field_visits_schema_contract_missing_columns():
    """Verify FieldVisitsSchemaContract fails when required columns are missing."""
    contract = FieldVisitsSchemaContract()
    df = pd.DataFrame([
        {
            "visit_id": "V001",
            "gateway_id": "06:39:EA:56:02:C1",
        }
    ])
    valid, errors = contract.validate_dataframe(df)
    assert valid is False
    assert any("Missing required column(s)" in e for e in errors)
    with pytest.raises(SchemaValidationError, match="Field visits schema validation failed"):
        contract.validate(df)


def test_field_visits_schema_contract_null_mandatory_fields():
    """Verify FieldVisitsSchemaContract fails when mandatory identifier/date fields are null."""
    contract = FieldVisitsSchemaContract()
    df = pd.DataFrame([
        {
            "visit_id": None,
            "gateway_id": "06:39:EA:56:02:C1",
            "requested_on": "2025-09-01",
            "visited_on": "2025-09-03",
            "reason_reported": "COMM_FAULT",
            "outcome": "REPAIRED",
            "parts_replaced": None,
            "technician_hours": 2.5,
        }
    ])
    valid, errors = contract.validate_dataframe(df)
    assert valid is False
    assert any("visit_id" in e for e in errors)


def test_field_visits_schema_contract_invalid_date_ordering():
    """Verify FieldVisitsSchemaContract fails when requested_on > visited_on."""
    contract = FieldVisitsSchemaContract()
    df = pd.DataFrame([
        {
            "visit_id": "V001",
            "gateway_id": "06:39:EA:56:02:C1",
            "requested_on": "2025-09-10",
            "visited_on": "2025-09-03",  # Violated logical ordering
            "reason_reported": "COMM_FAULT",
            "outcome": "REPAIRED",
            "parts_replaced": "MODEM",
            "technician_hours": 2.5,
        }
    ])
    valid, errors = contract.validate_dataframe(df)
    assert valid is False
    assert any("Date logical ordering violated" in e for e in errors)


def test_field_visits_schema_contract_negative_technician_hours():
    """Verify FieldVisitsSchemaContract fails when technician_hours < 0.0."""
    contract = FieldVisitsSchemaContract()
    df = pd.DataFrame([
        {
            "visit_id": "V001",
            "gateway_id": "06:39:EA:56:02:C1",
            "requested_on": "2025-09-01",
            "visited_on": "2025-09-03",
            "reason_reported": "COMM_FAULT",
            "outcome": "REPAIRED",
            "parts_replaced": "MODEM",
            "technician_hours": -1.5,
        }
    ])
    valid, errors = contract.validate_dataframe(df)
    assert valid is False
    assert any("technician_hours must be non-negative" in e for e in errors)


def test_load_field_visits_real_data():
    """Verify loading real data/field_visits.csv (642 rows, schema invariants, types)."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "field_visits.csv").exists():
        pytest.skip("data/field_visits.csv missing from local workspace")

    df = load_field_visits(data_dir)
    assert len(df) == 642
    expected_cols = [
        "visit_id",
        "gateway_id",
        "requested_on",
        "visited_on",
        "reason_reported",
        "outcome",
        "parts_replaced",
        "technician_hours",
        "canonical_id",
    ]
    for col in expected_cols:
        assert col in df.columns, f"Missing column {col} in loaded field visits"

    assert isinstance(df.iloc[0]["requested_on"], dt.date)
    assert isinstance(df.iloc[0]["visited_on"], dt.date)
    assert df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()
    assert (df["technician_hours"] >= 0.0).all()
    assert (df["requested_on"] <= df["visited_on"]).all()


def test_load_field_visits_string_dtypes_preserved(tmp_path: pathlib.Path):
    """Verify dtype={"gateway_id": str, "visit_id": str} preserves leading zeros."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "00123,001122334455,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    df = load_field_visits(tmp_path)
    assert df.loc[0, "visit_id"] == "00123"
    assert df.loc[0, "gateway_id"] == "001122334455"
    assert df.loc[0, "canonical_id"] == "001122334455"


def test_load_field_visits_canonicalize_gateway_id_integration(tmp_path: pathlib.Path):
    """Verify canonical_id is generated via single production canonicalize_gateway_id function."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V002,0639ea5602c2,2025-09-10,2025-09-12,POWER_LOSS,INSPECTED,NONE,1.0\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    df = load_field_visits(tmp_path)
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert df.loc[1, "canonical_id"] == "0639EA5602C2"


def test_load_field_visits_equivalent_duplicate_collapse(tmp_path: pathlib.Path):
    """Verify equivalent duplicate visit records (differing only in raw gateway_id formatting) collapse to 1 logical visit."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    df = load_field_visits(tmp_path)
    assert len(df) == 1
    assert df.loc[0, "visit_id"] == "V001"
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"


def test_load_field_visits_conflicting_visit_id_blocks(tmp_path: pathlib.Path):
    """Verify conflicting records sharing visit_id trip ConflictingRecordError."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,NO_FAULT_FOUND,NONE,1.0\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ConflictingRecordError, match="Conflicting visit records detected"):
        load_field_visits(tmp_path)


def test_load_field_visits_invalid_date_order_blocks(tmp_path: pathlib.Path):
    """Verify requested_on > visited_on trips SchemaValidationError and blocks ingestion."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-10,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="Date logical ordering violated"):
        load_field_visits(tmp_path)


def test_load_field_visits_negative_technician_hours_blocks(tmp_path: pathlib.Path):
    """Verify technician_hours < 0.0 trips SchemaValidationError and blocks ingestion."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,-1.0\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="technician_hours must be non-negative"):
        load_field_visits(tmp_path)


def test_load_field_visits_missing_file_raises_filenotfound(tmp_path: pathlib.Path):
    """Verify missing field_visits.csv raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Missing field_visits.csv"):
        load_field_visits(tmp_path)


def test_anti_fake_field_visits_duplicate_safety(tmp_path: pathlib.Path):
    """Anti-fake test: prove equivalent formatting variations pass, but semantic differences block."""
    # 1. Formatting variation alone -> Passes and deduplicates
    csv_content_valid = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,  06:39:ea:56:02:c1  ,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content_valid, encoding="utf-8")
    df = load_field_visits(tmp_path)
    assert len(df) == 1

    # 2. Semantic difference -> Blocks
    csv_content_invalid = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-04,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path.write_text(csv_content_invalid, encoding="utf-8")
    with pytest.raises(ConflictingRecordError):
        load_field_visits(tmp_path)


def test_anti_fake_field_visits_schema_validation_fails_closed(tmp_path: pathlib.Path):
    """Anti-fake test: prove malformed schemas fail closed instead of proceeding with corrupt data."""
    # Missing required column 'outcome'
    csv_bad_schema = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_bad_schema, encoding="utf-8")
    with pytest.raises(SchemaValidationError):
        load_field_visits(tmp_path)
