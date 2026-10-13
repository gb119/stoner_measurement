"""Two-controller sequences retain owned targets, outputs and lifecycle."""

import json
from dataclasses import replace

import pytest

from stoner_measurement.core.sequence_metadata import sequence_json_from_metadata, sequence_metadata
from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.plugins.command.make_safe import MakeSafeCommand
from stoner_measurement.plugins.command.set_temperature import SetTemperatureCommand
from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
from stoner_measurement.plugins.state_scan.temperature_controller import (
    TemperatureControllerScanPlugin,
)
from stoner_measurement.plugins.state_sweep.temperature_controller import (
    TemperatureControllerSweepPlugin,
)
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import ChannelRef, LoopRef


@pytest.fixture
def rig(monkeypatch, qapp):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    service = TemperatureControllerEngine()
    service.set_polling_rate(0)
    monkeypatch.setattr(TemperatureControllerEngine, "_singleton", service)
    for slot in ("primary", "secondary"):
        service.connect_instrument(SimulatedTemperatureController(), controller_id=slot)
    yield service
    service.shutdown()


def test_sequence_round_trip_controls_secondary_and_reports_both(rig, engine):
    command = SetTemperatureCommand()
    command.controller_id = "secondary"
    command.setpoint_expr = "275"
    command.wait_expr = "False"
    monitor = TemperatureMonitorPlugin()
    monitor.control_loops = [1, LoopRef("secondary", 1)]
    monitor.sensor_channels = ["A", ChannelRef("secondary", "A")]
    stored_metadata = json.loads(json.dumps(sequence_metadata([command, monitor])))
    encoded = sequence_json_from_metadata(stored_metadata)
    assert encoded == json.loads(json.dumps(sequence_to_json([command, monitor])))
    restored_command, restored_monitor = sequence_from_json(encoded)
    engine.add_plugin("set_temperature", restored_command)
    engine.add_plugin("temperature_monitor", restored_monitor)
    restored_command.execute()
    rig.read_controller_state()
    assert rig.connected_driver.get_setpoint(1) == 300
    assert rig.controller("secondary").connected_driver.get_setpoint(1) == 275
    assert restored_monitor.setpoint({"controller_id": "secondary", "loop": 1}) == 275
    assert len(restored_monitor._active_channels()) == 2
    namespace = {restored_monitor.instance_name: restored_monitor}
    for expression in restored_monitor.reported_values().values():
        # Generated expressions are the runtime contract under test.
        result = eval(  # nosec B307
            expression, {"__builtins__": {}}, namespace
        )
        assert isinstance(result, float)
    restored_monitor.disconnect()
    assert rig.connected_driver.is_connected
    assert rig.controller("secondary").connected_driver.is_connected


@pytest.mark.parametrize(
    "plugin_class", [TemperatureControllerScanPlugin, TemperatureControllerSweepPlugin]
)
def test_scan_and_sweep_secondary_limits_settings_and_reported_values(
    rig, monkeypatch, plugin_class
):
    secondary = rig.controller("secondary").connected_driver
    caps = replace(secondary.get_capabilities(), min_temperature=20, max_temperature=400)
    monkeypatch.setattr(secondary, "get_capabilities", lambda: caps)
    plugin = plugin_class()
    plugin.controller_id = "secondary"
    plugin.control_loop = 2
    plugin.sensor_channels = ["A", ChannelRef("secondary", "B")]
    restored = plugin_class.from_json(json.loads(json.dumps(plugin.to_json())))
    restored.connect()
    restored.set_state(250)
    assert restored.limits == (20, 400)
    assert secondary.get_setpoint(2) == 250
    assert rig.connected_driver.get_setpoint(2) == 300
    rig.read_controller_state()
    for expression in restored.reported_values().values():
        # Generated expressions are the runtime contract under test.
        eval(  # nosec B307
            expression, {"__builtins__": {}}, {restored.instance_name: restored}
        )
    restored.disconnect()
    assert secondary.is_connected


def test_missing_secondary_never_falls_back_to_primary(rig, engine):
    rig.controller("secondary").disconnect_instrument()
    command = SetTemperatureCommand()
    command.controller_id = "secondary"
    command.setpoint_expr = "150"
    engine.add_plugin("set_temperature", command)
    with pytest.raises(RuntimeError, match="persisted"):
        command.execute()
    assert rig.connected_driver.get_setpoint(1) == 300


def test_make_safe_attempts_peer_after_failure(rig, monkeypatch):
    primary = rig.connected_driver
    secondary = rig.controller("secondary").connected_driver

    def fail(loop, value):
        raise ConnectionError("primary heater range failed")

    monkeypatch.setattr(primary, "set_heater_range", fail)
    with pytest.raises(ExceptionGroup):
        MakeSafeCommand._make_temperature_safe()
    assert secondary.get_heater_range(1) == 0
    assert secondary.get_loop_mode(1).value == "off"
    assert primary.get_loop_mode(1).value == "off"


def test_all_sensors_with_secondary_only_does_not_require_primary(rig):
    rig.disconnect_instrument()
    monitor = TemperatureMonitorPlugin()
    monitor.control_loops = [LoopRef("secondary", 1)]
    monitor.connect()
    reading = monitor.read(force_poll=True)
    assert any("Secondary" in name for name in reading)
    assert rig.connected_driver is None
    monitor.disconnect()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
