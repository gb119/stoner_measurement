"""Tests for MakeSafeCommand."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QCheckBox

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.instruments.temperature_controller import ControlMode
from stoner_measurement.plugins.command.make_safe import MakeSafeCommand
from stoner_measurement.plugins.trace.dummy import DummyPlugin


def test_defaults_json_and_widget(qapp):
    command = MakeSafeCommand()
    assert (command.temperature, command.magnet, command.motor) == (True, True, True)
    widget = command.config_widget()
    checks = widget.findChildren(QCheckBox)
    for check in checks:
        check.setChecked(False)
    restored = MakeSafeCommand.from_json(command.to_json())
    assert not any((restored.temperature, restored.magnet, restored.motor, restored.always_make_safe))


def test_execute_makes_selected_controllers_safe(monkeypatch, qapp):
    temperature_calls = []
    temp_engine = SimpleNamespace(
        connected_driver=SimpleNamespace(
            get_capabilities=lambda: SimpleNamespace(
                num_loops=2, has_gas_auto_mode=True, has_cryogen_control=True
            )
        ),
        set_manual_heater_output=lambda *args: temperature_calls.append(("output", *args)),
        set_heater_range=lambda *args: temperature_calls.append(("range", *args)),
        set_loop_mode=lambda *args: temperature_calls.append(("mode", *args)),
        set_gas_auto=lambda value: temperature_calls.append(("gas_auto", value)),
        set_needle_valve=lambda value: temperature_calls.append(("needle", value)),
    )
    magnet_calls = []
    magnet_engine = SimpleNamespace(
        connected_driver=object(),
        go_to_zero=lambda: magnet_calls.append("zero"),
        read_controller_state=lambda: SimpleNamespace(at_target=True),
        heater_off=lambda: magnet_calls.append("heater_off"),
    )
    motor_calls = []
    motor_engine = SimpleNamespace(move_home=motor_calls.append)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.make_safe.TemperatureControllerEngine.instance",
        lambda: temp_engine,
    )
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.make_safe.MagnetControllerEngine.instance",
        lambda: magnet_engine,
    )
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.make_safe.MotorControllerEngine.instance",
        lambda: motor_engine,
    )

    MakeSafeCommand().execute()

    assert ("output", 1, 0.0) in temperature_calls
    assert ("range", 2, 0) in temperature_calls
    assert ("mode", 1, ControlMode.OFF) in temperature_calls
    assert temperature_calls.index(("needle", 0.0)) < temperature_calls.index(
        ("mode", 1, ControlMode.OFF)
    )
    assert magnet_calls == ["zero", "heater_off"]
    assert motor_calls == [MotorMoveDirection.SHORTEST]


def test_always_make_safe_precedes_lifecycle_disconnect(qapp, engine):
    command = MakeSafeCommand()
    command.always_make_safe = True
    trace = DummyPlugin()
    code = engine.generate_sequence_code(
        ["dummy", "make_safe"], {"dummy": trace, "make_safe": command}
    )
    finally_body = code.split("finally:", maxsplit=1)[1]
    assert finally_body.index("make_safe()") < finally_body.index("dummy.disconnect()")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
