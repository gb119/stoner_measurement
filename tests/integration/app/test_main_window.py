"""Integration tests for the main UI window."""

from __future__ import annotations

from stoner_measurement.ui.main_window import MainWindow


class TestMainWindow:
    def test_creates_window(self, plugin_manager, managed_qt_widget):
        window = managed_qt_widget(MainWindow(plugin_manager=plugin_manager))
        assert window is not None

    def test_has_three_panels(self, plugin_manager, managed_qt_widget):
        window = managed_qt_widget(MainWindow(plugin_manager=plugin_manager))
        assert window.dock_panel is not None
        assert window.plot_widget is not None

    def test_close_closes_lifecycle_sensitive_children(
        self, plugin_manager, managed_qt_widget, monkeypatch
    ):
        window = managed_qt_widget(MainWindow(plugin_manager=plugin_manager))
        plot_closed = []
        script_tab_closed = []
        original_close = window.plot_widget.close
        original_script_tab_close = window.script_tab.close

        def close_plot():
            plot_closed.append(True)
            return original_close()

        def close_script_tab():
            script_tab_closed.append(True)
            return original_script_tab_close()

        monkeypatch.setattr(window.plot_widget, "close", close_plot)
        monkeypatch.setattr(window.script_tab, "close", close_script_tab)
        window.close()

        assert plot_closed == [True]
        assert script_tab_closed == [True]
