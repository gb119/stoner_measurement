"""Integration tests for the main UI window."""

from __future__ import annotations

from stoner_measurement.ui.main_window import MainWindow


class TestMainWindow:
    def test_creates_window(self, plugin_manager):
        window = MainWindow(plugin_manager=plugin_manager)
        assert window is not None

    def test_has_three_panels(self, plugin_manager):
        window = MainWindow(plugin_manager=plugin_manager)
        assert window.dock_panel is not None
        assert window.plot_widget is not None
