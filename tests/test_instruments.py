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
from stoner_measurement.instruments.lakeshore import (
    Lakeshore335,
)
from stoner_measurement.instruments.lock_registry import canonical_resource_key
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
from stoner_measurement.instruments.oxford import (
    OxfordIPS120,
    OxfordMercuryIPS,
)
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    SourceMeter,
)
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
