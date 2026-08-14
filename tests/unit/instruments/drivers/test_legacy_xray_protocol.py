"""Pure protocol tests for the legacy X-ray controller."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.xray import (
    XrayBcdError,
    XrayFrameLengthError,
    XrayOpcode,
    decode_le_bcd,
    decode_snapshot,
    decode_wrapped_six_digits,
)


def test_recovered_opcodes_are_exact_single_byte_values():
    assert {opcode.name: opcode.value for opcode in XrayOpcode} == {
        "DISABLE_TWO_THETA": 0x80,
        "STEP_TWO_THETA_ANTICLOCKWISE": 0x82,
        "STEP_TWO_THETA_CLOCKWISE": 0x83,
        "DISABLE_THETA": 0x90,
        "STEP_THETA_ANTICLOCKWISE": 0x92,
        "STEP_THETA_CLOCKWISE": 0x93,
        "RESET_LIMIT_LATCH": 0xA0,
        "ZERO_TWO_THETA": 0xB0,
        "ZERO_THETA": 0xC0,
        "START_COUNT": 0xD0,
        "STOP_COUNT": 0xE0,
        "READ_SNAPSHOT": 0xF0,
    }
    assert all(len(bytes([opcode])) == 1 for opcode in XrayOpcode)


def test_little_endian_packed_bcd_example():
    assert decode_le_bcd(bytes.fromhex("46 37")) == 3746


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("00 00 00", 0),
        ("99 99 49", 499_999),
        ("00 00 50", -500_000),
        ("99 99 99", -1),
    ],
)
def test_wrapped_six_digit_boundaries(field, expected):
    assert decode_wrapped_six_digits(bytes.fromhex(field)) == expected


def test_reference_snapshot_decodes_counts_positions_and_status_separately():
    snapshot = decode_snapshot(bytes.fromhex("A5 8F 56 34 12 00 00 02 00 00 04 00"))
    assert snapshot.counts == 123_456
    assert snapshot.two_theta_deg == 1.0
    assert snapshot.theta_deg == 1.0
    assert snapshot.status.raw_motor == 0xA5
    assert snapshot.status.raw_limits == 0x8F


def test_negative_reference_snapshot():
    snapshot = decode_snapshot(bytes.fromhex("00 00 01 00 00 00 00 98 99 00 96 99"))
    assert snapshot.counts == 1
    assert snapshot.two_theta_deg == -1.0
    assert snapshot.theta_deg == -1.0


@pytest.mark.parametrize("length", [0, 11, 13])
def test_wrong_frame_length_is_rejected(length):
    with pytest.raises(XrayFrameLengthError):
        decode_snapshot(bytes(length))


@pytest.mark.parametrize("bad", [b"\x0a", b"\xa0", b"\xff"])
def test_invalid_bcd_nibbles_are_rejected(bad):
    with pytest.raises(XrayBcdError):
        decode_le_bcd(bad)


def test_status_bytes_are_not_validated_as_bcd():
    snapshot = decode_snapshot(bytes.fromhex("FF FF 00 00 00 00 00 00 00 00 00 00"))
    assert snapshot.status.raw_motor == 0xFF


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
