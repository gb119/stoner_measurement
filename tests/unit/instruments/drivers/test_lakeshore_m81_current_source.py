"""Focused tests for the Lakeshore M81 current source driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.current_source import (
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
)
from stoner_measurement.instruments.lakeshore import LakeshoreM81CurrentSource
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestLakeshoreM81CurrentSource:
    def test_default_protocol_is_scpi(self):
        src = LakeshoreM81CurrentSource(transport=NullTransport())
        assert isinstance(src.protocol, ScpiProtocol)

    def test_set_and_get_balanced_source_level(self):
        t = _null(responses=[b"0.002\n"])
        src = LakeshoreM81CurrentSource(transport=t)
        assert src.get_source_level() == pytest.approx(0.002)
        src.set_source_level(0.003)
        assert t.write_log == [
            b":SOUR1:CURR?\n",
            b":SOUR1:CURR 0.003\n",
            b":SOUR2:CURR -0.003\n",
        ]

    def test_channel_level_validation(self):
        src = LakeshoreM81CurrentSource(transport=_null())
        with pytest.raises(ValueError, match="channels 1 and 2"):
            src.get_channel_level(3)

    def test_output_and_compliance(self):
        t = _null(responses=[b"1\n", b"1\n", b"20\n"])
        src = LakeshoreM81CurrentSource(transport=t)
        assert src.output_enabled() is True
        assert src.get_compliance_voltage() == pytest.approx(20.0)
        src.enable_output(False)
        src.set_compliance_voltage(15.0)
        assert t.write_log == [
            b":OUTP1:STAT?\n",
            b":OUTP2:STAT?\n",
            b":SOUR1:CURR:COMP?\n",
            b":OUTP1:STAT 0\n",
            b":OUTP2:STAT 0\n",
            b":SOUR1:CURR:COMP 15.0\n",
            b":SOUR2:CURR:COMP 15.0\n",
        ]

    def test_waveform_frequency_offset_and_capabilities(self):
        t = _null(responses=[b"SIN\n", b"17.5\n", b"1.0E-4\n"])
        src = LakeshoreM81CurrentSource(transport=t)
        assert src.get_waveform() is CurrentWaveform.SINE
        assert src.get_frequency() == pytest.approx(17.5)
        assert src.get_offset_current() == pytest.approx(1.0e-4)
        src.set_waveform(CurrentWaveform.DC)
        src.set_frequency(23.0)
        src.set_offset_current(2.0e-4)
        caps = src.get_capabilities()
        assert isinstance(caps, CurrentSourceCapabilities)
        assert caps.has_waveform_selection
        assert caps.has_frequency_control
        assert caps.has_offset_current
        assert caps.has_balanced_outputs
        assert caps.has_sweep
        assert not caps.has_pulsed_sweep
        assert caps.channel_count == 2
        assert t.write_log == [
            b":SOUR1:FUNC?\n",
            b":SOUR1:FREQ?\n",
            b":SOUR1:CURR:OFFS?\n",
            b":SOUR1:FUNC DC\n",
            b":SOUR2:FUNC DC\n",
            b":SOUR1:FREQ 23.0\n",
            b":SOUR2:FREQ 23.0\n",
            b":SOUR1:CURR:OFFS 0.0002\n",
            b":SOUR2:CURR:OFFS -0.0002\n",
        ]

    def test_frequency_validation(self):
        with pytest.raises(ValueError, match="positive"):
            LakeshoreM81CurrentSource(transport=_null()).set_frequency(-1.0)

    def test_balanced_list_sweep_configuration(self):
        t = _null()
        src = LakeshoreM81CurrentSource(transport=t)
        src.configure_sweep(
            CurrentSweepConfiguration(
                spacing=CurrentSweepSpacing.LIST,
                values=(1e-3, 2e-3, 3e-3),
            )
        )
        assert t.write_log == [
            b":SOUR1:SWE:MODE LIST\n",
            b":SOUR1:SWE:CUST:LIST 0.001,0.002,0.003\n",
            b":SOUR1:SWE:NPTS 3\n",
            b":SOUR2:SWE:MODE LIST\n",
            b":SOUR2:SWE:CUST:LIST -0.001,-0.002,-0.003\n",
            b":SOUR2:SWE:NPTS 3\n",
        ]

    def test_balanced_linear_sweep_configuration(self):
        t = _null()
        src = LakeshoreM81CurrentSource(transport=t)
        src.configure_sweep(
            CurrentSweepConfiguration(
                start=0.0,
                stop=1e-3,
                points=5,
                spacing=CurrentSweepSpacing.LIN,
            )
        )
        assert t.write_log == [
            b":SOUR1:SWE:MODE LIN\n",
            b":SOUR1:SWE:STAR 0.0\n",
            b":SOUR1:SWE:STOP 0.001\n",
            b":SOUR1:SWE:NPTS 5\n",
            b":SOUR2:SWE:MODE LIN\n",
            b":SOUR2:SWE:STAR -0.0\n",
            b":SOUR2:SWE:STOP -0.001\n",
            b":SOUR2:SWE:NPTS 5\n",
        ]

    def test_balanced_sweep_with_delay_and_count(self):
        t = _null()
        src = LakeshoreM81CurrentSource(transport=t)
        src.configure_sweep(
            CurrentSweepConfiguration(
                spacing=CurrentSweepSpacing.LIST,
                values=(1e-3, 2e-3),
                delay=0.1,
                count=2,
            )
        )
        assert b":SOUR1:SWE:DEL 0.1\n" in t.write_log
        assert b":SOUR2:SWE:DEL 0.1\n" in t.write_log
        assert b":SOUR1:SWE:COUN 2\n" in t.write_log
        assert b":SOUR2:SWE:COUN 2\n" in t.write_log

    def test_list_sweep_empty_raises(self):
        src = LakeshoreM81CurrentSource(transport=_null())
        with pytest.raises(ValueError, match="non-empty"):
            src.configure_sweep(CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=()))

    def test_balanced_sweep_start_and_abort(self):
        t = _null()
        src = LakeshoreM81CurrentSource(transport=t)
        src.sweep_start()
        src.sweep_abort()
        assert t.write_log == [
            b":SOUR1:SWE:ARM\n",
            b":SOUR2:SWE:ARM\n",
            b":SOUR1:SWE:ABOR\n",
            b":SOUR2:SWE:ABOR\n",
        ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
