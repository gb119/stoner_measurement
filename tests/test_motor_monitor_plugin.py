"""Tests for MotorAngleMonitorPlugin."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
    MotorReading,
)
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.monitor import motor_controller as mc_module
from stoner_measurement.plugins.monitor.motor_controller import (
    MotorAngleMonitorPlugin,
)


def _make_state() -> MotorEngineState:
    """Construct a representative motor engine state for tests."""
    return MotorEngineState(
        reading=MotorReading(
            timestamp=datetime.now(tz=UTC),
            angle=12.5,
            target_angle=15.0,
            moving=True,
            homed=True,
            angular_rate=2.5,
            at_target=True,
        ),
        target_angle=15.0,
        velocity=5.0,
        acceleration=10.0,
        at_target=True,
        stable=False,
        engine_status=MotorEngineStatus.POLLING,
    )


class _FakeEngine:
    def __init__(self, state: MotorEngineState | None = None) -> None:
        self.connected_driver = SimpleNamespace()
        self.poll_calls = 0
        self._state = state or MotorEngineState(
            engine_status=MotorEngineStatus.DISCONNECTED
        )

    def get_engine_state(self) -> MotorEngineState:
        """Return the cached engine state."""
        return self._state

    def read_controller_state(self) -> MotorEngineState:
        """Simulate a controller read and count how many polls occur."""
        self.poll_calls += 1
        return self._state


class _FakeSequenceEngine:
    def __init__(self) -> None:
        self.rebuild_calls = 0

    def _rebuild_data_catalogs(self) -> None:
        self.rebuild_calls += 1


def _make_plugin(engine: _FakeEngine, monkeypatch) -> MotorAngleMonitorPlugin:
    """Create a plugin instance using a patched fake engine."""
    monkeypatch.setattr(
        mc_module,
        "MotorControllerEngine",
        type("_FakeMCE", (), {"instance": staticmethod(lambda: engine)}),
    )
    return MotorAngleMonitorPlugin()


def test_plugin_name():
    """Plugin exposes the expected display name."""
    plugin = MotorAngleMonitorPlugin()
    assert plugin.name == "Motor Angle Monitor"


def test_plugin_type():
    """Plugin identifies itself as a monitor plugin."""
    plugin = MotorAngleMonitorPlugin()
    assert plugin.plugin_type == "monitor"


def test_quantity_names_with_all_parameters(monkeypatch):
    """All enabled outputs appear in quantity_names."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    names = plugin.quantity_names
    assert "angle" in names
    assert "target_angle" in names
    assert "moving" in names
    assert "angular_rate" in names
    assert "at_target" in names
    assert "stable" in names


def test_quantity_names_filtered_by_flags(monkeypatch):
    """Disabled outputs are omitted from quantity_names."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_target_angle = False
    plugin.report_moving = False
    plugin.report_stability = False

    names = plugin.quantity_names
    assert "target_angle" not in names
    assert "moving" not in names
    assert "stable" not in names
    assert "angle" in names
    assert "angular_rate" in names


def test_units_map(monkeypatch):
    """Units are reported correctly for enabled outputs."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    units = plugin.units
    assert units["angle"] == "deg"
    assert units["target_angle"] == "deg"
    assert units["moving"] == ""
    assert units["angular_rate"] == "deg/s"
    assert units["at_target"] == ""
    assert units["stable"] == ""


def test_read_returns_all_parameters(monkeypatch):
    """read() returns the enabled motor parameters."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read()
    assert reading["angle"] == pytest.approx(12.5)
    assert reading["target_angle"] == pytest.approx(15.0)
    assert reading["moving"] == 1.0
    assert reading["angular_rate"] == pytest.approx(2.5)
    assert reading["at_target"] == 1.0
    assert reading["stable"] == 0.0


def test_read_returns_nan_when_values_missing(monkeypatch):
    """Unavailable quantities are returned as NaN where appropriate."""
    state = MotorEngineState(
        reading=MotorReading(
            timestamp=datetime.now(tz=UTC),
            angle=7.5,
            target_angle=None,
            moving=False,
            homed=None,
            angular_rate=0.0,
            at_target=False,
        ),
        target_angle=None,
        at_target=False,
        stable=False,
        engine_status=MotorEngineStatus.POLLING,
    )
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read()
    assert reading["angle"] == pytest.approx(7.5)
    assert math.isnan(reading["target_angle"])
    assert reading["moving"] == 0.0
    assert reading["angular_rate"] == pytest.approx(0.0)
    assert reading["at_target"] == 0.0
    assert reading["stable"] == 0.0


def test_read_caches_last_reading(monkeypatch):
    """The last_reading cache is updated after a read."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    plugin.read()
    assert "angle" in plugin.last_reading


def test_read_force_poll_triggers_engine_poll(monkeypatch):
    """Explicit force_poll=True triggers a fresh engine poll."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    assert engine.poll_calls == 0
    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    assert reading["angle"] == pytest.approx(12.5)


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
        return None

    engine.read_controller_state = _returning_none  # type: ignore[method-assign]
    plugin = _make_plugin(engine, monkeypatch)

    reading = plugin.read(force_poll=True)
    assert engine.poll_calls == 1
    assert reading["angle"] == pytest.approx(12.5)


def test_accessor_methods(monkeypatch):
    """Accessor methods expose the current motor state."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)

    assert plugin.angle() == pytest.approx(12.5)
    assert plugin.target_angle() == pytest.approx(15.0)
    assert plugin.moving() == 1.0
    assert plugin.angular_rate() == pytest.approx(2.5)
    assert plugin.at_target() == 1.0
    assert plugin.stable() == 0.0


def test_accessor_methods_return_nan_when_unavailable(monkeypatch):
    """Accessor methods return NaN for unavailable optional quantities."""
    state = MotorEngineState(
        reading=None,
        target_angle=None,
        at_target=False,
        stable=False,
        engine_status=MotorEngineStatus.POLLING,
    )
    engine = _FakeEngine(state)
    plugin = _make_plugin(engine, monkeypatch)

    assert math.isnan(plugin.angle())
    assert math.isnan(plugin.target_angle())
    assert math.isnan(plugin.moving())
    assert math.isnan(plugin.angular_rate())
    assert plugin.at_target() == 0.0
    assert plugin.stable() == 0.0


def test_connect_uses_existing_engine_connection(monkeypatch):
    """connect() reuses an existing engine connection."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.connect()
    plugin.disconnect()


def test_connect_raises_without_connected_controller(monkeypatch):
    """connect() fails when no motor controller is connected."""
    engine = _FakeEngine()
    engine.connected_driver = None
    plugin = _make_plugin(engine, monkeypatch)

    with pytest.raises(RuntimeError, match="No motor controller is connected"):
        plugin.connect()


def test_reported_values_all_parameters(monkeypatch):
    """All enabled outputs are exported to the sequence namespace."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    var = plugin.instance_name

    values = plugin.reported_values()
    assert values[f"{var}:Angle"] == f"{var}.angle()"
    assert values[f"{var}:Target Angle"] == f"{var}.target_angle()"
    assert values[f"{var}:Moving"] == f"{var}.moving()"
    assert values[f"{var}:Angular Rate"] == f"{var}.angular_rate()"
    assert values[f"{var}:At Target"] == f"{var}.at_target()"
    assert values[f"{var}:Stable"] == f"{var}.stable()"


def test_reported_values_honours_flags(monkeypatch):
    """Disabled outputs are omitted from reported_values()."""
    engine = _FakeEngine(_make_state())
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_target_angle = False
    plugin.report_moving = False
    var = plugin.instance_name

    values = plugin.reported_values()
    assert f"{var}:Target Angle" not in values
    assert f"{var}:Moving" not in values
    assert f"{var}:Angle" in values


def test_json_round_trip(monkeypatch):
    """Plugin configuration round-trips through JSON serialisation."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.report_angle = True
    plugin.report_target_angle = False
    plugin.report_moving = True
    plugin.report_angular_rate = False
    plugin.report_at_target = True
    plugin.report_stability = False
    plugin.force_fresh_poll = True

    data = plugin.to_json()
    assert data["report_target_angle"] is False
    assert data["report_angular_rate"] is False
    assert data["report_stability"] is False
    assert data["force_fresh_poll"] is True

    restored = BasePlugin.from_json(data)
    assert isinstance(restored, MotorAngleMonitorPlugin)
    assert restored.report_angle is True
    assert restored.report_target_angle is False
    assert restored.report_moving is True
    assert restored.report_angular_rate is False
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
    assert "General" in tab_titles
    assert "Motor Angle Monitor" in tab_titles


def test_widget_rebuilds_catalogs_on_output_settings_change(monkeypatch):
    """Changing widget options triggers catalogue rebuilds."""
    engine = _FakeEngine()
    plugin = _make_plugin(engine, monkeypatch)
    plugin.sequence_engine = _FakeSequenceEngine()
    widget = plugin.config_widget()

    widget._on_angle_toggled(False)  # noqa: SLF001
    widget._on_target_angle_toggled(False)  # noqa: SLF001
    widget._on_moving_toggled(False)  # noqa: SLF001
    widget._on_angular_rate_toggled(False)  # noqa: SLF001
    widget._on_at_target_toggled(False)  # noqa: SLF001
    widget._on_stability_toggled(False)  # noqa: SLF001
    widget._on_force_poll_toggled(True)  # noqa: SLF001

    assert plugin.sequence_engine.rebuild_calls == 7


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
