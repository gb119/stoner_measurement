"""Tests for the DummyPlugin."""

from __future__ import annotations

from stoner_measurement.plugins.dummy import DummyPlugin
from stoner_measurement.plugins.trace import TraceStatus


class TestDummyPlugin:
    def test_name(self):
        plugin = DummyPlugin()
        assert plugin.name == "Dummy"

    def test_execute_default_points(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({}))
        assert len(data) == 100

    def test_execute_custom_points(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 50}))
        assert len(data) == 50

    def test_execute_yields_tuples(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 10}))
        for item in data:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_execute_amplitude(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 4, "amplitude": 2.0}))
        # Check that values are within [-2.0, 2.0]
        for _x, y in data:
            assert abs(y) <= 2.0 + 1e-9

    def test_execute_sine_wave(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 5, "amplitude": 1.0}))
        # First point: sin(0) = 0
        assert abs(data[0][1]) < 1e-9
        # Last point: sin(2π) ≈ 0
        assert abs(data[-1][1]) < 1e-9

    def test_config_widget(self, qapp):
        plugin = DummyPlugin()
        widget = plugin.config_widget()
        assert widget is not None

    def test_config_tabs_returns_two_tabs(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert len(tabs) == 5

    def test_config_tabs_titles(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        titles = [t for t, _ in tabs]
        # Tab titles use an en-dash (\u2013) as the separator, matching the
        # implementation in TracePlugin.config_tabs() and DummyPlugin._plugin_config_tabs().
        assert titles == [
            "Dummy \u2013 Scan",
            "Dummy \u2013 Scan Type",
            "Dummy \u2013 Settings",
            "Dummy \u2013 About",
            "Dummy \u2013 General",
        ]

    def test_config_tabs_widgets_are_qwidgets(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        for _title, widget in plugin.config_tabs():
            assert isinstance(widget, QWidget)

    def test_monitor_widget_returns_none(self):
        plugin = DummyPlugin()
        assert plugin.monitor_widget() is None

    def test_configured_points_default(self):
        plugin = DummyPlugin()
        assert plugin.configured_points == 100

    def test_has_scan_generator(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator
        plugin = DummyPlugin()
        assert isinstance(plugin.scan_generator, SteppedScanGenerator)

    def test_scan_tab_is_first(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert "Scan" in tabs[0][0]
        assert "Type" not in tabs[0][0]

    def test_scan_tab_widget_is_qwidget(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert isinstance(tabs[0][1], QWidget)

    def test_scan_type_tab_is_second(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert "Scan Type" in tabs[1][0]

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        plugin = DummyPlugin()
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert isinstance(plugin.scan_generator, FunctionScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator
        plugin = DummyPlugin()
        gen_before = plugin.scan_generator
        plugin.set_scan_generator_class(SteppedScanGenerator)
        assert plugin.scan_generator is gen_before

    def test_scan_generator_changed_signal(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        plugin = DummyPlugin()
        received = []
        plugin.scan_generator_changed.connect(lambda: received.append(True))
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert len(received) == 1

    def test_plugin_config_tabs_returns_settings_and_about(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin._plugin_config_tabs()
        titles = [t for t, _ in tabs]
        assert titles == ["Dummy \u2013 Settings", "Dummy \u2013 About"]

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def test_connect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin.connect()
        assert plugin.status is TraceStatus.IDLE

    def test_configure_reads_widget_points(self, qapp):
        plugin = DummyPlugin()
        _ = plugin.config_widget()
        plugin._points_spin.setValue(42)
        plugin.configure()
        assert plugin.configured_points == 42

    def test_configure_no_widget_is_noop(self):
        plugin = DummyPlugin()
        plugin.configure()  # should not raise when widget not created

    def test_disconnect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin._set_status(TraceStatus.DATA_AVAILABLE)
        plugin.disconnect()
        assert plugin.status is TraceStatus.IDLE

    def test_measure_yields_data(self, qapp):
        plugin = DummyPlugin()
        pts = list(plugin.measure({"points": 5}))
        assert len(pts) == 5
        assert all(ch == "Dummy" for ch, _, _ in pts)

    def test_measure_status_data_available_after_completion(self, qapp):
        plugin = DummyPlugin()
        list(plugin.measure({"points": 3}))
        assert plugin.status is TraceStatus.DATA_AVAILABLE

    # ------------------------------------------------------------------
    # Trace detail properties
    # ------------------------------------------------------------------

    def test_num_traces(self, qapp):
        assert DummyPlugin().num_traces == 1

    def test_trace_title(self, qapp):
        assert DummyPlugin().trace_title == "Dummy"

    def test_x_units(self, qapp):
        assert DummyPlugin().x_units == ""

    def test_y_units(self, qapp):
        assert DummyPlugin().y_units == ""

    def test_trace_scan_is_scan_generator(self, qapp):
        plugin = DummyPlugin()
        assert plugin.trace_scan is plugin.scan_generator
