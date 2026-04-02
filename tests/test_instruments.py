"""Tests for the instrument communication class hierarchy.

Covers:
- Correct ABC enforcement (direct instantiation raises TypeError).
- BaseInstrument composition: write, query, read, identify, reset.
- NullTransport record-keeping and context manager support.
- Protocol formatting and response parsing for SCPI, Oxford, and Lakeshore.
- Keithley2400 concrete driver methods.
"""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.keithley import Keithley2400
from stoner_measurement.instruments.magnet_controller import MagnetController
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
        with pytest.raises(RuntimeError, match="Instrument error"):
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
        with pytest.raises(RuntimeError, match="Oxford Instruments"):
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
        with pytest.raises(RuntimeError, match="Lakeshore"):
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
