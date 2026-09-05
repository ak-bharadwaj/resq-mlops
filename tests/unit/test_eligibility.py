"""Dedicated unit tests for Task 5: Weekly Gateway Eligibility.

Covered Invariants:
1. Boundary cases: installed_on <= Monday AND (decommissioned_on is null OR decommissioned_on > Monday).
2. Decommissioned ON Monday is NOT > Monday -> INELIGIBLE_DATE.
3. Installed ON Monday -> Eligible.
4. Installed AFTER Monday -> INELIGIBLE_DATE.
5. Decommissioned AFTER Monday -> Eligible.
6. Real data assertion: Monday 2026-02-02 produces exactly 290 eligible gateways out of 332 in gateway_master.csv.
7. Anti-fake test: Telemetry presence/absence NEVER alters eligibility evaluation.
8. Preserves canonical_id and master metadata attributes.
9. Accepts dt.date, dt.datetime, and string date inputs.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pandas as pd
import pytest

from app.data.loader import get_gateway_eligibility, load_gateway_master
from app.data.schema import MissingDataReason


def test_eligibility_boundary_cases():
    """Verify exact date boundary conditions per frozen architecture v25."""
    scored_monday = dt.date(2026, 2, 2)

    data = pd.DataFrame([
        # 1. Exactly on Monday -> eligible
        {"gateway_id": "06:39:EA:56:02:01", "installed_on": dt.date(2026, 2, 2), "decommissioned_on": None},
        # 2. Installed before Monday -> eligible
        {"gateway_id": "0639ea560202", "installed_on": dt.date(2026, 1, 15), "decommissioned_on": None},
        # 3. Installed 1 day after Monday -> INELIGIBLE_DATE
        {"gateway_id": "0639ea560203", "installed_on": dt.date(2026, 2, 3), "decommissioned_on": None},
        # 4. Decommissioned exactly on Monday -> INELIGIBLE_DATE (contract: decommissioned_on > Monday)
        {"gateway_id": "0639ea560204", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 2, 2)},
        # 5. Decommissioned 1 day after Monday -> eligible
        {"gateway_id": "0639ea560205", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 2, 3)},
        # 6. Decommissioned before Monday -> INELIGIBLE_DATE
        {"gateway_id": "0639ea560206", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 1, 31)},
    ])

    result = get_gateway_eligibility(data, scored_monday)
    assert "canonical_id" in result.columns

    res_dict = result.set_index("canonical_id").to_dict(orient="index")

    # 1. Installed on Monday -> Eligible
    assert bool(res_dict["0639EA560201"]["is_eligible"]) is True
    assert pd.isna(res_dict["0639EA560201"]["exclusion_reason"]) or res_dict["0639EA560201"]["exclusion_reason"] is None

    # 2. Installed before Monday -> Eligible
    assert bool(res_dict["0639EA560202"]["is_eligible"]) is True
    assert pd.isna(res_dict["0639EA560202"]["exclusion_reason"]) or res_dict["0639EA560202"]["exclusion_reason"] is None

    # 3. Installed after Monday -> Ineligible
    assert bool(res_dict["0639EA560203"]["is_eligible"]) is False
    assert res_dict["0639EA560203"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value

    # 4. Decommissioned on Monday -> Ineligible
    assert bool(res_dict["0639EA560204"]["is_eligible"]) is False
    assert res_dict["0639EA560204"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value

    # 5. Decommissioned after Monday -> Eligible
    assert bool(res_dict["0639EA560205"]["is_eligible"]) is True
    assert pd.isna(res_dict["0639EA560205"]["exclusion_reason"]) or res_dict["0639EA560205"]["exclusion_reason"] is None

    # 6. Decommissioned before Monday -> Ineligible
    assert bool(res_dict["0639EA560206"]["is_eligible"]) is False
    assert res_dict["0639EA560206"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value


def test_eligibility_real_data_2026_02_02():
    """Verify real workspace data/gateway_master.csv yields exactly 290 eligible gateways for Monday 2026-02-02."""
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.skip("data/gateway_master.csv missing from local workspace")

    master_df = load_gateway_master(data_dir)
    assert len(master_df) == 332

    monday_date = dt.date(2026, 2, 2)
    eligible_df = get_gateway_eligibility(master_df, monday=monday_date)

    eligible_count = eligible_df["is_eligible"].sum()
    ineligible_count = (~eligible_df["is_eligible"]).sum()

    assert eligible_count == 290
    assert ineligible_count == 42
    assert len(eligible_df) == 332


def test_eligibility_anti_fake_telemetry_isolation():
    """Anti-fake test: prove eligibility is strictly date-driven and NEVER altered by telemetry presence or absence."""
    data = pd.DataFrame([
        # Gateway has 0 telemetry rows in window, but installed before Monday -> Must be ELIGIBLE!
        {"gateway_id": "0639ea560201", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": None, "telemetry_row_count": 0},
        # Gateway has 1000 telemetry rows in window, but decommissioned before Monday -> Must be INELIGIBLE!
        {"gateway_id": "0639ea560202", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 1, 1), "telemetry_row_count": 1000},
    ])

    result = get_gateway_eligibility(data, dt.date(2026, 2, 2))
    res_dict = result.set_index("canonical_id").to_dict(orient="index")

    # Telemetry absence does NOT make a valid date gateway ineligible
    assert bool(res_dict["0639EA560201"]["is_eligible"]) is True
    assert pd.isna(res_dict["0639EA560201"]["exclusion_reason"]) or res_dict["0639EA560201"]["exclusion_reason"] is None

    # Telemetry presence does NOT override decommissioning date
    assert bool(res_dict["0639EA560202"]["is_eligible"]) is False
    assert res_dict["0639EA560202"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value


def test_eligibility_preserves_canonical_id_and_master_attributes():
    """Verify get_gateway_eligibility preserves canonical_id and all master metadata columns."""
    data = pd.DataFrame([
        {
            "gateway_id": "06:39:EA:56:02:01",
            "tenant": "TENANT_A",
            "site_type": "Gebäude",
            "region": "NORTH",
            "hw_model": "V1",
            "antenna_type": "OMNI",
            "fw_version": "1.0.0",
            "installed_on": dt.date(2025, 1, 1),
            "decommissioned_on": None,
            "n_meters_installed": 5,
        }
    ])

    result = get_gateway_eligibility(data, dt.date(2026, 2, 2))
    assert result.loc[0, "canonical_id"] == "0639EA560201"
    assert result.loc[0, "tenant"] == "TENANT_A"
    assert result.loc[0, "site_type"] == "Gebäude"
    assert result.loc[0, "n_meters_installed"] == 5
    assert bool(result.loc[0, "is_eligible"]) is True
    assert result.loc[0, "exclusion_reason"] is None


def test_eligibility_accepts_string_and_datetime_monday_inputs():
    """Verify get_gateway_eligibility accepts str, dt.date, and dt.datetime Monday inputs."""
    data = pd.DataFrame([
        {"gateway_id": "0639ea560201", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": None}
    ])

    res_str = get_gateway_eligibility(data, "2026-02-02")
    res_dt = get_gateway_eligibility(data, dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc))
    res_date = get_gateway_eligibility(data, dt.date(2026, 2, 2))

    assert bool(res_str.loc[0, "is_eligible"]) is True
    assert bool(res_dt.loc[0, "is_eligible"]) is True
    assert bool(res_date.loc[0, "is_eligible"]) is True
