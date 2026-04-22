"""Tests for the instrument communication class hierarchy.

Covers:
- Correct ABC enforcement (direct instantiation raises TypeError).
- BaseInstrument composition: write, query, read, identify, reset.
- NullTransport record-keeping and context manager support.
- Protocol formatting and response parsing for SCPI, Oxford, and Lakeshore.
- Keithley2400 concrete driver methods.
- InstrumentError structured exception and error-checking paths.
"""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
    PulsedSweepConfiguration,
)
from stoner_measurement.instruments.dmm import (
    DigitalMultimeter,
    DmmCapabilities,
    DmmFunction,
    DmmTriggerSource,
)
from stoner_measurement.instruments.electrometer import (
    Electrometer,
    ElectrometerCapabilities,
    ElectrometerDataFormat,
    ElectrometerFunction,
    ElectrometerTriggerConfiguration,
    ElectrometerTriggerSource,
)
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.keithley import (
    Keithley182,
    Keithley2000,
    Keithley2182A,
    Keithley2400,
    Keithley2410,
    Keithley2450,
    Keithley2700,
    Keithley6221,
    Keithley6514,
    Keithley6517,
    Keithley6845,
)
from stoner_measurement.instruments.lakeshore import (
    Lakeshore335,
    Lakeshore336,
    Lakeshore340,
    Lakeshore525,
    LakeshoreM81CurrentSource,
)
from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInInputCoupling,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.magnet_controller import (
    MagnetController,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterCapabilities,
    NanovoltmeterFunction,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.oxford import (
    OxfordIPS120,
    OxfordITC503,
    OxfordMercuryTemperatureController,
)
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    MeasureFunction,
    SourceMeter,
    SourceMeterCapabilities,
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
    TriggerSource,
)
from stoner_measurement.instruments.srs import SRS830
from stoner_measurement.instruments.temperature_controller import (
    AlarmState,
    ControllerCapabilities,
    ControlMode,
    LoopStatus,
    PIDParameters,
    RampState,
    SensorStatus,
    TemperatureController,
    TemperatureReading,
    TemperatureStatus,
    ZoneEntry,
)
from stoner_measurement.instruments.transport import NullTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    t = NullTransport(responses=responses or [])
    t.open()
    return t


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestAbstractEnforcement:
    """Abstract enforcement for the instrument hierarchy.

    BaseInstrument inherits from ABC (making its metaclass ABCMeta) so that
    @abstractmethod decorators on its subclasses are properly enforced.
    It has no abstract methods of its own, so it is *not* directly prevented
    from instantiation — it can be used as a generic instrument accessor.

    The instrument-type intermediaries (TemperatureController, etc.) all carry
    @abstractmethod decorators and therefore cannot be instantiated directly.
    """

    def test_base_instrument_uses_abcmeta(self):
        from abc import ABCMeta

        assert isinstance(BaseInstrument, ABCMeta)

    def test_temperature_controller_is_abstract(self):
        with pytest.raises(TypeError):
            TemperatureController(NullTransport(), LakeshoreProtocol())  # type: ignore[abstract]

    def test_magnet_controller_is_abstract(self):
        with pytest.raises(TypeError):
            MagnetController(NullTransport(), OxfordProtocol())  # type: ignore[abstract]

    def test_source_meter_is_abstract(self):
        with pytest.raises(TypeError):
            SourceMeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_current_source_is_abstract(self):
        with pytest.raises(TypeError):
            CurrentSource(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_digital_multimeter_is_abstract(self):
        with pytest.raises(TypeError):
            DigitalMultimeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_nanovoltmeter_is_abstract(self):
        with pytest.raises(TypeError):
            Nanovoltmeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_electrometer_is_abstract(self):
        with pytest.raises(TypeError):
            Electrometer(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_lock_in_amplifier_is_abstract(self):
        with pytest.raises(TypeError):
            LockInAmplifier(NullTransport(), ScpiProtocol())  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# BaseInstrument (via Keithley2400 as a concrete stand-in)
# ---------------------------------------------------------------------------


class TestBaseInstrument:
    def test_connect_disconnect(self):
        t = NullTransport()
        k = Keithley2400(transport=t)
        assert not k.is_connected
        k.connect()
        assert k.is_connected
        k.disconnect()
        assert not k.is_connected

    def test_context_manager(self):
        t = NullTransport()
        with Keithley2400(transport=t) as k:
            assert k.is_connected
        assert not k.is_connected

    def test_write_formats_via_protocol(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.write("OUTP ON")
        assert t.write_log == [b"OUTP ON\n"]

    def test_query_writes_then_reads(self):
        t = _null(responses=[b"answer\n"])
        k = Keithley2400(transport=t)
        result = k.query("*IDN?")
        assert t.write_log == [b"*IDN?\n"]
        assert result == "answer"

    def test_read_strips_whitespace(self):
        t = _null(responses=[b"  +1.0\r\n"])
        k = Keithley2400(transport=t)
        assert k.read() == "+1.0"

    def test_identify(self):
        t = _null(responses=[b"KEITHLEY,2400,SN,v1\n"])
        k = Keithley2400(transport=t)
        assert k.identify() == "KEITHLEY,2400,SN,v1"

    def test_reset_sends_rst(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.reset()
        assert t.write_log == [b"*RST\n"]

    def test_write_raises_when_not_open(self):
        t = NullTransport()
        k = Keithley2400(transport=t)
        with pytest.raises(ConnectionError):
            k.write("OUTP ON")


# ---------------------------------------------------------------------------
# NullTransport
# ---------------------------------------------------------------------------


class TestNullTransport:
    def test_open_close_state(self):
        t = NullTransport()
        assert not t.is_open
        t.open()
        assert t.is_open
        t.close()
        assert not t.is_open

    def test_write_and_log(self):
        t = NullTransport()
        t.open()
        t.write(b"CMD\n")
        assert t.write_log == [b"CMD\n"]

    def test_read_returns_queued_response(self):
        t = NullTransport(responses=[b"resp\n"])
        t.open()
        assert t.read() == b"resp\n"

    def test_read_returns_empty_when_exhausted(self):
        t = NullTransport()
        t.open()
        assert t.read() == b""

    def test_read_until_returns_next_response(self):
        t = NullTransport(responses=[b"hello\n"])
        t.open()
        assert t.read_until(b"\n") == b"hello\n"

    def test_queue_response(self):
        t = NullTransport()
        t.open()
        t.queue_response(b"dynamic\n")
        assert t.read() == b"dynamic\n"

    def test_clear_log(self):
        t = NullTransport(responses=[b"x\n"])
        t.open()
        t.write(b"CMD\n")
        t.clear_log()
        assert t.write_log == []
        assert t.read() == b""

    def test_write_raises_when_closed(self):
        t = NullTransport()
        with pytest.raises(ConnectionError):
            t.write(b"CMD\n")

    def test_read_raises_when_closed(self):
        t = NullTransport()
        with pytest.raises(ConnectionError):
            t.read()

    def test_context_manager(self):
        with NullTransport() as t:
            assert t.is_open
        assert not t.is_open


# ---------------------------------------------------------------------------
# ScpiProtocol
# ---------------------------------------------------------------------------


class TestScpiProtocol:
    def test_format_command(self):
        assert ScpiProtocol().format_command("OUTP ON") == b"OUTP ON\n"

    def test_format_query(self):
        assert ScpiProtocol().format_query("*IDN?") == b"*IDN?\n"

    def test_parse_response_strips_whitespace(self):
        assert ScpiProtocol().parse_response(b"  +1.234\r\n") == "+1.234"

    def test_check_error_no_error(self):
        ScpiProtocol().check_error('+0,"No error"')  # must not raise

    def test_check_error_raises_on_error(self):
        with pytest.raises(InstrumentError, match="Undefined header"):
            ScpiProtocol().check_error('-113,"Undefined header"')

    def test_custom_terminator(self):
        p = ScpiProtocol(terminator=b"\r\n")
        assert p.format_command("X") == b"X\r\n"


# ---------------------------------------------------------------------------
# OxfordProtocol
# ---------------------------------------------------------------------------


class TestOxfordProtocol:
    def test_format_command(self):
        assert OxfordProtocol().format_command("H1") == b"H1\r"

    def test_format_query(self):
        assert OxfordProtocol().format_query("R1") == b"R1\r"

    def test_parse_response_strips_echo_char(self):
        assert OxfordProtocol().parse_response(b"R1.234\r") == "1.234"

    def test_parse_response_single_char(self):
        # Degenerate one-char response: no stripping of payload
        assert OxfordProtocol().parse_response(b"R") == "R"

    def test_check_error_no_error(self):
        OxfordProtocol().check_error("1.234")  # must not raise

    def test_check_error_raises_on_question_mark(self):
        with pytest.raises(InstrumentError, match="Oxford Instruments"):
            OxfordProtocol().check_error("?")


# ---------------------------------------------------------------------------
# LakeshoreProtocol
# ---------------------------------------------------------------------------


class TestLakeshoreProtocol:
    def test_format_command(self):
        assert LakeshoreProtocol().format_command("SETP 1,10.0") == b"SETP 1,10.0\r\n"

    def test_format_query(self):
        assert LakeshoreProtocol().format_query("KRDG? A") == b"KRDG? A\r\n"

    def test_parse_response_strips_crlf(self):
        assert LakeshoreProtocol().parse_response(b"+273.150\r\n") == "+273.150"

    def test_check_error_no_error(self):
        LakeshoreProtocol().check_error("+77.350")  # must not raise

    def test_check_error_raises_on_question_mark(self):
        with pytest.raises(InstrumentError, match="Lakeshore"):
            LakeshoreProtocol().check_error("?")


# ---------------------------------------------------------------------------
# Keithley2400 concrete driver
# ---------------------------------------------------------------------------


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

    def test_set_compliance(self):
        t = _null()
        Keithley2400(transport=t).set_compliance(0.05)
        assert t.write_log[-1] == b":SENS:CURR:PROT 0.05\n"

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
        assert Keithley2400(transport=t).get_measure_functions() == (MeasureFunction.VOLT, MeasureFunction.CURR)

    def test_get_measure_functions_without_suffix(self):
        t = _null(responses=[b"'VOLT','CURR'\n"])
        assert Keithley2400(transport=t).get_measure_functions() == (MeasureFunction.VOLT, MeasureFunction.CURR)

    def test_set_measure_functions(self):
        t = _null()
        Keithley2400(transport=t).set_measure_functions((MeasureFunction.VOLT, MeasureFunction.CURR))
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
            SourceSweepConfiguration(start=0.0, stop=1.0, points=5, spacing=SweepSpacing.LIN, delay=0.01)
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
            k.configure_source_sweep(SourceSweepConfiguration(start=0.0, stop=1.0, points=1, spacing=SweepSpacing.LOG))

    def test_configure_custom_sweep(self):
        t = _null(responses=[b"CURR\n"])
        k = Keithley2400(transport=t)
        k.configure_source_sweep(
            SourceSweepConfiguration(spacing=SweepSpacing.LIST, values=(1e-3, 2e-3, 3e-3), delay=0.1)
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


# ---------------------------------------------------------------------------
# Keithley2000/2700 concrete drivers
# ---------------------------------------------------------------------------


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
        t = _null(responses=[b'"VOLT:DC"\n', b"10\n", b'"VOLT:DC"\n', b"1\n", b'"VOLT:DC"\n', b"1\n"])
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
        t = _null(responses=[b'"VOLT:DC"\n', b'"VOLT:DC"\n', b'"VOLT:DC"\n', b'"VOLT:DC"\n', b'"VOLT:DC"\n'])
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
        assert t.write_log[-5:] == [b":TRIG:SOUR EXT\n", b":TRIG:COUN 2\n", b":INIT\n", b":ABOR\n", b":TRAC:CLE\n"]
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


# ---------------------------------------------------------------------------
# Keithley2182A/182 concrete drivers
# ---------------------------------------------------------------------------


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
        assert t.write_log[-5:] == [b":TRIG:SOUR EXT\n", b":TRIG:COUN 2\n", b":INIT\n", b":ABOR\n", b":TRAC:CLE\n"]
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


# ---------------------------------------------------------------------------
# SRS830 concrete driver
# ---------------------------------------------------------------------------


class TestSRS830:
    def test_default_protocol_is_scpi(self):
        k = SRS830(transport=NullTransport())
        assert isinstance(k.protocol, ScpiProtocol)

    def test_dual_output_measurements(self):
        t = _null(responses=[b"1.0,-2.0\n", b"3.0,45.0\n"])
        k = SRS830(transport=t)
        assert k.measure_xy() == pytest.approx((1.0, -2.0))
        assert k.measure_rt() == pytest.approx((3.0, 45.0))

    def test_getters(self):
        t = _null(responses=[b"8\n", b"10\n", b"1\n", b"137.0\n", b"-12.5\n", b"3\n", b"2\n", b"1\n", b"2\n"])
        k = SRS830(transport=t)
        assert k.get_sensitivity() == pytest.approx(1e-6)
        assert k.get_time_constant() == pytest.approx(1.0)
        assert k.get_reference_source() is LockInReferenceSource.INTERNAL
        assert k.get_reference_frequency() == pytest.approx(137.0)
        assert k.get_reference_phase() == pytest.approx(-12.5)
        assert k.get_harmonic() == 3
        assert k.get_filter_slope() == 18
        assert k.get_input_coupling() is LockInInputCoupling.DC
        assert k.get_reserve_mode() is LockInReserveMode.LOW_NOISE

    def test_setters_and_auto_actions(self):
        t = _null()
        k = SRS830(transport=t)
        k.set_sensitivity(1e-6)
        k.set_time_constant(1.0)
        k.set_reference_source(LockInReferenceSource.EXTERNAL)
        k.set_reference_frequency(17.0)
        k.set_reference_phase(33.5)
        k.set_harmonic(2)
        k.set_filter_slope(12)
        k.set_input_coupling(LockInInputCoupling.AC)
        k.set_reserve_mode(LockInReserveMode.NORMAL)
        k.auto_gain()
        k.auto_phase()
        k.auto_reserve()
        assert t.write_log == [
            b"SENS 8\n",
            b"OFLT 10\n",
            b"FMOD 0\n",
            b"FREQ 17.0\n",
            b"PHAS 33.5\n",
            b"HARM 2\n",
            b"OFSL 1\n",
            b"ICPL 0\n",
            b"RMOD 1\n",
            b"AGAN\n",
            b"APHS\n",
            b"ARSV\n",
        ]

    def test_setter_validation(self):
        k = SRS830(transport=_null())
        with pytest.raises(ValueError):
            k.set_sensitivity(1.5e-6)
        with pytest.raises(ValueError):
            k.set_time_constant(2.0)
        with pytest.raises(ValueError):
            k.set_reference_frequency(0.0)
        with pytest.raises(ValueError):
            k.set_harmonic(0)
        with pytest.raises(ValueError):
            k.set_filter_slope(9)

    def test_capabilities(self):
        caps = SRS830(transport=_null()).get_capabilities()
        assert isinstance(caps, LockInAmplifierCapabilities)
        assert caps.has_harmonic_selection
        assert caps.has_filter_slope_control
        assert caps.has_input_coupling_control
        assert caps.has_reserve_mode_control
        assert caps.has_auto_gain
        assert caps.has_auto_phase
        assert caps.has_auto_reserve


# ---------------------------------------------------------------------------
# Keithley6221 concrete driver
# ---------------------------------------------------------------------------


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
        t = _null(responses=[b"SIN\n", b"13.7\n", b"1.0E-4\n"])
        k = Keithley6221(transport=t)
        assert k.get_waveform() is CurrentWaveform.SINE
        assert k.get_frequency() == pytest.approx(13.7)
        assert k.get_offset_current() == pytest.approx(1.0e-4)
        k.set_waveform(CurrentWaveform.DC)
        k.set_frequency(17.0)
        k.set_offset_current(-2.0e-4)
        assert t.write_log == [
            b":SOUR:WAVE:FUNC?\n",
            b":SOUR:WAVE:FREQ?\n",
            b":SOUR:WAVE:OFFS?\n",
            b":SOUR:WAVE:FUNC DC\n",
            b":SOUR:WAVE:FREQ 17.0\n",
            b":SOUR:WAVE:OFFS -0.0002\n",
        ]

    def test_set_frequency_validation(self):
        with pytest.raises(ValueError, match="positive"):
            Keithley6221(transport=_null()).set_frequency(0.0)

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
            b":SOUR:DEL 0.0\n",
        ]

    def test_list_sweep_empty_values_raises(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="non-empty"):
            k.configure_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=())
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
        assert t.write_log == [b":SOUR:SWE:ARM\n", b":SOUR:SWE:ABOR\n"]

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
            b":SOUR:DEL 0.0\n",
            b":SOUR:PULS:STAT 1\n",
            b":SOUR:PULS:WIDT 0.001\n",
            b":SOUR:PULS:DEL 0.005\n",
            b":SOUR:PULS:CURR:LOW 0.0\n",
        ]

    def test_pulsed_sweep_width_validation(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="width"):
            k.configure_pulsed_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=(1e-3,)),
                PulsedSweepConfiguration(width=0.0, off_time=1e-3),
            )

    def test_pulsed_sweep_off_time_validation(self):
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="off_time"):
            k.configure_pulsed_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=(1e-3,)),
                PulsedSweepConfiguration(width=1e-3, off_time=0.0),
            )

    def test_convenience_configure_custom_sweep(self):
        """configure_custom_sweep delegates to configure_sweep with LIST spacing."""
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_custom_sweep((1e-3, 2e-3, 3e-3), delay=0.01)
        assert t.write_log == [
            b":SOUR:SWE:SPAC LIST\n",
            b":SOUR:LIST:CURR 0.001,0.002,0.003\n",
            b":SOUR:SWE:POIN 3\n",
            b":SOUR:DEL 0.01\n",
        ]

    def test_convenience_configure_linear_sweep(self):
        """configure_linear_sweep delegates to configure_sweep with LIN spacing."""
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_linear_sweep(0.0, 1e-3, 11)
        assert t.write_log[0] == b":SOUR:SWE:SPAC LIN\n"

    def test_base_sweep_raises_on_unsupported_driver(self):
        """Base class configure_sweep raises NotImplementedError when not overridden."""

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
            src.configure_sweep(CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIN))
        with pytest.raises(NotImplementedError, match="has_pulsed_sweep"):
            src.configure_pulsed_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=(1e-3,)),
                PulsedSweepConfiguration(width=1e-3, off_time=1e-3),
            )


# ---------------------------------------------------------------------------
# Keithley 6845/6514/6517 electrometer concrete drivers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lakeshore M81 current source concrete driver
# ---------------------------------------------------------------------------


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
            src.configure_sweep(
                CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=())
            )

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


# ---------------------------------------------------------------------------
# Lakeshore525 concrete driver
# ---------------------------------------------------------------------------


class TestLakeshore525:
    def test_default_protocol_is_lakeshore(self):
        m = Lakeshore525(transport=NullTransport())
        assert isinstance(m.protocol, LakeshoreProtocol)

    def test_identify_and_model_and_firmware(self):
        t = _null(
            responses=[
                b"LAKESHORE,MODEL525,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL525,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL525,SN001,1.2.3\r\n",
            ]
        )
        m = Lakeshore525(transport=t)
        assert m.identify() == "LAKESHORE,MODEL525,SN001,1.2.3"
        assert m.get_model() == "MODEL525"
        assert m.get_firmware_version() == "1.2.3"

    def test_reading_properties_send_correct_commands(self):
        t = _null(responses=[b"2.5\r\n", b"0.75\r\n", b"1.2\r\n"])
        m = Lakeshore525(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

    def test_current_uses_first_value_from_comma_separated_response(self):
        t = _null(responses=[b"2.5,OK\r\n"])
        m = Lakeshore525(transport=t)
        assert m.current == pytest.approx(2.5)

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = Lakeshore525(transport=t)
        m.set_target_current(3.0)
        m.set_target_field(0.9)
        m.ramp_to_target()
        assert t.write_log == [b"SETI 3.0\r\n", b"SETF 0.9\r\n", b"RAMP\r\n"]

    def test_heater_methods_and_property(self):
        t = _null(responses=[b"1\r\n"])
        m = Lakeshore525(transport=t)
        m.heater_on()
        m.heater_off()
        assert m.heater is True
        assert t.write_log == [b"PSH 1\r\n", b"PSH 0\r\n", b"PSH?\r\n"]

    def test_status_maps_state(self):
        t = _null(
            responses=[
                b"at_target\r\n",
                b"1.1\r\n",
                b"0.3\r\n",
                b"0.2\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore525(transport=t)
        status = m.status
        assert status.state.value == "at_target"
        assert status.at_target is True
        assert status.current == pytest.approx(1.1)
        assert status.field == pytest.approx(0.3)
        assert status.voltage == pytest.approx(0.2)
        assert status.heater_on is False
        assert t.write_log == [b"OPSTR?\r\n", b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n", b"PSH?\r\n"]

    def test_set_magnet_constant_validation(self):
        m = Lakeshore525(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)

    def test_query_float_raises_for_unparseable_numeric_response(self):
        t = _null(responses=[b"not-a-float\r\n"])
        m = Lakeshore525(transport=t)
        with pytest.raises(ValueError):
            _ = m.current

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = Lakeshore525(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=False,
                at_target=False,
                message="ramping",
            )

        monkeypatch.setattr(Lakeshore525, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)


# ---------------------------------------------------------------------------
# OxfordIPS120 concrete driver
# ---------------------------------------------------------------------------


class TestOxfordIPS120:
    def test_default_protocol_is_oxford(self):
        m = OxfordIPS120(transport=NullTransport())
        assert isinstance(m.protocol, OxfordProtocol)

    def test_identity_parsing(self):
        t = _null(
            responses=[
                b"VIPS120-10 3.07\r",
                b"VIPS120-10 3.07\r",
                b"VIPS120-10 3.07\r",
            ]
        )
        m = OxfordIPS120(transport=t)
        assert m.identify() == "IPS120-10 3.07"
        assert m.get_model() == "IPS120-10"
        assert m.get_firmware_version() == "3.07"

    def test_reading_properties_send_correct_commands(self):
        t = _null(responses=[b"R2.5\r", b"R0.75\r", b"R1.2\r"])
        m = OxfordIPS120(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"R1\r", b"R7\r", b"R5\r"]

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = OxfordIPS120(transport=t)
        m.set_target_current(3.0)
        m.set_ramp_rate_current(0.2)
        m.ramp_to_target()
        assert t.write_log == [b"J3.0\r", b"T0.2\r", b"A1\r"]

    def test_heater_methods_and_property(self):
        t = _null(responses=[b"X00A0C0H1P0\r"])
        m = OxfordIPS120(transport=t)
        m.heater_on()
        m.heater_off()
        assert m.heater is True
        assert t.write_log == [b"H1\r", b"H0\r", b"X\r"]

    def test_status_maps_state(self):
        t = _null(
            responses=[
                b"X00A0C0H0P1\r",
                b"R1.1\r",
                b"R0.3\r",
                b"R0.2\r",
            ]
        )
        m = OxfordIPS120(transport=t)
        status = m.status
        assert status.state.value == "standby"
        assert status.at_target is True
        assert status.current == pytest.approx(1.1)
        assert status.field == pytest.approx(0.3)
        assert status.voltage == pytest.approx(0.2)
        assert status.heater_on is False
        assert status.persistent is True
        assert t.write_log == [b"X\r", b"R1\r", b"R7\r", b"R5\r"]

    def test_set_magnet_constant_validation(self):
        m = OxfordIPS120(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)
        m.set_magnet_constant(0.5)
        assert m.magnet_constant == pytest.approx(0.5)

    def test_set_target_field_uses_magnet_constant_conversion(self):
        t = _null()
        m = OxfordIPS120(transport=t)
        m.set_magnet_constant(0.5)
        m.set_target_field(1.0)
        assert t.write_log == [b"J2.0\r"]

    def test_query_float_raises_for_unparseable_numeric_response(self):
        t = _null(responses=[b"Rnot-a-float\r"])
        m = OxfordIPS120(transport=t)
        with pytest.raises(ValueError, match=r"Invalid numeric response for R1"):
            _ = m.current

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = OxfordIPS120(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=False,
                at_target=False,
                message="X00A1C0H0P0",
            )

        monkeypatch.setattr(OxfordIPS120, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)


# ---------------------------------------------------------------------------
# Lakeshore temperature controller drivers
# ---------------------------------------------------------------------------


class TestLakeshoreTemperatureControllers:
    def test_default_protocol_is_lakeshore(self):
        assert isinstance(Lakeshore335(transport=NullTransport()).protocol, LakeshoreProtocol)
        assert isinstance(Lakeshore336(transport=NullTransport()).protocol, LakeshoreProtocol)
        assert isinstance(Lakeshore340(transport=NullTransport()).protocol, LakeshoreProtocol)

    def test_lakeshore335_temperature_and_status(self):
        t = _null(responses=[b"4.2\r\n", b"0\r\n"])
        tc = Lakeshore335(transport=t)
        assert tc.get_temperature("A") == pytest.approx(4.2)
        assert tc.get_sensor_status("A") is SensorStatus.OK
        assert t.write_log == [b"KRDG? A\r\n", b"RDGST? A\r\n"]

    def test_lakeshore335_loop_methods(self):
        t = _null(
            responses=[
                b"1,1,0\r\n",
                b"10.0\r\n",
                b"1,1,0\r\n",
                b"1,0.5\r\n",
                b"1,0.5\r\n",
                b"50,2,0.1\r\n",
            ]
        )
        tc = Lakeshore335(transport=t)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert tc.get_setpoint(1) == pytest.approx(10.0)
        tc.set_setpoint(1, 12.5)
        tc.set_input_channel(1, "B")
        assert tc.get_ramp_enabled(1) is True
        assert tc.get_ramp_rate(1) == pytest.approx(0.5)
        pid = tc.get_pid(1)
        assert pid == PIDParameters(50.0, 2.0, 0.1)
        assert t.write_log == [
            b"OUTMODE? 1\r\n",
            b"SETP? 1\r\n",
            b"SETP 1,12.5\r\n",
            b"OUTMODE? 1\r\n",
            b"OUTMODE 1,1,2,0\r\n",
            b"RAMP? 1\r\n",
            b"RAMP? 1\r\n",
            b"PID? 1\r\n",
        ]

    def test_lakeshore_capabilities(self):
        caps_335 = Lakeshore335(transport=_null()).get_capabilities()
        caps_336 = Lakeshore336(transport=_null()).get_capabilities()
        caps_340 = Lakeshore340(transport=_null()).get_capabilities()
        assert caps_335.input_channels == ("A", "B")
        assert caps_336.input_channels == ("A", "B", "C", "D")
        assert caps_340.input_channels == ("A", "B")


# ---------------------------------------------------------------------------
# Oxford temperature controller drivers
# ---------------------------------------------------------------------------


class TestOxfordTemperatureControllers:
    def test_default_protocols(self):
        assert isinstance(OxfordITC503(transport=NullTransport()).protocol, OxfordProtocol)
        assert isinstance(OxfordMercuryTemperatureController(transport=NullTransport()).protocol, ScpiProtocol)

    def test_itc503_core_methods(self):
        t = _null(
            responses=[
                b"R4.2\r",
                b"R10.0\r",
                b"R1\r",
                b"R22.5\r",
                b"R30.0,4.0,0.0\r",
                b"R1,0.8\r",
                b"R1,0.8\r",
            ]
        )
        tc = OxfordITC503(transport=t)
        assert tc.get_temperature("A") == pytest.approx(4.2)
        assert tc.get_setpoint(1) == pytest.approx(10.0)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert tc.get_heater_output(1) == pytest.approx(22.5)
        assert tc.get_pid(1) == PIDParameters(30.0, 4.0, 0.0)
        assert tc.get_ramp_rate(1) == pytest.approx(0.8)
        tc.set_setpoint(1, 12.0)
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)
        tc.set_ramp_enabled(1, True)
        assert t.write_log == [
            b"R1\r",
            b"R0\r",
            b"R20\r",
            b"R5\r",
            b"R8,R9,R10\r",
            b"R21\r",
            b"T12.0\r",
            b"A2\r",
            b"R21\r",
            b"S1,0.8\r",
        ]

    def test_mercury_core_methods(self):
        t = _null(
            responses=[
                b"4.2\n",
                b"15.0\n",
                b"1\n",
                b"35.0\n",
                b"40.0,3.0,0.2\n",
                b"0,1.5\n",
                b"0,1.5\n",
            ]
        )
        tc = OxfordMercuryTemperatureController(transport=t)
        assert tc.get_temperature("B") == pytest.approx(4.2)
        assert tc.get_setpoint(1) == pytest.approx(15.0)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert tc.get_heater_output(1) == pytest.approx(35.0)
        assert tc.get_pid(1) == PIDParameters(40.0, 3.0, 0.2)
        assert tc.get_ramp_enabled(1) is False
        tc.set_setpoint(1, 22.0)
        tc.set_ramp_rate(1, 2.0)
        assert t.write_log == [
            b"READ:TEMP? B\n",
            b"READ:LOOP1:SETP?\n",
            b"READ:LOOP1:MODE?\n",
            b"READ:LOOP1:HTR?\n",
            b"READ:LOOP1:PID?\n",
            b"READ:LOOP1:RAMP?\n",
            b"SET:LOOP1:SETP 22.0\n",
            b"READ:LOOP1:RAMP?\n",
            b"SET:LOOP1:RAMP 0,2.0\n",
        ]

    def test_capabilities(self):
        caps_itc = OxfordITC503(transport=_null()).get_capabilities()
        caps_mercury = OxfordMercuryTemperatureController(transport=_null()).get_capabilities()
        assert caps_itc.has_cryogen_control is False
        assert caps_mercury.has_cryogen_control is True
        assert caps_mercury.loop_numbers == (1, 2)


# ---------------------------------------------------------------------------
# InstrumentError
# ---------------------------------------------------------------------------


class TestInstrumentError:
    """Structured exception class for instrument errors."""

    def test_message_only(self):
        exc = InstrumentError("bad news")
        assert str(exc) == "bad news"
        assert exc.message == "bad news"
        assert exc.command is None
        assert exc.error_code is None

    def test_with_command(self):
        exc = InstrumentError("bad news", command="*IDN")
        assert "command: *IDN" in str(exc)
        assert exc.command == "*IDN"

    def test_with_error_code(self):
        exc = InstrumentError("Undefined header", error_code=-113)
        assert "code: -113" in str(exc)
        assert exc.error_code == -113

    def test_with_all_fields(self):
        exc = InstrumentError("Undefined header", command="*IDN", error_code=-113)
        s = str(exc)
        assert "Undefined header" in s
        assert "command: *IDN" in s
        assert "code: -113" in s

    def test_is_exception(self):
        assert issubclass(InstrumentError, Exception)

    def test_exported_from_instruments_package(self):
        from stoner_measurement.instruments import InstrumentError as IE

        assert IE is InstrumentError


# ---------------------------------------------------------------------------
# SCPI protocol — error_query and check_error details
# ---------------------------------------------------------------------------


class TestScpiErrorHandling:
    def test_error_query_property(self):
        assert ScpiProtocol().error_query == "SYST:ERR?"

    def test_errors_in_response_is_false(self):
        assert ScpiProtocol().errors_in_response is False

    def test_check_error_no_error_variants(self):
        p = ScpiProtocol()
        p.check_error('+0,"No error"')
        p.check_error("+0,No error")
        p.check_error("+00,No error")  # some instruments zero-pad the code

    def test_check_error_sets_error_code(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error('-113,"Undefined header"', command="*IDN")
        exc = exc_info.value
        assert exc.error_code == -113
        assert exc.command == "*IDN"
        assert "Undefined header" in exc.message

    def test_check_error_unstructured_response(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error("ERROR")
        assert exc_info.value.error_code is None

    def test_check_error_positive_nonzero_code(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error('+100,"Device-specific error"')
        assert exc_info.value.error_code == 100


# ---------------------------------------------------------------------------
# Oxford protocol — errors_in_response
# ---------------------------------------------------------------------------


class TestOxfordErrorHandling:
    def test_errors_in_response_is_true(self):
        assert OxfordProtocol().errors_in_response is True

    def test_error_query_is_none(self):
        assert OxfordProtocol().error_query is None

    def test_check_error_ok(self):
        OxfordProtocol().check_error("1.234")  # must not raise

    def test_check_error_raises(self):
        with pytest.raises(InstrumentError) as exc_info:
            OxfordProtocol().check_error("?", command="R99")
        exc = exc_info.value
        assert exc.command == "R99"
        assert exc.error_code is None

    def test_check_error_question_mark_prefix(self):
        with pytest.raises(InstrumentError):
            OxfordProtocol().check_error("?status")


# ---------------------------------------------------------------------------
# Lakeshore protocol — errors_in_response
# ---------------------------------------------------------------------------


class TestLakeshoreErrorHandling:
    def test_errors_in_response_is_true(self):
        assert LakeshoreProtocol().errors_in_response is True

    def test_error_query_is_none(self):
        assert LakeshoreProtocol().error_query is None

    def test_check_error_ok(self):
        LakeshoreProtocol().check_error("+77.350")  # must not raise

    def test_check_error_raises(self):
        with pytest.raises(InstrumentError) as exc_info:
            LakeshoreProtocol().check_error("?", command="KRDG? Z")
        exc = exc_info.value
        assert exc.command == "KRDG? Z"


# ---------------------------------------------------------------------------
# BaseInstrument.check_for_errors — SCPI / NullTransport (no out-of-band STB)
# ---------------------------------------------------------------------------


class TestCheckForErrors:
    def test_check_for_errors_no_error(self):
        t = _null(responses=[b'+0,"No error"\n'])
        instr = BaseInstrument(t, ScpiProtocol())
        instr.check_for_errors()  # must not raise
        assert t.write_log == [b"SYST:ERR?\n"]

    def test_check_for_errors_raises_on_error(self):
        t = _null(responses=[b'-113,"Undefined header"\n'])
        instr = BaseInstrument(t, ScpiProtocol())
        with pytest.raises(InstrumentError) as exc_info:
            instr.check_for_errors(command="*IDN")
        assert exc_info.value.error_code == -113
        assert exc_info.value.command == "*IDN"

    def test_check_for_errors_noop_for_response_embedded_protocol(self):
        t = _null()
        instr = BaseInstrument(t, OxfordProtocol())
        instr.check_for_errors()  # Oxford has no error_query — must be a no-op
        assert t.write_log == []

    def test_check_for_errors_noop_when_no_error_query(self):
        t = _null()
        instr = BaseInstrument(t, LakeshoreProtocol())
        instr.check_for_errors()  # no error_query — no-op
        assert t.write_log == []

    def test_check_for_errors_skips_query_when_stb_esb_clear(self):
        """When transport returns a status byte with ESB clear, no query is sent."""

        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x00  # ESB bit NOT set

        t = StubTransport()
        t.open()
        instr = BaseInstrument(t, ScpiProtocol())
        instr.check_for_errors()
        assert t.write_log == []  # no SYST:ERR? sent

    def test_check_for_errors_queries_when_stb_esb_set(self):
        """When transport returns a status byte with ESB set, error queue is queried."""

        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x04  # ESB bit set

        t = StubTransport(responses=[b'+0,"No error"\n'])
        t.open()
        instr = BaseInstrument(t, ScpiProtocol())
        instr.check_for_errors()
        assert t.write_log == [b"SYST:ERR?\n"]

    def test_check_for_errors_raises_when_stb_esb_set_and_error_queued(self):
        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x04

        t = StubTransport(responses=[b'-113,"Undefined header"\n'])
        t.open()
        instr = BaseInstrument(t, ScpiProtocol())
        with pytest.raises(InstrumentError) as exc_info:
            instr.check_for_errors(command="BAD CMD")
        assert exc_info.value.error_code == -113
        assert exc_info.value.command == "BAD CMD"


# ---------------------------------------------------------------------------
# auto_check_errors flag
# ---------------------------------------------------------------------------


class TestAutoCheckErrors:
    def test_auto_check_errors_default_is_false(self):
        assert BaseInstrument(NullTransport(), ScpiProtocol()).auto_check_errors is False

    def test_auto_check_errors_query_raises_on_scpi_error(self):
        # The NullTransport serves: first the query response, then the SYST:ERR? response
        t = _null(responses=[b"ACME\n", b'-113,"Undefined header"\n'])
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError, match="Undefined header"):
            instr.query("*IDN?")

    def test_auto_check_errors_query_no_raise_when_queue_clear(self):
        t = _null(responses=[b"ACME\n", b'+0,"No error"\n'])
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=True)
        result = instr.query("*IDN?")
        assert result == "ACME"

    def test_auto_check_errors_write_raises_on_scpi_error(self):
        t = _null(responses=[b'-113,"Undefined header"\n'])
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError):
            instr.write("BAD CMD")

    def test_auto_check_errors_oxford_query_raises_on_error_response(self):
        # Oxford error is a bare '?\r' response — parse_response returns "?" (single char, no stripping)
        t = _null(responses=[b"?\r"])
        instr = BaseInstrument(t, OxfordProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError, match="Oxford Instruments"):
            instr.query("X9")

    def test_auto_check_errors_oxford_query_ok(self):
        t = _null(responses=[b"R1.234\r"])
        instr = BaseInstrument(t, OxfordProtocol(), auto_check_errors=True)
        assert instr.query("R1") == "1.234"

    def test_auto_check_errors_write_does_not_query_for_response_embedded(self):
        """Oxford write with auto_check_errors should NOT send an error query."""
        t = _null()
        instr = BaseInstrument(t, OxfordProtocol(), auto_check_errors=True)
        instr.write("H1")
        # Only the command itself should be in the write log
        assert t.write_log == [b"H1\r"]



# ---------------------------------------------------------------------------
# UdpTransport
# ---------------------------------------------------------------------------


class TestUdpTransport:
    """Tests for the UDP socket transport."""

    def test_constructor_stores_host_port(self):
        from stoner_measurement.instruments.transport import UdpTransport

        t = UdpTransport(host="10.0.0.1", port=8000)
        assert t.host == "10.0.0.1"
        assert t.port == 8000

    def test_default_timeout(self):
        from stoner_measurement.instruments.transport import UdpTransport

        assert UdpTransport(host="10.0.0.1", port=8000).timeout == 2.0

    def test_custom_timeout(self):
        from stoner_measurement.instruments.transport import UdpTransport

        assert UdpTransport(host="10.0.0.1", port=8000, timeout=5.0).timeout == 5.0

    def test_initially_closed(self):
        from stoner_measurement.instruments.transport import UdpTransport

        assert not UdpTransport(host="10.0.0.1", port=8000).is_open

    def test_write_raises_when_closed(self):
        from stoner_measurement.instruments.transport import UdpTransport

        t = UdpTransport(host="10.0.0.1", port=8000)
        with pytest.raises(ConnectionError):
            t.write(b"CMD\n")

    def test_read_raises_when_closed(self):
        from stoner_measurement.instruments.transport import UdpTransport

        t = UdpTransport(host="10.0.0.1", port=8000)
        with pytest.raises(ConnectionError):
            t.read()

    def test_close_when_not_open_is_harmless(self):
        from stoner_measurement.instruments.transport import UdpTransport

        UdpTransport(host="10.0.0.1", port=8000).close()  # must not raise

    def test_exported_from_transport_package(self):
        from stoner_measurement.instruments.transport import UdpTransport as UdpT

        assert UdpT is not None


# ---------------------------------------------------------------------------
# BaseTransport.from_uri — URI schemes
# ---------------------------------------------------------------------------


class TestFromUriSchemes:
    """Tests for BaseTransport.from_uri with scheme://... URIs."""

    def test_tcp_uri_returns_ethernet_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        t = BaseTransport.from_uri("tcp://192.168.1.100:5025")
        assert isinstance(t, EthernetTransport)
        assert t.host == "192.168.1.100"
        assert t.port == 5025

    def test_tcpip_scheme_alias(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        t = BaseTransport.from_uri("tcpip://10.0.0.5:1234")
        assert isinstance(t, EthernetTransport)
        assert t.host == "10.0.0.5"
        assert t.port == 1234

    def test_tcp_uri_custom_timeout(self):
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("tcp://192.168.1.100:5025?timeout=5.0")
        assert t.timeout == 5.0

    def test_tcp_uri_missing_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="host and port"):
            BaseTransport.from_uri("tcp://192.168.1.100")

    def test_udp_uri_returns_udp_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, UdpTransport

        t = BaseTransport.from_uri("udp://10.0.0.1:8000")
        assert isinstance(t, UdpTransport)
        assert t.host == "10.0.0.1"
        assert t.port == 8000

    def test_udp_uri_custom_timeout(self):
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("udp://10.0.0.1:8000?timeout=3.5")
        assert t.timeout == 3.5

    def test_udp_uri_missing_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="host and port"):
            BaseTransport.from_uri("udp://10.0.0.1")

    def test_serial_unix_uri(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        t = BaseTransport.from_uri("serial:///dev/ttyUSB0?baud_rate=9600")
        assert isinstance(t, SerialTransport)
        assert t.port == "/dev/ttyUSB0"
        assert t.baud_rate == 9600

    def test_serial_windows_uri(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        t = BaseTransport.from_uri("serial://COM3?baud_rate=115200")
        assert isinstance(t, SerialTransport)
        assert t.port == "COM3"
        assert t.baud_rate == 115200

    def test_serial_uri_baud_alias(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("serial:///dev/ttyUSB0?baud=19200")
        assert t.baud_rate == 19200

    def test_serial_uri_all_params(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri(
            "serial:///dev/ttyS0?baud_rate=9600&data_bits=7&stop_bits=2&parity=E&timeout=5.0"
        )
        assert t.data_bits == 7
        assert t.stop_bits == 2.0
        assert t.parity == "E"
        assert t.timeout == 5.0

    def test_serial_uri_missing_port_raises(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="No serial port"):
            BaseTransport.from_uri("serial://?baud_rate=9600")

    def test_gpib_uri_address_only(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("gpib://22/")
        assert isinstance(t, GpibTransport)
        assert t.address == 22
        assert t.board == 0

    def test_gpib_uri_board_and_address(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("gpib://1:14/")
        assert isinstance(t, GpibTransport)
        assert t.board == 1
        assert t.address == 14

    def test_gpib_uri_custom_timeout(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("gpib://22/?timeout=10.0")
        assert t.timeout == 10.0

    def test_unsupported_scheme_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            BaseTransport.from_uri("ftp://somehost:21")


# ---------------------------------------------------------------------------
# BaseTransport.from_uri — VISA resource strings
# ---------------------------------------------------------------------------


class TestFromUriVisaResourceStrings:
    """Tests for BaseTransport.from_uri with VISA resource strings."""

    def test_gpib_visa_returns_gpib_transport(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("GPIB0::22::INSTR")
        assert isinstance(t, GpibTransport)
        assert t.address == 22
        assert t.board == 0

    def test_gpib_visa_no_board_defaults_to_zero(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("GPIB::14::INSTR")
        assert isinstance(t, GpibTransport)
        assert t.address == 14
        assert t.board == 0

    def test_gpib_visa_nonzero_board(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("GPIB1::7::INSTR")
        assert isinstance(t, GpibTransport)
        assert t.address == 7
        assert t.board == 1

    def test_gpib_visa_lowercase(self):
        pyvisa = pytest.importorskip("pyvisa")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        t = BaseTransport.from_uri("gpib0::22::instr")
        assert isinstance(t, GpibTransport)
        assert t.address == 22

    def test_tcpip_visa_socket_returns_ethernet_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        t = BaseTransport.from_uri("TCPIP::192.168.1.100::5025::SOCKET")
        assert isinstance(t, EthernetTransport)
        assert t.host == "192.168.1.100"
        assert t.port == 5025

    def test_tcpip_visa_with_board_number(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        t = BaseTransport.from_uri("TCPIP0::10.0.0.5::1234::SOCKET")
        assert isinstance(t, EthernetTransport)
        assert t.host == "10.0.0.5"
        assert t.port == 1234

    def test_tcpip_visa_instr_uses_default_port(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        t = BaseTransport.from_uri("TCPIP::192.168.1.100::INSTR")
        assert isinstance(t, EthernetTransport)
        assert t.host == "192.168.1.100"
        assert t.port == 5025

    def test_asrl_unix_device(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        t = BaseTransport.from_uri("ASRL/dev/ttyUSB0::INSTR")
        assert isinstance(t, SerialTransport)
        assert t.port == "/dev/ttyUSB0"

    def test_asrl_windows_com_port(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        t = BaseTransport.from_uri("ASRLCOM3::INSTR")
        assert isinstance(t, SerialTransport)
        assert t.port == "COM3"

    def test_asrl_lowercase(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        t = BaseTransport.from_uri("asrl/dev/ttyS0::INSTR")
        assert isinstance(t, SerialTransport)
        assert t.port == "/dev/ttyS0"

    def test_asrl_empty_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="No serial port"):
            BaseTransport.from_uri("ASRL::INSTR")

    def test_unrecognised_visa_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unrecognised VISA resource string"):
            BaseTransport.from_uri("USB0::0x1234::0x5678::SN001::INSTR")

    def test_plain_string_without_scheme_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unrecognised VISA resource string"):
            BaseTransport.from_uri("notauri")


# ---------------------------------------------------------------------------
# SerialTransport — flow control defaults and parameters
# ---------------------------------------------------------------------------


class TestSerialTransportFlowControl:
    """Tests for the flow-control parameters on SerialTransport."""

    def test_default_xonxoff_is_false(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0").xonxoff is False

    def test_default_rtscts_is_false(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0").rtscts is False

    def test_xonxoff_can_be_enabled(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0", xonxoff=True).xonxoff is True

    def test_rtscts_can_be_enabled(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0", rtscts=True).rtscts is True

    def test_serial_uri_xonxoff_true(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("serial:///dev/ttyUSB0?xonxoff=true")
        assert t.xonxoff is True
        assert t.rtscts is False

    def test_serial_uri_rtscts_true(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("serial:///dev/ttyUSB0?rtscts=1")
        assert t.rtscts is True
        assert t.xonxoff is False

    def test_serial_uri_no_flow_control_by_default(self):
        serial = pytest.importorskip("serial")  # noqa: F841
        from stoner_measurement.instruments.transport import BaseTransport

        t = BaseTransport.from_uri("serial:///dev/ttyUSB0")
        assert t.xonxoff is False
        assert t.rtscts is False


# ---------------------------------------------------------------------------
# TemperatureController — helpers and concrete stub
# ---------------------------------------------------------------------------

# A minimal concrete TemperatureController implementing all abstract methods.
# Used across the TemperatureController test classes below.

def _make_tc(transport=None):
    """Return a _FullTC instance connected to *transport* (default: open NullTransport)."""

    class _FullTC(TemperatureController):
        """Minimal concrete implementation of TemperatureController for testing."""

        def get_temperature(self, channel):
            return 77.0

        def get_sensor_status(self, channel):
            return SensorStatus.OK

        def get_input_channel(self, loop):
            return "A"

        def set_input_channel(self, loop, channel):
            pass

        def get_setpoint(self, loop):
            return 80.0

        def set_setpoint(self, loop, value):
            pass

        def get_loop_mode(self, loop):
            return ControlMode.CLOSED_LOOP

        def set_loop_mode(self, loop, mode):
            pass

        def get_heater_output(self, loop):
            return 25.0

        def set_heater_range(self, loop, range_):
            pass

        def get_pid(self, loop):
            return PIDParameters(p=50.0, i=2.0, d=0.0)

        def set_pid(self, loop, p, i, d):
            pass

        def get_ramp_rate(self, loop):
            return 10.0

        def set_ramp_rate(self, loop, rate):
            pass

        def get_ramp_enabled(self, loop):
            return False

        def set_ramp_enabled(self, loop, enabled):
            pass

        def get_capabilities(self):
            return ControllerCapabilities(
                num_inputs=2,
                num_loops=1,
                input_channels=("A", "B"),
                loop_numbers=(1,),
                has_ramp=True,
                has_pid=True,
            )

    t = transport if transport is not None else _null()
    return _FullTC(t, LakeshoreProtocol())


# ---------------------------------------------------------------------------
# TemperatureController — core abstract method tests
# ---------------------------------------------------------------------------


class TestTemperatureControllerCore:
    """Tests for all seventeen core abstract methods via the _FullTC stub."""

    def test_get_temperature(self):
        tc = _make_tc()
        assert tc.get_temperature("A") == pytest.approx(77.0)

    def test_get_sensor_status(self):
        tc = _make_tc()
        assert tc.get_sensor_status("A") is SensorStatus.OK

    def test_get_input_channel(self):
        tc = _make_tc()
        assert tc.get_input_channel(1) == "A"

    def test_set_input_channel(self):
        tc = _make_tc()
        tc.set_input_channel(1, "B")  # must not raise

    def test_get_setpoint(self):
        tc = _make_tc()
        assert tc.get_setpoint(1) == pytest.approx(80.0)

    def test_set_setpoint(self):
        tc = _make_tc()
        tc.set_setpoint(1, 100.0)  # must not raise

    def test_get_loop_mode(self):
        tc = _make_tc()
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP

    def test_set_loop_mode(self):
        tc = _make_tc()
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)  # must not raise

    def test_get_heater_output(self):
        tc = _make_tc()
        assert tc.get_heater_output(1) == pytest.approx(25.0)

    def test_set_heater_range(self):
        tc = _make_tc()
        tc.set_heater_range(1, 2)  # must not raise

    def test_get_pid(self):
        tc = _make_tc()
        pid = tc.get_pid(1)
        assert isinstance(pid, PIDParameters)
        assert pid.p == pytest.approx(50.0)
        assert pid.i == pytest.approx(2.0)
        assert pid.d == pytest.approx(0.0)

    def test_set_pid(self):
        tc = _make_tc()
        tc.set_pid(1, 40.0, 1.5, 0.1)  # must not raise

    def test_get_ramp_rate(self):
        tc = _make_tc()
        assert tc.get_ramp_rate(1) == pytest.approx(10.0)

    def test_set_ramp_rate(self):
        tc = _make_tc()
        tc.set_ramp_rate(1, 5.0)  # must not raise

    def test_get_ramp_enabled(self):
        tc = _make_tc()
        assert tc.get_ramp_enabled(1) is False

    def test_set_ramp_enabled(self):
        tc = _make_tc()
        tc.set_ramp_enabled(1, True)  # must not raise

    def test_get_capabilities_returns_descriptor(self):
        tc = _make_tc()
        caps = tc.get_capabilities()
        assert isinstance(caps, ControllerCapabilities)
        assert caps.num_inputs == 2
        assert caps.num_loops == 1
        assert caps.input_channels == ("A", "B")
        assert caps.loop_numbers == (1,)
        assert caps.has_ramp is True
        assert caps.has_pid is True

    def test_capabilities_optional_flags_default_false(self):
        caps = ControllerCapabilities(
            num_inputs=1,
            num_loops=1,
            input_channels=("A",),
            loop_numbers=(1,),
        )
        assert caps.has_autotune is False
        assert caps.has_alarm is False
        assert caps.has_zone is False
        assert caps.has_user_curves is False
        assert caps.has_sensor_excitation is False
        assert caps.has_cryogen_control is False
        assert caps.min_temperature is None
        assert caps.max_temperature is None

    def test_capabilities_with_temperature_bounds(self):
        caps = ControllerCapabilities(
            num_inputs=4,
            num_loops=2,
            input_channels=("A", "B", "C", "D"),
            loop_numbers=(1, 2),
            min_temperature=1.5,
            max_temperature=400.0,
        )
        assert caps.min_temperature == pytest.approx(1.5)
        assert caps.max_temperature == pytest.approx(400.0)

    def test_capabilities_is_immutable(self):
        caps = ControllerCapabilities(
            num_inputs=1,
            num_loops=1,
            input_channels=("A",),
            loop_numbers=(1,),
        )
        with pytest.raises((AttributeError, TypeError)):
            caps.num_inputs = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TemperatureController — enumerations
# ---------------------------------------------------------------------------


class TestTemperatureControllerEnums:
    """Tests for the four public enumerations."""

    def test_control_mode_members(self):
        assert ControlMode.OFF.value == "off"
        assert ControlMode.CLOSED_LOOP.value == "closed_loop"
        assert ControlMode.ZONE.value == "zone"
        assert ControlMode.OPEN_LOOP.value == "open_loop"
        assert ControlMode.MONITOR.value == "monitor"

    def test_ramp_state_members(self):
        assert RampState.IDLE.value == "idle"
        assert RampState.RAMPING.value == "ramping"

    def test_sensor_status_members(self):
        assert SensorStatus.OK.value == "ok"
        assert SensorStatus.INVALID.value == "invalid"
        assert SensorStatus.OVERRANGE.value == "overrange"
        assert SensorStatus.UNDERRANGE.value == "underrange"
        assert SensorStatus.FAULT.value == "fault"

    def test_alarm_state_members(self):
        assert AlarmState.DISABLED.value == "disabled"
        assert AlarmState.OK.value == "ok"
        assert AlarmState.LOW.value == "low"
        assert AlarmState.HIGH.value == "high"


# ---------------------------------------------------------------------------
# TemperatureController — data classes
# ---------------------------------------------------------------------------


class TestTemperatureControllerDataClasses:
    """Tests for the five public data classes."""

    def test_pid_parameters_fields(self):
        pid = PIDParameters(p=50.0, i=2.0, d=0.5)
        assert pid.p == pytest.approx(50.0)
        assert pid.i == pytest.approx(2.0)
        assert pid.d == pytest.approx(0.5)

    def test_pid_parameters_is_frozen(self):
        pid = PIDParameters(p=1.0, i=1.0, d=1.0)
        with pytest.raises((AttributeError, TypeError)):
            pid.p = 99.0  # type: ignore[misc]

    def test_temperature_reading_defaults_units_to_kelvin(self):
        reading = TemperatureReading(value=77.0, status=SensorStatus.OK)
        assert reading.units == "K"

    def test_temperature_reading_custom_units(self):
        reading = TemperatureReading(value=1000.0, status=SensorStatus.OK, units="Ohm")
        assert reading.units == "Ohm"

    def test_temperature_reading_is_frozen(self):
        r = TemperatureReading(value=1.0, status=SensorStatus.OK)
        with pytest.raises((AttributeError, TypeError)):
            r.value = 2.0  # type: ignore[misc]

    def test_loop_status_fields(self):
        ls = LoopStatus(
            setpoint=80.0,
            process_value=77.0,
            mode=ControlMode.CLOSED_LOOP,
            heater_output=25.0,
            ramp_enabled=False,
            ramp_rate=10.0,
            ramp_state=RampState.IDLE,
            p=50.0,
            i=2.0,
            d=0.0,
            input_channel="A",
        )
        assert ls.setpoint == pytest.approx(80.0)
        assert ls.process_value == pytest.approx(77.0)
        assert ls.mode is ControlMode.CLOSED_LOOP
        assert ls.heater_output == pytest.approx(25.0)
        assert ls.ramp_enabled is False
        assert ls.ramp_rate == pytest.approx(10.0)
        assert ls.ramp_state is RampState.IDLE
        assert ls.p == pytest.approx(50.0)
        assert ls.input_channel == "A"

    def test_temperature_status_fields(self):
        reading = TemperatureReading(value=77.0, status=SensorStatus.OK)
        loop = LoopStatus(
            setpoint=80.0,
            process_value=77.0,
            mode=ControlMode.CLOSED_LOOP,
            heater_output=25.0,
            ramp_enabled=False,
            ramp_rate=10.0,
            ramp_state=RampState.IDLE,
            p=50.0,
            i=2.0,
            d=0.0,
            input_channel="A",
        )
        status = TemperatureStatus(
            temperatures={"A": reading},
            loops={1: loop},
        )
        assert status.temperatures["A"] is reading
        assert status.loops[1] is loop
        assert status.error_state is None

    def test_temperature_status_error_state(self):
        status = TemperatureStatus(temperatures={}, loops={}, error_state="sensor fault")
        assert status.error_state == "sensor fault"


# ---------------------------------------------------------------------------
# TemperatureController — concrete composite methods
# ---------------------------------------------------------------------------


class TestTemperatureControllerComposite:
    """Tests for the concrete methods built from core abstracts."""

    def test_get_temperature_reading(self):
        tc = _make_tc()
        reading = tc.get_temperature_reading("A")
        assert isinstance(reading, TemperatureReading)
        assert reading.value == pytest.approx(77.0)
        assert reading.status is SensorStatus.OK
        assert reading.units == "K"

    def test_get_ramp_state_when_disabled(self):
        tc = _make_tc()
        assert tc.get_ramp_state(1) is RampState.IDLE

    def test_get_ramp_state_when_enabled(self, monkeypatch):
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_ramp_enabled", lambda self, loop: True)
        assert tc.get_ramp_state(1) is RampState.RAMPING

    def test_get_loop_status(self):
        tc = _make_tc()
        ls = tc.get_loop_status(1)
        assert isinstance(ls, LoopStatus)
        assert ls.setpoint == pytest.approx(80.0)
        assert ls.process_value == pytest.approx(77.0)
        assert ls.mode is ControlMode.CLOSED_LOOP
        assert ls.heater_output == pytest.approx(25.0)
        assert ls.ramp_enabled is False
        assert ls.ramp_rate == pytest.approx(10.0)
        assert ls.ramp_state is RampState.IDLE
        assert ls.p == pytest.approx(50.0)
        assert ls.i == pytest.approx(2.0)
        assert ls.d == pytest.approx(0.0)
        assert ls.input_channel == "A"

    def test_get_controller_status(self):
        tc = _make_tc()
        status = tc.get_controller_status()
        assert isinstance(status, TemperatureStatus)
        assert set(status.temperatures.keys()) == {"A", "B"}
        assert 1 in status.loops
        assert status.error_state is None

    def test_wait_for_setpoint_immediate_success(self, monkeypatch):
        """Temperature already within tolerance — should return immediately."""
        tc = _make_tc()
        # setpoint = 80.0, temperature = 77.0 — but with tolerance >= 3.0 it passes
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, channel: 79.8)
        tc.wait_for_setpoint(1, "A", tolerance=1.0, timeout=1.0, poll_period=0.01)

    def test_wait_for_setpoint_times_out(self, monkeypatch):
        """Temperature never reaches setpoint — TimeoutError must be raised."""
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, channel: 50.0)
        with pytest.raises(TimeoutError, match="channel 'A'"):
            tc.wait_for_setpoint(1, "A", tolerance=0.5, timeout=0.05, poll_period=0.01)

    def test_wait_for_setpoint_converges(self, monkeypatch):
        """Temperature converges after a few polls."""
        readings = iter([50.0, 70.0, 79.6, 80.1])

        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, ch: next(readings))
        tc.wait_for_setpoint(1, "A", tolerance=0.5, timeout=5.0, poll_period=0.001)


# ---------------------------------------------------------------------------
# TemperatureController — optional methods raise NotImplementedError
# ---------------------------------------------------------------------------


class TestTemperatureControllerOptional:
    """Optional methods must raise NotImplementedError on the base stub."""

    def test_get_alarm_state_raises(self):
        with pytest.raises(NotImplementedError, match="has_alarm"):
            _make_tc().get_alarm_state("A")

    def test_get_alarm_limits_raises(self):
        with pytest.raises(NotImplementedError, match="has_alarm"):
            _make_tc().get_alarm_limits("A")

    def test_set_alarm_limits_raises(self):
        with pytest.raises(NotImplementedError, match="has_alarm"):
            _make_tc().set_alarm_limits("A", 10.0, 400.0)

    def test_set_alarm_enabled_raises(self):
        with pytest.raises(NotImplementedError, match="has_alarm"):
            _make_tc().set_alarm_enabled("A", True)

    def test_get_num_zones_raises(self):
        with pytest.raises(NotImplementedError, match="has_zone"):
            _make_tc().get_num_zones(1)

    def test_get_zone_raises(self):
        with pytest.raises(NotImplementedError, match="has_zone"):
            _make_tc().get_zone(1, 1)

    def test_set_zone_raises(self):
        entry = ZoneEntry(upper_bound=50.0, p=10.0, i=1.0, d=0.0, ramp_rate=5.0, heater_range=1, heater_output=25.0)
        with pytest.raises(NotImplementedError, match="has_zone"):
            _make_tc().set_zone(1, 1, entry)

    def test_start_autotune_raises(self):
        with pytest.raises(NotImplementedError, match="has_autotune"):
            _make_tc().start_autotune(1)

    def test_get_autotune_status_raises(self):
        with pytest.raises(NotImplementedError, match="has_autotune"):
            _make_tc().get_autotune_status(1)

    def test_get_excitation_raises(self):
        with pytest.raises(NotImplementedError, match="has_sensor_excitation"):
            _make_tc().get_excitation("A")

    def test_set_excitation_raises(self):
        with pytest.raises(NotImplementedError, match="has_sensor_excitation"):
            _make_tc().set_excitation("A", 10.0)

    def test_get_filter_raises(self):
        with pytest.raises(NotImplementedError, match="has_sensor_excitation"):
            _make_tc().get_filter("A")

    def test_set_filter_raises(self):
        with pytest.raises(NotImplementedError, match="has_sensor_excitation"):
            _make_tc().set_filter("A", enabled=True, points=10, window=2.0)

    def test_get_sensor_curve_raises(self):
        with pytest.raises(NotImplementedError, match="has_user_curves"):
            _make_tc().get_sensor_curve("A")

    def test_set_sensor_curve_raises(self):
        with pytest.raises(NotImplementedError, match="has_user_curves"):
            _make_tc().set_sensor_curve("A", 21)

    def test_get_gas_flow_raises(self):
        with pytest.raises(NotImplementedError, match="has_cryogen_control"):
            _make_tc().get_gas_flow()

    def test_set_gas_flow_raises(self):
        with pytest.raises(NotImplementedError, match="has_cryogen_control"):
            _make_tc().set_gas_flow(50.0)

    def test_get_needle_valve_raises(self):
        with pytest.raises(NotImplementedError, match="has_cryogen_control"):
            _make_tc().get_needle_valve()

    def test_set_needle_valve_raises(self):
        with pytest.raises(NotImplementedError, match="has_cryogen_control"):
            _make_tc().set_needle_valve(25.0)


# ---------------------------------------------------------------------------
# TemperatureController — package-level exports
# ---------------------------------------------------------------------------


class TestTemperatureControllerExports:
    """New types must be importable from the top-level instruments package."""

    def test_all_types_exported(self):
        from stoner_measurement.instruments import (
            AlarmState,
            ControllerCapabilities,
            ControlMode,
            LoopStatus,
            PIDParameters,
            RampState,
            SensorStatus,
            TemperatureController,
            TemperatureReading,
            TemperatureStatus,
            ZoneEntry,
        )

        assert AlarmState is not None
        assert ControllerCapabilities is not None
        assert ControlMode is not None
        assert LoopStatus is not None
        assert PIDParameters is not None
        assert RampState is not None
        assert SensorStatus is not None
        assert TemperatureController is not None
        assert TemperatureReading is not None
        assert TemperatureStatus is not None
        assert ZoneEntry is not None


class TestLockInAmplifierExports:
    """Lock-in types must be importable from the top-level instruments package."""

    def test_all_types_exported(self):
        from stoner_measurement.instruments import (
            LockInAmplifier,
            LockInAmplifierCapabilities,
            LockInInputCoupling,
            LockInReferenceSource,
            LockInReserveMode,
        )

        assert LockInAmplifier is not None
        assert LockInAmplifierCapabilities is not None
        assert LockInInputCoupling is not None
        assert LockInReferenceSource is not None
        assert LockInReserveMode is not None


# ---------------------------------------------------------------------------
# ZoneEntry dataclass
# ---------------------------------------------------------------------------


class TestZoneEntry:
    """Tests for the ZoneEntry frozen dataclass."""

    def test_fields_round_trip(self):
        entry = ZoneEntry(
            upper_bound=100.0,
            p=50.0,
            i=2.0,
            d=0.5,
            ramp_rate=10.0,
            heater_range=2,
            heater_output=30.0,
        )
        assert entry.upper_bound == pytest.approx(100.0)
        assert entry.p == pytest.approx(50.0)
        assert entry.i == pytest.approx(2.0)
        assert entry.d == pytest.approx(0.5)
        assert entry.ramp_rate == pytest.approx(10.0)
        assert entry.heater_range == 2
        assert entry.heater_output == pytest.approx(30.0)

    def test_is_frozen(self):
        entry = ZoneEntry(
            upper_bound=50.0, p=10.0, i=1.0, d=0.0,
            ramp_rate=5.0, heater_range=1, heater_output=25.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            entry.heater_output = 50.0  # type: ignore[misc]

    def test_zero_ramp_rate_allowed(self):
        """ramp_rate=0 means immediate setpoint change (no ramping)."""
        entry = ZoneEntry(
            upper_bound=50.0, p=10.0, i=1.0, d=0.0,
            ramp_rate=0.0, heater_range=0, heater_output=0.0,
        )
        assert entry.ramp_rate == pytest.approx(0.0)
        assert entry.heater_range == 0

    def test_full_heater_power(self):
        """heater_output of 100 % is a valid upper boundary."""
        entry = ZoneEntry(
            upper_bound=400.0, p=100.0, i=10.0, d=1.0,
            ramp_rate=2.0, heater_range=5, heater_output=100.0,
        )
        assert entry.heater_output == pytest.approx(100.0)
        assert entry.heater_range == 5


# ---------------------------------------------------------------------------
# ZoneEntry — optional zone API (NotImplementedError paths)
# ---------------------------------------------------------------------------


class TestZoneEntryOptionalAPI:
    """The updated zone optional methods use ZoneEntry; NotImplementedError paths."""

    def test_get_zone_raises(self):
        with pytest.raises(NotImplementedError, match="has_zone"):
            _make_tc().get_zone(1, 1)

    def test_set_zone_raises_with_entry(self):
        entry = ZoneEntry(
            upper_bound=100.0, p=50.0, i=2.0, d=0.0,
            ramp_rate=5.0, heater_range=1, heater_output=25.0,
        )
        with pytest.raises(NotImplementedError, match="has_zone"):
            _make_tc().set_zone(1, 1, entry)


# ---------------------------------------------------------------------------
# ramp_to_setpoint composite method
# ---------------------------------------------------------------------------


class TestRampToSetpoint:
    """Tests for the ramp_to_setpoint concrete composite method."""

    def test_ramp_to_setpoint_enables_ramp_and_sets_setpoint(self, monkeypatch):
        """When has_ramp=True and no rate given: enables ramp then sets setpoint."""
        calls = []
        tc = _make_tc()

        monkeypatch.setattr(type(tc), "set_ramp_enabled", lambda self, loop, enabled: calls.append(("ramp_enabled", loop, enabled)))
        monkeypatch.setattr(type(tc), "set_setpoint", lambda self, loop, val: calls.append(("setpoint", loop, val)))

        tc.ramp_to_setpoint(1, 200.0)

        assert ("ramp_enabled", 1, True) in calls
        assert ("setpoint", 1, 200.0) in calls
        # setpoint must be written after ramp is enabled
        assert calls.index(("ramp_enabled", 1, True)) < calls.index(("setpoint", 1, 200.0))

    def test_ramp_to_setpoint_sets_rate_when_provided(self, monkeypatch):
        """When rate is supplied it is written before enabling ramping."""
        calls = []
        tc = _make_tc()

        monkeypatch.setattr(type(tc), "set_ramp_rate", lambda self, loop, rate: calls.append(("rate", loop, rate)))
        monkeypatch.setattr(type(tc), "set_ramp_enabled", lambda self, loop, en: calls.append(("enabled", loop, en)))
        monkeypatch.setattr(type(tc), "set_setpoint", lambda self, loop, val: calls.append(("sp", loop, val)))

        tc.ramp_to_setpoint(1, 150.0, rate=5.0)

        assert ("rate", 1, 5.0) in calls
        assert ("enabled", 1, True) in calls
        assert ("sp", 1, 150.0) in calls
        # order: set_ramp_rate → set_ramp_enabled → set_setpoint
        assert calls.index(("rate", 1, 5.0)) < calls.index(("enabled", 1, True))
        assert calls.index(("enabled", 1, True)) < calls.index(("sp", 1, 150.0))

    def test_ramp_to_setpoint_skips_ramp_when_not_supported(self, monkeypatch):
        """When has_ramp=False, ramp methods are not called."""
        calls = []
        tc = _make_tc()

        # Override capabilities to report has_ramp=False
        monkeypatch.setattr(
            type(tc),
            "get_capabilities",
            lambda self: ControllerCapabilities(
                num_inputs=2, num_loops=1,
                input_channels=("A", "B"), loop_numbers=(1,),
                has_ramp=False,
            ),
        )
        monkeypatch.setattr(type(tc), "set_ramp_rate", lambda self, loop, rate: calls.append("rate"))
        monkeypatch.setattr(type(tc), "set_ramp_enabled", lambda self, loop, en: calls.append("enabled"))
        monkeypatch.setattr(type(tc), "set_setpoint", lambda self, loop, val: calls.append(("sp", val)))

        tc.ramp_to_setpoint(1, 200.0, rate=5.0)

        # ramp methods must not be called
        assert "rate" not in calls
        assert "enabled" not in calls
        # but setpoint must still be written
        assert ("sp", 200.0) in calls

    def test_ramp_to_setpoint_no_rate_no_set_ramp_rate_call(self, monkeypatch):
        """When rate=None, set_ramp_rate must not be called."""
        calls = []
        tc = _make_tc()

        monkeypatch.setattr(type(tc), "set_ramp_rate", lambda self, loop, rate: calls.append("rate"))
        monkeypatch.setattr(type(tc), "set_ramp_enabled", lambda self, loop, en: calls.append("enabled"))
        monkeypatch.setattr(type(tc), "set_setpoint", lambda self, loop, val: calls.append("sp"))

        tc.ramp_to_setpoint(1, 100.0)  # rate omitted (None)

        assert "rate" not in calls
        assert "enabled" in calls
        assert "sp" in calls
