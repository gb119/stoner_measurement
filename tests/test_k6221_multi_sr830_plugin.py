"""Tests for the Keithley6221_MultiSR830Plugin."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
from PyQt6.QtWidgets import QCheckBox, QTabWidget, QTableWidget, QWidget

from stoner_measurement.instruments.lockin_amplifier import LockInLineFilter
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    Keithley6221_MultiSR830Plugin,
    LockInOutput,
    ResistanceCurrentMode,
    WaveformScanMode,
)
from stoner_measurement.plugins.trace.k6221_multi_sr830 import LockInEntry, LockInReading


def _make_plugin() -> Keithley6221_MultiSR830Plugin:
    return Keithley6221_MultiSR830Plugin()


class TestDefaults:
    def test_name(self, qapp):
        assert _make_plugin().name == "k6221_multi_sr830"

    def test_defaults(self, qapp):
        plugin = _make_plugin()
        assert plugin._scan_mode is WaveformScanMode.OFFSET
        assert plugin._phase_marker_tlink == 4
        assert plugin._waveform_frequency == pytest.approx(367.0)
        assert plugin._time_constant == pytest.approx(0.3)
        assert plugin._read_rate_multiple == pytest.approx(3.0)
        assert len(plugin._lockin_entries) == 1
        assert plugin.channel_names == ["LIA 1"]
        assert plugin._report_channel_statistics is True

    def test_lockin_entry_defaults(self, qapp):
        entry = LockInEntry()
        assert entry.harmonic == 1
        assert entry.phase == pytest.approx(0.0)
        assert entry.auto_phase is False
        assert entry.auto_sensitivity is True
        assert entry.auto_offsets == {}

    def test_source_range_mode_default(self, qapp):
        plugin = _make_plugin()
        assert plugin._source_range_mode == "BEST"

    def test_offset_enabled_default(self, qapp):
        plugin = _make_plugin()
        assert plugin._offset_enabled is False


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
        plugin._resistance_mode = ResistanceCurrentMode.RMS
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
        assert restored._resistance_mode is ResistanceCurrentMode.RMS
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
                phase=45.0,
                auto_phase=True,
                auto_sensitivity=False,
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
        assert entry.phase == pytest.approx(45.0)
        assert entry.auto_phase is True
        assert entry.auto_sensitivity is False
        assert entry.auto_offsets == {"X": pytest.approx(12.5), "Y": pytest.approx(-3.0)}

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
        from PyQt6.QtWidgets import QPushButton

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

        # Transposed table: rows = settings (11), cols = lock-ins (1 by default)
        tables = settings_widget.findChildren(QTableWidget)
        assert tables
        table = tables[0]
        assert table.rowCount() == 11
        assert table.columnCount() == 1

        # Remove button disabled when only one lock-in
        remove_buttons = [b for b in settings_widget.findChildren(QPushButton) if "Remove" in b.text()]
        assert remove_buttons, "Expected a 'Remove selected' button"
        assert not remove_buttons[0].isEnabled(), "Remove button should be disabled with a single lock-in"

        # Offset checkbox present
        checkboxes = settings_widget.findChildren(QCheckBox)
        texts = [cb.text() for cb in checkboxes]
        assert any("Offset" in t for t in texts)


class TestConfiguration:
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
        for lockin in plugin._lockins:
            lockin.set_reference_source.assert_called_once()
            lockin.set_time_constant.assert_called_once_with(3.0)
            lockin.set_filter_slope.assert_called_once_with(18)
            lockin.set_harmonic.assert_called_once_with(1)
            lockin.set_reference_phase.assert_called_once_with(0.0)
        plugin._lockins[0].set_output_offset.assert_called_once()
        plugin._lockins[1].set_output_offset.assert_not_called()

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
        from stoner_measurement.instruments.lockin_amplifier import LockInLineFilter
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

    def test_auto_offset_clears_previous_offsets(self, qapp):
        plugin = _make_plugin()
        plugin._time_constant = 0.0
        plugin._read_rate_multiple = 0.0
        plugin._k6221 = MagicMock()
        lockin = MagicMock()
        lockin.get_output_offset.return_value = (5.0, MagicMock())
        plugin._lockins = [lockin]
        entry = LockInEntry(
            label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,),
            auto_offsets={"X": 99.0}
        )
        plugin._lockin_entries = [entry]

        plugin.auto_offset()

        assert entry.auto_offsets == {"X": pytest.approx(5.0)}


class TestOffsetCorrection:
    def test_offset_correction_adds_back_offset_voltage(self, qapp):
        from stoner_measurement.instruments.lockin_amplifier import LockInOutputChannel
        plugin = _make_plugin()
        entry = LockInEntry(
            label="A", resource="GPIB0::8::INSTR",
            sensitivity=1e-3, auto_offsets={"X": 50.0}
        )
        # 50% of 1 mV = 0.5 mV offset voltage; measured = true - 0.5 mV
        # true = measured + 0.5 mV
        corrected = plugin._apply_offset_correction(entry, LockInOutput.X, 0.1e-3)
        assert corrected == pytest.approx(0.1e-3 + 0.5e-3)

    def test_offset_correction_falls_back_to_offset_pct(self, qapp):
        plugin = _make_plugin()
        entry = LockInEntry(
            label="A", resource="GPIB0::8::INSTR",
            sensitivity=2e-3, offset_pct=25.0, auto_offsets={}
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
            label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,),
            sensitivity=1e-3, auto_offsets={"X": 50.0}
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
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))]
        plugin._time_constant = 2.0
        plugin._read_rate_multiple = 2.0
        plugin._last_read_at = {"GPIB0::8::INSTR": 9.0}

        with patch(
            "stoner_measurement.plugins.trace.k6221_multi_sr830.time.monotonic",
            side_effect=[10.0, 11.0, 12.0, 13.0],
        ), patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep") as sleep_mock:
            list(plugin.execute({}))
            list(plugin.execute({}))

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
            {entry.resource: LockInReading(output_values={LockInOutput.R: 0.95e-3}, ratio_signal=0.95e-3)}
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
                low_entry.resource: LockInReading(output_values={LockInOutput.R: 1e-12}, ratio_signal=1e-12),
                high_entry.resource: LockInReading(output_values={LockInOutput.R: 2.0}, ratio_signal=2.0),
            }
        )

        plugin._lockins[0].set_sensitivity.assert_not_called()
        plugin._lockins[1].set_sensitivity.assert_not_called()

    def test_auto_sensitivity_per_lockin_flag(self, qapp):
        plugin = _make_plugin()
        plugin._auto_sensitivity_enabled = True
        # entry_a: auto_sensitivity=True (default) — should update
        entry_a = LockInEntry(label="A", resource="GPIB0::8::INSTR", sensitivity=1e-3, auto_sensitivity=True)
        # entry_b: auto_sensitivity=False — should NOT update
        entry_b = LockInEntry(label="B", resource="GPIB0::9::INSTR", sensitivity=1e-3, auto_sensitivity=False)
        plugin._lockin_entries = [entry_a, entry_b]
        lockin_a = MagicMock()
        lockin_b = MagicMock()
        plugin._lockins = [lockin_a, lockin_b]

        plugin._apply_auto_sensitivity(
            {
                entry_a.resource: LockInReading(output_values={LockInOutput.R: 5e-5}, ratio_signal=5e-5),
                entry_b.resource: LockInReading(output_values={LockInOutput.R: 5e-5}, ratio_signal=5e-5),
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
            LockInEntry(label="Theta label", resource="GPIB0::9::INSTR", outputs=(LockInOutput.THETA,)),
        ]

        assert plugin.channel_names == ["X label", "X label resistance", "Theta label"]

    def test_measure_returns_multi_channel_data_with_units(self, qapp):
        plugin = _make_plugin()
        plugin._resistance_enabled = True
        plugin._lockin_entries = [LockInEntry(label="X label", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))]
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

        assert list(data) == ["X label", "X label resistance"]
        assert data["X label"].units["y"] == "V"
        assert data["X label resistance"].units["y"] == "\u03a9"

    def test_resistance_conversion_modes(self, qapp):
        plugin = _make_plugin()
        assert plugin._convert_to_resistance(1.0, 0.5) == pytest.approx(2.0)

        plugin._resistance_mode = ResistanceCurrentMode.RMS
        assert plugin._convert_to_resistance(1.0, 0.5) == pytest.approx(2.0 * np.sqrt(2.0))

        plugin._resistance_mode = ResistanceCurrentMode.PEAK_TO_PEAK
        assert plugin._convert_to_resistance(1.0, 0.5) == pytest.approx(1.0)

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
        assert plugin.channel_names == [
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
        plugin._lockin_entries = [LockInEntry(label="A", resource="GPIB0::8::INSTR", outputs=(LockInOutput.X,))]
        readings = plugin._read_lockins()

        transport.send_group_execute_trigger.assert_called_once_with()
        lockin.measure_outputs.assert_called_once_with((LockInOutput.X, LockInOutput.R))
        assert readings["GPIB0::8::INSTR"].output_values[LockInOutput.X] == pytest.approx(1.0)


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
