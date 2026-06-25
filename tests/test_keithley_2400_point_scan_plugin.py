"""Tests for the Keithley2400PointScanPlugin (no hardware required)."""

import json
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox, QSpinBox, QTabWidget

from stoner_measurement.instruments.keithley.k2400 import BufferReading, FilterType
from stoner_measurement.instruments.source_meter import SourceMode, TriggerSource
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan.keithley_2400 import (
    ComplianceMode,
    ConnectionMode,
    Keithley2400PointScanPlugin,
    RangeMode,
    SweepSourceMode,
    TerminalMode,
    TriggerRouting,
)


def _make_plugin() -> Keithley2400PointScanPlugin:
    plugin = Keithley2400PointScanPlugin()
    plugin._resource = "GPIB0::24::INSTR"
    plugin.instance_name = "k2400_point"
    return plugin


class TestJsonRoundTrip:
    """JSON serialisation and restore behaviour."""

    def test_to_json_includes_point_scan_keys(self):
        """Serialised state should include point-scan trigger and compliance settings."""
        data = _make_plugin().to_json()
        assert "compliance_mode" in data
        assert "compliance_resistance" in data
        assert "trigger_routing" in data
        assert "source_range_mode" in data
        assert "sense_range_mode" in data
        assert "terminal_mode" in data
        assert "filter_type" in data
        assert "enable_trigger_out" in data

    def test_round_trip_restores_resistance_compliance_and_triggering(self):
        """Round-tripping JSON should restore key point-scan settings."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.CURRENT
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 2500.0
        plugin._trigger_routing = TriggerRouting.TIMER
        plugin._timer_interval = 0.25
        plugin._source_range_mode = RangeMode.FIXED
        plugin._source_range = 0.5
        plugin._sense_range_mode = RangeMode.FIXED
        plugin._sense_range = 0.05
        plugin._connection_mode = ConnectionMode.FOUR_WIRE
        plugin._terminal_mode = TerminalMode.REAR
        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley2400PointScanPlugin)
        assert restored._source_mode is SweepSourceMode.CURRENT
        assert restored._compliance_mode is ComplianceMode.RESISTANCE
        assert restored._compliance_resistance == pytest.approx(2500.0)
        assert restored._trigger_routing is TriggerRouting.TIMER
        assert restored._timer_interval == pytest.approx(0.25)
        assert restored._source_range_mode is RangeMode.FIXED
        assert restored._source_range == pytest.approx(0.5)
        assert restored._sense_range_mode is RangeMode.FIXED
        assert restored._sense_range == pytest.approx(0.05)
        assert restored._connection_mode is ConnectionMode.FOUR_WIRE
        assert restored._terminal_mode is TerminalMode.REAR


class TestDefaults:
    """Default configuration values for the Keithley 2400 point-scan plugin."""

    def test_defaults_match_current_sweep_lab_setup(self):
        """Defaults should mirror the canonical trace-plugin lab setup."""
        plugin = Keithley2400PointScanPlugin()
        assert plugin._source_mode is SweepSourceMode.CURRENT
        assert plugin._compliance_mode is ComplianceMode.FIXED
        assert plugin._compliance == pytest.approx(10.0)
        assert plugin._enable_trigger_out is True
        assert plugin._trigger_out_line == 2
        assert plugin._terminal_mode is TerminalMode.FRONT
        assert plugin._connection_mode is ConnectionMode.FOUR_WIRE


class TestReportedValues:
    """Reported value exposure for sequence collection."""

    def test_reported_values_include_source_and_measured_quantities(self):
        """The plugin should expose source and measured values via reported_values()."""
        plugin = _make_plugin()
        values = plugin.reported_values()

        assert values["k2400_point.source_value"] == "k2400_point.get_state()"
        assert values["k2400_point.voltage"] == "k2400_point._last_voltage"
        assert values["k2400_point.current"] == "k2400_point._last_current"
        assert values["k2400_point.resistance"] == "k2400_point._last_resistance"
        assert values["k2400_point.power"] == "k2400_point._last_power"
        assert values["k2400_point.timestamp"] == "k2400_point._last_timestamp"
        assert values["k2400_point:Current"] == "k2400_point.value"
        assert values["k2400_point:Index"] == "k2400_point.index"


class TestConfigureTriggering:
    """Trigger configuration behavior during plugin setup."""

    def test_configure_bus_trigger_programs_bus_arm_source(self):
        """BUS routing should use immediate trigger config plus BUS arm source override."""
        plugin = _make_plugin()
        plugin._trigger_routing = TriggerRouting.BUS
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        config = smu.configure_trigger_model.call_args.args[0]
        assert config.trigger_source is TriggerSource.IMM
        assert config.arm_source is TriggerSource.IMM
        assert config.trigger_count == 1
        assert config.arm_count == 1
        smu.write.assert_any_call(":ARM:SOUR BUS")

    def test_configure_external_trigger_programs_input_line(self):
        """External routing should configure TLIN arm acceptance and selected input line."""
        plugin = _make_plugin()
        plugin._trigger_routing = TriggerRouting.EXTERNAL
        plugin._trigger_in_line = 3
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        config = smu.configure_trigger_model.call_args.args[0]
        assert config.trigger_source is TriggerSource.IMM
        smu.write.assert_any_call(":ARM:SOUR TLIN")
        smu.write.assert_any_call(":ARM:TCON:DIR ACC")
        smu.write.assert_any_call(":ARM:TCON:ILIN 3")

    def test_configure_timer_trigger_programs_timer_arm_source(self):
        """Timer routing should configure timer arm source and interval."""
        plugin = _make_plugin()
        plugin._trigger_routing = TriggerRouting.TIMER
        plugin._timer_interval = 0.125
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        config = smu.configure_trigger_model.call_args.args[0]
        assert config.trigger_source is TriggerSource.IMM
        smu.write.assert_any_call(":ARM:SOUR TIM")
        smu.write.assert_any_call(":ARM:TIM 0.125")

    def test_configure_trigger_output_enabled_programs_output_line(self):
        """Enabled trigger output should program source direction and output line."""
        plugin = _make_plugin()
        plugin._enable_trigger_out = True
        plugin._trigger_out_line = 2
        smu = MagicMock()
        plugin._smu = smu

        plugin.configure()

        smu.write.assert_any_call(":TRIG:TCON:DIR SOUR")
        smu.write.assert_any_call(":TRIG:TCON:OLIN 2")
        smu.write.assert_any_call(":TRIG:TCON:OUTP DEL")

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
    """UI structure for the Keithley 2400 point-scan configuration."""

    def test_settings_tab_contains_basic_and_advanced_nested_tabs(self, qtbot):
        """Settings should expose nested Basic/Advanced tabs matching the trace plugin layout."""
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


class TestSetState:
    """Per-point acquisition behavior."""

    def test_set_state_fixed_compliance_reads_point_and_updates_measurements(self):
        """A fixed-compliance point should configure, acquire, and cache the reading."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.VOLTAGE
        plugin._compliance_mode = ComplianceMode.FIXED
        plugin._compliance = 0.01
        smu = MagicMock()
        smu.transport = MagicMock()
        smu.read_buffer_records.return_value = [
            BufferReading(voltage=2.0, current=0.5, resistance=4.0, time=1.25, status=0)
        ]
        plugin._smu = smu

        plugin.set_state(2.0)

        smu.set_compliance.assert_called_once_with(0.01, SourceMode.VOLT)
        smu.enable_output.assert_any_call(True)
        smu.set_source_level.assert_called_once_with(2.0)
        smu.configure_buffer.assert_called_once()
        smu.initiate.assert_called_once_with()
        smu.wait_for_operation_complete.assert_called_once_with()
        smu.read_buffer_records.assert_called_once_with(("VOLT", "CURR", "RES", "TIME", "STAT"), count=1)
        smu.set_trace_feed_continuous_never.assert_called_once_with()
        assert plugin.get_state() == pytest.approx(2.0)
        assert plugin._last_voltage == pytest.approx(2.0)
        assert plugin._last_current == pytest.approx(0.5)
        assert plugin._last_resistance == pytest.approx(4.0)
        assert plugin._last_timestamp == pytest.approx(1.25)
        assert plugin._last_power == pytest.approx(1.0)

    def test_set_state_current_mode_resistance_compliance_uses_driver_helper(self):
        """Current mode resistance compliance should delegate to the driver helper."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.CURRENT
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 1000.0
        smu = MagicMock()
        smu.transport = MagicMock()
        smu.read_buffer_records.return_value = [BufferReading(current=0.002, voltage=1.0)]
        plugin._smu = smu

        plugin.set_state(-0.002)

        smu.set_compliance_from_resistance.assert_called_once_with(
            1000.0,
            source_level=-0.002,
            source_mode=SourceMode.CURR,
        )

    def test_set_state_voltage_mode_zero_resistance_compliance_raises(self):
        """Voltage-source resistance compliance is undefined at zero programmed voltage."""
        plugin = _make_plugin()
        plugin._source_mode = SweepSourceMode.VOLTAGE
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 1000.0
        plugin._smu = MagicMock()

        with pytest.raises(ValueError):
            plugin.set_state(0.0)

    def test_set_state_bus_trigger_self_fires_group_execute_trigger(self):
        """BUS-triggered point acquisition should self-fire the GPIB group execute trigger."""
        plugin = _make_plugin()
        plugin._trigger_routing = TriggerRouting.BUS
        smu = MagicMock()
        smu.transport = MagicMock()
        smu.read_buffer_records.return_value = [BufferReading(voltage=1.0, current=0.1)]
        plugin._smu = smu

        plugin.set_state(1.0)

        smu.initiate.assert_called_once_with()
        smu.transport.send_group_execute_trigger.assert_called_once_with()
        smu.wait_for_operation_complete.assert_called_once_with()

    def test_set_state_can_leave_output_disabled(self):
        """If requested, the plugin should keep output disabled during the point action."""
        plugin = _make_plugin()
        plugin._enable_output_during_measurement = False
        smu = MagicMock()
        smu.transport = MagicMock()
        smu.read_buffer_records.return_value = [BufferReading(voltage=0.0, current=0.0)]
        plugin._smu = smu

        plugin.set_state(0.5)

        smu.enable_output.assert_any_call(False)
