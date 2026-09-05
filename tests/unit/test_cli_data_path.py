"""Tests verifying --data PATH contract across all CLI entry points and loaders (Task 11)."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import pytest

from app.data.loader import load_gateway_master, load_field_visits, load_telemetry_window


def test_cli_predict_propagation_to_alternate_directory(tmp_path: pathlib.Path):
    """Verify scripts/predict.py --data PATH reads from alternate mounted data directory."""
    sentinel_id = "0639EA999999"
    master_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed\n"
        f"{sentinel_id},tenant_test,Rooftop,Berlin,ModelX,Omni,v1.0,2025-01-01,100\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_content.encode("cp1252"))

    cmd = [
        sys.executable,
        "scripts/predict.py",
        "--data",
        str(tmp_path),
        "--week",
        "2026-02-02",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert str(tmp_path.resolve()) in res.stdout
    assert "Eligible gateways: 1 of 1" in res.stdout


def test_cli_predict_rejects_nonexistent_directory():
    """Verify scripts/predict.py --data rejects non-existent directory with non-zero exit code."""
    nonexistent = pathlib.Path("data_does_not_exist_12345")
    cmd = [
        sys.executable,
        "scripts/predict.py",
        "--data",
        str(nonexistent),
        "--week",
        "2026-02-02",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "does not exist" in res.stderr


def test_cli_make_submission_propagation_to_alternate_directory(tmp_path: pathlib.Path):
    """Verify scripts/make_submission.py --data PATH reads from alternate data directory."""
    rows = [
        f"0639EA9999{i:02d},tenant_test,Rooftop,Berlin,ModelX,Omni,v1.0,2025-01-01,100"
        for i in range(20)
    ]
    header = "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,installed_on,n_meters_installed"
    csv_content = header + "\n" + "\n".join(rows) + "\n"
    (tmp_path / "gateway_master.csv").write_bytes(csv_content.encode("cp1252"))

    cmd = [
        sys.executable,
        "scripts/make_submission.py",
        "--data",
        str(tmp_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert "Loaded 20 master gateways from" in res.stdout


def test_cli_make_submission_rejects_nonexistent_directory():
    """Verify scripts/make_submission.py --data rejects non-existent directory with non-zero exit code."""
    nonexistent = pathlib.Path("data_does_not_exist_12345")
    cmd = [
        sys.executable,
        "scripts/make_submission.py",
        "--data",
        str(nonexistent),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "does not exist" in res.stderr


def test_cli_train_data_flag_and_validation(tmp_path: pathlib.Path):
    """Verify scripts/train.py --data accepts alternate path and rejects non-existent directory."""
    # 1. Non-existent path rejects cleanly with non-zero code
    nonexistent = pathlib.Path("data_does_not_exist_12345")
    cmd_invalid = [
        sys.executable,
        "scripts/train.py",
        "--data",
        str(nonexistent),
    ]
    res_inv = subprocess.run(cmd_invalid, capture_output=True, text=True)
    assert res_inv.returncode != 0
    assert "does not exist" in res_inv.stderr

    # 2. Existing path proceeds to phase boundary notice (NotImplementedError)
    cmd_valid = [
        sys.executable,
        "scripts/train.py",
        "--data",
        str(tmp_path),
    ]
    res_val = subprocess.run(cmd_valid, capture_output=True, text=True)
    assert "NotImplementedError" in res_val.stderr or "Phase gating" in res_val.stderr


def test_underlying_loaders_propagate_data_dir(tmp_path: pathlib.Path):
    """Verify loaders take explicit data_dir and do not hardcode ./data."""
    # Ensure empty directory raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_gateway_master(tmp_path)

    with pytest.raises(FileNotFoundError):
        load_field_visits(tmp_path)
