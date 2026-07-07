"""Tests for MagneticFieldMonitorPlugin."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from stoner_measurement.instruments.magnet_controller import MagnetState
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
)
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.monitor import magnet_controller as mc_module
from stoner_measurement.plugins.monitor.magnet_controller import (
    MagneticFieldMonitorPlugin,
)


def _make_state() -> MagnetEngineState:
    """Construct a representative magnet engine state for tests."""
    return MagnetEngineState(
        reading=MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=1.25,
            current=10.0,
            voltage=2.5,
            heater_on=True,
            state=MagnetState.AT_TARGET,
            at_target=True,
            field_rate=0.125,
        ),
        target_field=1.5,
        target_current=12.0,
        ramp_rate_field=0.2,
        ramp_rate_current=1.0,
        magnet_constant=0.125,
        at_target=True,
        stable=False,
        engine_status=MagnetEngineStatus.POLLING,
    )


class _FakeEngine:
    def __init__(self, state: MagnetEngineState | None = None) -> None:
        self.connected_driver = SimpleNamespace()
        self.connect_calls = 0
        self.poll_calls = 0
        self._state = state or MagnetEngineState(
            engine_status=MagnetEngineStatus.DISCONNECTED
        )

    def connect_preferred_driver(self) -> None:
        """Simulate reconnecting via persisted settings."""
        self.connect_calls += 1
        if self.connected_driver is None:
            raise RuntimeError("No magnet controller is connected.")

    def get_engine_state(self) -> MagnetEngineState:
        """Return the cached engine state."""
        return self._state

    def read_controller_state(self) -> MagnetEngineState:
        """Simulate a controller read and count how many polls occur."""
        self.poll_calls += 1
        return self._state


class _FakeSequenceEngine:
    def __init__(self) -> None:
        self.rebuild_calls = 0

    def _rebuild_data_catalogs(self) -> None:
        self.rebuild_calls += 1


def _make_plugin(engine: _FakeEngine, monkeypatch) -> MagneticFieldMonitorPlugin:
    """Create a plugin instance using a patched fake engine."""
    monkeypatch.setattr(
        mc_module,
        "MagnetControllerEngine",
        type("_FakeMCE", (), {"instance": staticmethod(lambda: engine)}),
    )
    return MagneticFieldMonitorPlugin()


def test_plugin_name():
    """Plugin exposes the expected display name."""
    plugin = MagneticFieldMonitorPlugin()
    assert plugin.name == "Magnetic Field Monitor"


def test_plugin_type():
    """Plugin identifies itself as a monitor plugin."""
    plugin = MagneticFieldMonitorPlugin()
    assert plugin.plugin_type == "monitor"


def test_quantity_names_with_all_parameters(monkeypatch):
    """All enabled outputs appear in quantity_names."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    names = plugin.quantity_names
    assert "field" in names
    assert "target_field" in names
    assert "current" in names
    assert "voltage" in names
    assert "field_rate" in names
    assert "target_field_rate" in names
    assert "heater" in names
    assert "at_target" in names
    assert "stable" in names


def test_quantity_names_filtered_by_flags(monkeypatch):
    """Disabled outputs are omitted from quantity_names."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_voltage = False
    plugin.report_heater = False
    plugin.report_stability = False

    names = plugin.quantity_names
    assert "voltage" not in names
    assert "heater" not in names
    assert "stable" not in names
    assert "field" in names
    assert "current" in names


def test_units_map(monkeypatch):
    """Units are reported correctly for enabled outputs."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    units = plugin.units
    assert units["field"] == "T"
    assert units["target_field"] == "T"
    assert units["current"] == "A"
    assert units["voltage"] == "V"
    assert units["field_rate"] == "T/min"
    assert units["target_field_rate"] == "T/min"
    assert units["heater"] == ""
    assert units["at_target"] == ""
    assert units["stable"] == ""


def test_read_returns_all_parameters(monkeypatch):
    """read() returns the enabled magnet parameters."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read()
    assert reading["field"] == pytest.approx(1.25)
    assert reading["target_field"] == pytest.approx(1.5)
    assert reading["current"] == pytest.approx(10.0)
    assert reading["voltage"] == pytest.approx(2.5)
    assert reading["field_rate"] == pytest.approx(0.125)
    assert reading["target_field_rate"] == pytest.approx(0.2)
    assert reading["heater"] == 1.0
    assert reading["at_target"] == 1.0
    assert reading["stable"] == 0.0


def test_read_returns_nan_when_values_missing(monkeypatch):
    """Unavailable quantities are returned as NaN where appropriate."""
    state = MagnetEngineState(
        reading=MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=None,
            current=5.0,
            voltage=None,
            heater_on=None,
            state=MagnetState.HOLDING,
            at_target=False,
            field_rate=0.0,
        ),
        target_field=None,
        at_target=False,
        stable=False,
        engine_status=MagnetEngineStatus.POLLING,
    )
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read()
    assert math.isnan(reading["field"])
    assert math.isnan(reading["target_field"])
    assert math.isnan(reading["voltage"])
    assert math.isnan(reading["heater"])


def test_read_caches_last_reading(monkeypatch):
    """The last_reading cache is updated after a read."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    plugin.read()
    assert "field" in plugin.last_reading


def test_read_force_poll_triggers_engine_poll(monkeypatch):
    """Explicit force_poll=True triggers a fresh engine poll."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    assert engine.poll_calls == 0
    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    assert reading["field"] == pytest.approx(1.25)


def test_read_force_fresh_poll_setting_triggers_engine_poll(monkeypatch):
    """Persistent force_fresh_poll setting triggers a fresh engine poll."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.force_fresh_poll = True

    assert engine.poll_calls == 0
    plugin.read()
    assert engine.poll_calls == 1


def test_read_no_force_poll_does_not_trigger_engine_poll(monkeypatch):
    """Default reads use the cached engine state."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    plugin.read()
    assert engine.poll_calls == 0


def test_read_force_poll_falls_back_to_cached_state_when_poll_returns_none(monkeypatch):
    """Forced reads fall back to cached state if the immediate poll fails."""
    engine = _FakeEngine(_make_state())

    def _returning_none():
        engine.poll_calls += 1

    engine.read_controller_state = _returning_none  # type: ignore[method-assign]
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    assert reading["field"] == pytest.approx(1.25)


def test_accessor_methods(monkeypatch):
    """Accessor methods expose the current magnet state."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    assert plugin.field() == pytest.approx(1.25)
    assert plugin.target_field() == pytest.approx(1.5)
    assert plugin.current() == pytest.approx(10.0)
    assert plugin.voltage() == pytest.approx(2.5)
    assert plugin.field_rate() == pytest.approx(0.125)
    assert plugin.target_field_rate() == pytest.approx(0.2)
    assert plugin.heater() == 1.0
    assert plugin.at_target() == 1.0
    assert plugin.stable() == 0.0


def test_accessor_methods_return_nan_when_unavailable(monkeypatch):
    """Accessor methods return NaN for unavailable optional quantities."""
    state = MagnetEngineState(
        reading=MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=None,
            current=5.0,
            voltage=None,
            heater_on=None,
            state=MagnetState.HOLDING,
            at_target=False,
            field_rate=0.0,
        ),
        target_field=None,
        at_target=False,
        stable=False,
        engine_status=MagnetEngineStatus.POLLING,
    )
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)

    assert math.isnan(plugin.field())
    assert math.isnan(plugin.target_field())
    assert math.isnan(plugin.voltage())
    assert math.isnan(plugin.heater())
    assert plugin.at_target() == 0.0
    assert plugin.stable() == 0.0


def test_connect_uses_existing_engine_connection(monkeypatch):
    """connect() reuses an existing engine connection."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.connect()
    plugin.disconnect()


def test_connect_raises_without_connected_controller(monkeypatch):
    """connect() fails when no magnet controller is connected."""
    engine = _FakeEngine()
    engine.connected_driver = None
    plugin = _make_plugin(engine, monkeypatch)

    with pytest.raises(RuntimeError, match="No magnet controller is connected"):
        plugin.connect()


def test_reported_values_all_parameters(monkeypatch):
    """All enabled outputs are exported to the sequence namespace."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    var = plugin.instance_name

    values = plugin.reported_values()
    assert values[f"{var}:Field"] == f"{var}.field()"
    assert values[f"{var}:Target Field"] == f"{var}.target_field()"
    assert values[f"{var}:Current"] == f"{var}.current()"
    assert values[f"{var}:Voltage"] == f"{var}.voltage()"
    assert values[f"{var}:Field Rate"] == f"{var}.field_rate()"
    assert values[f"{var}:Target Field Rate"] == f"{var}.target_field_rate()"
    assert values[f"{var}:Heater"] == f"{var}.heater()"
    assert values[f"{var}:At Target"] == f"{var}.at_target()"
    assert values[f"{var}:Stable"] == f"{var}.stable()"


def test_reported_values_honours_flags(monkeypatch):
    """Disabled outputs are omitted from reported_values()."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_voltage = False
    plugin.report_target_field_rate = False
    plugin.report_heater = False
    var = plugin.instance_name

    values = plugin.reported_values()
    assert f"{var}:Voltage" not in values
    assert f"{var}:Target Field Rate" not in values
    assert f"{var}:Heater" not in values
    assert f"{var}:Field" in values


def test_json_round_trip(monkeypatch):
    """Plugin configuration round-trips through JSON serialisation."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_field = True
    plugin.report_target_field = False
    plugin.report_current = True
    plugin.report_voltage = False
    plugin.report_field_rate = True
    plugin.report_target_field_rate = True
    plugin.report_heater = False
    plugin.report_at_target = True
    plugin.report_stability = False
    plugin.force_fresh_poll = True

    data = plugin.to_json()
    assert data["report_target_field"] is False
    assert data["report_voltage"] is False
    assert data["report_target_field_rate"] is True
    assert data["report_heater"] is False
    assert data["report_stability"] is False
    assert data["force_fresh_poll"] is True

    restored = BasePlugin.from_json(data)
    assert isinstance(restored, MagneticFieldMonitorPlugin)
    assert restored.report_field is True
    assert restored.report_target_field is False
    assert restored.report_current is True
    assert restored.report_voltage is False
    assert restored.report_field_rate is True
    assert restored.report_target_field_rate is True
    assert restored.report_heater is False
    assert restored.report_at_target is True
    assert restored.report_stability is False
    assert restored.force_fresh_poll is True


def test_config_widget_created(monkeypatch):
    """A configuration widget can be constructed successfully."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)

    widget = plugin.config_widget()
    assert widget is not None


def test_config_tabs_has_general_tab(monkeypatch):
    """The default config tabs include the plugin tab and General."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)

    tabs = plugin.config_tabs()
    tab_titles = [title for title, _ in tabs]
    assert tab_titles[0] == "General"
    assert tab_titles[1] == "Magnetic Field Monitor"
    assert "General" in tab_titles
    assert "Magnetic Field Monitor" in tab_titles


def test_widget_rebuilds_catalogs_on_output_settings_change(monkeypatch):
    """Changing widget options triggers catalogue rebuilds."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sequence_engine = _FakeSequenceEngine()
    widget = plugin.config_widget()

    widget._on_field_toggled(False)  # noqa: SLF001
    widget._on_target_field_toggled(False)  # noqa: SLF001
    widget._on_current_toggled(False)  # noqa: SLF001
    widget._on_voltage_toggled(False)  # noqa: SLF001
    widget._on_field_rate_toggled(False)  # noqa: SLF001
    widget._on_target_field_rate_toggled(False)  # noqa: SLF001
    widget._on_heater_toggled(False)  # noqa: SLF001
    widget._on_at_target_toggled(False)  # noqa: SLF001
    widget._on_stability_toggled(False)  # noqa: SLF001
    widget._on_force_poll_toggled(True)  # noqa: SLF001

    assert plugin.sequence_engine.rebuild_calls == 10


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
