"""Unsupported loop telemetry must not interrupt temperature monitoring."""

import pytest

from stoner_measurement.instruments.lakeshore import Lakeshore340
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.types import EngineStatus


@pytest.fixture
def rig(qapp, monkeypatch):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    engine = TemperatureControllerEngine()
    engine.set_polling_rate(0)
    driver = Lakeshore340(NullTransport())
    units = {1: 1, 2: 1}

    def query(command, **kwargs):
        if command.startswith("KRDG?"):
            return "4.2"
        if command.startswith("RDGST?"):
            return "0"
        if command.startswith("CSET?"):
            return f"A,{units[int(command.split()[-1])]},{units.get('enabled', 1)},0"
        if command.startswith("SETP?"):
            return "4.2"
        if command.startswith("CMODE?"):
            return "1"
        if command in ("HTR?", "AOUT? 2", "RANGE?"):
            return "0"
        raise AssertionError(command)

    monkeypatch.setattr(driver, "query", query)
    engine._driver = driver
    yield engine, driver, units
    engine._driver = None
    engine.shutdown()


@pytest.mark.parametrize("slot", ["primary", "secondary"])
@pytest.mark.parametrize("enabled", [0, 1])
def test_sensor_unit_loop_preserves_monitoring_and_recovers(rig, slot, enabled):
    engine, driver, units = rig
    session = engine.controller(slot)
    if slot == "secondary":
        engine._driver = None
        session._driver = driver
    try:
        assert engine.read_controller_state().for_controller(slot).setpoints == {1: 4.2, 2: 4.2}
        session._stable[1] = True
        units[1] = 3
        units["enabled"] = enabled
        for _ in range(2):
            state = engine.read_controller_state().for_controller(slot)
            assert state.readings["A"].value == 4.2
            assert state.readings["B"].value == 4.2
            assert state.setpoints == ({2: 4.2} if enabled else {})
            assert state.heater_outputs == ({1: 0, 2: 0} if enabled else {})
            assert not state.stable.get(1, False)
            assert 1 not in state.stability_diagnostics
            assert 1 not in session._target_setpoints
            assert session.status is EngineStatus.POLLING
        assert session.get_loop_settings(1) is None
        units[1] = 1
        units["enabled"] = 1
        assert engine.read_controller_state().for_controller(slot).setpoints[1] == 4.2
    finally:
        session._driver = None


@pytest.mark.parametrize("method", ["get_heater_output", "get_loop_mode", "get_input_channel"])
def test_other_unsupported_loop_fields_preserve_readings(rig, monkeypatch, method):
    engine, driver, _ = rig

    def unsupported(loop):
        raise NotImplementedError("optional telemetry")

    monkeypatch.setattr(driver, method, unsupported)
    assert engine.read_controller_state().readings["A"].value == 4.2


def test_connection_failure_still_invalidates_snapshot(rig, monkeypatch):
    engine, driver, _ = rig

    def disconnected(loop):
        raise ConnectionError("lost connection")

    monkeypatch.setattr(driver, "get_setpoint", disconnected)
    assert not engine.read_controller_state().readings
    assert engine.status is EngineStatus.ERROR
    assert not engine.get_engine_state().readings


def test_off_loops_only_query_enable_and_sensor_readings(rig, monkeypatch):
    engine, driver, units = rig
    units["enabled"] = 0
    commands = []
    query = driver.query

    def record(command, **kwargs):
        commands.append(command)
        return query(command, **kwargs)

    monkeypatch.setattr(driver, "query", record)
    state = engine.read_controller_state()
    assert state.readings["A"].value == 4.2
    assert not state.setpoints
    assert [command for command in commands if not command.startswith(("KRDG?", "RDGST?"))] == [
        "CSET? 1", "CSET? 2",
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
