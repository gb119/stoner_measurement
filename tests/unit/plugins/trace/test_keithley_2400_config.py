"""Configuration layout for the Keithley SourceMeter buffered trace."""

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox, QSpinBox, QTabWidget

from stoner_measurement.plugins.trace.keithley_2400 import (
    ConnectionMode,
    Keithley2400SweepPlugin,
    TerminalMode,
)


def _make_plugin():
    return Keithley2400SweepPlugin()


class TestConfigUi:
    """UI structure for the Keithley 2400 trace-plugin configuration."""

    def test_settings_tab_contains_basic_advanced_and_secondary_tabs(
        self, managed_plugin_config_tabs
    ):
        """Settings should expose the four nested configuration pages."""
        plugin = _make_plugin()
        tabs = managed_plugin_config_tabs(plugin)
        settings_widget = tabs[1][1]

        nested_tabs = settings_widget.findChildren(QTabWidget)
        inner_tabs = next(
            tab
            for tab in nested_tabs
            if tab.count() == 4
            and tab.tabText(0) == "Basic"
            and tab.tabText(1) == "Advanced"
            and tab.tabText(2) == "Secondary nanovoltmeter"
            and tab.tabText(3) == "Electrometer"
        )
        assert inner_tabs is not None

        basic_widget = inner_tabs.widget(0)
        advanced_widget = inner_tabs.widget(1)

        basic_groups = {group.title() for group in basic_widget.findChildren(QGroupBox)}
        assert "Connection" in basic_groups
        assert "Source / Sense" in basic_groups
        assert "Ranges" in basic_groups
        assert "Triggering" not in basic_groups

        advanced_groups = {group.title() for group in advanced_widget.findChildren(QGroupBox)}
        assert "Terminals and Wiring" in advanced_groups
        assert "Triggering" in advanced_groups
        assert "Filtering" in advanced_groups
        assert "Ranges" not in advanced_groups

        basic_combo_texts = [combo.itemText(0) for combo in basic_widget.findChildren(QComboBox)]
        assert "Current sweep" in basic_combo_texts or "Voltage sweep" in basic_combo_texts
        assert "Auto" in basic_combo_texts

        advanced_combo_texts = [
            combo.itemText(0) for combo in advanced_widget.findChildren(QComboBox)
        ]
        assert "Front terminals" in advanced_combo_texts
        assert "Immediate" in advanced_combo_texts
        assert "Repeat" in advanced_combo_texts

        basic_combos = {
            combo.currentText(): combo for combo in basic_widget.findChildren(QComboBox)
        }
        assert "Current sweep" in basic_combos
        assert "Fixed limit" in basic_combos

        advanced_combos = {
            combo.currentText(): combo for combo in advanced_widget.findChildren(QComboBox)
        }
        assert "Front terminals" in advanced_combos
        assert "4-wire remote sense" in advanced_combos
        assert "Immediate" in advanced_combos

        trigger_group = next(
            group
            for group in advanced_widget.findChildren(QGroupBox)
            if group.title() == "Triggering"
        )
        trigger_out_checkbox = trigger_group.findChildren(QCheckBox)[0]
        trigger_out_spinbox = trigger_group.findChildren(QSpinBox)[-1]
        assert trigger_out_checkbox.isChecked() is True
        assert trigger_out_spinbox.value() == 2

        assert plugin._compliance == pytest.approx(10.0)
        assert plugin._enable_trigger_out is True
        assert plugin._trigger_out_line == 2
        assert plugin._terminal_mode is TerminalMode.FRONT
        assert plugin._connection_mode is ConnectionMode.FOUR_WIRE

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
