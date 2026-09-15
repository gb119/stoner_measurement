"""Tests for the Run Again sequence command."""

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.core.serializer import (
    rename_identifier_references,
    sequence_from_json,
    sequence_to_json,
)
from stoner_measurement.plugins.command import RunAgainCommand, WaitCommand
from stoner_measurement.plugins.trace import DummyPlugin


def _engine_with_steps(engine: SequenceEngine, *plugins):
    engine.update_step_plugin_catalog(list(plugins))
    for plugin in plugins:
        plugin.sequence_engine = engine
    return engine


def test_widget_lists_other_steps_and_updates_options(qapp, engine, managed_qt_widget):
    target = WaitCommand()
    target.instance_name = "pause"
    command = RunAgainCommand()
    _engine_with_steps(engine, target, command)

    widget = managed_qt_widget(command.config_widget())
    combo = widget.findChild(QComboBox, "run_again_target")
    reconnect = widget.findChild(QCheckBox, "reconnect_and_configure")

    assert combo.count() == 1
    assert combo.itemData(0) == "pause"
    assert command.target_step == "pause"
    reconnect.setChecked(True)
    assert command.reconnect_and_configure is True


def test_generated_code_repeats_command_action(qapp, engine):
    target = WaitCommand()
    target.instance_name = "pause"
    command = RunAgainCommand()
    command.target_step = "pause"
    _engine_with_steps(engine, target, command)

    code = engine.generate_sequence_code([target, command], {})

    assert code.count("pause()") == 2


def test_generated_code_repeats_measurement_with_optional_setup(qapp, engine):
    target = DummyPlugin()
    target.instance_name = "measurement"
    command = RunAgainCommand()
    command.target_step = "measurement"
    command.reconnect_and_configure = True
    _engine_with_steps(engine, target, command)

    code = engine.generate_sequence_code([target, command], {})

    assert code.count("measurement.measure({})") == 2
    assert code.count("measurement.connect()") == 2
    assert code.count("measurement.configure()") == 2
    assert code.count("measurement.require_ready()") == 1


def test_generated_code_checks_readiness_without_reconnection(qapp, engine):
    target = DummyPlugin()
    target.instance_name = "measurement"
    command = RunAgainCommand()
    command.target_step = "measurement"
    _engine_with_steps(engine, target, command)

    code = engine.generate_sequence_code([target, command], {})

    assert code.count("measurement.require_ready()") == 2


def test_configuration_round_trip_and_rename(qapp):
    target = WaitCommand()
    target.instance_name = "before"
    command = RunAgainCommand()
    command.target_step = "before"
    command.reconnect_and_configure = True

    saved = sequence_to_json([target, command])
    restored = sequence_from_json(saved)[1]
    renamed = rename_identifier_references(saved, "before", "after")
    renamed_command = sequence_from_json(renamed)[1]

    assert isinstance(restored, RunAgainCommand)
    assert restored.target_step == "before"
    assert restored.reconnect_and_configure is True
    assert renamed_command.target_step == "after"


def test_missing_target_is_reported_during_generation(qapp, engine):
    command = RunAgainCommand()
    command.target_step = "deleted"
    _engine_with_steps(engine, command)

    with pytest.raises(RuntimeError, match="not present"):
        engine.generate_sequence_code([command], {})


def test_repeats_a_container_with_its_nested_steps(qapp, engine):
    from stoner_measurement.plugins.command import IfCommand

    condition = IfCommand(condition="repeat_enabled")
    condition.instance_name = "conditional"
    target = WaitCommand()
    target.instance_name = "pause"
    command = RunAgainCommand()
    command.target_step = "conditional"
    _engine_with_steps(engine, condition, target, command)

    code = engine.generate_sequence_code([(condition, [target]), command], {})

    assert code.count("if repeat_enabled:") == 2
    assert code.count("pause()") == 2


def test_recursive_selection_is_rejected(qapp, engine):
    command = RunAgainCommand()
    command.target_step = "run_again"
    _engine_with_steps(engine, command)

    with pytest.raises(RuntimeError, match="recursive cycle"):
        engine.generate_sequence_code([command], {})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
