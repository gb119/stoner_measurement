"""Focused tests for Keithley 2182A-family nanovoltmeters."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.keithley import Keithley182, Keithley2182A
from stoner_measurement.instruments.nanovoltmeter import (
    NanovoltmeterCapabilities,
    NanovoltmeterFunction,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKeithley2182A:
    def test_default_protocol_is_scpi(self):
        k = Keithley2182A(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_measure_range_autorange_nplc(self):
        t = _null(responses=[b"1.0E-06\n", b"0.1\n", b"1\n", b"5.0\n"])
        k = Keithley2182A(transport=t)
        assert k.measure_voltage() == pytest.approx(1e-6)
        assert k.get_range() == pytest.approx(0.1)
        assert k.get_autorange() is True
        assert k.get_nplc() == pytest.approx(5.0)

    def test_function_filter_trigger_and_buffer(self):
        t = _null(responses=[b'"VOLT"\n', b"1\n", b"5\n", b"BUS\n", b"7\n", b"2\n", b"1.0,2.0\n"])
        k = Keithley2182A(transport=t)
        assert k.get_measure_function() == NanovoltmeterFunction.VOLT
        assert k.get_filter_enabled() is True
        assert k.get_filter_count() == 5
        assert k.get_trigger_source() == NanovoltmeterTriggerSource.BUS
        assert k.get_trigger_count() == 7
        assert k.get_buffer_count() == 2
        assert k.read_buffer() == pytest.approx((1.0, 2.0))

    def test_setters_and_limits(self):
        t = _null()
        k = Keithley2182A(transport=t)
        k.set_range(0.1)
        k.set_autorange(False)
        k.set_nplc(1.0)
        k.set_measure_function(NanovoltmeterFunction.TEMP)
        k.set_filter_enabled(True)
        k.set_filter_count(3)
        k.set_trigger_source(NanovoltmeterTriggerSource.EXT)
        k.set_trigger_count(2)
        k.initiate()
        k.abort()
        k.clear_buffer()
        assert t.write_log[-5:] == [
            b":TRIG:SOUR EXT\n",
            b":TRIG:COUN 2\n",
            b":INIT\n",
            b":ABOR\n",
            b":TRAC:CLE\n",
        ]
        with pytest.raises(ValueError):
            k.set_range(0.0)
        with pytest.raises(ValueError):
            k.set_nplc(0.0)
        with pytest.raises(ValueError):
            k.set_filter_count(0)
        with pytest.raises(ValueError):
            k.set_trigger_count(0)
        with pytest.raises(ValueError):
            k.read_buffer(0)

    def test_extended_controls(self):
        t = _null()
        k = Keithley2182A(transport=t)
        k.set_digits(6)
        k.set_analog_filter_enabled(True)
        k.set_relative_enabled(False)
        k.set_buffer_size(8)
        k.set_buffer_feed_sense()
        k.set_buffer_feed_continuous_next()
        assert t.write_log == [
            b":SENS:VOLT:DIG 6\n",
            b":SENS:VOLT:LPAS:STAT 1\n",
            b":SENS:VOLT:REF:STAT 0\n",
            b":TRAC:POIN 8\n",
            b":TRAC:FEED SENS\n",
            b":TRAC:FEED:CONT NEXT\n",
        ]
        with pytest.raises(ValueError):
            k.set_digits(3)
        with pytest.raises(ValueError):
            k.set_digits(9)
        with pytest.raises(ValueError):
            k.set_buffer_size(0)

    def test_capabilities(self):
        caps = Keithley2182A(transport=_null()).get_capabilities()
        assert isinstance(caps, NanovoltmeterCapabilities)
        assert caps.has_filter
        assert caps.has_trigger
        assert caps.has_buffer


class TestKeithley2182Variants:
    def test_keithley182_inherits_2182a_behaviour(self):
        t = _null()
        k = Keithley182(transport=t)
        k.abort()
        assert t.write_log[-1] == b":ABOR\n"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
