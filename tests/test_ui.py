"""Tests for the main UI components."""

from __future__ import annotations

import pytest

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


class TestPlotWidget:
    def test_creates_widget(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget is not None

    def test_initial_data_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.x_data == []
        assert widget.y_data == []

    def test_append_data(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_data(1.0, 2.0)
        assert widget.x_data == [1.0]
        assert widget.y_data == [2.0]

    def test_clear_data(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_data(1.0, 2.0)
        widget.clear_data()
        assert widget.x_data == []
        assert widget.y_data == []

    def test_pg_widget_exists(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.pg_widget is not None


class TestConfigPanel:
    def test_creates_widget(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_tabs_populated(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel.tabs.count() == 1
        assert panel.tabs.tabText(0) == "Dummy"

    def test_tabs_rebuild_on_plugin_change(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        assert panel.tabs.count() == 0

        pm.register("Dummy", DummyPlugin())
        assert panel.tabs.count() == 1


class TestMainWindow:
    def test_creates_window(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window is not None

    def test_has_three_panels(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window.dock_panel is not None
        assert window.plot_widget is not None
        assert window.config_panel is not None
