"""Tests for the main UI components."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.plugins.dummy import DummyPlugin
from stoner_measurement.ui.config_panel import ConfigPanel
from stoner_measurement.ui.dock_panel import DockPanel
from stoner_measurement.ui.main_window import MainWindow
from stoner_measurement.ui.plot_widget import PlotWidget


class TestDockPanel:
    def test_creates_widget(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_instrument_list_populated(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel._instrument_list.count() == 1
        assert panel._instrument_list.item(0).text() == "Dummy"

    def test_sequence_steps_empty_initially(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel.sequence_steps == []

    def test_add_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        assert panel.sequence_steps == ["Dummy"]

    def test_remove_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._sequence_list.setCurrentRow(0)
        panel._remove_step()
        assert panel.sequence_steps == []

    def test_refresh_on_plugin_registration(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert panel._instrument_list.count() == 0

        pm.register("Dummy", DummyPlugin())
        assert panel._instrument_list.count() == 1

    # --- Monitoring widget tests ---

    def test_monitor_widgets_empty_initially(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert panel.monitor_widgets == {}

    def test_add_monitor_widget(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl = QLabel("Status: OK")
        panel.add_monitor_widget("test_plugin", lbl)
        assert "test_plugin" in panel.monitor_widgets

    def test_add_monitor_widget_duplicate_noop(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl1 = QLabel("First")
        lbl2 = QLabel("Second")
        panel.add_monitor_widget("p", lbl1)
        panel.add_monitor_widget("p", lbl2)  # should be ignored
        assert panel.monitor_widgets["p"] is lbl1

    def test_remove_monitor_widget(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl = QLabel("Status")
        panel.add_monitor_widget("p", lbl)
        panel.remove_monitor_widget("p")
        assert "p" not in panel.monitor_widgets

    def test_remove_monitor_widget_missing_noop(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        panel.remove_monitor_widget("nonexistent")  # should not raise

    def test_monitoring_section_hidden_when_empty(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert not panel._monitor_label.isVisible()
        assert not panel._monitor_container.isVisible()

    def test_monitoring_section_visible_when_widget_added(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        panel.add_monitor_widget("p", QLabel("Status"))
        # isVisible() is False when the parent panel hasn't been shown, so
        # use isHidden() to confirm the widget was not explicitly hidden.
        assert not panel._monitor_label.isHidden()
        assert not panel._monitor_container.isHidden()

    def test_monitor_widget_removed_on_plugin_unregister(self, qapp):
        """A plugin that provides a monitor_widget should have it removed when unregistered."""

        class _MonitorPlugin(DummyPlugin):
            @property
            def name(self) -> str:
                return "MonitorPlugin"

            def monitor_widget(self, parent=None):
                return QLabel("Live reading", parent)

        pm = PluginManager()
        pm.register("MonitorPlugin", _MonitorPlugin())
        panel = DockPanel(plugin_manager=pm)
        assert "MonitorPlugin" in panel.monitor_widgets

        pm.unregister("MonitorPlugin")
        assert "MonitorPlugin" not in panel.monitor_widgets


class TestPlotWidget:
    def test_creates_widget(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget is not None

    def test_initial_data_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.x_data() == []
        assert widget.y_data() == []

    def test_append_point(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 1.0, 2.0)
        assert widget.x_data("sig") == [1.0]
        assert widget.y_data("sig") == [2.0]

    def test_append_point_multiple_traces(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("a", 1.0, 10.0)
        widget.append_point("b", 2.0, 20.0)
        assert widget.x_data("a") == [1.0]
        assert widget.x_data("b") == [2.0]
        assert sorted(widget.trace_names) == ["a", "b"]

    def test_set_trace(self, runner):
        widget = PlotWidget(runner=runner)
        widget.set_trace("sig", [0.0, 1.0, 2.0], [3.0, 4.0, 5.0])
        assert widget.x_data("sig") == [0.0, 1.0, 2.0]
        assert widget.y_data("sig") == [3.0, 4.0, 5.0]

    def test_set_trace_replaces_data(self, runner):
        widget = PlotWidget(runner=runner)
        widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
        widget.set_trace("sig", [10.0], [20.0])
        assert widget.x_data("sig") == [10.0]
        assert widget.y_data("sig") == [20.0]

    def test_remove_trace(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 1.0, 2.0)
        widget.remove_trace("sig")
        assert "sig" not in widget.trace_names
        assert widget.x_data("sig") == []

    def test_remove_trace_missing_noop(self, runner):
        widget = PlotWidget(runner=runner)
        widget.remove_trace("nonexistent")  # should not raise

    def test_clear_all(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget.trace_names == []

    def test_clear_data_deprecated(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("default", 1.0, 2.0)
        with pytest.warns(DeprecationWarning):
            widget.clear_data()
        assert widget.trace_names == []

    def test_append_data_deprecated(self, runner):
        widget = PlotWidget(runner=runner)
        with pytest.warns(DeprecationWarning):
            widget.append_data(1.0, 2.0)
        assert widget.x_data("default") == [1.0]

    def test_pg_widget_exists(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.pg_widget is not None

    def test_default_axis_names(self, runner):
        widget = PlotWidget(runner=runner)
        assert "left" in widget.axis_names
        assert "bottom" in widget.axis_names

    def test_add_y_axis(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temperature", "Temperature (K)", side="right")
        assert "temperature" in widget.axis_names

    def test_add_y_axis_duplicate_noop(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temp", "Temp", side="right")
        widget.add_y_axis("temp", "Other", side="right")  # should not raise
        assert widget.axis_names.count("temp") == 1

    def test_add_x_axis(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_x_axis("freq", "Frequency (Hz)", position="top")
        assert "freq" in widget.axis_names

    def test_assign_trace_axes(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 300.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")

    def test_assign_trace_axes_unknown_trace_raises(self, runner):
        widget = PlotWidget(runner=runner)
        with pytest.raises(KeyError, match="unknown"):
            widget.assign_trace_axes("unknown", y_axis="left")

    def test_assign_trace_axes_unknown_axis_raises(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such"):
            widget.assign_trace_axes("sig", y_axis="no_such")

    def test_x_data_unknown_trace_returns_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.x_data("nonexistent") == []

    def test_y_data_unknown_trace_returns_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.y_data("nonexistent") == []


class TestConfigPanel:
    def test_creates_widget(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_tabs_populated(self, plugin_manager):
        """DummyPlugin contributes 4 tabs (Scan + Scan Type + Settings + About)."""
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel.tabs.count() == 4
        assert panel.tabs.tabText(0) == "Dummy \u2013 Scan"
        assert panel.tabs.tabText(1) == "Dummy \u2013 Scan Type"
        assert panel.tabs.tabText(2) == "Dummy \u2013 Settings"
        assert panel.tabs.tabText(3) == "Dummy \u2013 About"

    def test_tabs_added_on_plugin_registration(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        assert panel.tabs.count() == 0

        pm.register("Dummy", DummyPlugin())
        assert panel.tabs.count() == 4

    def test_tabs_removed_on_plugin_unregistration(self, qapp):
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = ConfigPanel(plugin_manager=pm)
        assert panel.tabs.count() == 4

        pm.unregister("Dummy")
        assert panel.tabs.count() == 0

    def test_tabs_preserved_for_existing_plugin(self, qapp):
        """Tabs for already-registered plugins are not re-created on sync."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = ConfigPanel(plugin_manager=pm)
        first_widget = panel.tabs.widget(0)

        pm.register("Other", DummyPlugin())  # triggers plugins_changed
        # The original Dummy tab widget should be the same object
        assert panel.tabs.widget(0) is first_widget

    def test_add_plugin_tabs_duplicate_noop(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        plugin = DummyPlugin()
        panel.add_plugin_tabs(plugin)
        panel.add_plugin_tabs(plugin)  # second call should be ignored
        assert panel.tabs.count() == 4

    def test_remove_plugin_tabs_missing_noop(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        panel.remove_plugin_tabs("nonexistent")  # should not raise


class TestMainWindow:
    def test_creates_window(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window is not None

    def test_has_three_panels(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window.dock_panel is not None
        assert window.plot_widget is not None
        assert window.config_panel is not None
