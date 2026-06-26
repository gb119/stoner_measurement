"""Tests for AlertCommand."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from stoner_measurement.plugins.command import AlertCommand


class TestAlertCommand:
    def test_name(self, qapp):
        assert AlertCommand().name == "Alert"

    def test_plugin_type(self, qapp):
        assert AlertCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert AlertCommand().has_lifecycle is False

    def test_default_message_expr(self, qapp):
        assert AlertCommand().message_expr == "'Alert'"

    def test_to_json_includes_message_expr(self, qapp):
        command = AlertCommand()
        command.message_expr = "'Check instrument'"
        data = command.to_json()
        assert data["message_expr"] == "'Check instrument'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        command = AlertCommand()
        command.message_expr = "'Step complete'"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, AlertCommand)
        assert restored.message_expr == "'Step complete'"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(AlertCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        widget = AlertCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) >= 1

    def test_config_widget_updates_message_expr(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        command = AlertCommand()
        widget = command.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("'new message'")
        edit.editingFinished.emit()
        assert command.message_expr == "'new message'"

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        command = AlertCommand()
        with pytest.raises(RuntimeError):
            command.execute()

    def test_execute_with_explicit_message_emits_signal(self, qapp):
        """execute(message=...) emits show_alert with the provided message."""
        command = AlertCommand()
        received: list[str] = []
        command.show_alert.disconnect(command._display_alert)
        command.show_alert.connect(received.append)

        with patch.object(command, "_display_alert", lambda message: None):
            command.execute(message="test msg")

        assert received == ["test msg"]

    def test_call_with_explicit_message_emits_signal(self, qapp):
        """__call__(message=...) delegates to execute(message=...)."""
        command = AlertCommand()
        received: list[str] = []
        command.show_alert.disconnect(command._display_alert)
        command.show_alert.connect(received.append)

        command(message="call test")
        assert received == ["call test"]

    def test_execute_uses_message_expr_when_attached(self, qapp, engine):
        command = AlertCommand()
        command.message_expr = "'engine alert'"
        engine.add_plugin("alert", command)
        received: list[str] = []
        command.show_alert.disconnect(command._display_alert)
        command.show_alert.connect(received.append)

        command.execute()
        assert received == ["engine alert"]

    def test_generate_action_code(self, qapp):
        command = AlertCommand()
        lines = command.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    alert()"

    def test_reported_traces_empty(self, qapp):
        assert AlertCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert AlertCommand().reported_values() == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
