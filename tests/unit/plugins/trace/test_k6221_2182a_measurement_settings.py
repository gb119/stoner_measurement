"""Focused tests for the 6221/2182A trace measurement settings."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QLabel, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    ComplianceMode,
    DigitalFilterType,
    Keithley6221_2182APlugin,
)
from stoner_measurement.ui.widgets import SISpinBox


def _configured_plugin() -> Keithley6221_2182APlugin:
    plugin = Keithley6221_2182APlugin()
    plugin._k6221 = MagicMock()
    plugin._k2182a = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = np.array([1e-3, 2e-3])
    return plugin


def test_measurement_setting_defaults(qapp):
    plugin = Keithley6221_2182APlugin()

    assert plugin._trigger_delay == pytest.approx(0.0)
    assert plugin._line_sync is False
    assert plugin._autozero is True
    assert plugin._filter_type is DigitalFilterType.OFF
    assert plugin._relative_value == pytest.approx(0.0)
    assert plugin._output_tlink == 2
    assert plugin._input_tlink == 1


def test_measurement_settings_round_trip(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._trigger_delay = 0.125
    plugin._line_sync = True
    plugin._autozero = False
    plugin._filter_type = DigitalFilterType.WINDOW
    plugin._filter_count = 17
    plugin._relative_enabled = True
    plugin._relative_value = -2.5e-6

    restored = BasePlugin.from_json(plugin.to_json())

    assert restored._trigger_delay == pytest.approx(0.125)
    assert restored._line_sync is True
    assert restored._autozero is False
    assert restored._filter_type is DigitalFilterType.WINDOW
    assert restored._filter_count == 17
    assert restored._relative_enabled is True
    assert restored._relative_value == pytest.approx(-2.5e-6)


def test_legacy_enabled_filter_restores_as_repeat(qapp):
    data = Keithley6221_2182APlugin().to_json()
    data.pop("filter_type")
    data["filter_enabled"] = True

    restored = BasePlugin.from_json(data)

    assert restored._filter_type is DigitalFilterType.REPEAT


@pytest.mark.parametrize(
    ("filter_type", "enabled", "driver_type"),
    [
        (DigitalFilterType.OFF, False, None),
        (DigitalFilterType.REPEAT, True, "REPEAT"),
        (DigitalFilterType.WINDOW, True, "WINDOW"),
    ],
)
def test_configure_applies_2182a_settings(qapp, filter_type, enabled, driver_type):
    plugin = _configured_plugin()
    plugin._trigger_delay = 0.25
    plugin._line_sync = True
    plugin._autozero = False
    plugin._filter_type = filter_type
    plugin._filter_count = 7
    plugin._relative_enabled = True
    plugin._relative_value = 3e-6

    plugin.configure()

    meter = plugin._k2182a
    meter.set_trigger_delay.assert_called_once_with(0.25)
    meter.set_line_sync_enabled.assert_called_once_with(True)
    meter.set_autozero_enabled.assert_called_once_with(False)
    meter.set_filter_enabled.assert_called_once_with(enabled)
    meter.set_relative_value.assert_called_once_with(3e-6)
    meter.set_relative_enabled.assert_called_once_with(True)
    plugin._k6221.configure_trigger.assert_called_once_with(
        source="TLIN", direction="SOUR", tlink_in=1, tlink_out=2, output="DEL"
    )
    if driver_type is None:
        meter.set_filter_count.assert_not_called()
        meter.set_filter_type.assert_not_called()
    else:
        meter.set_filter_count.assert_called_once_with(7)
        meter.set_filter_type.assert_called_once_with(driver_type)


@pytest.mark.parametrize(
    ("filter_type", "expected"),
    [
        (DigitalFilterType.OFF, 0.25),
        (DigitalFilterType.WINDOW, 0.25),
        (DigitalFilterType.REPEAT, 0.8),
    ],
)
def test_post_sweep_delay_only_counts_repeated_conversions(qapp, filter_type, expected):
    plugin = Keithley6221_2182APlugin()
    plugin._nplc = 10.0
    plugin._filter_type = filter_type
    plugin._filter_count = 4

    assert plugin._post_sweep_delay() == pytest.approx(expected)


def test_measurement_controls_update_plugin_and_use_paired_rows(qapp):
    plugin = Keithley6221_2182APlugin()
    widget = plugin._plugin_config_tabs()

    for row_name in (
        "timing_row",
        "input_row",
        "zero_sync_row",
        "filter_row",
        "relative_row",
        "trigger_lines_row",
    ):
        assert widget.findChild(QWidget, row_name) is not None

    filter_combo = widget.findChild(QComboBox, "digital_filter_type")
    filter_combo.setCurrentIndex(filter_combo.findData(DigitalFilterType.WINDOW))
    widget.findChild(QCheckBox, "autozero").setChecked(False)
    widget.findChild(QCheckBox, "line_sync").setChecked(True)

    assert plugin._filter_type is DigitalFilterType.WINDOW
    assert plugin._autozero is False
    assert plugin._line_sync is True


def test_compliance_row_switches_level_units_and_value(qapp):
    plugin = Keithley6221_2182APlugin()
    widget = plugin._plugin_config_tabs()
    mode_combo = widget.findChild(QComboBox, "compliance_mode")
    level_label = widget.findChild(QLabel, "compliance_level_label")
    level_spin = widget.findChild(SISpinBox, "compliance_level")

    mode_combo.setCurrentIndex(mode_combo.findData(ComplianceMode.RESISTANCE))
    level_spin.setValue(2500.0)

    assert widget.findChild(QWidget, "compliance_group") is not None
    assert level_label.text() == "Level (Ω):"
    assert level_spin.opts["suffix"] == "Ω"
    assert plugin._compliance_resistance == pytest.approx(2500.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
