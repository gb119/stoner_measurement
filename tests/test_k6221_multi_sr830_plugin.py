"""Tests for the Keithley6221_MultiSR830Plugin."""

from __future__ import annotations

import itertools
import json
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
from qtpy.QtWidgets import (
    QCheckBox,
    QPushButton,
    QTableWidget,
    QTableWidgetSelectionRange,
    QTabWidget,
    QWidget,
)

from stoner_measurement.instruments.lockin_amplifier import (
    LockInExpandFactor,
    LockInInputCoupling,
    LockInLineFilter,
    LockinRefenceEdge,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.srs import SRS830LIAStatus
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    Keithley6221_MultiSR830Plugin,
    LockInOutput,
    TraceStatus,
    WaveformScanMode,
)
from stoner_measurement.plugins.trace.k6221_multi_sr830 import LockInEntry, LockInReading
from stoner_measurement.ui.widgets import AutoSISpinBox, SIComboBox


def _make_plugin() -> Keithley6221_MultiSR830Plugin:
    return Keithley6221_MultiSR830Plugin()


def _row_with_label(table: QTableWidget, label: str) -> int:
    """Return the row carrying *label* in the table's vertical header."""
    return next(
        row for row in range(table.rowCount()) if table.verticalHeaderItem(row).text() == label
    )


def _output_checks(table: QTableWidget, column: int = 0) -> dict[str, QCheckBox]:
    """Return output checkboxes keyed by SR830 output name."""
    return {
        output: table.cellWidget(_row_with_label(table, f"Output {output}"), column)
        for output in ("X", "Y", "R", "THETA")
    }


class TestDefaults:
    def test_name(self, qapp):
        assert _make_plugin().name == "k6221_multi_sr830"

    def test_defaults(self, qapp):
        plugin = _make_plugin()
        assert plugin._6221_resource == "GPIB0::13::INSTR"
        assert plugin._scan_mode is WaveformScanMode.OFFSET
        assert plugin._phase_marker_tlink == 4
        assert plugin._waveform_frequency == pytest.approx(367.0)
        assert plugin._time_constant == pytest.approx(0.3)
        assert plugin._read_rate_multiple == pytest.approx(3.0)
        assert len(plugin._lockin_entries) == 1
        assert plugin.trace_names == ["Signals"]
        assert plugin._report_channel_statistics is True

    def test_lockin_entry_defaults(self, qapp):
        entry = LockInEntry()
        assert entry.harmonic == 1
        assert entry.phase == pytest.approx(0.0)
        assert entry.auto_sensitivity is True
        assert entry.auto_offsets == {}

    def test_source_range_mode_default(self, qapp):
        plugin = _make_plugin()
        assert plugin._source_range_mode == "BEST"

    def test_offset_enabled_default(self, qapp):
        plugin = _make_plugin()
        assert plugin._offset_enabled is False


class TestReportedValues:
    def test_catalogue_lists_every_selected_lockin_output_and_6221_value(self, qapp):
        plugin = _make_plugin()
        plugin.instance_name = "measure"
        plugin._lockin_entries = [
            LockInEntry(label="Rxx", outputs=(LockInOutput.X, LockInOutput.Y)),
            LockInEntry(label="Rxy", outputs=(LockInOutput.X, LockInOutput.Y)),
        ]

        values = plugin.reported_values()

        assert values == {
            "measure.Rxx.X": "measure.get_channel_statistic('Signals Rxx X', 'mean')",
            "measure.Rxx.Y": "measure.get_channel_statistic('Signals Rxx Y', 'mean')",
            "measure.Rxy.X": "measure.get_channel_statistic('Signals Rxy X', 'mean')",
            "measure.Rxy.Y": "measure.get_channel_statistic('Signals Rxy Y', 'mean')",
            "measure.K6221.offset": "measure._waveform_offset",
            "measure.K6221.amplitude": "measure._waveform_amplitude",
            "measure.K6221.frequency": "measure._waveform_frequency",
        }

    def test_disabling_channel_statistics_retains_6221_values_only(self, qapp):
        plugin = _make_plugin()
        plugin.instance_name = "measure"
        plugin._set_report_channel_statistics(False)

        assert set(plugin.reported_values()) == {
            "measure.K6221.offset",
            "measure.K6221.amplitude",
            "measure.K6221.frequency",
        }


class TestJsonRoundTrip:
    def test_round_trip_preserves_multi_lockin_options(self, qapp):
        plugin = _make_plugin()
        plugin._scan_mode = WaveformScanMode.FREQUENCY
        plugin._waveform_amplitude = 2e-3
        plugin._waveform_offset = 3e-4
        plugin._waveform_frequency = 123.0
        plugin._phase_marker_tlink = 5
        plugin._time_constant = 3.0
        plugin._filter_slope = 24
        plugin._read_rate_multiple = 4.0
        plugin._auto_sensitivity_enabled = True
        plugin._auto_sensitivity_low = 0.2
        plugin._auto_sensitivity_high = 0.8
        plugin._resistance_enabled = True
        plugin._lockin_entries = [
            LockInEntry(label="X1", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,)),
            LockInEntry(label="T2", resource="GPIB0::9::INSTR", outputs=(LockInOutput.THETA,)),
        ]

        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley6221_MultiSR830Plugin)
        assert restored._scan_mode is WaveformScanMode.FREQUENCY
        assert restored._phase_marker_tlink == 5
        assert restored._time_constant == pytest.approx(3.0)
        assert restored._auto_sensitivity_enabled is True
        assert [entry.label for entry in restored._lockin_entries] == ["X1", "T2"]
        assert [entry.outputs for entry in restored._lockin_entries] == [
            (LockInOutput.X,),
            (LockInOutput.THETA,),
        ]

    def test_round_trip_preserves_new_fields(self, qapp):
        plugin = _make_plugin()
        plugin._line_filter = LockInLineFilter.LINE
        plugin._offset_enabled = True
        plugin._source_range_mode = "FIXED"
        plugin._lockin_entries = [
            LockInEntry(
                label="LIA 1",
                resource="GPIB0::8::INSTR",
                harmonic=3,
                phase=None,
                auto_sensitivity=False,
                offset_auto=True,
                auto_offsets={"X": 12.5, "Y": -3.0},
            )
        ]

        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley6221_MultiSR830Plugin)
        assert restored._offset_enabled is True
        assert restored._line_filter is LockInLineFilter.LINE
        assert restored._source_range_mode == "FIXED"
        entry = restored._lockin_entries[0]
        assert entry.harmonic == 3
        assert entry.phase is None
        assert entry.auto_sensitivity is False
        assert entry.offset_auto is True
        assert entry.auto_offsets == {"X": pytest.approx(12.5), "Y": pytest.approx(-3.0)}
        serialised_entry = plugin.to_json()["lockins"][0]
        assert serialised_entry["phase"] == "auto"
        assert "auto_phase" not in serialised_entry

    def test_restore_legacy_auto_phase_flag(self, qapp):
        plugin = _make_plugin()
        payload = plugin.to_json()
        payload["lockins"] = [{"phase": 45.0, "auto_phase": True}]

        restored = BasePlugin.from_json(payload)

        assert restored._lockin_entries[0].phase is None

    def test_restore_legacy_single_output_field(self, qapp):
        plugin = _make_plugin()
        payload = plugin.to_json()
        payload["lockins"] = [{"label": "LIA 1", "resource": "GPIB0::8::INSTR", "output": "R"}]
        restored = BasePlugin.from_json(payload)
        assert isinstance(restored, Keithley6221_MultiSR830Plugin)
        assert restored._lockin_entries[0].outputs == (LockInOutput.R,)


class TestUi:
    def test_settings_widget(self, qapp):
        """Single test for all UI checks (avoids pyqtgraph segfault on multiple widget creation cycles)."""
        plugin = _make_plugin()
        tabs = plugin.config_tabs()

        # Top-level structure
        assert len(tabs) == 3
        settings_widget = tabs[1][1]
        assert isinstance(settings_widget, QWidget)

        # Inner QTabWidget with two sub-tabs
        inner_tabs = settings_widget.findChildren(QTabWidget)
        assert len(inner_tabs) == 1
        inner_tab = inner_tabs[0]
        assert inner_tab.count() == 2
        assert "Common" in inner_tab.tabText(0)
        assert "Lock-in" in inner_tab.tabText(1)

        # Transposed table: rows = settings (including one per output), cols = lock-ins.
        tables = settings_widget.findChildren(QTableWidget)
        assert tables
        table = tables[0]
        assert table.rowCount() == 12
        assert table.columnCount() == 1

        # Remove button disabled when only one lock-in
        remove_buttons = [
            b for b in settings_widget.findChildren(QPushButton) if "Remove" in b.text()
        ]
        assert remove_buttons, "Expected a 'Remove selected' button"
        assert not remove_buttons[0].isEnabled(), (
            "Remove button should be disabled with a single lock-in"
        )

        # Offset checkbox present
        checkboxes = settings_widget.findChildren(QCheckBox)
        texts = [cb.text() for cb in checkboxes]
        assert any("offset" in text.casefold() for text in texts)

        output_checks = _output_checks(table)
        assert set(output_checks) == {"X", "Y", "R", "THETA"}
        assert all(check is not None for check in output_checks.values())
        assert output_checks["X"].isChecked()
        assert not output_checks["Y"].isChecked()
        assert not output_checks["R"].isChecked()
        assert not output_checks["THETA"].isChecked()

        assert table.columnWidth(0) >= 180

        all_texts = [cb.text() for cb in checkboxes]
        assert "Use RMS current" not in all_texts
        assert "Use peak current" not in all_texts

    def test_output_checkboxes_allow_multiple_outputs(self, qapp):
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        settings_widget = tabs[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]

        output_checks = _output_checks(table)

        output_checks["Y"].click()
        output_checks["R"].click()

        assert plugin._lockin_entries[0].outputs == (LockInOutput.X, LockInOutput.Y, LockInOutput.R)

    def test_output_checkboxes_keep_at_least_one_output_selected(self, qapp):
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        settings_widget = tabs[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]

        output_checks = _output_checks(table)

        output_checks["X"].click()

        assert plugin._lockin_entries[0].outputs == (LockInOutput.X,)
        assert plugin.scan_generator.stages == [(0.0, True)]

    def test_boolean_cells_stay_neutral_when_column_is_selected(self, qapp):
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        settings_widget = tabs[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]

        output_checks = _output_checks(table)
        phase_spin = table.cellWidget(_row_with_label(table, "Phase (\u00b0)"), 0)
        offset_spin = table.cellWidget(_row_with_label(table, "Offset (%)"), 0)
        label_edit = table.cellWidget(_row_with_label(table, "Label"), 0)

        table.selectColumn(0)

        assert isinstance(phase_spin, AutoSISpinBox)
        assert isinstance(offset_spin, AutoSISpinBox)
        assert output_checks
        assert all(cb.styleSheet() == "background: transparent;" for cb in output_checks.values())
        assert "alternate_base" not in table.styleSheet()
        assert "background-color" in label_edit.styleSheet()
        assert all("background-color" not in cb.styleSheet() for cb in output_checks.values())

    def test_auto_sensitivity_has_no_redundant_boolean_row(self, qapp):
        plugin = _make_plugin()
        table = plugin.config_tabs()[1][1].findChildren(QTableWidget)[0]
        labels = [table.verticalHeaderItem(row).text() for row in range(table.rowCount())]

        assert "Sensitivity" in labels
        assert "Auto-sensitivity" not in labels

    def test_lockin_table_uses_only_its_row_height_and_tab_stretches_below_controls(self, qapp):
        plugin = _make_plugin()
        settings = plugin.config_tabs()[1][1]
        table = settings.findChildren(QTableWidget)[0]
        lockins_page = table.parentWidget()
        while lockins_page is not None and lockins_page.layout() is None:
            lockins_page = lockins_page.parentWidget()

        expected_height = (
            table.horizontalHeader().height()
            + table.rowCount() * table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
        )
        assert table.minimumHeight() == expected_height
        assert table.maximumHeight() == expected_height
        assert lockins_page is not None
        assert lockins_page.layout().itemAt(lockins_page.layout().count() - 1).spacerItem() is not None

    def test_offset_compensation_control_explains_software_only_correction(self, qapp):
        plugin = _make_plugin()
        settings = plugin.config_tabs()[1][1]
        checkbox = next(
            control
            for control in settings.findChildren(QCheckBox)
            if control.text() == "Add offset to readings"
        )

        assert "does not change the lock-in settings" in checkbox.toolTip()

    def test_nonzero_manual_offset_enables_adding_offset_to_readings(self, qapp):
        plugin = _make_plugin()
        settings = plugin.config_tabs()[1][1]
        table = settings.findChildren(QTableWidget)[0]
        checkbox = next(
            control for control in settings.findChildren(QCheckBox) if control.text() == "Add offset to readings"
        )
        offset_spin = table.cellWidget(_row_with_label(table, "Offset (%)"), 0)

        assert checkbox.isChecked() is False
        offset_spin.setValue(5.0)

        assert plugin._offset_enabled is True
        assert checkbox.isChecked() is True

    def test_restore_without_saved_preference_enables_nonzero_offset(self, qapp):
        plugin = _make_plugin()
        data = plugin.to_json()
        data.pop("offset_enabled")
        data["lockins"][0]["offset_pct"] = 5.0

        restored = BasePlugin.from_json(data)

        assert restored._offset_enabled is True

    def test_sensitivity_combo_starts_with_auto_and_numeric_selection_disables_it(self, qapp):
        plugin = _make_plugin()
        settings_widget = plugin.config_tabs()[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]
        combo = table.cellWidget(_row_with_label(table, "Sensitivity"), 0)

        assert isinstance(combo, SIComboBox)
        assert combo.itemText(0) == "Auto"
        assert combo.currentIndex() == 0

        combo.setFloatValue(1e-3)

        assert plugin._lockin_entries[0].auto_sensitivity is False
        assert plugin._lockin_entries[0].sensitivity == pytest.approx(1e-3)

    def test_offset_spinbox_auto_state_updates_entry(self, qapp):
        plugin = _make_plugin()
        settings_widget = plugin.config_tabs()[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]
        offset_spin = table.cellWidget(_row_with_label(table, "Offset (%)"), 0)

        offset_spin.setAuto(True)

        assert plugin._lockin_entries[0].offset_auto is True
        assert offset_spin.lineEdit().text() == "Auto"

    def test_phase_spinbox_auto_state_updates_entry(self, qapp):
        plugin = _make_plugin()
        settings_widget = plugin.config_tabs()[1][1]
        table = settings_widget.findChildren(QTableWidget)[0]
        phase_spin = table.cellWidget(_row_with_label(table, "Phase (\u00b0)"), 0)

        phase_spin.setAuto(True)

        assert plugin._lockin_entries[0].phase is None
        assert phase_spin.lineEdit().text() == "Auto"

    def test_read_and_auto_offset_buttons_require_selection_and_accept_multiple_columns(self, qapp):
        plugin = _make_plugin()
        plugin._lockin_entries.append(LockInEntry(label="LIA 2", resource="GPIB0::9::INSTR"))
        settings = plugin.config_tabs()[1][1]
        table = settings.findChildren(QTableWidget)[0]
        buttons = {button.text(): button for button in settings.findChildren(QPushButton)}

        assert buttons["Read Lockin"].isEnabled() is False
        assert buttons["Run auto-offset"].isEnabled() is False

        table.setRangeSelected(QTableWidgetSelectionRange(0, 0, table.rowCount() - 1, 1), True)

        assert buttons["Read Lockin"].isEnabled() is True
        assert buttons["Run auto-offset"].isEnabled() is True
        plugin.auto_offset_temporary_lockins = MagicMock()
        buttons["Run auto-offset"].click()
        plugin.auto_offset_temporary_lockins.assert_called_once_with([0, 1])

    def test_read_lockin_updates_source_common_and_selected_entry_controls(self, qapp):
        plugin = _make_plugin()
        settings = plugin.config_tabs()[1][1]
        table = settings.findChildren(QTableWidget)[0]
        read_button = next(button for button in settings.findChildren(QPushButton) if button.text() == "Read Lockin")
        plugin.read_temporary_instrument_settings = MagicMock(
            return_value=(
                {"amplitude": 2e-3, "offset": 1e-4, "frequency": 123.0},
                [
                    (
                        0,
                        {
                            "time_constant": 1.0,
                            "filter_slope": 24,
                            "input_coupling": LockInInputCoupling.DC,
                            "line_filter": LockInLineFilter.BOTH,
                            "sensitivity": 5e-3,
                            "harmonic": 3,
                            "phase": 12.5,
                            "reserve_mode": LockInReserveMode.LOW_NOISE,
                            "offsets": {"X": (4.0, LockInExpandFactor.X10)},
                        },
                    )
                ],
            )
        )

        table.selectColumn(0)
        read_button.click()

        plugin.read_temporary_instrument_settings.assert_called_once_with([0])
        assert plugin._waveform_amplitude == pytest.approx(2e-3)
        assert plugin._waveform_offset == pytest.approx(1e-4)
        assert plugin._waveform_frequency == pytest.approx(123.0)
        assert plugin._time_constant == pytest.approx(1.0)
        assert plugin._filter_slope == 24
        assert plugin._input_coupling is LockInInputCoupling.DC
        assert plugin._line_filter is LockInLineFilter.BOTH
        entry = plugin._lockin_entries[0]
        assert entry.sensitivity == pytest.approx(5e-3)
        assert entry.auto_sensitivity is False
        assert entry.harmonic == 3
        assert entry.phase == pytest.approx(12.5)
        assert entry.offset_pct == pytest.approx(4.0)
        assert entry.expand is LockInExpandFactor.X10
        assert entry.reserve_mode is LockInReserveMode.LOW_NOISE


class TestConfiguration:
    def test_configure_auto_sensitivity_waits_for_agan_and_reads_back_range(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 1e-5
        plugin._read_rate_multiple = 0.0
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.get_sensitivity.return_value = 2e-3
        lockin.read_lia_status.return_value = SRS830LIAStatus.NONE
        plugin._lockins = [lockin]

        plugin.configure()

        lockin.auto_gain.assert_called_once_with()
        lockin.get_sensitivity.assert_called_once_with()
        assert plugin._lockin_entries[0].sensitivity == pytest.approx(2e-3)

    def test_configure_aborts_when_lockin_reports_overload(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 1e-5
        plugin._read_rate_multiple = 0.0
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.get_sensitivity.return_value = 1e-3
        lockin.read_lia_status.return_value = SRS830LIAStatus.INPUT_OR_RESERVE_OVERLOAD
        plugin._lockins = [lockin]

        with pytest.raises(RuntimeError, match="overloaded after configuration"):
            plugin.configure()

        assert plugin.status is TraceStatus.ERROR

    def test_configure_auto_phase_uses_phase_state(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 1e-5
        plugin._read_rate_multiple = 0.0
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        automatic_lockin = MagicMock()
        manual_lockin = MagicMock()
        plugin._lockins = [automatic_lockin, manual_lockin]
        plugin._lockin_entries = [
            LockInEntry(label="Auto", resource="GPIB0::8::INSTR", phase=None),
            LockInEntry(label="Manual", resource="GPIB0::9::INSTR", phase=45.0),
        ]

        plugin.configure()

        automatic_lockin.set_reference_phase.assert_not_called()
        automatic_lockin.auto_phase.assert_called_once_with()
        manual_lockin.set_reference_phase.assert_called_once_with(45.0)
        manual_lockin.auto_phase.assert_not_called()

    def test_configure_maps_common_and_per_lockin_settings(self, qapp):
        plugin = _make_plugin()
        plugin._scan_mode = WaveformScanMode.OFFSET
        plugin._waveform_amplitude = 5e-3
        plugin._waveform_offset = 1e-3
        plugin._waveform_frequency = 73.0
        plugin._phase_marker_tlink = 4
        plugin._time_constant = 3.0
        plugin._filter_slope = 18
        plugin._lockin_entries = [
            LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,)),
            LockInEntry(label="B", resource="GPIB0::9::INSTR", outputs=(LockInOutput.THETA,)),
        ]
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1, 0.2]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock(), MagicMock()]

        plugin.configure()

        plugin._k6221.set_waveform.assert_called_once()
        plugin._k6221.set_waveform_amplitude.assert_called_once_with(5e-3)
        plugin._k6221.set_offset_current.assert_called_once_with(1e-3)
        plugin._k6221.set_frequency.assert_called_once_with(73.0)
        plugin._k6221.set_phase_marker_output_line.assert_called_once_with(4)
        plugin._k6221.enable_phase_marker.assert_called_once_with(True)
        plugin._k6221.wave_start.assert_called_once_with()
        for lockin in plugin._lockins:
            lockin.set_reference_source.assert_has_calls(
                [
                    call(LockInReferenceSource.EXTERNAL),
                    call(LockInReferenceSource.EXTERNAL, LockinRefenceEdge.FALLING),
                ]
            )
            lockin.set_time_constant.assert_called_once_with(3.0)
            lockin.set_filter_slope.assert_called_once_with(18)
            lockin.set_harmonic.assert_called_once_with(1)
            lockin.set_reference_phase.assert_called_once_with(0.0)
        plugin._lockins[0].set_output_offset.assert_called_once()
        plugin._lockins[1].set_output_offset.assert_not_called()
        for lockin in plugin._lockins:
            lockin.read_lia_status.assert_called_once_with()

    def test_configure_leaves_6221_output_enabled(self, qapp):
        plugin = _make_plugin()
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        plugin.configure()

        plugin._k6221.enable_output.assert_called_with(True)

    def test_configure_sets_source_range_best(self, qapp):
        plugin = _make_plugin()
        plugin._source_range_mode = "BEST"
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        plugin.configure()

        plugin._k6221.set_sweep_range_mode.assert_called_once_with("BEST")
        plugin._k6221.set_fixed_range.assert_not_called()

    def test_configure_sets_source_range_fixed(self, qapp):
        plugin = _make_plugin()
        plugin._source_range_mode = "FIXED"
        plugin._scan_mode = WaveformScanMode.AMPLITUDE
        plugin._waveform_offset = 0.0
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.5e-3, 1.0e-3, 2.0e-3]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        plugin.configure()

        plugin._k6221.set_fixed_range.assert_called_once_with(pytest.approx(2.0e-3))

    def test_configure_sets_line_filter(self, qapp):
        plugin = _make_plugin()
        plugin._line_filter = LockInLineFilter.LINE
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        plugin.configure()

        plugin._lockins[0].set_line_filter.assert_called_once_with(LockInLineFilter.LINE)

    def test_resource_conflict_fails_early(self, qapp):
        plugin = _make_plugin()
        plugin._lockin_entries = [LockInEntry(label="A", resource=plugin._6221_resource)]
        with pytest.raises(ValueError, match="conflicts"):
            plugin.connect()


class TestAutoOffset:
    def test_configure_calculates_auto_offsets_after_settling(self, qapp):
        from stoner_measurement.instruments.lockin_amplifier import LockInOutputChannel

        plugin = _make_plugin()
        plugin._time_constant = 3.0
        plugin._read_rate_multiple = 1.5
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        events: list[object] = []
        plugin._k6221 = MagicMock()
        plugin._k6221.enable_output.side_effect = lambda enabled: events.append(("output", enabled))
        lockin = MagicMock()
        lockin.measure_outputs.side_effect = lambda outputs: (
            events.append(("read", outputs)) or {LockInOutput.X: 0.25e-3, LockInOutput.Y: -0.5e-3}
        )
        lockin.set_output_offset.side_effect = lambda channel, offset, expand: events.append(
            ("offset", channel, offset, expand)
        )
        plugin._lockins = [lockin]
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            sensitivity=1e-3,
            outputs=(LockInOutput.X, LockInOutput.Y),
            offset_auto=True,
            expand=LockInExpandFactor.X10,
        )
        plugin._lockin_entries = [entry]

        with patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep") as sleep:
            plugin.configure()

        sleep.assert_called_once_with(9.0)
        lockin.measure_outputs.assert_called_once_with((LockInOutput.X, LockInOutput.Y))
        lockin.set_output_offset.assert_has_calls(
            [
                call(LockInOutputChannel.X, 25.0, entry.expand),
                call(LockInOutputChannel.Y, -50.0, entry.expand),
            ]
        )
        assert lockin.wait_for_ifc.call_count == 2
        assert entry.auto_offsets == {"X": pytest.approx(25.0), "Y": pytest.approx(-50.0)}
        assert events.index(("output", True)) < events.index(
            ("read", (LockInOutput.X, LockInOutput.Y))
        )
        assert events.index(("read", (LockInOutput.X, LockInOutput.Y))) < events.index(
            ("offset", LockInOutputChannel.X, 25.0, entry.expand)
        )

    def test_configure_auto_offset_reads_only_x_when_only_x_selected(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 0.01
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.measure_outputs.return_value = {LockInOutput.X: 0.25e-3}
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(
                label="A",
                resource="GPIB0::8::INSTR",
                sensitivity=1e-3,
                outputs=(LockInOutput.X,),
                offset_auto=True,
            )
        ]

        plugin.configure()

        lockin.measure_outputs.assert_called_once_with((LockInOutput.X,))

    @pytest.mark.parametrize(
        ("selected_output", "processed_outputs"),
        [
            (LockInOutput.R, (LockInOutput.X, LockInOutput.Y)),
            (LockInOutput.THETA, (LockInOutput.X, LockInOutput.Y)),
        ],
    )
    def test_configure_auto_offset_processes_xy_for_polar_outputs(
        self, qapp, selected_output, processed_outputs
    ):
        plugin = _make_plugin()
        plugin._time_constant = 0.01
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.measure_outputs.return_value = {
            LockInOutput.X: 0.1e-3,
            LockInOutput.Y: 0.2e-3,
            LockInOutput.R: 0.3e-3,
        }
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(
                label="A",
                resource="GPIB0::8::INSTR",
                sensitivity=1e-3,
                outputs=(selected_output,),
                offset_auto=True,
            )
        ]

        plugin.configure()

        lockin.measure_outputs.assert_called_once_with(processed_outputs)
        assert set(plugin._lockin_entries[0].auto_offsets) >= {"X", "Y"}

    def test_auto_offset_calls_aoff_and_reads_back(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 0.01
        plugin._read_rate_multiple = 1.0
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.get_output_offset.return_value = (15.0, MagicMock())
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))
        ]

        with patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep"):
            plugin.auto_offset()

        from stoner_measurement.instruments.lockin_amplifier import LockInOutputChannel

        lockin.auto_offset_channel.assert_called_once_with(LockInOutputChannel.X)
        lockin.get_output_offset.assert_called_once_with(LockInOutputChannel.X)
        assert plugin._lockin_entries[0].auto_offsets == {"X": pytest.approx(15.0)}
        plugin._k6221.enable_output.assert_any_call(True)
        plugin._k6221.enable_output.assert_called_with(False)

    def test_auto_offset_waits_at_least_three_time_constants_before_aoff(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 2.0
        plugin._read_rate_multiple = 0.5
        plugin._k6221 = MagicMock()
        events = []
        plugin._k6221.enable_output.side_effect = lambda enabled: events.append(("output", enabled))
        lockin = MagicMock()
        lockin.auto_offset_channel.side_effect = lambda channel: events.append(("aoff", channel))
        lockin.get_output_offset.return_value = (5.0, LockInExpandFactor.X1)
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))
        ]

        with patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep") as sleep:
            plugin.auto_offset()

        sleep.assert_called_once_with(6.0)
        assert events.index(("output", True)) < next(
            index for index, event in enumerate(events) if event[0] == "aoff"
        )

    def test_auto_offset_clears_previous_offsets(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 0.0
        plugin._read_rate_multiple = 0.0
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.get_output_offset.return_value = (5.0, MagicMock())
        plugin._lockins = [lockin]
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            outputs=(LockInOutput.X,),
            auto_offsets={"X": 99.0},
        )
        plugin._lockin_entries = [entry]

        plugin.auto_offset()

        assert entry.auto_offsets == {"X": pytest.approx(5.0)}


class TestOffsetCorrection:
    def test_offset_correction_adds_back_offset_voltage(self, qapp):
        plugin = _make_plugin()
        entry = LockInEntry(
            label="A", resource="GPIB0::8::INSTR", sensitivity=1e-3, auto_offsets={"X": 50.0}
        )
        # 50% of 1 mV = 0.5 mV offset voltage; measured = true - 0.5 mV
        # true = measured + 0.5 mV
        corrected = plugin._apply_offset_correction(entry, LockInOutput.X, 0.1e-3)
        assert corrected == pytest.approx(0.1e-3 + 0.5e-3)

    def test_offset_correction_falls_back_to_offset_pct(self, qapp):
        plugin = _make_plugin()
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            sensitivity=2e-3,
            offset_pct=25.0,
            auto_offsets={},
        )
        corrected = plugin._apply_offset_correction(entry, LockInOutput.X, 0.0)
        assert corrected == pytest.approx(0.5e-3)

    def test_offset_correction_skips_theta(self, qapp):
        plugin = _make_plugin()
        entry = LockInEntry(label="A", resource="GPIB0::8::INSTR", auto_offsets={"X": 99.0})
        corrected = plugin._apply_offset_correction(entry, LockInOutput.THETA, 45.0)
        assert corrected == pytest.approx(45.0)

    def test_offset_enabled_applied_in_acquire_trace(self, qapp):
        plugin = _make_plugin()
        plugin._offset_enabled = True
        plugin._sweep_values = np.array([1.0])
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.measure_outputs.return_value = {
            LockInOutput.X: 0.1e-3,
            LockInOutput.R: 0.1e-3,
        }
        plugin._lockins = [lockin]
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            outputs=(LockInOutput.X,),
            sensitivity=1e-3,
            auto_offsets={"X": 50.0},
        )
        plugin._lockin_entries = [entry]

        _, channel_values, _ = plugin._acquire_trace({})

        expected = 0.1e-3 + 0.5e-3  # measured + 50% of 1 mV
        assert channel_values["A"][0] == pytest.approx(expected)


class TestRateLimitAndAutoSensitivity:
    def test_rate_limit_persists_across_execute_calls(self, qapp):
        plugin = _make_plugin()
        plugin._sweep_values = np.array([1.0])
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.measure_outputs.return_value = {
            LockInOutput.X: 0.1,
            LockInOutput.Y: 0.2,
            LockInOutput.R: 0.3,
            LockInOutput.THETA: 45.0,
        }
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))
        ]
        plugin._time_constant = 2.0
        plugin._read_rate_multiple = 2.0
        plugin._last_read_at = {"GPIB0::8::INSTR": 9.0}
        monotonic_values = itertools.chain([10.0, 11.0, 12.0, 13.0], itertools.repeat(13.0))

        with (
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.time.monotonic",
                side_effect=monotonic_values,
            ),
            patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep") as sleep_mock,
        ):
            plugin.measure({})
            plugin.measure({})

        assert sleep_mock.call_args_list == [call(3.0), call(3.0)]
        assert plugin._last_read_at["GPIB0::8::INSTR"] == pytest.approx(13.0)

    def test_auto_sensitivity_steps_up_and_down(self, qapp):
        plugin = _make_plugin()
        plugin._auto_sensitivity_enabled = True
        entry = LockInEntry(label="A", resource="GPIB0::8::INSTR", sensitivity=1e-3)
        plugin._lockin_entries = [entry]
        lockin = MagicMock()
        plugin._lockins = [lockin]
        plugin._apply_auto_sensitivity(
            {entry.resource: LockInReading(output_values={LockInOutput.R: 5e-5}, ratio_signal=5e-5)}
        )
        assert entry.sensitivity == pytest.approx(5e-4)
        lockin.set_sensitivity.assert_called_once_with(5e-4)

        lockin.reset_mock()
        entry.sensitivity = 1e-3
        plugin._apply_auto_sensitivity(
            {
                entry.resource: LockInReading(
                    output_values={LockInOutput.R: 0.95e-3}, ratio_signal=0.95e-3
                )
            }
        )
        assert entry.sensitivity == pytest.approx(2e-3)
        lockin.set_sensitivity.assert_called_once_with(2e-3)

    def test_auto_sensitivity_respects_limits(self, qapp):
        plugin = _make_plugin()
        plugin._auto_sensitivity_enabled = True
        low_entry = LockInEntry(label="A", resource="GPIB0::8::INSTR", sensitivity=2e-9)
        high_entry = LockInEntry(label="B", resource="GPIB0::9::INSTR", sensitivity=1.0)
        plugin._lockin_entries = [low_entry, high_entry]
        plugin._lockins = [MagicMock(), MagicMock()]

        plugin._apply_auto_sensitivity(
            {
                low_entry.resource: LockInReading(
                    output_values={LockInOutput.R: 1e-12}, ratio_signal=1e-12
                ),
                high_entry.resource: LockInReading(
                    output_values={LockInOutput.R: 2.0}, ratio_signal=2.0
                ),
            }
        )

        plugin._lockins[0].set_sensitivity.assert_not_called()
        plugin._lockins[1].set_sensitivity.assert_not_called()

    def test_auto_sensitivity_per_lockin_flag(self, qapp):
        plugin = _make_plugin()
        plugin._auto_sensitivity_enabled = True
        # entry_a: auto_sensitivity=True (default) — should update
        entry_a = LockInEntry(
            label="A", resource="GPIB0::8::INSTR", sensitivity=1e-3, auto_sensitivity=True
        )
        # entry_b: auto_sensitivity=False — should NOT update
        entry_b = LockInEntry(
            label="B", resource="GPIB0::9::INSTR", sensitivity=1e-3, auto_sensitivity=False
        )
        plugin._lockin_entries = [entry_a, entry_b]
        lockin_a = MagicMock()
        lockin_b = MagicMock()
        plugin._lockins = [lockin_a, lockin_b]

        plugin._apply_auto_sensitivity(
            {
                entry_a.resource: LockInReading(
                    output_values={LockInOutput.R: 5e-5}, ratio_signal=5e-5
                ),
                entry_b.resource: LockInReading(
                    output_values={LockInOutput.R: 5e-5}, ratio_signal=5e-5
                ),
            }
        )

        lockin_a.set_sensitivity.assert_called_once()
        lockin_b.set_sensitivity.assert_not_called()


class TestChannelsAndResistance:
    def test_channel_labelling_and_output_selection(self, qapp):
        plugin = _make_plugin()
        plugin._resistance_enabled = True
        plugin._lockin_entries = [
            LockInEntry(label="X label", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,)),
            LockInEntry(
                label="Theta label", resource="GPIB0::9::INSTR", outputs=(LockInOutput.THETA,)
            ),
        ]

        assert [spec.name for spec in plugin._channel_specs()] == [
            "X label",
            "X label resistance",
            "Theta label",
        ]

    def test_measure_returns_multi_channel_data_with_units(self, qapp):
        plugin = _make_plugin()
        plugin._resistance_enabled = True
        plugin._lockin_entries = [
            LockInEntry(label="X label", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))
        ]
        specs = plugin._channel_specs()

        with patch.object(
            plugin,
            "_acquire_trace",
            return_value=(
                np.array([1.0, 2.0]),
                {
                    "X label": [0.1, 0.2],
                    "X label resistance": [10.0, 20.0],
                },
                specs,
            ),
        ):
            data = plugin.measure({})

        assert list(data) == ["Signals"]
        trace = data["Signals"]
        assert trace.columns == ["x", "X label", "X label resistance"]
        assert trace.units["X label"] == "V"
        assert trace.units["X label resistance"] == "\u03a9"

    def test_resistance_conversion_uses_rms_current_from_peak_amplitude(self, qapp):
        plugin = _make_plugin()
        assert plugin._convert_to_resistance(1.0, 0.5) == pytest.approx(2.0 * np.sqrt(2.0))

    def test_multi_output_channel_labelling(self, qapp):
        plugin = _make_plugin()
        plugin._resistance_enabled = True
        plugin._lockin_entries = [
            LockInEntry(
                label="LIA",
                resource="GPIB0::8::INSTR",
                outputs=(LockInOutput.X, LockInOutput.R, LockInOutput.THETA),
            )
        ]
        assert [spec.name for spec in plugin._channel_specs()] == [
            "LIA X",
            "LIA X resistance",
            "LIA R",
            "LIA R resistance",
            "LIA THETA",
        ]


class TestParseOutputs:
    def test_t_alias_for_theta(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs("T")
        assert result == (LockInOutput.THETA,)

    def test_lowercase_tokens(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs("x, y, r, theta")
        assert result == (LockInOutput.X, LockInOutput.Y, LockInOutput.R, LockInOutput.THETA)

    def test_whitespace_handling(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs("  X ,  T  ")
        assert result == (LockInOutput.X, LockInOutput.THETA)

    def test_mixed_alias_and_canonical(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs("X, T, R")
        assert result == (LockInOutput.X, LockInOutput.THETA, LockInOutput.R)

    def test_deduplication(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs("X, x, X")
        assert result == (LockInOutput.X,)

    def test_enum_passthrough(self):
        result = Keithley6221_MultiSR830Plugin._parse_outputs((LockInOutput.R, LockInOutput.THETA))
        assert result == (LockInOutput.R, LockInOutput.THETA)

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError):
            Keithley6221_MultiSR830Plugin._parse_outputs("INVALID")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="At least one output"):
            Keithley6221_MultiSR830Plugin._parse_outputs("")


class TestGpibTrigger:
    def test_read_lockins_asserts_get_for_gpib_transports(self, qapp):
        plugin = _make_plugin()
        transport = GpibTransport(address=8)
        transport.send_group_execute_trigger = MagicMock()
        lockin = MagicMock()
        lockin.transport = transport
        lockin.measure_outputs.return_value = {
            LockInOutput.X: 1.0,
            LockInOutput.Y: 2.0,
            LockInOutput.R: 3.0,
            LockInOutput.THETA: 4.0,
        }
        plugin._lockins = [lockin]
        plugin._lockin_entries = [
            LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))
        ]
        readings = plugin._read_lockins()

        transport.send_group_execute_trigger.assert_called_once_with()
        lockin.measure_outputs.assert_called_once_with((LockInOutput.X, LockInOutput.R))
        assert readings["GPIB0::8::INSTR"].output_values[LockInOutput.X] == pytest.approx(1.0)

    def test_read_lockin_recovers_lia_timeout_by_dropping_expand(self, qapp):
        from stoner_measurement.instruments.lockin_amplifier import LockInOutputChannel

        plugin = _make_plugin()
        lockin = MagicMock()
        lockin.measure_outputs.side_effect = [
            TimeoutError("MAV missing"),
            {LockInOutput.X: 1.0, LockInOutput.R: 1.0},
        ]
        lockin.read_status_byte.return_value = 11
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            outputs=(LockInOutput.X,),
            offset_auto=True,
            auto_offsets={"X": 25.0},
            expand=LockInExpandFactor.X10,
        )

        resource, reading = plugin._read_one_lockin(entry, lockin)

        assert resource == entry.resource
        assert reading.output_values[LockInOutput.X] == pytest.approx(1.0)
        assert lockin.measure_outputs.call_count == 2
        lockin.set_output_offset.assert_called_once_with(
            LockInOutputChannel.X, 25.0, LockInExpandFactor.X1
        )
        lockin.wait_for_ifc.assert_called_once_with()
        lockin.write.assert_called_once_with("*CLS")
        assert entry.expand is LockInExpandFactor.X1

    def test_read_lockin_does_not_retry_timeout_without_lia_status(self, qapp):
        plugin = _make_plugin()
        lockin = MagicMock()
        lockin.measure_outputs.side_effect = TimeoutError("MAV missing")
        lockin.read_status_byte.return_value = 3
        entry = LockInEntry(
            label="A",
            resource="GPIB0::8::INSTR",
            outputs=(LockInOutput.X,),
            expand=LockInExpandFactor.X10,
        )

        with pytest.raises(TimeoutError, match="MAV missing"):
            plugin._read_one_lockin(entry, lockin)

        lockin.set_output_offset.assert_not_called()
        assert entry.expand is LockInExpandFactor.X10


class TestValidation:
    def test_invalid_harmonic_raises(self, qapp):
        plugin = _make_plugin()
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR", harmonic=0)]
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        with pytest.raises(ValueError, match="harmonic"):
            plugin.configure()

    def test_invalid_source_range_mode_raises(self, qapp):
        plugin = _make_plugin()
        plugin._source_range_mode = "INVALID"
        plugin.scan_generator.generate = MagicMock(return_value=np.array([0.1]))
        plugin._k6221 = MagicMock()
        plugin._lockins = [MagicMock()]
        with pytest.raises(ValueError, match="range mode"):
            plugin.configure()


class TestConnect:
    def test_sr830_transport_opts_into_ifc_aware_mav_timeout(self, qapp):
        plugin = _make_plugin()
        entry = LockInEntry(label="A", resource="GPIB0::8::INSTR")
        mock_transport = MagicMock()
        mock_sr830 = MagicMock()
        mock_sr830.identify.return_value = "Stanford Research Systems,SR830"

        with (
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.GpibTransport.from_resource_string",
                return_value=mock_transport,
            ) as transport_factory,
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.SRS830",
                return_value=mock_sr830,
            ),
        ):
            transport, lockin = plugin._connect_one_lockin(entry)

        transport_factory.assert_called_once_with(
            entry.resource,
            timeout=10.0,
            command_complete_mask=2,
        )
        assert transport is mock_transport
        assert lockin is mock_sr830

    def test_sr830_identity_mismatch_closes_transports_and_resets_state(self, qapp):
        """Verify connect() cleans up and resets state when an SR830 returns a wrong identity."""
        plugin = _make_plugin()
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        mock_transport_6221 = MagicMock()
        mock_transport_sr830 = MagicMock()
        mock_k6221 = MagicMock()
        mock_sr830 = MagicMock()
        mock_sr830.identify.return_value = "SR860"  # does not contain "SR830"

        with (
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.GpibTransport.from_resource_string",
                side_effect=[mock_transport_6221, mock_transport_sr830],
            ),
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.Keithley6221",
                return_value=mock_k6221,
            ),
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.SRS830",
                return_value=mock_sr830,
            ),
        ):
            with pytest.raises(RuntimeError, match="Unexpected SR830 identity"):
                plugin.connect()

        mock_transport_sr830.close.assert_called()
        mock_transport_6221.close.assert_called()
        assert plugin._k6221 is None
        assert plugin._lockins == []
        assert plugin.status is TraceStatus.ERROR


class TestResistanceConversion:
    def test_convert_to_resistance_uses_rms_current_from_peak_amplitude(self, qapp):
        plugin = _make_plugin()
        resistance = plugin._convert_to_resistance(signal=1.0, amplitude=2.0)
        assert resistance == pytest.approx(np.sqrt(2.0) / 2.0)

    def test_sr830_connect_exception_closes_transports_and_resets_state(self, qapp):
        """Verify connect() cleans up and resets state when an SR830 raises during connection."""
        plugin = _make_plugin()
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR")]

        mock_transport_6221 = MagicMock()
        mock_transport_sr830 = MagicMock()
        mock_k6221 = MagicMock()
        mock_sr830 = MagicMock()
        mock_sr830.connect.side_effect = OSError("Instrument not responding")

        with (
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.GpibTransport.from_resource_string",
                side_effect=[mock_transport_6221, mock_transport_sr830],
            ),
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.Keithley6221",
                return_value=mock_k6221,
            ),
            patch(
                "stoner_measurement.plugins.trace.k6221_multi_sr830.SRS830",
                return_value=mock_sr830,
            ),
        ):
            with pytest.raises(OSError, match="Instrument not responding"):
                plugin.connect()

        mock_transport_sr830.close.assert_called()
        mock_transport_6221.close.assert_called()
        assert plugin._k6221 is None
        assert plugin._lockins == []
        assert plugin.status is TraceStatus.ERROR
