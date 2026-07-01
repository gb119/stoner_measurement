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
)
from stoner_measurement.instruments.dmm import (
    DigitalMultimeter,
)
from stoner_measurement.instruments.electrometer import (
    Electrometer,
)
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.keithley import (
    Keithley2400,
)
from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
)
from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetController,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
)
from stoner_measurement.instruments.oxford import OxfordMercuryIPS
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    SourceMeter,
)
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
