"""Tests for the base command plugin contract."""

from __future__ import annotations

from stoner_measurement.plugins.command import CommandPlugin


class _Noop(CommandPlugin):
    """Minimal concrete command plugin for base-contract tests."""

    executed: list[int]

    @property
    def name(self) -> str:
        return "Noop"

    def execute(self) -> None:
        try:
            self.executed.append(1)
        except AttributeError:
            self.executed = [1]


class TestCommandPlugin:
    def test_plugin_type(self, qapp):
        assert _Noop().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert _Noop().has_lifecycle is False

    def test_instance_name_defaults_to_name(self, qapp):
        assert _Noop().instance_name == "noop"

    def test_instance_name_changed_signal(self, qapp):
        plugin = _Noop()
        received: list[tuple[str, str]] = []
        plugin.instance_name_changed.connect(lambda old, new: received.append((old, new)))
        plugin.instance_name = "my_noop"
        assert received == [("noop", "my_noop")]

    def test_reported_traces_empty(self, qapp):
        assert _Noop().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert _Noop().reported_values() == {}

    def test_generate_action_code_execute_call(self, qapp):
        plugin = _Noop()
        lines = plugin.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    noop()"

    def test_call_delegates_to_execute(self, qapp):
        plugin = _Noop()
        plugin.executed = []
        plugin()
        assert plugin.executed == [1]

    def test_generate_action_code_blank_separator(self, qapp):
        plugin = _Noop()
        lines = plugin.generate_action_code(1, [], lambda source, indent: [])
        assert lines[-1] == ""

    def test_generate_action_code_indentation(self, qapp):
        plugin = _Noop()
        lines = plugin.generate_action_code(2, [], lambda source, indent: [])
        assert lines[0].startswith("        ")

    def test_to_json_type_field(self, qapp):
        data = _Noop().to_json()
        assert data["type"] == "command"

    def test_to_json_class_field(self, qapp):
        data = _Noop().to_json()
        assert "class" in data

    def test_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        plugin = _Noop()
        plugin.instance_name = "my_noop"
        restored = BasePlugin.from_json(plugin.to_json())
        assert restored.instance_name == "my_noop"
        assert restored.plugin_type == "command"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(_Noop().config_widget(), QWidget)

    def test_config_tabs_includes_config_and_about_tabs(self, qapp):
        tabs = _Noop().config_tabs()
        assert tabs[0][0] == "Noop"
        assert tabs[-1][0] == "Noop – About"

    def test_execute_called_via_sequence(self, qapp, engine):
        """CommandPlugin.execute() is called when the sequence script runs."""
        plugin = _Noop()
        plugin.executed = []
        engine.add_plugin("noop", plugin)
        code = engine.generate_sequence_code(["noop"], {"noop": plugin})
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code
        assert "noop()" in code

    def test_no_lifecycle_in_generated_code(self, qapp, engine):
        plugin = _Noop()
        engine.add_plugin("noop", plugin)
        code = engine.generate_sequence_code(["noop"], {"noop": plugin})
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
