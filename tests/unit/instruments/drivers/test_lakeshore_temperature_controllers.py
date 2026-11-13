"""Focused tests for Lakeshore temperature controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.lakeshore import Lakeshore335, Lakeshore336, Lakeshore340
from stoner_measurement.instruments.lakeshore.temperature_controllers import (
    Lakeshore340InputSettings,
)
from stoner_measurement.instruments.protocol import LakeshoreProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControlMode,
    InputChannelSettings,
    PIDParameters,
    SensorStatus,
    ZoneEntry,
)
from stoner_measurement.instruments.transport import GpibTransport, NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    class StatusTransport(NullTransport):
        def write(self, data, slow=None):
            result = super().write(data, slow=slow)
            if data == b"*ESR?\r\n":
                self._responses.appendleft(b"0\r\n")
            return result

    transport = StatusTransport(responses=responses or [])
    transport.open()
    return transport


class TestLakeshoreTemperatureControllers:
    @pytest.mark.parametrize("status", [0x00, 0x01, 0x04, 0x05, 0x80])
    def test_lakeshore340_gpib_poll_accepts_normal_status(self, status):
        class Resource:
            def write_raw(self, data):
                assert data == b"KRDG? A\r\n"

            def read_stb(self):
                return status

            def read_raw(self, count):
                return b"4.2\r\n"

        transport = GpibTransport(address=12)
        driver = Lakeshore340(transport)
        transport._resource = Resource()
        assert transport._use_mav is False
        assert driver.get_temperature("A") == pytest.approx(4.2)

    def test_lakeshore340_gpib_retains_instrument_error_check(self):
        class Resource:
            def write_raw(self, data):
                pass

            def read_stb(self):
                return 0x10

        transport = GpibTransport(address=12)
        driver = Lakeshore340(transport)
        transport._resource = Resource()
        with pytest.raises(InstrumentError, match=r"(?s)KRDG.*STB=16"):
            driver.get_temperature("A")

    def test_lakeshore335_disables_gpib_mav_polling(self):
        transport = GpibTransport(address=12)

        Lakeshore335(transport=transport)

        assert transport._use_mav is False
        assert transport._command_complete_mask is None

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
        assert caps_340.has_zone is True
        assert caps_340.has_input_settings is True
        assert caps_340.input_settings_model == "lakeshore340"
        assert caps_340.heater_range_loops == (1,)

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
        t = _null(responses=[b"100.0,50.0,10.0,0.5,25.0,2,1,4.5\r\n"])
        tc = Lakeshore336(transport=t)
        zone = tc.get_zone(1, 1)
        assert zone.upper_bound == pytest.approx(100.0)
        assert zone.p == pytest.approx(50.0)
        assert zone.i == pytest.approx(10.0)
        assert zone.d == pytest.approx(0.5)
        assert zone.heater_output == pytest.approx(25.0)
        assert zone.heater_range == 2
        assert zone.input_channel == 1
        assert zone.ramp_rate == pytest.approx(4.5)
        assert t.write_log == [b"ZONE? 1,1\r\n"]

    def test_lakeshore335_get_zone_reads_control_input_and_ramp_rate(self):
        t = _null(responses=[b"80.0,40.0,8.0,0.2,10.0,1,2,3.5\r\n"])
        zone = Lakeshore335(transport=t).get_zone(1, 2)

        assert zone.input_channel == 2
        assert zone.ramp_rate == pytest.approx(3.5)
        assert t.write_log == [b"ZONE? 1,2\r\n"]

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
        assert t.write_log == [b"ZONE 1,1,100.0,50.0,10.0,0.5,25.0,2,0,0.0\r\n"]

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
        t = _null(responses=[b"B,1,1,0\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_input_channel(1) == "B"
        assert t.write_log == [b"CSET? 1\r\n"]

    def test_lakeshore340_set_input_channel_uses_cset(self):
        t = _null(responses=[b"A,1,1,0\r\n"])
        tc = Lakeshore340(transport=t)
        tc.set_input_channel(1, "B")
        assert t.write_log == [b"CSET? 1\r\n", b"CSET 1,B,1,1,0\r\n", b"*ESR?\r\n"]

    def test_lakeshore340_get_loop_mode_uses_cmode(self):
        t = _null(responses=[b"A,1,1,0\r\n", b"1\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP
        assert t.write_log == [b"CSET? 1\r\n", b"CMODE? 1\r\n"]

    def test_lakeshore340_set_loop_mode_uses_cmode(self):
        t = _null([b"A,1,0,1\r\n"])
        tc = Lakeshore340(transport=t)
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)
        assert t.write_log == [b"CSET? 1\r\n", b"CMODE 1,3\r\n", b"*ESR?\r\n",
                               b"CSET 1,A,1,1,1\r\n", b"*ESR?\r\n"]

    def test_lakeshore340_zone_methods_use_native_six_fields(self):
        t = _null([b"100,50,10,0,25,2\r\n"])
        tc = Lakeshore340(transport=t)
        assert tc.get_num_zones(1) == 10
        zone = tc.get_zone(1, 1)
        assert zone == ZoneEntry(100, 50, 10, 0, 0, 2, 25)
        tc.set_zone(1, 1, zone)
        assert t.write_log == [b"ZONE? 1,1\r\n", b"ZONE 1,1,100.0,50.0,10.0,0.0,25.0,2\r\n",
                               b"*ESR?\r\n"]

    def test_lakeshore336_loop_numbers(self):
        caps = Lakeshore336(transport=_null()).get_capabilities()
        assert caps.loop_numbers == (1, 2, 3, 4)
        assert caps.num_loops == 4


@pytest.mark.parametrize("loop,query", [(1, b"HTR?\r\n"), (2, b"AOUT? 2\r\n")])
def test_340_actual_output_query_has_native_addressing(loop, query):
    transport = _null([b"+050.0%\r\n"])
    assert Lakeshore340(transport).get_heater_output(loop) == 50
    assert transport.write_log == [query]


def test_340_range_is_only_for_the_single_heater():
    transport = _null([b"3\r\n"])
    driver = Lakeshore340(transport)
    assert driver.get_heater_range(1) == 3
    driver.set_heater_range(1, 2)
    assert transport.write_log == [b"RANGE?\r\n", b"RANGE 2\r\n", b"*ESR?\r\n"]
    for method, args in ((driver.get_heater_range, (2,)), (driver.set_heater_range, (2, 1))):
        with pytest.raises(NotImplementedError):
            method(*args)


@pytest.mark.parametrize("loop", [1, 2])
def test_340_off_disables_control_without_selecting_closed_loop(loop):
    transport = _null([b"B,2,1,1\r\n", b"B,2,0,1\r\n"])
    driver = Lakeshore340(transport)
    driver.set_loop_mode(loop, ControlMode.OFF)
    assert driver.get_loop_mode(loop) is ControlMode.OFF
    assert transport.write_log == [f"CSET? {loop}\r\n".encode(), f"CSET {loop},B,2,0,1\r\n".encode(),
                                    b"*ESR?\r\n", f"CSET? {loop}\r\n".encode()]


def test_340_celsius_setpoints_are_exposed_as_kelvin():
    transport = _null([b"A,2,1,0\r\n", b"-20\r\n", b"A,2,1,0\r\n"])
    driver = Lakeshore340(transport)
    assert driver.get_setpoint(1) == pytest.approx(253.15)
    driver.set_setpoint(1, 273.15)
    assert transport.write_log[-2:] == [b"SETP 1,0.0\r\n", b"*ESR?\r\n"]


def test_340_sensor_unit_setpoints_are_not_misreported_as_kelvin():
    transport = _null([b"A,3,1,0\r\n"] * 2)
    driver = Lakeshore340(transport)
    with pytest.raises(NotImplementedError):
        driver.get_setpoint(1)
    with pytest.raises(NotImplementedError):
        driver.set_setpoint(1, 20)
    assert transport.write_log == [b"CSET? 1\r\n"] * 2


@pytest.mark.parametrize("status,expected", [
    (0, SensorStatus.OK), (1, SensorStatus.INVALID), (2, SensorStatus.INVALID),
    (16, SensorStatus.UNDERRANGE), (32, SensorStatus.OVERRANGE),
    (64, SensorStatus.INVALID), (128, SensorStatus.OVERRANGE),
])
def test_340_sensor_status_uses_340_bit_definitions(status, expected):
    transport = _null([f"{status}\r\n".encode()])
    assert Lakeshore340(transport).get_sensor_status("A") is expected


@pytest.mark.parametrize("status", [4, 8, 16, 32, 60])
def test_340_event_errors_propagate_without_replaying_the_action(status):
    transport = NullTransport([f"{status}\r\n".encode()])
    transport.open()
    driver = Lakeshore340(transport)
    with pytest.raises(InstrumentError):
        driver.set_manual_heater_output(2, -20)
    assert transport.write_log == [b"MOUT 2,-20\r\n", b"*ESR?\r\n"]


def test_340_native_input_fields_do_not_use_335_intype_layout():
    transport = _null([b"8,2,1,7,8\r\n", b"1,2\r\n", b"1,10,2\r\n", b"25\r\n"])
    driver = Lakeshore340(transport)
    settings = driver.get_input_channel_settings("A")
    assert isinstance(settings, Lakeshore340InputSettings)
    assert settings.sensor_type == 8
    assert settings.sensor_units == 2
    assert settings.coefficient == 1
    assert settings.excitation == 7
    assert settings.range_ == 8
    assert settings.compensation_mode == 2
    assert settings.units is None and settings.autorange is None
    driver.set_input_channel_settings("A", Lakeshore340InputSettings(sensor_type=8))
    assert transport.write_log[-2:] == [b"INTYPE A,8,,,,\r\n", b"*ESR?\r\n"]
    driver.set_input_channel_settings("A", Lakeshore340InputSettings(compensation_mode=2, curve_number=22))
    assert transport.write_log[-4:] == [b"INSET A,,2\r\n", b"*ESR?\r\n",
                                        b"INCRV A,22\r\n", b"*ESR?\r\n"]


def test_340_rejects_335_input_fields_and_invalid_settings_before_writes():
    transport = _null()
    driver = Lakeshore340(transport)
    for settings in (InputChannelSettings(autorange=True), InputChannelSettings(units=1),
                     Lakeshore340InputSettings(excitation=13), InputChannelSettings(filter_points=65)):
        with pytest.raises(ValueError):
            driver.set_input_channel_settings("A", settings)
    for value in (-1, float("nan"), 1001):
        with pytest.raises(ValueError):
            driver.set_pid(1, value, 1, 1)
    assert transport.write_log == []


@pytest.mark.parametrize("response", [b"1,1,1,0\r\n", b"A,1,2,0\r\n", b"A,1,1\r\n"])
def test_340_invalid_control_readback_prevents_configuration_write(response):
    transport = _null([response])
    with pytest.raises(ValueError):
        Lakeshore340(transport).set_loop_mode(1, ControlMode.CLOSED_LOOP)
    assert transport.write_log == [b"CSET? 1\r\n"]


@pytest.mark.parametrize("loop", [1, 2])
def test_primary_340_apply_configures_ramp_and_native_output_before_target(
    loop, monkeypatch, managed_qt_widget, wait_temperature_tasks
):
    from qtpy.QtWidgets import QPushButton

    from stoner_measurement.temperature_control import engine as engine_module
    from stoner_measurement.ui.temperature_panel import _LoopControlGroup

    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    transport = _null([b"A,1,1,0\r\n", b"0,1\r\n", b"0,5\r\n",
                       b"B,1,1,0\r\n", b"B,1,1,0\r\n"])
    driver = Lakeshore340(transport)
    service = engine_module.TemperatureControllerEngine()
    service.set_polling_rate(0)
    service._driver = driver
    try:
        group = managed_qt_widget(_LoopControlGroup(loop, service, driver.get_capabilities()))
        from stoner_measurement.temperature_control.types import LoopSettings

        monkeypatch.setattr(service, "get_loop_settings", lambda loop: LoopSettings(
            4.2, ControlMode.CLOSED_LOOP, "A", False, 0, 1, 1, 1,
        ))
        assert group.read_from_hardware()
        group._channel_combo.setCurrentIndex(group._channel_combo.findData("B"))
        group._mode_combo.setCurrentIndex(group._mode_combo.findData(ControlMode.CLOSED_LOOP))
        group._sp_spin.setValue(30)
        group._ramp_rate_spin.setValue(5)
        group._ramp_enable.setChecked(True)
        group._pid_p_spin.setValue(20)
        group._pid_i_spin.setValue(3)
        group._pid_d_spin.setValue(1)
        if loop == 1:
            group._heater_range_combo.setCurrentIndex(2)
        else:
            assert group._heater_range_spin.isHidden()
        next(button for button in group.findChildren(QPushButton) if button.text() == "Apply").click()
        wait_temperature_tasks(service)
        commands = [data for data in transport.write_log if data != b"*ESR?\r\n"]
        assert commands[:6] == [f"CSET? {loop}\r\n".encode(), f"CSET {loop},B,1,1,0\r\n".encode(),
                                f"RAMP? {loop}\r\n".encode(), f"RAMP {loop},0,5.0\r\n".encode(),
                                f"RAMP? {loop}\r\n".encode(), f"RAMP {loop},1,5.0\r\n".encode()]
        assert commands[-5:] == [f"CSET? {loop}\r\n".encode(), f"SETP {loop},30.0\r\n".encode(),
                                 f"CSET? {loop}\r\n".encode(), f"CMODE {loop},1\r\n".encode(),
                                 f"CSET {loop},B,1,1,0\r\n".encode()]
        assert (b"RANGE 2\r\n" in commands) is (loop == 1)
    finally:
        service.shutdown()


@pytest.mark.parametrize("response", [b"2,5\r\n", b"1,nan\r\n", b"1,101\r\n"])
def test_340_bad_ramp_readback_cannot_trigger_a_write(response):
    transport = _null([response])
    with pytest.raises(ValueError):
        Lakeshore340(transport).set_ramp_rate(1, 5)
    assert transport.write_log == [b"RAMP? 1\r\n"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
