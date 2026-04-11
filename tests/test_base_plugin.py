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

    def test_eval_does_not_pollute_namespace_with_print(self, qapp):
        """eval() must not permanently overwrite 'print' in the engine namespace.

        asteval.Interpreter.__init__ unconditionally injects its own ``_printer``
        into the supplied symtable.  Without the save/restore guard in
        ``BasePlugin.eval()``, all subsequent ``print()`` calls in the engine
        namespace would use asteval's writer (the terminal) instead of the
        redirected ``sys.stdout``.
        """

        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)

        assert "print" not in engine.namespace, "namespace should not have 'print' before eval"
        plugin.eval("1 + 1")
        assert "print" not in engine.namespace, "eval() must not leave 'print' in the namespace"

        engine.shutdown()

    def test_eval_preserves_user_defined_print_in_namespace(self, qapp):
        """eval() must restore a user-set 'print' after asteval overwrites it."""
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)

        custom_print = lambda *a, **kw: None  # noqa: E731
        # Use the live namespace dict (engine.namespace returns a copy).
        plugin.engine_namespace["print"] = custom_print

        plugin.eval("1 + 1")

        assert plugin.engine_namespace.get("print") is custom_print, (
            "eval() must restore a pre-existing 'print' to the namespace"
        )

        engine.shutdown()


class TestGenerateInstantiationCode:
    def test_returns_list_of_strings(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_guard_uses_instance_name(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert lines[0] == "if 'minimal' not in globals():"

    def test_guard_uses_custom_instance_name(self):
        plugin = _MinimalPlugin()
        plugin.instance_name = "my_plugin"
        lines = plugin.generate_instantiation_code()
        assert lines[0] == "if 'my_plugin' not in globals():"

    def test_reconstruction_uses_base_plugin_from_json(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert "_BasePlugin.from_json" in lines[1]

    def test_reconstruction_uses_json_loads(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert "_json.loads" in lines[1]

    def test_json_payload_contains_class_path(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        cls = type(plugin)
        expected_class = f"{cls.__module__}:{cls.__qualname__}"
        assert expected_class in lines[1]

    def test_json_payload_contains_instance_name(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert '"minimal"' in lines[1]

    def test_ends_with_blank_separator(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert lines[-1] == ""

