"""Focused tests for discrete temperature-controller state scans."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan import TemperatureControllerScanPlugin
from stoner_measurement.ui.widgets import SISpinBox


def test_temperature_scan_defaults_to_twenty_minute_stability_timeout(qapp):
    plugin = TemperatureControllerScanPlugin()

    assert plugin.settle_timeout_minutes == 20.0
    assert plugin.settle_timeout == 1200.0


def test_temperature_scan_stability_timeout_round_trips(qapp):
    plugin = TemperatureControllerScanPlugin()
    plugin.settle_timeout_minutes = 45.0

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, TemperatureControllerScanPlugin)
    assert restored.settle_timeout_minutes == 45.0
    assert restored.settle_timeout == 2700.0


def test_temperature_scan_settings_expose_stability_timeout(
    qapp, managed_qt_widget
):
    plugin = TemperatureControllerScanPlugin()
    settings = managed_qt_widget(plugin.config_tabs()[2][1])
    timeout = settings.findChild(
        SISpinBox, "temperature_settle_timeout_minutes"
    )

    assert timeout is not None
    assert timeout.value() == 20.0
    assert timeout.opts["suffix"] == "min"

    timeout.setValue(30.0)

    assert plugin.settle_timeout_minutes == 30.0
    assert plugin.settle_timeout == 1800.0


def test_temperature_scan_records_timeout(monkeypatch, qapp):
    plugin = TemperatureControllerScanPlugin()
    plugin.settle_timeout_minutes = 0.001
    monkeypatch.setattr(plugin, "set_state", lambda _value: None)
    monkeypatch.setattr(plugin, "get_state", lambda: 4.0)
    monkeypatch.setattr(plugin, "is_at_target", lambda: False)
    times = iter((0.0, 1.0))
    monkeypatch.setattr(
        "stoner_measurement.plugins.state_scan.base.time.monotonic",
        lambda: next(times),
    )

    plugin.ramp_to(5.0, poll_interval=0.0)

    assert plugin.timed_out is True
    assert plugin.reported_values()["temperature_controller:Timed Out"] == (
        "temperature_controller.timed_out"
    )


def test_temperature_scan_resets_timeout_on_next_operation(monkeypatch, qapp):
    plugin = TemperatureControllerScanPlugin()
    plugin.timed_out = True
    monkeypatch.setattr(plugin, "set_state", lambda _value: None)
    monkeypatch.setattr(plugin, "is_at_target", lambda: True)
    monkeypatch.setattr(plugin, "get_state", lambda: 5.0)

    plugin.ramp_to(5.0, poll_interval=0.0)

    assert plugin.timed_out is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
