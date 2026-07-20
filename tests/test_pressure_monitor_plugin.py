"""Tests for PressureMonitorPlugin."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from stoner_measurement.instruments.pressure_controller import (
    PressureReading,
    PressureStatus,
    PressureUnit,
)
from stoner_measurement.plugins.monitor import pressure_controller as pressure_module
from stoner_measurement.plugins.monitor.pressure_controller import PressureMonitorPlugin
from stoner_measurement.pressure_control.types import (
    PressureEngineReading,
    PressureEngineState,
    PressureEngineStatus,
)


def _make_state() -> PressureEngineState:
    reading = PressureEngineReading(
        timestamp=datetime.now(tz=UTC),
        readings={
            1: PressureReading(1, 1.0e-3, PressureUnit.MBAR, PressureStatus.OK),
            2: PressureReading(2, 2.0e-3, PressureUnit.MBAR, PressureStatus.OK),
        },
        flow_actual={1: 0.4, 2: 0.7},
        flow_setpoints={1: 0.5, 2: 0.8},
        target_pressures={1: 1.5e-3},
        unit=PressureUnit.MBAR,
        flow_unit="sccm",
    )
    return PressureEngineState(
        reading=reading,
        readings=reading.readings,
        flow_actual=reading.flow_actual,
        flow_setpoints=reading.flow_setpoints,
        target_pressures=reading.target_pressures,
        gauge_channel_enabled={1: True, 2: False},
        engine_status=PressureEngineStatus.POLLING,
        driver_name="SimulatedPressureGaugeController",
        mfc_driver_name="SimulatedMassFlowController",
        unit=PressureUnit.MBAR,
        flow_unit="sccm",
    )


class _FakeEngine:
    def __init__(self, state: PressureEngineState) -> None:
        self.connected_driver = SimpleNamespace()
        self.connected_mfc_driver = SimpleNamespace()
        self.preferred_driver_name = ""
        self.preferred_mfc_driver_name = ""
        self._state = state
        self.poll_calls = 0

    def get_engine_state(self) -> PressureEngineState:
        return self._state

    def read_controller_state(self) -> PressureEngineState:
        self.poll_calls += 1
        return self._state


def _make_plugin(engine: _FakeEngine, monkeypatch) -> PressureMonitorPlugin:
    monkeypatch.setattr(
        pressure_module,
        "PressureControllerEngine",
        type("_FakePCE", (), {"instance": staticmethod(lambda: engine)}),
    )
    return PressureMonitorPlugin()


def test_pressure_monitor_identity(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    assert plugin.name == "Pressure Monitor"
    assert plugin.plugin_type == "monitor"
    assert plugin.controller_features == frozenset({"pressure"})


def test_pressure_monitor_quantity_names(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    names = plugin.quantity_names
    assert "pressure_1" in names
    assert "gauge_enabled_2" in names
    assert "flow_setpoint_1" in names
    assert "flow_actual_2" in names
    assert "target_pressure_1" in names


def test_pressure_monitor_read(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    reading = plugin.read()
    assert reading["pressure_1"] == pytest.approx(1.0e-3)
    assert reading["gauge_enabled_1"] == 1.0
    assert reading["gauge_enabled_2"] == 0.0
    assert reading["flow_setpoint_1"] == pytest.approx(0.5)
    assert reading["flow_actual_2"] == pytest.approx(0.7)
    assert reading["target_pressure_1"] == pytest.approx(1.5e-3)


def test_pressure_monitor_read_missing_values_are_nan(monkeypatch, qapp):
    state = _make_state()
    state.readings.pop(2)
    state.gauge_channel_enabled.pop(2)
    plugin = _make_plugin(_FakeEngine(state), monkeypatch)
    plugin.pressure_channels = [2]
    reading = plugin.read()
    assert math.isnan(reading["pressure_2"])
    assert math.isnan(reading["gauge_enabled_2"])


def test_pressure_monitor_force_poll(monkeypatch, qapp):
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.read(force_poll=True)
    assert engine.poll_calls == 1
