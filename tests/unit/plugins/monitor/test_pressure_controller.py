"""Focused tests for the pressure-controller monitor plugin."""

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
from stoner_measurement.plugins.monitor.pressure_controller import (
    PressureMonitorPlugin,
    _parse_int_list,
)
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
        self.pressure_connect_calls = 0
        self.mfc_connect_calls = 0
        self.poll_result = state

    def get_engine_state(self) -> PressureEngineState:
        return self._state

    def read_controller_state(self) -> PressureEngineState | None:
        self.poll_calls += 1
        return self.poll_result

    def connect_preferred_driver(self) -> None:
        self.pressure_connect_calls += 1
        self.connected_driver = SimpleNamespace()

    def connect_preferred_mfc_driver(self) -> None:
        self.mfc_connect_calls += 1
        self.connected_mfc_driver = SimpleNamespace()


def _make_plugin(engine: _FakeEngine, monkeypatch) -> PressureMonitorPlugin:
    monkeypatch.setattr(
        pressure_module,
        "PressureControllerEngine",
        type("_FakePCE", (), {"instance": staticmethod(lambda: engine)}),
    )
    return PressureMonitorPlugin()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("   ", None),
        ("1, 2, 2, 0, -4, invalid, 3", [1, 2, 3]),
        ("invalid, 0", None),
    ],
)
def test_parse_int_list_filters_invalid_duplicate_and_nonpositive_channels(text, expected):
    assert _parse_int_list(text) == expected


def test_pressure_monitor_identity_and_catalog(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    assert plugin.name == "Pressure Monitor"
    assert plugin.plugin_type == "monitor"
    assert plugin.controller_features == frozenset({"pressure"})
    assert plugin.quantity_names == [
        "pressure_1",
        "pressure_2",
        "gauge_enabled_1",
        "gauge_enabled_2",
        "flow_setpoint_1",
        "flow_setpoint_2",
        "flow_actual_1",
        "flow_actual_2",
        "target_pressure_1",
        "target_pressure_2",
    ]


def test_units_follow_pressure_and_flow_units(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)

    assert plugin.units == {
        "pressure_1": "mbar",
        "pressure_2": "mbar",
        "gauge_enabled_1": "",
        "gauge_enabled_2": "",
        "flow_setpoint_1": "sccm",
        "flow_setpoint_2": "sccm",
        "flow_actual_1": "sccm",
        "flow_actual_2": "sccm",
        "target_pressure_1": "mbar",
        "target_pressure_2": "mbar",
    }


def test_explicit_channels_and_report_flags_control_catalog(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    plugin.pressure_channels = [2]
    plugin.mfc_channels = [1]
    plugin.report_pressures = False
    plugin.report_flow_actual = False
    plugin.report_target_pressures = False

    assert plugin.quantity_names == ["gauge_enabled_2", "flow_setpoint_1"]
    assert plugin.units == {"gauge_enabled_2": "", "flow_setpoint_1": "sccm"}


def test_empty_state_has_no_implicit_channels(monkeypatch, qapp):
    state = _make_state()
    state.readings.clear()
    state.flow_actual.clear()
    state.flow_setpoints.clear()
    plugin = _make_plugin(_FakeEngine(state), monkeypatch)

    assert plugin.quantity_names == []


def test_read_returns_values_and_nan_for_missing_channels(monkeypatch, qapp):
    state = _make_state()
    state.readings.pop(2)
    state.gauge_channel_enabled.pop(2)
    plugin = _make_plugin(_FakeEngine(state), monkeypatch)
    plugin.pressure_channels = [1, 2]
    plugin.mfc_channels = [1, 3]

    reading = plugin.read()

    assert reading["pressure_1"] == pytest.approx(1.0e-3)
    assert reading["gauge_enabled_1"] == 1.0
    assert math.isnan(reading["pressure_2"])
    assert math.isnan(reading["gauge_enabled_2"])
    assert math.isnan(reading["flow_setpoint_3"])
    assert math.isnan(reading["flow_actual_3"])
    assert math.isnan(reading["target_pressure_3"])
    assert plugin.last_reading == reading


@pytest.mark.parametrize("plugin_setting", [False, True])
def test_force_poll_can_be_requested_per_read_or_by_configuration(
    monkeypatch, qapp, plugin_setting
):
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.force_fresh_poll = plugin_setting

    plugin.read(force_poll=not plugin_setting)

    assert engine.poll_calls == 1


def test_force_poll_falls_back_to_cached_state_when_driver_returns_none(monkeypatch, qapp):
    engine = _FakeEngine(_make_state())
    engine.poll_result = None
    plugin = _make_plugin(engine, monkeypatch)

    assert plugin.read(force_poll=True)["pressure_1"] == pytest.approx(1.0e-3)


def test_connect_restores_preferred_drivers_and_disconnect_stops_timer(monkeypatch, qapp):
    engine = _FakeEngine(_make_state())
    engine.connected_driver = None
    engine.connected_mfc_driver = None
    engine.preferred_driver_name = "preferred pressure"
    engine.preferred_mfc_driver_name = "preferred mfc"
    plugin = _make_plugin(engine, monkeypatch)

    plugin.connect()

    assert engine.pressure_connect_calls == 1
    assert engine.mfc_connect_calls == 1
    assert plugin._timer.isActive() is True  # noqa: SLF001

    plugin.disconnect()
    assert plugin._timer.isActive() is False  # noqa: SLF001


def test_connect_rejects_absent_controllers(monkeypatch, qapp):
    engine = _FakeEngine(_make_state())
    engine.connected_driver = None
    engine.connected_mfc_driver = None
    plugin = _make_plugin(engine, monkeypatch)

    with pytest.raises(RuntimeError, match="No pressure controller"):
        plugin.connect()


def test_reported_values_use_instance_name_and_catalog(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    plugin.instance_name = "vacuum"
    plugin.pressure_channels = [1]
    plugin.mfc_channels = []

    assert plugin.reported_values() == {
        "vacuum:Pressure 1": "vacuum.last_reading['pressure_1']",
        "vacuum:Gauge Enabled 1": "vacuum.last_reading['gauge_enabled_1']",
    }


def test_json_round_trip_restores_channel_and_report_configuration(monkeypatch, qapp):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    plugin.pressure_channels = [2]
    plugin.mfc_channels = [1, 3]
    plugin.report_pressures = False
    plugin.report_flow_actual = False
    plugin.force_fresh_poll = True
    data = plugin.to_json()
    restored = _make_plugin(_FakeEngine(_make_state()), monkeypatch)

    restored._restore_from_json(data)  # noqa: SLF001

    assert restored.pressure_channels == [2]
    assert restored.mfc_channels == [1, 3]
    assert restored.report_pressures is False
    assert restored.report_flow_actual is False
    assert restored.force_fresh_poll is True


def test_settings_widget_updates_plugin_and_refreshes_catalog(
    monkeypatch, qapp, managed_qt_widget
):
    plugin = _make_plugin(_FakeEngine(_make_state()), monkeypatch)
    refresh_calls = []
    plugin.sequence_engine = SimpleNamespace(
        _rebuild_data_catalogs=lambda: refresh_calls.append("refresh")
    )
    widget = managed_qt_widget(plugin.config_widget())

    widget._pressure_channels_edit.setText("2, 4, invalid")  # noqa: SLF001
    widget._pressure_channels_edit.editingFinished.emit()  # noqa: SLF001
    widget._mfc_channels_edit.setText("1, 3")  # noqa: SLF001
    widget._mfc_channels_edit.editingFinished.emit()  # noqa: SLF001
    widget._cb_pressures.setChecked(False)  # noqa: SLF001
    widget._cb_flow_actual.setChecked(False)  # noqa: SLF001
    widget._cb_force_poll.setChecked(True)  # noqa: SLF001

    assert plugin.pressure_channels == [2, 4]
    assert plugin.mfc_channels == [1, 3]
    assert plugin.report_pressures is False
    assert plugin.report_flow_actual is False
    assert plugin.force_fresh_poll is True
    assert len(refresh_calls) == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
