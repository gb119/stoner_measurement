"""Tests for conditional loop-control commands."""

from __future__ import annotations

import pytest
from qtpy.QtWidgets import QLineEdit

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import BreakIfCommand, ContinueIfCommand, IfCommand
from stoner_measurement.plugins.state_scan.counter import CounterPlugin


@pytest.mark.parametrize(
    ("command_type", "instance_name", "statement"),
    [
        (BreakIfCommand, "break_if", "break"),
        (ContinueIfCommand, "continue_if", "continue"),
    ],
)
def test_defaults_and_generated_code(qapp, command_type, instance_name, statement):
    command = command_type(condition="counter.index > 4")
    assert command.instance_name == instance_name
    assert command.generate_action_code(1, [], None) == [
        "    if counter.index > 4:",
        f"        {statement}",
        "",
    ]


@pytest.mark.parametrize("command_type", [BreakIfCommand, ContinueIfCommand])
def test_json_round_trip_restores_condition(qapp, command_type):
    command = command_type(condition="temperature.actual > limit")
    restored = BasePlugin.from_json(command.to_json())
    assert isinstance(restored, command_type)
    assert restored.condition == "temperature.actual > limit"


def test_config_widget_edits_condition(qapp, managed_qt_widget):
    command = BreakIfCommand()
    widget = managed_qt_widget(command.config_widget())
    condition_edit = widget.findChild(QLineEdit)

    condition_edit.setText("counter.index == 3")
    condition_edit.editingFinished.emit()

    assert command.condition == "counter.index == 3"


@pytest.mark.parametrize("command_type", [BreakIfCommand, ContinueIfCommand])
def test_position_validation_requires_loop_ancestor(qapp, command_type):
    command = command_type()
    conditional = IfCommand()
    scan = CounterPlugin()

    with pytest.raises(ValueError, match="inside a scan or sweep loop"):
        command.validate_sequence_position([command])
    with pytest.raises(ValueError, match="inside a scan or sweep loop"):
        command.validate_sequence_position([(conditional, [command])])

    command.validate_sequence_position([(scan, [(conditional, [command])])])


def test_sequence_engine_rejects_invalid_loop_control_position(qapp, engine):
    command = BreakIfCommand()
    with pytest.raises(ValueError, match="inside a scan or sweep loop"):
        engine.generate_sequence_code([command], {"break_if": command})


def test_sequence_engine_generates_loop_control_inside_scan(qapp, engine):
    scan = CounterPlugin()
    command = ContinueIfCommand(condition="counter.index < 2")
    code = engine.generate_sequence_code(
        [(scan, [command])],
        {"counter": scan, "continue_if": command},
    )
    assert "if counter.index < 2:" in code
    assert "continue" in code


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
