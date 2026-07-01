"""Focused tests for Keithley 2400-family source meters."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.keithley import Keithley2400, Keithley2410, Keithley2450
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    MeasureFunction,
    SourceMeterCapabilities,
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
    TriggerSource,
)
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKeithley2400:
    def test_default_protocol_is_scpi(self):
        k = Keithley2400(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_get_source_mode(self):
        t = _null(responses=[b"VOLT\n"])
        k = Keithley2400(transport=t)
        assert k.get_source_mode() == SourceMode.VOLT

    def test_set_source_mode_volt(self):
        t = _null()
        Keithley2400(transport=t).set_source_mode(SourceMode.VOLT)
        assert t.write_log[-1] == b":SOUR:FUNC:MODE VOLT\n"

    def test_set_source_mode_curr(self):
        t = _null()
        Keithley2400(transport=t).set_source_mode(SourceMode.CURR)
        assert t.write_log[-1] == b":SOUR:FUNC:MODE CURR\n"

    def test_source_mode_invalid_value_raises(self):
        with pytest.raises(ValueError):
            SourceMode("OHMS")

    def test_get_source_level(self):
        t = _null(responses=[b"1.000000E+00\n"])
        assert Keithley2400(transport=t).get_source_level() == 1.0

    def test_set_source_level(self):
        t = _null()
        Keithley2400(transport=t).set_source_level(1.5)
        assert t.write_log[-1] == b":SOUR:AMPL 1.5\n"

    def test_get_compliance(self):
        t = _null(responses=[b"1.000000E-01\n"])
        assert Keithley2400(transport=t).get_compliance() == pytest.approx(0.1)

    def test_get_compliance_current_mode_queries_voltage_protection(self):
        t = _null(responses=[b"1.000000E+01\n"])
        assert Keithley2400(transport=t).get_compliance(SourceMode.CURR) == pytest.approx(10.0)
        assert t.write_log == [b":SENS:VOLT:PROT?\n"]

    def test_set_compliance(self):
        t = _null()
        Keithley2400(transport=t).set_compliance(0.05)
        assert t.write_log[-1] == b":SENS:CURR:PROT 0.05\n"

    def test_set_compliance_current_mode_writes_voltage_protection(self):
        t = _null()
        Keithley2400(transport=t).set_compliance(5.0, SourceMode.CURR)
        assert t.write_log == [b":SENS:VOLT:PROT 5.0\n"]

    def test_set_compliance_from_resistance_current_mode(self):
        t = _null()
        result = Keithley2400(transport=t).set_compliance_from_resistance(
            1000.0,
            source_level=0.002,
            source_mode=SourceMode.CURR,
        )
        assert result == pytest.approx(2.0)
        assert t.write_log[-1] == b":SENS:VOLT:PROT 2.0\n"

    def test_get_nplc(self):
        t = _null(responses=[b"1.000000E+00\n"])
        assert Keithley2400(transport=t).get_nplc() == 1.0

    def test_set_nplc(self):
        t = _null()
        Keithley2400(transport=t).set_nplc(5.0)
        assert t.write_log[0] == b":SENS:VOLT:NPLC 5.0\n"
        assert t.write_log[1] == b":SENS:CURR:NPLC 5.0\n"

    def test_set_nplc_out_of_range_raises(self):
        with pytest.raises(ValueError, match="NPLC"):
            Keithley2400(transport=_null()).set_nplc(20.0)

    def test_measure_voltage(self):
        t = _null(responses=[b"+1.234567E+00\n"])
        assert Keithley2400(transport=t).measure_voltage() == pytest.approx(1.234567)

    def test_measure_current(self):
        t = _null(responses=[b"+1.000000E-03\n"])
        assert Keithley2400(transport=t).measure_current() == pytest.approx(0.001)

    def test_get_measure_functions(self):
        t = _null(responses=[b"'VOLT:DC','CURR:DC'\n"])
        assert Keithley2400(transport=t).get_measure_functions() == (
            MeasureFunction.VOLT,
            MeasureFunction.CURR,
        )

    def test_get_measure_functions_without_suffix(self):
        t = _null(responses=[b"'VOLT','CURR'\n"])
        assert Keithley2400(transport=t).get_measure_functions() == (
            MeasureFunction.VOLT,
            MeasureFunction.CURR,
        )

    def test_set_measure_functions(self):
        t = _null()
        Keithley2400(transport=t).set_measure_functions(
            (MeasureFunction.VOLT, MeasureFunction.CURR)
        )
        assert t.write_log[-1] == b":SENS:FUNC 'VOLT','CURR'\n"

    def test_measure_function_invalid_value_raises(self):
        with pytest.raises(ValueError):
            MeasureFunction("TEMP")

    def test_measure_resistance(self):
        t = _null(responses=[b"+1.200000E+03\n"])
        assert Keithley2400(transport=t).measure_resistance() == pytest.approx(1200.0)

    def test_measure_power(self):
        t = _null(responses=[b"+2.000000E+00,+5.000000E-01\n"])
        assert Keithley2400(transport=t).measure_power() == pytest.approx(1.0)

    def test_measure_power_raises_when_response_missing_current(self):
        t = _null(responses=[b"+2.000000E+00\n"])
        with pytest.raises(ValueError, match="both voltage and current"):
            Keithley2400(transport=t).measure_power()

    def test_configure_linear_sweep(self):
        t = _null(responses=[b"VOLT\n"])
        k = Keithley2400(transport=t)
        k.configure_source_sweep(
            SourceSweepConfiguration(
                start=0.0,
                stop=1.0,
                points=5,
                spacing=SweepSpacing.LIN,
                delay=0.01,
            )
        )
        assert t.write_log == [
            b":SOUR:FUNC:MODE?\n",
            b":SOUR:FUNC:MODE VOLT\n",
            b":SOUR:VOLT:MODE SWE\n",
            b":SOUR:VOLT:STAR 0.0\n",
            b":SOUR:VOLT:STOP 1.0\n",
            b":SOUR:SWE:POIN 5\n",
            b":SOUR:SWE:SPAC LIN\n",
            b":SOUR:DEL 0.01\n",
        ]

    def test_configure_log_sweep_requires_at_least_two_points(self):
        t = _null()
        k = Keithley2400(transport=t)
        with pytest.raises(ValueError, match="at least 2 points"):
            k.configure_source_sweep(
                SourceSweepConfiguration(
                    start=0.0,
                    stop=1.0,
                    points=1,
                    spacing=SweepSpacing.LOG,
                )
            )

    def test_configure_custom_sweep(self):
        t = _null(responses=[b"CURR\n"])
        k = Keithley2400(transport=t)
        k.configure_source_sweep(
            SourceSweepConfiguration(
                spacing=SweepSpacing.LIST,
                values=(1e-3, 2e-3, 3e-3),
                delay=0.1,
            )
        )
        assert t.write_log == [
            b":SOUR:FUNC:MODE?\n",
            b":SOUR:FUNC:MODE CURR\n",
            b":SOUR:CURR:MODE LIST\n",
            b":SOUR:LIST:CURR 0.001,0.002,0.003\n",
            b":SOUR:SWE:POIN 3\n",
            b":SOUR:DEL 0.1\n",
        ]

    def test_sweep_spacing_invalid_value_raises(self):
        with pytest.raises(ValueError):
            SweepSpacing("CUSTOM")

    def test_set_and_get_source_delay(self):
        t = _null(responses=[b"1.000000E-02\n"])
        k = Keithley2400(transport=t)
        k.set_source_delay(0.01)
        assert k.get_source_delay() == pytest.approx(0.01)
        assert t.write_log == [b":SOUR:DEL 0.01\n", b":SOUR:DEL?\n"]

    def test_set_source_delay_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            Keithley2400(transport=_null()).set_source_delay(-0.1)

    def test_configure_trigger_model(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.configure_trigger_model(
            TriggerModelConfiguration(
                trigger_source=TriggerSource.BUS,
                trigger_count=11,
                trigger_delay=0.25,
                arm_source=TriggerSource.IMM,
                arm_count=3,
            )
        )
        assert t.write_log == [
            b":TRIG:SOUR BUS\n",
            b":TRIG:COUN 11\n",
            b":TRIG:DEL 0.25\n",
            b":ARM:SOUR IMM\n",
            b":ARM:COUN 3\n",
        ]

    def test_trigger_source_invalid_value_raises(self):
        with pytest.raises(ValueError):
            TriggerSource("BAD")

    def test_initiate_and_abort(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.initiate()
        k.abort()
        assert t.write_log == [b":INIT\n", b":ABOR\n"]

    def test_buffer_control_and_readout(self):
        t = _null(responses=[b"250\n", b"1.0,2.0,3.0\n", b"4.0,5.0\n"])
        k = Keithley2400(transport=t)
        k.set_buffer_size(250)
        assert k.get_buffer_size() == 250
        k.clear_buffer()
        all_values = k.read_buffer()
        partial_values = k.read_buffer(2)
        assert all_values == pytest.approx((1.0, 2.0, 3.0))
        assert partial_values == pytest.approx((4.0, 5.0))
        assert t.write_log == [
            b":TRAC:POIN 250\n",
            b":TRAC:POIN?\n",
            b":TRAC:CLE\n",
            b":TRAC:DATA?\n",
            b":TRAC:DATA? 1,2\n",
        ]

    def test_read_buffer_records_parses_explicit_format(self):
        t = _null(responses=[b"1,2,3,4,5,6,7,8,9,10\n"])
        records = Keithley2400(transport=t).read_buffer_records(
            ("VOLT", "CURR", "RES", "TIME", "STAT")
        )
        assert len(records) == 2
        assert records[0].voltage == pytest.approx(1.0)
        assert records[0].current == pytest.approx(2.0)
        assert records[0].resistance == pytest.approx(3.0)
        assert records[0].time == pytest.approx(4.0)
        assert records[0].status == pytest.approx(5.0)
        assert t.write_log == [
            b":FORM:DATA ASC\n",
            b":FORM:ELEM VOLT,CURR,RES,TIME,STAT\n",
            b":TRAC:DATA?\n",
        ]

    def test_check_error_queue_returns_terminating_no_error(self):
        t = _null(responses=[b'-200,"Execution error"\n', b'0,"No error"\n'])
        errors = Keithley2400(transport=t).check_error_queue(raise_on_error=False)
        assert errors == ((-200, "Execution error"), (0, "No error"))

    def test_check_error_queue_raises_on_instrument_error(self):
        t = _null(responses=[b'-200,"Execution error"\n', b'0,"No error"\n'])
        with pytest.raises(RuntimeError, match="Execution error"):
            Keithley2400(transport=t).check_error_queue()

    def test_check_error_queue_accepts_plain_no_error_message(self):
        t = _null(responses=[b'0,"No error"\n'])
        assert Keithley2400(transport=t).check_error_queue(
            raise_on_error=False
        ) == ((0, "No error"),)

    def test_buffer_size_validation(self):
        with pytest.raises(ValueError, match="positive"):
            Keithley2400(transport=_null()).set_buffer_size(0)
        with pytest.raises(ValueError, match="positive"):
            Keithley2400(transport=_null()).read_buffer(0)

    def test_read_buffer_malformed_numeric_response_raises(self):
        t = _null(responses=[b"1.0,,2.0\n"])
        with pytest.raises(ValueError, match="Malformed numeric response"):
            Keithley2400(transport=t).read_buffer()

    def test_read_buffer_non_numeric_response_raises(self):
        t = _null(responses=[b"abc,1.0\n"])
        with pytest.raises(ValueError, match="Malformed numeric response"):
            Keithley2400(transport=t).read_buffer()

    def test_read_buffer_empty_response_returns_empty_tuple(self):
        t = _null(responses=[b"\n"])
        assert Keithley2400(transport=t).read_buffer() == ()

    def test_output_enabled_true(self):
        t = _null(responses=[b"1\n"])
        assert Keithley2400(transport=t).output_enabled() is True

    def test_output_enabled_false(self):
        t = _null(responses=[b"0\n"])
        assert Keithley2400(transport=t).output_enabled() is False

    def test_enable_output_on(self):
        t = _null()
        Keithley2400(transport=t).enable_output(True)
        assert t.write_log[-1] == b":OUTP:STAT 1\n"

    def test_enable_output_off(self):
        t = _null()
        Keithley2400(transport=t).enable_output(False)
        assert t.write_log[-1] == b":OUTP:STAT 0\n"

    def test_get_capabilities(self):
        caps = Keithley2400(transport=_null()).get_capabilities()
        assert isinstance(caps, SourceMeterCapabilities)
        assert caps.has_function_selection
        assert caps.has_sweep
        assert caps.has_source_delay
        assert caps.has_trigger_model
        assert caps.has_buffer


class TestKeithley24xxVariants:
    def test_keithley2410_inherits_2400_behaviour(self):
        t = _null()
        k = Keithley2410(transport=t)
        k.enable_output(True)
        assert t.write_log[-1] == b":OUTP:STAT 1\n"

    def test_keithley2450_inherits_2400_behaviour(self):
        t = _null()
        k = Keithley2450(transport=t)
        k.enable_output(False)
        assert t.write_log[-1] == b":OUTP:STAT 0\n"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
