"""Tests for the PluginManager."""

from __future__ import annotations

import pytest

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.plugins.dummy import DummyPlugin


class TestPluginManager:
    def test_initially_empty(self, qapp):
        pm = PluginManager()
        assert pm.plugins == {}
        assert pm.plugin_names == []

    def test_register_plugin(self, qapp):
        pm = PluginManager()
        plugin = DummyPlugin()
        pm.register("Dummy", plugin)
        assert "Dummy" in pm.plugins
        assert pm.get("Dummy") is plugin

    def test_plugin_names_sorted(self, qapp):
        pm = PluginManager()
        pm.register("Zebra", DummyPlugin())
        pm.register("Alpha", DummyPlugin())
        assert pm.plugin_names == ["Alpha", "Zebra"]

    def test_unregister_plugin(self, qapp):
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        pm.unregister("Dummy")
        assert "Dummy" not in pm.plugins

    def test_unregister_nonexistent(self, qapp):
        pm = PluginManager()
        # Should not raise
        pm.unregister("nonexistent")

    def test_get_missing_returns_none(self, qapp):
        pm = PluginManager()
        assert pm.get("missing") is None

    def test_plugins_changed_signal_on_register(self, qapp):
        pm = PluginManager()
        emitted = []
        pm.plugins_changed.connect(lambda: emitted.append(True))
        pm.register("Dummy", DummyPlugin())
        assert len(emitted) == 1

    def test_plugins_changed_signal_on_unregister(self, qapp):
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        emitted = []
        pm.plugins_changed.connect(lambda: emitted.append(True))
        pm.unregister("Dummy")
        assert len(emitted) == 1

    def test_discover_loads_entry_points(self, qapp):
        """After discover(), the built-in 'dummy' entry-point should be loaded."""
        pm = PluginManager()
        pm.discover()
        # The package registers 'dummy' via pyproject.toml entry-points
        assert "dummy" in pm.plugins
