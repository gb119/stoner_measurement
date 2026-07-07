"""Focused tests for Eurotherm temperature controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.eurotherm import Eurotherm2000Series, Eurotherm3200Series
from stoner_measurement.instruments.eurotherm.temperature_controllers import (
    _append_crc,
)
from stoner_measurement.instruments.protocol import ModbusRtuProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControlMode,
    PIDParameters,
    SensorStatus,
)
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


def _read_response(unit_id: int, address: int, value: int) -> bytes:
    """Return a Modbus RTU read-holding-register response frame."""
    payload = bytes(
        (
            unit_id,
            0x03,
            0x02,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )
    return _append_crc(payload)


def _write_echo(unit_id: int, address: int, value: int) -> bytes:
    """Return a Modbus RTU write-single-register echo frame."""
    payload = bytes(
        (
            unit_id,
            0x06,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )
    return _append_crc(payload)


class TestEurothermTemperatureController:
    def test_default_protocol(self):
        tc = Eurotherm3200Series(transport=NullTransport())
        assert isinstance(tc.protocol, ModbusRtuProtocol)

    def test_identify_uses_register_122_when_available(self):
        transport = _null(responses=[_read_response(1, 122, 0x3208)])
        tc = Eurotherm3200Series(transport=transport)

        assert tc.identify() == "Eurotherm 3208 (3200 Series) Modbus RTU (unit 1)"

    def test_identify_falls_back_when_register_122_is_unavailable(self):
        transport = _null()
        tc = Eurotherm3200Series(transport=transport)

        assert tc.identify() == "Eurotherm 3200 Series Modbus RTU (unit 1)"

    def test_read_raw_builds_modbus_frame_and_parses_signed_register(self):
        transport = _null(responses=[_read_response(7, 75, 1234)])
        tc = Eurotherm3200Series(transport=transport, unit_id=7)

        assert tc.read_raw(75) == 1234
        assert transport.write_log == [_append_crc(bytes((7, 0x03, 0x00, 0x4B, 0x00, 0x01)))]

    def test_write_raw_builds_write_single_register_frame(self):
        transport = _null(responses=[_write_echo(3, 273, 1)])
        tc = Eurotherm3200Series(transport=transport, unit_id=3)

        tc.write_raw(273, 1)

        assert transport.write_log == [_append_crc(bytes((3, 0x06, 0x01, 0x11, 0x00, 0x01)))]

    def test_get_temperature_converts_celsius_process_value_to_kelvin(self):
        transport = _null(responses=[_read_response(1, 1, 250)])
        tc = Eurotherm3200Series(transport=transport, temperature_unit="C")

        assert tc.get_temperature("PV") == pytest.approx(298.15)

    def test_get_sensor_status_uses_status_bitmap(self):
        overrange_status = 1 << 10
        transport = _null(
            responses=[
                _read_response(1, 75, overrange_status),
            ]
        )
        tc = Eurotherm3200Series(transport=transport)

        assert tc.get_sensor_status("PV") is SensorStatus.OVERRANGE

    def test_get_setpoint_reads_working_setpoint(self):
        transport = _null(responses=[_read_response(1, 5, 300)])
        tc = Eurotherm3200Series(transport=transport, temperature_unit="C")

        assert tc.get_setpoint(1) == pytest.approx(303.15)

    def test_set_setpoint_uses_remote_register_path_by_default(self):
        transport = _null(
            responses=[
                _read_response(1, 276, 0),
                _write_echo(1, 276, 1),
                _write_echo(1, 26, 369),
            ]
        )
        tc = Eurotherm3200Series(transport=transport, temperature_unit="C")

        tc.set_setpoint(1, 310.05)

        assert transport.write_log == [
            _append_crc(bytes((1, 0x03, 0x01, 0x14, 0x00, 0x01))),
            _append_crc(bytes((1, 0x06, 0x01, 0x14, 0x00, 0x01))),
            _append_crc(bytes((1, 0x06, 0x00, 0x1A, 0x01, 0x71))),
        ]

    def test_set_setpoint_skips_rewriting_remote_select_when_already_selected(self):
        transport = _null(
            responses=[
                _read_response(1, 276, 1),
                _write_echo(1, 26, 315),
            ]
        )
        tc = Eurotherm3200Series(transport=transport, temperature_unit="C")

        tc.set_setpoint(1, 304.65)

        assert transport.write_log == [
            _append_crc(bytes((1, 0x03, 0x01, 0x14, 0x00, 0x01))),
            _append_crc(bytes((1, 0x06, 0x00, 0x1A, 0x01, 0x3B))),
        ]

    def test_get_loop_mode_maps_im_and_auto_manual_registers(self):
        transport = _null(
            responses=[
                _read_response(1, 199, 0),
                _read_response(1, 273, 1),
                _read_response(1, 199, 1),
            ]
        )
        tc = Eurotherm3200Series(transport=transport)

        assert tc.get_loop_mode(1) is ControlMode.OPEN_LOOP
        assert tc.get_loop_mode(1) is ControlMode.OFF

    def test_set_loop_mode_open_loop_writes_standby_off_then_manual_mode(self):
        transport = _null(
            responses=[
                _write_echo(1, 199, 0),
                _write_echo(1, 273, 1),
            ]
        )
        tc = Eurotherm3200Series(transport=transport)

        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)

        assert transport.write_log == [
            _append_crc(bytes((1, 0x06, 0x00, 0xC7, 0x00, 0x00))),
            _append_crc(bytes((1, 0x06, 0x01, 0x11, 0x00, 0x01))),
        ]

    def test_get_pid_reads_three_scaled_registers(self):
        transport = _null(
            responses=[
                _read_response(1, 6, 125),
                _read_response(1, 8, 30),
                _read_response(1, 9, 5),
            ]
        )
        tc = Eurotherm3200Series(transport=transport)

        assert tc.get_pid(1) == PIDParameters(p=12.5, i=3.0, d=0.5)

    def test_set_manual_heater_output_validates_percentage_and_writes_scaled_value(self):
        transport = _null(responses=[_write_echo(1, 3, 455)])
        tc = Eurotherm3200Series(transport=transport)

        tc.set_manual_heater_output(1, 45.5)

        assert transport.write_log == [_append_crc(bytes((1, 0x06, 0x00, 0x03, 0x01, 0xC7)))]

    def test_get_controller_status_sets_error_state_from_status_bits(self):
        sensor_break = 1 << 5
        transport = _null(
            responses=[
                _read_response(1, 1, 250),
                _read_response(1, 75, sensor_break),
                _read_response(1, 6, 100),
                _read_response(1, 8, 20),
                _read_response(1, 9, 0),
                _read_response(1, 35, 0),
                _read_response(1, 5, 300),
                _read_response(1, 1, 250),
                _read_response(1, 199, 0),
                _read_response(1, 273, 0),
                _read_response(1, 4, 125),
                _read_response(1, 35, 0),
                _read_response(1, 35, 0),
                _read_response(1, 75, sensor_break),
                _read_response(1, 263, 0),
            ]
        )
        tc = Eurotherm3200Series(transport=transport, temperature_unit="C")

        status = tc.get_controller_status()

        assert status.error_state == "sensor break"
        assert status.loops[1].mode is ControlMode.CLOSED_LOOP

    def test_start_autotune_and_status(self):
        transport = _null(
            responses=[
                _write_echo(1, 270, 1),
                _read_response(1, 75, 1 << 15),
            ]
        )
        tc = Eurotherm3200Series(transport=transport)

        tc.start_autotune(1)

        assert tc.get_autotune_status(1) == "running"


class TestEurotherm2000Series:
    def test_identify_reads_version_and_identifier(self):
        transport = _null(
            responses=[
                _read_response(1, 107, 0x1234),
                _read_response(1, 122, 0x2480),
            ]
        )
        tc = Eurotherm2000Series(transport=transport)

        identity = tc.identify()

        assert "2408" in identity
        assert "2400" in identity
        assert "0x1234" in identity
        assert "0x2480" in identity

    def test_set_setpoint_uses_remote_register_26_for_2200(self):
        transport = _null(
            responses=[
                _read_response(1, 276, 0),
                _write_echo(1, 276, 1),
                _write_echo(1, 26, 369),
            ]
        )
        tc = Eurotherm2000Series(transport=transport, model_series="2200", temperature_unit="C")

        tc.set_setpoint(1, 310.05)

        assert transport.write_log[-1] == _append_crc(bytes((1, 0x06, 0x00, 0x1A, 0x01, 0x71)))

    def test_set_setpoint_uses_remote_register_485_for_2400(self):
        transport = _null(
            responses=[
                _read_response(1, 276, 0),
                _write_echo(1, 276, 1),
                _write_echo(1, 485, 369),
            ]
        )
        tc = Eurotherm2000Series(transport=transport, model_series="2400", temperature_unit="C")

        tc.set_setpoint(1, 310.05)

        assert transport.write_log[-1] == _append_crc(bytes((1, 0x06, 0x01, 0xE5, 0x01, 0x71)))

    def test_set_setpoint_infers_2400_remote_register_from_identifier(self):
        transport = _null(
            responses=[
                _read_response(1, 122, 0x2480),
                _read_response(1, 276, 0),
                _write_echo(1, 276, 1),
                _write_echo(1, 485, 369),
            ]
        )
        tc = Eurotherm2000Series(transport=transport, temperature_unit="C")

        tc.set_setpoint(1, 310.05)

        assert transport.write_log[-1] == _append_crc(bytes((1, 0x06, 0x01, 0xE5, 0x01, 0x71)))

    @pytest.mark.parametrize(
        ("identifier", "expected_model", "expected_series"),
        [
            (0x2260, "2216", "2200"),
            (0x2280, "2208", "2200"),
            (0x2240, "2204", "2200"),
            (0x2460, "2416", "2400"),
            (0x2480, "2408", "2400"),
            (0x2440, "2404", "2400"),
            (0x2462, "2416", "2400"),
            (0x2482, "2408", "2400"),
            (0x2442, "2404", "2400"),
        ],
    )
    def test_identify_controller_decodes_known_register_122_values(
        self, identifier, expected_model, expected_series
    ):
        transport = _null(
            responses=[
                _read_response(1, 107, 0x0102),
                _read_response(1, 122, identifier),
            ]
        )
        tc = Eurotherm2000Series(transport=transport)

        info = tc.identify_controller()

        assert info["model"] == expected_model
        assert info["model_series"] == expected_series

    def test_get_status_uses_instrument_status_word_for_ramp_running(self):
        transport = _null(
            responses=[
                _read_response(1, 75, 0),
                _read_response(1, 77, 1 << 2),
            ]
        )
        tc = Eurotherm2000Series(transport=transport, model_series="2400")

        status = tc.get_status()

        assert status["ramp_running"] is True

    def test_get_autotune_status_reports_complete_from_control_status(self):
        transport = _null(
            responses=[
                _read_response(1, 75, 0),
                _read_response(1, 77, 0),
                _read_response(1, 76, 1 << 8),
            ]
        )
        tc = Eurotherm2000Series(transport=transport, model_series="2400")

        assert tc.get_autotune_status(1) == "complete"

    def test_enter_configuration_requires_explicit_permission(self):
        tc = Eurotherm2000Series(transport=NullTransport())

        with pytest.raises(PermissionError):
            tc.enter_configuration()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
