"""Protocol constants and pure codecs for the legacy X-ray controller."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol

FRAME_SIZE = 12


class XrayOpcode(IntEnum):
    """The complete set of opcodes recovered from the legacy application."""

    DISABLE_TWO_THETA = 0x80
    STEP_TWO_THETA_ANTICLOCKWISE = 0x82
    STEP_TWO_THETA_CLOCKWISE = 0x83
    DISABLE_THETA = 0x90
    STEP_THETA_ANTICLOCKWISE = 0x92
    STEP_THETA_CLOCKWISE = 0x93
    RESET_LIMIT_LATCH = 0xA0
    ZERO_TWO_THETA = 0xB0
    ZERO_THETA = 0xC0
    START_COUNT = 0xD0
    STOP_COUNT = 0xE0
    READ_SNAPSHOT = 0xF0


class XrayProtocolError(InstrumentError):
    """Base class for malformed X-ray controller data."""


class XrayFrameLengthError(XrayProtocolError):
    """A snapshot did not contain exactly twelve bytes."""


class XrayBcdError(XrayProtocolError):
    """A snapshot contained a non-decimal packed-BCD nibble."""


@dataclass(frozen=True)
class ControllerStatus:
    """Raw and provisional status flags from snapshot bytes one and two."""

    raw_motor: int
    raw_limits: int
    motor0_direction: bool
    motor0_enabled: bool
    motor1_direction: bool
    motor1_enabled: bool
    limit_input_1: bool
    limit_latch_1: bool
    data_ready: bool
    overflow_or_infinite: bool

    @classmethod
    def from_bytes(cls, motor: int, limits: int) -> ControllerStatus:
        """Decode provisional names while retaining both authoritative bytes."""
        return cls(
            raw_motor=motor,
            raw_limits=limits,
            motor0_direction=bool(motor & 0x01),
            motor0_enabled=bool(motor & 0x02),
            motor1_direction=bool(motor & 0x10),
            motor1_enabled=bool(motor & 0x20),
            limit_input_1=bool(limits & 0x01),
            limit_latch_1=bool(limits & 0x02),
            data_ready=bool(limits & 0x04),
            overflow_or_infinite=bool(limits & 0x08),
        )


@dataclass(frozen=True)
class XraySnapshot:
    """One atomic counter and two-axis position snapshot."""

    theta_deg: float
    two_theta_deg: float
    counts: int
    status: ControllerStatus
    raw_frame: bytes


class LegacyXrayProtocol(BaseProtocol):
    """Framing metadata for the controller's fixed binary response.

    The driver bypasses the text formatting API and writes opcodes directly.
    These formatting methods therefore reject strings rather than risk an
    accidental ASCII command or line terminator.
    """

    terminator = None

    @property
    def max_frame_size(self) -> int:
        return FRAME_SIZE

    def format_command(self, command: str) -> bytes:
        raise TypeError("The legacy X-ray controller accepts binary opcodes only.")

    def format_query(self, query: str) -> bytes:
        raise TypeError("The legacy X-ray controller accepts binary opcodes only.")

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        raise TypeError("Use decode_snapshot() for the binary X-ray response.")


def decode_le_bcd(field: bytes) -> int:
    """Decode packed decimal pairs whose least-significant digit comes first."""
    value = 0
    multiplier = 1
    for byte in field:
        low = byte & 0x0F
        high = (byte >> 4) & 0x0F
        if low > 9 or high > 9:
            raise XrayBcdError(f"Invalid packed-BCD byte 0x{byte:02X}.")
        value += low * multiplier + high * multiplier * 10
        multiplier *= 100
    return value


def decode_wrapped_six_digits(field: bytes) -> int:
    """Decode the controller's modulo-one-million signed representation."""
    raw = decode_le_bcd(field)
    return raw - 1_000_000 if raw >= 500_000 else raw


def decode_snapshot(frame: bytes) -> XraySnapshot:
    """Validate and decode one fixed twelve-byte response."""
    raw = bytes(frame)
    if len(raw) != FRAME_SIZE:
        raise XrayFrameLengthError(
            f"Expected {FRAME_SIZE} snapshot bytes, received {len(raw)}."
        )
    counts = decode_le_bcd(raw[2:6])
    two_theta = decode_wrapped_six_digits(raw[6:9]) / 200.0
    theta = decode_wrapped_six_digits(raw[9:12]) / 400.0
    return XraySnapshot(
        theta_deg=theta,
        two_theta_deg=two_theta,
        counts=counts,
        status=ControllerStatus.from_bytes(raw[0], raw[1]),
        raw_frame=raw,
    )
