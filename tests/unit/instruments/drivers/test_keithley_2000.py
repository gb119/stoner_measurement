"""Focused tests for Keithley 2000-family digital multimeters."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.dmm import (
    DmmCapabilities,
    DmmFunction,
    DmmTriggerSource,
)
from stoner_measurement.instruments.keithley import Keithley2000, Keithley2700
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKeithley2000:
    def test_default_protocol_is_scpi(self):
        k = Keithley2000(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_measure_and_function_control(self):
        t = _null(responses=[b"1.234\n", b'"VOLT:DC"\n'])
        k = Keithley2000(transport=t)
        assert k.measure() == pytest.approx(1.234)
        assert k.get_measure_function() == DmmFunction.VOLT_DC
        k.set_measure_function(DmmFunction.CURR_DC)
        assert t.write_log[-1] == b':SENS:FUNC "CURR:DC"\n'

    def test_range_autorange_and_nplc(self):
        t = _null(
            responses=[
                b'"VOLT:DC"\n',
                b"10\n",
                b'"VOLT:DC"\n',
                b"1\n",
                b'"VOLT:DC"\n',
                b"1\n",
            ]
        )
        k = Keithley2000(transport=t)
        assert k.get_range() == pytest.approx(10.0)
        assert k.get_autorange() is True
        assert k.get_nplc() == pytest.approx(1.0)

    def test_filter_trigger_and_buffer(self):
        t = _null(
            responses=[
                b'"VOLT:DC"\n',
                b"1\n",
                b'"VOLT:DC"\n',
                b"10\n",
                b"BUS\n",
                b"3\n",
                b"5\n",
                b"1.0,2.0,3.0\n",
            ]
        )
        k = Keithley2000(transport=t)
        assert k.get_filter_enabled() is True
        assert k.get_filter_count() == 10
        assert k.get_trigger_source() == DmmTriggerSource.BUS
        assert k.get_trigger_count() == 3
        assert k.get_buffer_count() == 5
        assert k.read_buffer() == pytest.approx((1.0, 2.0, 3.0))

    def test_setters_and_limits(self):
        t = _null(
            responses=[
                b'"VOLT:DC"\n',
                b'"VOLT:DC"\n',
                b'"VOLT:DC"\n',
                b'"VOLT:DC"\n',
                b'"VOLT:DC"\n',
            ]
        )
        k = Keithley2000(transport=t)
        k.set_range(1.0)
        k.set_autorange(False)
        k.set_nplc(2.0)
        k.set_filter_enabled(True)
        k.set_filter_count(4)
        k.set_trigger_source(DmmTriggerSource.EXT)
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
            k.set_filter_count(0)
        with pytest.raises(ValueError):
            k.set_trigger_count(0)
        with pytest.raises(ValueError):
            k.read_buffer(0)

    def test_capabilities(self):
        caps = Keithley2000(transport=_null()).get_capabilities()
        assert isinstance(caps, DmmCapabilities)
        assert caps.has_filter
        assert caps.has_trigger
        assert caps.has_buffer


class TestKeithley2000Variants:
    def test_keithley2700_inherits_2000_behaviour(self):
        t = _null()
        k = Keithley2700(transport=t)
        k.abort()
        assert t.write_log[-1] == b":ABOR\n"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
