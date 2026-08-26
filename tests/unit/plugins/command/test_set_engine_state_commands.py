"""Tests for engine-state command plugins."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QComboBox, QLineEdit, QSpinBox

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import (
    SetFieldCommand,
    SetPositionCommand,
    SetTemperatureCommand,
)
from stoner_measurement.plugins.command.pressure_set_flow import PressureSetFlowCommand
from stoner_measurement.ui.widgets import SISpinBox


class _StateEngine:
    def __init__(self, states, *, driver_attribute: str = "connected_driver") -> None:
        setattr(self, driver_attribute, object())
        self.states = list(states)
        self.index = 0
        self.calls = []

    def read_controller_state(self):
        state = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return state

    def get_engine_state(self):
        return self.states[min(self.index, len(self.states) - 1)]

    def set_setpoint(self, loop, value):
        self.calls.append(("temperature", loop, value))

    def ramp_to_field(self, value):
        self.calls.append(("field", value))

    def move_to_angle(self, value, *, direction):
        self.calls.append(("position", value, direction))

    def set_flow_rate(self, channel, value):
        self.calls.append(("flow", channel, value))


def _install_engine(monkeypatch, module: str, class_name: str, fake) -> None:
    replacement = type("_Singleton", (), {"instance": staticmethod(lambda: fake)})
    monkeypatch.setattr(f"{module}.{class_name}", replacement)


def test_temperature_uses_loop_waits_and_snapshots_outputs(monkeypatch, qapp, engine):
    reading = SimpleNamespace(value=123.4)
    pending = SimpleNamespace(
        readings={"A": reading}, setpoints={2: 125.0}, heater_outputs={2: 10.0},
        input_channels={2: "A"}, at_setpoint={2: False}, stable={2: False},
    )
    settling = SimpleNamespace(
        readings={"A": reading}, setpoints={2: 125.0}, heater_outputs={2: 8.0},
        input_channels={2: "A"}, at_setpoint={2: True}, stable={2: False},
    )
    stable = SimpleNamespace(
        readings={"A": reading}, setpoints={2: 125.0}, heater_outputs={2: 7.0},
        input_channels={2: "A"}, at_setpoint={2: True}, stable={2: True},
    )
    fake = _StateEngine([pending, settling, stable])
    _install_engine(
        monkeypatch,
        "stoner_measurement.plugins.command.set_temperature",
        "TemperatureControllerEngine",
        fake,
    )
    monkeypatch.setattr("stoner_measurement.plugins.command.set_engine_state.time.sleep", lambda _: None)
    command = SetTemperatureCommand()
    command.control_loop = 2
    command.setpoint_expr = "target"
    engine.add_plugin("set_temperature", command)
    engine._namespace["target"] = 125.0  # noqa: SLF001

    command.execute()

    assert fake.calls == [("temperature", 2, 125.0)]
    assert fake.index == 3
    assert command.output_value("Temperature") == 123.4
    assert command.output_value("Heater Output") == 7.0
    assert command.output_value("At Setpoint") == 1.0
    assert command.output_value("Stable") == 1.0


def test_temperature_false_wait_expression_does_not_require_stability(monkeypatch, qapp, engine):
    """A false wait condition captures one fresh state without blocking."""
    state = SimpleNamespace(
        readings={}, setpoints={1: 310.0}, heater_outputs={1: 0.0},
        input_channels={}, at_setpoint={1: True}, stable={1: False},
    )
    fake = _StateEngine([state])
    _install_engine(
        monkeypatch,
        "stoner_measurement.plugins.command.set_temperature",
        "TemperatureControllerEngine",
        fake,
    )
    command = SetTemperatureCommand()
    command.setpoint_expr = "310.0"
    command.wait_expr = "False"
    engine.add_plugin("set_temperature", command)

    command.execute()

    assert fake.index == 1
    assert command.output_value("Stable") == 0.0


def test_field_false_wait_expression_takes_one_fresh_snapshot(monkeypatch, qapp, engine):
    state = SimpleNamespace(
        reading=SimpleNamespace(field=0.4, current=4.0, voltage=0.2, quench_detected=False),
        target_field=1.0, at_target=False, stable=False,
    )
    fake = _StateEngine([state])
    _install_engine(
        monkeypatch,
        "stoner_measurement.plugins.command.set_field",
        "MagnetControllerEngine",
        fake,
    )
    command = SetFieldCommand()
    command.setpoint_expr = "target_field"
    command.wait_expr = "should_wait"
    engine.add_plugin("set_field", command)
    engine._namespace.update({"target_field": 1.0, "should_wait": False})  # noqa: SLF001

    command.execute()

    assert fake.calls == [("field", 1.0)]
    assert fake.index == 1
    assert command.output_value("Field") == 0.4
    assert command.output_value("At Target") == 0.0


def test_position_passes_configured_direction(monkeypatch, qapp, engine):
    state = SimpleNamespace(
        reading=SimpleNamespace(angle=45.0, angular_rate=0.0),
        target_angle=45.0, at_target=True, stable=True,
    )
    fake = _StateEngine([state])
    _install_engine(
        monkeypatch,
        "stoner_measurement.plugins.command.set_position",
        "MotorControllerEngine",
        fake,
    )
    command = SetPositionCommand()
    command.direction = MotorMoveDirection.COUNTERCLOCKWISE
    command.setpoint_expr = "45"
    engine.add_plugin("set_position", command)

    command.execute()

    assert fake.calls == [("position", 45.0, MotorMoveDirection.COUNTERCLOCKWISE)]
    assert command.output_value("Position") == 45.0
    assert command.output_value("Stable") == 1.0


def test_flow_waits_until_actual_is_within_configured_tolerance(monkeypatch, qapp, engine):
    pending = SimpleNamespace(flow_actual={2: 3.0}, flow_setpoints={2: 5.0})
    reached = SimpleNamespace(flow_actual={2: 4.95}, flow_setpoints={2: 5.0})
    fake = _StateEngine([pending, reached], driver_attribute="connected_mfc_driver")
    _install_engine(
        monkeypatch,
        "stoner_measurement.plugins.command.pressure_set_flow",
        "PressureControllerEngine",
        fake,
    )
    monkeypatch.setattr("stoner_measurement.plugins.command.set_engine_state.time.sleep", lambda _: None)
    command = PressureSetFlowCommand()
    command.channel = 2
    command.setpoint_expr = "requested_flow"
    command.tolerance_expr = "flow_tolerance"
    engine.add_plugin("set_flow", command)
    engine._namespace.update({"requested_flow": 5.0, "flow_tolerance": 0.1})  # noqa: SLF001

    command.execute()

    assert fake.calls == [("flow", 2, 5.0)]
    assert fake.index == 2
    assert command.output_value("Flow") == 4.95
    assert command.output_value("At Target") == 1.0


def test_common_and_specific_configuration_widgets(qapp):
    temperature = SetTemperatureCommand()
    temperature_widget = temperature.config_widget()
    assert temperature_widget.findChild(SISpinBox, "setpoint_expression") is not None
    assert temperature_widget.findChild(QLineEdit, "wait_expression").text() == "True"
    assert temperature_widget.findChild(QSpinBox, "control_loop").value() == 1

    position = SetPositionCommand()
    position_widget = position.config_widget()
    direction = position_widget.findChild(QComboBox, "move_direction")
    assert direction.currentData() is MotorMoveDirection.SHORTEST


@pytest.mark.parametrize(
    ("command", "attribute", "value"),
    [
        (SetTemperatureCommand(), "control_loop", 3),
        (SetPositionCommand(), "direction", MotorMoveDirection.CLOCKWISE),
        (PressureSetFlowCommand(), "channel_expr", "selected_channel"),
    ],
)
def test_specific_settings_round_trip(qapp, command, attribute, value):
    setattr(command, attribute, value)
    command.setpoint_expr = "requested_target"
    command.wait_expr = "wait_for_it"

    restored = BasePlugin.from_json(command.to_json())

    assert getattr(restored, attribute) == value
    assert restored.setpoint_expr == "requested_target"
    assert restored.wait_expr == "wait_for_it"


def test_reported_values_reference_final_snapshot(qapp):
    command = SetFieldCommand()
    command.instance_name = "set_field"
    values = command.reported_values()
    assert values["set_field:Field"] == "set_field.output_value('Field')"
    assert values["set_field:Stable"] == "set_field.output_value('Stable')"


def test_legacy_flow_json_restores_runtime_expressions(qapp):
    data = PressureSetFlowCommand().to_json()
    data.pop("setpoint_expr")
    data.pop("wait_expr")
    data.pop("tolerance_expr")
    data["channel_expr"] = "selected_channel"
    data["flow_expr"] = "base_flow * 2"

    restored = BasePlugin.from_json(data)

    assert isinstance(restored, PressureSetFlowCommand)
    assert restored.channel_expr == "selected_channel"
    assert restored.setpoint_expr == "base_flow * 2"
    assert restored.wait_expr == "True"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
