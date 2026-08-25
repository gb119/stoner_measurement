"""Focused tests for Keithley 2182A-family nanovoltmeters."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.instruments.electrometer import ElectrometerDataFormat
from stoner_measurement.instruments.keithley import Keithley2182A, KeithleyByteOrder
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
        k.set_filter_type("REPEAT")
        k.set_filter_type("WINDOW")
        k.set_trigger_delay(0.25)
        k.set_line_sync_enabled(True)
        k.set_autozero_enabled(False)
        k.set_analog_filter_enabled(True)
        k.set_relative_value(-0.5)
        k.set_relative_enabled(False)
        k.set_buffer_size(8)
        k.set_buffer_feed_sense()
        k.set_buffer_feed_continuous_next()
        assert t.write_log == [
            b":SENS:VOLT:DIG 6\n",
            b":SENS:VOLT:DFIL:TCON REP\n",
            b":SENS:VOLT:DFIL:TCON MOV\n",
            b":TRIG:DEL 0.25\n",
            b":SYST:LSYN 1\n",
            b":SYST:AZER 0\n",
            b":SENS:VOLT:LPAS:STAT 1\n",
            b":SENS:VOLT:REF -0.5\n",
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
        with pytest.raises(ValueError):
            k.set_filter_type("median")
        with pytest.raises(ValueError):
            k.set_trigger_delay(-0.1)
        with pytest.raises(ValueError):
            k.set_trigger_delay(1e6)
        with pytest.raises(ValueError):
            k.set_relative_value(121.0)

    def test_data_format_and_byte_order_are_cached(self):
        t = _null()
        k = Keithley2182A(transport=t)

        assert k.get_data_format() is ElectrometerDataFormat.ASCII
        assert k.get_byte_order() is KeithleyByteOrder.NORMAL
        k.set_data_format(ElectrometerDataFormat.SREAL)
        k.set_byte_order(KeithleyByteOrder.SWAPPED)
        k.set_data_format(ElectrometerDataFormat.SREAL)
        k.set_byte_order(KeithleyByteOrder.SWAPPED)

        assert k.get_data_format() is ElectrometerDataFormat.SREAL
        assert k.get_byte_order() is KeithleyByteOrder.SWAPPED
        assert t.write_log == [b":FORM:DATA SRE\n", b":FORM:BORD SWAP\n"]

    def test_buffer_size_is_cached_after_setting(self):
        t = _null()
        k = Keithley2182A(transport=t)
        k.set_buffer_size(8)
        k.set_buffer_size(8)

        assert k.get_buffer_size() == 8
        assert t.write_log == [b":TRAC:POIN 8\n"]

    @pytest.mark.parametrize(
        ("data_format", "byte_order", "dtype"),
        [
            (ElectrometerDataFormat.SREAL, KeithleyByteOrder.NORMAL, ">f4"),
            (ElectrometerDataFormat.SREAL, KeithleyByteOrder.SWAPPED, "<f4"),
            (ElectrometerDataFormat.DREAL, KeithleyByteOrder.NORMAL, ">f8"),
            (ElectrometerDataFormat.DREAL, KeithleyByteOrder.SWAPPED, "<f8"),
        ],
    )
    def test_binary_buffer_is_zero_copy_numpy_view(self, data_format, byte_order, dtype):
        expected = np.array([1.25, -2.5, 3.75], dtype=dtype)
        t = _null(responses=[b"#0" + expected.tobytes() + b"\n"])
        k = Keithley2182A(transport=t)
        k.set_data_format(data_format)
        k.set_byte_order(byte_order)

        result = k.read_buffer(count=3)

        assert isinstance(result, np.ndarray)
        np.testing.assert_array_equal(result, expected)
        assert result.flags.owndata is False
        assert t.write_log[-1] == b":TRAC:DATA?\n"

    def test_binary_buffer_requires_marker_and_whole_values(self):
        k = Keithley2182A(transport=_null())
        with pytest.raises(ValueError, match="#0"):
            k.parse_binary_floats(
                b"not binary",
                data_format=ElectrometerDataFormat.SREAL,
                byte_order=KeithleyByteOrder.NORMAL,
            )
        with pytest.raises(ValueError, match="whole number"):
            k.parse_binary_floats(
                b"#0abc",
                data_format=ElectrometerDataFormat.SREAL,
                byte_order=KeithleyByteOrder.NORMAL,
            )

    def test_binary_precision_can_be_inferred_from_count_and_length(self):
        expected = np.array([1.25, -2.5], dtype=">f8")

        result = Keithley2182A.parse_binary_floats(
            b"#0" + expected.tobytes() + b"\n",
            data_format=None,
            byte_order=KeithleyByteOrder.NORMAL,
            count=2,
        )

        assert result.dtype == np.dtype(">f8")
        np.testing.assert_array_equal(result, expected)

    def test_capabilities(self):
        caps = Keithley2182A(transport=_null()).get_capabilities()
        assert isinstance(caps, NanovoltmeterCapabilities)
        assert caps.has_filter
        assert caps.has_trigger
        assert caps.has_buffer
        assert caps.has_data_format
        assert caps.has_byte_order
        assert caps.fixed_voltage_ranges == (0.01, 0.1, 1.0, 10.0, 100.0, 120.0)
        assert caps.nplc_values == (0.1, 1.0, 10.0)
        assert caps.digit_values == (4, 5, 6, 7, 8)
        assert caps.filter_types == ("OFF", "REPEAT", "WINDOW")
        assert caps.supports_filter_count
        assert caps.supports_line_sync
        assert caps.supports_autozero
        assert caps.supports_safe_reset
        assert caps.relative_limits == (-120.0, 120.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
