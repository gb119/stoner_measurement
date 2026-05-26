"""Tests for TemperatureMonitorPlugin."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from stoner_measurement.instruments.temperature_controller import SensorStatus
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.monitor import temperature_controller as tc_module
from stoner_measurement.plugins.monitor.temperature_controller import (
    TemperatureMonitorPlugin,
    _parse_channel_list,
    _parse_int_list,
)
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    TemperatureChannelReading,
    TemperatureEngineState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDriverManager:
    def __init__(self, *names):
        self._names = list(names)

    def discover(self) -> None:
        pass

    def drivers_by_type(self, _instrument_type):
        return {n: object for n in self._names}


def _make_state(*, channels=("A", "B"), loops=(1,)) -> TemperatureEngineState:
    now = datetime.now(tz=UTC)
    readings = {
        ch: TemperatureChannelReading(
            channel=ch,
            value=300.0 + i * 10,
            timestamp=now,
            status=SensorStatus.OK,
            rate_of_change=0.5 + i * 0.1,
        )
        for i, ch in enumerate(channels)
    }
    setpoints = {lp: 295.0 + lp for lp in loops}
    heater_outputs = {lp: 10.0 * lp for lp in loops}
    stable = {lp: lp % 2 == 0 for lp in loops}
    return TemperatureEngineState(
        readings=readings,
        setpoints=setpoints,
        heater_outputs=heater_outputs,
        at_setpoint={lp: True for lp in loops},
        stable=stable,
        engine_status=EngineStatus.POLLING,
    )


class _FakeEngine:
    def __init__(self, state: TemperatureEngineState | None = None) -> None:
        self.connected_driver = None
        self.connected_driver_name = None
        self.connected_transport_name = None
        self.connected_address = None
        self.connect_calls: list[tuple[str, str, str]] = []
        self.poll_calls: int = 0
        self._state: TemperatureEngineState = state or TemperatureEngineState(
            engine_status=EngineStatus.DISCONNECTED
        )

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        self.connect_calls.append((driver_name, transport_name, address))
        self.connected_driver_name = driver_name
        self.connected_transport_name = transport_name
        self.connected_address = address
        self.connected_driver = SimpleNamespace()

    def get_engine_state(self) -> TemperatureEngineState:
        return self._state

    def read_controller_state(self) -> TemperatureEngineState:
        """Simulate a controller state read and increment the poll counter."""
        self.poll_calls += 1
        return self._state


def _make_plugin(engine: _FakeEngine, monkeypatch, driver_name: str = "FakeTemp") -> TemperatureMonitorPlugin:
    monkeypatch.setattr(tc_module, "InstrumentDriverManager", lambda: _FakeDriverManager(driver_name))
    monkeypatch.setattr(
        tc_module,
        "TemperatureControllerEngine",
        type("_FakeTCE", (), {"instance": staticmethod(lambda: engine)}),
    )
    plugin = TemperatureMonitorPlugin()
    plugin.driver_name = driver_name
    return plugin


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_parse_int_list_valid():
    assert _parse_int_list("1, 2, 3", [1]) == [1, 2, 3]


def test_parse_int_list_deduplicated():
    assert _parse_int_list("1, 1, 2", [1]) == [1, 2]


def test_parse_int_list_empty_returns_default():
    assert _parse_int_list("", [1]) == [1]


def test_parse_int_list_invalid_returns_default():
    assert _parse_int_list("abc", [1]) == [1]


def test_parse_channel_list_none_when_blank():
    assert _parse_channel_list("") is None


def test_parse_channel_list_single():
    assert _parse_channel_list("A") == ["A"]


def test_parse_channel_list_multiple():
    assert _parse_channel_list("A, B, C") == ["A", "B", "C"]


def test_parse_channel_list_deduplicated():
    assert _parse_channel_list("A, A, B") == ["A", "B"]


# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------


def test_plugin_name(qapp):
    m = TemperatureMonitorPlugin()
    assert m.name == "Temperature Monitor"


def test_plugin_type(qapp):
    m = TemperatureMonitorPlugin()
    assert m.plugin_type == "monitor"


# ---------------------------------------------------------------------------
# quantity_names and units
# ---------------------------------------------------------------------------


def test_quantity_names_with_all_parameters(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    names = plugin.quantity_names
    assert "setpoint_1" in names
    assert "temperature_A" in names
    assert "heater_1" in names
    assert "rate_A" in names
    assert "stable_1" in names


def test_quantity_names_filtered_by_flags(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]
    plugin.report_setpoints = False
    plugin.report_heater = False
    plugin.report_stability = False

    names = plugin.quantity_names
    assert "setpoint_1" not in names
    assert "heater_1" not in names
    assert "stable_1" not in names
    assert "temperature_A" in names
    assert "rate_A" in names


def test_units_map(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    u = plugin.units
    assert u["setpoint_1"] == "K"
    assert u["temperature_A"] == "K"
    assert u["heater_1"] == "%"
    assert u["rate_A"] == "K/min"
    assert u["stable_1"] == ""


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------


def test_read_returns_all_parameters(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    reading = plugin.read()

    assert reading["setpoint_1"] == pytest.approx(296.0)
    assert reading["temperature_A"] == pytest.approx(300.0)
    assert reading["heater_1"] == pytest.approx(10.0)
    assert reading["rate_A"] == pytest.approx(0.5)
    assert reading["stable_1"] == 0.0  # loop 1 is not stable (odd)


def test_read_stable_flag(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[2])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [2]

    reading = plugin.read()
    assert reading["stable_2"] == 1.0  # loop 2 is stable (even)


def test_read_nan_when_channel_missing(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["B"]  # "B" not in state.readings
    plugin.control_loops = [1]

    reading = plugin.read()
    assert math.isnan(reading["temperature_B"])
    assert math.isnan(reading["rate_B"])


def test_read_nan_when_loop_missing(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [9]  # loop 9 not in state

    reading = plugin.read()
    assert math.isnan(reading["setpoint_9"])
    assert math.isnan(reading["heater_9"])


def test_read_caches_last_reading(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    plugin.read()
    assert "setpoint_1" in plugin.last_reading


def test_read_force_poll_triggers_engine_poll(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    assert engine.poll_calls == 0
    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    assert reading["setpoint_1"] == pytest.approx(296.0)


def test_read_no_force_poll_does_not_trigger_engine_poll(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    plugin.read()
    assert engine.poll_calls == 0


def test_read_force_poll_falls_back_to_cached_state_when_poll_returns_none(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)

    def _returning_none():
        engine.poll_calls += 1
        return None

    engine.read_controller_state = _returning_none  # type: ignore[method-assign]

    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]

    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    # Falls back to cached state — values should still be present
    assert reading["setpoint_1"] == pytest.approx(296.0)


# ---------------------------------------------------------------------------
# Accessor methods
# ---------------------------------------------------------------------------


def test_setpoint_method(monkeypatch, qapp):
    state = _make_state(channels=[], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    assert plugin.setpoint(1) == pytest.approx(296.0)
    assert math.isnan(plugin.setpoint(99))


def test_temperature_method(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    assert plugin.temperature("A") == pytest.approx(300.0)
    assert math.isnan(plugin.temperature("Z"))


def test_heater_method(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    assert plugin.heater(1) == pytest.approx(10.0)
    assert math.isnan(plugin.heater(99))


def test_rate_method(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    assert plugin.rate("A") == pytest.approx(0.5)
    assert math.isnan(plugin.rate("Z"))


def test_stable_method(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1, 2])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    assert plugin.stable(1) == 0.0   # odd loop = not stable
    assert plugin.stable(2) == 1.0   # even loop = stable
    assert plugin.stable(99) == 0.0  # unknown loop = not stable


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_calls_engine(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.transport_name = "Null (test)"
    plugin.address = ""
    plugin.connect()
    assert engine.connect_calls == [("FakeTemp", "Null (test)", "")]
    plugin.disconnect()


def test_connect_raises_without_driver(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch, driver_name="")
    plugin.driver_name = ""
    with pytest.raises(RuntimeError, match="No temperature controller driver selected"):
        plugin.connect()


def test_connect_does_not_reconnect_when_already_connected(monkeypatch, qapp):
    engine = _FakeEngine()
    engine.connected_driver = SimpleNamespace()
    engine.connected_driver_name = "FakeTemp"
    engine.connected_transport_name = "Null (test)"
    engine.connected_address = ""
    plugin = _make_plugin(engine, monkeypatch)
    plugin.transport_name = "Null (test)"
    plugin.address = ""
    plugin.connect()
    assert engine.connect_calls == []
    plugin.disconnect()


def test_connect_reconnects_on_driver_change(monkeypatch, qapp):
    engine = _FakeEngine()
    engine.connected_driver = SimpleNamespace()
    engine.connected_driver_name = "OldDriver"
    engine.connected_transport_name = "Null (test)"
    engine.connected_address = ""
    plugin = _make_plugin(engine, monkeypatch, driver_name="FakeTemp")
    plugin.transport_name = "Null (test)"
    plugin.address = ""
    plugin.connect()
    assert engine.connect_calls == [("FakeTemp", "Null (test)", "")]
    plugin.disconnect()


# ---------------------------------------------------------------------------
# reported_values
# ---------------------------------------------------------------------------


def test_reported_values_all_parameters(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]
    var = plugin.instance_name

    vals = plugin.reported_values()
    assert f"{var}:Setpoint loop 1" in vals
    assert vals[f"{var}:Setpoint loop 1"] == f"{var}.setpoint(1)"
    assert f"{var}:Temperature A" in vals
    assert vals[f"{var}:Temperature A"] == f"{var}.temperature('A')"
    assert f"{var}:Heater loop 1" in vals
    assert vals[f"{var}:Heater loop 1"] == f"{var}.heater(1)"
    assert f"{var}:Rate A" in vals
    assert vals[f"{var}:Rate A"] == f"{var}.rate('A')"
    assert f"{var}:Stable loop 1" in vals
    assert vals[f"{var}:Stable loop 1"] == f"{var}.stable(1)"


def test_reported_values_honours_flags(monkeypatch, qapp):
    state = _make_state(channels=["A"], loops=[1])
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = ["A"]
    plugin.control_loops = [1]
    plugin.report_setpoints = False
    plugin.report_heater = False
    var = plugin.instance_name

    vals = plugin.reported_values()
    assert f"{var}:Setpoint loop 1" not in vals
    assert f"{var}:Heater loop 1" not in vals
    assert f"{var}:Temperature A" in vals


# ---------------------------------------------------------------------------
# JSON serialisation round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.control_loops = [1, 2]
    plugin.sensor_channels = ["A", "B"]
    plugin.report_setpoints = True
    plugin.report_temperatures = True
    plugin.report_heater = False
    plugin.report_rate = True
    plugin.report_stability = False
    plugin.transport_name = "Null (test)"
    plugin.address = ""

    data = plugin.to_json()
    assert data["report_heater"] is False
    assert data["report_stability"] is False
    assert data["control_loops"] == [1, 2]
    assert data["sensor_channels"] == ["A", "B"]

    restored = BasePlugin.from_json(data)
    assert isinstance(restored, TemperatureMonitorPlugin)
    assert restored.control_loops == [1, 2]
    assert restored.sensor_channels == ["A", "B"]
    assert restored.report_heater is False
    assert restored.report_stability is False
    assert restored.report_setpoints is True


def test_json_round_trip_sensor_channels_none(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sensor_channels = None

    data = plugin.to_json()
    assert data["sensor_channels"] is None

    restored = BasePlugin.from_json(data)
    assert isinstance(restored, TemperatureMonitorPlugin)
    assert restored.sensor_channels is None


# ---------------------------------------------------------------------------
# Config widget
# ---------------------------------------------------------------------------


def test_config_widget_created(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    w = plugin.config_widget()
    assert w is not None


def test_config_tabs_has_general_tab(monkeypatch, qapp):
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    tabs = plugin.config_tabs()
    tab_titles = [title for title, _ in tabs]
    assert "General" in tab_titles
    assert "Temperature Monitor" in tab_titles
