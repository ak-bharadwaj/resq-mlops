"""Tests verifying --data PATH contract across all CLI entry points and loaders (Task 11 & Task 12)."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import pytest

from app.data.loader import load_gateway_master, load_field_visits, load_telemetry_window


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


def test_cli_predict_propagation_to_alternate_directory(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify scripts/predict.py --data PATH reads from alternate mounted data directory."""
    alt_data = tmp_path / "alt_data"
    alt_data.mkdir(parents=True)
    shutil.copy(repo_root / "data" / "gateway_master.csv", alt_data / "gateway_master.csv")
    shutil.copytree(repo_root / "data" / "telemetry", alt_data / "telemetry")

    out_csv = tmp_path / "pred.csv"
    cmd = [
        sys.executable,
        "scripts/predict.py",
        "--data",
        str(alt_data),
        "--week",
        "2026-02-02",
        "--output",
        str(out_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert str(alt_data.resolve()) in res.stdout
    assert "Eligible gateways: 15 selected" in res.stdout
    assert out_csv.exists()


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


def test_cli_make_submission_propagation_to_alternate_directory(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify scripts/make_submission.py --data PATH reads from alternate data directory."""
    alt_data = tmp_path / "alt_data_sub"
    alt_data.mkdir(parents=True)
    shutil.copy(repo_root / "data" / "gateway_master.csv", alt_data / "gateway_master.csv")
    shutil.copytree(repo_root / "data" / "telemetry", alt_data / "telemetry")

    out_csv = tmp_path / "sub.csv"
    cmd = [
        sys.executable,
        "scripts/make_submission.py",
        "--data",
        str(alt_data),
        "--output",
        str(out_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert "120 rows over 8 weeks" in res.stdout
    assert out_csv.exists()


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


def test_cli_train_data_flag_and_path_validation(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify scripts/train.py --data flag, path validation, and candidate materialization."""
    # 1. Non-existent path rejects cleanly with non-zero exit code
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

    # 2. Empty directory rejects cleanly with non-zero exit code
    cmd_empty = [
        sys.executable,
        "scripts/train.py",
        "--data",
        str(tmp_path),
    ]
    res_empty = subprocess.run(cmd_empty, capture_output=True, text=True)
    assert res_empty.returncode != 0
    assert "Missing gateway_master.csv" in res_empty.stderr or "failed" in res_empty.stderr

    # 3. Real/valid data directory succeeds and materializes candidate
    cand_out = tmp_path / "cand_test"
    cmd_valid = [
        sys.executable,
        "scripts/train.py",
        "--data",
        str(repo_root / "data"),
        "--candidate",
        "v_cli_test",
        "--output-dir",
        str(cand_out),
    ]
    res_val = subprocess.run(cmd_valid, capture_output=True, text=True)
    assert res_val.returncode == 0, f"train.py failed: {res_val.stderr}"
    assert "Materialized candidate model: v_cli_test" in res_val.stdout
    assert cand_out.exists()
    assert (cand_out / "manifest.json").exists()


def test_underlying_loaders_propagate_data_dir(tmp_path: pathlib.Path):
    """Verify loaders take explicit data_dir and do not hardcode ./data."""
    with pytest.raises(FileNotFoundError):
        load_gateway_master(tmp_path)

    with pytest.raises(FileNotFoundError):
        load_field_visits(tmp_path)
