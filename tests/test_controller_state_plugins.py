"""Tests for engine-backed temperature and magnet state plugins."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from stoner_measurement.instruments.magnet_controller import MagnetState
from stoner_measurement.instruments.temperature_controller import SensorStatus
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
)
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state import (
    _magnet_controller_plugin as magnet_module,
)
from stoner_measurement.plugins.state import (
    _temperature_controller_plugin as temperature_module,
)
from stoner_measurement.plugins.state_scan import (
    MagnetControllerScanPlugin,
    TemperatureControllerScanPlugin,
)
from stoner_measurement.plugins.state_sweep import (
    MagnetControllerSweepPlugin,
    TemperatureControllerSweepPlugin,
)
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    TemperatureChannelReading,
    TemperatureEngineState,
)


class _FakeDriverManager:
    def __init__(self, names):
        self._names = names

    def discover(self) -> None:
        pass

    def drivers_by_type(self, _instrument_type):
        return {name: object for name in self._names}


def _manager_factory(*names):
    return lambda: _FakeDriverManager(names)


class _FakeMagnetEngine:
    def __init__(self) -> None:
        self.connected_driver = None
        self.connected_driver_name = None
        self.connected_transport_name = None
        self.connected_address = None
        self.connect_calls: list[tuple[str, str, str]] = []
        self.ramp_rate_calls: list[float] = []
        self.ramp_to_field_calls: list[float] = []
        self.target_field_calls: list[float] = []
        self.ramp_to_target_calls = 0
        self._limits = SimpleNamespace(max_field=2.5)
        self._state = MagnetEngineState(
            reading=MagnetReading(
                timestamp=datetime.now(tz=UTC),
                field=0.75,
                current=12.0,
                voltage=0.4,
                heater_on=True,
                state=MagnetState.RAMPING,
                at_target=True,
            ),
            target_field=1.0,
            ramp_rate_field=0.2,
            engine_status=MagnetEngineStatus.POLLING,
        )

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        self.connect_calls.append((driver_name, transport_name, address))
        self.connected_driver_name = driver_name
        self.connected_transport_name = transport_name
        self.connected_address = address
        self.connected_driver = type(driver_name, (), {})()

    def read_controller_state(self):
        return self._state

    def get_engine_state(self):
        return self._state

    def set_ramp_rate_field(self, value: float) -> None:
        self.ramp_rate_calls.append(float(value))

    def ramp_to_field(self, value: float) -> None:
        self.ramp_to_field_calls.append(float(value))

    def set_target_field(self, value: float) -> None:
        self.target_field_calls.append(float(value))

    def ramp_to_target(self) -> None:
        self.ramp_to_target_calls += 1

    def get_limits(self):
        return self._limits


class _FakeTemperatureDriver:
    def __init__(self) -> None:
        self._caps = SimpleNamespace(
            min_temperature=1.5,
            max_temperature=400.0,
            input_channels=("A", "B"),
        )

    def get_capabilities(self):
        return self._caps


class _FakeTemperatureEngine:
    def __init__(self) -> None:
        self._driver = _FakeTemperatureDriver()
        self.connected_driver = self._driver
        self.connect_calls: list[tuple[str, str, str]] = []
        self.ramp_calls: list[tuple[int, float, bool]] = []
        self.setpoint_calls: list[tuple[int, float]] = []
        self.loop_settings_calls: list[int] = []
        self._state = TemperatureEngineState(
            readings={
                "A": TemperatureChannelReading(
                    channel="A",
                    value=5.0,
                    timestamp=datetime.now(tz=UTC),
                    status=SensorStatus.OK,
                ),
                "B": TemperatureChannelReading(
                    channel="B",
                    value=7.5,
                    timestamp=datetime.now(tz=UTC),
                    status=SensorStatus.OK,
                ),
            },
            setpoints={2: 10.0},
            input_channels={2: "B"},
            at_setpoint={2: True},
            engine_status=EngineStatus.POLLING,
        )

    def read_controller_state(self):
        return self._state

    def get_engine_state(self):
        return self._state

    def set_ramp(self, loop: int, rate: float, enabled: bool) -> None:
        self.ramp_calls.append((int(loop), float(rate), bool(enabled)))

    def set_setpoint(self, loop: int, value: float) -> None:
        self.setpoint_calls.append((int(loop), float(value)))

    def get_loop_settings(self, loop: int):
        self.loop_settings_calls.append(int(loop))
        return SimpleNamespace(input_channel="B")


def test_magnet_controller_scan_plugin_uses_engine(monkeypatch, qapp):
    engine = _FakeMagnetEngine()
    engine.connected_driver = object()
    monkeypatch.setattr(
        magnet_module,
        "MagnetControllerEngine",
        type("FakeMagnetControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = MagnetControllerScanPlugin()
    plugin.report_outputs = ["current", "voltage"]
    plugin.connect()
    plugin.set_state(1.25)

    assert engine.connect_calls == []
    assert engine.ramp_rate_calls[-1] == plugin.ramp_rate
    assert engine.ramp_to_field_calls == [1.25]
    assert plugin.get_state() == 0.75
    assert plugin.is_at_target() is True
    assert plugin.limits == (float("-inf"), 2.5)
    assert plugin.reported_values() == {
        "magnet_controller:Setpoint": "magnet_controller.value",
        "magnet_controller:Index": "magnet_controller.index",
        "magnet_controller:Current": "magnet_controller.current",
        "magnet_controller:Voltage": "magnet_controller.voltage",
    }


def test_magnet_controller_sweep_plugin_serialises(monkeypatch, qapp):
    engine = _FakeMagnetEngine()
    engine.connected_driver = object()
    monkeypatch.setattr(
        magnet_module,
        "MagnetControllerEngine",
        type("FakeMagnetControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = MagnetControllerSweepPlugin()
    plugin.ramp_rate = 0.33
    plugin.report_outputs = None
    plugin.set_target(1.1)
    plugin.set_rate(0.5)

    restored = BasePlugin.from_json(plugin.to_json())

    assert engine.target_field_calls == [1.1]
    assert engine.ramp_to_target_calls == 1
    assert engine.ramp_rate_calls[-1] == 30.0
    assert isinstance(restored, MagnetControllerSweepPlugin)
    assert restored.ramp_rate == 30.0
    assert restored.report_outputs is None
    assert restored.reported_values()["magnet_controller:Control Value"] == "magnet_controller.value"


def test_temperature_controller_scan_plugin_uses_loop_and_selected_sensors(monkeypatch, qapp):
    engine = _FakeTemperatureEngine()
    monkeypatch.setattr(
        temperature_module,
        "TemperatureControllerEngine",
        type("FakeTemperatureControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = TemperatureControllerScanPlugin()
    plugin.control_loop = 2
    plugin.sensor_channels = ["A"]
    plugin.connect()
    plugin.configure()
    plugin.set_state(20.0)

    assert engine.connect_calls == []
    assert engine.ramp_calls[-1] == (2, plugin.ramp_rate, True)
    assert engine.setpoint_calls[-1] == (2, 20.0)
    assert plugin.get_state() == 7.5
    assert plugin.is_at_target() is True
    assert plugin.limits == (1.5, 400.0)
    assert plugin.reported_values() == {
        "temperature_controller:Setpoint": "temperature_controller.value",
        "temperature_controller:Index": "temperature_controller.index",
        "temperature_controller:Loop Setpoint": "temperature_controller.control_setpoint",
        "temperature_controller:Sensor A": "temperature_controller.sensor_value('A')",
    }


def test_temperature_controller_sweep_plugin_round_trips(monkeypatch, qapp):
    engine = _FakeTemperatureEngine()
    monkeypatch.setattr(
        temperature_module,
        "TemperatureControllerEngine",
        type("FakeTemperatureControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = TemperatureControllerSweepPlugin()
    plugin.control_loop = 2
    plugin.ramp_rate = 3.0
    plugin.sensor_channels = None

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, TemperatureControllerSweepPlugin)
    assert restored.control_loop == 2
    assert restored.ramp_rate == 3.0
    assert restored.sensor_channels is None
    assert restored.reported_values() == {
        "temperature_controller:Control Value": "temperature_controller.value",
        "temperature_controller:Index": "temperature_controller.index",
        "temperature_controller:Loop Setpoint": "temperature_controller.control_setpoint",
        "temperature_controller:Sensor A": "temperature_controller.sensor_value('A')",
        "temperature_controller:Sensor B": "temperature_controller.sensor_value('B')",
    }


def test_magnet_controller_plugin_requires_existing_engine_connection(monkeypatch, qapp):
    engine = _FakeMagnetEngine()
    engine.connected_driver = None
    monkeypatch.setattr(
        magnet_module,
        "MagnetControllerEngine",
        type("FakeMagnetControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = MagnetControllerScanPlugin()

    import pytest

    with pytest.raises(RuntimeError, match="No magnet controller is connected"):
        plugin.connect()


def test_temperature_controller_plugin_requires_existing_engine_connection(monkeypatch, qapp):
    engine = _FakeTemperatureEngine()
    engine.connected_driver = None
    monkeypatch.setattr(
        temperature_module,
        "TemperatureControllerEngine",
        type("FakeTemperatureControllerEngine", (), {"instance": staticmethod(lambda: engine)}),
    )

    plugin = TemperatureControllerScanPlugin()
    import pytest

    with pytest.raises(RuntimeError, match="No temperature controller is connected"):
        plugin.connect()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
