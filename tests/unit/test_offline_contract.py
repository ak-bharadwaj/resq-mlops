"""Unit tests asserting offline execution contract (no socket connection attempts)."""
import socket
import pytest
from app.data.loader import canonicalize_gateway_id


def test_no_network_calls_during_loader_operations(monkeypatch):
    def fake_connect(*args, **kwargs):
        raise RuntimeError("Network call attempted during offline execution!")

    # Block socket.create_connection and socket.connect
    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    # Run canonicalization and contract verification - must never attempt network
    res = canonicalize_gateway_id("06:39:EA:56:02:C1")
    assert res == "0639EA5602C1"
