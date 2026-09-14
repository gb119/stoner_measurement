"""Tests for generic character-echo serial transport behavior."""

from __future__ import annotations

from collections import deque

import pytest

from stoner_measurement.instruments.protocol import SignalRecoveryProtocol
from stoner_measurement.instruments.transport import EchoSerialTransport
from stoner_measurement.instruments.transport.base import BaseTransport


class _FakeSerial:
    def __init__(self) -> None:
        self.is_open = True
        self.echoes: deque[bytes] = deque()
        self.response = bytearray()
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        self.echoes.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        if self.echoes:
            return self.echoes.popleft()
        if not self.response:
            return b""
        result = bytes(self.response[:size])
        del self.response[:size]
        return result

    def read_until(self, terminator: bytes, size: int) -> bytes:
        end = self.response.find(terminator)
        if end < 0:
            end = min(len(self.response), size) - len(terminator)
        end = min(end + len(terminator), size)
        result = bytes(self.response[:end])
        del self.response[:end]
        return result


def _transport(fake: _FakeSerial, suffixes: tuple[bytes, ...] = ()) -> EchoSerialTransport:
    transport = object.__new__(EchoSerialTransport)
    BaseTransport.__init__(transport, timeout=0.1)
    transport.port = "COM1"
    transport._serial = fake
    transport._is_open = True
    transport.response_suffixes = suffixes
    transport.set_protocol(SignalRecoveryProtocol())
    return transport


def test_write_uses_character_echo_handshake():
    fake = _FakeSerial()
    transport = _transport(fake)

    transport.write(b"ID\r\n")

    assert fake.writes == [b"I", b"D", b"\r", b"\n"]


@pytest.mark.parametrize("suffix", [b"*", b"?"])
def test_read_includes_configured_response_suffix(suffix: bytes):
    fake = _FakeSerial()
    fake.response.extend(b"7265\r\n" + suffix)
    transport = _transport(fake, (b"*", b"?"))

    assert transport.read() == b"7265\r\n" + suffix


def test_read_without_suffix_uses_normal_serial_framing():
    fake = _FakeSerial()
    fake.response.extend(b"OK\r\n")
    transport = _transport(fake)

    assert transport.read() == b"OK\r\n"


def test_write_rejects_missing_echo():
    fake = _FakeSerial()
    transport = _transport(fake)

    def no_echo(data: bytes) -> int:
        fake.writes.append(data)
        return len(data)

    fake.write = no_echo  # type: ignore[method-assign]

    with pytest.raises(TimeoutError, match="did not echo"):
        transport.write(b"I")


def test_constructor_rejects_unequal_response_suffix_lengths():
    with pytest.raises(ValueError, match="equal lengths"):
        EchoSerialTransport("COM1", response_suffixes=(b"*", b"ERR"))


def test_signal_recovery_protocol_allows_full_curve_frames():
    assert SignalRecoveryProtocol().max_frame_size == 4 * 1024 * 1024
