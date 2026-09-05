"""Tests verifying --data PATH propagation into actual data-loading paths."""
import pathlib
import subprocess
import sys
import pandas as pd
import pytest


def test_cli_data_propagation_to_alternate_directory(tmp_path: pathlib.Path):
    # Create an alternate temporary data directory with a unique sentinel gateway
    sentinel_id = "0639EA999999"
    master_content = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        f"{sentinel_id},tenant_test,Rooftop,Berlin,ModelX,Omni,v1.0,2025-01-01,2025-01-01,,100\n"
    )
    master_file = tmp_path / "gateway_master.csv"
    master_file.write_text(master_content, encoding="cp1252")

    # Run scripts/predict.py pointing to alternate directory
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
    # Verify the output reports reading from the alternate directory
    assert str(tmp_path.resolve()) in res.stdout
    assert "Eligible gateways: 1 of 1" in res.stdout


def test_cli_data_rejects_nonexistent_directory():
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
