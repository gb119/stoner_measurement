"""Focused tests for the SIGNAL RECOVERY 7265 lock-in driver."""

from __future__ import annotations

from collections import deque

import pytest

from stoner_measurement.instruments.lockin_amplifier import (
    LockInInputSource,
    LockInOutput,
    LockinRefenceEdge,
    LockInReferenceSource,
)
from stoner_measurement.instruments.protocol import SignalRecoveryProtocol
from stoner_measurement.instruments.signal_recovery import (
    SR7265,
    SR7265Error,
    SR7265ReferenceInput,
    SR7265Status,
)
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.instruments.transport.base import BaseTransport
from stoner_measurement.instruments.transport.serial_transport import EchoSerialTransport


def _null(responses: list[bytes] | None = None) -> NullTransport:
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class _StatusTransport(BaseTransport):
    """Minimal transport with programmable serial-poll values."""

    def __init__(self, statuses: list[int], responses: list[bytes] | None = None) -> None:
        super().__init__(timeout=0.1)
        self.statuses = deque(statuses)
        self.responses = deque(responses or [])
        self.write_log: list[bytes] = []
        self.open()

    def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def write(self, data: bytes, slow: int | None = None) -> int:
        del slow
        self.write_log.append(data)
        return 0

    def read(self, num_bytes: int | None = None) -> bytes:
        del num_bytes
        return self.responses.popleft() if self.responses else b""

    def read_status_byte(self) -> int | None:
        return self.statuses.popleft() if self.statuses else None


class _FakeEchoTransport(EchoSerialTransport):
    """Echo transport double that exposes complete post-echo response frames."""

    def __init__(self, responses: list[bytes]) -> None:
        BaseTransport.__init__(self, timeout=0.1)
        self.port = "COM1"
        self.responses = deque(responses)
        self.write_log: list[bytes] = []
        self.response_suffixes = (b"*", b"?")
        self._is_open = True

    def write(self, data: bytes, slow: int | None = None) -> int:
        del slow
        self.write_log.append(data)
        return 0

    def read(self, num_bytes: int | None = None) -> bytes:
        del num_bytes
        return self.responses.popleft()


class TestSignalRecoveryProtocol:
    def test_native_query_framing_and_prompt_parsing(self):
        protocol = SignalRecoveryProtocol()
        assert protocol.format_query("FRQ.") == b"FRQ.\r\n"
        assert protocol.parse_response(b"123.0\r\n*") == "123.0"


class TestSR7265:
    def test_default_protocol_and_identity_reset(self):
        transport = _null([b"7265\r\n"])
        lockin = SR7265(transport)

        assert isinstance(lockin.protocol, SignalRecoveryProtocol)
        assert lockin.identify() == "7265"
        lockin.reset()

        assert transport.write_log == [b"ID\r\n", b"ADF 1\r\n"]

    def test_serial_write_consumes_the_post_command_prompt(self):
        transport = _FakeEchoTransport([b"\r\n*"])
        lockin = SR7265(transport)

        lockin.set_reference_phase(12.0)

        assert transport.write_log == [b"REFP. 12.0\r\n"]
        assert not transport.responses

    def test_serial_error_prompt_collects_status_diagnostics(self):
        transport = _FakeEchoTransport([b"\r\n?", b"6\r\n*", b"0\r\n*"])
        lockin = SR7265(transport)

        with pytest.raises(SR7265Error, match="error prompt") as caught:
            lockin.set_reference_phase(12.0)

        assert caught.value.status == SR7265Status.INVALID_COMMAND | SR7265Status.PARAMETER_ERROR
        assert transport.write_log == [b"REFP. 12.0\r\n", b"ST\r\n", b"N\r\n"]

    def test_measurement_uses_native_compound_commands_and_delimiter(self):
        transport = _null([b"1.5;-2.0\r\n", b"3.0;45.0\r\n"])
        lockin = SR7265(transport, response_delimiter=";")

        assert lockin.measure_xy() == pytest.approx((1.5, -2.0))
        assert lockin.measure_rt() == pytest.approx((3.0, 45.0))
        assert transport.write_log == [b"X.;Y.\r\n", b"MAG.;PHA.\r\n"]

    def test_getters_use_7265_query_syntax_and_lookup_tables(self):
        transport = _null(
            [b"1e-6\r\n", b"0.1\r\n", b"2\r\n", b"137.0\r\n", b"-12.5\r\n", b"3\r\n", b"2\r\n"]
        )
        lockin = SR7265(transport)

        assert lockin.get_sensitivity() == pytest.approx(1e-6)
        assert lockin.get_time_constant() == pytest.approx(0.1)
        assert lockin.get_reference_input() is SR7265ReferenceInput.EXTERNAL_ANALOG
        assert lockin.get_reference_frequency() == pytest.approx(137.0)
        assert lockin.get_reference_phase() == pytest.approx(-12.5)
        assert lockin.get_harmonic() == 3
        assert lockin.get_filter_slope() == 18
        assert transport.write_log == [
            b"SEN.\r\n",
            b"TC.\r\n",
            b"IE\r\n",
            b"FRQ.\r\n",
            b"REFP.\r\n",
            b"REFN\r\n",
            b"SLOPE\r\n",
        ]

    def test_setters_and_auto_actions_map_from_sr830_surface(self):
        # set_sensitivity first queries IMODE then VMODE to choose its native table.
        transport = _null([b"0\r\n", b"1\r\n"])
        lockin = SR7265(transport)

        lockin.set_sensitivity(100e-9)
        lockin.set_time_constant(0.1)
        lockin.set_reference_source(LockInReferenceSource.EXTERNAL, LockinRefenceEdge.ZERO)
        lockin.set_reference_frequency(17.0)
        lockin.set_reference_phase(33.5)
        lockin.set_harmonic(2)
        lockin.set_filter_slope(12)
        lockin.auto_gain()
        lockin.auto_phase()
        lockin.auto_reserve()

        assert transport.write_log == [
            b"IMODE\r\n",
            b"VMODE\r\n",
            b"SEN 6\r\n",
            b"TC 11\r\n",
            b"IE 2\r\n",
            b"OF. 17.0\r\n",
            b"REFP. 33.5\r\n",
            b"REFN 2\r\n",
            b"SLOPE 1\r\n",
            b"AS\r\n",
            b"AQN\r\n",
            b"AUTOMATIC 1\r\n",
        ]

    def test_current_sensitivity_code_tables(self):
        wide = _null([b"1\r\n"])
        low_noise = _null([b"2\r\n"])

        SR7265(wide).set_sensitivity(1e-9)
        SR7265(low_noise).set_sensitivity(10e-9)

        assert wide.write_log == [b"IMODE\r\n", b"SEN 18\r\n"]
        assert low_noise.write_log == [b"IMODE\r\n", b"SEN 27\r\n"]

    def test_status_poll_waits_for_complete_and_records_conditions(self):
        transport = _StatusTransport(
            statuses=[0, int(SR7265Status.COMMAND_COMPLETE | SR7265Status.DATA_AVAILABLE)],
            responses=[b"1.0,2.0\r\n"],
        )
        lockin = SR7265(transport)

        assert lockin.measure_outputs((LockInOutput.X, LockInOutput.Y)) == {
            LockInOutput.X: pytest.approx(1.0),
            LockInOutput.Y: pytest.approx(2.0),
        }
        assert lockin.last_status == SR7265Status.COMMAND_COMPLETE | SR7265Status.DATA_AVAILABLE

    def test_measurement_status_raises_with_overload_byte(self):
        measurement_status = (
            SR7265Status.COMMAND_COMPLETE | SR7265Status.DATA_AVAILABLE | SR7265Status.OVERLOAD
        )
        transport = _StatusTransport(
            statuses=[
                int(measurement_status),
                int(SR7265Status.COMMAND_COMPLETE | SR7265Status.DATA_AVAILABLE),
            ],
            responses=[b"1.0,2.0\r\n", b"4\r\n"],
        )
        lockin = SR7265(transport)

        with pytest.raises(SR7265Error, match="overload=0x04") as caught:
            lockin.measure_xy()

        assert caught.value.status == measurement_status
        assert caught.value.overload == 4

    @pytest.mark.parametrize(
        "status, message",
        [
            (SR7265Status.COMMAND_COMPLETE | SR7265Status.INVALID_COMMAND, "invalid command"),
            (SR7265Status.COMMAND_COMPLETE | SR7265Status.PARAMETER_ERROR, "parameter error"),
        ],
    )
    def test_command_status_errors_are_structured(self, status: SR7265Status, message: str):
        lockin = SR7265(_StatusTransport([int(status)]))

        with pytest.raises(SR7265Error, match=message) as caught:
            lockin.write("BAD")

        assert caught.value.status == status
        assert caught.value.command == "BAD"

    def test_curve_and_auxiliary_commands(self):
        transport = _null([b"0,1,2,17\r\n", b"1.0,2.0,3.0\r\n", b"0.125\r\n"])
        lockin = SR7265(transport)

        assert lockin.buffer_points() == 17
        assert lockin.read_curve(2) == pytest.approx((1.0, 2.0, 3.0))
        assert lockin.read_adc(1) == pytest.approx(0.125)
        lockin.start_curve(triggered=True)
        lockin.set_dac(3, 1.2344)

        assert transport.write_log == [
            b"M\r\n",
            b"DC. 2\r\n",
            b"ADC. 1\r\n",
            b"TDT 0\r\n",
            b"DAC. 3 1.234\r\n",
        ]

    def test_curve_storage_interval_special_case_and_rounding(self):
        transport = _null([b"0\r\n", b"15\r\n"])
        lockin = SR7265(transport)

        assert lockin.get_curve_storage_interval() == pytest.approx(0.00125)
        assert lockin.get_curve_storage_interval() == pytest.approx(0.015)
        lockin.set_curve_storage_interval(0.00125)
        lockin.set_curve_storage_interval(0.011)

        assert transport.write_log == [b"STR\r\n", b"STR\r\n", b"STR 0\r\n", b"STR 15\r\n"]

    def test_capabilities_and_validation(self):
        lockin = SR7265(_null())
        capabilities = lockin.get_capabilities()

        assert capabilities.max_harmonic == 65535
        assert capabilities.has_input_source_selection
        assert capabilities.has_sync_filter
        with pytest.raises(ValueError):
            lockin.set_harmonic(65536)
        with pytest.raises(ValueError):
            lockin.set_reference_frequency(0.0)
        with pytest.raises(ValueError):
            lockin.start_curve(continuous=True, triggered=True)

    def test_supported_ranges_are_complete(self):
        assert SR7265.supported_time_constants()[0] == pytest.approx(10e-6)
        assert SR7265.supported_time_constants()[-1] == pytest.approx(100e3)
        assert len(SR7265.supported_time_constants()) == 30
        assert SR7265.supported_sensitivities()[0] == pytest.approx(2e-9)
        assert SR7265.supported_sensitivities()[-1] == pytest.approx(1.0)

    def test_inverted_b_mode_uses_voltage_sensitivity_table(self):
        transport = _null([b"0\n", b"2\n", b"0\n", b"2\n"])
        lockin = SR7265(transport)
        lockin.set_input_source(LockInInputSource.B)
        assert lockin.get_input_source() is LockInInputSource.B
        lockin.set_sensitivity(1e-3)
        assert b"IMODE 0;VMODE 2\r\n" in transport.write_log
        assert b"SEN 18\r\n" in transport.write_log
