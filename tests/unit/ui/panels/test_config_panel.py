"""Tests for ConfigPanel."""

from __future__ import annotations

from qtpy.QtWidgets import QTabBar

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.ui.config_panel import ConfigPanel


class TestConfigPanel:
    def test_creates_widget(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_tabs_empty_initially(self, qapp):
        """No tabs shown until show_plugin() is called."""
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        assert panel.tabs.count() == 0

    def test_show_plugin_displays_tabs(self, plugin_manager):
        """show_plugin() populates the tab widget with the plugin's tabs."""
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        assert panel.tabs.count() == 3
        assert panel.tabs.tabText(0) == "Scan"
        assert panel.tabs.tabText(1) == "Settings"
        assert panel.tabs.tabText(2) == "About"

    def test_show_plugin_none_clears_tabs(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        panel.show_plugin(None)
        assert panel.tabs.count() == 0

    def test_show_plugin_none_detaches_cached_pages(self, plugin_manager):
        """Removed pages must not remain in the tab widget's internal stack."""
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        pages = [panel.tabs.widget(index) for index in range(panel.tabs.count())]

        panel.show_plugin(None)

        assert all(page.parent() is None for page in pages)
        assert all(page.isHidden() for page in pages)

    def test_show_plugin_replaces_previous_plugin_tabs(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        plugin_a = DummyPlugin()
        plugin_b = DummyPlugin()
        panel.show_plugin(plugin_a)
        first_count = panel.tabs.count()
        panel.show_plugin(plugin_b)
        assert panel.tabs.count() == first_count  # same type, same count
        # Widgets belong to plugin_b (different cache)
        assert panel.tabs.widget(0) is plugin_b.config_tabs()[0][1]

    def test_show_plugin_caches_widgets(self, qapp):
        """Tabs are cached on the plugin; re-showing reuses the same widgets."""
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        first_widget = panel.tabs.widget(0)
        panel.show_plugin(None)
        panel.show_plugin(plugin)
        assert panel.tabs.widget(0) is first_widget
        assert first_widget.parent() is not None

    def test_sync_clears_tabs_on_plugin_removal(self, qapp):
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = ConfigPanel(plugin_manager=pm)
        plugin = pm.plugins["Dummy"]
        panel.show_plugin(plugin)
        assert panel.tabs.count() == 3

        pm.unregister("Dummy")
        assert panel.tabs.count() == 0

    def test_sync_leaves_other_plugin_intact(self, qapp):
        """Removing an unrelated plugin does not clear the current plugin's tabs."""
        pm = PluginManager()
        plugin_a = DummyPlugin()
        plugin_b = DummyPlugin()
        pm.register("A", plugin_a)
        pm.register("B", plugin_b)
        panel = ConfigPanel(plugin_manager=pm)
        panel.show_plugin(plugin_a)
        assert panel.tabs.count() == 3

        pm.unregister("B")
        assert panel.tabs.count() == 3  # plugin_a tabs unaffected

    def test_show_placeholder(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        panel.show_placeholder()
        assert panel.tabs.count() == 1

    def test_collapse_shows_vertical_tab_strip(self, plugin_manager, managed_qt_widget):
        """Collapsing uses right-facing vertical labels in top-to-bottom order."""
        panel = managed_qt_widget(ConfigPanel(plugin_manager=plugin_manager))
        panel.show_plugin(DummyPlugin())

        panel.collapse_button.click()

        assert panel.is_collapsed
        assert panel.tabs.isHidden()
        assert panel.collapsed_tabs.isVisibleTo(panel)
        assert panel.collapsed_tabs.shape() == QTabBar.Shape.RoundedEast
        assert [
            panel.collapsed_tabs.tabText(index) for index in range(panel.collapsed_tabs.count())
        ] == ["Scan", "Settings", "About"]

    def test_chevrons_are_bold_and_fifty_percent_larger(
        self, plugin_manager, managed_qt_widget
    ):
        panel = managed_qt_widget(ConfigPanel(plugin_manager=plugin_manager))
        normal_size = panel.font().pointSizeF()

        for button in (panel.collapse_button, panel.expand_button):
            assert button.font().bold()
            assert button.font().pointSizeF() == normal_size * 1.5

    def test_changing_plugin_preserves_collapsed_state(self, plugin_manager, managed_qt_widget):
        """Selecting another sequence step must not expand the config pages."""
        panel = managed_qt_widget(ConfigPanel(plugin_manager=plugin_manager))
        panel.show_plugin(DummyPlugin())
        panel.set_collapsed(True)

        panel.show_plugin(DummyPlugin())

        assert panel.is_collapsed
        assert panel.tabs.isHidden()
        assert panel.collapsed_tabs.count() == panel.tabs.count()

    def test_expand_button_restores_previous_tab(self, plugin_manager, managed_qt_widget):
        panel = managed_qt_widget(ConfigPanel(plugin_manager=plugin_manager))
        panel.show_plugin(DummyPlugin())
        panel.tabs.setCurrentIndex(2)
        panel.set_collapsed(True)

        panel.expand_button.click()

        assert not panel.is_collapsed
        assert panel.tabs.currentIndex() == 2

    def test_collapsed_tab_expands_and_focuses_clicked_page(
        self, plugin_manager, managed_qt_widget
    ):
        panel = managed_qt_widget(ConfigPanel(plugin_manager=plugin_manager))
        panel.show_plugin(DummyPlugin())
        panel.set_collapsed(True)

        panel.collapsed_tabs.tabBarClicked.emit(1)

        assert not panel.is_collapsed
        assert panel.tabs.currentIndex() == 1


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
