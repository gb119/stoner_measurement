"""Tests for the Keithley2400SweepPlugin (no hardware required)."""

import json
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox, QSpinBox, QTabWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.instruments.keithley.k2400 import FilterType
from stoner_measurement.plugins.trace import Keithley2400SweepPlugin, SweepSourceMode
from stoner_measurement.plugins.trace.keithley_2400 import (
    ComplianceMode,
    ConnectionMode,
    RangeMode,
    TerminalMode,
)


def _make_plugin() -> Keithley2400SweepPlugin:
    plugin = Keithley2400SweepPlugin()
    plugin._resource = "GPIB0::24::INSTR"
    plugin.scan_generator.generate = MagicMock(return_value=[0.1, 0.2, 0.3])
    return plugin


class TestJsonRoundTrip:
    """JSON serialisation and restore behaviour."""

    def test_to_json_includes_compliance_keys(self):
        """Serialised state should include resistance-compliance settings."""
        data = _make_plugin().to_json()
        assert "compliance_mode" in data
        assert "compliance_resistance" in data
        assert "source_range_mode" in data
        assert "sense_range_mode" in data
        assert "terminal_mode" in data
        assert "filter_type" in data

    def test_round_trip_restores_resistance_compliance(self):
        """Round-tripping JSON should restore resistance-compliance settings."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.CURRENT
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 2500.0
        plugin._source_range_mode = RangeMode.FIXED
        plugin._source_range = 0.5
        plugin._sense_range_mode = RangeMode.FIXED
        plugin._sense_range = 0.05
        plugin._connection_mode = ConnectionMode.FOUR_WIRE
        plugin._terminal_mode = TerminalMode.REAR
        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley2400SweepPlugin)
        assert restored._source_mode is SweepSourceMode.CURRENT
        assert restored._compliance_mode.value == ComplianceMode.RESISTANCE.value
        assert restored._compliance_resistance == pytest.approx(2500.0)
        assert restored._source_range_mode is RangeMode.FIXED
        assert restored._source_range == pytest.approx(0.5)
        assert restored._sense_range_mode is RangeMode.FIXED
        assert restored._sense_range == pytest.approx(0.05)
        assert restored._connection_mode is ConnectionMode.FOUR_WIRE
        assert restored._terminal_mode is TerminalMode.REAR


class TestDefaults:
    """Default configuration values for the Keithley 2400 sweep plugin."""

    def test_defaults_match_current_sweep_lab_setup(self):
        """Defaults should match the configured current-sweep lab setup."""
        plugin = Keithley2400SweepPlugin()
        assert plugin._source_mode is SweepSourceMode.CURRENT
        assert plugin._compliance_mode is ComplianceMode.FIXED
        assert plugin._compliance == pytest.approx(10.0)
        assert plugin._enable_trigger_out is True
        assert plugin._trigger_out_line == 2
        assert plugin._terminal_mode is TerminalMode.FRONT
        assert plugin._connection_mode is ConnectionMode.FOUR_WIRE
        assert plugin._connection_mode is ConnectionMode.FOUR_WIRE


class TestConfigureComplianceModes:
    """Compliance configuration behaviour during plugin setup."""

    def test_configure_uses_fixed_compliance(self):
        """Fixed compliance mode should program the configured direct limit."""
        plugin = _make_plugin()
        smu = MagicMock()
        plugin._smu = smu
        plugin._compliance_mode = ComplianceMode.FIXED
        plugin._compliance = 0.25

        plugin.configure()

        smu.set_compliance.assert_called_once_with(0.25)

    def test_configure_current_mode_resistance_compliance_uses_max_abs_current(self):
        """Current sweeps should derive voltage compliance from max |I| × R."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.CURRENT
        plugin.scan_generator.generate = MagicMock(return_value=[-0.1, 0.2, -0.3])
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 1000.0
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        smu.set_compliance.assert_called_once_with(pytest.approx(300.0))

    def test_configure_voltage_mode_resistance_compliance_uses_min_nonzero_abs_voltage(self):
        """Voltage sweeps should derive current compliance from min nonzero |V| / R."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.VOLTAGE
        plugin.scan_generator.generate = MagicMock(return_value=[0.0, -2.0, 5.0])
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 1000.0
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        smu.set_compliance.assert_called_once_with(pytest.approx(0.002))

    def test_configure_voltage_mode_resistance_compliance_with_all_zero_points_raises(self):
        """All-zero voltage sweeps cannot define a minimum nonzero resistance threshold."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.VOLTAGE
        plugin.scan_generator.generate = MagicMock(return_value=[0.0, 0.0])
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 1000.0
        plugin._smu = MagicMock()

        with pytest.raises(ValueError):
            plugin.configure()

    def test_configure_applies_advanced_source_sense_options(self):
        """Advanced range, wiring, terminal, and filter settings should be pushed to the driver."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.VOLTAGE
        plugin._source_range_mode = RangeMode.FIXED
        plugin._source_range = 20.0
        plugin._sense_range_mode = RangeMode.FIXED
        plugin._sense_range = 0.01
        plugin._connection_mode = ConnectionMode.FOUR_WIRE
        plugin._terminal_mode = TerminalMode.REAR
        plugin._filter_enabled = True
        plugin._filter_count = 7
        plugin._filter_type = FilterType.MOVING
        plugin._median_filter_enabled = True
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        smu.set_terminal_selection.assert_called_once()
        smu.set_remote_sense.assert_called_once_with(True)
        smu.set_source_autorange.assert_called_once()
        smu.set_source_range.assert_called_once_with(pytest.approx(20.0), smu.set_source_autorange.call_args.args[1])
        smu.set_sense_autorange.assert_called_once()
        smu.set_sense_range.assert_called_once_with(pytest.approx(0.01), smu.set_sense_autorange.call_args.args[1])
        smu.set_filter_enabled.assert_called_once_with(True, smu.set_filter_enabled.call_args.args[1])
        smu.set_filter_count.assert_called_once_with(7, smu.set_filter_count.call_args.args[1])
        smu.set_filter_type.assert_called_once_with(FilterType.MOVING, smu.set_filter_type.call_args.args[1])
        smu.set_median_filter_enabled.assert_called_once_with(True, smu.set_median_filter_enabled.call_args.args[1])


class TestConfigUi:
    """UI structure for the Keithley 2400 trace-plugin configuration."""

    def test_settings_tab_contains_basic_and_advanced_nested_tabs(self, qtbot):
        """Settings should expose nested Basic/Advanced tabs."""
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        settings_widget = tabs[1][1]
        qtbot.addWidget(settings_widget)

        nested_tabs = settings_widget.findChildren(QTabWidget)
        inner_tabs = next(
            tab
            for tab in nested_tabs
            if tab.count() == 2 and tab.tabText(0) == "Basic" and tab.tabText(1) == "Advanced"
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

        advanced_combo_texts = [combo.itemText(0) for combo in advanced_widget.findChildren(QComboBox)]
        assert "Front terminals" in advanced_combo_texts
        assert "Immediate" in advanced_combo_texts
        assert "Repeat" in advanced_combo_texts

        basic_combos = {combo.currentText(): combo for combo in basic_widget.findChildren(QComboBox)}
        assert "Current sweep" in basic_combos
        assert "Fixed limit" in basic_combos

        advanced_combos = {combo.currentText(): combo for combo in advanced_widget.findChildren(QComboBox)}
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
