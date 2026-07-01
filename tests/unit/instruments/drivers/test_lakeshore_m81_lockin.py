"""Focused tests for the Lakeshore M81 lock-in driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.lakeshore import LakeshoreM81LockIn
from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifierCapabilities,
    LockInInputCoupling,
    LockInReferenceSource,
)
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestLakeshoreM81LockIn:
    def test_default_protocol_is_scpi(self):
        k = LakeshoreM81LockIn(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_measure_xy_and_rt(self):
        t = _null(responses=[b"1.2\n", b"-3.4\n", b"5.6\n", b"30.0\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        x, y = k.measure_xy()
        assert x == pytest.approx(1.2)
        assert y == pytest.approx(-3.4)
        r, theta = k.measure_rt()
        assert r == pytest.approx(5.6)
        assert theta == pytest.approx(30.0)

    def test_sensitivity_and_time_constant(self):
        t = _null(responses=[b"1e-3\n", b"0.1\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=2)
        assert k.get_sensitivity() == pytest.approx(1e-3)
        assert k.get_time_constant() == pytest.approx(0.1)
        k.set_sensitivity(2e-3)
        k.set_time_constant(0.3)
        assert t.write_log == [b":SENS2:LIA:RANG 2e-03\n", b":SENS2:LIA:TC 0.3\n"]

    def test_reference_source_and_phase(self):
        t = _null(responses=[b"INT\n", b"-15.0\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        assert k.get_reference_source() is LockInReferenceSource.INTERNAL
        assert k.get_reference_phase() == pytest.approx(-15.0)
        k.set_reference_source(LockInReferenceSource.EXTERNAL)
        k.set_reference_phase(45.0)
        assert t.write_log == [b":SENS1:LIA:RSRC EXT\n", b":SENS1:LIA:PHAS 45.0\n"]

    def test_get_reference_frequency_without_source_slot(self):
        t = _null(responses=[b"137.0\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        assert k.get_reference_frequency() == pytest.approx(137.0)
        assert t.write_log == []

    def test_set_reference_frequency_without_source_slot_raises(self):
        k = LakeshoreM81LockIn(transport=_null(), sense_slot=1)
        with pytest.raises(NotImplementedError):
            k.set_reference_frequency(100.0)

    def test_reference_frequency_with_source_slot(self):
        t = _null(responses=[b"100.0\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1, source_slot=2)
        assert k.get_reference_frequency() == pytest.approx(100.0)
        k.set_reference_frequency(200.0)
        assert t.write_log == [b":SOUR2:FREQ 200.0\n"]

    def test_harmonic(self):
        t = _null(responses=[b"5\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        assert k.get_harmonic() == 5
        k.set_harmonic(10)
        assert t.write_log == [b":SENS1:LIA:HARM 10\n"]

    def test_filter_slope(self):
        t = _null(responses=[b"2\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        assert k.get_filter_slope() == 12
        k.set_filter_slope(18)
        assert t.write_log == [b":SENS1:LIA:FILP 3\n"]

    def test_input_coupling(self):
        t = _null(responses=[b"DC\n"])
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        assert k.get_input_coupling() is LockInInputCoupling.DC
        k.set_input_coupling(LockInInputCoupling.AC)
        assert t.write_log == [b":SENS1:LIA:CPLS AC\n"]

    def test_auto_phase(self):
        t = _null()
        k = LakeshoreM81LockIn(transport=t, sense_slot=1)
        k.auto_phase()
        assert t.write_log == [b":SENS1:LIA:APHS\n"]

    def test_validation(self):
        k = LakeshoreM81LockIn(transport=_null())
        with pytest.raises(ValueError):
            k.set_sensitivity(0.0)
        with pytest.raises(ValueError):
            k.set_time_constant(-1.0)
        with pytest.raises(ValueError):
            k.set_harmonic(0)
        with pytest.raises(ValueError):
            k.set_filter_slope(9)

    def test_capabilities_without_source_slot(self):
        caps = LakeshoreM81LockIn(transport=_null()).get_capabilities()
        assert isinstance(caps, LockInAmplifierCapabilities)
        assert not caps.has_reference_frequency_control
        assert caps.has_reference_phase_control
        assert caps.has_harmonic_selection
        assert caps.has_filter_slope_control
        assert caps.has_input_coupling_control
        assert caps.has_auto_phase
        assert not caps.has_reserve_mode_control
        assert not caps.has_output_offset
        assert caps.max_harmonic == 9999

    def test_capabilities_with_source_slot(self):
        caps = LakeshoreM81LockIn(transport=_null(), source_slot=2).get_capabilities()
        assert caps.has_reference_frequency_control


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
