"""Tests for the DummyPlugin."""

from __future__ import annotations

import math

from stoner_measurement.plugins.dummy import DummyPlugin
from stoner_measurement.plugins.trace import TraceStatus
from stoner_measurement.scan import SteppedScanGenerator


def _make_scan(plugin, end=0.4, step=0.1):
    """Return a SteppedScanGenerator with one stage and assign it to *plugin*."""
    gen = SteppedScanGenerator(
        start=0.0, stages=[(end, step, True)], parent=plugin
    )
    plugin.scan_generator = gen
    return gen


class TestDummyPlugin:
    def test_name(self):
        plugin = DummyPlugin()
        assert plugin.name == "Dummy"

    def test_execute_uses_scan_generator(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)  # 5 points: 0.0…0.4
        data = list(plugin.execute({}))
        assert len(data) == 5

    def test_execute_empty_scan_yields_start_point(self, qapp):
        plugin = DummyPlugin()
        # Default scan generator has no stages but still yields the start point (0.0)
        data = list(plugin.execute({}))
        assert len(data) == 1
        assert data[0][0] == 0.0  # start point

    def test_execute_only_measured_points_yielded(self, qapp):
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(0.2, 0.1, False), (0.4, 0.1, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({}))
        xs = [x for x, _ in data]
        # Positioning stage (0.0→0.2) not measured; measuring stage (0.2→0.4) is
        assert all(x > 0.19 for x in xs)

    def test_execute_yields_tuples(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        data = list(plugin.execute({}))
        for item in data:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_execute_amplitude(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        data = list(plugin.execute({"amplitude": 2.0}))
        for _x, y in data:
            assert abs(y) <= 2.0 + 1e-9

    def test_execute_sine_values(self, qapp):
        plugin = DummyPlugin()
        # x = 0, π/2, π  → sin values: 0, 1, ≈0
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(math.pi, math.pi / 2, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({}))
        assert len(data) == 3
        assert abs(data[0][1]) < 1e-9  # sin(0) = 0
        assert abs(data[1][1] - 1.0) < 1e-9  # sin(π/2) = 1
        assert abs(data[-1][1]) < 1e-9  # sin(π) ≈ 0

    def test_config_tabs_returns_three_tabs(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert len(tabs) == 3

    def test_config_tabs_titles(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        titles = [t for t, _ in tabs]
        assert titles == [
            "Dummy \u2013 Scan",
            "Dummy \u2013 Settings",
            "Dummy \u2013 About",
        ]

    def test_config_tabs_widgets_are_qwidgets(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        for _title, widget in plugin.config_tabs():
            assert isinstance(widget, QWidget)

    def test_config_tabs_caches_widgets(self, qapp):
        """Subsequent calls to config_tabs() return the same widget instances."""
        plugin = DummyPlugin()
        tabs1 = plugin.config_tabs()
        tabs2 = plugin.config_tabs()
        for (t1, w1), (t2, w2) in zip(tabs1, tabs2):
            assert t1 == t2
            assert w1 is w2

    def test_monitor_widget_returns_none(self):
        plugin = DummyPlugin()
        assert plugin.monitor_widget() is None

    def test_has_scan_generator(self, qapp):
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

    def test_about_tab_is_third(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert "About" in tabs[2][0]

    def test_about_html_returns_string(self, qapp):
        plugin = DummyPlugin()
        html = plugin._about_html()
        assert isinstance(html, str)
        assert "<h3>" in html

    def test_plugin_config_tabs_returns_none(self, qapp):
        plugin = DummyPlugin()
        assert plugin._plugin_config_tabs() is None

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        plugin = DummyPlugin()
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert isinstance(plugin.scan_generator, FunctionScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
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

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def test_connect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin.connect()
        assert plugin.status is TraceStatus.IDLE

    def test_configure_is_noop(self, qapp):
        plugin = DummyPlugin()
        plugin.configure()  # should not raise

    def test_disconnect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin._set_status(TraceStatus.DATA_AVAILABLE)
        plugin.disconnect()
        assert plugin.status is TraceStatus.IDLE

    def test_measure_yields_data(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        pts = list(plugin.measure({}))
        assert len(pts) == 5
        assert all(ch == "Dummy" for ch, _, _ in pts)

    def test_measure_status_data_available_after_completion(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.2, step=0.1)
        list(plugin.measure({}))
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
