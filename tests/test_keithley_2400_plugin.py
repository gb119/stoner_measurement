"""Tests for the Keithley2400SweepPlugin (no hardware required)."""

import json
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox, QSpinBox, QTabWidget

from stoner_measurement.instruments.keithley.k2400 import FilterType
from stoner_measurement.plugins.base_plugin import BasePlugin
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


class TestReportedValues:
    """Reported value catalogue entries for buffered 2400 traces."""

    def test_reported_values_include_all_buffered_columns_when_enabled(self):
        plugin = _make_plugin()
        plugin._set_report_channel_statistics(True)

        values = plugin.reported_values()

        prefix = plugin.instance_name
        for column in ("Current", "Voltage", "Resistance", "Power", "Timestamp"):
            assert f"{prefix}:IV {column} mean" in values
            assert f"{prefix}:IV {column} std" in values

    def test_measure_updates_all_column_statistics_when_enabled(self):
        from stoner_measurement.instruments.keithley.k2400 import BufferReading

        plugin = _make_plugin()
        plugin._set_report_channel_statistics(True)
        plugin._sweep_values = (0.001, 0.002)
        buffer_records = (
            BufferReading(voltage=0.1, current=0.001, resistance=100.0, time=1.0, status=0),
            BufferReading(voltage=0.4, current=0.002, resistance=200.0, time=2.0, status=0),
        )

        def _execute(_parameters):
            plugin._last_buffer_raw = buffer_records
            return iter([(0.001, 0.1), (0.002, 0.4)])

        plugin.execute = MagicMock(side_effect=_execute)

        plugin.measure({})

        assert plugin.channel_statistics["IV Current"]["mean"] == pytest.approx(0.0015)
        assert plugin.channel_statistics["IV Voltage"]["mean"] == pytest.approx(0.25)
        assert plugin.channel_statistics["IV Resistance"]["mean"] == pytest.approx(150.0)
        assert plugin.channel_statistics["IV Power"]["mean"] == pytest.approx(0.00045)
        assert plugin.channel_statistics["IV Timestamp"]["mean"] == pytest.approx(1.5)


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
        smu.enable_output.assert_any_call(True)

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

    def test_configure_with_output_disabled_leaves_output_off(self):
        """The legacy opt-out flag should prevent configure() from enabling output."""
        plugin = _make_plugin()
        plugin._enable_output_during_measurement = False
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        smu.enable_output.assert_called_once_with(False)


class TestExecuteLifecycle:
    """Sweep execution should support repeated measurements after one configure call."""

    def test_execute_does_not_toggle_output_after_successful_sweep(self):
        from stoner_measurement.instruments.keithley.k2400 import BufferReading

        plugin = _make_plugin()
        plugin._sweep_values = (0.1, 0.2)
        smu = MagicMock()
        smu.get_buffer_count.return_value = 2
        smu.read_buffer_records.return_value = (
            BufferReading(voltage=1.0, current=0.01, resistance=100.0, time=1.0, status=0),
            BufferReading(voltage=2.0, current=0.02, resistance=100.0, time=2.0, status=0),
        )
        plugin._smu = smu

        points = list(plugin.execute({}))

        assert points == [(0.1, 1.0), (0.2, 2.0)]
        smu.initiate.assert_called_once_with()
        smu.safe_output_off.assert_not_called()

    def test_execute_can_run_successive_sweeps_without_reconfigure(self):
        from stoner_measurement.instruments.keithley.k2400 import BufferReading

        plugin = _make_plugin()
        plugin._sweep_values = (0.1, 0.2)
        smu = MagicMock()
        smu.get_buffer_count.return_value = 2
        smu.read_buffer_records.side_effect = [
            (
                BufferReading(voltage=1.0, current=0.01, resistance=100.0, time=1.0, status=0),
                BufferReading(voltage=2.0, current=0.02, resistance=100.0, time=2.0, status=0),
            ),
            (
                BufferReading(voltage=3.0, current=0.03, resistance=100.0, time=3.0, status=0),
                BufferReading(voltage=4.0, current=0.04, resistance=100.0, time=4.0, status=0),
            ),
        ]
        plugin._smu = smu

        first = list(plugin.execute({}))
        second = list(plugin.execute({}))

        assert first == [(0.1, 1.0), (0.2, 2.0)]
        assert second == [(0.1, 3.0), (0.2, 4.0)]
        assert smu.initiate.call_count == 2
        smu.safe_output_off.assert_not_called()


class TestDisconnectLifecycle:
    """Disconnect should own final output shutdown."""

    def test_disconnect_turns_output_off(self):
        plugin = _make_plugin()
        smu = MagicMock()
        plugin._smu = smu

        plugin.disconnect()

        smu.safe_output_off.assert_called_once_with()


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
