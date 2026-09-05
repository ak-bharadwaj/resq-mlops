"""Unit and integration tests for canonical gateway ID normalization and collision safety."""
from __future__ import annotations

import ast
import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import (
    canonicalize_gateway_id,
    load_field_visits,
    load_gateway_master,
    load_telemetry_window,
    resolve_telemetry_duplicates,
)
from app.data.schema import ConflictingRecordError


# ---------------------------------------------------------------------------
# 1. Bare 12-hex normalization
# ---------------------------------------------------------------------------


def test_canonicalize_bare_uppercase():
    assert canonicalize_gateway_id("0639EA5602C1") == "0639EA5602C1"
    assert canonicalize_gateway_id("1A2B3C4D5E6F") == "1A2B3C4D5E6F"


def test_canonicalize_bare_lowercase():
    assert canonicalize_gateway_id("0639ea5602c1") == "0639EA5602C1"
    assert canonicalize_gateway_id("1a2b3c4d5e6f") == "1A2B3C4D5E6F"


# ---------------------------------------------------------------------------
# 2. Colon-separated normalization
# ---------------------------------------------------------------------------


def test_canonicalize_colon_separated_uppercase():
    assert canonicalize_gateway_id("06:39:EA:56:02:C1") == "0639EA5602C1"
    assert canonicalize_gateway_id("1A:2B:3C:4D:5E:6F") == "1A2B3C4D5E6F"


def test_canonicalize_colon_separated_lowercase():
    assert canonicalize_gateway_id("06:39:ea:56:02:c1") == "0639EA5602C1"
    assert canonicalize_gateway_id("1a:2b:3c:4d:5e:6f") == "1A2B3C4D5E6F"


# ---------------------------------------------------------------------------
# 3. Case and whitespace normalization
# ---------------------------------------------------------------------------


def test_canonicalize_leading_trailing_whitespace():
    assert canonicalize_gateway_id("  0639EA5602C1  ") == "0639EA5602C1"
    assert canonicalize_gateway_id("\t0639ea5602c1\n") == "0639EA5602C1"
    assert canonicalize_gateway_id("   06:39:EA:56:02:C1   ") == "0639EA5602C1"
    assert canonicalize_gateway_id("\t06:39:ea:56:02:c1\r\n") == "0639EA5602C1"


def test_canonicalize_mixed_case():
    assert canonicalize_gateway_id("0639eA5602c1") == "0639EA5602C1"
    assert canonicalize_gateway_id("06:39:eA:56:02:C1") == "0639EA5602C1"
    assert canonicalize_gateway_id("1a:2B:3c:4D:5e:6F") == "1A2B3C4D5E6F"
    assert canonicalize_gateway_id("  06:39:Ea:56:02:c1  ") == "0639EA5602C1"


# ---------------------------------------------------------------------------
# 4. Equivalence proof across multiple accepted representations
# ---------------------------------------------------------------------------


def test_multiple_accepted_representations_produce_same_canonical_id():
    """Prove that at least two different accepted raw representations produce the same canonical ID."""
    rep_bare_upper = "0639EA5602C1"
    rep_bare_lower = "0639ea5602c1"
    rep_colon_upper = "06:39:EA:56:02:C1"
    rep_colon_lower = "06:39:ea:56:02:c1"
    rep_mixed_padded = "  06:39:eA:56:02:c1 \t"

    expected = "0639EA5602C1"
    assert canonicalize_gateway_id(rep_bare_upper) == expected
    assert canonicalize_gateway_id(rep_bare_lower) == expected
    assert canonicalize_gateway_id(rep_colon_upper) == expected
    assert canonicalize_gateway_id(rep_colon_lower) == expected
    assert canonicalize_gateway_id(rep_mixed_padded) == expected

    # Explicit cross-representation equivalence assertion
    assert (
        canonicalize_gateway_id(rep_bare_upper)
        == canonicalize_gateway_id(rep_bare_lower)
        == canonicalize_gateway_id(rep_colon_upper)
        == canonicalize_gateway_id(rep_colon_lower)
        == canonicalize_gateway_id(rep_mixed_padded)
    )


# ---------------------------------------------------------------------------
# 5. Invalid-ID rejection (deterministic fail-closed)
# ---------------------------------------------------------------------------


def test_canonicalize_rejects_null_and_nan():
    with pytest.raises(ValueError):
        canonicalize_gateway_id(None)
    with pytest.raises(ValueError):
        canonicalize_gateway_id(float("nan"))
    with pytest.raises(ValueError):
        canonicalize_gateway_id(pd.NA)


def test_canonicalize_rejects_empty_string():
    with pytest.raises(ValueError):
        canonicalize_gateway_id("")


def test_canonicalize_rejects_whitespace_only():
    with pytest.raises(ValueError):
        canonicalize_gateway_id("   ")
    with pytest.raises(ValueError):
        canonicalize_gateway_id("\t\r\n")


def test_canonicalize_rejects_non_hex_characters():
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602CG")
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06:39:ZZ:56:02:C1")
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06-39-EA-56-02-C1")  # Unauthorized hyphen separator
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06.39.EA.56.02.C1")  # Unauthorized dot separator
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602C!")  # Punctuation


def test_canonicalize_rejects_incorrect_length():
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602")  # 10 chars
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602C1FF")  # 14 chars
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06:39:EA:56:02")  # 5 octets
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06:39:EA:56:02:C1:AA")  # 7 octets


def test_canonicalize_rejects_non_scalar_types():
    """Reject non-scalar collections and arrays deterministically without ambiguous truth errors."""
    import numpy as np
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id([])
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id([1, 2])
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id(["0639EA5602C1"])
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id({})
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id(set())
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id(np.array([1, 2]))
    with pytest.raises(ValueError, match="Invalid gateway ID format"):
        canonicalize_gateway_id(pd.Series(["0639EA5602C1"]))


# ---------------------------------------------------------------------------
# 6. Single normalization path verification (AST enforcement)
# ---------------------------------------------------------------------------


def test_single_normalization_path_ast_enforcement():
    """Verify single normalization path across entire codebase via AST inspection."""
    root = pathlib.Path(__file__).parent.parent.parent
    app_and_scripts = list((root / "app").rglob("*.py")) + list((root / "scripts").rglob("*.py"))

    canonicalizer_definitions = []
    for py_file in app_and_scripts:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "canonicalize_gateway_id":
                canonicalizer_definitions.append(str(py_file.relative_to(root)))

    # Exactly one authoritative definition in app/data/loader.py
    assert len(canonicalizer_definitions) == 1
    assert canonicalizer_definitions[0].replace("\\", "/") == "app/data/loader.py"


# ---------------------------------------------------------------------------
# 7. Loader-level integration tests: gateway_master, field_visits, telemetry
# ---------------------------------------------------------------------------


def test_gateway_master_loader_canonicalization(tmp_path: pathlib.Path):
    """Verify load_gateway_master applies production canonicalization during ingestion."""
    csv_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639ea5602c2,tenant_b,Gebäude,Bayern,Modell_B,Omni,v1.0,,2021-05-10,2026-01-01,50\n"
        "  06:39:eA:56:02:c3  ,tenant_c,Rooftop,Hessen,Modell_C,Omni,v1.0,,2022-03-15,,75\n"
    )
    csv_path = tmp_path / "gateway_master.csv"
    csv_path.write_bytes(csv_content.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert "canonical_id" in df.columns
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert df.loc[1, "canonical_id"] == "0639EA5602C2"
    assert df.loc[2, "canonical_id"] == "0639EA5602C3"

    # Reject malformed raw ID in master
    malformed_content = csv_content + "INVALID_GW,tenant_d,Site,Region,Model,Ant,v1,,2020-01-01,,10\n"
    csv_path.write_bytes(malformed_content.encode("cp1252"))
    with pytest.raises(ValueError):
        load_gateway_master(tmp_path)


def test_field_visits_loader_canonicalization(tmp_path: pathlib.Path):
    """Verify load_field_visits applies production canonicalization during ingestion."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V002,0639ea5602c2,2025-09-10,2025-09-12,POWER_LOSS,INSPECTED,NONE,1.0\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    df = load_field_visits(tmp_path)
    assert "canonical_id" in df.columns
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert df.loc[1, "canonical_id"] == "0639EA5602C2"

    # Reject malformed raw ID in visits
    malformed_content = csv_content + "V003,BAD:ID:123,2025-09-15,2025-09-16,FAULT,REPAIRED,NONE,1.0\n"
    csv_path.write_text(malformed_content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_field_visits(tmp_path)


def test_telemetry_loader_canonicalization(tmp_path: pathlib.Path):
    """Verify load_telemetry_window applies production canonicalization during ingestion."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    raw_data = pd.DataFrame([
        {"gateway_id": "06:39:ea:56:02:c1", "ts_utc": "2026-01-10T12:00:00Z", "offline_duration_sec": 10.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0},
        {"gateway_id": "0639EA5602C2", "ts_utc": "2026-01-10T12:00:00Z", "offline_duration_sec": 20.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0},
    ])
    raw_data.to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)

    df = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc, start_utc=start_utc)
    assert "canonical_id" in df.columns
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"
    assert df.loc[1, "canonical_id"] == "0639EA5602C2"

    # Reject malformed raw ID in telemetry
    bad_data = pd.DataFrame([
        {"gateway_id": "NOT_AN_ID", "ts_utc": "2026-01-10T12:00:00Z", "offline_duration_sec": 10.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0}
    ])
    bad_data.to_parquet(tel_dir / "part-0.parquet")
    with pytest.raises(ValueError):
        load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc, start_utc=start_utc)


# ---------------------------------------------------------------------------
# 8. Downstream joins operating on canonical representation
# ---------------------------------------------------------------------------


def test_downstream_join_on_canonical_representation(tmp_path: pathlib.Path):
    """Verify downstream joins succeed on canonical_id where raw joins fail."""
    # Master has uppercase colon format
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Außenmast,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    # Visits has lowercase colon format
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:ea:56:02:c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    (tmp_path / "field_visits.csv").write_text(visits_csv, encoding="utf-8")

    # Telemetry has bare lowercase format
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)
    tel_df = pd.DataFrame([
        {"gateway_id": "0639ea5602c1", "ts_utc": "2026-01-15T12:00:00Z", "offline_duration_sec": 10.0, "disconnection_cnt": 0.0, "reboot_cnt": 0.0}
    ])
    tel_df.to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)

    m_df = load_gateway_master(tmp_path)
    v_df = load_field_visits(tmp_path)
    t_df = load_telemetry_window(tmp_path, cutoff_utc=cutoff_utc, start_utc=start_utc)

    # Raw join fails because string representations differ
    raw_join = pd.merge(m_df, t_df, on="gateway_id")
    assert len(raw_join) == 0, "Raw join should fail on mismatched formatting"

    # Canonical join succeeds seamlessly
    canonical_join_mv = pd.merge(m_df, v_df, on="canonical_id")
    assert len(canonical_join_mv) == 1
    assert canonical_join_mv.loc[0, "canonical_id"] == "0639EA5602C1"

    canonical_join_mt = pd.merge(m_df, t_df, on="canonical_id")
    assert len(canonical_join_mt) == 1
    assert canonical_join_mt.loc[0, "canonical_id"] == "0639EA5602C1"


# ---------------------------------------------------------------------------
# 9. Collision safety tests: equivalent deduplication vs distinct blocking
# ---------------------------------------------------------------------------


def test_collision_safety_master_equivalent_representations(tmp_path: pathlib.Path):
    """Equivalent representations in master deduplicate safely."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639ea5602c1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert len(df) == 1
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"


def test_collision_safety_master_distinct_records_block(tmp_path: pathlib.Path):
    """Distinct records colliding on same canonical ID raise ConflictingRecordError."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639ea5602c1,tenant_b,Basement,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    with pytest.raises(ConflictingRecordError):
        load_gateway_master(tmp_path)


def test_collision_safety_telemetry_equivalent_representations():
    """Equivalent telemetry records with different raw formatting deduplicate safely."""
    ts = pd.Timestamp("2026-01-10 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"gateway_id": "06:39:EA:56:02:C1", "canonical_id": "0639EA5602C1", "ts": ts, "val": 42.0},
        {"gateway_id": "0639ea5602c1", "canonical_id": "0639EA5602C1", "ts": ts, "val": 42.0},
    ])
    deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])
    assert dup_count == 1
    assert len(deduped) == 1
    assert deduped.iloc[0]["canonical_id"] == "0639EA5602C1"


def test_collision_safety_telemetry_distinct_records_block():
    """Distinct conflicting telemetry records for same canonical_id + ts raise ConflictingRecordError."""
    ts = pd.Timestamp("2026-01-10 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"gateway_id": "06:39:EA:56:02:C1", "canonical_id": "0639EA5602C1", "ts": ts, "val": 42.0},
        {"gateway_id": "0639ea5602c1", "canonical_id": "0639EA5602C1", "ts": ts, "val": 999.0},
    ])
    with pytest.raises(ConflictingRecordError):
        resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])


def test_collision_safety_field_visits_conflicting_visit_id_blocks(tmp_path: pathlib.Path):
    """Conflicting visit records with same visit_id raise ConflictingRecordError."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,NO_FAULT_FOUND,NONE,1.0\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ConflictingRecordError):
        load_field_visits(tmp_path)


def test_loader_numeric_gateway_id_leading_zeros_preserved(tmp_path: pathlib.Path):
    """Verify that all-numeric gateway IDs with leading zeros are not corrupted by CSV type inference."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "012345678901,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "001122334455,tenant_b,Basement,Bayern,Modell_B,Omni,v1.0,,2021-01-01,,50\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,012345678901,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V002,001122334455,2025-09-10,2025-09-12,POWER_LOSS,INSPECTED,NONE,1.0\n"
    )
    (tmp_path / "field_visits.csv").write_text(visits_csv, encoding="utf-8")

    m_df = load_gateway_master(tmp_path)
    assert m_df.loc[0, "canonical_id"] == "012345678901"
    assert m_df.loc[1, "canonical_id"] == "001122334455"

    v_df = load_field_visits(tmp_path)
    assert v_df.loc[0, "canonical_id"] == "012345678901"
    assert v_df.loc[1, "canonical_id"] == "001122334455"


def test_telemetry_loader_column_projection_with_canonical_id(tmp_path: pathlib.Path):
    """Verify load_telemetry_window safely projects derived canonical_id without parquet schema error."""
    tel_dir = tmp_path / "telemetry"
    tel_dir.mkdir(parents=True)

    raw_data = pd.DataFrame([
        {"gateway_id": "06:39:ea:56:02:c1", "ts_utc": "2026-01-10T12:00:00Z", "offline_duration_sec": 42.0},
    ])
    raw_data.to_parquet(tel_dir / "part-0.parquet")

    cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)

    projected = load_telemetry_window(
        tmp_path,
        cutoff_utc=cutoff_utc,
        start_utc=start_utc,
        columns=["canonical_id", "offline_duration_sec"],
    )
    assert list(projected.columns) == ["canonical_id", "offline_duration_sec"]
    assert projected.loc[0, "canonical_id"] == "0639EA5602C1"
    assert projected.loc[0, "offline_duration_sec"] == 42.0


def test_telemetry_duplicate_resolution_with_raw_ts_utc_differences():
    """Verify that equivalent telemetry records with different string formatting for ts_utc deduplicate safely."""
    ts = pd.Timestamp("2026-01-10 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"gateway_id": "06:39:EA:56:02:C1", "canonical_id": "0639EA5602C1", "ts_utc": "2026-01-10T12:00:00Z", "ts": ts, "val": 42.0},
        {"gateway_id": "0639ea5602c1", "canonical_id": "0639EA5602C1", "ts_utc": "2026-01-10 12:00:00+00:00", "ts": ts, "val": 42.0},
    ])
    deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])
    assert dup_count == 1
    assert len(deduped) == 1
    assert deduped.iloc[0]["canonical_id"] == "0639EA5602C1"


def test_resolve_telemetry_duplicates_infers_canonical_id():
    """Verify resolve_telemetry_duplicates auto-canonicalizes gateway_id if canonical_id column is absent."""
    ts = pd.Timestamp("2026-01-10 12:00:00", tz="UTC")
    df = pd.DataFrame([
        {"gateway_id": "06:39:EA:56:02:C1", "ts": ts, "val": 42.0},
        {"gateway_id": "0639ea5602c1", "ts": ts, "val": 42.0},
    ])
    deduped, dup_count = resolve_telemetry_duplicates(df, key_cols=["canonical_id", "ts"])
    assert dup_count == 1
    assert len(deduped) == 1
    assert deduped.iloc[0]["canonical_id"] == "0639EA5602C1"


def test_telemetry_loader_real_data_canonicalization():
    """Verify real telemetry dataset partitions load and produce valid canonical IDs."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "telemetry").exists():
        pytest.skip("data/telemetry not found in local workspace")

    cutoff_utc = dt.datetime(2025, 8, 3, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc)

    df = load_telemetry_window(data_dir, cutoff_utc=cutoff_utc, start_utc=start_utc)
    assert len(df) > 0
    assert "canonical_id" in df.columns
    assert df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()


# ---------------------------------------------------------------------------
# 10. Explicit edge case, anti-fake, real data, and connectivity tests
# ---------------------------------------------------------------------------


def test_canonicalize_leading_zero_id():
    """Verify that bare and colon-separated IDs with leading zeros normalize properly while preserving length and digits."""
    assert canonicalize_gateway_id("001122334455") == "001122334455"
    assert canonicalize_gateway_id("00:11:22:33:44:55") == "001122334455"
    assert canonicalize_gateway_id("00:ab:cd:ef:00:11") == "00ABCDEF0011"


def test_collision_safety_field_visits_equivalent_representations(tmp_path: pathlib.Path):
    """Equivalent visit records with different raw formatting collapse into one logical visit."""
    csv_content = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,06:39:EA:56:02:C1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )
    csv_path = tmp_path / "field_visits.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    df = load_field_visits(tmp_path)
    assert len(df) == 1
    assert df.loc[0, "canonical_id"] == "0639EA5602C1"


def test_anti_fake_loader_fails_without_canonicalization(monkeypatch):
    """Anti-fake test: prove that without canonicalize_gateway_id in the loader path, joining fails on formatted raw IDs."""
    import io
    monkeypatch.setattr("app.data.loader.canonicalize_gateway_id", lambda x: str(x))

    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    visits_csv = (
        "visit_id,gateway_id,requested_on,visited_on,reason_reported,outcome,parts_replaced,technician_hours\n"
        "V001,0639ea5602c1,2025-09-01,2025-09-03,COMM_FAULT,REPAIRED,MODEM,2.5\n"
    )

    m_df = pd.read_csv(io.StringIO(master_csv))
    v_df = pd.read_csv(io.StringIO(visits_csv))
    joined = pd.merge(m_df, v_df, on="gateway_id")
    assert len(joined) == 0, "Without production canonicalization, formatted raw IDs fail to join"


def test_anti_fake_raw_formatting_differences_do_not_create_false_conflict(tmp_path: pathlib.Path):
    """Anti-fake test: prove that raw formatting differences alone do NOT trigger ConflictingRecordError."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "  06:39:ea:56:02:c1  ,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    df = load_gateway_master(tmp_path)
    assert len(df) == 1
    assert df["canonical_id"].iloc[0] == "0639EA5602C1"


def test_anti_fake_semantic_differences_do_create_conflict(tmp_path: pathlib.Path):
    """Anti-fake test: prove that semantic attribute differences DO trigger ConflictingRecordError."""
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "0639EA5602C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639EA5602C1,tenant_b,Basement,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    with pytest.raises(ConflictingRecordError):
        load_gateway_master(tmp_path)


def test_real_data_gateway_master_and_field_visits_canonicalization():
    """Verify real master and field visits datasets load and canonicalize all IDs."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists() or not (data_dir / "field_visits.csv").exists():
        pytest.skip("real data files missing from data directory")

    m_df = load_gateway_master(data_dir)
    assert len(m_df) > 0
    assert "canonical_id" in m_df.columns
    assert m_df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()

    v_df = load_field_visits(data_dir)
    assert len(v_df) > 0
    assert "canonical_id" in v_df.columns
    assert v_df["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()

    joined = pd.merge(m_df, v_df, on="canonical_id", how="inner")
    assert len(joined) > 0
    assert joined["canonical_id"].str.match(r"^[0-9A-F]{12}$").all()


def test_e2e_cli_connectivity_with_canonical_id(tmp_path: pathlib.Path):
    """Verify end-to-end connectivity from CLI scripts/predict.py down to canonical IDs."""
    import subprocess
    import sys

    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639ea5602c2,tenant_b,Basement,Bayern,Modell_B,Omni,v1.0,,2021-05-10,,50\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))

    cmd = [
        sys.executable,
        "scripts/predict.py",
        "--data",
        str(tmp_path),
        "--week",
        "2026-02-02",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"CLI command failed: {res.stderr}"
    assert "Eligible gateways: 2 of 2" in res.stdout

