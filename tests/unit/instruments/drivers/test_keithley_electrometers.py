"""Focused tests for Keithley electrometer drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.electrometer import (
    ElectrometerCapabilities,
    ElectrometerDataFormat,
    ElectrometerFunction,
    ElectrometerTriggerConfiguration,
    ElectrometerTriggerSource,
)
from stoner_measurement.instruments.keithley import Keithley6514, Keithley6517, Keithley6845
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKeithleyElectrometers:
    def test_default_protocol_is_scpi(self):
        k = Keithley6514(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    @pytest.mark.parametrize("driver_cls", [Keithley6845, Keithley6514, Keithley6517])
    def test_measurement_functions(self, driver_cls):
        t = _null(responses=[b"'CURR','VOLT'\n"])
        k = driver_cls(transport=t)
        assert k.get_measure_functions() == (ElectrometerFunction.CURR, ElectrometerFunction.VOLT)
        k.set_measure_functions((ElectrometerFunction.CURR, ElectrometerFunction.RES))
        assert t.write_log == [
            b":SENS:FUNC?\n",
            b":SENS:FUNC 'CURR','RES'\n",
        ]

    @pytest.mark.parametrize("driver_cls", [Keithley6845, Keithley6514, Keithley6517])
    def test_range_and_autorange(self, driver_cls):
        t = _null(responses=[b"1.0E-6\n", b"1\n"])
        k = driver_cls(transport=t)
        assert k.get_range() == pytest.approx(1.0e-6)
        assert k.get_autorange() is True
        k.set_range(2.0e-6)
        k.set_autorange(False)
        assert t.write_log == [
            b":SENS:CURR:RANG?\n",
            b":SENS:CURR:RANG:AUTO?\n",
            b":SENS:CURR:RANG 2e-06\n",
            b":SENS:CURR:RANG:AUTO 0\n",
        ]

    @pytest.mark.parametrize("driver_cls", [Keithley6845, Keithley6514, Keithley6517])
    def test_filter_settings(self, driver_cls):
        t = _null(responses=[b"1\n", b"10\n"])
        k = driver_cls(transport=t)
        assert k.get_filter_enabled() is True
        assert k.get_filter_count() == 10
        k.set_filter_enabled(False)
        k.set_filter_count(5)
        assert t.write_log == [
            b":SENS:CURR:AVER:STAT?\n",
            b":SENS:CURR:AVER:COUN?\n",
            b":SENS:CURR:AVER:STAT 0\n",
            b":SENS:CURR:AVER:COUN 5\n",
        ]

    @pytest.mark.parametrize("driver_cls", [Keithley6845, Keithley6514, Keithley6517])
    def test_trigger_model_buffer_and_data_format(self, driver_cls):
        t = _null(responses=[b"100\n", b"1.0,2.0\n", b"SRE\n"])
        k = driver_cls(transport=t)
        k.configure_trigger_model(
            ElectrometerTriggerConfiguration(
                trigger_source=ElectrometerTriggerSource.BUS,
                trigger_count=3,
                trigger_delay=0.02,
                arm_source=ElectrometerTriggerSource.IMM,
                arm_count=2,
            )
        )
        k.initiate()
        k.abort()
        k.set_buffer_size(100)
        assert k.get_buffer_size() == 100
        k.clear_buffer()
        assert k.read_buffer() == (1.0, 2.0)
        assert k.get_data_format() is ElectrometerDataFormat.SREAL
        k.set_data_format(ElectrometerDataFormat.ASCII)
        assert t.write_log == [
            b":TRIG:SOUR BUS\n",
            b":TRIG:COUN 3\n",
            b":TRIG:DEL 0.02\n",
            b":ARM:SOUR IMM\n",
            b":ARM:COUN 2\n",
            b":INIT\n",
            b":ABOR\n",
            b":TRAC:POIN 100\n",
            b":TRAC:POIN?\n",
            b":TRAC:CLE\n",
            b":TRAC:DATA?\n",
            b":FORM:DATA?\n",
            b":FORM:DATA ASC\n",
        ]

    def test_capabilities(self):
        caps = Keithley6517(transport=_null()).get_capabilities()
        assert isinstance(caps, ElectrometerCapabilities)
        assert caps.has_function_selection
        assert caps.has_filter
        assert caps.has_trigger_model
        assert caps.has_buffer
        assert caps.has_data_format


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
