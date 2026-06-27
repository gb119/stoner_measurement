"""Tests for the UDP socket transport."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.transport import UdpTransport


class TestUdpTransport:
    def test_constructor_stores_host_port(self):
        transport = UdpTransport(host="10.0.0.1", port=8000)
        assert transport.host == "10.0.0.1"
        assert transport.port == 8000

    def test_default_timeout(self):
        assert UdpTransport(host="10.0.0.1", port=8000).timeout == 2.0

    def test_custom_timeout(self):
        assert UdpTransport(host="10.0.0.1", port=8000, timeout=5.0).timeout == 5.0

    def test_initially_closed(self):
        assert not UdpTransport(host="10.0.0.1", port=8000).is_open

    def test_write_raises_when_closed(self):
        transport = UdpTransport(host="10.0.0.1", port=8000)
        with pytest.raises(ConnectionError):
            transport.write(b"CMD\n")

    def test_read_raises_when_closed(self):
        transport = UdpTransport(host="10.0.0.1", port=8000)
        with pytest.raises(ConnectionError):
            transport.read()

    def test_close_when_not_open_is_harmless(self):
        UdpTransport(host="10.0.0.1", port=8000).close()

    def test_exported_from_transport_package(self):
        import stoner_measurement.instruments.transport as transport

        assert transport.UdpTransport is UdpTransport
