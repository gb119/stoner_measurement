"""Tests for direct Thorlabs Kinesis USB motor connections."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.thorlabs import ThorlabsHDR50, ThorlabsKDC101KPRMTE
from stoner_measurement.motor_control.engine import MotorControllerEngine


def test_engine_constructs_kinesis_driver_from_controller_serial(qapp, monkeypatch):
    """Kinesis USB addresses should be passed to the driver as serial numbers."""
    engine = MotorControllerEngine()
    connected = []
    monkeypatch.setattr(engine, "connect_instrument", connected.append)

    engine.connect_driver(
        "ThorlabsKDC101KPRMTE",
        "Kinesis USB",
        "  27500125  ",
    )

    assert len(connected) == 1
    assert isinstance(connected[0], ThorlabsKDC101KPRMTE)
    assert connected[0]._serial_number == "27500125"  # noqa: SLF001
    assert engine.connected_transport_name == "Kinesis USB"
    assert engine.connected_address == "27500125"
    engine.shutdown()


def test_engine_requires_kinesis_controller_serial(qapp):
    """A blank Kinesis address should fail before attempting hardware access."""
    engine = MotorControllerEngine()

    with pytest.raises(ValueError, match="serial number is required"):
        engine.connect_driver("ThorlabsKDC101KPRMTE", "Kinesis USB", " ")

    engine.shutdown()


def test_engine_accepts_hdr50_apt_driver_on_existing_usb_route(qapp, monkeypatch):
    """The legacy UI route should construct the new APT-backed HDR50 driver."""
    engine = MotorControllerEngine()
    connected = []
    monkeypatch.setattr(engine, "connect_instrument", connected.append)

    engine.connect_driver("ThorlabsHDR50", "Kinesis USB", "  70001234  ")

    assert len(connected) == 1
    assert isinstance(connected[0], ThorlabsHDR50)
    assert connected[0]._serial_number == "70001234"  # noqa: SLF001
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
