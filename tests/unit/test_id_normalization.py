"""Unit tests for canonical gateway ID normalization."""
import pytest
from app.data.loader import canonicalize_gateway_id


def test_canonicalize_bare_12hex():
    assert canonicalize_gateway_id("0639EA5602C1") == "0639EA5602C1"
    assert canonicalize_gateway_id("0639ea5602c1") == "0639EA5602C1"
    assert canonicalize_gateway_id("  0639ea5602c1  ") == "0639EA5602C1"


def test_canonicalize_colon_separated():
    assert canonicalize_gateway_id("06:39:EA:56:02:C1") == "0639EA5602C1"
    assert canonicalize_gateway_id("06:39:ea:56:02:c1") == "0639EA5602C1"
    assert canonicalize_gateway_id("  06:39:EA:56:02:C1  ") == "0639EA5602C1"


def test_canonicalize_invalid_formats():
    # Null or empty
    with pytest.raises(ValueError):
        canonicalize_gateway_id(None)
    with pytest.raises(ValueError):
        canonicalize_gateway_id("")
    with pytest.raises(ValueError):
        canonicalize_gateway_id("   ")

    # Non-hex characters
    with pytest.raises(ValueError):
        canonicalize_gateway_id("06:39:ZZ:56:02:C1")
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602CG")

    # Wrong length
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602")  # 10 chars
    with pytest.raises(ValueError):
        canonicalize_gateway_id("0639EA5602C1FF")  # 14 chars
