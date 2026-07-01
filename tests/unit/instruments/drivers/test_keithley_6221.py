"""Focused tests for the Keithley 6221 current source driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
    PulsedSweepConfiguration,
)
from stoner_measurement.instruments.keithley import Keithley6221
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKeithley6221:
    def test_default_protocol_is_scpi(self):
        k = Keithley6221(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_get_set_source_level(self):
        t = _null(responses=[b"1.000000E-03\n"])
        k = Keithley6221(transport=t)
        assert k.get_source_level() == pytest.approx(1e-3)
        k.set_source_level(2e-3)
        assert t.write_log == [b":SOUR:CURR?\n", b":SOUR:CURR 0.002\n"]

    def test_get_set_compliance_voltage(self):
        t = _null(responses=[b"10\n"])
        k = Keithley6221(transport=t)
        assert k.get_compliance_voltage() == pytest.approx(10.0)
        k.set_compliance_voltage(8.5)
        assert t.write_log == [b":SOUR:CURR:COMP?\n", b":SOUR:CURR:COMP 8.5\n"]

    def test_output_enable(self):
        t = _null(responses=[b"1\n"])
        k = Keithley6221(transport=t)
        assert k.output_enabled() is True
        k.enable_output(False)
        assert t.write_log == [b":OUTP:STAT?\n", b":OUTP:STAT 0\n"]

    def test_waveform_frequency_and_offset(self):
        t = _null(responses=[b"SIN\n", b"2.5E-3\n", b"13.7\n", b"1.0E-4\n", b"1\n", b"4\n"])
        k = Keithley6221(transport=t)
        assert k.get_waveform() is CurrentWaveform.SINE
        assert k.get_waveform_amplitude() == pytest.approx(2.5e-3)
        assert k.get_frequency() == pytest.approx(13.7)
        assert k.get_offset_current() == pytest.approx(1.0e-4)
        assert k.phase_marker_enabled() is True
        assert k.get_phase_marker_output_line() == 4
        k.set_waveform(CurrentWaveform.DC)
        k.set_waveform_amplitude(2e-3)
        k.set_frequency(17.0)
        k.set_offset_current(-2.0e-4)
        k.enable_phase_marker(False)
        k.set_phase_marker_output_line(3)
        assert t.write_log == [
            b":SOUR:WAVE:FUNC?\n",
            b":SOUR:WAVE:AMPL?\n",
            b":SOUR:WAVE:FREQ?\n",
            b":SOUR:WAVE:OFFS?\n",
            b":SOUR:WAVE:PMAR:STAT?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":SOUR:WAVE:FUNC DC\n",
            b":SOUR:WAVE:AMPL 0.002\n",
            b":SOUR:WAVE:FREQ 17.0\n",
            b":SOUR:WAVE:OFFS -0.0002\n",
            b":SOUR:WAVE:PMAR:STAT 0\n",
            b":SOUR:WAVE:PMAR:OLIN 3\n",
        ]

    def test_set_frequency_validation(self):
        with pytest.raises(ValueError, match="positive"):
            Keithley6221(transport=_null()).set_frequency(0.0)
        with pytest.raises(ValueError, match="non-negative"):
            Keithley6221(transport=_null()).set_waveform_amplitude(-1.0)
        with pytest.raises(ValueError, match="range 1..6"):
            Keithley6221(transport=_null()).set_phase_marker_output_line(0)

    def test_get_capabilities(self):
        caps = Keithley6221(transport=_null()).get_capabilities()
        assert isinstance(caps, CurrentSourceCapabilities)
        assert caps.has_waveform_selection
        assert caps.has_frequency_control
        assert caps.has_offset_current
        assert not caps.has_balanced_outputs
        assert caps.has_sweep
        assert caps.has_pulsed_sweep
        assert caps.channel_count == 1

    def test_linear_sweep_configuration(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_sweep(
            CurrentSweepConfiguration(
                start=0.0,
                stop=1e-3,
                points=11,
                spacing=CurrentSweepSpacing.LIN,
                delay=0.05,
            )
        )
        assert t.write_log == [
            b":SOUR:SWE:SPAC LIN\n",
            b":SOUR:SWE:STAR 0.0\n",
            b":SOUR:SWE:STOP 0.001\n",
            b":SOUR:SWE:POIN 11\n",
            b":SOUR:DEL 0.05\n",
        ]

    def test_list_sweep_configuration(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_sweep(
            CurrentSweepConfiguration(
                spacing=CurrentSweepSpacing.LIST,
                values=(1e-3, 2e-3, 3e-3),
                delay=0.0,
            )
        )
        assert t.write_log == [
            b":SOUR:SWE:SPAC LIST\n",
            b":SOUR:LIST:CURR 0.001,0.002,0.003\n",
            b":SOUR:SWE:POIN 3\n",
            b":SOUR:LIST:DEL 0.0,0.0,0.0\n",
        ]

    def test_list_sweep_empty_values_raises(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="non-empty"):
            k.configure_sweep(
                CurrentSweepConfiguration(
                    spacing=CurrentSweepSpacing.LIST,
                    values=(),
                )
            )

    def test_sweep_with_repeat_count(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_sweep(
            CurrentSweepConfiguration(
                start=0.0,
                stop=1e-3,
                points=5,
                spacing=CurrentSweepSpacing.LIN,
                count=3,
            )
        )
        assert b":SOUR:SWE:COUN 3\n" in t.write_log

    def test_sweep_start_and_abort(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.sweep_start()
        k.sweep_abort()
        assert t.write_log == [
            b":OUTP:STAT 1\n",
            b":SOUR:SWE:ARM\n",
            b":INIT:IMM\n",
            b":SOUR:SWE:ABOR\n",
        ]

    def test_get_operating_status(self):
        t = _null([b"4\n"])
        k = Keithley6221(transport=t)
        assert k.get_operating_status() == 4
        assert t.write_log == [b":STAT:OPER:COND?\n"]

    def test_sweep_status_helpers(self):
        t = _null([b"2\n", b"4\n"])
        k = Keithley6221(transport=t)
        assert k.sweep_is_running() is True
        assert k.sweep_is_finished() is True

    def test_pulsed_list_sweep(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_pulsed_sweep(
            CurrentSweepConfiguration(
                spacing=CurrentSweepSpacing.LIST,
                values=(1e-3, 2e-3, 3e-3),
            ),
            PulsedSweepConfiguration(width=1e-3, off_time=5e-3, low_level=0.0),
        )
        assert t.write_log == [
            b":SOUR:SWE:SPAC LIST\n",
            b":SOUR:LIST:CURR 0.001,0.002,0.003\n",
            b":SOUR:SWE:POIN 3\n",
            b":SOUR:LIST:DEL 0.0,0.0,0.0\n",
            b":SOUR:PULS:STAT 1\n",
            b":SOUR:PULS:WIDT 0.001\n",
            b":SOUR:PULS:DEL 0.005\n",
            b":SOUR:PULS:CURR:LOW 0.0\n",
        ]

    def test_pulsed_sweep_width_validation(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="width"):
            k.configure_pulsed_sweep(
                CurrentSweepConfiguration(
                    spacing=CurrentSweepSpacing.LIST,
                    values=(1e-3,),
                ),
                PulsedSweepConfiguration(width=0.0, off_time=1e-3),
            )

    def test_pulsed_sweep_off_time_validation(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="off_time"):
            k.configure_pulsed_sweep(
                CurrentSweepConfiguration(
                    spacing=CurrentSweepSpacing.LIST,
                    values=(1e-3,),
                ),
                PulsedSweepConfiguration(width=1e-3, off_time=0.0),
            )

    def test_sweep_range_helpers(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.set_sweep_range_mode("AUTO")
        k.set_fixed_range(1e-3)
        k.set_sweep_count(2)
        assert t.write_log == [
            b":SOUR:SWE:RANG AUTO\n",
            b":SOUR:CURR:RANG 1.000000e-03\n",
            b":SOUR:SWE:COUN 2\n",
        ]
        with pytest.raises(ValueError):
            k.set_sweep_range_mode("INVALID")
        with pytest.raises(ValueError):
            k.set_fixed_range(0.0)
        with pytest.raises(ValueError):
            k.set_sweep_count(0)

    def test_configure_trigger_link_validation(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="output_line"):
            k.configure_trigger_link(output_line=0, input_line=2)
        with pytest.raises(ValueError, match="input_line"):
            k.configure_trigger_link(output_line=1, input_line=7)
        with pytest.raises(ValueError, match="different"):
            k.configure_trigger_link(output_line=3, input_line=3)

    def test_configure_trigger_link_no_conflict(self):
        t = _null(responses=[b"3\n", b"4\n", b"0\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:ILIN 2\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_olin_blocks_input(self):
        t = _null(responses=[b"2\n", b"4\n", b"0\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:OLIN 3\n",
            b":TRIG:ILIN 2\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_pmar_blocks_input(self):
        t = _null(responses=[b"3\n", b"4\n", b"1\n", b"2\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:ILIN 2\n",
            b":SOUR:WAVE:PMAR:OLIN 4\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_pmar_blocks_output(self):
        t = _null(responses=[b"3\n", b"4\n", b"1\n", b"1\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:ILIN 2\n",
            b":SOUR:WAVE:PMAR:OLIN 4\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_both_conflicts(self):
        t = _null(responses=[b"2\n", b"4\n", b"1\n", b"1\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:OLIN 3\n",
            b":TRIG:ILIN 2\n",
            b":SOUR:WAVE:PMAR:OLIN 4\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_serial_relay_helpers(self):
        t = _null(responses=[b"1.23\r\n\n"])
        k = Keithley6221(transport=t)
        k.send_serial_command("*IDN?")
        value = k.query_serial_command("READ?")
        assert value == "1.23"
        assert t.write_log[0].decode().startswith('SYST:COMM:SER:SEND "*IDN?\r\n"')
        assert t.write_log[1].decode().startswith('SYST:COMM:SER:SEND "READ?\r\n"')
        assert t.write_log[2].decode().strip() == "SYST:COMM:SER:ENT?"
        with pytest.raises(ValueError):
            k.query_serial_command("READ?", max_chunks=0)

    def test_query_serial_command_raises_on_bare_cr_without_lf(self):
        t = _null(responses=[b"1.23\r\n"])
        k = Keithley6221(transport=t)
        with pytest.raises(RuntimeError, match="no line terminator"):
            k.query_serial_command("READ?", max_chunks=1)

    def test_query_serial_command_max_chunks_exhausted(self):
        t = _null(responses=[b"part1\n", b"part2\n"])
        k = Keithley6221(transport=t)
        with pytest.raises(RuntimeError, match="no line terminator"):
            k.query_serial_command("READ?", max_chunks=2)

    def test_convenience_configure_custom_sweep(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_custom_sweep((1e-3, 2e-3, 3e-3), delay=0.01)
        assert t.write_log == [
            b":SOUR:SWE:SPAC LIST\n",
            b":SOUR:LIST:CURR 0.001,0.002,0.003\n",
            b":SOUR:SWE:POIN 3\n",
            b":SOUR:LIST:DEL 0.01,0.01,0.01\n",
        ]

    def test_list_sweep_batching_over_100_points(self):
        from stoner_measurement.instruments.keithley.k6221 import _LIST_BATCH_SIZE

        t = _null()
        k = Keithley6221(transport=t)
        values = tuple(float(i) * 1e-5 for i in range(150))
        k.configure_custom_sweep(values)
        writes = [w.decode().strip() for w in t.write_log]
        assert writes[0] == ":SOUR:SWE:SPAC LIST"
        first_batch_cmd = writes[1]
        assert first_batch_cmd.startswith(":SOUR:LIST:CURR ")
        first_vals = first_batch_cmd[len(":SOUR:LIST:CURR ") :].split(",")
        assert len(first_vals) == _LIST_BATCH_SIZE
        second_batch_cmd = writes[2]
        assert second_batch_cmd.startswith(":SOUR:LIST:CURR:APP ")
        second_vals = second_batch_cmd[len(":SOUR:LIST:CURR:APP ") :].split(",")
        assert len(second_vals) == 50
        assert writes[3] == f":SOUR:SWE:POIN {len(values)}"

    def test_list_sweep_exactly_100_points_no_append(self):
        t = _null()
        k = Keithley6221(transport=t)
        values = tuple(float(i) * 1e-5 for i in range(100))
        k.configure_custom_sweep(values)
        writes = [w.decode().strip() for w in t.write_log]
        app_cmds = [w for w in writes if w.startswith(":SOUR:LIST:CURR:APP")]
        assert app_cmds == []

    def test_configure_list_compliance_single_batch(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_list_compliance([5.0, 10.0, 15.0])
        writes = [w.decode().strip() for w in t.write_log]
        assert len(writes) == 1
        assert writes[0].startswith(":SOUR:LIST:COMP ")
        parts = writes[0][len(":SOUR:LIST:COMP ") :].split(",")
        assert len(parts) == 3

    def test_configure_list_compliance_multi_batch(self):
        t = _null()
        k = Keithley6221(transport=t)
        vals = [10.0] * 120
        k.configure_list_compliance(vals)
        writes = [w.decode().strip() for w in t.write_log]
        assert writes[0].startswith(":SOUR:LIST:COMP ")
        assert writes[1].startswith(":SOUR:LIST:COMP:APP ")
        first_parts = writes[0][len(":SOUR:LIST:COMP ") :].split(",")
        second_parts = writes[1][len(":SOUR:LIST:COMP:APP ") :].split(",")
        assert len(first_parts) == 100
        assert len(second_parts) == 20

    def test_configure_list_compliance_empty_raises(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="non-empty"):
            k.configure_list_compliance([])

    def test_convenience_configure_linear_sweep(self):
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_linear_sweep(0.0, 1e-3, 11)
        assert t.write_log[0] == b":SOUR:SWE:SPAC LIN\n"

    def test_base_sweep_raises_on_unsupported_driver(self):
        class _MinimalSource(CurrentSource):
            def get_source_level(self):
                return 0.0

            def set_source_level(self, v):
                pass

            def get_compliance_voltage(self):
                return 0.0

            def set_compliance_voltage(self, v):
                pass

            def output_enabled(self):
                return False

            def enable_output(self, s):
                pass

            def get_capabilities(self):
                return CurrentSourceCapabilities()

        src = _MinimalSource(_null(), ScpiProtocol())
        with pytest.raises(NotImplementedError, match="has_sweep"):
            src.configure_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIN)
            )
        with pytest.raises(NotImplementedError, match="has_pulsed_sweep"):
            src.configure_pulsed_sweep(
                CurrentSweepConfiguration(
                    spacing=CurrentSweepSpacing.LIST,
                    values=(1e-3,),
                ),
                PulsedSweepConfiguration(width=1e-3, off_time=1e-3),
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
