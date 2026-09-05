"""Tests asserting runtime offline contract (zero socket connections during loading)."""
import pathlib
import socket
import pytest
import datetime as dt
from app.data.loader import (
    load_gateway_master,
    verify_field_visits_encoding,
    load_field_visits,
    get_gateway_eligibility,
    load_telemetry_window,
)


def test_runtime_offline_contract(monkeypatch):
    data_dir = pathlib.Path("data")
    if not (data_dir / "gateway_master.csv").exists():
        pytest.fail("data/gateway_master.csv required for offline contract test")

    def forbidden_connect(*args, **kwargs):
        raise RuntimeError("ATTEMPTED_NETWORK_CALL: Network access strictly forbidden during execution")

    # Monkeypatch low-level socket connection methods
    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    # 1. Execute actual production data loaders on real data
    master_df = load_gateway_master(data_dir)
    assert len(master_df) == 332

    enc = verify_field_visits_encoding(data_dir)
    assert enc in ("utf-8", "cp1252", "latin-1")

    visits_df = load_field_visits(data_dir)
    assert len(visits_df) == 642

    elig_df = get_gateway_eligibility(master_df, dt.date(2026, 2, 2))
    assert elig_df["is_eligible"].sum() > 0

    cutoff = dt.datetime(2025, 9, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    start = dt.datetime(2025, 8, 25, 0, 0, 0, tzinfo=dt.timezone.utc)
    tel_df = load_telemetry_window(data_dir, cutoff_utc=cutoff, start_utc=start)
    assert len(tel_df) > 0

    # 2. Verify that the socket trap actually fires when a network call IS attempted
    with pytest.raises(RuntimeError, match="ATTEMPTED_NETWORK_CALL"):
        s = socket.socket()
        s.connect(("127.0.0.1", 80))
