"""Tests for BasePlugin default method implementations."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin


class _MinimalPlugin(BasePlugin):
    """Concrete minimal plugin used only for testing BasePlugin defaults."""

    @property
    def name(self) -> str:
        return "Minimal"


class TestBasePluginDefaults:
    def test_config_widget_returns_label(self, qapp):
        plugin = _MinimalPlugin()
        from PyQt6.QtWidgets import QLabel
        widget = plugin.config_widget()
        assert isinstance(widget, QLabel)
        assert "Minimal" in widget.text()

    def test_config_tabs_wraps_config_widget(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert isinstance(tabs, list)
        assert len(tabs) == 1
        title, widget = tabs[0]
        assert title == "Minimal"
        from PyQt6.QtWidgets import QWidget
        assert isinstance(widget, QWidget)

    def test_config_tabs_title_matches_name(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert tabs[0][0] == plugin.name

    def test_monitor_widget_returns_none(self):
        plugin = _MinimalPlugin()
        assert plugin.monitor_widget() is None

    def test_monitor_widget_accepts_parent(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = _MinimalPlugin()
        parent = QWidget()
        assert plugin.monitor_widget(parent=parent) is None
