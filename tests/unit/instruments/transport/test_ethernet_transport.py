"""Tests for the TCP/IP socket transport."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import EthernetTransport


class TestEthernetTransportFraming:
    """Tests for frame-aware Ethernet transport reads."""

    class _FakeSocket:
        def __init__(self, chunks: list[bytes]):
            self._chunks = list(chunks)

        def recv(self, _num_bytes: int) -> bytes:
            if self._chunks:
                return self._chunks.pop(0)
            return b""

        def setblocking(self, _blocking: bool) -> None:
            pass

        def settimeout(self, _timeout: float) -> None:
            pass

    def test_read_accumulates_until_protocol_terminator(self):
        transport = EthernetTransport(host="127.0.0.1", port=5025)
        transport._socket = self._FakeSocket([b"+1.23", b"45\n"])
        transport._is_open = True
        transport.set_protocol(ScpiProtocol(max_frame_size=32))
        assert transport.read() == b"+1.2345\n"

    def test_read_raises_for_frame_longer_than_protocol_limit(self):
        transport = EthernetTransport(host="127.0.0.1", port=5025)
        transport._socket = self._FakeSocket([b"1234", b"5678", b"90\n"])
        transport._is_open = True
        transport.set_protocol(ScpiProtocol(max_frame_size=8))
        with pytest.raises(TimeoutError, match="terminator"):
            transport.read()

    def test_read_preserves_data_after_first_frame(self):
        transport = EthernetTransport(host="127.0.0.1", port=5025)
        transport._socket = self._FakeSocket([b"A\nB\n"])
        transport._is_open = True
        transport.set_protocol(ScpiProtocol(max_frame_size=32))
        assert transport.read() == b"A\n"
        assert transport.read() == b"B\n"
