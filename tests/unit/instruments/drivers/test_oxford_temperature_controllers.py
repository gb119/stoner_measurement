"""Focused tests for Oxford temperature controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.oxford import (
    OxfordITC503,
    OxfordMercuryTemperatureController,
)
from stoner_measurement.instruments.oxford import (
    temperature_controllers as oxford_temperature_controllers,
)
from stoner_measurement.instruments.protocol import OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControlMode,
    PIDParameters,
    ZoneEntry,
)
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    class AcknowledgingTransport(NullTransport):
        def write(self, data, slow=None):
            result = super().write(data, slow=slow)
            # ITC503 actions acknowledge with just their command letter.
            if data[:1] in (b"T", b"A", b"H", b"P", b"I", b"D", b"S", b"C",
                             b"G", b"O", b"M", b"L", b"x", b"y", b"p") and b":" not in data:
                self._responses.appendleft(data[:1] + b"\r")
            return result

    transport = AcknowledgingTransport(responses=responses or [])
    transport.open()
    return transport


class TestOxfordTemperatureControllers:
    @pytest.mark.parametrize(
        ("direction", "raw", "corrected"),
        [("nominal_to_corrected", 15, 25), ("corrected_to_nominal", 25, 15)],
    )
    def test_itc503_sensor_scales_follow_hardware_control_input(self, direction, raw, corrected):
        status = b"X0A1C3S00H2L0\r"
        transport = _null(responses=[
            b"R15\r", f"R{raw}\r".encode(), b"R15\r",
            status, f"R{raw}\r".encode(), status,
            f"Q{raw}\r".encode(), status, b"Q30\r", b"Q4\r", b"Q0.5\r", status,
        ])
        driver = OxfordITC503(transport)
        driver.configure_temperature_scales({
            "A": None,
            "B": {"scale_name": "Cernox", "direction": direction,
                  "pre_scaled_values": [10, 20, 30, 40], "scaled_values": [10, 40, 90, 160]},
        })
        assert driver.get_temperature("A") == 15
        assert driver.get_temperature("B") == corrected
        assert driver.get_temperature("C") == 15  # Existing YAML fallback.
        assert driver.get_setpoint(1) == corrected
        driver.set_setpoint(1, corrected)
        zone = driver.get_zone(1, 1)
        assert zone.upper_bound == corrected
        driver.set_zone(1, 1, zone)
        assert f"T{float(raw)}\r".encode() in transport.write_log
        assert f"p{float(raw)}\r".encode() in transport.write_log
        # The scale is entirely software-defined; reading sensors uses only R registers.
        assert transport.write_log[:3] == [b"R1\r", b"R2\r", b"R3\r"]

    def test_itc503_invalid_scale_keeps_existing_selection(self):
        driver = OxfordITC503(_null())
        driver.configure_temperature_scales({"A": None})
        with pytest.raises(ValueError):
            driver.configure_temperature_scales({
                "A": {"pre_scaled_values": [1, 2], "scaled_values": [3, 3]},
            })
        assert driver.temperature_scales() == {"A": None}

    def test_itc503_none_disables_legacy_calibration_only_for_selected_sensor(self, monkeypatch):
        driver = OxfordITC503(_null(responses=[b"R10\r", b"R10\r"]))
        monkeypatch.setattr(driver, "_itc503_to_true_temperature", lambda value: value * 2)
        driver.configure_temperature_scales({"A": None})
        assert driver.get_temperature("A") == 10
        assert driver.get_temperature("B") == 20

    def test_itc503_all_uncorrected_channels_avoid_control_sensor_queries(self):
        transport = _null(responses=[b"R10\r"])
        driver = OxfordITC503(transport)
        driver.configure_temperature_scales({"A": None, "B": None, "C": None})
        assert driver.get_setpoint(1) == 10
        driver.set_setpoint(1, 12)
        assert transport.write_log == [b"R0\r", b"T12.0\r"]

    def test_default_protocols(self):
        assert isinstance(OxfordITC503(transport=NullTransport()).protocol, OxfordProtocol)
        assert isinstance(OxfordMercuryTemperatureController(transport=NullTransport()).protocol, ScpiProtocol)

    def test_itc503_core_methods(self):
        t = _null(
            responses=[
                b"R4.2\r",
                b"R10.0\r",
                b"X0A1C3S00H1L0\r",
                b"R22.5\r",
                b"R30.0\r",
                b"R4.0\r",
                b"R0.0\r",
                b"X0A1C3S00H1L0\r",
            ]
        )
        tc = OxfordITC503(transport=t)
        assert tc.get_temperature("A") == pytest.approx(4.2)
        assert tc.get_setpoint(1) == pytest.approx(10.0)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert tc.get_heater_output(1) == pytest.approx(22.5)
        assert tc.get_pid(1) == PIDParameters(30.0, 4.0, 0.0)
        with pytest.raises(NotImplementedError):
            tc.get_ramp_rate(1)
        tc.set_setpoint(1, 12.0)
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)
        tc.set_input_channel(1, "B")
        tc.set_pid(1, 30.0, 4.0, 0.0)
        tc.start_sweep()
        assert t.write_log == [
            b"R1\r",
            b"R0\r",
            b"X\r",
            b"R5\r",
            b"R8\r",
            b"R9\r",
            b"R10\r",
            b"T12.0\r",
            b"X\r",
            b"L0\r",
            b"A0\r",
            b"H2\r",
            b"L0\r",
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

    def test_itc503_has_no_heater_ranges(self):
        t = _null()
        tc = OxfordITC503(transport=t)
        with pytest.raises(NotImplementedError):
            tc.get_heater_range(1)
        with pytest.raises(NotImplementedError):
            tc.set_heater_range(1, 1)
        assert not tc.get_capabilities().has_heater_range
        assert t.write_log == []

    def test_itc503_get_gas_flow_uses_r7_register(self):
        t = _null(responses=[b"R55.0\r"])
        tc = OxfordITC503(transport=t)
        assert tc.get_gas_flow() == pytest.approx(55.0)
        assert t.write_log == [b"R7\r"]

    def test_itc503_get_num_zones(self):
        tc = OxfordITC503(transport=_null())
        assert tc.get_num_zones(1) == 32

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

    @pytest.mark.parametrize("populated_rows", [0, 2, 32])
    def test_itc503_zone_table_stops_at_raw_zero_temperature(self, qapp, monkeypatch, populated_rows):
        responses = []
        expected_commands = []
        for row in range(1, populated_rows + 1):
            responses.extend([f"Q{row * 10}\r".encode(), b"Q30\r", b"Q4\r", b"Q0.5\r"])
            for column in range(1, 5):
                expected_commands.extend([f"x{row}\r".encode(), f"y{column}\r".encode(), b"q\r"])
        if populated_rows < 32:
            responses.append(b"Q0\r")
            expected_commands.extend([f"x{populated_rows + 1}\r".encode(), b"y1\r", b"q\r"])
        transport = _null(responses=responses)
        driver = OxfordITC503(transport=transport)
        # A calibration offset must not turn the raw end marker into a zone.
        monkeypatch.setattr(driver, "_itc503_to_true_temperature", lambda value: value + 5)
        engine = TemperatureControllerEngine()
        engine._driver = driver
        try:
            entries = engine.get_zone_table(1)
            assert entries == [
                ZoneEntry(row * 10 + 5, 30.0, 4.0, 0.5, 0.0, 0, 0.0)
                for row in range(1, populated_rows + 1)
            ]
            assert transport.write_log == expected_commands
        finally:
            engine._driver = None
            engine.shutdown()

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
            tc.set_zone(1, 33, ZoneEntry(100.0, 30.0, 5.0, 1.0, 0.0, 0, 0.0))

    def test_itc503_zone_row_upper_bound_is_valid(self):
        t = _null(responses=[b"Q100.0\r", b"Q30.0\r", b"Q5.0\r", b"Q1.0\r"])
        tc = OxfordITC503(transport=t)
        zone = tc.get_zone(1, 32)
        assert zone.upper_bound == pytest.approx(100.0)
        assert t.write_log[:3] == [b"x32\r", b"y1\r", b"q\r"]

    @pytest.mark.parametrize(
        ("status_response", "expected_mode"),
        [
            (b"X0A0C3S00H1L0\r", ControlMode.OPEN_LOOP),
            (b"X0A2C3S00H1L0\r", ControlMode.OPEN_LOOP),
            (b"X0A3C3S00H1L0\r", ControlMode.CLOSED_LOOP),
            (b"X0A1C3S00H1L1\r", ControlMode.ZONE),
            (b"X0A5C3S00H1L0\r", ControlMode.CLOSED_LOOP),
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
            (b"X0A1C3S00H1L0\r", False),
            (b"X0A1C3S01H1L0\r", True),
            (b"X0A1C3S05H1L0\r", True),
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

    def test_itc503_connection_selects_remote_without_changing_outputs(self):
        t = _null([b"ITC503 Version 1.11\r"])
        tc = OxfordITC503(transport=t)
        tc.confirm_identity()
        assert t.write_log == [b"V\r", b"C3\r"]

    @pytest.mark.parametrize("sensor,channel", [(1, "A"), (2, "B"), (3, "C")])
    def test_itc503_sensor_selection_is_hardware_backed(self, sensor, channel):
        t = _null([f"X0A1C3S00H{sensor}L0\r".encode()])
        tc = OxfordITC503(transport=t)
        tc.set_input_channel(1, channel)
        assert tc.get_input_channel(1) == channel
        assert t.write_log == [f"H{sensor}\r".encode(), b"X\r"]

    @pytest.mark.parametrize("status", range(8))
    @pytest.mark.parametrize("enabled", [False, True])
    def test_itc503_gas_toggle_preserves_heater_and_reads_live_status(self, status, enabled):
        t = _null([f"X0A{status}C3S00H1L0\r".encode()] * 2)
        tc = OxfordITC503(transport=t)
        assert tc.get_gas_auto() == bool(status & 2)
        tc.set_gas_auto(enabled)
        expected = (status & 1) | (2 if enabled else 0)
        assert t.write_log == [b"X\r", b"X\r", f"A{expected}\r".encode()]

    @pytest.mark.parametrize("gas", [0, 2])
    @pytest.mark.parametrize("mode,heater,table", [
        (ControlMode.OFF, 0, 0),
        (ControlMode.OPEN_LOOP, 0, 0),
        (ControlMode.CLOSED_LOOP, 1, 0),
        (ControlMode.ZONE, 1, 1),
    ])
    def test_itc503_heater_mode_preserves_gas(self, gas, mode, heater, table):
        t = _null([f"X0A{gas}C3S00H1L0\r".encode()])
        tc = OxfordITC503(transport=t)
        tc.set_loop_mode(1, mode)
        expected = [b"X\r", f"L{table}\r".encode(), f"A{gas | heater}\r".encode()]
        if mode is ControlMode.OFF:
            expected.append(b"O0.0\r")
        assert t.write_log == expected

    @pytest.mark.parametrize("response", [b"?G25.0\r", b"T\r", b"\r"])
    def test_itc503_write_rejects_errors_and_invalid_acknowledgements(self, response):
        t = NullTransport(responses=[response])
        t.open()
        tc = OxfordITC503(transport=t)
        tc.auto_check_errors = False
        with pytest.raises(InstrumentError):
            tc.set_gas_flow(25)
        assert t.write_log == [b"G25.0\r"]

    def test_itc503_write_consumes_ack_before_following_read(self):
        t = NullTransport(responses=[b"G\r", b"R25.0\r"])
        t.open()
        tc = OxfordITC503(transport=t)
        tc.set_gas_flow(25)
        assert tc.get_gas_flow() == 25
        assert t.write_log == [b"G25.0\r", b"R7\r"]

    @pytest.mark.parametrize("status", [b"X0A1C3S00H1\r", b"X0A1C3S33H1L0\r", b"garbage\r"])
    def test_itc503_malformed_status_cannot_trigger_mode_write(self, status):
        t = _null([status])
        with pytest.raises(ValueError, match="status"):
            OxfordITC503(transport=t).set_gas_auto(True)
        assert t.write_log == [b"X\r"]

    @pytest.mark.parametrize("value", [-1, 100, float("nan"), float("inf")])
    def test_itc503_output_validation_sends_nothing(self, value):
        t = _null()
        tc = OxfordITC503(transport=t)
        with pytest.raises(ValueError):
            tc.set_gas_flow(value)
        with pytest.raises(ValueError):
            tc.set_manual_heater_output(1, value)
        assert t.write_log == []

    def test_itc503_manual_output_voltage_limit_and_sweep_commands(self):
        t = _null()
        tc = OxfordITC503(transport=t)
        tc.set_manual_heater_output(1, 99.9)
        tc.set_maximum_heater_voltage(10)
        tc.start_sweep()
        tc.stop_sweep()
        assert t.write_log == [b"O99.9\r", b"M10.0\r", b"S1\r", b"S0\r"]
        assert not tc.get_capabilities().has_ramp
        with pytest.raises(NotImplementedError):
            tc.set_ramp_rate(1, 2)
        with pytest.raises(NotImplementedError):
            tc.set_ramp_enabled(1, True)

    def test_itc503_invalid_pid_is_rejected_before_partial_write(self):
        t = _null()
        tc = OxfordITC503(transport=t)
        with pytest.raises(ValueError):
            tc.set_pid(1, 20, 141, 1)
        assert t.write_log == []

    def test_capabilities(self):
        caps_itc = OxfordITC503(transport=_null()).get_capabilities()
        caps_mercury = OxfordMercuryTemperatureController(transport=_null()).get_capabilities()
        assert caps_itc.has_cryogen_control is True
        assert caps_itc.has_gas_auto_mode is True
        assert caps_itc.has_zone is True
        assert caps_mercury.has_cryogen_control is False
        assert caps_mercury.loop_numbers == ()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
