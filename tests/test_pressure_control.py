"""Focused tests for the pressure controller engine additions."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.simulated import (
    SimulatedMassFlowController,
    SimulatedPressureGaugeController,
)
from stoner_measurement.pressure_control.engine import PressureControllerEngine


@pytest.fixture(autouse=True)
def cleanup_pressure_engine():
    engine = PressureControllerEngine._singleton  # pylint: disable=protected-access
    if engine is not None:
        engine.shutdown()
    yield
    engine = PressureControllerEngine._singleton  # pylint: disable=protected-access
    if engine is not None:
        engine.shutdown()


def test_pressure_engine_reads_pressure_and_flow_state(qapp):
    _ = qapp
    engine = PressureControllerEngine.instance()
    engine.connect_instrument(SimulatedPressureGaugeController())
    engine.connect_mfc_instrument(SimulatedMassFlowController())
    state = engine.read_controller_state()
    assert state is not None
    assert state.readings
    assert state.flow_actual
    assert state.mfc_driver_name == "SimulatedMassFlowController"


def test_pressure_engine_can_toggle_gauge_channel(qapp):
    _ = qapp
    engine = PressureControllerEngine.instance()
    engine.connect_instrument(SimulatedPressureGaugeController())
    engine.set_gauge_channel_enabled(2, False)
    state = engine.read_controller_state()
    assert state is not None
    assert state.gauge_channel_enabled[2] is False
    assert state.readings[2].value is None


def test_pressure_engine_can_set_flow_and_target_pressure(qapp):
    _ = qapp
    engine = PressureControllerEngine.instance()
    engine.connect_mfc_instrument(SimulatedMassFlowController())
    engine.set_flow_rate(1, 1.2)
    engine.set_target_pressure(2, 3.4)
    state = engine.read_controller_state()
    assert state is not None
    assert state.flow_setpoints[1] == pytest.approx(1.2)
    assert state.target_pressures[2] == pytest.approx(3.4)
