"""Controller failures must abort target waits without accepting cached success."""

from types import SimpleNamespace

import pytest

from stoner_measurement.core.controller_polling import raise_for_controller_failure
from stoner_measurement.plugins.command import (
    SetFieldCommand,
    SetPositionCommand,
    SetTemperatureCommand,
)
from stoner_measurement.plugins.command.make_safe import MakeSafeCommand
from stoner_measurement.plugins.command.pressure_set_flow import PressureSetFlowCommand
from stoner_measurement.plugins.state_scan import (
    MagnetControllerScanPlugin,
    MotorControllerScanPlugin,
    TemperatureControllerScanPlugin,
)
from stoner_measurement.plugins.state_sweep import (
    MagnetControllerSweepPlugin,
    MotorControllerSweepPlugin,
    TemperatureControllerSweepPlugin,
)


@pytest.mark.parametrize("command_class", [SetFieldCommand, SetPositionCommand, SetTemperatureCommand,
                                           PressureSetFlowCommand])
@pytest.mark.parametrize("status", ["error", "disconnected", "stopped"])
@pytest.mark.parametrize("during_wait", [False, True])
def test_commands_abort_failed_snapshot(command_class, status, during_wait, monkeypatch, qapp):
    failed = SimpleNamespace(engine_status=status)
    healthy = SimpleNamespace(engine_status="polling")
    engine = SimpleNamespace(get_engine_state=lambda: failed)
    engine._state_updates = SimpleNamespace(revision=0, wait=lambda *args: True)
    command = command_class()
    monkeypatch.setattr(command, "_ensure_engine", lambda: engine)
    monkeypatch.setattr(command, "_set_target", lambda *args: None)
    monkeypatch.setattr(command, "_read_state", lambda *args: healthy if during_wait else failed)
    monkeypatch.setattr(command, "_target_reached", lambda *args: False)
    monkeypatch.setattr(command, "eval_float", lambda *args: 1)
    monkeypatch.setattr(command, "eval", lambda *args: True)
    command._final_values = {"previous success": 1}
    with pytest.raises(RuntimeError, match=f"is {status}"):
        command.execute()
    assert command._final_values == {}
    assert not command.timed_out


@pytest.mark.parametrize("plugin_class", [TemperatureControllerScanPlugin, MagnetControllerScanPlugin,
                                         MotorControllerScanPlugin, TemperatureControllerSweepPlugin,
                                         MagnetControllerSweepPlugin, MotorControllerSweepPlugin])
def test_scans_and_sweeps_abort_before_accepting_target(plugin_class, monkeypatch, qapp):
    controller = SimpleNamespace(
        connected_driver=None, get_limits=lambda: None,
        get_engine_state=lambda: SimpleNamespace(engine_status="error", reading=None)
    )
    plugin = plugin_class()
    monkeypatch.setattr(plugin, "_engine", lambda: controller)
    monkeypatch.setattr(plugin, "set_state", lambda value: None)
    monkeypatch.setattr(plugin, "is_at_target", lambda: True)
    with pytest.raises(RuntimeError, match="is error"):
        if isinstance(plugin, (TemperatureControllerScanPlugin, MagnetControllerScanPlugin, MotorControllerScanPlugin)):
            plugin.ramp_to(1)
        else:
            next(plugin)


def test_temperature_slot_health_is_independent():
    snapshot = SimpleNamespace(engine_status="error", controller_statuses={"primary": "polling", "secondary": "error"})
    raise_for_controller_failure(snapshot, controller_id="primary")
    with pytest.raises(RuntimeError, match="is error"):
        raise_for_controller_failure(snapshot, controller_id="secondary")


def test_failed_connection_clears_previous_command_outputs(monkeypatch, qapp):
    command = SetFieldCommand()
    command._final_values = {"Field": 1}
    monkeypatch.setattr(command, "eval_float", lambda *args: 1)
    monkeypatch.setattr(command, "eval", lambda *args: True)

    def fail():
        raise ConnectionError("controller unavailable")

    monkeypatch.setattr(command, "_ensure_engine", fail)
    with pytest.raises(ConnectionError, match="unavailable"):
        command.execute()
    assert command._final_values == {}


def test_make_safe_failure_never_switches_heater_off(monkeypatch, qapp):
    heater_calls = []
    engine = SimpleNamespace(
        connected_driver=object(), go_to_zero=lambda: None,
        read_controller_state=lambda: None,
        get_engine_state=lambda: SimpleNamespace(engine_status="error", at_target=True),
        heater_off=lambda: heater_calls.append(True),
    )
    monkeypatch.setattr("stoner_measurement.plugins.command.make_safe.MagnetControllerEngine.instance", lambda: engine)
    with pytest.raises(RuntimeError, match="is error"):
        MakeSafeCommand()._make_magnet_safe()
    assert not heater_calls


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
