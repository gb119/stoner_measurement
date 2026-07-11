"""Tests for Leybold pressure-gauge controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.leybold import LeyboldCenterThree, LeyboldDisplayThree
from stoner_measurement.instruments.pressure_controller import PressureStatus, PressureUnit
from stoner_measurement.instruments.transport import NullTransport


def _ack_payload(payload: str) -> list[bytes]:
    return [b"\x06\r\n", payload.encode("ascii") + b"\r\n"]


def test_center_three_reads_single_pressure() -> None:
    transport = NullTransport(responses=[*_ack_payload("0,1.2500E-01"), *_ack_payload("0")])
    controller = LeyboldCenterThree(transport)
    controller.connect()

    reading = controller.read_pressure(1)

    assert reading.channel == 1
    assert reading.value == pytest.approx(0.125)
    assert reading.status is PressureStatus.OK
    assert reading.unit is PressureUnit.MBAR
    assert transport.write_log == [b"PR1\r", b"\x05", b"UNI\r", b"\x05"]


def test_center_three_suppresses_invalid_pressure_values() -> None:
    transport = NullTransport(responses=[*_ack_payload("2,9.9900E+09"), *_ack_payload("2")])
    controller = LeyboldCenterThree(transport)
    controller.connect()

    reading = controller.read_pressure(2)

    assert reading.value is None
    assert reading.status is PressureStatus.OVERRANGE
    assert reading.unit is PressureUnit.PASCAL


def test_center_three_reads_all_pressures() -> None:
    responses = [*_ack_payload("0,1.0E-03,4,0.0E+00,5,0.0E+00")]
    transport = NullTransport(responses=[*responses, *_ack_payload("1"), *_ack_payload("1"), *_ack_payload("1")])
    controller = LeyboldCenterThree(transport)
    controller.connect()

    readings = controller.read_all_pressures()

    assert readings[1].value == pytest.approx(1.0e-3)
    assert readings[2].status is PressureStatus.SWITCHED_OFF
    assert readings[3].status is PressureStatus.NO_TRANSMITTER


def test_center_three_raises_on_nak() -> None:
    transport = NullTransport(responses=[b"\x15\r\n", b"0001\r\n"])
    controller = LeyboldCenterThree(transport)
    controller.connect()

    with pytest.raises(InstrumentError, match="rejected"):
        controller.identify()

    assert transport.write_log == [b"PNR\r", b"\x05"]


def test_display_three_reads_analogue_pressure() -> None:
    transport = NullTransport()
    controller = LeyboldDisplayThree(
        transport,
        voltage_reader=lambda channel: 2.0 + channel,
        voltage_to_pressure=lambda channel, voltage: voltage * 10**-channel,
    )

    reading = controller.read_pressure(2)

    assert reading.value == pytest.approx(0.04)
    assert reading.status is PressureStatus.OK
    assert reading.raw_status == "analogue"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
