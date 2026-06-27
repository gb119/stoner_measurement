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

import logging

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
    Lakeshore625,
    LakeshoreM81CurrentSource,
    LakeshoreM81LockIn,
)
from stoner_measurement.instruments.lock_registry import canonical_resource_key
from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInExpandFactor,
    LockInInputCoupling,
    LockInInputShielding,
    LockInInputSource,
    LockInLineFilter,
    LockInOutput,
    LockInOutputChannel,
    LockinRefenceEdge,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
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
    OxfordMercuryIPS,
    OxfordMercuryTemperatureController,
)
from stoner_measurement.instruments.oxford import (
    temperature_controllers as oxford_temperature_controllers,
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
    InputChannelSettings,
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
from stoner_measurement.instruments.transport.gpib_transport import (
    GpibTransport,
    PassThroughGpibTransport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    t = NullTransport(responses=responses or [])
    t.open()
    return t


class _NullTransportWithEsb(NullTransport):
    """Null transport variant that reports ESB set for SCPI error polling tests."""

    def read_status_byte(self) -> int:
        """Return a status byte with IEEE 488.2 Event Status Bit (bit 2) set.

        Returns:
            (int): ``0x04`` so tests exercise the SCPI error-queue polling path.
        """
        return 0x04


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


# pylint: disable=abstract-class-instantiated
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

    def test_read_uses_transport_read_not_read_until(self):
        class _ReadOnlyTransport(NullTransport):
            def read(self, num_bytes: int = 4096) -> bytes:
                return b"ACME,MODEL,SN,FW\r\n"

            def read_until(self, terminator: bytes = b"\n") -> bytes:
                raise AssertionError("read_until should not be called")

        t = _ReadOnlyTransport()
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(terminator=b"\r\n"))
        assert instr.read() == "ACME,MODEL,SN,FW"

    def test_constructor_binds_protocol_to_transport(self):
        class _ProtocolAwareTransport(NullTransport):
            def __init__(self):
                super().__init__()
                self.bound_protocol = None

            def set_protocol(self, protocol: object) -> None:
                super().set_protocol(protocol)
                self.bound_protocol = protocol

        transport = _ProtocolAwareTransport()
        protocol = LakeshoreProtocol()
        BaseInstrument(transport, protocol)
        assert transport.bound_protocol is protocol

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

    def test_query_logs_tx_and_rx_transcript_records(self, caplog):
        t = _null(responses=[b"answer\n"])
        k = Keithley2400(transport=t)
        with caplog.at_level(logging.DEBUG, logger="stoner_measurement.sequence.comms"):
            assert k.query("*IDN?") == "answer"
        transcript_records = [
            record for record in caplog.records if getattr(record, "sm_traffic_channel", "") == "instrument_comms"
        ]
        assert len(transcript_records) == 2
        assert transcript_records[0].sm_traffic_direction == "TX"
        assert transcript_records[0].getMessage() == "TX *IDN?"
        assert transcript_records[0].sm_transport_address == ""
        assert transcript_records[1].sm_traffic_direction == "RX"
        assert transcript_records[1].getMessage() == "RX answer"
        assert transcript_records[1].sm_transport_address == ""


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
        assert OxfordProtocol().parse_response(b"R1.234\r", command="R1") == "1.234"

    def test_parse_response_legacy_fallback_without_command(self):
        assert OxfordProtocol().parse_response(b"R1.234\r") == "1.234"

    def test_parse_response_single_char(self):
        # Degenerate one-char response with no command context (fallback path).
        assert OxfordProtocol().parse_response(b"R") == "R"

    def test_parse_response_single_char_with_command(self):
        assert OxfordProtocol().parse_response(b"R", command="R1") == "R"

    def test_parse_response_preserves_non_matching_char(self):
        assert (
            OxfordProtocol().parse_response(
                b"ITC503 Version 1.11 (c) OXFORD 1997\r",
                command="V",
            )
            == "ITC503 Version 1.11 (c) OXFORD 1997"
        )

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
        assert Keithley2400(transport=t).set_compliance_from_resistance(1000.0, source_level=0.002, source_mode=SourceMode.CURR) == pytest.approx(2.0)
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

    def test_read_buffer_records_parses_explicit_format(self):
        t = _null(responses=[b"1,2,3,4,5,6,7,8,9,10\n"])
        records = Keithley2400(transport=t).read_buffer_records(("VOLT", "CURR", "RES", "TIME", "STAT"))
        assert len(records) == 2
        assert records[0].voltage == pytest.approx(1.0)
        assert records[0].current == pytest.approx(2.0)
        assert records[0].resistance == pytest.approx(3.0)
        assert records[0].time == pytest.approx(4.0)
        assert records[0].status == pytest.approx(5.0)
        assert t.write_log == [b":FORM:DATA ASC\n", b":FORM:ELEM VOLT,CURR,RES,TIME,STAT\n", b":TRAC:DATA?\n"]

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
        assert Keithley2400(transport=t).check_error_queue(raise_on_error=False) == ((0, "No error"),)

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

    def test_multi_output_measurement(self):
        t = _null(responses=[b"1.0,3.0,45.0\n"])
        k = SRS830(transport=t)
        values = k.measure_outputs((LockInOutput.X, LockInOutput.R, LockInOutput.THETA))
        assert values[LockInOutput.X] == pytest.approx(1.0)
        assert values[LockInOutput.R] == pytest.approx(3.0)
        assert values[LockInOutput.THETA] == pytest.approx(45.0)
        assert t.write_log == [b"SNAP?1,3,4\n"]

    def test_getters(self):
        t = _null(
            responses=[b"8\n", b"10\n", b"1\n", b"2\n", b"137.0\n", b"-12.5\n", b"3\n", b"2\n", b"1\n", b"2\n"]
        )
        k = SRS830(transport=t)
        assert k.get_sensitivity() == pytest.approx(1e-6)
        assert k.get_time_constant() == pytest.approx(1.0)
        assert k.get_reference_source() == (LockInReferenceSource.INTERNAL, LockinRefenceEdge.FALLING)
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
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(k, "wait_for_ifc", lambda: None)
            k.auto_gain()
            k.auto_phase()
            k.auto_reserve()
        assert t.write_log == [
            b"SENS 8\n",
            b"OFLT 10\n",
            b"FMOD 0\n",
            b"RSLP 2\n",
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
            k.set_harmonic(20000)
        with pytest.raises(ValueError):
            k.set_filter_slope(9)
        with pytest.raises(ValueError):
            k.set_oscillator_amplitude(0.003)
        with pytest.raises(ValueError):
            k.set_oscillator_amplitude(5.001)
        with pytest.raises(ValueError):
            k.set_output_offset(LockInOutputChannel.X, 106.0, LockInExpandFactor.X1)
        with pytest.raises(ValueError):
            k.set_output_offset(LockInOutputChannel.X, -106.0, LockInExpandFactor.X1)

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
        assert caps.has_output_offset
        assert caps.has_internal_oscillator
        assert caps.has_input_source_selection
        assert caps.has_input_shielding_control
        assert caps.has_line_filter_control
        assert caps.has_sync_filter
        assert caps.max_harmonic == 19999

    def test_oscillator_and_output_offset(self):
        t = _null(responses=[b"0.5\n", b"10.0,1\n"])
        k = SRS830(transport=t)
        assert k.get_oscillator_amplitude() == pytest.approx(0.5)
        offset_pct, expand = k.get_output_offset(LockInOutputChannel.X)
        assert offset_pct == pytest.approx(10.0)
        assert expand is LockInExpandFactor.X10
        k.set_oscillator_amplitude(1.0)
        k.set_output_offset(LockInOutputChannel.R, 5.0, LockInExpandFactor.X100)
        assert t.write_log == [b"SLVL 1.0\n", b"OEXP 3,5.0,2\n"]

    def test_input_source_and_shielding(self):
        t = _null(responses=[b"1\n", b"1\n"])
        k = SRS830(transport=t)
        assert k.get_input_source() is LockInInputSource.A_MINUS_B
        assert k.get_input_shielding() is LockInInputShielding.GROUND
        k.set_input_source(LockInInputSource.I_1MOHM)
        k.set_input_shielding(LockInInputShielding.FLOAT)
        assert t.write_log == [b"ISRC 2\n", b"IGND 0\n"]

    def test_line_filter_and_sync(self):
        t = _null(responses=[b"2\n", b"0\n"])
        k = SRS830(transport=t)
        assert k.get_line_filter() is LockInLineFilter.LINE_2X
        assert k.get_sync_filter_enabled() is False
        k.set_line_filter(LockInLineFilter.BOTH)
        k.set_sync_filter_enabled(True)
        assert t.write_log == [b"ILIN 3\n", b"SYNC 1\n"]


# ---------------------------------------------------------------------------
# LakeshoreM81LockIn concrete driver
# ---------------------------------------------------------------------------


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
            k.configure_sweep(CurrentSweepConfiguration(spacing=CurrentSweepSpacing.LIST, values=()))

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
        # cur_olin=3, cur_ilin=4, pmar disabled -- no temporary moves needed.
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
        # cur_olin=2 (= desired input_line) -> olin must be moved first.
        # free_line(input=2, output=1, cur_ilin=4, pmar=0) -> 3
        t = _null(responses=[b"2\n", b"4\n", b"0\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:OLIN 3\n",  # temporary move to free line 3
            b":TRIG:ILIN 2\n",
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_pmar_blocks_input(self):
        # cur_olin=3, cur_ilin=4, pmar on line 2 (= desired input_line).
        # free_line(input=2, output=1, cur_olin=3, cur_ilin=4) -> 5
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
        # cur_olin=3, cur_ilin=4, pmar on line 1 (= desired output_line).
        # After setting ILIN=2: free_line(output=1, ilin=2, cur_olin=3) -> 4
        t = _null(responses=[b"3\n", b"4\n", b"1\n", b"1\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:ILIN 2\n",
            b":SOUR:WAVE:PMAR:OLIN 4\n",  # move pmar away from line 1
            b":TRIG:OLIN 1\n",
        ]

    def test_configure_trigger_link_both_conflicts(self):
        # cur_olin=2 blocks input, pmar=1 blocks output.
        # Step 1: free_line(input=2, output=1, cur_ilin=4, pmar=1) → 3 (temp olin)
        # Step 3: free_line(output=1, ilin=2, cur_olin=3) → 4 (temp pmar)
        t = _null(responses=[b"2\n", b"4\n", b"1\n", b"1\n"])
        k = Keithley6221(transport=t)
        k.configure_trigger_link(output_line=1, input_line=2)
        assert t.write_log == [
            b":TRIG:OLIN?\n",
            b":TRIG:ILIN?\n",
            b":SOUR:WAVE:PMAR:OLIN?\n",
            b":TRIG:OLIN 3\n",  # move olin away from line 2
            b":TRIG:ILIN 2\n",
            b":SOUR:WAVE:PMAR:OLIN 4\n",  # move pmar away from line 1
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
        """A response ending in bare CR (no LF) does not satisfy the line terminator."""
        # The outer protocol terminator (b"\n") is present, but the inner payload
        # ends only in CR — combined.endswith("\n") will be False after stripping
        # the outer LF, so RuntimeError is raised after max_chunks is exhausted.
        t = _null(responses=[b"1.23\r\n"])
        k = Keithley6221(transport=t)
        with pytest.raises(RuntimeError, match="no line terminator"):
            k.query_serial_command("READ?", max_chunks=1)

    def test_query_serial_command_max_chunks_exhausted(self):
        """RuntimeError is raised when no LF-terminated response arrives within max_chunks."""
        # Each chunk carries partial data with only the outer protocol LF stripped;
        # the combined payload never ends with the inner response_terminator "\n".
        t = _null(responses=[b"part1\n", b"part2\n"])
        k = Keithley6221(transport=t)
        with pytest.raises(RuntimeError, match="no line terminator"):
            k.query_serial_command("READ?", max_chunks=2)

    def test_convenience_configure_custom_sweep(self):
        """configure_custom_sweep delegates to configure_sweep with LIST spacing."""
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
        """LIST sweep with > 100 points must use SOUR:LIST:CURR:APP for overflow batches."""
        from stoner_measurement.instruments.keithley.k6221 import _LIST_BATCH_SIZE

        t = _null()
        k = Keithley6221(transport=t)
        values = tuple(float(i) * 1e-5 for i in range(150))
        k.configure_custom_sweep(values)
        writes = [w.decode().strip() for w in t.write_log]
        assert writes[0] == ":SOUR:SWE:SPAC LIST"
        # Second write: first 100 values
        first_batch_cmd = writes[1]
        assert first_batch_cmd.startswith(":SOUR:LIST:CURR ")
        first_vals = first_batch_cmd[len(":SOUR:LIST:CURR ") :].split(",")
        assert len(first_vals) == _LIST_BATCH_SIZE
        # Third write: append remaining 50
        second_batch_cmd = writes[2]
        assert second_batch_cmd.startswith(":SOUR:LIST:CURR:APP ")
        second_vals = second_batch_cmd[len(":SOUR:LIST:CURR:APP ") :].split(",")
        assert len(second_vals) == 50
        # Fourth write: POIN = 150
        assert writes[3] == f":SOUR:SWE:POIN {len(values)}"

    def test_list_sweep_exactly_100_points_no_append(self):
        """A 100-point LIST sweep must not emit any SOUR:LIST:CURR:APP command."""
        t = _null()
        k = Keithley6221(transport=t)
        values = tuple(float(i) * 1e-5 for i in range(100))
        k.configure_custom_sweep(values)
        writes = [w.decode().strip() for w in t.write_log]
        app_cmds = [w for w in writes if w.startswith(":SOUR:LIST:CURR:APP")]
        assert app_cmds == []

    def test_configure_list_compliance_single_batch(self):
        """configure_list_compliance with ≤ 100 values uses SOUR:LIST:COMP only."""
        t = _null()
        k = Keithley6221(transport=t)
        k.configure_list_compliance([5.0, 10.0, 15.0])
        writes = [w.decode().strip() for w in t.write_log]
        assert len(writes) == 1
        assert writes[0].startswith(":SOUR:LIST:COMP ")
        parts = writes[0][len(":SOUR:LIST:COMP ") :].split(",")
        assert len(parts) == 3

    def test_configure_list_compliance_multi_batch(self):
        """configure_list_compliance with > 100 values appends with SOUR:LIST:COMP:APP."""
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
        """configure_list_compliance with an empty list must raise ValueError."""
        k = Keithley6221(transport=_null())
        with pytest.raises(ValueError, match="non-empty"):
            k.configure_list_compliance([])

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


# ---------------------------------------------------------------------------
# Lakeshore625 concrete driver
# ---------------------------------------------------------------------------


class TestLakeshore625:
    def test_default_protocol_is_lakeshore(self):
        m = Lakeshore625(transport=NullTransport())
        assert isinstance(m.protocol, LakeshoreProtocol)

    def test_identify_and_model_and_firmware(self):
        t = _null(
            responses=[
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        assert m.identify() == "LAKESHORE,MODEL625,SN001,1.2.3"
        assert m.get_model() == "MODEL625"
        assert m.get_firmware_version() == "1.2.3"

    def test_reading_properties_send_correct_commands(self):
        t = _null(responses=[b"2.5\r\n", b"0.75\r\n", b"1.2\r\n"])
        m = Lakeshore625(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

    def test_current_uses_first_value_from_comma_separated_response(self):
        t = _null(responses=[b"2.5,OK\r\n"])
        m = Lakeshore625(transport=t)
        assert m.current == pytest.approx(2.5)

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.set_target_current(3.0)
        m.set_target_field(0.9)
        m.ramp_to_target()
        assert t.write_log == [b"SETI 3.0\r\n", b"SETF 0.9\r\n", b"RAMP\r\n"]

    def test_heater_methods_and_property(self):
        t = _null(responses=[b"1\r\n"])
        m = Lakeshore625(transport=t)
        m.heater_on()
        m.heater_off()
        assert m.heater is True
        assert t.write_log == [b"PSH 1\r\n", b"PSH 0\r\n", b"PSH?\r\n"]

    def test_heater_property_false_during_transition(self):
        t = _null(responses=[b"2\r\n", b"3\r\n"])
        m = Lakeshore625(transport=t)
        assert m.heater is False
        assert m.heater is False
        assert t.write_log == [b"PSH?\r\n", b"PSH?\r\n"]

    def test_status_maps_heater_transition_states(self):
        for psh_reply, expected in ((b"2\r\n", HeaterState.COOLING), (b"3\r\n", HeaterState.WARMING)):
            t = _null(
                responses=[b"2\r\n", psh_reply, b"1.1\r\n", b"0.3\r\n", b"0.2\r\n"]
            )
            m = Lakeshore625(transport=t)
            status = m.status
            assert status.heater_state is expected
            assert status.heater_on is False

    def test_status_maps_state(self):
        # RDGST? returns numeric bit-coded status: bit 1 (0x02) = AT_TARGET
        t = _null(
            responses=[
                b"2\r\n",
                b"0\r\n",
                b"1.1\r\n",
                b"0.3\r\n",
                b"0.2\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "at_target"
        assert status.at_target is True
        assert status.current == pytest.approx(1.1)
        assert status.field == pytest.approx(0.3)
        assert status.voltage == pytest.approx(0.2)
        assert status.heater_on is False
        assert t.write_log == [b"RDGST?\r\n", b"PSH?\r\n", b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

    def test_status_maps_ramping_state(self):
        # RDGST? bit 0 (0x01) = RAMPING
        t = _null(
            responses=[
                b"1\r\n",
                b"0.5\r\n",
                b"0.1\r\n",
                b"0.1\r\n",
                b"1\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "ramping"
        assert status.at_target is False

    def test_status_maps_fault_state(self):
        # RDGST? bit 2 (0x04) = FAULT
        t = _null(
            responses=[
                b"4\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "fault"

    def test_status_maps_quench_state(self):
        # RDGST? bit 3 (0x08) = QUENCH
        t = _null(
            responses=[
                b"8\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "quench"

    def test_status_standby_when_no_bits_set(self):
        # RDGST? returns 0 = STANDBY
        t = _null(
            responses=[
                b"0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "standby"

    def test_status_unknown_for_unparseable_rdgst_response(self, caplog):
        t = _null(
            responses=[
                b"not-an-int\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence.comms"):
            status = m.status
        assert status.state is MagnetState.UNKNOWN
        assert status.at_target is False
        assert any("marking status UNKNOWN" in record.getMessage() for record in caplog.records)

    def test_status_unknown_for_unhandled_rdgst_bits(self, caplog):
        t = _null(
            responses=[
                b"16\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence.comms"):
            status = m.status
        assert status.state is MagnetState.UNKNOWN
        assert status.at_target is False
        assert any("unhandled status bits 0x10" in record.getMessage() for record in caplog.records)

    def test_set_magnet_constant_validation(self):
        m = Lakeshore625(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)

    def test_query_float_raises_for_unparseable_numeric_response(self):
        t = _null(responses=[b"not-a-float\r\n"])
        m = Lakeshore625(transport=t)
        with pytest.raises(ValueError):
            _ = m.current

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = Lakeshore625(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=False,
                heater_state=HeaterState.OFF,
                at_target=False,
                message="ramping",
            )

        monkeypatch.setattr(Lakeshore625, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)

    def test_lakeshore525_is_alias_for_lakeshore625(self):
        """Lakeshore525 is a backward-compatibility alias for Lakeshore625."""
        assert Lakeshore525 is Lakeshore625


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
        assert t.write_log == [b"R1\r", b"R7\r", b"R2\r"]

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = OxfordIPS120(transport=t)
        m.set_target_current(3.0)
        m.set_ramp_rate_current(0.2)
        m.ramp_to_target()
        assert t.write_log == [b"I3.0\r", b"S0.2\r", b"A1\r"]

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
        assert t.write_log == [b"X\r", b"R1\r", b"R7\r", b"R2\r"]

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
        assert t.write_log == [b"I2.0\r"]

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
                heater_state=HeaterState.OFF,
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
        # Zone and input settings capabilities
        for caps in (caps_335, caps_336):
            assert caps.has_zone is True
            assert caps.has_input_settings is True
        # 340 does not support ZONE/ZONE? commands
        assert caps_340.has_zone is False
        assert caps_340.has_input_settings is True

    def test_lakeshore336_get_num_zones(self):
        tc = Lakeshore336(transport=_null())
        assert tc.get_num_zones(1) == 10
        assert tc.get_num_zones(2) == 10
        assert tc.get_num_zones(3) == 10
        assert tc.get_num_zones(4) == 10

    def test_lakeshore336_get_num_zones_invalid_loop(self):
        tc = Lakeshore336(transport=_null())
        with pytest.raises(ValueError):
            tc.get_num_zones(5)

    def test_lakeshore336_get_zone(self):
        t = _null(responses=[b"100.0,50.0,10.0,0.5,25.0,2\r\n"])
        tc = Lakeshore336(transport=t)
        zone = tc.get_zone(1, 1)
        assert zone.upper_bound == pytest.approx(100.0)
        assert zone.p == pytest.approx(50.0)
        assert zone.i == pytest.approx(10.0)
        assert zone.d == pytest.approx(0.5)
        assert zone.heater_output == pytest.approx(25.0)
        assert zone.heater_range == 2
        assert t.write_log == [b"ZONE? 1,1\r\n"]

    def test_lakeshore336_set_zone(self):
        t = _null()
        tc = Lakeshore336(transport=t)
        zone = ZoneEntry(upper_bound=100.0, p=50.0, i=10.0, d=0.5, ramp_rate=0.0, heater_range=2, heater_output=25.0)
        tc.set_zone(1, 1, zone)
        assert t.write_log == [b"ZONE 1,1,100.0,50.0,10.0,0.5,25.0,2\r\n"]

    def test_lakeshore336_get_input_channel_settings(self):
        t = _null(
            responses=[
                b"3,0,4,0,1\r\n",  # INTYPE? response
                b"1,10,2.0\r\n",  # FILTER? response
                b"22\r\n",  # INCRV? response
            ]
        )
        tc = Lakeshore336(transport=t)
        settings = tc.get_input_channel_settings("A")
        assert settings.sensor_type == 3
        assert settings.autorange is False
        assert settings.range_ == 4
        assert settings.compensation is False
        assert settings.units == 1
        assert settings.filter_enabled is True
        assert settings.filter_points == 10
        assert settings.filter_window == pytest.approx(2.0)
        assert settings.curve_number == 22
        assert t.write_log == [b"INTYPE? A\r\n", b"FILTER? A\r\n", b"INCRV? A\r\n"]

    def test_lakeshore336_get_calibration_curve_names(self):
        from unittest.mock import MagicMock

        tc = Lakeshore336(transport=_null())
        tc.query = MagicMock(
            side_effect=[
                "Standard Diode,0,0,0,0",
                '"Cernox, 1k, custom",0,0,0,0',
            ]
            + [RuntimeError("unsupported curve")] * 58
        )
        names = tc.get_calibration_curve_names()
        assert names == {
            1: "Standard Diode",
            2: "Cernox, 1k, custom",
        }
        assert tc.query.call_count == 3
        assert tc.get_calibration_curve_names() == names
        assert tc.query.call_count == 3

    def test_lakeshore336_set_input_channel_settings_all_fields(self):
        t = _null()
        tc = Lakeshore336(transport=t)
        settings = InputChannelSettings(
            sensor_type=3,
            autorange=False,
            range_=4,
            compensation=False,
            units=1,
            filter_enabled=True,
            filter_points=10,
            filter_window=2.0,
            curve_number=22,
        )
        tc.set_input_channel_settings("A", settings)
        assert t.write_log == [
            b"INTYPE A,3,0,4,0,1\r\n",
            b"FILTER A,1,10,2.0\r\n",
            b"INCRV A,22\r\n",
        ]

    def test_lakeshore336_set_input_channel_settings_partial(self):
        # Only filter_enabled set; should read current FILTER? first.
        t = _null(responses=[b"0,5,1.5\r\n"])  # FILTER? read: enabled=0, points=5, window=1.5
        tc = Lakeshore336(transport=t)
        settings = InputChannelSettings(filter_enabled=True)
        tc.set_input_channel_settings("A", settings)
        # FILTER? read then FILTER write (filter_enabled overridden, points/window preserved).
        assert t.write_log == [b"FILTER? A\r\n", b"FILTER A,1,5,1.5\r\n"]

    def test_lakeshore336_set_input_channel_settings_curve_only(self):
        t = _null()
        tc = Lakeshore336(transport=t)
        settings = InputChannelSettings(curve_number=5)
        tc.set_input_channel_settings("A", settings)
        assert t.write_log == [b"INCRV A,5\r\n"]

    def test_lakeshore340_get_input_channel_uses_cset(self):
        # CSET? returns: input_index, units, onoff, powerup_enable
        t = _null(responses=[b"2,1,1,0\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_input_channel(1) == "B"
        assert t.write_log == [b"CSET? 1\r\n"]

    def test_lakeshore340_set_input_channel_uses_cset(self):
        # First CSET? reads current params, then CSET writes updated input index
        t = _null(responses=[b"1,1,1,0\r\n"])
        tc = Lakeshore340(transport=t)
        tc.set_input_channel(1, "B")
        assert t.write_log == [b"CSET? 1\r\n", b"CSET 1,2,1,1,0\r\n"]

    def test_lakeshore340_get_loop_mode_uses_cmode(self):
        t = _null(responses=[b"1\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert t.write_log == [b"CMODE? 1\r\n"]

    def test_lakeshore340_set_loop_mode_uses_cmode(self):
        t = _null()
        tc = Lakeshore340(transport=t)
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)
        assert t.write_log == [b"CMODE 1,3\r\n"]

    def test_lakeshore340_zone_methods_raise_not_implemented(self):
        tc = Lakeshore340(transport=_null())
        with pytest.raises(NotImplementedError):
            tc.get_num_zones(1)
        with pytest.raises(NotImplementedError):
            tc.get_zone(1, 1)
        with pytest.raises(NotImplementedError):
            zone = ZoneEntry(
                upper_bound=100.0, p=50.0, i=10.0, d=0.0, ramp_rate=0.0, heater_range=1, heater_output=0.0
            )
            tc.set_zone(1, 1, zone)

    def test_lakeshore336_loop_numbers(self):
        caps = Lakeshore336(transport=_null()).get_capabilities()
        assert caps.loop_numbers == (1, 2, 3, 4)
        assert caps.num_loops == 4


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
                b"X00A1C0H1P0\r",
                b"R22.5\r",
                b"R30.0\r",
                b"R4.0\r",
                b"R0.0\r",
            ]
        )
        tc = OxfordITC503(transport=t)
        assert tc.get_temperature("A") == pytest.approx(4.2)
        assert tc.get_setpoint(1) == pytest.approx(10.0)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert tc.get_heater_output(1) == pytest.approx(22.5)
        assert tc.get_pid(1) == PIDParameters(30.0, 4.0, 0.0)
        assert tc.get_ramp_rate(1) == pytest.approx(0.0)
        tc.set_setpoint(1, 12.0)
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)
        tc.set_input_channel(1, "B")
        tc.set_pid(1, 30.0, 4.0, 0.0)
        tc.set_ramp_enabled(1, True)
        assert t.write_log == [
            b"R1\r",
            b"R0\r",
            b"X\r",
            b"R5\r",
            b"R8\r",
            b"R9\r",
            b"R10\r",
            b"T12.0\r",
            b"A2\r",
            b"C1\r",
            b"P30.0\r",
            b"I4.0\r",
            b"D0.0\r",
            b"S1\r",
        ]

    def test_itc503_temperature_calibration_applies_to_reads_and_writes(self, monkeypatch):
        monkeypatch.setattr(
            oxford_temperature_controllers,
            "_load_itc503_temperature_calibration_config",
            lambda: {
                "temperature_calibration": {
                    "lookup_table": [
                        {"true_temperature": 0.0, "itc503_temperature": 0.0},
                        {"true_temperature": 10.0, "itc503_temperature": 11.0},
                        {"true_temperature": 20.0, "itc503_temperature": 22.0},
                        {"true_temperature": 30.0, "itc503_temperature": 33.0},
                    ]
                }
            },
        )
        t = _null(responses=[b"R11.0\r", b"R22.0\r"])
        tc = OxfordITC503(transport=t)

        assert tc.get_temperature("A") == pytest.approx(10.0)
        assert tc.get_setpoint(1) == pytest.approx(20.0)
        tc.set_setpoint(1, 30.0)
        tc.set_setpoint(1, 40.0)

        assert t.write_log == [
            b"R1\r",
            b"R0\r",
            b"T33.0\r",
            b"T40.0\r",
        ]

    def test_itc503_temperature_calibration_applies_to_zone_upper_bound(self, monkeypatch):
        monkeypatch.setattr(
            oxford_temperature_controllers,
            "_load_itc503_temperature_calibration_config",
            lambda: {
                "temperature_calibration": {
                    "lookup_table": [
                        [0.0, 0.0],
                        [10.0, 11.0],
                        [20.0, 22.0],
                        [30.0, 33.0],
                    ]
                }
            },
        )
        t = _null(responses=[b"Q22.0\r", b"Q30.0\r", b"Q4.0\r", b"Q0.5\r"])
        tc = OxfordITC503(transport=t)

        zone = tc.get_zone(1, 2)
        tc.set_zone(1, 3, ZoneEntry(10.0, 40.0, 5.0, 1.0, 0.0, 0, 0.0))

        assert zone.upper_bound == pytest.approx(20.0)
        assert t.write_log == [
            b"x2\r",
            b"y1\r",
            b"q\r",
            b"x2\r",
            b"y2\r",
            b"q\r",
            b"x2\r",
            b"y3\r",
            b"q\r",
            b"x2\r",
            b"y4\r",
            b"q\r",
            b"x3\r",
            b"y1\r",
            b"p11.0\r",
            b"x3\r",
            b"y2\r",
            b"p40.0\r",
            b"x3\r",
            b"y3\r",
            b"p5.0\r",
            b"x3\r",
            b"y4\r",
            b"p1.0\r",
        ]

    def test_itc503_temperature_calibration_ignores_short_or_out_of_range_values(self, monkeypatch):
        monkeypatch.setattr(
            oxford_temperature_controllers,
            "_load_itc503_temperature_calibration_config",
            lambda: {"temperature_calibration": {"lookup_table": [[0.0, 0.0], [10.0, 11.0]]}},
        )
        t = _null(responses=[b"R5.5\r"])
        tc = OxfordITC503(transport=t)

        assert tc.get_temperature("A") == pytest.approx(5.0)
        tc.set_setpoint(1, 20.0)

        assert t.write_log == [
            b"R1\r",
            b"T20.0\r",
        ]

    def test_itc503_temperature_values_are_limited_to_millikelvin_resolution(self, monkeypatch):
        monkeypatch.setattr(
            oxford_temperature_controllers,
            "_load_itc503_temperature_calibration_config",
            lambda: {
                "temperature_calibration": {
                    "lookup_table": [
                        [0.0, 0.0],
                        [10.0, 10.001],
                        [20.0, 20.002],
                        [30.0, 30.003],
                    ]
                }
            },
        )
        t = _null(responses=[b"R10.0015\r"])
        tc = OxfordITC503(transport=t)

        assert tc.get_temperature("A") == pytest.approx(10.0)
        tc.set_setpoint(1, 12.34567)

        assert t.write_log == [
            b"R1\r",
            b"T12.347\r",
        ]

    def test_itc503_get_heater_range_reads_x_status_h_token(self):
        t = _null(responses=[b"X00A1C0H1P0\r", b"X00A1C0H0P0\r"])
        tc = OxfordITC503(transport=t)
        assert tc.get_heater_range(1) == 1
        assert tc.get_heater_range(1) == 0
        assert t.write_log == [b"X\r", b"X\r"]

    def test_itc503_get_gas_flow_uses_r7_register(self):
        t = _null(responses=[b"R55.0\r"])
        tc = OxfordITC503(transport=t)
        assert tc.get_gas_flow() == pytest.approx(55.0)
        assert t.write_log == [b"R7\r"]

    def test_itc503_get_num_zones(self):
        tc = OxfordITC503(transport=_null())
        assert tc.get_num_zones(1) == 16

    def test_itc503_get_num_zones_invalid_loop(self):
        tc = OxfordITC503(transport=_null())
        with pytest.raises(ValueError):
            tc.get_num_zones(2)

    def test_itc503_get_zone_uses_pointer_and_q_commands(self):
        t = _null(responses=[b"Q10.0\r", b"Q20.0\r", b"Q30.0\r", b"Q40.0\r"])
        tc = OxfordITC503(transport=t)
        zone = tc.get_zone(1, 1)
        assert zone == ZoneEntry(
            upper_bound=10.0,
            p=20.0,
            i=30.0,
            d=40.0,
            ramp_rate=0.0,
            heater_range=0,
            heater_output=0.0,
        )
        assert t.write_log == [
            b"x1\r",
            b"y1\r",
            b"q\r",
            b"x1\r",
            b"y2\r",
            b"q\r",
            b"x1\r",
            b"y3\r",
            b"q\r",
            b"x1\r",
            b"y4\r",
            b"q\r",
        ]

    def test_itc503_set_zone_uses_pointer_and_p_commands(self):
        t = _null()
        tc = OxfordITC503(transport=t)
        zone = ZoneEntry(
            upper_bound=12.5,
            p=30.0,
            i=4.0,
            d=0.5,
            ramp_rate=9.0,
            heater_range=1,
            heater_output=25.0,
        )
        tc.set_zone(1, 2, zone)
        assert t.write_log == [
            b"x2\r",
            b"y1\r",
            b"p12.5\r",
            b"x2\r",
            b"y2\r",
            b"p30.0\r",
            b"x2\r",
            b"y3\r",
            b"p4.0\r",
            b"x2\r",
            b"y4\r",
            b"p0.5\r",
        ]

    def test_itc503_zone_row_validation(self):
        tc = OxfordITC503(transport=_null())
        with pytest.raises(ValueError, match="PID-table row"):
            tc.get_zone(1, 0)
        with pytest.raises(ValueError, match="PID-table row"):
            tc.set_zone(1, 17, ZoneEntry(100.0, 30.0, 5.0, 1.0, 0.0, 0, 0.0))

    def test_itc503_zone_row_upper_bound_is_valid(self):
        t = _null(responses=[b"Q100.0\r", b"Q30.0\r", b"Q5.0\r", b"Q1.0\r"])
        tc = OxfordITC503(transport=t)
        zone = tc.get_zone(1, 16)
        assert zone.upper_bound == pytest.approx(100.0)
        assert t.write_log[:3] == [b"x16\r", b"y1\r", b"q\r"]

    @pytest.mark.parametrize(
        ("status_response", "expected_mode"),
        [
            (b"X00A0C0H1P0\r", ControlMode.OFF),
            (b"X00A2C0H1P0\r", ControlMode.OPEN_LOOP),
            (b"X00A3C0H1P0\r", ControlMode.MONITOR),
            (b"X00C0H1P0\r", ControlMode.CLOSED_LOOP),
        ],
    )
    def test_itc503_get_loop_mode_maps_status_a_token(self, status_response, expected_mode):
        t = _null(responses=[status_response])
        tc = OxfordITC503(transport=t)
        assert tc.get_loop_mode(1) is expected_mode
        assert t.write_log == [b"X\r"]

    @pytest.mark.parametrize(
        ("status_response", "expected"),
        [
            (b"X00A1C0S0H1P0\r", False),
            (b"X00A1C0S1H1P0\r", True),
            (b"X00A1C0S5H1P0\r", True),
        ],
    )
    def test_itc503_get_ramp_enabled_maps_status_s_token(self, status_response, expected):
        t = _null(responses=[status_response])
        tc = OxfordITC503(transport=t)
        assert tc.get_ramp_enabled(1) is expected
        assert t.write_log == [b"X\r"]

    def test_itc503_identify_handles_non_echo_v_response(self):
        t = _null(responses=[b"ITC503 Version 1.11 (c) OXFORD 1997\r"])
        tc = OxfordITC503(transport=t)
        assert tc.identify() == "ITC503 Version 1.11 (c) OXFORD 1997"

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
        assert caps_itc.has_cryogen_control is True
        assert caps_itc.has_gas_auto_mode is True
        assert caps_itc.has_zone is True
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
        t = _NullTransportWithEsb(responses=[b'+0,"No error"\n'])
        t.open()
        instr = BaseInstrument(t, ScpiProtocol())
        instr.check_for_errors()  # must not raise
        assert t.write_log == [b"SYST:ERR?\n"]

    def test_check_for_errors_raises_on_error(self):
        t = _NullTransportWithEsb(responses=[b'-113,"Undefined header"\n'])
        t.open()
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
    def test_auto_check_errors_default_true(self):
        assert BaseInstrument(NullTransport(), ScpiProtocol()).auto_check_errors is True

    def test_auto_check_errors_query_raises_on_scpi_error(self):
        # The NullTransport serves: first the query response, then the SYST:ERR? response
        t = _NullTransportWithEsb(responses=[b"ACME\n", b'-113,"Undefined header"\n'])
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError, match="Undefined header"):
            instr.query("*IDN?")

    def test_auto_check_errors_query_no_raise_when_queue_clear(self):
        t = _NullTransportWithEsb(responses=[b"ACME\n", b'+0,"No error"\n'])
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=True)
        result = instr.query("*IDN?")
        assert result == "ACME"

    def test_auto_check_errors_write_raises_on_scpi_error(self):
        t = _NullTransportWithEsb(responses=[b'-113,"Undefined header"\n'])
        t.open()
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


class TestIdentityAndQueueClearing:
    def test_confirm_identity_passes_for_expected_tokens(self):
        class _IdentityInstr(BaseInstrument):
            _EXPECTED_IDENTITY_TOKENS = ("MODEL1",)

        t = _null(responses=[b"VENDOR,MODEL1,SN,FW\n"])
        instr = _IdentityInstr(t, ScpiProtocol(), auto_check_errors=False)
        assert instr.confirm_identity() == "VENDOR,MODEL1,SN,FW"

    def test_confirm_identity_raises_for_mismatched_tokens(self):
        class _IdentityInstr(BaseInstrument):
            _EXPECTED_IDENTITY_TOKENS = ("MODEL1",)

        t = _null(responses=[b"VENDOR,OTHER,SN,FW\n"])
        instr = _IdentityInstr(t, ScpiProtocol(), auto_check_errors=False)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            instr.confirm_identity()

    def test_confirm_identity_uses_model_fallback(self):
        class _ModelInstr(BaseInstrument):
            _MODEL = "MODEL2"

        t = _null(responses=[b"VENDOR,MODEL2,SN,FW\n"])
        instr = _ModelInstr(t, ScpiProtocol(), auto_check_errors=False)
        assert instr.confirm_identity() == "VENDOR,MODEL2,SN,FW"

    def test_check_for_errors_clears_remaining_queue_entries(self, caplog):
        t = _NullTransportWithEsb(
            responses=[
                b'-113,"First error"\n',
                b'-114,"Second error"\n',
                b'+0,"No error"\n',
            ]
        )
        t.open()
        instr = BaseInstrument(t, ScpiProtocol())
        with caplog.at_level(logging.ERROR, logger="stoner_measurement.sequence.comms"):
            with pytest.raises(InstrumentError, match="First error"):
                instr.check_for_errors(command="BAD CMD")
        assert t.write_log == [b"SYST:ERR?\n", b"SYST:ERR?\n", b"SYST:ERR?\n"]
        assert any("Cleared queued instrument error" in record.getMessage() for record in caplog.records)

    def test_temperature_controller_connect_closes_on_identity_failure(self):
        t = NullTransport(responses=[b"VENDOR,WRONGMODEL,SN,1.0\r\n"])
        controller = Lakeshore335(t)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            controller.connect()
        assert not controller.is_connected

    def test_magnet_controller_connect_closes_on_identity_failure(self):
        t = NullTransport(responses=[b"VWRONGMODEL 3.07\r"])
        controller = OxfordIPS120(t)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            controller.connect()
        assert not controller.is_connected


# ---------------------------------------------------------------------------
# Instrument locking and connect-time buffer flush.
# ---------------------------------------------------------------------------


class TestInstrumentLocking:
    """Tests for the RLock serialization of write/query/check_for_errors."""

    class _KeyedTransport(NullTransport):
        """Test helper transport exposing a configurable transport address."""

        def __init__(self, address: str):
            super().__init__()
            self._address = address

        @property
        def transport_address(self) -> str:
            return self._address

    def test_instrument_has_rlock(self):
        """BaseInstrument carries an RLock accessible as _lock."""
        import threading

        instr = BaseInstrument(NullTransport(), ScpiProtocol())
        assert isinstance(instr._lock, type(threading.RLock()))

    def test_same_resource_key_shares_lock_object(self):
        """Two instruments with the same keyed transport share one lock."""
        first = BaseInstrument(self._KeyedTransport(" gpib0::22::instr "), ScpiProtocol())
        second = BaseInstrument(self._KeyedTransport("GPIB0::22::INSTR"), ScpiProtocol())

        assert first._lock is second._lock

    def test_canonical_resource_key_normalises_case_and_whitespace(self):
        """canonical_resource_key strips and case-normalises addresses."""

        assert canonical_resource_key(" gpib0::22::instr ") == "gpib0::22::instr"
        assert canonical_resource_key("  ") is None
        assert canonical_resource_key("\t\r\n") is None
        assert canonical_resource_key("\nGpIb0::22::InStR\t") == "gpib0::22::instr"
        assert canonical_resource_key(None) is None

    def test_different_resource_keys_get_different_locks(self):
        """Two instruments with different keyed transports do not share a lock."""
        first = BaseInstrument(self._KeyedTransport("GPIB0::22::INSTR"), ScpiProtocol())
        second = BaseInstrument(self._KeyedTransport("GPIB0::23::INSTR"), ScpiProtocol())

        assert first._lock is not second._lock

    def test_unkeyed_transports_keep_per_instance_lock(self):
        """Empty/unkeyed transport addresses use per-instance locks."""
        first = BaseInstrument(NullTransport(), ScpiProtocol())
        second = BaseInstrument(NullTransport(), ScpiProtocol())

        assert first._lock is not second._lock

    def test_gpib_and_passthrough_transports_share_lock_key(self):
        """6221 host and passthrough transports share one lock key/lock."""
        pytest.importorskip("pyvisa")
        host_transport = GpibTransport(address=22)
        relay_transport = PassThroughGpibTransport(address=22)

        assert host_transport.lock_key == relay_transport.lock_key

        host_instr = BaseInstrument(host_transport, ScpiProtocol())
        relay_instr = BaseInstrument(relay_transport, ScpiProtocol())

        assert host_instr._lock is relay_instr._lock

    def test_connect_flushes_transport(self):
        """connect() calls transport.flush() after opening the transport."""

        class _FlushCountingTransport(NullTransport):
            def __init__(self):
                super().__init__()
                self.flush_count = 0

            def flush(self) -> None:
                self.flush_count += 1

        t = _FlushCountingTransport()
        instr = BaseInstrument(t, ScpiProtocol())
        instr.connect()
        assert t.flush_count == 1

    def test_query_holds_lock_during_write_read(self):
        """The instrument lock is held throughout the write-read cycle of query()."""
        import threading

        lock_was_held = []
        barrier = threading.Barrier(2, timeout=2)

        class _BarrierTransport(NullTransport):
            """Transport that synchronises with the test thread during read()."""

            def read(self, num_bytes: int | None = None) -> bytes:
                barrier.wait()  # rendezvous: test thread now checks the lock
                barrier.wait()  # wait for test thread to finish its check
                return b"response\n"

        t = _BarrierTransport()
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=False)

        def do_query():
            instr.query("CMD")

        thread = threading.Thread(target=do_query, daemon=True)
        thread.start()
        barrier.wait()  # wait until transport.read() is entered (lock held)
        # Try to acquire the lock non-blockingly; it should be held by the query thread.
        acquired = instr._lock.acquire(blocking=False)
        if acquired:
            instr._lock.release()
        lock_was_held.append(not acquired)
        barrier.wait()  # let the query thread proceed
        thread.join(timeout=2)
        assert not thread.is_alive(), "query() worker thread did not finish; possible deadlock"

        assert lock_was_held == [True], "Lock should be held by query thread during read()"

    def test_concurrent_queries_do_not_interleave(self):
        """Two concurrent query() calls are serialised so writes and reads stay paired."""
        import threading

        events: list[str] = []
        events_lock = threading.Lock()

        class _LoggingTransport(NullTransport):
            def write(self, data: bytes, slow: int|None = None) -> None:
                super().write(data)
                with events_lock:
                    events.append(f"W:{data.strip().decode()}")

            def read(self, num_bytes: int | None = None) -> bytes:
                # Yield briefly so the other thread can attempt to interleave.
                import time

                time.sleep(0.005)
                last_write = self.write_log[-1].strip().decode() if self.write_log else "?"
                with events_lock:
                    events.append(f"R:{last_write}")
                return f"{last_write}-resp\n".encode()

        t = _LoggingTransport()
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(), auto_check_errors=False)

        results = []

        def do_query(cmd):
            results.append(instr.query(cmd))

        t1 = threading.Thread(target=do_query, args=("A",), daemon=True)
        t2 = threading.Thread(target=do_query, args=("B",), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        assert not t1.is_alive(), "First query thread did not finish; possible deadlock"
        assert not t2.is_alive(), "Second query thread did not finish; possible deadlock"

        # Each write must be immediately followed by the matching read.
        for i in range(0, len(events) - 1, 2):
            w_cmd = events[i][2:]  # strip "W:"
            r_cmd = events[i + 1][2:]  # strip "R:"
            assert w_cmd == r_cmd, f"Write {w_cmd!r} was not paired with its read; got {r_cmd!r}"


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
            LockInExpandFactor,
            LockInInputCoupling,
            LockInInputShielding,
            LockInInputSource,
            LockInLineFilter,
            LockInOutputChannel,
            LockInReferenceSource,
            LockInReserveMode,
        )

        assert LockInAmplifier is not None
        assert LockInAmplifierCapabilities is not None
        assert LockInExpandFactor is not None
        assert LockInInputCoupling is not None
        assert LockInInputShielding is not None
        assert LockInInputSource is not None
        assert LockInLineFilter is not None
        assert LockInOutputChannel is not None
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
            upper_bound=50.0,
            p=10.0,
            i=1.0,
            d=0.0,
            ramp_rate=5.0,
            heater_range=1,
            heater_output=25.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            entry.heater_output = 50.0  # type: ignore[misc]

    def test_zero_ramp_rate_allowed(self):
        """ramp_rate=0 means immediate setpoint change (no ramping)."""
        entry = ZoneEntry(
            upper_bound=50.0,
            p=10.0,
            i=1.0,
            d=0.0,
            ramp_rate=0.0,
            heater_range=0,
            heater_output=0.0,
        )
        assert entry.ramp_rate == pytest.approx(0.0)
        assert entry.heater_range == 0

    def test_full_heater_power(self):
        """heater_output of 100 % is a valid upper boundary."""
        entry = ZoneEntry(
            upper_bound=400.0,
            p=100.0,
            i=10.0,
            d=1.0,
            ramp_rate=2.0,
            heater_range=5,
            heater_output=100.0,
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
            upper_bound=100.0,
            p=50.0,
            i=2.0,
            d=0.0,
            ramp_rate=5.0,
            heater_range=1,
            heater_output=25.0,
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

        monkeypatch.setattr(
            type(tc), "set_ramp_enabled", lambda self, loop, enabled: calls.append(("ramp_enabled", loop, enabled))
        )
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
                num_inputs=2,
                num_loops=1,
                input_channels=("A", "B"),
                loop_numbers=(1,),
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


# ---------------------------------------------------------------------------
# OxfordMercuryIPS concrete driver
# ---------------------------------------------------------------------------


class TestOxfordMercuryIPS:
    def test_default_protocol_is_scpi(self):
        m = OxfordMercuryIPS(transport=NullTransport())
        assert isinstance(m.protocol, ScpiProtocol)

    def test_default_uid(self):
        m = OxfordMercuryIPS(transport=NullTransport())
        assert m._uid == "PSU.M1"

    def test_custom_uid(self):
        m = OxfordMercuryIPS(transport=NullTransport(), device_uid="PSU.M2")
        assert m._uid == "PSU.M2"

    def test_identity_and_model_and_firmware(self):
        t = _null(
            responses=[
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        assert m.identify() == "Oxford Instruments,Mercury iPS,12345,2.7.0"
        assert m.get_model() == "Mercury iPS"
        assert m.get_firmware_version() == "2.7.0"

    def test_field_current_voltage_properties(self):
        uid = "PSU.M1"
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+2.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.12345V\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        assert m.field == pytest.approx(1.5)
        assert m.current == pytest.approx(2.0)
        assert m.voltage == pytest.approx(0.12345)
        assert t.write_log == [
            f"READ:DEV:{uid}:PSU:SIG:FLD\n".encode(),
            f"READ:DEV:{uid}:PSU:SIG:CURR\n".encode(),
            f"READ:DEV:{uid}:PSU:SIG:VOLT\n".encode(),
        ]

    def test_heater_property_on(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n"])
        m = OxfordMercuryIPS(transport=t)
        assert m.heater is True

    def test_heater_property_off(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n"])
        m = OxfordMercuryIPS(transport=t)
        assert m.heater is False

    def test_heater_on_off_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.heater_on()
        m.heater_off()
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",
            b"SET:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n",
        ]

    def test_set_target_field_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_target_field(1.0)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n"]

    def test_set_target_current_uses_magnet_constant(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.set_target_current(2.0)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n"]

    def test_set_ramp_rate_field_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_ramp_rate_field(0.1)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:RSET:0.100000\n"]

    def test_set_ramp_rate_current_uses_magnet_constant(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.set_ramp_rate_current(0.2)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:RSET:0.100000\n"]

    def test_set_ramp_rate_negative_raises(self):
        m = OxfordMercuryIPS(transport=_null())
        with pytest.raises(ValueError, match="non-negative"):
            m.set_ramp_rate_field(-0.1)
        with pytest.raises(ValueError, match="non-negative"):
            m.set_ramp_rate_current(-0.1)

    def test_ramp_to_target_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.ramp_to_target()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n"]

    def test_pause_ramp_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.pause_ramp()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:HOLD\n"]

    def test_abort_ramp_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.abort_ramp()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:HOLD\n"]

    def test_ramp_to_field_sends_correct_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.ramp_to_field(1.5)
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.500000\n",
            b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n",
        ]

    def test_ramp_to_current_sends_correct_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.ramp_to_current(2.0)
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n",
            b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n",
        ]

    def test_set_magnet_constant_validation(self):
        m = OxfordMercuryIPS(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)
        m.set_magnet_constant(0.5)
        assert m.magnet_constant == pytest.approx(0.5)

    def test_status_ramping(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:RTOS\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+0.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+1.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.05000V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",                
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.RAMPING
        assert status.field == pytest.approx(0.5)
        assert status.current == pytest.approx(1.0)
        assert status.voltage == pytest.approx(0.05)
        assert status.at_target is False
        assert status.heater_on is True
        assert status.heater_state.value == "on"
        assert status.persistent is False

    def test_status_at_target_when_hold_and_field_matches(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+2.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00001V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",                
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.AT_TARGET
        assert status.at_target is True

    def test_status_standby_when_hold_but_field_differs(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+0.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+1.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00001V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.STANDBY
        assert status.at_target is False

    def test_status_persistent_when_heater_off(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+0.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00000V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.persistent is True
        assert status.heater_on is False
        assert status.heater_state.value == "off"

    def test_read_sig_float_raises_on_invalid_response(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:FLD:NOT_A_NUMBER\n"])
        m = OxfordMercuryIPS(transport=t)
        with pytest.raises(ValueError, match="FLD"):
            _ = m.field

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = OxfordMercuryIPS(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=True,
                heater_state=HeaterState.ON,
                at_target=False,
                persistent_field=None,
            )

        monkeypatch.setattr(OxfordMercuryIPS, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)

    def test_custom_uid_in_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t, device_uid="PSU.M2")
        m.set_target_field(1.0)
        m.ramp_to_target()
        m.pause_ramp()
        m.heater_on()
        assert t.write_log == [
            b"SET:DEV:PSU.M2:PSU:SIG:FSET:1.000000\n",
            b"SET:DEV:PSU.M2:PSU:ACTN:RTOS\n",
            b"SET:DEV:PSU.M2:PSU:ACTN:HOLD\n",
            b"SET:DEV:PSU.M2:PSU:SIG:SWHT:ON\n",
        ]


if __name__ == "__main__":

    raise SystemExit(pytest.main([__file__, "--pdb"]))
