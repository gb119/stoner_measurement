"""Focused tests for Oxford temperature controller drivers."""

from __future__ import annotations

import pytest

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


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
