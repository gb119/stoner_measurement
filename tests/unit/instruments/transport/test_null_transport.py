"""Tests for the simulation transport."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.transport import NullTransport


class TestNullTransport:
    def test_open_close_state(self):
        transport = NullTransport()
        assert not transport.is_open
        transport.open()
        assert transport.is_open
        transport.close()
        assert not transport.is_open

    def test_write_and_log(self):
        transport = NullTransport()
        transport.open()
        transport.write(b"CMD\n")
        assert transport.write_log == [b"CMD\n"]

    def test_read_returns_queued_response(self):
        transport = NullTransport(responses=[b"resp\n"])
        transport.open()
        assert transport.read() == b"resp\n"

    def test_read_returns_empty_when_exhausted(self):
        transport = NullTransport()
        transport.open()
        assert transport.read() == b""

    def test_read_until_returns_next_response(self):
        transport = NullTransport(responses=[b"hello\n"])
        transport.open()
        assert transport.read_until(b"\n") == b"hello\n"

    def test_queue_response(self):
        transport = NullTransport()
        transport.open()
        transport.queue_response(b"dynamic\n")
        assert transport.read() == b"dynamic\n"

    def test_clear_log(self):
        transport = NullTransport(responses=[b"x\n"])
        transport.open()
        transport.write(b"CMD\n")
        transport.clear_log()
        assert transport.write_log == []
        assert transport.read() == b""

    def test_write_raises_when_closed(self):
        transport = NullTransport()
        with pytest.raises(ConnectionError):
            transport.write(b"CMD\n")

    def test_read_raises_when_closed(self):
        transport = NullTransport()
        with pytest.raises(ConnectionError):
            transport.read()

    def test_context_manager(self):
        with NullTransport() as transport:
            assert transport.is_open
        assert not transport.is_open
