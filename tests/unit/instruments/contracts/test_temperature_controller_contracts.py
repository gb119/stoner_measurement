"""Contract tests for temperature-controller abstractions and composites."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.protocol import LakeshoreProtocol
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


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


def _make_tc(transport=None):
    """Return a minimal concrete temperature controller for contract tests."""

    class _FullTC(TemperatureController):
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

    return _FullTC(transport or _null(), LakeshoreProtocol())


class TestTemperatureControllerCore:
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
        tc.set_input_channel(1, "B")

    def test_get_setpoint(self):
        tc = _make_tc()
        assert tc.get_setpoint(1) == pytest.approx(80.0)

    def test_set_setpoint(self):
        tc = _make_tc()
        tc.set_setpoint(1, 100.0)

    def test_get_loop_mode(self):
        tc = _make_tc()
        assert tc.get_loop_mode(1) is ControlMode.CLOSED_LOOP

    def test_set_loop_mode(self):
        tc = _make_tc()
        tc.set_loop_mode(1, ControlMode.OPEN_LOOP)

    def test_get_heater_output(self):
        tc = _make_tc()
        assert tc.get_heater_output(1) == pytest.approx(25.0)

    def test_set_heater_range(self):
        tc = _make_tc()
        tc.set_heater_range(1, 2)

    def test_get_pid(self):
        tc = _make_tc()
        pid = tc.get_pid(1)
        assert isinstance(pid, PIDParameters)
        assert pid.p == pytest.approx(50.0)
        assert pid.i == pytest.approx(2.0)
        assert pid.d == pytest.approx(0.0)

    def test_set_pid(self):
        tc = _make_tc()
        tc.set_pid(1, 40.0, 1.5, 0.1)

    def test_get_ramp_rate(self):
        tc = _make_tc()
        assert tc.get_ramp_rate(1) == pytest.approx(10.0)

    def test_set_ramp_rate(self):
        tc = _make_tc()
        tc.set_ramp_rate(1, 5.0)

    def test_get_ramp_enabled(self):
        tc = _make_tc()
        assert tc.get_ramp_enabled(1) is False

    def test_set_ramp_enabled(self):
        tc = _make_tc()
        tc.set_ramp_enabled(1, True)

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


class TestTemperatureControllerEnums:
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


class TestTemperatureControllerDataClasses:
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
        reading = TemperatureReading(
            value=1000.0, status=SensorStatus.OK, units="Ohm"
        )
        assert reading.units == "Ohm"

    def test_temperature_reading_is_frozen(self):
        reading = TemperatureReading(value=1.0, status=SensorStatus.OK)
        with pytest.raises((AttributeError, TypeError)):
            reading.value = 2.0  # type: ignore[misc]

    def test_loop_status_fields(self):
        loop_status = LoopStatus(
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
        assert loop_status.setpoint == pytest.approx(80.0)
        assert loop_status.process_value == pytest.approx(77.0)
        assert loop_status.mode is ControlMode.CLOSED_LOOP
        assert loop_status.heater_output == pytest.approx(25.0)
        assert loop_status.ramp_enabled is False
        assert loop_status.ramp_rate == pytest.approx(10.0)
        assert loop_status.ramp_state is RampState.IDLE
        assert loop_status.p == pytest.approx(50.0)
        assert loop_status.input_channel == "A"

    def test_temperature_status_fields(self):
        reading = TemperatureReading(value=77.0, status=SensorStatus.OK)
        loop_status = LoopStatus(
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
        status = TemperatureStatus(temperatures={"A": reading}, loops={1: loop_status})
        assert status.temperatures["A"] is reading
        assert status.loops[1] is loop_status
        assert status.error_state is None

    def test_temperature_status_error_state(self):
        status = TemperatureStatus(temperatures={}, loops={}, error_state="sensor fault")
        assert status.error_state == "sensor fault"


class TestTemperatureControllerComposite:
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
        loop_status = tc.get_loop_status(1)
        assert isinstance(loop_status, LoopStatus)
        assert loop_status.setpoint == pytest.approx(80.0)
        assert loop_status.process_value == pytest.approx(77.0)
        assert loop_status.mode is ControlMode.CLOSED_LOOP
        assert loop_status.heater_output == pytest.approx(25.0)
        assert loop_status.ramp_enabled is False
        assert loop_status.ramp_rate == pytest.approx(10.0)
        assert loop_status.ramp_state is RampState.IDLE
        assert loop_status.p == pytest.approx(50.0)
        assert loop_status.i == pytest.approx(2.0)
        assert loop_status.d == pytest.approx(0.0)
        assert loop_status.input_channel == "A"

    def test_get_controller_status(self):
        tc = _make_tc()
        status = tc.get_controller_status()
        assert isinstance(status, TemperatureStatus)
        assert set(status.temperatures.keys()) == {"A", "B"}
        assert 1 in status.loops
        assert status.error_state is None

    def test_wait_for_setpoint_immediate_success(self, monkeypatch):
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, channel: 79.8)
        tc.wait_for_setpoint(1, "A", tolerance=1.0, timeout=1.0, poll_period=0.01)

    def test_wait_for_setpoint_times_out(self, monkeypatch):
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, channel: 50.0)
        with pytest.raises(TimeoutError, match="channel 'A'"):
            tc.wait_for_setpoint(1, "A", tolerance=0.5, timeout=0.05, poll_period=0.01)

    def test_wait_for_setpoint_converges(self, monkeypatch):
        readings = iter([50.0, 70.0, 79.6, 80.1])
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "get_setpoint", lambda self, loop: 80.0)
        monkeypatch.setattr(type(tc), "get_temperature", lambda self, channel: next(readings))
        tc.wait_for_setpoint(1, "A", tolerance=0.5, timeout=5.0, poll_period=0.001)

    def test_ramp_to_setpoint_enables_ramp_and_sets_setpoint(self, monkeypatch):
        calls = []
        tc = _make_tc()
        monkeypatch.setattr(
            type(tc),
            "set_ramp_enabled",
            lambda self, loop, enabled: calls.append(("ramp_enabled", loop, enabled)),
        )
        monkeypatch.setattr(
            type(tc),
            "set_setpoint",
            lambda self, loop, value: calls.append(("setpoint", loop, value)),
        )
        tc.ramp_to_setpoint(1, 200.0)
        assert ("ramp_enabled", 1, True) in calls
        assert ("setpoint", 1, 200.0) in calls
        assert calls.index(("ramp_enabled", 1, True)) < calls.index(("setpoint", 1, 200.0))

    def test_ramp_to_setpoint_sets_rate_when_provided(self, monkeypatch):
        calls = []
        tc = _make_tc()
        monkeypatch.setattr(
            type(tc), "set_ramp_rate", lambda self, loop, rate: calls.append(("rate", loop, rate))
        )
        monkeypatch.setattr(
            type(tc),
            "set_ramp_enabled",
            lambda self, loop, enabled: calls.append(("enabled", loop, enabled)),
        )
        monkeypatch.setattr(
            type(tc),
            "set_setpoint",
            lambda self, loop, value: calls.append(("setpoint", loop, value)),
        )
        tc.ramp_to_setpoint(1, 150.0, rate=5.0)
        assert ("rate", 1, 5.0) in calls
        assert ("enabled", 1, True) in calls
        assert ("setpoint", 1, 150.0) in calls
        assert calls.index(("rate", 1, 5.0)) < calls.index(("enabled", 1, True))
        assert calls.index(("enabled", 1, True)) < calls.index(("setpoint", 1, 150.0))

    def test_ramp_to_setpoint_skips_ramp_when_not_supported(self, monkeypatch):
        calls = []
        tc = _make_tc()
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
        monkeypatch.setattr(
            type(tc), "set_ramp_enabled", lambda self, loop, enabled: calls.append("enabled")
        )
        monkeypatch.setattr(
            type(tc), "set_setpoint", lambda self, loop, value: calls.append(("setpoint", value))
        )
        tc.ramp_to_setpoint(1, 200.0, rate=5.0)
        assert "rate" not in calls
        assert "enabled" not in calls
        assert ("setpoint", 200.0) in calls

    def test_ramp_to_setpoint_no_rate_no_set_ramp_rate_call(self, monkeypatch):
        calls = []
        tc = _make_tc()
        monkeypatch.setattr(type(tc), "set_ramp_rate", lambda self, loop, rate: calls.append("rate"))
        monkeypatch.setattr(
            type(tc), "set_ramp_enabled", lambda self, loop, enabled: calls.append("enabled")
        )
        monkeypatch.setattr(type(tc), "set_setpoint", lambda self, loop, value: calls.append("setpoint"))
        tc.ramp_to_setpoint(1, 100.0)
        assert "rate" not in calls
        assert "enabled" in calls
        assert "setpoint" in calls


class TestTemperatureControllerOptional:
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
        entry = ZoneEntry(
            upper_bound=50.0,
            p=10.0,
            i=1.0,
            d=0.0,
            ramp_rate=5.0,
            heater_range=1,
            heater_output=25.0,
        )
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


class TestTemperatureControllerExports:
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


class TestZoneEntry:
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


class TestZoneEntryOptionalAPI:
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
