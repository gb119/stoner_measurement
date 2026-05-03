"""Tests for the Keithley6221_2182APlugin (no hardware required)."""

from __future__ import annotations

import json
import logging

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    ConnectionMode,
    Keithley6221_2182APlugin,
    TraceStatus,
)
from stoner_measurement.scan import ListScanGenerator, SteppedScanGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin() -> Keithley6221_2182APlugin:
    """Return a freshly constructed plugin instance."""
    return Keithley6221_2182APlugin()


# ---------------------------------------------------------------------------
# Identity properties
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_name(self, qapp):
        assert _make_plugin().name == "k6221_dc_iv"

    def test_trace_title(self, qapp):
        assert _make_plugin().trace_title == "6221/2182A I-V"

    def test_x_label(self, qapp):
        assert _make_plugin().x_label == "I"

    def test_y_label(self, qapp):
        assert _make_plugin().y_label == "V"

    def test_x_units(self, qapp):
        assert _make_plugin().x_units == "A"

    def test_y_units(self, qapp):
        assert _make_plugin().y_units == "V"

    def test_plugin_type(self, qapp):
        assert _make_plugin().plugin_type == "trace"

    def test_num_traces(self, qapp):
        assert _make_plugin().num_traces == 1


# ---------------------------------------------------------------------------
# Default attributes
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_connection_mode(self, qapp):
        assert _make_plugin()._connection_mode is ConnectionMode.VIA_6221_SERIAL

    def test_default_scan_generator_type(self, qapp):
        assert isinstance(_make_plugin().scan_generator, SteppedScanGenerator)

    def test_scan_generator_units_are_amps(self, qapp):
        assert _make_plugin().scan_generator.units == "A"

    def test_default_compliance(self, qapp):
        assert _make_plugin()._compliance == pytest.approx(10.0)

    def test_default_nplc(self, qapp):
        assert _make_plugin()._nplc == pytest.approx(1.0)

    def test_default_output_tlink(self, qapp):
        assert _make_plugin()._output_tlink == 1

    def test_default_input_tlink(self, qapp):
        assert _make_plugin()._input_tlink == 2

    def test_no_active_instruments_at_init(self, qapp):
        plugin = _make_plugin()
        assert plugin._k6221 is None
        assert plugin._k2182a is None

    def test_initial_status_is_idle(self, qapp):
        assert _make_plugin().status is TraceStatus.IDLE


# ---------------------------------------------------------------------------
# Scan generator management
# ---------------------------------------------------------------------------

class TestScanGenerator:
    def test_scan_generator_classes(self, qapp):
        plugin = _make_plugin()
        classes = plugin._scan_generator_classes
        assert SteppedScanGenerator in classes
        assert ListScanGenerator in classes

    def test_set_scan_generator_class_changes_type(self, qapp):
        plugin = _make_plugin()
        plugin.set_scan_generator_class(ListScanGenerator)
        assert isinstance(plugin.scan_generator, ListScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
        plugin = _make_plugin()
        gen_before = plugin.scan_generator
        plugin.set_scan_generator_class(SteppedScanGenerator)
        assert plugin.scan_generator is gen_before


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_to_json_includes_all_keys(self, qapp):
        d = _make_plugin().to_json()
        for key in (
            "resource_6221", "resource_2182a", "connection_mode",
            "compliance", "source_delay", "source_range",
            "nplc", "voltage_range", "filter_enabled", "filter_count",
            "output_tlink", "input_tlink",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_json_default_values(self, qapp):
        d = _make_plugin().to_json()
        assert d["connection_mode"] == "via_6221_serial"
        assert d["compliance"] == pytest.approx(10.0)
        assert d["nplc"] == pytest.approx(1.0)
        assert d["filter_enabled"] is False
        assert d["filter_count"] == 10
        assert d["output_tlink"] == 1
        assert d["input_tlink"] == 2

    def test_round_trip_restores_settings(self, qapp):
        plugin = _make_plugin()
        plugin._compliance = 5.0
        plugin._nplc = 10.0
        plugin._filter_enabled = True
        plugin._filter_count = 25
        plugin._output_tlink = 3
        plugin._input_tlink = 4
        plugin._connection_mode = ConnectionMode.DIRECT_GPIB
        plugin._2182a_resource = "GPIB0::14::INSTR"

        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley6221_2182APlugin)
        assert restored._compliance == pytest.approx(5.0)
        assert restored._nplc == pytest.approx(10.0)
        assert restored._filter_enabled is True
        assert restored._filter_count == 25
        assert restored._output_tlink == 3
        assert restored._input_tlink == 4
        assert restored._connection_mode is ConnectionMode.DIRECT_GPIB
        assert restored._2182a_resource == "GPIB0::14::INSTR"

    def test_round_trip_preserves_scan_generator(self, qapp):
        plugin = _make_plugin()
        plugin.set_scan_generator_class(ListScanGenerator)

        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored.scan_generator, ListScanGenerator)

    def test_round_trip_default_settings(self, qapp):
        plugin = _make_plugin()
        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, Keithley6221_2182APlugin)
        assert restored._connection_mode is ConnectionMode.VIA_6221_SERIAL
        assert restored._compliance == pytest.approx(10.0)

    def test_restore_unknown_connection_mode_falls_back(self, qapp, caplog):
        """An unknown connection_mode value in saved JSON must not raise,
        and must log a warning."""
        plugin = _make_plugin()
        data = plugin.to_json()
        data["connection_mode"] = "future_mode_value"

        with caplog.at_level(logging.WARNING):
            try:
                restored = BasePlugin.from_json(data)
            except ValueError:
                pytest.fail(
                    "_restore_from_json raised ValueError for an unknown "
                    "connection_mode instead of falling back gracefully."
                )

        # The connection mode should be left at the pre-restore default.
        assert isinstance(restored._connection_mode, ConnectionMode)
        # A warning must have been emitted.
        assert any("future_mode_value" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# _nvm_write / _nvm_query guards
# ---------------------------------------------------------------------------

class TestNvmGuards:
    def test_nvm_write_direct_gpib_without_connection_raises(self, qapp):
        plugin = _make_plugin()
        plugin._connection_mode = ConnectionMode.DIRECT_GPIB
        # _k2182a is None — should raise RuntimeError, not AttributeError
        with pytest.raises(RuntimeError, match="DIRECT_GPIB"):
            plugin._nvm_write("*IDN?")

    def test_nvm_query_direct_gpib_without_connection_raises(self, qapp):
        plugin = _make_plugin()
        plugin._connection_mode = ConnectionMode.DIRECT_GPIB
        with pytest.raises(RuntimeError, match="DIRECT_GPIB"):
            plugin._nvm_query("*IDN?")


# ---------------------------------------------------------------------------
# execute() guards
# ---------------------------------------------------------------------------

class TestExecuteGuards:
    def test_execute_without_connect_raises(self, qapp):
        plugin = _make_plugin()
        with pytest.raises(RuntimeError, match="connect"):
            list(plugin.execute({}))

    def test_execute_without_configure_raises(self, qapp):
        from unittest.mock import MagicMock
        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        # _sweep_values is None — configure() not called
        with pytest.raises(RuntimeError, match="configure"):
            list(plugin.execute({}))


# ---------------------------------------------------------------------------
# configure() guards
# ---------------------------------------------------------------------------

class TestConfigureGuards:
    def test_configure_without_connect_raises(self, qapp):
        plugin = _make_plugin()
        with pytest.raises(RuntimeError, match="connect"):
            plugin.configure()


# ---------------------------------------------------------------------------
# disconnect() behaviour
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_sets_idle(self, qapp):
        plugin = _make_plugin()
        plugin._set_status(TraceStatus.DATA_AVAILABLE)
        plugin.disconnect()
        assert plugin.status is TraceStatus.IDLE

    def test_disconnect_clears_instruments(self, qapp):
        from unittest.mock import MagicMock
        plugin = _make_plugin()
        mock_6221 = MagicMock()
        plugin._k6221 = mock_6221
        plugin.disconnect()
        assert plugin._k6221 is None
        assert plugin._k2182a is None
        mock_6221.write.assert_called_with("OUTP:STAT 0")

    def test_disconnect_clears_sweep_values(self, qapp):
        import numpy as np
        from unittest.mock import MagicMock
        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([0.0, 1.0])
        plugin.disconnect()
        assert plugin._sweep_values is None


# ---------------------------------------------------------------------------
# Settings tab widget construction
# ---------------------------------------------------------------------------

class TestConfigTabsWidget:
    def test_settings_widget_is_qwidget(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = _make_plugin()
        widget = plugin._plugin_config_tabs()
        assert isinstance(widget, QWidget)

    def test_config_tabs_returns_three_tabs(self, qapp):
        plugin = _make_plugin()
        tabs = plugin.config_tabs()
        assert len(tabs) == 3

    def test_config_tabs_titles(self, qapp):
        plugin = _make_plugin()
        titles = [t for t, _ in plugin.config_tabs()]
        assert titles[0].endswith("Scan")
        assert titles[1].endswith("Settings")
        assert titles[2].endswith("About")

    def test_about_html_contains_heading(self, qapp):
        plugin = _make_plugin()
        html = plugin._about_html()
        assert "<h3>" in html

    def test_settings_widget_contains_group_boxes(self, qapp):
        from PyQt6.QtWidgets import QGroupBox
        plugin = _make_plugin()
        widget = plugin._plugin_config_tabs()
        groups = widget.findChildren(QGroupBox)
        titles = {g.title() for g in groups}
        assert "Connection" in titles
        assert "Source (6221)" in titles
        assert "Measurement (2182A)" in titles
        assert "Trigger link" in titles
