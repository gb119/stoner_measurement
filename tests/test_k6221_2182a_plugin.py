"""Tests for the Keithley6221_2182APlugin (no hardware required)."""

from __future__ import annotations

import json
import logging

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    ComplianceMode,
    ConnectionMode,
    Keithley6221_2182APlugin,
    SourceRangeMode,
    TraceStatus,
)
from stoner_measurement.scan import FunctionScanGenerator, ListScanGenerator, SteppedScanGenerator

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

    def test_channel_names(self, qapp):
        assert _make_plugin().channel_names == ["IV"]

    def test_reported_values_include_channel_stats_when_enabled(self, qapp):
        plugin = _make_plugin()
        plugin._set_report_channel_statistics(True)
        vals = plugin.reported_values()
        assert "k6221_dc_iv:IV mean" in vals
        assert "k6221_dc_iv:IV std" in vals

    def test_num_traces_matches_channel_names_length(self, qapp):
        """num_traces must always equal len(channel_names) for consistency."""
        plugin = _make_plugin()
        assert plugin.num_traces == len(plugin.channel_names)


# ---------------------------------------------------------------------------
# Default attributes
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_connection_mode(self, qapp):
        assert _make_plugin()._connection_mode is ConnectionMode.VIA_6221_SERIAL

    def test_default_scan_generator_type(self, qapp):
        assert isinstance(_make_plugin().scan_generator, FunctionScanGenerator)

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
        assert FunctionScanGenerator in classes
        assert SteppedScanGenerator in classes
        assert ListScanGenerator in classes

    def test_function_generator_is_first(self, qapp):
        plugin = _make_plugin()
        assert plugin._scan_generator_classes[0] is FunctionScanGenerator

    def test_set_scan_generator_class_changes_type(self, qapp):
        plugin = _make_plugin()
        plugin.set_scan_generator_class(ListScanGenerator)
        assert isinstance(plugin.scan_generator, ListScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
        plugin = _make_plugin()
        gen_before = plugin.scan_generator
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert plugin.scan_generator is gen_before


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_to_json_includes_all_keys(self, qapp):
        d = _make_plugin().to_json()
        for key in (
            "resource_6221", "resource_2182a", "connection_mode",
            "compliance_mode", "compliance", "compliance_resistance",
            "source_delay", "source_range_mode", "source_range",
            "nplc", "voltage_range", "filter_enabled", "filter_count",
            "analog_filter", "relative_enabled", "digits",
            "output_tlink", "input_tlink",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_json_default_values(self, qapp):
        d = _make_plugin().to_json()
        assert d["connection_mode"] == "via_6221_serial"
        assert d["compliance_mode"] == "voltage"
        assert d["compliance"] == pytest.approx(10.0)
        assert d["compliance_resistance"] == pytest.approx(1000.0)
        assert d["source_range_mode"] == "BEST"
        assert d["nplc"] == pytest.approx(1.0)
        assert d["filter_enabled"] is False
        assert d["filter_count"] == 10
        assert d["analog_filter"] is False
        assert d["relative_enabled"] is False
        assert d["digits"] == 8
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
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 500.0
        plugin._source_range_mode = SourceRangeMode.FIXED
        plugin._source_range = 1e-3
        plugin._analog_filter = True
        plugin._relative_enabled = True
        plugin._digits = 7

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
        assert restored._compliance_mode is ComplianceMode.RESISTANCE
        assert restored._compliance_resistance == pytest.approx(500.0)
        assert restored._source_range_mode is SourceRangeMode.FIXED
        assert restored._source_range == pytest.approx(1e-3)
        assert restored._analog_filter is True
        assert restored._relative_enabled is True
        assert restored._digits == 7

    def test_round_trip_unknown_compliance_mode_warns(self, qapp, caplog):
        """An unknown compliance_mode value must not raise and must log a warning."""
        plugin = _make_plugin()
        data = plugin.to_json()
        data["compliance_mode"] = "future_compliance_mode"

        with caplog.at_level(logging.WARNING):
            try:
                restored = BasePlugin.from_json(data)
            except ValueError:
                pytest.fail(
                    "_restore_from_json raised ValueError for an unknown "
                    "compliance_mode instead of falling back gracefully."
                )
        assert isinstance(restored._compliance_mode, ComplianceMode)
        assert any("future_compliance_mode" in r.message for r in caplog.records)

    def test_round_trip_unknown_source_range_mode_warns(self, qapp, caplog):
        """An unknown source_range_mode value must not raise and must log a warning."""
        plugin = _make_plugin()
        data = plugin.to_json()
        data["source_range_mode"] = "future_range_mode"

        with caplog.at_level(logging.WARNING):
            try:
                restored = BasePlugin.from_json(data)
            except ValueError:
                pytest.fail(
                    "_restore_from_json raised ValueError for an unknown "
                    "source_range_mode instead of falling back gracefully."
                )
        assert isinstance(restored._source_range_mode, SourceRangeMode)
        assert any("future_range_mode" in r.message for r in caplog.records)

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


class TestExecute:
    def test_execute_waits_for_6221_operating_status_before_reading_buffer(self, qapp):
        from unittest.mock import MagicMock, call, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._sweep_values = np.array([1e-3, 2e-3])
        plugin._k6221 = MagicMock()
        plugin._k2182a = MagicMock()
        plugin._k6221.get_operating_status.side_effect = [0x02, 0x02, 0x04]
        plugin._k2182a.read_buffer.return_value = (0.1, 0.2)

        with patch("stoner_measurement.plugins.trace.k6221_2182a.time.sleep") as sleep_mock:
            points = list(plugin.execute({}))

        assert points == [(1e-3, 0.1), (2e-3, 0.2)]
        plugin._k6221.sweep_start.assert_called_once_with()
        plugin._k2182a.initiate.assert_called_once_with()
        assert plugin._k6221.enable_output.call_args_list[:1] == [call(False)]
        plugin._k2182a.read_buffer.assert_called_once_with(count=2)
        plugin._k2182a.clear_buffer.assert_called_once_with()
        assert plugin._k6221.get_operating_status.call_count == 3
        plugin._k2182a.get_buffer_count.assert_not_called()
        assert sleep_mock.call_args_list == [
            call(plugin._post_sweep_delay()),
            call(0.25),
            call(0.25),
            call(plugin._post_sweep_delay()),
        ]

    def test_execute_retries_buffer_read_until_final_measurement_arrives(self, qapp):
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._sweep_values = np.array([1e-3, 2e-3])
        plugin._k6221 = MagicMock()
        plugin._k2182a = MagicMock()
        plugin._k6221.get_operating_status.return_value = 0x04
        plugin._k2182a.read_buffer.side_effect = [(0.1,), (0.1, 0.2)]

        with patch("stoner_measurement.plugins.trace.k6221_2182a.time.sleep"):
            points = list(plugin.execute({}))

        assert points == [(1e-3, 0.1), (2e-3, 0.2)]
        assert plugin._k2182a.read_buffer.call_count == 2
        plugin._k2182a.clear_buffer.assert_called_once_with()


# ---------------------------------------------------------------------------
# configure() guards
# ---------------------------------------------------------------------------

class TestConfigureGuards:
    def test_configure_without_connect_raises(self, qapp):
        plugin = _make_plugin()
        with pytest.raises(RuntimeError, match="connect"):
            plugin.configure()


# ---------------------------------------------------------------------------
# connect() transport selection and cleanup
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_via_6221_uses_passthrough_transport(self, qapp):
        from unittest.mock import MagicMock, patch

        plugin = _make_plugin()
        plugin._connection_mode = ConnectionMode.VIA_6221_SERIAL

        t6221 = MagicMock()
        t2182 = MagicMock()
        k6221 = MagicMock()
        k2182 = MagicMock()
        k6221.identify.return_value = "Keithley 6221"
        k2182.identify.return_value = "Keithley 2182A"

        with patch(
            "stoner_measurement.plugins.trace.k6221_2182a.GpibTransport.from_resource_string",
            return_value=t6221,
        ) as gpib_from_resource, patch(
            "stoner_measurement.plugins.trace.k6221_2182a.PassThroughGpibTransport.from_resource_string",
            return_value=t2182,
        ) as passthrough_from_resource, patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley6221",
            return_value=k6221,
        ), patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley2182A",
            return_value=k2182,
        ):
            plugin.connect()

        gpib_from_resource.assert_called_once_with(plugin._6221_resource, timeout=10.0)
        passthrough_from_resource.assert_called_once_with(plugin._6221_resource, timeout=10.0)
        assert plugin.status is TraceStatus.IDLE

    def test_connect_direct_gpib_uses_direct_2182_transport(self, qapp):
        from unittest.mock import MagicMock, patch

        plugin = _make_plugin()
        plugin._connection_mode = ConnectionMode.DIRECT_GPIB

        t6221 = MagicMock()
        t2182 = MagicMock()
        k6221 = MagicMock()
        k2182 = MagicMock()
        k6221.identify.return_value = "Keithley 6221"
        k2182.identify.return_value = "Keithley 2182A"

        with patch(
            "stoner_measurement.plugins.trace.k6221_2182a.GpibTransport.from_resource_string",
            side_effect=[t6221, t2182],
        ) as gpib_from_resource, patch(
            "stoner_measurement.plugins.trace.k6221_2182a.PassThroughGpibTransport.from_resource_string"
        ) as passthrough_from_resource, patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley6221",
            return_value=k6221,
        ), patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley2182A",
            return_value=k2182,
        ):
            plugin.connect()

        assert gpib_from_resource.call_count == 2
        passthrough_from_resource.assert_not_called()
        assert plugin.status is TraceStatus.IDLE

    def test_connect_closes_open_transports_when_2182_identify_fails(self, qapp):
        from unittest.mock import MagicMock, patch

        plugin = _make_plugin()
        plugin._connection_mode = ConnectionMode.VIA_6221_SERIAL

        t6221 = MagicMock()
        t2182 = MagicMock()
        k6221 = MagicMock()
        k2182 = MagicMock()
        k6221.confirm_identity.return_value = "Keithley 6221"
        k2182.confirm_identity.side_effect = RuntimeError("Unexpected instrument on 2182A connection")

        with patch(
            "stoner_measurement.plugins.trace.k6221_2182a.GpibTransport.from_resource_string",
            return_value=t6221,
        ), patch(
            "stoner_measurement.plugins.trace.k6221_2182a.PassThroughGpibTransport.from_resource_string",
            return_value=t2182,
        ), patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley6221",
            return_value=k6221,
        ), patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley2182A",
            return_value=k2182,
        ):
            with pytest.raises(RuntimeError, match="Unexpected instrument"):
                plugin.connect()

        t2182.close.assert_called_once()
        t6221.close.assert_called_once()
        assert plugin._k6221 is None
        assert plugin._k2182a is None
        assert plugin.status is TraceStatus.ERROR


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
        mock_6221.enable_output.assert_called_once_with(False)

    def test_disconnect_clears_sweep_values(self, qapp):
        from unittest.mock import MagicMock

        import numpy as np
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
        from qtpy.QtWidgets import QWidget
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
        from qtpy.QtWidgets import QGroupBox
        plugin = _make_plugin()
        widget = plugin._plugin_config_tabs()
        groups = widget.findChildren(QGroupBox)
        titles = {g.title() for g in groups}
        assert "Connection" in titles
        assert "Source (6221)" in titles
        assert "Measurement (2182A)" in titles
        assert "Trigger link" in titles


# ---------------------------------------------------------------------------
# New attributes — defaults and round-trip
# ---------------------------------------------------------------------------

class TestNewAttributes:
    def test_compliance_mode_default(self, qapp):
        assert _make_plugin()._compliance_mode is ComplianceMode.VOLTAGE

    def test_compliance_resistance_default(self, qapp):
        assert _make_plugin()._compliance_resistance == pytest.approx(1000.0)

    def test_source_range_mode_default(self, qapp):
        assert _make_plugin()._source_range_mode is SourceRangeMode.BEST

    def test_analog_filter_default(self, qapp):
        assert _make_plugin()._analog_filter is False

    def test_relative_enabled_default(self, qapp):
        assert _make_plugin()._relative_enabled is False

    def test_digits_default(self, qapp):
        assert _make_plugin()._digits == 8

    def test_nplc_default(self, qapp):
        assert _make_plugin()._nplc == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# measure() — multicolumn DataFrame output
# ---------------------------------------------------------------------------

class TestMeasure:
    def _patch_execute(self, plugin, fake_pairs):
        from unittest.mock import patch
        return patch.object(plugin, "execute", return_value=iter(fake_pairs))

    def test_measure_returns_iv_key(self, qapp):
        """measure() must return a dict with a single 'IV' key."""
        from unittest.mock import patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        plugin._sweep_values = np.array([1e-3, 2e-3])

        fake_pairs = [(1e-3, 0.1), (2e-3, 0.2)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        assert list(result.keys()) == ["IV"]

    def test_measure_x_is_source_current(self, qapp):
        """The x-axis of the returned TraceData must be the source current."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3, 2e-3])

        fake_pairs = [(1e-3, 0.1), (2e-3, 0.2)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        np.testing.assert_array_almost_equal(result["IV"].x, [1e-3, 2e-3])

    def test_measure_v_column_values(self, qapp):
        """Column 'V' must hold the measured voltages."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3, 2e-3])

        fake_pairs = [(1e-3, 0.1), (2e-3, 0.4)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        np.testing.assert_array_almost_equal(result["IV"].df["V"], [0.1, 0.4])

    def test_measure_r_column_values(self, qapp):
        """Column 'R' must hold V/I for each point."""
        from unittest.mock import MagicMock, patch

        import numpy as np
        import pytest

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3, 2e-3])

        fake_pairs = [(1e-3, 0.1), (2e-3, 0.4)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        r = result["IV"].df["R"].tolist()
        assert r[0] == pytest.approx(0.1 / 1e-3)
        assert r[1] == pytest.approx(0.4 / 2e-3)

    def test_measure_p_column_values(self, qapp):
        """Column 'P' must hold I×V for each point."""
        from unittest.mock import MagicMock, patch

        import numpy as np
        import pytest

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3, 2e-3])

        fake_pairs = [(1e-3, 0.1), (2e-3, 0.4)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        p = result["IV"].df["P"].tolist()
        assert p[0] == pytest.approx(1e-3 * 0.1)
        assert p[1] == pytest.approx(2e-3 * 0.4)

    def test_measure_zero_current_r_is_nan(self, qapp):
        """Column 'R' must be NaN when source current is zero."""
        import math
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([0.0])

        fake_pairs = [(0.0, 0.5)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        assert math.isnan(result["IV"].df["R"].iloc[0])

    def test_measure_column_roles(self, qapp):
        """V must have COLUMN_ROLE_Y; R and P must have COLUMN_ROLE_Z."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, COLUMN_ROLE_Z

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3])

        fake_pairs = [(1e-3, 0.1)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        roles = result["IV"].column_roles
        assert roles["V"] == COLUMN_ROLE_Y
        assert roles["R"] == COLUMN_ROLE_Z
        assert roles["P"] == COLUMN_ROLE_Z

    def test_measure_units(self, qapp):
        """Returned TraceData must carry correct physical units."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3])

        fake_pairs = [(1e-3, 0.1)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        units = result["IV"].units
        assert units["x"] == "A"
        assert units["V"] == "V"
        assert units["R"] == "Ω"
        assert units["P"] == "W"

    def test_measure_names(self, qapp):
        """Returned TraceData must carry correct axis names."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3])

        fake_pairs = [(1e-3, 0.1)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        names = result["IV"].names
        assert names["x"] == "I"
        assert names["V"] == "V"

    def test_measure_status_is_data_available(self, qapp):
        """Status must be DATA_AVAILABLE after a successful measure()."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3])

        fake_pairs = [(1e-3, 0.1)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            plugin.measure({})

        assert plugin.status is TraceStatus.DATA_AVAILABLE

    def test_measure_stores_data_attr(self, qapp):
        """Result must also be stored as plugin.data."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([1e-3])

        fake_pairs = [(1e-3, 0.1)]
        with patch.object(plugin, "execute", return_value=iter(fake_pairs)):
            result = plugin.measure({})

        assert plugin.data is result

    def test_measure_empty_sweep(self, qapp):
        """measure() must handle an empty sweep without raising."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._sweep_values = np.array([])

        with patch.object(plugin, "execute", return_value=iter([])):
            result = plugin.measure({})

        assert "IV" in result
        assert len(result["IV"].x) == 0


# ---------------------------------------------------------------------------
# Compliance bounds validation
# ---------------------------------------------------------------------------

class TestComplianceBounds:
    def test_voltage_mode_does_not_raise_below_limit(self, qapp):
        """Fixed-voltage compliance at the limit must configure without error."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._k2182a = MagicMock()
        plugin._compliance_mode = ComplianceMode.VOLTAGE
        plugin._compliance = 100.0  # below 105 V limit
        plugin._sweep_values = np.array([1e-3, 2e-3])

        with patch.object(plugin._k6221, "configure_custom_sweep"), \
             patch.object(plugin._k6221, "configure_list_compliance"):
            # Should not raise
            try:
                plugin.configure()
            except RuntimeError:
                pass  # connect() not called; that's fine — we only care about ValueError

    def test_resistance_mode_raises_when_compliance_exceeds_limit(self, qapp):
        """Resistance-mode compliance exceeding 105 V must raise ValueError."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._k2182a = MagicMock()
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 2000.0  # 2 kΩ
        # 100 mA × 2 kΩ = 200 V > 105 V
        plugin._sweep_values = np.array([0.1])

        with patch.object(plugin._k6221, "configure_custom_sweep"), \
             patch.object(plugin._k6221, "configure_list_compliance"):
            with pytest.raises(ValueError, match="105"):
                plugin.configure()

    def test_resistance_mode_ok_within_limit(self, qapp):
        """Resistance-mode compliance within 105 V must not raise."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        plugin = _make_plugin()
        plugin._k6221 = MagicMock()
        plugin._k2182a = MagicMock()
        plugin._compliance_mode = ComplianceMode.RESISTANCE
        plugin._compliance_resistance = 100.0  # 100 Ω
        # 1 mA × 100 Ω = 0.1 V — well within limit
        plugin._sweep_values = np.array([1e-3])

        # Should not raise ValueError; RuntimeError from missing setup is OK
        with patch.object(plugin._k6221, "configure_custom_sweep"), \
             patch.object(plugin._k6221, "configure_list_compliance"):
            try:
                plugin.configure()
            except (RuntimeError, AttributeError):
                pass
            # ValueError would propagate through; reaching here means no bounds error


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
