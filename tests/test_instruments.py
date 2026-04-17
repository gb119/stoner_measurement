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
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.keithley import Keithley2400
from stoner_measurement.instruments.lakeshore import Lakeshore525
from stoner_measurement.instruments.magnet_controller import (
    MagnetController,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.nanovoltmeter import Nanovoltmeter
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.source_meter import SourceMeter
from stoner_measurement.instruments.temperature_controller import TemperatureController
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

    def test_nanovoltmeter_is_abstract(self):
        with pytest.raises(TypeError):
            Nanovoltmeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]


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
        assert k.get_source_mode() == "VOLT"

    def test_set_source_mode_volt(self):
        t = _null()
        Keithley2400(transport=t).set_source_mode("VOLT")
        assert t.write_log[-1] == b":SOUR:FUNC:MODE VOLT\n"

    def test_set_source_mode_curr(self):
        t = _null()
        Keithley2400(transport=t).set_source_mode("CURR")
        assert t.write_log[-1] == b":SOUR:FUNC:MODE CURR\n"

    def test_set_source_mode_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid source mode"):
            Keithley2400(transport=_null()).set_source_mode("OHMS")

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

    def test_current_field_voltage_queries(self):
        t = _null(responses=[b"2.5\r\n", b"0.75\r\n", b"1.2\r\n"])
        m = Lakeshore525(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

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
        assert t.write_log == [b"HEATER 1\r\n", b"HEATER 0\r\n", b"HEATER?\r\n"]

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

    def test_wait_for_ramp_complete_times_out_when_state_stays_ramping(self, monkeypatch):
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
