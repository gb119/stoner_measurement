"""Focused tests for Lakeshore temperature controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.lakeshore import Lakeshore335, Lakeshore336, Lakeshore340
from stoner_measurement.instruments.protocol import LakeshoreProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControlMode,
    InputChannelSettings,
    PIDParameters,
    SensorStatus,
    ZoneEntry,
)
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


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
        for caps in (caps_335, caps_336):
            assert caps.has_zone is True
            assert caps.has_input_settings is True
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
        zone = ZoneEntry(
            upper_bound=100.0,
            p=50.0,
            i=10.0,
            d=0.5,
            ramp_rate=0.0,
            heater_range=2,
            heater_output=25.0,
        )
        tc.set_zone(1, 1, zone)
        assert t.write_log == [b"ZONE 1,1,100.0,50.0,10.0,0.5,25.0,2\r\n"]

    def test_lakeshore336_get_input_channel_settings(self):
        t = _null(
            responses=[
                b"3,0,4,0,1\r\n",
                b"1,10,2.0\r\n",
                b"22\r\n",
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
        t = _null(responses=[b"0,5,1.5\r\n"])
        tc = Lakeshore336(transport=t)
        settings = InputChannelSettings(filter_enabled=True)
        tc.set_input_channel_settings("A", settings)
        assert t.write_log == [b"FILTER? A\r\n", b"FILTER A,1,5,1.5\r\n"]

    def test_lakeshore336_set_input_channel_settings_curve_only(self):
        t = _null()
        tc = Lakeshore336(transport=t)
        settings = InputChannelSettings(curve_number=5)
        tc.set_input_channel_settings("A", settings)
        assert t.write_log == [b"INCRV A,5\r\n"]

    def test_lakeshore340_get_input_channel_uses_cset(self):
        t = _null(responses=[b"2,1,1,0\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_input_channel(1) == "B"
        assert t.write_log == [b"CSET? 1\r\n"]

    def test_lakeshore340_set_input_channel_uses_cset(self):
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
                upper_bound=100.0,
                p=50.0,
                i=10.0,
                d=0.0,
                ramp_rate=0.0,
                heater_range=1,
                heater_output=0.0,
            )
            tc.set_zone(1, 1, zone)

    def test_lakeshore336_loop_numbers(self):
        caps = Lakeshore336(transport=_null()).get_capabilities()
        assert caps.loop_numbers == (1, 2, 3, 4)
        assert caps.num_loops == 4


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
