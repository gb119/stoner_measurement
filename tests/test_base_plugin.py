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
        assert len(tabs) == 2
        title, widget = tabs[0]
        assert title == "Minimal"
        from PyQt6.QtWidgets import QWidget
        assert isinstance(widget, QWidget)

    def test_config_tabs_title_matches_name(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert tabs[0][0] == plugin.name

    def test_config_tabs_general_tab_is_last(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert tabs[-1][0] == "General"

    def test_monitor_widget_returns_none(self):
        plugin = _MinimalPlugin()
        assert plugin.monitor_widget() is None

    def test_monitor_widget_accepts_parent(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = _MinimalPlugin()
        parent = QWidget()
        assert plugin.monitor_widget(parent=parent) is None

    def test_sequence_engine_default_none(self):
        plugin = _MinimalPlugin()
        assert plugin.sequence_engine is None

    def test_engine_namespace_detached_returns_empty_dict(self):
        plugin = _MinimalPlugin()
        assert plugin.engine_namespace == {}


class TestBasePluginEval:
    """Tests for BasePlugin.eval()."""

    def test_eval_raises_when_detached(self):
        plugin = _MinimalPlugin()
        with pytest.raises(RuntimeError, match="not attached to a sequence engine"):
            plugin.eval("1 + 1")

    def test_eval_raises_syntax_error(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        with pytest.raises(SyntaxError):
            plugin.eval("def")
        engine.shutdown()

    def test_eval_raises_exception_from_expression(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        with pytest.raises(ZeroDivisionError):
            plugin.eval("1/0")
        engine.shutdown()

    def test_eval_simple_arithmetic(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        assert plugin.eval("1 + 1") == 2
        engine.shutdown()

    def test_eval_with_engine_namespace(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        engine._namespace["_x"] = 7
        assert plugin.eval("_x * 6") == 42
        engine.shutdown()

    def test_eval_numpy_sin_with_engine(self, qapp):
        import numpy as np
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        result = plugin.eval("sin(0.0)")
        assert abs(result - np.sin(0.0)) < 1e-12
        engine.shutdown()

    def test_eval_numpy_sqrt_with_engine(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        result = plugin.eval("sqrt(9.0)")
        assert abs(result - 3.0) < 1e-12
        engine.shutdown()

