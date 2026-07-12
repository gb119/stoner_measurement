"""Tests for ConfigPanel."""

from __future__ import annotations

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
        assert panel.tabs.tabText(0) == "Dummy \u2013 Scan"
        assert panel.tabs.tabText(1) == "Dummy \u2013 Settings"
        assert panel.tabs.tabText(2) == "Dummy \u2013 About"

    def test_show_plugin_none_clears_tabs(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        panel.show_plugin(None)
        assert panel.tabs.count() == 0

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
