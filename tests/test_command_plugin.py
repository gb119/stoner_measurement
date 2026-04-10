"""Tests for CommandPlugin and SaveCommand."""

from __future__ import annotations

import json
import pathlib

import pytest

from stoner_measurement.plugins.command import CommandPlugin, SaveCommand


# ---------------------------------------------------------------------------
# Minimal concrete implementation used across tests
# ---------------------------------------------------------------------------


class _Noop(CommandPlugin):
    """CommandPlugin that does nothing."""

    executed: list[int]

    @property
    def name(self) -> str:
        return "Noop"

    def execute(self) -> None:
        try:
            self.executed.append(1)
        except AttributeError:
            self.executed = [1]


# ---------------------------------------------------------------------------
# CommandPlugin abstract contract
# ---------------------------------------------------------------------------


class TestCommandPlugin:
    def test_plugin_type(self, qapp):
        assert _Noop().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert _Noop().has_lifecycle is False

    def test_instance_name_defaults_to_name(self, qapp):
        assert _Noop().instance_name == "noop"

    def test_instance_name_changed_signal(self, qapp):
        p = _Noop()
        received: list[tuple[str, str]] = []
        p.instance_name_changed.connect(lambda o, n: received.append((o, n)))
        p.instance_name = "my_noop"
        assert received == [("noop", "my_noop")]

    def test_reported_traces_empty(self, qapp):
        assert _Noop().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert _Noop().reported_values() == {}

    def test_generate_action_code_execute_call(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    noop.execute()"

    def test_generate_action_code_blank_separator(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert lines[-1] == ""

    def test_generate_action_code_indentation(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(2, [], lambda s, i: [])
        assert lines[0].startswith("        ")

    def test_to_json_type_field(self, qapp):
        d = _Noop().to_json()
        assert d["type"] == "command"

    def test_to_json_class_field(self, qapp):
        d = _Noop().to_json()
        assert "class" in d

    def test_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = _Noop()
        p.instance_name = "my_noop"
        restored = BasePlugin.from_json(p.to_json())
        assert restored.instance_name == "my_noop"
        assert restored.plugin_type == "command"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(_Noop().config_widget(), QWidget)

    def test_config_tabs_has_general_tab(self, qapp):
        tabs = _Noop().config_tabs()
        tab_names = [t[0] for t in tabs]
        assert "General" in tab_names

    def test_execute_called_via_sequence(self, qapp, engine):
        """CommandPlugin.execute() is called when the sequence script runs."""
        import time

        from PyQt6.QtWidgets import QApplication

        p = _Noop()
        p.executed = []
        engine.add_plugin("noop", p)
        code = engine.generate_sequence_code(["noop"], {"noop": p})
        # Should NOT contain connect/configure/disconnect for command plugin
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code
        # Should contain execute()
        assert "noop.execute()" in code

    def test_no_lifecycle_in_generated_code(self, qapp, engine):
        p = _Noop()
        engine.add_plugin("noop", p)
        code = engine.generate_sequence_code(["noop"], {"noop": p})
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code


# ---------------------------------------------------------------------------
# SaveCommand
# ---------------------------------------------------------------------------


class TestSaveCommand:
    def test_name(self, qapp):
        assert SaveCommand().name == "Save"

    def test_plugin_type(self, qapp):
        assert SaveCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert SaveCommand().has_lifecycle is False

    def test_default_path_expr(self, qapp):
        assert SaveCommand().path_expr == "'data/output.json'"

    def test_to_json_includes_path_expr(self, qapp):
        cmd = SaveCommand()
        cmd.path_expr = "'my/path.json'"
        d = cmd.to_json()
        assert d["path_expr"] == "'my/path.json'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = SaveCommand()
        cmd.path_expr = "'run/output.json'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, SaveCommand)
        assert restored.path_expr == "'run/output.json'"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(SaveCommand().config_widget(), QWidget)

    def test_config_widget_updates_path_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert line_edits, "Config widget should have a QLineEdit"
        line_edits[0].setText("'new/path.json'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "'new/path.json'"

    def test_execute_writes_json_file(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.json"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "traces" in data
        assert "values" in data

    def test_execute_creates_parent_dirs(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "subdir" / "nested" / "out.json"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()
        assert out_file.exists()

    def test_execute_raises_when_detached(self, qapp):
        cmd = SaveCommand()
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_execute_raises_for_non_string_path(self, qapp, engine):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.path_expr = "42"  # evaluates to int, not str
        with pytest.raises(TypeError):
            cmd.execute()

    def test_generate_action_code(self, qapp):
        cmd = SaveCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    save.execute()"
