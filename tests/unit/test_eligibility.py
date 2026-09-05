"""Unit tests for per-week gateway eligibility logic."""
import datetime as dt
import pandas as pd
import pytest
from app.data.loader import get_gateway_eligibility
from app.data.schema import MissingDataReason


def test_eligibility_boundary_cases():
    scored_monday = dt.date(2026, 2, 2)

    data = pd.DataFrame([
        # 1. Exactly on Monday -> eligible
        {"gateway_id": "0639EA560201", "installed_on": dt.date(2026, 2, 2), "decommissioned_on": None},
        # 2. Installed before Monday -> eligible
        {"gateway_id": "0639EA560202", "installed_on": dt.date(2026, 1, 15), "decommissioned_on": None},
        # 3. Installed 1 day after Monday -> INELIGIBLE_DATE
        {"gateway_id": "0639EA560203", "installed_on": dt.date(2026, 2, 3), "decommissioned_on": None},
        # 4. Decommissioned exactly on Monday -> INELIGIBLE_DATE (contract: decommissioned_on > Monday)
        {"gateway_id": "0639EA560204", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 2, 2)},
        # 5. Decommissioned 1 day after Monday -> eligible
        {"gateway_id": "0639EA560205", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 2, 3)},
        # 6. Decommissioned before Monday -> INELIGIBLE_DATE
        {"gateway_id": "0639EA560206", "installed_on": dt.date(2025, 1, 1), "decommissioned_on": dt.date(2026, 1, 31)},
    ])

    result = get_gateway_eligibility(data, scored_monday)

    # Convert to dict by gateway_id
    res_dict = result.set_index("gateway_id").to_dict(orient="index")

    # Assertions
    assert res_dict["0639EA560201"]["is_eligible"] is True
    assert pd.isna(res_dict["0639EA560201"]["exclusion_reason"]) or res_dict["0639EA560201"]["exclusion_reason"] is None

    assert res_dict["0639EA560202"]["is_eligible"] is True
    assert pd.isna(res_dict["0639EA560202"]["exclusion_reason"]) or res_dict["0639EA560202"]["exclusion_reason"] is None

    assert res_dict["0639EA560203"]["is_eligible"] is False
    assert res_dict["0639EA560203"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value

    assert res_dict["0639EA560204"]["is_eligible"] is False
    assert res_dict["0639EA560204"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value

    assert res_dict["0639EA560205"]["is_eligible"] is True
    assert pd.isna(res_dict["0639EA560205"]["exclusion_reason"]) or res_dict["0639EA560205"]["exclusion_reason"] is None

    assert res_dict["0639EA560206"]["is_eligible"] is False
    assert res_dict["0639EA560206"]["exclusion_reason"] == MissingDataReason.INELIGIBLE_DATE.value
