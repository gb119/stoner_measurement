"""Tests for StatusCommand."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.command import StatusCommand


class TestStatusCommand:
    def test_name(self, qapp):
        assert StatusCommand().name == "Status"

    def test_plugin_type(self, qapp):
        assert StatusCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert StatusCommand().has_lifecycle is False

    def test_default_status_expr(self, qapp):
        assert StatusCommand().status_expr == "'Ready'"

    def test_to_json_includes_status_expr(self, qapp):
        command = StatusCommand()
        command.status_expr = "'Running step 1'"
        data = command.to_json()
        assert data["status_expr"] == "'Running step 1'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        command = StatusCommand()
        command.status_expr = "'Done'"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, StatusCommand)
        assert restored.status_expr == "'Done'"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(StatusCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        widget = StatusCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) >= 1

    def test_config_widget_updates_status_expr(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        command = StatusCommand()
        widget = command.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("'new status'")
        edit.editingFinished.emit()
        assert command.status_expr == "'new status'"

    def test_execute_with_explicit_status_emits_signal(self, qapp):
        command = StatusCommand()
        received: list[str] = []
        command.status_message.connect(received.append)
        command.execute(status="hello")
        assert received == ["hello"]

    def test_call_with_explicit_status_emits_signal(self, qapp):
        command = StatusCommand()
        received: list[str] = []
        command.status_message.connect(received.append)
        command(status="world")
        assert received == ["world"]

    def test_execute_uses_status_expr_when_attached(self, qapp, engine):
        command = StatusCommand()
        command.status_expr = "'engine ready'"
        engine.add_plugin("status", command)
        received: list[str] = []
        command.status_message.connect(received.append)
        command.execute()
        assert received == ["engine ready"]

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        command = StatusCommand()
        with pytest.raises(RuntimeError):
            command.execute()

    def test_status_message_forwarded_to_engine_status_changed(self, qapp, engine):
        command = StatusCommand()
        engine.add_plugin("status", command)
        engine_statuses: list[str] = []
        engine.status_changed.connect(engine_statuses.append)
        command.execute(status="custom message")
        assert "custom message" in engine_statuses

    def test_sequence_engine_property_none_initially(self, qapp):
        assert StatusCommand().sequence_engine is None

    def test_sequence_engine_set_via_add_plugin(self, qapp, engine):
        command = StatusCommand()
        engine.add_plugin("status", command)
        assert command.sequence_engine is engine

    def test_sequence_engine_cleared_via_remove_plugin(self, qapp, engine):
        command = StatusCommand()
        engine.add_plugin("status", command)
        engine.remove_plugin("status")
        assert command.sequence_engine is None

    def test_generate_action_code(self, qapp):
        command = StatusCommand()
        lines = command.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    status()"

    def test_reported_traces_empty(self, qapp):
        assert StatusCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert StatusCommand().reported_values() == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
