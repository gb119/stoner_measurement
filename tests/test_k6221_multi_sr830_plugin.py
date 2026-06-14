"""Tests for the Keithley6221_MultiSR830Plugin."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
from PyQt6.QtWidgets import QGroupBox, QTableWidget, QWidget

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
        assert plugin._scan_mode is WaveformScanMode.AMPLITUDE
        assert plugin._phase_marker_tlink == 3
        assert plugin._time_constant == pytest.approx(0.3)
        assert plugin._read_rate_multiple == pytest.approx(3.0)
        assert len(plugin._lockin_entries) == 1
        assert plugin.channel_names == ["LIA 1"]


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

    def test_restore_legacy_single_output_field(self, qapp):
        restored = BasePlugin.from_json(
            {
                "__plugin_type__": "trace",
                "name": "k6221_multi_sr830",
                "lockins": [{"label": "LIA 1", "resource": "GPIB0::8::INSTR", "output": "R"}],
            }
        )
        assert isinstance(restored, Keithley6221_MultiSR830Plugin)
        assert restored._lockin_entries[0].outputs == (LockInOutput.R,)


class TestUi:
    def test_settings_widget_construction(self, qapp):
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        assert len(tabs) == 3
        assert isinstance(tabs[1][1], QWidget)
        groups = tabs[1][1].findChildren(QGroupBox)
        titles = {group.title() for group in groups}
        assert "Common lock-in" in titles
        assert "Lock-ins" in titles
        assert "Resistance conversion" in titles
        tables = tabs[1][1].findChildren(QTableWidget)
        assert tables and tables[0].columnCount() == 7


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
        plugin._lockins[0].set_output_offset.assert_called_once()
        plugin._lockins[1].set_output_offset.assert_not_called()

    def test_resource_conflict_fails_early(self, qapp):
        plugin = _make_plugin()
        plugin._lockin_entries = [LockInEntry(label="A", resource=plugin._6221_resource)]
        with pytest.raises(ValueError, match="conflicts"):
            plugin.connect()


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

        with patch("stoner_measurement.plugins.trace.k6221_multi_sr830.time.monotonic", side_effect=[10.0, 11.0, 12.0, 13.0]), patch(
            "stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep"
        ) as sleep_mock:
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
        assert data["X label resistance"].units["y"] == "Ω"

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


class TestGpibTrigger:
    def test_read_lockins_asserts_get_for_gpib_transports(self, qapp):
        pytest.importorskip("pyvisa")
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
        assert readings["GPIB0::8::INSTR"].output_values[LockInOutput.X] == pytest.approx(1.0)
